"""Starting agent runs: create the RLS-owned run row, then enqueue the worker job."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import update

from app.core.container import Container
from app.core.errors import AdapterUnavailable, Conflict, NotFound, UnprocessableEntity
from app.db.models import Action, ActionApproval, AgentRun
from app.domain.enums import ActionStatus, ApprovalStatus, RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.repositories.runs import create_run, get_run
from app.services.agent_registry import get_agent

DIAGNOSTIC_JOB = "run_diagnostic"


async def start_run(
    container: Container,
    principal: Principal,
    kind: RunKind,
    job: str,
    *,
    agent: str | None = None,
    **job_kwargs: Any,
) -> AgentRun:
    async with container.db.user_session(principal) as session:
        run = await create_run(session, principal, kind, agent=agent, input=dict(job_kwargs))
        await session.commit()
    try:
        job_id = await container.queue.enqueue(
            job, job_id=str(run.id), run_id=str(run.id), **principal.as_job_args(), **job_kwargs
        )
    except AdapterUnavailable:
        async with container.db.user_session(principal) as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run.id)
                .values(status=RunStatus.FAILED, error={"code": "queue_unavailable"})
            )
            await session.commit()
        raise
    async with container.db.user_session(principal) as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(job_id=job_id))
        await session.commit()
    run.job_id = job_id
    return run


async def start_agent(
    container: Container, principal: Principal, name: str, raw_input: dict[str, Any]
) -> AgentRun:
    spec = get_agent(name)
    try:
        parsed = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        raise UnprocessableEntity(
            f"The input for '{name}' is not valid",
            code="invalid_agent_input",
            extra={"errors": [e.get("msg") for e in exc.errors()][:10]},
        ) from exc
    return await start_run(
        container,
        principal,
        spec.kind,
        spec.job,
        agent=spec.name,
        **parsed.model_dump(mode="json"),
    )


async def start_diagnostic_run(container: Container, principal: Principal) -> AgentRun:
    return await start_agent(container, principal, "diagnostic", {})


async def cancel_run(container: Container, principal: Principal, run_id: UUID) -> AgentRun:
    """Stop a run that is paused for the person's input.

    Only a paused run can be cancelled: no worker is executing it, and the claim below
    clears the pending review in the same statement, so a concurrent resume (which claims
    on that review) can't revive it. Its open approvals expire and the actions waiting on
    them go back to draft, exactly as if each had been declined. Earlier action outcomes
    remain recorded; cancelling a later review does not undo those outcomes.
    """
    async with container.db.user_session(principal) as session:
        claimed = (
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.status == RunStatus.AWAITING_INPUT)
                .values(status=RunStatus.CANCELLED, pending_review=None)
                .returning(AgentRun.id)
            )
        ).first()
        if claimed is None:
            run = await get_run(session, run_id)
            if run is None:
                raise NotFound("Run not found", code="run_not_found")
            raise Conflict(
                "Only a run that is waiting for you can be cancelled",
                code="run_not_cancellable",
                extra={"status": run.status.value},
            )
        approvals = list(
            (
                await session.execute(
                    update(ActionApproval)
                    .where(
                        ActionApproval.run_id == run_id,
                        ActionApproval.status == ApprovalStatus.PENDING,
                    )
                    .values(status=ApprovalStatus.EXPIRED, decided_at=datetime.now(UTC))
                    .returning(ActionApproval.action_id)
                )
            ).scalars()
        )
        if approvals:
            await session.execute(
                update(Action)
                .where(Action.id.in_(approvals), Action.status == ActionStatus.AWAITING_APPROVAL)
                .values(status=ActionStatus.DRAFT)
            )
        await session.commit()
    events = RunEventEmitter(container.db, principal, run_id, container.notifier)
    await events.run_cancelled("You stopped this run. Check your plan for each action's outcome.")
    async with container.db.user_session(principal) as session:
        run = await get_run(session, run_id)
    assert run is not None
    return run
