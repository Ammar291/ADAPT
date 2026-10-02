"""HUMAN_APPROVAL -> EXECUTION_OR_HANDOFF -> FINAL_PLAN.

Idempotency across resumes matters here. LangGraph re-runs an interrupted node from the
top when the user answers, so everything before `interrupt()` must be safe to repeat:
approvals are created once per action (`ensure_approvals`), and execution re-reads the
stored action first, so an action is never executed twice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.instrumentation import report
from app.agents.journey.context import JourneyContext, ctx
from app.agents.journey.planning import GOAL_LABELS
from app.agents.journey.review import (
    REVIEW_RESPONSE,
    ActionApprovalResponse,
    ActionApprovalReview,
    ActionReviewItem,
    EvidenceBrief,
    SubmissionConfirmationResponse,
    SubmissionConfirmationReview,
    SubmissionReviewItem,
    review_id_for,
    validate_response,
)
from app.agents.journey.spec import NodeSpec, journal, journey_node
from app.agents.journey.state import (
    ActionRecord,
    ApprovalRequest,
    Dependency,
    EligibilityResult,
    EvidenceRecord,
    GeneratedDocumentRef,
    GovernanceContext,
    Requirement,
    Risk,
    Task,
    UserFact,
)
from app.agents.journey.tools import JourneyTools, StartResearchInput
from app.agents.journey.vocab import NodeId, ReviewGate, RiskSeverity, TaskStatus
from app.core.errors import AppError
from app.domain.actions import (
    ActionRequest,
    ApprovalGrant,
    check_transition,
    confirmation_status,
)
from app.domain.enums import ActionKind, ActionStatus, ApprovalStatus


def _with_status(action: ActionRecord, status: ActionStatus, **changes: Any) -> ActionRecord:
    return ActionRecord(**{**action, **changes, "status": status.value})  # type: ignore[typeddict-item]


# --- HUMAN_APPROVAL (gate: action_approval) ----------------------------------------------


class ApprovalIn(TypedDict):
    run_id: str
    journey_id: str
    actions: list[ActionRecord]
    evidence: list[EvidenceRecord]


class ApprovalOut(TypedDict, total=False):
    actions: list[ActionRecord]
    approval_requests: list[ApprovalRequest]


HUMAN_APPROVAL = NodeSpec(
    id=NodeId.HUMAN_APPROVAL,
    label="Your approval",
    description="Nothing consequential happens until you approve it.",
    kind="human",
    input=ApprovalIn,
    output=ApprovalOut,
    fact_keys=frozenset(),
    lane=1,
)


@journey_node(HUMAN_APPROVAL)
async def human_approval(state: ApprovalIn, runtime: Runtime[Any]) -> dict[str, Any]:
    context = ctx(runtime)
    store = context.svc.store
    pending = [
        a
        for a in state["actions"]
        if a["status"] == ActionStatus.PREPARED and a["requires_human_approval"]
    ]
    if not pending:
        return {"_summary": "Nothing needs your approval"}

    run_id, review_id = state["run_id"], review_id_for(state["run_id"], ReviewGate.ACTION_APPROVAL)
    approvals = await store.ensure_approvals(
        run_id=run_id, review_id=review_id, action_ids=[a["id"] for a in pending]
    )
    newly_awaiting = []
    for action in pending:
        approval_id, created = approvals[action["id"]]
        if created:  # only on the first pass: a resumed re-run must not undo decisions
            check_transition(
                ActionStatus.PREPARED,
                ActionStatus.AWAITING_APPROVAL,
                source="agent",
                requires_approval=True,
                approved=False,
                is_simulated=action["is_simulated"],
            )
            newly_awaiting.append(
                _with_status(action, ActionStatus.AWAITING_APPROVAL, approval_id=approval_id)
            )
    if newly_awaiting:
        await store.save_actions(
            journey_id=state["journey_id"], run_id=run_id, actions=newly_awaiting
        )

    evidence = {e["id"]: e for e in state["evidence"]}
    review = ActionApprovalReview(
        review_id=review_id,
        run_id=run_id,
        journey_id=state["journey_id"],
        title="Review and approve your next steps",
        summary=f"{len(pending)} step(s) are ready. Approve each one you want ADAPT to hand "
        "over; nothing is sent on your behalf.",
        items=[
            ActionReviewItem(
                action_id=a["id"],
                approval_id=approvals[a["id"]][0],
                action_type=a["type"],
                title=a["title"],
                summary=a["summary"],
                consequences=a["consequences"],
                payload_preview=a["payload"],
                official_url=a["official_url"],
                reversible=a["reversible"],
                requires_user_authentication=a["requires_user_authentication"],
                is_simulated=a["is_simulated"],
                simulation_label=a["simulation_label"],
                task_key=a["task_key"],
                evidence=[
                    EvidenceBrief(
                        title=evidence[e]["title"],
                        source_url=evidence[e]["source_url"],
                        kind=evidence[e]["kind"],
                    )
                    for e in a["evidence"]
                    if e in evidence
                ],
            )
            for a in pending
        ],
    )
    journal("approval_required", review.title, review_id)
    answer = interrupt(review.model_dump(mode="json"))

    response = REVIEW_RESPONSE.validate_python(answer)
    validate_response(review, response)
    assert isinstance(response, ActionApprovalResponse)
    # The approval rows are authoritative; the resume payload only says "go on".
    rows = await store.approvals([a["id"] for a in pending])
    decided: list[ActionRecord] = []
    outcome: dict[str, str] = {}
    for action in pending:
        row = rows.get(action["id"])
        approved = row is not None and row.status == ApprovalStatus.APPROVED
        target = ActionStatus.APPROVED if approved else ActionStatus.DRAFT
        check_transition(
            ActionStatus.AWAITING_APPROVAL,
            target,
            source="user",
            requires_approval=True,
            approved=approved,
            is_simulated=action["is_simulated"],
        )
        decided.append(_with_status(action, target, approval_id=row.id if row else None))
        outcome[action["id"]] = "approved" if approved else (row.status if row else "undecided")
        journal(
            "approval_resolved",
            f"{action['title']}: {outcome[action['id']]}",
            row.id if row else None,
        )
    await store.save_actions(journey_id=state["journey_id"], run_id=run_id, actions=decided)
    count = sum(1 for v in outcome.values() if v == "approved")
    return {
        "actions": decided,
        "approval_requests": [
            ApprovalRequest(
                review_id=review_id,
                gate=ReviewGate.ACTION_APPROVAL.value,
                status="resolved",
                item_ids=[a["id"] for a in pending],
                outcome=outcome,
            )
        ],
        "_summary": f"{count} of {len(pending)} approved",
    }


# --- EXECUTION_OR_HANDOFF (gate: submission_confirmation) ---------------------------------


class ExecutionIn(TypedDict):
    run_id: str
    journey_id: str
    actions: list[ActionRecord]


class ExecutionOut(TypedDict, total=False):
    actions: list[ActionRecord]
    approval_requests: list[ApprovalRequest]


EXECUTION_OR_HANDOFF = NodeSpec(
    id=NodeId.EXECUTION_OR_HANDOFF,
    label="Hand over to official services",
    description="Carries out only what you approved, as official handoffs. "
    "You confirm the outcome.",
    kind="tool",
    input=ExecutionIn,
    output=ExecutionOut,
    fact_keys=frozenset(),
    lane=1,
)


async def _execute(
    context: JourneyContext, action: ActionRecord, grants: dict[str, Any]
) -> ActionRecord:
    kind = ActionKind(action["type"])
    adapter = context.svc.actions.resolve(kind)
    request = ActionRequest(
        kind=kind,
        service_key=action["service_key"],
        title=action["title"],
        action_id=action["id"],
        task_key=action["task_key"],
        parameters={
            **(action["response_metadata"].get("parameters") or {}),
            "official_url": action["official_url"],
        },
        payload=action["payload"],
    )
    try:
        prepared = await adapter.prepare(request)  # side-effect free; re-derived, not trusted
        row = grants.get(action["id"])
        grant = None
        if prepared.requires_approval:
            if row is None or row.status != ApprovalStatus.APPROVED or row.decided_at is None:
                return _with_status(
                    action,
                    ActionStatus.BLOCKED,
                    response_metadata={
                        **action["response_metadata"],
                        "blocked_reason": "approval missing",
                    },
                )
            grant = ApprovalGrant(
                approval_id=UUID(row.id),
                user_id=context.principal.user_id,
                action_id=action["id"],
                status=ApprovalStatus.APPROVED,
                decided_at=datetime.fromisoformat(row.decided_at),
                expires_at=datetime.fromisoformat(row.expires_at) if row.expires_at else None,
            )
        outcome = await adapter.execute(prepared, grant)
    except (AppError, ValueError) as exc:
        return _with_status(
            action,
            ActionStatus.FAILED,
            response_metadata={
                **action["response_metadata"],
                "error": exc.code if isinstance(exc, AppError) else "invalid_approval",
            },
        )
    check_transition(
        ActionStatus(action["status"]),
        outcome.status,
        source="adapter",
        requires_approval=prepared.requires_approval,
        approved=grant is not None,
        is_simulated=outcome.is_simulated,
        external_reference=outcome.external_reference,
        official_url=outcome.official_url,
    )
    return _with_status(
        action,
        outcome.status,
        official_url=outcome.official_url or action["official_url"],
        is_simulated=outcome.is_simulated,
        simulation_label=outcome.simulation_label,
        external_reference=outcome.external_reference,
        confirmation_source="adapter" if outcome.external_reference else None,
        response_metadata={
            **action["response_metadata"],
            "outcome": {"message": outcome.message, **outcome.response_metadata},
        },
    )


@journey_node(EXECUTION_OR_HANDOFF)
async def execution_or_handoff(state: ExecutionIn, runtime: Runtime[Any]) -> dict[str, Any]:
    context = ctx(runtime)
    store = context.svc.store
    candidates = [
        a
        for a in state["actions"]
        if a["status"] == ActionStatus.APPROVED
        or (a["status"] == ActionStatus.PREPARED and not a["requires_human_approval"])
    ]
    # Re-read what's stored: if this node already executed an action before pausing for
    # confirmation, reuse that result instead of executing again.
    stored = await store.load_actions([a["id"] for a in candidates]) if candidates else {}
    grants = await store.approvals([a["id"] for a in candidates]) if candidates else {}
    executed: list[ActionRecord] = []
    for index, action in enumerate(candidates, start=1):
        previous = stored.get(action["id"])
        if previous and previous["status"] not in (ActionStatus.APPROVED, ActionStatus.PREPARED):
            executed.append(previous)
            continue
        executed.append(await _execute(context, action, grants))
        await report(runtime, f"Handed over: {action['title']}", index / len(candidates))
    if executed:
        await store.save_actions(
            journey_id=state["journey_id"], run_id=state["run_id"], actions=executed
        )

    confirmable = [
        a
        for a in executed
        if a["status"] == ActionStatus.HANDOFF_REQUIRED and a["requires_human_approval"]
    ]
    handoffs = sum(1 for a in executed if a["status"] == ActionStatus.HANDOFF_REQUIRED)
    if not confirmable:
        return {
            "actions": executed,
            "_summary": f"{handoffs} official handoffs ready",
        }

    review = SubmissionConfirmationReview(
        review_id=review_id_for(state["run_id"], ReviewGate.SUBMISSION_CONFIRMATION),
        run_id=state["run_id"],
        journey_id=state["journey_id"],
        title="Tell ADAPT how the official steps went",
        summary="Open each official page and complete the step there. Your report is kept "
        "with the official handoff; only a provider confirmation verifies completion.",
        items=[
            SubmissionReviewItem(
                action_id=a["id"],
                action_type=a["type"],
                title=a["title"],
                official_url=a["official_url"],
                is_simulated=a["is_simulated"],
                simulation_label=a["simulation_label"],
            )
            for a in confirmable
        ],
    )
    journal("approval_required", review.title, review.review_id)
    answer = interrupt(review.model_dump(mode="json"))

    response = REVIEW_RESPONSE.validate_python(answer)
    validate_response(review, response)
    assert isinstance(response, SubmissionConfirmationResponse)
    by_id = {a["id"]: a for a in executed}
    confirmed: list[ActionRecord] = []
    outcome: dict[str, str] = {}
    for answer_item in response.confirmations:
        action = by_id[answer_item.action_id]
        target = confirmation_status(answer_item)
        outcome[action["id"]] = answer_item.outcome
        if target is None:
            continue  # "not yet": stays handed off, still on the user's list
        check_transition(
            ActionStatus.HANDOFF_REQUIRED,
            target,
            source="user",
            requires_approval=True,
            approved=action["approval_id"] is not None,
            is_simulated=action["is_simulated"],
            external_reference=answer_item.reference,
            official_url=action["official_url"],
        )
        updated = _with_status(
            action,
            target,
            external_reference=None,
            confirmation_source=None,
            response_metadata={
                **action["response_metadata"],
                "user_report": {
                    "outcome": answer_item.outcome,
                    "reference": answer_item.reference,
                    "note": answer_item.note,
                    "verified": False,
                },
            },
        )
        by_id[action["id"]] = updated
        confirmed.append(updated)
        journal(
            "approval_resolved",
            f"{action['title']}: user report recorded ({answer_item.outcome})",
            action["id"],
        )
    if confirmed:
        await store.save_actions(
            journey_id=state["journey_id"], run_id=state["run_id"], actions=confirmed
        )
    reported_count = sum(1 for v in outcome.values() if v in ("submitted", "completed"))
    return {
        "actions": list(by_id.values()),
        "approval_requests": [
            ApprovalRequest(
                review_id=review.review_id,
                gate=ReviewGate.SUBMISSION_CONFIRMATION.value,
                status="resolved",
                item_ids=[a["id"] for a in confirmable],
                outcome=outcome,
            )
        ],
        "_summary": f"{handoffs} official handoffs; {reported_count} user reports recorded",
    }


# --- FINAL_PLAN ------------------------------------------------------------------------------


class FinalIn(TypedDict):
    journey_id: str
    tasks: list[Task]
    dependencies: list[Dependency]
    requirements: list[Requirement]
    risks: list[Risk]
    eligibility: list[EligibilityResult]
    generated_documents: list[GeneratedDocumentRef]
    actions: list[ActionRecord]
    user_facts: dict[str, UserFact]
    evidence: list[EvidenceRecord]
    governance_context: GovernanceContext


class FinalOut(TypedDict, total=False):
    final_summary: str
    research_job_ids: list[str]


FINAL_PLAN = NodeSpec(
    id=NodeId.FINAL_PLAN,
    label="Your Abu Dhabi plan",
    description="Brings everything together into one plan and saves it.",
    kind="agent",
    input=FinalIn,
    output=FinalOut,
)


def compose_summary(state: dict[str, Any]) -> str:
    tasks: list[Task] = state.get("tasks", [])
    risks: list[Risk] = state.get("risks", [])
    actions: list[ActionRecord] = state.get("actions", [])
    open_tasks = [t for t in tasks if t["status"] != TaskStatus.DONE]
    ready = [t for t in open_tasks if t["status"] == TaskStatus.READY]
    stages = max((t["level"] for t in tasks), default=-1) + 1
    goals = [GOAL_LABELS.get(g, g) for g in state.get("goals", [])]
    parts = [
        f"Your plan has {len(open_tasks)} steps in {stages} stages"
        + (f" to {', '.join(goals)}" if goals else "")
        + "."
    ]
    if ready:
        names = ", ".join(t["title"] for t in ready[:3])
        parts.append(f"{len(ready)} can start now, including {names}.")
    blocking = [r for r in risks if r["severity"] == RiskSeverity.BLOCKING]
    warnings = [r for r in risks if r["severity"] == RiskSeverity.WARNING]
    if blocking:
        parts.append(f"{len(blocking)} risk(s) need attention before you continue.")
    if warnings:
        parts.append(f"{len(warnings)} thing(s) are worth checking.")
    handoffs = [a for a in actions if a["status"] == ActionStatus.HANDOFF_REQUIRED]
    confirmed = [
        a
        for a in actions
        if a["status"] in (ActionStatus.SUBMITTED, ActionStatus.COMPLETED)
        and a.get("confirmation_source") == "adapter"
        and not a["is_simulated"]
        and str(a.get("external_reference") or "").strip()
    ]
    if handoffs:
        parts.append(f"{len(handoffs)} step(s) are ready to continue on official sites.")
    if confirmed:
        parts.append(
            f"External providers confirmed {len(confirmed)} step(s) as submitted or completed."
        )
    if any(a["is_simulated"] for a in actions):
        parts.append("Booking and submission previews are marked DEMO / SIMULATED.")
    return " ".join(parts)


@journey_node(FINAL_PLAN)
async def final_plan(state: FinalIn, runtime: Runtime[Any]) -> dict[str, Any]:
    from app.agents.journey.facts import goals_of

    context = ctx(runtime)
    summary = compose_summary({**state, "goals": goals_of(state["user_facts"])})
    snapshot = plan_snapshot(dict(state), summary)
    await context.svc.store.save_plan(
        journey_id=state["journey_id"],
        plan=snapshot,
        tasks=state["tasks"],
        dependencies=state["dependencies"],
        status="active",
        summary=summary,
    )
    await report(runtime, "Plan saved", 0.8)
    research = await JourneyTools(context).start_research(
        StartResearchInput(journey_id=state["journey_id"])
    )
    return {
        "final_summary": summary,
        "research_job_ids": [research.job_id] if research.job_id else [],
        "_summary": f"{len(state['tasks'])} steps saved",
    }


PLAN_KEYS = (
    "tasks",
    "dependencies",
    "requirements",
    "risks",
    "eligibility",
    "generated_documents",
    "actions",
    "evidence",
)


def plan_snapshot(state: dict[str, Any], summary: str | None) -> dict[str, Any]:
    """The journey's persisted plan: everything the plan views need, JSON only."""
    from app.agents.journey.facts import goals_of

    facts = state.get("user_facts", {})
    governance = state.get("governance_context") or {}
    return {
        "version": 1,
        "summary": summary,
        "goals": goals_of(facts),
        "facts": list(facts.values()),
        "root_services": governance.get("root_services", []),
        "coverage_notes": governance.get("notes", []),
        **{key: state.get(key, []) for key in PLAN_KEYS},
    }
