"""Turn a stored passage into a citable `Evidence` object. Pure.

Trust is re-derived on every read from the page URL, the claimed publisher, the passage
and the clock, never taken from stored labels:

* `evidence_kind`: `authoritative_requirement` only for a current, verbatim passage from an
  official page that states a requirement. Other official passages are `official_guidance`,
  and anything off the allowlist is `community_web`.
* `confidence`: publisher trust x freshness x verbatim/paraphrase x how the page was read.
* `caveats`: why the UI should add "confirm on the official page".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.domain.enums import EvidenceKind
from app.knowledge.corpus import DEFAULT_STALE_AFTER_DAYS, assess_freshness
from app.knowledge.schemas import Evidence, EvidenceCaveat, Freshness, KnowledgeTopic
from app.knowledge.sources import FAMILY_PRIORITY, classify_source, publisher_name

SOURCE_TRUST: dict[int, float] = {1: 0.95, 2: 0.93, 3: 0.92, 4: 0.92, 5: 0.90, 6: 0.85, 7: 0.40}
STALE_FACTOR = 0.75
PARAPHRASE_FACTOR = 0.92
SNIPPET_FACTOR = 0.80
SUPERSEDED_FACTOR = 0.50
NOT_YET_EFFECTIVE_FACTOR = 0.70


@dataclass(frozen=True, slots=True)
class PassageView:
    """What evidence needs to know about one chunk of one document version."""

    document_id: UUID
    chunk_id: UUID
    content: str
    source_url: str
    title: str
    authority: str | None
    retrieved_at: datetime
    effective_date: date | None = None
    superseded_at: datetime | None = None
    section_or_page: str | None = None
    excerpt: Literal["quote", "paraphrase"] = "paraphrase"
    states_requirement: bool = False
    verification: Literal["fetched", "search_snippet"] = "fetched"
    topics: tuple[str, ...] = field(default_factory=tuple)


def evidence_id(chunk_id: UUID) -> str:
    return f"ev_{chunk_id.hex}"


def build_evidence(
    view: PassageView,
    *,
    now: datetime,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    score: float | None = None,
    rank: int | None = None,
    governance_keys: list[str] | None = None,
) -> Evidence:
    source = classify_source(view.source_url, view.authority)
    priority = FAMILY_PRIORITY[source.family]
    freshness = assess_freshness(view.retrieved_at, now=now, stale_after_days=stale_after_days)
    superseded = view.superseded_at is not None
    not_yet_effective = view.effective_date is not None and view.effective_date > now.date()

    caveats: list[EvidenceCaveat] = []
    confidence = SOURCE_TRUST[priority]
    if not source.is_official:
        caveats.append(EvidenceCaveat.UNOFFICIAL_SOURCE)
    if freshness is Freshness.STALE:
        caveats.append(EvidenceCaveat.STALE_SOURCE)
        confidence *= STALE_FACTOR
    if view.excerpt == "paraphrase":
        caveats.append(EvidenceCaveat.PARAPHRASED)
        confidence *= PARAPHRASE_FACTOR
    if view.verification == "search_snippet":
        caveats.append(EvidenceCaveat.SNIPPET_ONLY)
        confidence *= SNIPPET_FACTOR
    if superseded:
        caveats.append(EvidenceCaveat.SUPERSEDED_SOURCE)
        confidence *= SUPERSEDED_FACTOR
    if not_yet_effective:
        caveats.append(EvidenceCaveat.NOT_YET_EFFECTIVE)
        confidence *= NOT_YET_EFFECTIVE_FACTOR

    if not source.is_official:
        kind = EvidenceKind.COMMUNITY_WEB
    elif (
        view.states_requirement
        and view.excerpt == "quote"
        and view.verification == "fetched"
        and freshness is Freshness.CURRENT
        and not superseded
        and not not_yet_effective
    ):
        kind = EvidenceKind.AUTHORITATIVE_REQUIREMENT
    else:
        kind = EvidenceKind.OFFICIAL_GUIDANCE

    topics = [KnowledgeTopic(t) for t in view.topics if t in KnowledgeTopic._value2member_map_]
    return Evidence(
        id=evidence_id(view.chunk_id),
        claim=view.content,
        source_title=view.title,
        source_url=view.source_url,
        authority=publisher_name(view.authority),
        authority_key=view.authority,
        section_or_page=view.section_or_page,
        retrieved_at=view.retrieved_at,
        effective_date=view.effective_date,
        confidence=round(confidence, 2),
        evidence_kind=kind,
        excerpt=view.excerpt,
        source_family=source.family,
        source_priority=priority,
        freshness=freshness,
        caveats=caveats,
        score=None if score is None else round(score, 4),
        rank=rank,
        governance_keys=sorted(governance_keys or []),
        topics=topics,
        document_id=view.document_id,
        chunk_id=view.chunk_id,
    )


_KIND_STRENGTH = {
    EvidenceKind.AUTHORITATIVE_REQUIREMENT: 3,
    EvidenceKind.OFFICIAL_GUIDANCE: 2,
    EvidenceKind.COMMUNITY_WEB: 1,
    EvidenceKind.AI_RECOMMENDATION: 0,
}


def strongest_kind(evidence: list[Evidence]) -> EvidenceKind | None:
    """The trust tier a graph fact earns from its best supporting passage."""
    if not evidence:
        return None
    return max((e.evidence_kind for e in evidence), key=_KIND_STRENGTH.__getitem__)
