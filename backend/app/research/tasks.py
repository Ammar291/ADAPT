"""ARQ job: run one research job for one principal (re-verified through RLS)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import update

from app.agents.runner import execute_run
from app.domain.enums import RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.research import repository
from app.research.engines import build_research_engine
from app.research.graph import ResearchContext, build_research_graph
from app.research.models import ResearchJob
from app.research.processing import ContactVerifier, SourceProcessor
from app.research.profile import ResearchProfile
from app.research.types import CategoryStatus, ResearchMode

logger = logging.getLogger(__name__)


async def run_research(
    ctx: dict[str, Any],
    *,
    run_id: str,
    research_job_id: str,
    user_id: str,
    tenant_id: str,
) -> str:
    deps = ctx["deps"]
    principal = Principal.from_job_args(user_id, tenant_id)
    async with deps.db.user_session(principal) as session:
        found = await repository.get_job(session, UUID(research_job_id))
    if found is None or str(found[1].id) != run_id:
        logger.warning("research_job_not_found", extra={"job_id": research_job_id})
        return "skipped"
    job, run = found
    if run.status is not RunStatus.QUEUED:
        logger.info("research_job_already_started", extra={"job_id": research_job_id})
        return "skipped"

    # A job asked for the curated snapshot keeps it, even when live search is configured.
    engine = build_research_engine(deps.adapters, snapshot=job.mode is ResearchMode.SNAPSHOT)
    try:
        if engine.mode is not job.mode:
            async with deps.db.user_session(principal) as session:
                await session.execute(
                    update(ResearchJob).where(ResearchJob.id == job.id).values(mode=engine.mode)
                )
                await session.commit()
        status = job.category_status or {}
        active = [c for c in job.categories if status.get(c, {}).get("status") != "skipped"]
        skipped = [
            {"category": c, "reason": status[c].get("reason") or ""}
            for c in job.categories
            if status.get(c, {}).get("status") == CategoryStatus.SKIPPED.value
        ]
        research_ctx = ResearchContext(
            principal=principal,
            run_id=run.id,
            events=RunEventEmitter(deps.db, principal, run.id, deps.notifier),
            db=deps.db,
            adapters=deps.adapters,
            job_id=job.id,
            engine=engine,
            processor=SourceProcessor(ContactVerifier(engine.fetcher)),
            profile=ResearchProfile.model_validate(job.profile or {}),
        )
        outcome = await execute_run(
            graph=build_research_graph(deps.checkpointer),
            ctx=research_ctx,
            kind=RunKind.RESEARCH,
            thread_id=run.thread_id,
            graph_input={"job_id": str(job.id), "active": active, "skipped": skipped},
        )
    finally:
        await engine.aclose()
    return outcome.status
