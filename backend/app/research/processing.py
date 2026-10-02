"""Source processing: turn engine candidates into trustworthy, ranked, de-duplicated results.

For every candidate, in order:
1. Grounding: its URLs must be among the pages the engine actually read. Anything else is
   treated as invented and dropped.
2. Faith guard: without faith opt-in, faith-specific groups and events are removed.
3. Freshness: events that are already over are removed.
4. Classification: the primary source gets a label from domain rules (official,
   organization, community, general web).
5. Claim honesty: "law" and "official guidance" need an official government source. If a
   cited official page exists it becomes the primary source; otherwise the claim is
   dropped. Live search synthesis is guidance, never a reviewed official rule.
6. Contacts: phone, email and address are kept only if found on the cited page. A website
   is kept only if it belongs to a cited source's domain.
7. Score (internal), merge duplicates, rank and cap.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime

from app.adapters.web_fetch import PageFetcher
from app.domain.enums import EvidenceKind
from app.domain.provenance import Citation, Provenance
from app.research.profile import ResearchProfile, mentions_faith
from app.research.sources import (
    canonicalize_url,
    classify_source,
    dedupe_key,
    quality_score,
    registrable_domain,
    same_result,
    source_domain,
)
from app.research.types import (
    FAITH_GUARDED_CATEGORIES,
    Candidate,
    CategoryFindings,
    ClaimedSourceType,
    ContactCandidate,
    ContactKind,
    ProcessedCitation,
    ProcessedResult,
    ResearchMode,
    SourceLabel,
    SourceRef,
    VerifiedContact,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_CATEGORY = 6
OFFICIAL_KINDS = frozenset({EvidenceKind.AUTHORITATIVE_REQUIREMENT, EvidenceKind.OFFICIAL_GUIDANCE})


# --- contact verification ----------------------------------------------------------------

_PHONE_TOKEN = re.compile(r"\+?\d[\d\s().\-]{5,}\d")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def phone_on_page(phone: str, page_text: str) -> bool:
    """Match on the last 8 digits, so +971 2 123 4567 and 02 123 4567 are the same."""
    wanted = _digits(phone)
    if len(wanted) < 7:
        return False
    tail = wanted[-8:]
    return any(_digits(token).endswith(tail) for token in _PHONE_TOKEN.findall(page_text))


def email_on_page(email: str, page_text: str) -> bool:
    value = email.strip().lower()
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", value)) and value in page_text.lower()


def _loose(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def address_on_page(address: str, page_text: str) -> bool:
    wanted = _loose(address)
    return len(wanted) >= 8 and wanted in _loose(page_text)


class ContactVerifier:
    """Checks contact details against the page they're attributed to. Pages are fetched at
    most once per job."""

    def __init__(self, fetcher: PageFetcher) -> None:
        self._fetcher = fetcher
        self._pages: dict[str, str | None] = {}

    async def _page_text(self, url: str) -> str | None:
        key = canonicalize_url(url) or url
        if key not in self._pages:
            page = await self._fetcher.fetch_text(url)
            self._pages[key] = (
                page.text
                if page and registrable_domain(page.final_url) == registrable_domain(url)
                else None
            )
        return self._pages[key]

    async def verify(
        self, contacts: Sequence[ContactCandidate], grounded: dict[str, SourceRef], now: datetime
    ) -> list[VerifiedContact]:
        cited_domains = {registrable_domain(ref.url) for ref in grounded.values()}
        verified: list[VerifiedContact] = []
        seen: set[tuple[ContactKind, str]] = set()
        for contact in contacts:
            value = " ".join(contact.value.split())[:300]
            source_key = canonicalize_url(contact.source_url)
            if not value or source_key not in grounded:
                continue  # the page it's attributed to was never read
            source_url = grounded[source_key].url
            ok = False
            if contact.kind is ContactKind.WEBSITE:
                canonical = canonicalize_url(value)
                ok = canonical is not None and registrable_domain(canonical) in cited_domains
                value = canonical or value
            else:
                text = await self._page_text(source_url)
                if text:
                    ok = {
                        ContactKind.PHONE: phone_on_page,
                        ContactKind.EMAIL: email_on_page,
                        ContactKind.ADDRESS: address_on_page,
                    }[contact.kind](value, text)
            if ok and (contact.kind, value.casefold()) not in seen:
                seen.add((contact.kind, value.casefold()))
                verified.append(VerifiedContact(contact.kind, value, source_url, now))
        return verified


# --- processing ----------------------------------------------------------------------------


def _citation(
    ref: SourceRef, canonical: str, *, primary: bool, claimed: ClaimedSourceType | None
) -> ProcessedCitation:
    return ProcessedCitation(
        url=ref.url,
        canonical_url=canonical,
        title=(ref.title or source_domain(ref.url))[:500],
        source_domain=source_domain(ref.url),
        source_label=classify_source(ref.url, claimed if primary else None),
        retrieved_at=ref.retrieved_at,
        summary=ref.summary,
        is_primary=primary,
    )


def _event_is_over(candidate: Candidate, today: date) -> bool:
    last_day = candidate.event_ends_on or candidate.event_starts_on
    return last_day is not None and last_day < today


PERSONAL_MATCH_BONUS = 0.08


def rank(result: ProcessedResult) -> float:
    """Display order: source quality, plus a small bonus per stated fact the result matches,
    so a personal match outranks an equally good generic result. The quality score itself
    stays a pure source-type x freshness measure."""
    return result.quality_score + PERSONAL_MATCH_BONUS * min(3, len(result.fact_keys))


class SourceProcessor:
    def __init__(
        self, verifier: ContactVerifier, *, max_results: int = MAX_RESULTS_PER_CATEGORY
    ) -> None:
        self._verifier = verifier
        self._max = max_results

    async def process(
        self, findings: CategoryFindings, profile: ResearchProfile, now: datetime
    ) -> list[ProcessedResult]:
        processed: list[ProcessedResult] = []
        for candidate in findings.candidates:
            result = await self._one(candidate, findings.sources, profile, now, mode=findings.mode)
            if result is not None:
                processed.append(result)
        merged = self._dedupe(processed)
        # Stable sort: ties keep the engine's own order (most useful first).
        merged.sort(key=lambda r: -rank(r))
        return merged[: self._max]

    async def _one(
        self,
        candidate: Candidate,
        sources: dict[str, SourceRef],
        profile: ResearchProfile,
        now: datetime,
        *,
        mode: ResearchMode,
    ) -> ProcessedResult | None:
        notes: list[str] = []

        # 1. grounding
        grounded_keys: list[str] = []
        for url in [candidate.primary_url, *candidate.source_urls]:
            key = canonicalize_url(url)
            if key and key in sources and key not in grounded_keys:
                grounded_keys.append(key)
        if not grounded_keys:
            logger.info("research_candidate_ungrounded", extra={"category": candidate.category})
            return None
        if any(sources[key].retrieved_at > now for key in grounded_keys):
            return None  # a future check cannot support a present-day result
        if canonicalize_url(candidate.primary_url) != grounded_keys[0]:
            notes.append("primary source replaced by a grounded citation")

        # 2. faith guard
        if (
            not profile.faith_opted_in
            and candidate.category in FAITH_GUARDED_CATEGORIES
            and (
                candidate.involves_faith
                or mentions_faith(candidate.title, candidate.summary, candidate.relevance)
            )
        ):
            return None

        # 3. freshness
        if _event_is_over(candidate, now.date()):
            return None

        # 4. classification (primary first)
        citations = [
            _citation(sources[key], key, primary=i == 0, claimed=candidate.claimed_source_type)
            for i, key in enumerate(grounded_keys)
        ]

        # 5. claim honesty
        claim = candidate.claim_kind
        if claim in OFFICIAL_KINDS and citations[0].source_label is not SourceLabel.OFFICIAL:
            official = next((c for c in citations if c.source_label is SourceLabel.OFFICIAL), None)
            if official is not None:
                citations.remove(official)
                citations = [_promote(official), *(_demote(c) for c in citations)]
                notes.append("official citation promoted to primary")
            else:
                return None  # relabelling a fabricated rule leaves the false claim intact
        if claim is EvidenceKind.AUTHORITATIVE_REQUIREMENT and mode is ResearchMode.LIVE:
            claim = EvidenceKind.OFFICIAL_GUIDANCE
            notes.append("search synthesis: official rule requires a reviewed source passage")
        Provenance(  # the domain trust rules, checked once more on the final shape
            kind=claim,
            citations=[
                Citation(source_url=c.url, source_title=c.title, retrieved_at=c.retrieved_at)
                for c in citations
            ],
        )

        # 6. contacts
        grounded = {key: sources[key] for key in grounded_keys}
        contacts = await self._verifier.verify(candidate.contacts, grounded, now)
        dropped = len(candidate.contacts) - len(contacts)
        if dropped:
            notes.append(f"{dropped} unverified contact detail(s) dropped")

        # 7. score
        primary = citations[0]
        score = quality_score(
            primary.source_label,
            candidate.category,
            primary.retrieved_at,
            now,
            corroborating_sources=len({c.source_domain for c in citations}) - 1,
            event_date=candidate.event_starts_on,
        )
        return ProcessedResult(
            category=candidate.category,
            title=candidate.title.strip()[:300],
            summary=candidate.summary.strip()[:2000],
            relevance=candidate.relevance.strip()[:1000],
            claim_kind=claim,
            source_label=primary.source_label,
            citations=citations,
            quality_score=score,
            dedupe_key=dedupe_key(primary.canonical_url, candidate.title),
            contacts=contacts,
            event_starts_on=candidate.event_starts_on,
            event_ends_on=candidate.event_ends_on,
            event_timing=(candidate.event_timing or None) and candidate.event_timing[:200],
            fact_keys=list(dict.fromkeys(candidate.fact_keys)),
            fact_ids=profile.fact_ids_for(candidate.fact_keys),
            notes=notes,
        )

    @staticmethod
    def _dedupe(results: list[ProcessedResult]) -> list[ProcessedResult]:
        """Merge results describing the same thing: keep the better-scored one and union
        their citations (by canonical URL) and verified contacts."""
        kept: list[ProcessedResult] = []
        for result in sorted(results, key=lambda r: -r.quality_score):
            twin = next(
                (
                    k
                    for k in kept
                    if same_result(
                        k.primary.canonical_url, k.title, result.primary.canonical_url, result.title
                    )
                ),
                None,
            )
            if twin is None:
                kept.append(result)
                continue
            known = {c.canonical_url for c in twin.citations}
            twin.citations.extend(
                _demote(c) for c in result.citations if c.canonical_url not in known
            )
            contact_keys = {(c.kind, c.value.casefold()) for c in twin.contacts}
            twin.contacts.extend(
                c for c in result.contacts if (c.kind, c.value.casefold()) not in contact_keys
            )
            twin.fact_keys = list(dict.fromkeys([*twin.fact_keys, *result.fact_keys]))
            twin.fact_ids = list(dict.fromkeys([*twin.fact_ids, *result.fact_ids]))
            twin.notes.append("merged a duplicate result")
        return kept


def _promote(c: ProcessedCitation) -> ProcessedCitation:
    return replace(c, is_primary=True)


def _demote(c: ProcessedCitation) -> ProcessedCitation:
    return replace(c, is_primary=False) if c.is_primary else c
