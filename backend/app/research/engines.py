"""Research engines: where candidate results come from.

* `LiveResearchEngine` searches with OpenAI's web search (the real path whenever an API
  key is configured). Open-ended categories use agentic multi-step search: a reasoning
  model runs several searches and opens pages; an extraction step turns its cited notes
  into typed candidates; if coverage is thin, it proposes follow-up searches (passed
  through the privacy guard) for one more round.
* `SnapshotResearchEngine` reads the curated, URL-verified catalogue. It is deterministic
  and needs no network, for offline demo mode.

Both return `CategoryFindings`; the same `SourceProcessor` then validates, classifies,
scores and de-duplicates them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import TYPE_CHECKING, Protocol

from app.adapters.llm import LLMClient
from app.adapters.web_fetch import NoPageFetcher, PageFetcher, SafeHttpPageFetcher
from app.adapters.web_search import WebResearcher, WebResearchResult
from app.core.errors import AdapterUnavailable, UpstreamError
from app.domain.enums import EvidenceKind
from app.research.profile import ResearchProfile
from app.research.prompts import (
    ExtractedItem,
    Extraction,
    extraction_instructions,
    search_instructions,
)
from app.research.queries import PlannedQuery, build_query_plan, sanitize_follow_ups
from app.research.snapshot import CatalogueEntry, load_catalogue, select_entries, to_candidate
from app.research.sources import canonicalize_url
from app.research.types import (
    COMPLEX_CATEGORIES,
    Candidate,
    CategoryFindings,
    ClaimedSourceType,
    ContactCandidate,
    ContactKind,
    ResearchCategory,
    ResearchMode,
    SourceRef,
)

if TYPE_CHECKING:
    from app.adapters.registry import Adapters

logger = logging.getLogger(__name__)

Progress = Callable[[str, float | None], Awaitable[None]]

EXTRACT_PURPOSE = "research.extract"
MAX_NOTES_CHARS = 24_000

_CLAIMS: dict[str, EvidenceKind] = {
    "law": EvidenceKind.AUTHORITATIVE_REQUIREMENT,
    "official_guidance": EvidenceKind.OFFICIAL_GUIDANCE,
    "community_information": EvidenceKind.COMMUNITY_WEB,
    "ai_recommendation": EvidenceKind.AI_RECOMMENDATION,
}
_SOURCE_TYPES: dict[str, ClaimedSourceType] = {
    "government": ClaimedSourceType.GOVERNMENT,
    "organization_site": ClaimedSourceType.ORGANIZATION_SITE,
    "community_platform": ClaimedSourceType.COMMUNITY_PLATFORM,
    "news_or_blog": ClaimedSourceType.NEWS_OR_BLOG,
    "other": ClaimedSourceType.OTHER,
}
_FACT_KEYS = frozenset(
    {"relocation_type", "profession", "interests", "background", "faith", "focus", "journey_goals"}
)


class ResearchEngine(Protocol):
    mode: ResearchMode
    fetcher: PageFetcher

    async def research(
        self,
        category: ResearchCategory,
        profile: ResearchProfile,
        *,
        today: date,
        progress: Progress,
    ) -> CategoryFindings: ...

    async def aclose(self) -> None: ...


def _iso_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def to_candidates(extraction: Extraction, category: ResearchCategory) -> list[Candidate]:
    candidates: list[Candidate] = []
    for item in extraction.items:
        if not item.title.strip() or not item.source_url.strip():
            continue
        candidates.append(_candidate(item, category))
    return candidates


def _candidate(item: ExtractedItem, category: ResearchCategory) -> Candidate:
    return Candidate(
        category=category,
        title=item.title,
        summary=item.summary,
        relevance=item.relevance,
        claim_kind=_CLAIMS[item.claim_kind],
        primary_url=item.source_url,
        source_urls=list(item.supporting_urls),
        claimed_source_type=_SOURCE_TYPES[item.source_type],
        contacts=[
            ContactCandidate(ContactKind(c.kind), c.value, c.source_url) for c in item.contacts
        ],
        event_starts_on=_iso_day(item.event_start),
        event_ends_on=_iso_day(item.event_end),
        event_timing=item.event_timing,
        involves_faith=category is ResearchCategory.FAITH_AND_WORSHIP or item.involves_faith,
        fact_keys=[k for k in item.fact_keys if k in _FACT_KEYS],
    )


def render_notes(results: list[WebResearchResult], sources: dict[str, SourceRef]) -> str:
    listing = "\n".join(f"- {ref.title} | {ref.url}" for ref in sources.values())
    notes = "\n\n".join(f"### Search: {r.query}\n{r.answer.strip()}" for r in results)
    return f"SOURCES (cite these URLs exactly):\n{listing}\n\nNOTES:\n{notes}"[:MAX_NOTES_CHARS]


class LiveResearchEngine:
    mode = ResearchMode.LIVE

    def __init__(
        self,
        web: WebResearcher,
        llm: LLMClient,
        *,
        fetcher: PageFetcher,
        max_concurrent_searches: int = 3,
        max_rounds: int = 2,
        min_results: int = 3,
        max_items: int = 8,
    ) -> None:
        self._web = web
        self._llm = llm
        self.fetcher = fetcher
        self._searches = asyncio.Semaphore(max_concurrent_searches)
        self._max_rounds = max_rounds
        self._min_results = min_results
        self._max_items = max_items

    async def _search(
        self, planned: PlannedQuery, category: ResearchCategory, today: date
    ) -> WebResearchResult:
        async with self._searches:
            return await self._web.research(
                query=planned.query,
                instructions=search_instructions(category, today),
                allowed_domains=list(planned.allowed_domains) if planned.allowed_domains else None,
                depth=planned.depth,
            )

    async def research(
        self,
        category: ResearchCategory,
        profile: ResearchProfile,
        *,
        today: date,
        progress: Progress,
    ) -> CategoryFindings:
        plan = build_query_plan(category, profile, today)
        findings = CategoryFindings(category=category, mode=self.mode, candidates=[], sources={})
        if not plan:
            return findings
        rounds = self._max_rounds if category in COMPLEX_CATEGORIES else 1
        answers: list[WebResearchResult] = []

        for round_no in range(rounds):
            await progress(
                "Searching the web" if round_no == 0 else "Looking deeper to fill gaps",
                0.1 if round_no == 0 else 0.6,
            )
            outcomes = await asyncio.gather(
                *(self._search(q, category, today) for q in plan), return_exceptions=True
            )
            succeeded = [
                o
                for o in outcomes
                if isinstance(o, WebResearchResult) and o.available and o.citations
            ]
            failures = [o for o in outcomes if isinstance(o, BaseException)]
            for failure in failures:
                logger.warning(
                    "research_search_failed",
                    extra={"category": category.value, "error": type(failure).__name__},
                )
            if not succeeded and not answers:
                raise UpstreamError("Web search is not responding right now")
            for result in succeeded:
                answers.append(result)
                findings.queries.extend([result.query, *result.searches])
                for citation in result.citations:
                    key = canonicalize_url(citation.url)
                    if key and key not in findings.sources:
                        findings.sources[key] = SourceRef(
                            url=citation.url,
                            title=citation.title,
                            retrieved_at=result.retrieved_at,
                            summary=citation.snippet,
                        )
            if not findings.sources:
                break
            await progress(f"Reading {len(findings.sources)} sources", 0.4 + 0.3 * round_no)
            extraction = await self._llm.structured(
                purpose=EXTRACT_PURPOSE,
                instructions=extraction_instructions(category, profile, today, self._max_items),
                input=render_notes(answers, findings.sources),
                schema=Extraction,
                tier="reasoning" if category in COMPLEX_CATEGORIES else "fast",
            )
            findings.candidates = to_candidates(extraction, category)[: self._max_items]
            grounded = sum(
                1
                for c in findings.candidates
                if canonicalize_url(c.primary_url) in findings.sources
            )
            if round_no + 1 >= rounds or grounded >= self._min_results:
                break
            plan = sanitize_follow_ups(extraction.follow_up_queries, category, profile)
            if not plan:
                break
        return findings

    async def aclose(self) -> None:
        closer = getattr(self.fetcher, "aclose", None)
        if closer is not None:
            await closer()


class SnapshotResearchEngine:
    mode = ResearchMode.SNAPSHOT

    def __init__(
        self,
        entries: tuple[CatalogueEntry, ...] | None = None,
        *,
        pace_seconds: float = 0.0,
        per_category: int = 6,
    ) -> None:
        self._entries = entries if entries is not None else load_catalogue()
        self.fetcher: PageFetcher = NoPageFetcher()
        self._pace = pace_seconds
        self._per_category = per_category

    async def research(
        self,
        category: ResearchCategory,
        profile: ResearchProfile,
        *,
        today: date,
        progress: Progress,
    ) -> CategoryFindings:
        if not self._entries:
            raise AdapterUnavailable(
                "The reviewed source list is not available", code="research_snapshot_missing"
            )
        await progress("Checking ADAPT's reviewed source list", 0.2)
        if self._pace:
            await asyncio.sleep(self._pace)  # paced so progress is visible in the UI
        matches = select_entries(self._entries, category, profile, limit=self._per_category)
        sources = {
            key: SourceRef(
                url=m.entry.url,
                title=m.entry.source_title,
                retrieved_at=m.entry.retrieved_at,
                summary=m.entry.summary,
            )
            for m in matches
            if (key := canonicalize_url(m.entry.url))
        }
        await progress(f"Matched {len(matches)} to your profile", 0.8)
        return CategoryFindings(
            category=category,
            mode=self.mode,
            candidates=[to_candidate(m) for m in matches],
            sources=sources,
        )

    async def aclose(self) -> None:
        return None


def build_research_engine(
    adapters: Adapters, *, pace_seconds: float = 0.4, snapshot: bool = False
) -> ResearchEngine:
    """Live whenever web search and the language model are live (an OpenAI key is set);
    otherwise, or when `snapshot` is asked for, the curated offline snapshot."""
    if not snapshot and adapters.web_search.mode == "live" and adapters.llm.mode == "live":
        return LiveResearchEngine(adapters.web_search, adapters.llm, fetcher=SafeHttpPageFetcher())
    return SnapshotResearchEngine(pace_seconds=pace_seconds)
