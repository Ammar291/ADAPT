"""ARQ job functions. Each job acts for exactly one principal, re-checked via RLS."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agents.context import AgentContext
from app.agents.diagnostic import build_diagnostic_graph
from app.agents.runner import execute_run
from app.domain.enums import RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.repositories.runs import get_run
from app.workers.deps import WorkerDeps

logger = logging.getLogger(__name__)


async def _prepare(
    ctx: dict[str, Any], run_id: str, user_id: str, tenant_id: str, kind: RunKind
) -> tuple[WorkerDeps, AgentContext, str] | None:
    deps: WorkerDeps = ctx["deps"]
    principal = Principal.from_job_args(user_id, tenant_id)
    async with deps.db.user_session(principal) as session:
        run = await get_run(session, UUID(run_id))
    if run is None or run.kind is not kind:
        logger.warning("job_run_not_found", extra={"run_id": run_id})
        return None
    if run.status is not RunStatus.QUEUED:
        logger.info("job_run_already_started", extra={"run_id": run_id, "status": run.status})
        return None
    events = RunEventEmitter(deps.db, principal, run.id, deps.notifier)
    agent_ctx = AgentContext(
        principal=principal, run_id=run.id, events=events, db=deps.db, adapters=deps.adapters
    )
    return deps, agent_ctx, run.thread_id


async def run_diagnostic(ctx: dict[str, Any], *, run_id: str, user_id: str, tenant_id: str) -> str:
    prepared = await _prepare(ctx, run_id, user_id, tenant_id, RunKind.DIAGNOSTIC)
    if prepared is None:
        return "skipped"
    deps, agent_ctx, thread_id = prepared
    outcome = await execute_run(
        graph=build_diagnostic_graph(deps.checkpointer),
        ctx=agent_ctx,
        kind=RunKind.DIAGNOSTIC,
        thread_id=thread_id,
        graph_input={},
    )
    return outcome.status
