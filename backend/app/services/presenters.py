"""ORM -> API contract mapping. The only place that knows both shapes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.contracts.actions import ActionApprovalOut, ActionOut
from app.contracts.appointments import AppointmentOut, AppointmentPreparation
from app.contracts.auth import UserOut
from app.contracts.catalogue import CommunityOut, CulturalGuideOut, EventOut
from app.contracts.common import ProblemDetail
from app.contracts.generated_documents import GeneratedDocumentOut
from app.contracts.graph import (
    GovernanceGraphView,
    GovernanceNodeOut,
    GraphEdgeOut,
    JourneyGraphView,
    TwinGraphView,
    TwinNodeOut,
)
from app.contracts.journey import (
    BasisRef,
    Blocker,
    JourneyEdgeOut,
    JourneyNodeOut,
    JourneyOut,
    JourneySummary,
)
from app.contracts.profile import (
    FullProfileOut,
    HouseholdMemberOut,
    ProfileCompleteness,
    ProfileOut,
    UserGoalOut,
    UserPreferenceOut,
)
from app.contracts.runs import RunOut
from app.db.models import (
    Action,
    ActionApproval,
    AgentRun,
    Appointment,
    Community,
    CulturalGuide,
    Event,
    GeneratedDocument,
    GraphEdge,
    GraphNode,
    Journey,
    JourneyEdge,
    JourneyNode,
    User,
)
from app.domain.actions import SIMULATION_LABEL
from app.domain.enums import (
    GovernanceNodeType,
    GraphEdgeType,
    GraphType,
    StepStatus,
    TwinNodeType,
)
from app.domain.provenance import Provenance
from app.domain.twin import TwinFact
from app.repositories.accounts import read_preferences
from app.repositories.profile import ProfileBundle


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        tenant_id=user.tenant_id,
        display_name=user.display_name,
        is_demo=user.is_demo,
        preferences=read_preferences(user),
        created_at=user.created_at,
    )


# --- graphs ----------------------------------------------------------------------------------


def governance_node_out(node: GraphNode) -> GovernanceNodeOut:
    return GovernanceNodeOut(
        id=node.id,
        entity_type=GovernanceNodeType(node.entity_type),
        key=node.key,
        label=node.label,
        summary=node.summary,
        properties=node.properties_json or {},
        provenance=Provenance.model_validate(node.provenance) if node.provenance else None,
        official_url=node.official_url,
        source_id=node.source_id,
    )


def _facts(properties: dict[str, Any] | None) -> dict[str, TwinFact]:
    facts: dict[str, TwinFact] = {}
    for name, raw in (properties or {}).items():
        try:
            facts[name] = TwinFact.model_validate(raw)
        except ValueError:
            continue  # not a fact-shaped property; never guess its provenance
    return facts


def twin_node_out(node: GraphNode, facts: dict[str, TwinFact] | None = None) -> TwinNodeOut:
    return TwinNodeOut(
        id=node.id,
        entity_type=TwinNodeType(node.entity_type),
        key=node.key,
        label=node.label,
        facts=facts if facts is not None else _facts(node.properties_json),
        updated_at=node.updated_at,
    )


def edge_out(edge: GraphEdge) -> GraphEdgeOut:
    return GraphEdgeOut(
        id=edge.id,
        graph_type=GraphType(edge.graph_type),
        relation=GraphEdgeType(edge.relation),
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        label=edge.label,
        properties=edge.properties_json or {},
    )


def governance_graph_out(nodes: list[GraphNode], edges: list[GraphEdge]) -> GovernanceGraphView:
    return GovernanceGraphView(
        nodes=[governance_node_out(n) for n in nodes],
        edges=[edge_out(e) for e in edges],
        generated_at=datetime.now(UTC),
    )


def twin_graph_out(
    user_nodes: list[GraphNode],
    linked: list[GraphNode],
    edges: list[GraphEdge],
    facts: dict[Any, dict[str, TwinFact]] | None = None,
) -> TwinGraphView:
    return TwinGraphView(
        nodes=[twin_node_out(n, facts.get(n.id) if facts else None) for n in user_nodes],
        linked_governance_nodes=[governance_node_out(n) for n in linked],
        edges=[edge_out(e) for e in edges],
        generated_at=datetime.now(UTC),
    )


# --- journeys -----------------------------------------------------------------------------------


def journey_node_out(node: JourneyNode) -> JourneyNodeOut:
    return JourneyNodeOut(
        id=node.id,
        key=node.key,
        kind=node.kind,
        title=node.title,
        summary=node.summary,
        category=node.category,
        status=node.status,
        position=node.position,
        governance_node_id=node.governance_node_id,
        authority=node.authority,
        official_url=node.official_url,
        estimated_duration_days=node.estimated_duration_days,
        due_by=node.due_by,
        blockers=[Blocker.model_validate(b) for b in node.blockers or []],
        provenance=Provenance.model_validate(node.provenance),
        basis=[BasisRef.model_validate(b) for b in node.basis or []],
        details=node.details or {},
    )


def journey_edge_out(edge: JourneyEdge) -> JourneyEdgeOut:
    return JourneyEdgeOut(
        id=edge.id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        relation=edge.relation,
        properties=edge.properties_json or {},
    )


def journey_out(journey: Journey, nodes: list[JourneyNode], edges: list[JourneyEdge]) -> JourneyOut:
    return JourneyOut(
        id=journey.id,
        title=journey.title,
        status=journey.status,
        summary=journey.summary,
        goals=list(journey.goals or []),
        assumptions=dict(journey.assumptions or {}),
        considerations=list(journey.considerations or []),
        nodes=[journey_node_out(n) for n in nodes],
        edges=[journey_edge_out(e) for e in edges],
        simulation=journey.simulation,
        parent_journey_id=journey.parent_journey_id,
        created_at=journey.created_at,
        updated_at=journey.updated_at,
    )


def journey_summary(journey: Journey, node_count: int, done_count: int) -> JourneySummary:
    return JourneySummary(
        id=journey.id,
        title=journey.title,
        status=journey.status,
        node_count=node_count,
        completed_node_count=done_count,
        parent_journey_id=journey.parent_journey_id,
        updated_at=journey.updated_at,
    )


def journey_graph_out(
    journey: Journey,
    nodes: list[JourneyNode],
    edges: list[JourneyEdge],
    governance: list[GraphNode],
) -> JourneyGraphView:
    return JourneyGraphView(
        journey_id=journey.id,
        nodes=[journey_node_out(n) for n in nodes],
        edges=[journey_edge_out(e) for e in edges],
        governance_nodes=[governance_node_out(n) for n in governance],
        generated_at=datetime.now(UTC),
    )


DONE_STATUSES = frozenset({StepStatus.DONE, StepStatus.NOT_APPLICABLE})


# --- runs & actions -------------------------------------------------------------------------------


def run_out(run: AgentRun) -> RunOut:
    error = None
    if run.error:
        error = ProblemDetail(
            title="The run did not complete",
            status=500,
            code=str(run.error.get("code", "run_error")),
            detail=str(run.error.get("message", "")) or None,
        )
    return RunOut(
        id=run.id,
        agent=run.agent,
        kind=run.kind,
        status=run.status,
        journey_id=run.journey_id,
        last_event_seq=run.event_seq,
        pending_review=run.pending_review,
        error=error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def approval_out(approval: ActionApproval) -> ActionApprovalOut:
    return ActionApprovalOut(
        id=approval.id,
        action_id=approval.action_id,
        run_id=approval.run_id,
        status=approval.status,
        note=approval.note,
        created_at=approval.created_at,
        decided_at=approval.decided_at,
        expires_at=approval.expires_at,
    )


def action_out(action: Action, approval: ActionApproval | None = None) -> ActionOut:
    return ActionOut(
        id=action.id,
        type=action.type,
        status=action.status,
        adapter=action.adapter,
        title=action.title,
        summary=action.summary,
        consequences=list(action.consequences or []),
        task_key=action.task_key,
        service_key=action.service_key,
        journey_id=action.journey_id,
        journey_node_id=action.journey_node_id,
        run_id=action.run_id,
        reversible=action.reversible,
        requires_human_approval=action.requires_human_approval,
        requires_user_authentication=action.requires_user_authentication,
        official_url=action.official_url,
        payload=action.payload or {},
        is_simulated=action.is_simulated,
        simulation_label=SIMULATION_LABEL if action.is_simulated else None,
        evidence=list(action.evidence or []),
        confirmation_source=action.confirmation_source,
        external_reference=action.external_reference,
        approval=approval_out(approval) if approval else None,
        created_at=action.created_at,
        updated_at=action.updated_at,
        executed_at=action.executed_at,
    )


# --- documents, profile, catalogue, appointments --------------------------------------


def generated_document_out(doc: GeneratedDocument) -> GeneratedDocumentOut:
    return GeneratedDocumentOut(
        id=doc.id,
        kind=doc.kind,
        title=doc.title,
        body_markdown=doc.body_markdown,
        status=doc.status,
        journey_id=doc.journey_id,
        journey_node_id=doc.journey_node_id,
        run_id=doc.run_id,
        provenance=Provenance.model_validate(doc.provenance),
        details=doc.details or {},
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        approved_at=doc.approved_at,
    )


def full_profile_out(bundle: ProfileBundle, missing: list[str]) -> FullProfileOut:
    p = bundle.profile
    profile = (
        ProfileOut(
            preferred_name=p.preferred_name,
            nationality=p.nationality,
            country_of_residence=p.country_of_residence,
            date_of_birth=p.date_of_birth,
            occupation=p.occupation,
            persona=p.persona,
            company_name=p.company_name,
            business_activity=p.business_activity,
            monthly_income_aed=p.monthly_income_aed,
            arrival_date=p.arrival_date,
            target_city=p.target_city,
            languages=list(p.languages or []),
            assumptions=dict(p.assumptions or {}),
            onboarding_completed_at=p.onboarding_completed_at,
            updated_at=p.updated_at,
        )
        if p is not None
        else ProfileOut()
    )
    service_keys = {g.id: None for g in bundle.goals}
    return FullProfileOut(
        user=user_out(bundle.user),
        profile=profile,
        household=[
            HouseholdMemberOut(
                id=m.id,
                position=m.position,
                relationship=m.relationship,
                name=m.name,
                date_of_birth=m.date_of_birth,
                nationality=m.nationality,
                relocation_plan=m.relocation_plan,
                arrival_date=m.arrival_date,
                needs_sponsorship=m.needs_sponsorship,
                notes=m.notes,
                graph_node_id=m.graph_node_id,
            )
            for m in bundle.household
        ],
        goals=[
            UserGoalOut(
                id=g.id,
                goal_type=g.goal_type,
                title=g.title,
                description=g.description,
                priority=g.priority,
                status=g.status,
                target_date=g.target_date,
                service_key=service_keys.get(g.id),
                governance_node_id=g.governance_node_id,
                graph_node_id=g.graph_node_id,
            )
            for g in bundle.goals
        ],
        preferences=[
            UserPreferenceOut(
                id=pref.id,
                category=pref.category,
                key=pref.key,
                value=pref.value,
                source=pref.source,
            )
            for pref in bundle.preferences
        ],
        completeness=ProfileCompleteness(complete=not missing, missing=missing),
    )


def community_out(row: Community) -> CommunityOut:
    return CommunityOut.model_validate(row, from_attributes=True)


def event_out(row: Event) -> EventOut:
    return EventOut.model_validate(row, from_attributes=True)


def guide_out(row: CulturalGuide) -> CulturalGuideOut:
    return CulturalGuideOut.model_validate(row, from_attributes=True)


def appointment_out(row: Appointment) -> AppointmentOut:
    preparation = (
        AppointmentPreparation.model_validate(row.preparation) if row.preparation else None
    )
    return AppointmentOut(
        id=row.id,
        title=row.title,
        service_key=row.service_key,
        governance_node_id=row.governance_node_id,
        journey_id=row.journey_id,
        journey_node_id=row.journey_node_id,
        authority=row.authority,
        location=row.location,
        official_url=row.official_url,
        scheduled_at=row.scheduled_at,
        status=row.status,
        external_reference=row.external_reference,
        booking_confirmation=row.booking_confirmation,
        preparation=preparation,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
