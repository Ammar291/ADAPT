"""Production implementations of the journey ports that delegate to other workstreams:

* documents -> `app.documents.service.DocumentIntelligence` (idempotent analysis, corrections)
* evidence  -> `app.knowledge.retrieval.retrieve` (official passages scoped to graph nodes)
* research  -> `app.research.service.start_research` (fire and forget)

Each one degrades honestly: if a capability is missing, the agent gets no data, never
invented data, and the gap surfaces as a risk.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from app.adapters.registry import Adapters
from app.agents.journey.facts import document_fact_key, fact
from app.agents.journey.ports import (
    DocumentAnalysis,
    EvidenceHit,
    ExtractedField,
    ResearchStart,
)
from app.agents.journey.state import FactOrigin, UserFact
from app.core.errors import AppError
from app.db.session import Database
from app.domain.principal import Principal
from app.events.emitter import EventSink
from app.workers.queue import JobQueue

logger = logging.getLogger(__name__)

# An inferred profile value (e.g. "moving with spouse" because a spouse exists) is an
# assumption: the planner may follow it, but it is surfaced as missing information.
_ORIGINS: dict[str, FactOrigin] = {
    "user_stated": "user_stated",
    "document_extracted": "document_extracted",
    "inferred": "assumed",
}


def planning_fact(item: Any, *, default_origin: FactOrigin = "user_graph") -> UserFact:
    """personalization.PlanningFact -> journey UserFact."""
    return fact(
        item.key,
        item.value,
        _ORIGINS.get(str(item.source), default_origin),
        source_ref="profile",
        confidence=float(item.confidence),
        confirmed=bool(item.confirmed),
        fact_ids=[str(i) for i in item.fact_ids],
    )


async def load_planning_facts(db: Database, principal: Principal) -> list[UserFact]:
    from app.personalization.facts import planning_facts

    async with db.user_session(principal) as session:
        # Requirement planning never needs faith or community keys, and the plan snapshot
        # persists the facts it used, so leave them out entirely.
        items = await planning_facts(session, principal, for_requirements=True)
        return [planning_fact(f) for f in items]


# How long a journey waits for a document another reader (the upload's own job) holds.
DOCUMENT_READ_WAIT_SECONDS = 90.0
DOCUMENT_READ_POLL_SECONDS = 1.0


def _status(analysis: Any) -> str:
    return str(getattr(analysis.status, "value", analysis.status))


def _subject(holder: str) -> str:
    return "child1" if holder == "child" else holder


class PlatformDocuments:
    """DocumentAnalyzer backed by document intelligence (adapt-d6)."""

    def __init__(
        self, db: Database, principal: Principal, adapters: Adapters, events: EventSink | None
    ) -> None:
        from app.documents.service import DocumentIntelligence

        self._db, self._principal = db, principal
        self._intelligence = DocumentIntelligence(
            db, principal, adapters, events=events, node="document_analysis"
        )

    async def _facts_for(self, analysis: Any) -> list[UserFact]:
        """The planning facts this document contributed (same keys the planner reads)."""
        own_ids = {str(f.id) for f in analysis.facts}
        kind = getattr(analysis.kind, "value", str(analysis.kind))
        holder = _subject(getattr(analysis.holder, "value", str(analysis.holder)))
        held_key = document_fact_key(f"document.{kind}", holder)
        facts = []
        for item in await load_planning_facts(self._db, self._principal):
            if set(item["fact_ids"]) & own_ids or item["key"] == held_key:
                facts.append(
                    {
                        **item,
                        "source": "document_extracted",
                        "source_ref": f"document:{analysis.document_id}",
                    }
                )
        return facts  # type: ignore[return-value]

    async def analyze(self, document_id: str) -> DocumentAnalysis:
        analysis = await self._intelligence.analyze(UUID(document_id))
        deadline = time.monotonic() + DOCUMENT_READ_WAIT_SECONDS
        while _status(analysis) == "processing" and time.monotonic() < deadline:
            # Someone else is reading it (typically the upload's own job, when the plan is
            # started right after uploading). Wait for that result rather than planning
            # without the document; analyze() returns the stored state without re-reading.
            await asyncio.sleep(DOCUMENT_READ_POLL_SECONDS)
            analysis = await self._intelligence.analyze(UUID(document_id))
        if _status(analysis) == "processing":
            logger.warning("document_still_processing", extra={"document_id": document_id})
        return DocumentAnalysis(
            document_id=str(analysis.document_id),
            kind=getattr(analysis.kind, "value", str(analysis.kind)),
            holder=_subject(getattr(analysis.holder, "value", str(analysis.holder))),
            status=getattr(analysis.status, "value", str(analysis.status)),
            fields=[
                ExtractedField(
                    name=f.name,
                    label=f.label,
                    value=None if f.value is None else str(f.value),
                    confidence=float(f.confidence),
                    needs_review=bool(f.needs_review),
                    fact_id=str(f.fact_id) if f.fact_id else None,
                )
                for f in analysis.fields
            ],
            facts=await self._facts_for(analysis),
            review_task_ids=[str(i) for i in analysis.review_task_ids],
        )

    async def apply_corrections(
        self, document_id: str, corrections: list[dict[str, Any]], *, confirm: bool
    ) -> list[UserFact]:
        await self._intelligence.apply_corrections(UUID(document_id), corrections, confirm=confirm)
        refreshed = await self._intelligence.analyze(UUID(document_id))  # stored result
        return [{**f, "confirmed": True} for f in await self._facts_for(refreshed)]  # type: ignore[misc]


class KnowledgeEvidence:
    """EvidenceRetriever backed by the knowledge layer (adapt-f8)."""

    def __init__(self, db: Database, adapters: Adapters) -> None:
        self._db, self._adapters = db, adapters

    async def retrieve(
        self, query: str, *, governance_keys: list[str], top_k: int
    ) -> list[EvidenceHit]:
        from app.knowledge.retrieval import governance_keys_by_chunk, retrieve
        from app.knowledge.schemas import RetrievalFilters

        try:
            async with self._db.public_session() as session:
                response = await retrieve(
                    session,
                    self._adapters.embeddings,
                    query,
                    filters=RetrievalFilters(governance_keys=governance_keys),
                    top_k=top_k,
                )
                chunk_ids = [UUID(hex=e.id.removeprefix("ev_")) for e in response.evidence]
                keys_by_chunk = await governance_keys_by_chunk(session, chunk_ids)
        except (AppError, ValueError, LookupError) as exc:
            # No corpus or no search: the plan continues, and the gap becomes a risk.
            logger.warning("evidence_unavailable", extra={"error": type(exc).__name__})
            return []
        wanted = set(governance_keys)
        hits = []
        for evidence, chunk_id in zip(response.evidence, chunk_ids, strict=True):
            keys = [k for k in keys_by_chunk.get(chunk_id, []) if k in wanted]
            hits.append(
                EvidenceHit(
                    id=evidence.id,
                    title=evidence.source_title,
                    source_url=evidence.source_url,
                    authority=evidence.authority,
                    quote=evidence.claim[:1200] if evidence.excerpt == "quote" else None,
                    governance_key=keys[0] if keys else None,
                    trust=evidence.evidence_kind.value,
                    score=float(evidence.score or 0.0),
                    retrieved_at=evidence.retrieved_at.isoformat(),
                    claim=evidence.claim[:1200],
                    section_or_page=evidence.section_or_page,
                    effective_date=evidence.effective_date.isoformat()
                    if evidence.effective_date
                    else None,
                    excerpt=evidence.excerpt,
                    source_family=evidence.source_family.value,
                    freshness=evidence.freshness.value,
                    chunk_id=str(evidence.chunk_id),
                )
            )
        return hits


class PlatformResearch:
    """ResearchStarter backed by the research workstream (adapt-6a)."""

    def __init__(
        self,
        db: Database,
        queue: JobQueue | None,
        principal: Principal,
        adapters: Adapters,
        api_prefix: str = "/api",
        *,
        snapshot: bool = False,
    ) -> None:
        self._db, self._queue, self._principal = db, queue, principal
        self._adapters, self._api_prefix = adapters, api_prefix
        self._snapshot = snapshot

    async def start(self, *, journey_id: str) -> ResearchStart | None:
        if self._queue is None:
            return None
        try:
            from app.research.contracts import StartResearchRequest
            from app.research.service import journey_job, start_research

            # A plan gets one research job: reuse one already started for it (for example
            # by the person, before the plan's approvals were answered).
            existing = await journey_job(self._db, self._principal, UUID(journey_id))
            if existing is not None:
                return ResearchStart(
                    job_id=str(existing.id),
                    run_id=str(existing.run_id),
                    status=str(existing.status),
                )
            job = await start_research(
                self._db,
                self._queue,
                self._principal,
                StartResearchRequest(
                    journey_id=UUID(journey_id), mode="snapshot" if self._snapshot else "auto"
                ),
                adapters=self._adapters,
                api_prefix=self._api_prefix,
            )
        except (AppError, ImportError) as exc:
            logger.info("research_not_started", extra={"reason": type(exc).__name__})
            return None
        return ResearchStart(job_id=str(job.id), run_id=str(job.run_id), status=str(job.status))
