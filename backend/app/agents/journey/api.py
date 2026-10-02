"""Journey-agent routes (mounted under /api by app/api/router.py).

POST /journey                        start a journey run (202)
GET  /journey  ·  GET /journey/{id}  read journeys (detail adds risks, actions, review)
GET  /journey/{id}/what-if/variables what a what-if may change, with current values
POST /journey/{id}/simulate          start a what-if on a copy of the journey (202)
GET  /agents/what_if/topology        the what-if graph for visualisation
GET  /agents/{run_id}/review         the open human-in-the-loop gate of a paused run
POST /agents/{run_id}/resume         answer that gate (resumes the run)
POST /actions/prepare                prepare a step as an action awaiting approval
POST /actions/{id}/approve|reject    decide one action (resumes the run when last)
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Query, status
from sqlalchemy import select

from app.agents.journey import service
from app.agents.journey.review import (
    ActionApprovalResponse,
    DocumentCorrectionResponse,
    SubmissionConfirmationResponse,
)
from app.agents.journey.schemas import (
    ActionDecisionBody,
    ActionDecisionOut,
    ConsiderationOut,
    EligibilityOut,
    EvidenceOut,
    JourneyDetailOut,
    JourneyStarted,
    NodeAnswer,
    PendingReviewOut,
    PrepareActionRequest,
    PreparedActionOut,
    RequirementOut,
    ReviewAccepted,
    RiskOut,
    ScenarioVariableOut,
    SimulationResultOut,
    StartJourneyRequest,
    WhatIfAgentInput,
    WhatIfRequest,
    WhatIfStarted,
)
from app.agents.journey.simulation import SCENARIO_VARIABLES
from app.agents.journey.topology import WHAT_IF_TOPOLOGY
from app.api.deps import ContainerDep, PrincipalDep, UserSession
from app.contracts.actions import ActionOut
from app.contracts.agents import AgentTopology
from app.contracts.journey import JourneySummary
from app.core.errors import NotFound
from app.db.models import Action, ActionApproval, GeneratedDocument, Journey
from app.domain.enums import ActionStatus, ApprovalStatus, RunKind, RunStatus
from app.services import journeys as journey_reads
from app.services.agent_registry import AgentSpec, register_agent
from app.services.presenters import (
    action_out,
    approval_out,
    generated_document_out,
    journey_out,
    journey_summary,
    run_out,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["journey"])

register_agent(
    AgentSpec(
        name="journey",
        kind=RunKind.JOURNEY,
        job="run_journey",
        input_model=StartJourneyRequest,
        description="Plans a personalised Abu Dhabi journey from the user's request, profile "
        "and documents; pauses for approval before any consequential step.",
    )
)
register_agent(
    AgentSpec(
        name="what_if",
        kind=RunKind.WHAT_IF,
        job="run_what_if",
        input_model=WhatIfAgentInput,
        description="Simulates a changed assumption on a copy of a journey and reports what "
        "changes. Never modifies the journey.",
    )
)


def _urls(container: Any, run_id: UUID) -> dict[str, str]:
    prefix = container.settings.api_prefix
    return {
        "events_url": f"{prefix}/agents/{run_id}/events",
        "stream_url": f"{prefix}/agents/{run_id}/stream",
    }


# --- journeys ---


@router.post(
    "/journey",
    response_model=JourneyStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start planning a journey",
    description="Creates the journey and queues the journey agent. Follow `events_url`; "
    "when the run pauses (`approval_required`), fetch GET /agents/{run_id}/review.",
)
async def start_journey(
    body: StartJourneyRequest, principal: PrincipalDep, container: ContainerDep
) -> JourneyStarted:
    journey, run = await service.start_journey(container, principal, body)
    return JourneyStarted(journey_id=journey.id, run=run_out(run), **_urls(container, run.id))


@router.get("/journey", response_model=list[JourneySummary], summary="Your journeys, newest first")
async def list_journeys(principal: PrincipalDep, session: UserSession) -> list[JourneySummary]:
    rows = await journey_reads.list_journeys(session, principal)
    return [journey_summary(j, total, done) for j, total, done in rows]


async def journey_detail(session: Any, principal: Any, journey_id: UUID) -> JourneyDetailOut:
    journey = await journey_reads.get_journey(session, principal, journey_id)
    nodes, edges = await journey_reads.journey_parts(session, journey)
    plan = journey.plan or {}
    actions = list(
        (
            await session.execute(
                select(Action)
                .where(Action.journey_id == journey.id)
                .order_by(Action.created_at, Action.title, Action.id)
            )
        ).scalars()
    )
    approvals = (
        {
            a.action_id: a
            for a in (
                await session.execute(
                    select(ActionApproval).where(
                        ActionApproval.action_id.in_([a.id for a in actions])
                    )
                )
            ).scalars()
        }
        if actions
        else {}
    )
    documents = list(
        (
            await session.execute(
                select(GeneratedDocument)
                .where(GeneratedDocument.journey_id == journey.id)
                .order_by(GeneratedDocument.created_at)
            )
        ).scalars()
    )
    kind = RunKind.WHAT_IF if journey.parent_journey_id else RunKind.JOURNEY
    run = await service.latest_run(session, journey.id, kind)  # not e.g. research runs
    pending = None
    if run is not None and run.status is RunStatus.AWAITING_INPUT and run.pending_review:
        pending = run.pending_review
    base = journey_out(journey, nodes, edges).model_dump()
    return JourneyDetailOut.model_validate(
        {
            **base,
            "considerations": [
                c
                for raw in journey.considerations or []
                if (c := ConsiderationOut.stored(raw)) is not None
            ],
            "risks": [RiskOut.model_validate(r) for r in plan.get("risks", [])],
            "requirements": [
                RequirementOut.model_validate(r) for r in plan.get("requirements", [])
            ],
            "eligibility": [EligibilityOut.model_validate(r) for r in plan.get("eligibility", [])],
            "evidence": [EvidenceOut.model_validate(r) for r in plan.get("evidence", [])],
            "actions": [action_out(a, approvals.get(a.id)) for a in actions],
            "generated_documents": [generated_document_out(d) for d in documents],
            "latest_run": run_out(run) if run else None,
            "pending_review": pending,
            "simulation_result": SimulationResultOut.model_validate(journey.simulation)
            if journey.simulation
            else None,
        }
    )


@router.get(
    "/journey/{journey_id}", response_model=JourneyDetailOut, summary="One journey, in full"
)
async def read_journey(
    journey_id: UUID, principal: PrincipalDep, session: UserSession
) -> JourneyDetailOut:
    return await journey_detail(session, principal, journey_id)


@router.post(
    "/journey/{journey_id}/nodes/{node_key}/done",
    response_model=JourneyDetailOut,
    summary="Mark a personal preparation step done",
    description="Records a local preparation task as stated by you and re-plans. "
    "Official service and appointment steps require provider confirmation; "
    "409 `provider_confirmation_required` if manual completion is attempted.",
)
async def mark_done(
    journey_id: UUID, node_key: str, principal: PrincipalDep, container: ContainerDep
) -> JourneyDetailOut:
    await service.update_node(container, principal, journey_id, node_key, done=True)
    async with container.db.user_session(principal) as session:
        return await journey_detail(session, principal, journey_id)


@router.post(
    "/journey/{journey_id}/nodes/{node_key}/answer",
    response_model=JourneyDetailOut,
    summary="Answer the question a step is waiting on",
    description="Records the answer as a fact you stated (e.g. monthly income) and re-plans. "
    "409 `nothing_to_answer` when the step isn't waiting for anything.",
)
async def answer_node(
    journey_id: UUID,
    node_key: str,
    body: NodeAnswer,
    principal: PrincipalDep,
    container: ContainerDep,
) -> JourneyDetailOut:
    await service.update_node(
        container, principal, journey_id, node_key, answer=body.answer, fact_key=body.key
    )
    async with container.db.user_session(principal) as session:
        return await journey_detail(session, principal, journey_id)


# --- what-if ---


@router.get(
    "/journey/{journey_id}/what-if/variables",
    response_model=list[ScenarioVariableOut],
    summary="What a what-if can change, with the journey's current values",
)
async def what_if_variables(
    journey_id: UUID, principal: PrincipalDep, session: UserSession
) -> list[ScenarioVariableOut]:
    journey: Journey = await journey_reads.get_journey(session, principal, journey_id)
    facts = {f["key"]: f.get("value") for f in (journey.plan or {}).get("facts", [])}
    return [
        ScenarioVariableOut(
            key=v.key, label=v.label, type=v.type, options=list(v.options), current=facts.get(v.key)
        )
        for v in SCENARIO_VARIABLES
    ]


@router.post(
    "/journey/{journey_id}/simulate",
    response_model=WhatIfStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Simulate a what-if on a copy of the journey",
    description="The journey itself is never changed. The result is stored on a new scenario "
    "journey (GET /journey/{scenario_journey_id} → simulation_result).",
)
async def simulate(
    journey_id: UUID, body: WhatIfRequest, principal: PrincipalDep, container: ContainerDep
) -> WhatIfStarted:
    scenario, run = await service.start_what_if(container, principal, journey_id, body)
    return WhatIfStarted(
        base_journey_id=journey_id,
        scenario_journey_id=scenario.id,
        run=run_out(run),
        **_urls(container, run.id),
    )


@router.get(
    "/agents/what_if/topology",
    response_model=AgentTopology,
    tags=["agents"],
    summary="Nodes and edges of the what-if graph",
)
async def what_if_topology() -> AgentTopology:
    return WHAT_IF_TOPOLOGY


# --- human in the loop ---


@router.get(
    "/agents/{run_id}/review",
    response_model=PendingReviewOut,
    tags=["agents"],
    summary="The open review of a paused run",
    description="Render the Review / Approve step from this. 404 `no_pending_review` when "
    "the run isn't waiting for the user.",
)
async def read_review(run_id: UUID, principal: PrincipalDep, container: ContainerDep) -> Any:
    return await service.pending_review(container, principal, run_id)


@router.post(
    "/agents/{run_id}/resume",
    response_model=ReviewAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agents"],
    summary="Answer the open review and resume the run",
)
async def resume(
    run_id: UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: ActionApprovalResponse
    | DocumentCorrectionResponse
    | SubmissionConfirmationResponse = Body(discriminator="gate"),
) -> ReviewAccepted:
    run, resumed, remaining = await service.submit_review(
        container, principal, run_id, body.model_dump(mode="json")
    )
    return ReviewAccepted(run=run_out(run), resumed=resumed, remaining=remaining)


@router.post(
    "/actions/prepare",
    response_model=PreparedActionOut,
    tags=["actions"],
    summary="Prepare a journey step as an action awaiting your approval (no side effects)",
)
async def prepare_action(
    body: PrepareActionRequest, principal: PrincipalDep, container: ContainerDep
) -> PreparedActionOut:
    action, approval = await service.prepare_action(container, principal, body)
    return PreparedActionOut(action=action_out(action, approval), approval=approval_out(approval))


@router.get(
    "/actions",
    response_model=list[ActionOut],
    tags=["actions"],
    summary="Your actions, newest first (each with its approval)",
)
async def list_actions(
    session: UserSession,
    status: ActionStatus | None = None,
    journey_id: UUID | None = None,
    approval: ApprovalStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ActionOut]:
    query = select(Action, ActionApproval).outerjoin(
        ActionApproval, ActionApproval.action_id == Action.id
    )
    if status is not None:
        query = query.where(Action.status == status)
    if journey_id is not None:
        query = query.where(Action.journey_id == journey_id)
    if approval is not None:
        query = query.where(ActionApproval.status == approval)
    rows = await session.execute(query.order_by(Action.created_at.desc()).limit(limit))
    return [action_out(a, ap) for a, ap in rows]


@router.get(
    "/actions/{action_id}", response_model=ActionOut, tags=["actions"], summary="One action"
)
async def read_action(action_id: UUID, session: UserSession) -> ActionOut:
    action = await session.get(Action, action_id)
    if action is None:
        raise NotFound("Action not found", code="action_not_found")
    approval = (
        await session.execute(select(ActionApproval).where(ActionApproval.action_id == action_id))
    ).scalar_one_or_none()
    return action_out(action, approval)


async def _decide(
    action_id: UUID, decision: str, body: ActionDecisionBody, principal: Any, container: Any
) -> ActionDecisionOut:
    action, resumed = await service.decide_action(
        container, principal, action_id, decision, body.note
    )
    async with container.db.user_session(principal) as session:
        approval = (
            await session.execute(
                select(ActionApproval).where(ActionApproval.action_id == action_id)
            )
        ).scalar_one_or_none()
    if decision == "reject":
        message = "Declined. Nothing was sent, and the step stays on your list."
    elif action.status.value == "handoff_required":
        message = "Official handoff ready. Continue on the official site."
    elif action.status.value in {"submitted", "completed"}:
        message = "The external provider confirmed the action status shown here."
    elif action.status.value == "failed":
        message = "The action could not be completed. Review its recorded outcome."
    else:
        message = "Approved. ADAPT will continue once your other decisions are in."
    return ActionDecisionOut(
        action=action_out(action, approval), message=message, run_resumed=resumed
    )


@router.post(
    "/actions/{action_id}/approve",
    response_model=ActionDecisionOut,
    tags=["actions"],
    summary="Approve one action",
)
async def approve_action(
    action_id: UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: ActionDecisionBody | None = None,
) -> ActionDecisionOut:
    return await _decide(action_id, "approve", body or ActionDecisionBody(), principal, container)


@router.post(
    "/actions/{action_id}/reject",
    response_model=ActionDecisionOut,
    tags=["actions"],
    summary="Decline one action",
)
async def reject_action(
    action_id: UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: ActionDecisionBody | None = None,
) -> ActionDecisionOut:
    return await _decide(action_id, "reject", body or ActionDecisionBody(), principal, container)


# --- documents reviewed elsewhere ---

try:
    from app.documents.hooks import document_reviewed_listeners

    if service.resume_if_waiting not in document_reviewed_listeners:
        document_reviewed_listeners.append(service.resume_if_waiting)
except ImportError:  # the documents workstream isn't part of this build
    pass
