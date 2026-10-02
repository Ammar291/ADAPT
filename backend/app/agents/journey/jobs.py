"""ARQ jobs of the journey agent (registered in app/workers/settings.py).

* run_journey    - start the journey graph for a queued run
* resume_journey - resume a run paused at a human gate, with the user's answer
* run_what_if    - simulate a scenario on a copy of a journey

Each job acts for exactly one principal, re-checked through RLS when the run is loaded,
and only picks up a run that is `queued`, so a duplicate delivery is a no-op.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langgraph.types import Command
from sqlalchemy import update

from app.adapters.llm import DemoLLM
from app.agents.journey.context import JourneyContext, JourneyServices
from app.agents.journey.demo import register_demo_responders
from app.agents.journey.gates import review_announcer
from app.agents.journey.graph import build_journey_graph, journey_input
from app.agents.journey.integrations import KnowledgeEvidence, PlatformDocuments, PlatformResearch
from app.agents.journey.nodes.human import plan_snapshot
from app.agents.journey.service import latest_run
from app.agents.journey.simulation import ScenarioError, build_simulation_graph, run_simulation
from app.agents.journey.store_pg import PgJourneyStore
from app.agents.runner import execute_run
from app.db.models import AgentRun, Journey
from app.domain.enums import JourneyStatus, RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.repositories.runs import get_run
from app.workers.deps import WorkerDeps

logger = logging.getLogger(__name__)


async def _load(
    ctx: dict[str, Any], run_id: str, user_id: str, tenant_id: str, kind: RunKind
) -> tuple[WorkerDeps, Principal, AgentRun] | None:
    deps: WorkerDeps = ctx["deps"]
    principal = Principal.from_job_args(user_id, tenant_id)
    async with deps.db.user_session(principal) as session:
        run = await get_run(session, UUID(run_id))
    if run is None or run.kind is not kind:
        logger.warning("journey_job_run_not_found", extra={"run_id": run_id})
        return None
    if run.status is not RunStatus.QUEUED:
        logger.info("journey_job_not_queued", extra={"run_id": run_id, "status": run.status})
        return None
    return deps, principal, run


def is_deterministic(run: AgentRun | None) -> bool:
    return bool(run is not None and (run.input or {}).get("deterministic"))


def journey_context(
    deps: WorkerDeps, principal: Principal, run: AgentRun, *, deterministic: bool | None = None
) -> JourneyContext:
    """`deterministic` (default: the run's own request) swaps the language model for the
    rule-based parser and drafting templates, and asks research for the curated snapshot,
    so a scripted run gives the same plan with or without an LLM key."""
    events = RunEventEmitter(deps.db, principal, run.id, deps.notifier)
    fixed = is_deterministic(run) if deterministic is None else deterministic
    llm = DemoLLM() if fixed and not isinstance(deps.adapters.llm, DemoLLM) else deps.adapters.llm
    register_demo_responders(llm)
    services = JourneyServices(
        store=PgJourneyStore(deps.db, principal),
        documents=PlatformDocuments(deps.db, principal, deps.adapters, events),
        evidence=KnowledgeEvidence(deps.db, deps.adapters),
        research=PlatformResearch(
            deps.db,
            deps.queue,
            principal,
            deps.adapters,
            deps.settings.api_prefix,
            snapshot=fixed,
        ),
        actions=deps.adapters.actions,
        llm=llm,
    )
    return JourneyContext(
        principal=principal,
        run_id=run.id,
        events=events,
        db=deps.db,
        adapters=deps.adapters,
        services=services,
    )


async def _ensure_journey(
    deps: WorkerDeps, principal: Principal, run: AgentRun, **values: Any
) -> UUID:
    """Runs started through the generic POST /agents/run have no journey row yet."""
    if run.journey_id is not None:
        return run.journey_id
    async with deps.db.user_session(principal) as session:
        journey = Journey(tenant_id=principal.tenant_id, user_id=principal.user_id, **values)
        session.add(journey)
        await session.flush()
        await session.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(journey_id=journey.id)
        )
        await session.commit()
        return journey.id


async def run_journey(
    ctx: dict[str, Any],
    *,
    run_id: str,
    user_id: str,
    tenant_id: str,
    prompt: str,
    language: str = "en",
    channel: str = "text",
    document_ids: list[str] | None = None,
    journey_id: str | None = None,
    deterministic: bool = False,  # read from the run's input by journey_context
) -> str:
    loaded = await _load(ctx, run_id, user_id, tenant_id, RunKind.JOURNEY)
    if loaded is None:
        return "skipped"
    deps, principal, run = loaded
    journey = await _ensure_journey(
        deps,
        principal,
        run,
        title=(prompt.strip()[:117] or "Your move to Abu Dhabi"),
        status=JourneyStatus.DRAFT,
    )
    context = journey_context(deps, principal, run)
    outcome = await execute_run(
        graph=build_journey_graph(deps.checkpointer),
        ctx=context,
        kind=RunKind.JOURNEY,
        thread_id=run.thread_id,
        graph_input=journey_input(
            user_id=user_id,
            journey_id=str(journey),
            run_id=run_id,
            text=prompt,
            language=language,
            channel=channel,
            document_ids=[str(d) for d in document_ids or []],
        ),
        summary_key="final_summary",
        on_interrupt=review_announcer(context),
    )
    return outcome.status


async def resume_journey(
    ctx: dict[str, Any], *, run_id: str, user_id: str, tenant_id: str, answer: dict[str, Any]
) -> str:
    loaded = await _load(ctx, run_id, user_id, tenant_id, RunKind.JOURNEY)
    if loaded is None:
        return "skipped"
    deps, principal, run = loaded
    context = journey_context(deps, principal, run)
    outcome = await execute_run(
        graph=build_journey_graph(deps.checkpointer),
        ctx=context,
        kind=RunKind.JOURNEY,
        thread_id=run.thread_id,
        graph_input=Command(resume=answer),
        summary_key="final_summary",
        on_interrupt=review_announcer(context),
    )
    return outcome.status


def plan_overrides(plan: dict[str, Any]) -> dict[str, Any]:
    """The persisted plan's view of the journey (includes edits made after the run)."""
    if not plan.get("tasks"):
        return {}
    keys = ("tasks", "dependencies", "requirements", "eligibility", "risks")
    overrides: dict[str, Any] = {k: plan[k] for k in keys if k in plan}
    if plan.get("facts"):
        overrides["user_facts"] = {f["key"]: f for f in plan["facts"]}
    return overrides


async def run_what_if(
    ctx: dict[str, Any],
    *,
    run_id: str,
    user_id: str,
    tenant_id: str,
    base_journey_id: str,
    changes: list[dict[str, Any]],
) -> str:
    loaded = await _load(ctx, run_id, user_id, tenant_id, RunKind.WHAT_IF)
    if loaded is None:
        return "skipped"
    deps, principal, run = loaded
    async with deps.db.user_session(principal) as session:
        base = await session.get(Journey, UUID(base_journey_id))
        base_run = await latest_run(session, UUID(base_journey_id), RunKind.JOURNEY)
    # A what-if of a scripted plan is scripted too.
    context = journey_context(deps, principal, run, deterministic=is_deterministic(base_run))
    if base is None or base_run is None:
        await context.events.run_started(RunKind.WHAT_IF)
        await context.events.run_failed(
            "journey_not_ready", "That journey has no plan to compare against"
        )
        return "failed"
    scenario = await _ensure_journey(
        deps,
        principal,
        run,
        title="What if…",
        status=JourneyStatus.SCENARIO,
        parent_journey_id=base.id,
    )
    store = PgJourneyStore(deps.db, principal)

    async def save_scenario(values: dict[str, Any]) -> None:
        # The scenario is its own journey; the base journey is never written to.
        await store.save_plan(
            journey_id=str(scenario),
            plan=plan_snapshot(values, values.get("final_summary")),
            tasks=values.get("tasks", []),
            dependencies=values.get("dependencies", []),
            status=JourneyStatus.SCENARIO.value,
            summary=values.get("final_summary"),
            simulation=values.get("simulation"),
        )

    try:
        outcome = await run_simulation(
            journey_graph=build_journey_graph(deps.checkpointer),
            simulation_graph=build_simulation_graph(deps.checkpointer),
            context=context,
            base_thread_id=base_run.thread_id,
            base_journey_id=str(base.id),
            base_run_id=str(base_run.id),
            scenario_journey_id=str(scenario),
            thread_id=run.thread_id,
            changes=changes,
            on_complete=save_scenario,
            base_overrides=plan_overrides(base.plan or {}),
        )
    except ScenarioError as exc:
        await context.events.run_started(RunKind.WHAT_IF)
        await context.events.run_failed("invalid_scenario", str(exc))
        return "failed"
    return outcome.status
