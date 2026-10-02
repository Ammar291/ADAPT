"""Research use cases: start a background job, read briefs, save results, add to journey.

`start_research` returns as soon as the job is enqueued. Nothing on the request path, the
journey agent included, ever waits for research. It can be called from API routes and
from worker code (e.g. the journey agent's dispatch step) alike.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select, update

from app.core.errors import AdapterUnavailable, AppError, Conflict, NotFound
from app.db.session import Database
from app.domain.enums import ConsentStatus, EvidenceKind, RunKind, RunStatus
from app.domain.principal import Principal
from app.domain.provenance import Citation, Provenance
from app.research import repository
from app.research.contracts import (
    DiscoverOut,
    ResearchJobDetail,
    ResearchJobOut,
    ResearchResultOut,
    StartResearchRequest,
)
from app.research.inputs import gather_profile_facts
from app.research.presenters import discover_out, job_out, result_out
from app.research.profile import (
    ProfileFacts,
    ResearchProfile,
    build_research_profile,
    mentions_faith,
)
from app.research.types import (
    ALL_CATEGORIES,
    CategoryStatus,
    ResearchCategory,
    ResearchMode,
)
from app.workers.queue import JobQueue

if TYPE_CHECKING:
    from app.adapters.registry import Adapters

logger = logging.getLogger(__name__)

RESEARCH_TASK = "run_research"
AGENT_NAME = "research"
# A job still "queued" after this long is considered lost (worker down) and doesn't block
# a new one.
STALE_ACTIVE_AFTER = timedelta(minutes=20)

FAITH_NOT_OPTED_IN = "faith_not_opted_in"


class ConsentRequired(AppError):
    """The request asks for personal data the user hasn't agreed ADAPT may use."""

    status, code, title = 409, "consent_required", "Your permission is needed first"


def engine_mode(adapters: Adapters | None) -> ResearchMode:
    if adapters is not None and adapters.web_search.mode == "live" and adapters.llm.mode == "live":
        return ResearchMode.LIVE
    return ResearchMode.SNAPSHOT


def check_consent(request: StartResearchRequest, facts: ProfileFacts) -> None:
    """Explicit requests for sensitive personalisation need the matching consent. (Implicit
    use is filtered silently by `build_research_profile`.)"""
    given = request.profile
    if facts.faith_consent is not ConsentStatus.GRANTED and (
        (given is not None and given.faith)
        or mentions_faith(request.focus)
        or ResearchCategory.FAITH_AND_WORSHIP in (request.categories or [])
    ):
        raise ConsentRequired(
            "Turn on faith suggestions in Settings to include faith communities.",
            extra={"consent": "faith_personalization"},
        )
    if facts.community_consent is not ConsentStatus.GRANTED and (
        given is not None and (given.background or given.interests)
    ):
        raise ConsentRequired(
            "Turn on community suggestions in Settings to personalise with your background "
            "and interests.",
            extra={"consent": "community_personalization"},
        )


def plan_categories(
    request: StartResearchRequest, profile: ResearchProfile
) -> tuple[list[ResearchCategory], list[tuple[ResearchCategory, str]]]:
    requested = list(dict.fromkeys(request.categories or ALL_CATEGORIES))
    active: list[ResearchCategory] = []
    skipped: list[tuple[ResearchCategory, str]] = []
    for category in requested:
        if category is ResearchCategory.FAITH_AND_WORSHIP and not profile.faith_opted_in:
            skipped.append((category, FAITH_NOT_OPTED_IN))
        else:
            active.append(category)
    return active, skipped


async def start_research(
    db: Database,
    queue: JobQueue,
    principal: Principal,
    request: StartResearchRequest,
    *,
    adapters: Adapters | None = None,
    api_prefix: str = "/api",
) -> ResearchJobOut:
    """Create the run and job rows, enqueue `run_research` and return immediately.
    Idempotent while a job is queued or running (unless `request.force`)."""
    from app.db.models import AgentRun, Journey

    async with db.user_session(principal) as session:
        if not request.force:
            existing = await repository.active_job(session, stale_after=STALE_ACTIVE_AFTER)
            if existing is not None:
                return job_out(*existing, api_prefix=api_prefix)
        if request.journey_id is not None:
            owned = await session.execute(
                select(Journey.id).where(Journey.id == request.journey_id)
            )
            if owned.scalar_one_or_none() is None:
                raise NotFound("Journey not found")

        facts = await gather_profile_facts(session, principal, request)
        check_consent(request, facts)
        profile = build_research_profile(facts)
        active, skipped = plan_categories(request, profile)

        run = AgentRun(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            agent=AGENT_NAME,
            kind=RunKind.RESEARCH,
            thread_id=f"research:{uuid.uuid4()}",
            input={"categories": [c.value for c in active], "focus": profile.focus},
            journey_id=request.journey_id,
        )
        session.add(run)
        await session.flush()
        status: dict[str, dict[str, Any]] = {
            c.value: {"status": CategoryStatus.PENDING.value, "result_count": 0, "reason": None}
            for c in active
        }
        for category, reason in skipped:
            status[category.value] = {
                "status": CategoryStatus.SKIPPED.value,
                "result_count": 0,
                "reason": reason,
            }
        job = await repository.create_job(
            session,
            principal,
            run_id=run.id,
            journey_id=request.journey_id,
            categories=[*active, *(c for c, _ in skipped)],
            category_status=status,
            profile=profile.model_dump(mode="json"),
            mode=ResearchMode.SNAPSHOT if request.mode == "snapshot" else engine_mode(adapters),
        )
        await session.commit()
        await session.refresh(run)

    try:
        arq_id = await queue.enqueue(
            RESEARCH_TASK,
            job_id=str(run.id),
            run_id=str(run.id),
            research_job_id=str(job.id),
            **principal.as_job_args(),
        )
    except AdapterUnavailable:
        async with db.user_session(principal) as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run.id)
                .values(status=RunStatus.FAILED, error={"code": "queue_unavailable"})
            )
            await session.commit()
        raise
    async with db.user_session(principal) as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(job_id=arq_id))
        await session.commit()
    logger.info(
        "research_enqueued",
        extra={"job_id": str(job.id), "categories": [c.value for c in active]},
    )
    return job_out(job, run, api_prefix=api_prefix)


async def journey_job(
    db: Database, principal: Principal, journey_id: UUID, *, api_prefix: str = "/api"
) -> ResearchJobOut | None:
    """The newest research job started for a journey that hasn't failed, if any."""
    from app.db.models import AgentRun
    from app.research.models import ResearchJob

    async with db.user_session(principal) as session:
        row = (
            await session.execute(
                select(ResearchJob, AgentRun)
                .join(AgentRun, AgentRun.id == ResearchJob.run_id)
                .where(ResearchJob.journey_id == journey_id, AgentRun.status != RunStatus.FAILED)
                .order_by(ResearchJob.created_at.desc())
                .limit(1)
            )
        ).first()
    return job_out(row[0], row[1], api_prefix=api_prefix) if row else None


# --- reads ------------------------------------------------------------------------------


async def _results(session: Any, results: list[Any], now: datetime) -> list[ResearchResultOut]:
    citations = await repository.citations_for(session, [r.id for r in results])
    modes = await repository.job_modes(session, {r.job_id for r in results})
    return [result_out(r, citations.get(r.id, []), now, modes.get(r.job_id)) for r in results]


async def get_job_detail(
    db: Database, principal: Principal, job_id: UUID, *, api_prefix: str = "/api"
) -> ResearchJobDetail:
    async with db.user_session(principal) as session:
        found = await repository.get_job(session, job_id)
        if found is None:
            raise NotFound("Research job not found")
        results = await repository.results_for_job(session, job_id)
        now = datetime.now(UTC)
        return ResearchJobDetail(
            job=job_out(*found, api_prefix=api_prefix),
            results=await _results(session, results, now),
        )


async def list_jobs(
    db: Database, principal: Principal, *, limit: int = 10, api_prefix: str = "/api"
) -> list[ResearchJobOut]:
    async with db.user_session(principal) as session:
        rows = await repository.list_jobs(session, limit)
        return [job_out(job, run, api_prefix=api_prefix) for job, run in rows]


async def discover(db: Database, principal: Principal, *, api_prefix: str = "/api") -> DiscoverOut:
    """The latest brief, grouped into the seven Discover sections, plus earlier saves."""
    async with db.user_session(principal) as session:
        latest = await repository.list_jobs(session, 1)
        now = datetime.now(UTC)
        job = job_out(*latest[0], api_prefix=api_prefix) if latest else None
        results = await repository.results_for_job(session, job.id) if job else []
        saved = await repository.saved_results(session, exclude_job=job.id if job else None)
        return discover_out(
            job, await _results(session, results, now), await _results(session, saved, now)
        )


# --- actions ------------------------------------------------------------------------------


async def set_saved(
    db: Database, principal: Principal, result_id: UUID, saved: bool
) -> ResearchResultOut:
    from app.research.models import ResearchResult

    async with db.user_session(principal) as session:
        result = await repository.get_result(session, result_id)
        if result is None:
            raise NotFound("Result not found")
        await session.execute(
            update(ResearchResult)
            .where(ResearchResult.id == result_id)
            .values(saved_at=datetime.now(UTC) if saved else None)
        )
        await session.commit()
        await session.refresh(result)
        return (await _results(session, [result], datetime.now(UTC)))[0]


def _journey_category(category: ResearchCategory) -> str:
    return (
        "community"
        if category
        in (
            ResearchCategory.COMMUNITY,
            ResearchCategory.FAITH_AND_WORSHIP,
            ResearchCategory.PROFESSIONAL_NETWORK,
            ResearchCategory.EVENTS,
        )
        else "daily_life"
    )


async def add_to_journey(
    db: Database, principal: Principal, result_id: UUID, journey_id: UUID | None
) -> ResearchResultOut:
    """Append the result to the user's journey as a step, keeping its trust tier and
    sources. Idempotent: a result already on the journey is returned unchanged."""
    from app.domain.enums import StepCategory
    from app.research.models import ResearchResult

    try:
        from app.services.journeys import add_journey_node  # type: ignore[import-not-found]
    except ImportError as exc:
        raise Conflict("Build your plan first", code="journey_required") from exc

    async with db.user_session(principal) as session:
        result = await repository.get_result(session, result_id)
        if result is None:
            raise NotFound("Result not found")
        if result.journey_node_id is None:
            citations = (await repository.citations_for(session, [result.id])).get(result.id, [])
            provenance = Provenance(
                kind=EvidenceKind(result.evidence_kind),
                citations=[
                    Citation(source_url=c.url, source_title=c.title, retrieved_at=c.retrieved_at)
                    for c in citations
                ],
                note="Added from Discover",
            )
            try:
                node_id = await add_journey_node(
                    session,
                    principal,
                    journey_id=journey_id,
                    title=result.title,
                    summary=f"{result.summary}\n\nWhy: {result.relevance}",
                    category=StepCategory(_journey_category(result.category)),
                    provenance=provenance,
                    source_ref=f"research_result:{result.id}",
                )
            except NotFound as exc:
                raise Conflict("Build your plan first", code="journey_required") from exc
            await session.execute(
                update(ResearchResult)
                .where(ResearchResult.id == result.id)
                .values(journey_node_id=node_id)
            )
            await session.commit()
            await session.refresh(result)
        return (await _results(session, [result], datetime.now(UTC)))[0]


async def mark_seen(
    db: Database, principal: Principal, job_id: UUID, *, api_prefix: str = "/api"
) -> ResearchJobOut:
    async with db.user_session(principal) as session:
        found = await repository.get_job(session, job_id)
        if found is None:
            raise NotFound("Research job not found")
        await repository.mark_seen(session, job_id)
        await session.commit()
        job, run = found
        await session.refresh(job)
        return job_out(job, run, api_prefix=api_prefix)
