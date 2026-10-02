"""Use cases behind the journey-agent routes (the routes stay thin).

The resume protocol for human gates:

1. The graph pauses. The run is `awaiting_input` and `agent_runs.pending_review` holds
   the gate payload.
2. The user answers. Action approvals are decided one by one (approve/reject routes);
   the other gates are answered in one POST to /agents/{run_id}/resume.
3. When the gate is fully answered, the run is claimed atomically: `awaiting_input` ->
   `queued`, but only while the same review is still pending. This makes a double
   submission impossible. Then `resume_journey` is enqueued with the answer.
4. The worker resumes the graph with `Command(resume=answer)` on the same thread.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.agents.journey.review import (
    PENDING_REVIEW,
    REVIEW_RESPONSE,
    ActionApprovalResponse,
    ActionApprovalReview,
    DocumentCorrection,
    DocumentCorrectionResponse,
    ReviewMismatch,
    validate_response,
)
from app.agents.journey.schemas import (
    PrepareActionRequest,
    StartJourneyRequest,
    WhatIfRequest,
)
from app.agents.journey.simulation import ScenarioError, validate_changes
from app.agents.journey.store_pg import PgJourneyStore
from app.agents.journey.tools import action_record
from app.agents.journey.vocab import ReviewGate
from app.core.container import Container
from app.core.errors import AdapterUnavailable, AppError, Conflict, NotFound, UnprocessableEntity
from app.db.models import Action, ActionApproval, AgentRun, Journey, JourneyNode
from app.domain.actions import (
    ActionRequest,
    ApprovalGrant,
    check_transition,
)
from app.domain.enums import (
    ActionKind,
    ActionStatus,
    ApprovalStatus,
    ConfirmationSource,
    JourneyStatus,
    RunKind,
    RunStatus,
)
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.repositories.runs import create_run, get_run

logger = logging.getLogger(__name__)

RUN_JOURNEY, RESUME_JOURNEY, RUN_WHAT_IF = "run_journey", "resume_journey", "run_what_if"


def _title(prompt: str) -> str:
    first = prompt.strip().split("\n", 1)[0]
    return (first[:117] + "…") if len(first) > 120 else first or "Your move to Abu Dhabi"


async def _enqueue_or_fail(
    container: Container, principal: Principal, run: AgentRun, job: str, **kwargs: Any
) -> None:
    try:
        job_id = await container.queue.enqueue(
            job, job_id=str(run.id), run_id=str(run.id), **principal.as_job_args(), **kwargs
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


# --- journeys --------------------------------------------------------------------------------


async def start_journey(
    container: Container, principal: Principal, body: StartJourneyRequest
) -> tuple[Journey, AgentRun]:
    async with container.db.user_session(principal) as session:
        journey = Journey(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            title=_title(body.prompt),
            status=JourneyStatus.DRAFT,
        )
        session.add(journey)
        await session.flush()
        job_input = body.model_copy(update={"journey_id": journey.id}).model_dump(mode="json")
        run = await create_run(
            session,
            principal,
            RunKind.JOURNEY,
            agent="journey",
            input=job_input,
            journey_id=journey.id,
        )
        await session.commit()
    await _enqueue_or_fail(container, principal, run, RUN_JOURNEY, **job_input)
    return journey, run


async def latest_run(
    session: Any, journey_id: UUID, kind: RunKind | None = None
) -> AgentRun | None:
    query = select(AgentRun).where(AgentRun.journey_id == journey_id)
    if kind is not None:
        query = query.where(AgentRun.kind == kind)
    return (
        await session.execute(query.order_by(AgentRun.created_at.desc()).limit(1))
    ).scalar_one_or_none()


async def start_what_if(
    container: Container, principal: Principal, base_journey_id: UUID, body: WhatIfRequest
) -> tuple[Journey, AgentRun]:
    changes = [c.model_dump(mode="json") for c in body.changes]
    async with container.db.user_session(principal) as session:
        base = await session.get(Journey, base_journey_id)
        if base is None:
            raise NotFound("Journey not found", code="journey_not_found")
        if base.status is JourneyStatus.SCENARIO:
            raise Conflict(
                "A what-if can't be based on another what-if", code="scenario_of_scenario"
            )
        if (
            not (base.plan or {}).get("tasks")
            or await latest_run(session, base.id, RunKind.JOURNEY) is None
        ):
            raise Conflict(
                "This journey has no plan to compare against yet", code="journey_not_ready"
            )
        facts = {f["key"]: f for f in (base.plan or {}).get("facts", [])}
        try:
            validated = validate_changes(changes, facts)
        except ScenarioError as exc:
            raise UnprocessableEntity(str(exc), code="invalid_scenario") from exc
        scenario = Journey(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            title=(
                "What if: " + "; ".join(f"{c['label'].lower()} = {c['value']}" for c in validated)
            )[:300],
            status=JourneyStatus.SCENARIO,
            parent_journey_id=base.id,
            goals=list(base.goals or []),
        )
        session.add(scenario)
        await session.flush()
        job_input = {"base_journey_id": str(base.id), "changes": changes}
        run = await create_run(
            session,
            principal,
            RunKind.WHAT_IF,
            agent="what_if",
            input=job_input,
            journey_id=scenario.id,
        )
        await session.commit()
    await _enqueue_or_fail(container, principal, run, RUN_WHAT_IF, **job_input)
    return scenario, run


# --- reviews & approvals -------------------------------------------------------------------------


async def _resume(
    container: Container, principal: Principal, run_id: UUID, review_id: str, answer: dict[str, Any]
) -> bool:
    """Claim the paused run for this review (exactly once) and enqueue its resumption."""
    async with container.db.user_session(principal) as session:
        claimed = (
            await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == RunStatus.AWAITING_INPUT,
                    AgentRun.pending_review["review_id"].astext == review_id,
                )
                .values(status=RunStatus.QUEUED, pending_review=None)
                .returning(AgentRun.pending_review)
            )
        ).first()
        await session.commit()
    if claimed is None:
        return False
    events = RunEventEmitter(container.db, principal, run_id, container.notifier)
    gate = answer.get("gate")
    if gate and gate != ReviewGate.ACTION_APPROVAL.value:
        # Action approvals are announced one by one as they're decided; the other gates are
        # answered in one go, under the review's id (as `approval_required` announced them).
        await events.approval_resolved(approval_id=review_id, decision="approved", gate=gate)
    await events.run_status(RunStatus.QUEUED, "resuming after your review")
    try:
        await container.queue.enqueue(
            RESUME_JOURNEY,
            job_id=f"{run_id}:{review_id}",
            run_id=str(run_id),
            **principal.as_job_args(),
            answer=answer,
        )
    except AdapterUnavailable:
        logger.warning("resume_enqueue_failed", extra={"run_id": str(run_id)})
        await events.run_failed(
            "queue_unavailable",
            "Background processing is unavailable; try again shortly",
            retryable=True,
        )
        raise
    return True


async def pending_review(container: Container, principal: Principal, run_id: UUID) -> Any:
    async with container.db.user_session(principal) as session:
        run = await get_run(session, run_id)
    if run is None:
        raise NotFound("Run not found")
    if run.status is not RunStatus.AWAITING_INPUT or not run.pending_review:
        raise NotFound("This run is not waiting for a review", code="no_pending_review")
    review = PENDING_REVIEW.validate_python(run.pending_review)
    if isinstance(review, ActionApprovalReview) and review.items:
        # The stored payload is what was asked; the approval rows say what's been decided.
        async with container.db.user_session(principal) as session:
            rows = (
                await session.execute(
                    select(ActionApproval).where(
                        ActionApproval.id.in_([UUID(i.approval_id) for i in review.items])
                    )
                )
            ).scalars()
            decided = {str(a.id): a for a in rows}
        for item in review.items:
            if (approval := decided.get(item.approval_id)) is not None:
                item.approval_status = approval.status.value  # type: ignore[assignment]
                item.decided_at = approval.decided_at
    return review


async def _open_approvals(session: Any, review_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(ActionApproval)
                .where(
                    ActionApproval.review_id == review_id,
                    ActionApproval.status == ApprovalStatus.PENDING,
                )
            )
        ).scalar_one()
    )


async def decide_action(
    container: Container,
    principal: Principal,
    action_id: UUID,
    decision: str,
    note: str | None,
    *,
    resume: bool = True,
) -> tuple[Action, bool]:
    """Record the user's decision on one action. The approval row is the authority the
    graph (and the database trigger) checks before anything executes."""
    approve = decision == "approve"
    async with container.db.user_session(principal) as session:
        action = await session.get(Action, action_id)
        if action is None:
            raise NotFound("Action not found", code="action_not_found")
        approval = (
            await session.execute(
                select(ActionApproval)
                .where(ActionApproval.action_id == action_id)
                # Locked: a cancel or a second tap deciding the same approval waits, then
                # sees it decided instead of overwriting it.
                .with_for_update()
            )
        ).scalar_one_or_none()
        if approval is None or approval.status is not ApprovalStatus.PENDING:
            raise Conflict("This action has no open approval", code="approval_not_pending")
        if approval.expires_at is not None and approval.expires_at <= datetime.now(UTC):
            raise Conflict(
                "This approval has expired; prepare the action again", code="approval_expired"
            )
        target = ActionStatus.APPROVED if approve else ActionStatus.DRAFT
        try:
            check_transition(
                action.status,
                target,
                source="user",
                requires_approval=True,
                approved=approve,
                is_simulated=action.is_simulated,
            )
        except ValueError as exc:
            raise Conflict(str(exc), code="invalid_action_transition") from exc
        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_at = datetime.now(UTC)
        approval.note = note
        await session.flush()  # the trigger checks the approval before the action moves on
        action.status = target
        action.approval_id = approval.id
        run_id, review_id = approval.run_id, approval.review_id
        remaining = await _open_approvals(session, review_id) if review_id else 0
        await session.commit()
        await session.refresh(action)
    if remaining and review_id:
        # Decisions on one review can commit concurrently, and neither transaction sees the
        # other's uncommitted decision. Counting again after our own commit means the last
        # one to commit always sees the final tally (`_resume` claims the run only once).
        async with container.db.user_session(principal) as session:
            remaining = await _open_approvals(session, review_id)

    resumed = False
    if run_id is not None:
        events = RunEventEmitter(container.db, principal, run_id, container.notifier)
        await events.approval_resolved(
            approval_id=approval.id,
            decision="approved" if approve else "rejected",
            gate="action_approval",
        )
        if resume and remaining == 0 and review_id:
            resumed = await _resume(
                container,
                principal,
                run_id,
                review_id,
                ActionApprovalResponse(review_id=review_id).model_dump(mode="json"),
            )
    elif approve:
        action = await _execute_now(container, principal, action)
    return action, resumed


async def _execute_now(container: Container, principal: Principal, action: Action) -> Action:
    """An action prepared outside a run (e.g. from voice): hand it off once approved."""
    adapter = container.adapters.actions.resolve(action.type)
    request = ActionRequest(
        kind=action.type,
        service_key=action.service_key or "",
        title=action.title,
        action_id=str(action.id),
        task_key=action.task_key,
        parameters={
            **(action.response_metadata or {}).get("parameters", {}),
            "official_url": action.official_url,
        },
        payload=action.payload or {},
    )
    async with container.db.user_session(principal) as session:
        row = await session.get(Action, action.id, with_for_update=True)
        if row is None:
            raise NotFound("Action not found")
        if row.status is not ActionStatus.APPROVED:
            return row
        approval = (
            await session.execute(
                select(ActionApproval).where(ActionApproval.action_id == action.id)
            )
        ).scalar_one()
        assert row is not None and approval.decided_at is not None
        try:
            prepared = await adapter.prepare(request)
            outcome = await adapter.execute(
                prepared,
                ApprovalGrant(
                    approval_id=approval.id,
                    user_id=principal.user_id,
                    action_id=str(action.id),
                    status=approval.status,
                    decided_at=approval.decided_at,
                    expires_at=approval.expires_at,
                ),
            )
            check_transition(
                row.status,
                outcome.status,
                source="adapter",
                requires_approval=True,
                approved=True,
                is_simulated=outcome.is_simulated,
                external_reference=outcome.external_reference,
                official_url=outcome.official_url,
            )
        except (AppError, ValueError) as exc:
            logger.info(
                "manual_action_failed",
                extra={"action_id": str(action.id), "error": type(exc).__name__},
            )
            row.status = ActionStatus.FAILED
        else:
            row.status = outcome.status
            row.official_url = outcome.official_url or row.official_url
            row.executed_at = datetime.now(UTC)
            row.external_reference = outcome.external_reference
            row.confirmation_source = (
                ConfirmationSource.ADAPTER if outcome.external_reference else None
            )
            row.response_metadata = {
                **(row.response_metadata or {}),
                "outcome": {"message": outcome.message, **outcome.response_metadata},
            }
        await session.commit()
        await session.refresh(row)
        return row


async def submit_review(
    container: Container, principal: Principal, run_id: UUID, body: dict[str, Any]
) -> tuple[AgentRun, bool, int]:
    review = await pending_review(container, principal, run_id)
    try:
        response = REVIEW_RESPONSE.validate_python(body)
        validate_response(review, response)
    except ReviewMismatch as exc:
        raise Conflict(str(exc), code="review_mismatch") from exc
    except ValueError as exc:
        raise UnprocessableEntity(
            "The answer is not valid for this review", code="invalid_review_answer"
        ) from exc

    remaining, resumed = 0, False
    if isinstance(review, ActionApprovalReview):
        assert isinstance(response, ActionApprovalResponse)
        for decision in response.decisions:
            await decide_action(
                container,
                principal,
                UUID(decision.action_id),
                decision.decision,
                decision.note,
                resume=False,
            )
        async with container.db.user_session(principal) as session:
            remaining = await _open_approvals(session, review.review_id)
        if remaining == 0:
            resumed = await _resume(
                container,
                principal,
                run_id,
                review.review_id,
                ActionApprovalResponse(review_id=review.review_id).model_dump(mode="json"),
            )
    else:
        resumed = await _resume(
            container, principal, run_id, review.review_id, response.model_dump(mode="json")
        )
        if not resumed:
            raise Conflict("This review was already answered", code="review_already_answered")
    async with container.db.user_session(principal) as session:
        run = await get_run(session, run_id)
    assert run is not None
    return run, resumed, remaining


# --- manual preparation (voice) ------------------------------------------------------------------


async def prepare_action(
    container: Container, principal: Principal, body: PrepareActionRequest
) -> tuple[Action, ActionApproval]:
    async with container.db.user_session(principal) as session:
        journey = await session.get(Journey, body.journey_id)
        if journey is None:
            raise NotFound("Journey not found", code="journey_not_found")
        tasks = (journey.plan or {}).get("tasks", [])
        node_key = None
        if body.journey_node_id is not None:
            node = await session.get(JourneyNode, body.journey_node_id)
            node_key = node.key if node else None
        task = next(
            (
                t
                for t in tasks
                if t["key"] in {body.task_key, node_key}
                or (body.service_key and t["node_key"] == body.service_key)
            ),
            None,
        )
    if task is None:
        raise NotFound("That step isn't in this journey", code="journey_step_not_found")
    kind = body.type or (ActionKind(task["action_type"]) if task.get("action_type") else None)
    if kind is None:
        raise UnprocessableEntity(
            "ADAPT can't prepare an action for this step", code="no_action_for_step"
        )
    action_id = str(uuid4())
    adapter = container.adapters.actions.resolve(kind)
    request = ActionRequest(
        kind=kind,
        service_key=task["node_key"],
        title=task["title"],
        action_id=action_id,
        task_key=task["key"],
        parameters={
            "official_url": task["official_url"],
            "channel_name": task["portal"] or task["authority"],
            "requires_uae_pass": task["requires_login"],
        },
        payload={"task": task["title"]},
    )
    prepared = await adapter.prepare(request)  # no side effects
    record = action_record(action_id, prepared, list(task.get("evidence_ids", []))[:3])
    record["status"] = ActionStatus.AWAITING_APPROVAL.value
    store = PgJourneyStore(container.db, principal)
    await store.save_actions(journey_id=str(journey.id), run_id="", actions=[record])
    async with container.db.user_session(principal) as session:
        approval = ActionApproval(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            action_id=UUID(action_id),
            review_id=f"manual:{action_id}",
        )
        session.add(approval)
        await session.flush()
        row = await session.get(Action, UUID(action_id))
        assert row is not None
        row.approval_id = approval.id
        await session.commit()
        await session.refresh(row)
        await session.refresh(approval)
    return row, approval


# --- documents reviewed on the Documents page -------------------------------------------------

_hook_container: Container | None = None


def _container_for_hooks() -> Container:
    """Listeners are called with a principal only, so they build their own container."""
    global _hook_container
    if _hook_container is None:
        from app.core.config import get_settings

        _hook_container = Container.create(get_settings())
    return _hook_container


async def resume_if_waiting(principal: Principal, document_id: UUID) -> None:
    """Registered in app.documents.hooks.document_reviewed_listeners. If the user finishes
    reviewing a document on the Documents page while a journey waits at its
    document-correction gate, continue the journey once every document in that review
    is confirmed. Corrections were already applied there, so the answer only confirms."""
    from app.documents.service import DocumentIntelligence

    container = _container_for_hooks()
    async with container.db.user_session(principal) as session:
        runs = list(
            (
                await session.execute(
                    select(AgentRun).where(
                        AgentRun.kind == RunKind.JOURNEY,
                        AgentRun.status == RunStatus.AWAITING_INPUT,
                        AgentRun.pending_review["gate"].astext == "document_correction",
                    )
                )
            ).scalars()
        )
    intelligence = DocumentIntelligence(container.db, principal, container.adapters)
    for run in runs:
        review = PENDING_REVIEW.validate_python(run.pending_review)
        ids = [item.document_id for item in review.items]  # type: ignore[union-attr]
        if str(document_id) not in ids:
            continue
        statuses = [getattr((await intelligence.analyze(UUID(i))).status, "value", "") for i in ids]
        if any(s != "confirmed" for s in statuses):
            continue  # other documents in this review still need the user
        answer = DocumentCorrectionResponse(
            review_id=review.review_id,
            documents=[
                DocumentCorrection(document_id=i, corrections=[], confirm=True) for i in ids
            ],
        )
        await _resume(
            container, principal, run.id, review.review_id, answer.model_dump(mode="json")
        )


# --- editing a plan: step done / answer ---------------------------------------------------------


async def update_node(
    container: Container,
    principal: Principal,
    journey_id: UUID,
    node_key: str,
    *,
    done: bool = False,
    answer: str | None = None,
    fact_key: str | None = None,
) -> None:
    """Record "I did this step" or the answer a step waits on, then re-plan deterministically."""
    from app.agents.journey import updates
    from app.agents.journey.facts import fact

    async with container.db.user_session(principal) as session:
        journey = await session.get(Journey, journey_id)
        if journey is None:
            raise NotFound("Journey not found", code="journey_not_found")
        if journey.status is JourneyStatus.SCENARIO:
            raise Conflict(
                "A what-if can't be edited; change your plan instead", code="scenario_read_only"
            )
        previous = dict(journey.plan or {})
        status = journey.status
    task = next((t for t in previous.get("tasks", []) if t["key"] == node_key), None)
    if task is None:
        raise NotFound("That step isn't in this journey", code="journey_step_not_found")
    facts = {f["key"]: f for f in previous.get("facts", [])}
    if done:
        if task.get("kind") in {"service", "appointment"}:
            raise Conflict(
                "This official step needs confirmation from its provider",
                code="provider_confirmation_required",
            )
        item = updates.done_fact(task, str(journey_id))
    else:
        try:
            key = updates.open_question(node_key, previous, fact_key)
            value = updates.parse_answer(key, answer or "")
        except updates.NothingToAnswer as exc:
            raise Conflict(str(exc), code="nothing_to_answer") from exc
        except ScenarioError as exc:
            raise UnprocessableEntity(str(exc), code="invalid_answer") from exc
        item = fact(key, value, "user_stated", source_ref=f"journey:{journey_id}", confirmed=True)
    facts[item["key"]] = item
    store = PgJourneyStore(container.db, principal)
    stored = await store.load_actions(
        [a["id"] for a in previous.get("actions", []) if not a["id"].startswith("preview:")]
    )
    actions = [stored.get(a["id"], a) for a in previous.get("actions", [])]
    plan = updates.replan(await store.governance(), previous, facts, actions)
    await store.save_plan(
        journey_id=str(journey_id),
        plan=plan,
        tasks=plan["tasks"],
        dependencies=plan["dependencies"],
        status=status.value,
        summary=plan["summary"],
    )
