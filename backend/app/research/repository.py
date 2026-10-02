"""Research persistence. Every function takes a user-scoped (RLS) session, so a query that
forgot a filter still can't read another user's research."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import cast, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun
from app.domain.enums import RunStatus
from app.domain.principal import Principal
from app.research.models import ResearchCitation, ResearchJob, ResearchResult
from app.research.types import CategoryStatus, ProcessedResult, ResearchCategory, ResearchMode

ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


async def create_job(
    session: AsyncSession,
    principal: Principal,
    *,
    run_id: UUID,
    journey_id: UUID | None,
    categories: Sequence[ResearchCategory],
    category_status: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    mode: ResearchMode,
) -> ResearchJob:
    job = ResearchJob(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        run_id=run_id,
        journey_id=journey_id,
        categories=[c.value for c in categories],
        category_status=category_status,
        profile=profile,
        mode=mode,
    )
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: UUID) -> tuple[ResearchJob, AgentRun] | None:
    row = (
        await session.execute(
            select(ResearchJob, AgentRun)
            .join(AgentRun, AgentRun.id == ResearchJob.run_id)
            .where(ResearchJob.id == job_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def list_jobs(session: AsyncSession, limit: int = 10) -> list[tuple[ResearchJob, AgentRun]]:
    rows = await session.execute(
        select(ResearchJob, AgentRun)
        .join(AgentRun, AgentRun.id == ResearchJob.run_id)
        .order_by(ResearchJob.created_at.desc())
        .limit(limit)
    )
    return [(job, run) for job, run in rows.all()]


async def active_job(
    session: AsyncSession, *, stale_after: timedelta
) -> tuple[ResearchJob, AgentRun] | None:
    """The user's queued or running job, ignoring any stuck longer than `stale_after`."""
    cutoff = datetime.now(UTC) - stale_after
    row = (
        await session.execute(
            select(ResearchJob, AgentRun)
            .join(AgentRun, AgentRun.id == ResearchJob.run_id)
            .where(AgentRun.status.in_(ACTIVE_STATUSES), ResearchJob.created_at >= cutoff)
            .order_by(ResearchJob.created_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def set_category_status(
    session: AsyncSession,
    job_id: UUID,
    category: ResearchCategory,
    status: CategoryStatus,
    *,
    result_count: int = 0,
    reason: str | None = None,
) -> None:
    """Atomic per-category update (parallel category nodes never overwrite each other)."""
    entry = {
        category.value: {"status": status.value, "result_count": result_count, "reason": reason}
    }
    await session.execute(
        update(ResearchJob)
        .where(ResearchJob.id == job_id)
        .values(
            category_status=ResearchJob.category_status.op("||")(cast(literal(entry, JSONB), JSONB))
        )
    )


async def mark_completed(session: AsyncSession, job_id: UUID) -> None:
    await session.execute(
        update(ResearchJob).where(ResearchJob.id == job_id).values(completed_at=func.now())
    )


async def mark_seen(session: AsyncSession, job_id: UUID) -> bool:
    result = await session.execute(
        update(ResearchJob)
        .where(ResearchJob.id == job_id, ResearchJob.seen_at.is_(None))
        .values(seen_at=func.now())
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def save_results(
    session: AsyncSession,
    principal: Principal,
    job_id: UUID,
    results: Sequence[ProcessedResult],
) -> list[tuple[ResearchResult, list[ResearchCitation]]]:
    """Persist processed results with their citations. Idempotent per (job, category,
    dedupe_key), so a retried category never duplicates rows."""
    owner = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
    saved: list[tuple[ResearchResult, list[ResearchCitation]]] = []
    for position, result in enumerate(results):
        primary = result.primary
        values = {
            **owner,
            "job_id": job_id,
            "category": result.category.value,
            "title": result.title,
            "summary": result.summary,
            "relevance": result.relevance,
            "evidence_kind": result.claim_kind.value,
            "source_label": result.source_label.value,
            "source_url": primary.url,
            "canonical_url": primary.canonical_url,
            "source_title": primary.title,
            "source_domain": primary.source_domain,
            "retrieved_at": primary.retrieved_at,
            "quality_score": result.quality_score,
            "dedupe_key": result.dedupe_key,
            "contacts": [
                {
                    "kind": c.kind.value,
                    "value": c.value,
                    "source_url": c.source_url,
                    "verified_at": c.verified_at.isoformat(),
                }
                for c in result.contacts
            ],
            "event_starts_on": result.event_starts_on,
            "event_ends_on": result.event_ends_on,
            "event_timing": result.event_timing,
            "fact_keys": result.fact_keys,
            "fact_ids": result.fact_ids,
            "position": position,
        }
        statement = (
            insert(ResearchResult)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_research_results_dedupe")
            .returning(ResearchResult)
        )
        row = (await session.execute(statement)).scalar_one_or_none()
        if row is None:
            continue
        citations: list[ResearchCitation] = []
        for citation in result.citations:
            item = ResearchCitation(
                **owner,
                job_id=job_id,
                result_id=row.id,
                category=result.category,
                url=citation.url,
                canonical_url=citation.canonical_url,
                title=citation.title,
                source_domain=citation.source_domain,
                source_label=citation.source_label,
                retrieved_at=citation.retrieved_at,
                summary=citation.summary,
                is_primary=citation.is_primary,
            )
            session.add(item)
            citations.append(item)
        await session.flush()
        saved.append((row, citations))
    return saved


async def job_modes(session: AsyncSession, job_ids: set[UUID]) -> dict[UUID, ResearchMode]:
    """Which engine each job used (live web search or the curated snapshot)."""
    if not job_ids:
        return {}
    rows = await session.execute(
        select(ResearchJob.id, ResearchJob.mode).where(ResearchJob.id.in_(job_ids))
    )
    return {job_id: mode for job_id, mode in rows.all()}


async def citations_for(
    session: AsyncSession, result_ids: Sequence[UUID]
) -> dict[UUID, list[ResearchCitation]]:
    grouped: dict[UUID, list[ResearchCitation]] = defaultdict(list)
    if not result_ids:
        return grouped
    rows = await session.execute(
        select(ResearchCitation)
        .where(ResearchCitation.result_id.in_(result_ids))
        .order_by(ResearchCitation.is_primary.desc(), ResearchCitation.created_at)
    )
    for citation in rows.scalars():
        grouped[citation.result_id].append(citation)
    return grouped


async def results_for_job(session: AsyncSession, job_id: UUID) -> list[ResearchResult]:
    rows = await session.execute(
        select(ResearchResult)
        .where(ResearchResult.job_id == job_id)
        .order_by(ResearchResult.category, ResearchResult.position)
    )
    return list(rows.scalars())


async def saved_results(
    session: AsyncSession, *, exclude_job: UUID | None = None, limit: int = 100
) -> list[ResearchResult]:
    query = select(ResearchResult).where(ResearchResult.saved_at.is_not(None))
    if exclude_job is not None:
        query = query.where(ResearchResult.job_id != exclude_job)
    rows = await session.execute(query.order_by(ResearchResult.saved_at.desc()).limit(limit))
    return list(rows.scalars())


async def get_result(session: AsyncSession, result_id: UUID) -> ResearchResult | None:
    return (
        await session.execute(select(ResearchResult).where(ResearchResult.id == result_id))
    ).scalar_one_or_none()


async def count_results(session: AsyncSession, job_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(ResearchResult).where(ResearchResult.job_id == job_id)
        )
    ).scalar_one()
