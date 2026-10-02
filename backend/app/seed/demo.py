"""The fictional demo household: a complete, consistent private dataset for one user.

Everything here is invented for the demo — no real person's data. The household:
Arjun Mehta (founder of "Mehta Analytics Ltd", setting up in ADGM), his wife Priya and
their daughter Aanya, who join him later. The same persona appears on the clearly-marked
SPECIMEN documents in `app.documents.specimens`.

The seed is deterministic and idempotent: the demo account has fixed ids and is rebuilt
from scratch on every run. It exercises every private table: profile, household, goals,
preferences, the user graph (with links into the governance graph), a journey with
dependency edges and blockers, a completed agent run with its event log, generated
documents, actions awaiting approval and appointments. Nothing claims external success:
actions are prepared or awaiting approval, appointments are only planned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.auth import UserPreferencesUpdate
from app.contracts.profile import (
    HouseholdMemberIn,
    OnboardingProfileRequest,
    ProfileFields,
    UserGoalIn,
    UserPreferenceIn,
)
from app.db.models import (
    Action,
    ActionApproval,
    AgentRun,
    Appointment,
    GeneratedDocument,
    GraphNode,
    Journey,
    JourneyEdge,
    JourneyNode,
    Tenant,
    User,
)
from app.db.session import Database
from app.domain.enums import (
    ActionKind,
    ActionStatus,
    AppointmentStatus,
    ApprovalStatus,
    BlockerKind,
    ConsentStatus,
    EvidenceKind,
    GeneratedDocumentKind,
    GeneratedDocumentStatus,
    GoalType,
    GraphEdgeType,
    HouseholdRelationship,
    JourneyEdgeType,
    JourneyStatus,
    PreferenceCategory,
    Priority,
    RelocationPlan,
    RunKind,
    RunStatus,
    StepCategory,
    StepStatus,
    TwinNodeType,
)
from app.domain.principal import Principal
from app.domain.provenance import Provenance
from app.events.emitter import RunEventEmitter
from app.repositories.graph import GovernanceGraphRepository, UserGraphRepository
from app.repositories.runs import create_run
from app.services import profile as profile_service

logger = logging.getLogger("adapt.seed")

DEMO_TENANT_ID = UUID("5eed0000-0000-4000-8000-000000000001")
DEMO_USER_ID = UUID("5eed0000-0000-4000-8000-000000000002")
DEMO_PROVIDER = "demo"
DEMO_SUBJECT = "seed:demo-household"
DEMO_PRINCIPAL = Principal(user_id=DEMO_USER_ID, tenant_id=DEMO_TENANT_ID, is_demo=True)
JURISDICTION = "adgm"

ONBOARDING = OnboardingProfileRequest(
    display_name="Arjun (demo)",
    profile=ProfileFields(
        preferred_name="Arjun",
        nationality="IND",
        country_of_residence="IND",
        date_of_birth=date(1990, 4, 12),
        occupation="Data scientist and startup founder",
        persona="founder",
        company_name="Mehta Analytics Ltd",
        business_activity="Data analytics software and consulting",
        monthly_income_aed=45000,
        arrival_date=date(2026, 11, 15),
        target_city="Abu Dhabi",
        languages=["en", "hi"],
        assumptions={"company.jurisdiction": JURISDICTION},
    ),
    household=[
        HouseholdMemberIn(
            relationship=HouseholdRelationship.SPOUSE,
            name="Priya",
            date_of_birth=date(1992, 8, 30),
            nationality="IND",
            relocation_plan=RelocationPlan.LATER,
            arrival_date=date(2027, 1, 10),
            needs_sponsorship=True,
        ),
        HouseholdMemberIn(
            relationship=HouseholdRelationship.CHILD,
            name="Aanya",
            date_of_birth=date(2020, 6, 3),
            nationality="IND",
            relocation_plan=RelocationPlan.LATER,
            arrival_date=date(2027, 1, 10),
            needs_sponsorship=True,
        ),
    ],
    goals=[
        UserGoalIn(
            goal_type=GoalType.ESTABLISH_COMPANY,
            title="Set up Mehta Analytics in ADGM",
            priority=Priority.HIGH,
        ),
        UserGoalIn(
            goal_type=GoalType.RESIDENCY, title="Get my investor residency", priority=Priority.HIGH
        ),
        UserGoalIn(
            goal_type=GoalType.SPONSOR_FAMILY,
            title="Bring Priya and Aanya over",
            priority=Priority.HIGH,
            target_date=date(2027, 1, 10),
        ),
        UserGoalIn(
            goal_type=GoalType.FIND_HOUSING,
            title="Rent a family apartment",
            priority=Priority.MEDIUM,
        ),
        UserGoalIn(
            goal_type=GoalType.SCHOOLING, title="Find a school for Aanya", priority=Priority.MEDIUM
        ),
        UserGoalIn(
            goal_type=GoalType.COMMUNITY, title="Meet other founders", priority=Priority.LOW
        ),
    ],
    preferences=[
        UserPreferenceIn(
            category=PreferenceCategory.HOUSING, key="preferred_area", value="Al Reem Island"
        ),
        UserPreferenceIn(category=PreferenceCategory.HOUSING, key="bedrooms", value=3),
        UserPreferenceIn(category=PreferenceCategory.BUDGET, key="annual_rent_aed", value=150000),
        UserPreferenceIn(
            category=PreferenceCategory.COMMUNITY,
            key="interests",
            value=["startup founders", "running", "family activities"],
        ),
        UserPreferenceIn(category=PreferenceCategory.SCHOOLING, key="curriculum", value="IB"),
        UserPreferenceIn(category=PreferenceCategory.LANGUAGE, key="conversation", value="en"),
    ],
    consents=UserPreferencesUpdate(
        preferred_language="en",
        ui_locale="en",
        community_personalization=ConsentStatus.GRANTED,
        faith_personalization=ConsentStatus.NOT_ASKED,
    ),
)

# Documents the demo user has (user graph -> governance document types). The marriage
# certificate is NOT attested yet, which is what blocks the family visa in the journey.
HELD_DOCUMENTS: tuple[tuple[str, str, str], ...] = (
    ("passport.self", TwinNodeType.PASSPORT.value, "document.passport"),
    ("document.photo", TwinNodeType.DOCUMENT.value, "document.photo"),
)
UNATTESTED_MARRIAGE_CERTIFICATE = "document.marriage_certificate"

GOAL_SERVICES = (
    "service.company_registration_adgm",
    "service.residence_visa_investor",
    "service.family_residence_visa",
    "service.tawtheeq",
    "service.corporate_tax_registration",
)

CATEGORY_BY_SERVICE: dict[str, StepCategory] = {
    "service.company_registration_adgm": StepCategory.BUSINESS,
    "service.commercial_license_mainland": StepCategory.BUSINESS,
    "service.trade_name_reservation": StepCategory.BUSINESS,
    "service.initial_approval": StepCategory.BUSINESS,
    "service.establishment_card": StepCategory.BUSINESS,
    "service.corporate_tax_registration": StepCategory.FINANCE,
    "service.entry_permit_investor": StepCategory.RESIDENCY,
    "service.medical_fitness": StepCategory.HEALTH,
    "service.health_insurance": StepCategory.HEALTH,
    "service.emirates_id": StepCategory.RESIDENCY,
    "service.residence_visa_investor": StepCategory.RESIDENCY,
    "service.tawtheeq": StepCategory.HOUSING,
    "service.mofa_attestation": StepCategory.FAMILY,
    "service.family_residence_visa": StepCategory.FAMILY,
}


@dataclass
class DemoSeedReport:
    user_id: UUID
    journey_id: UUID
    journey_nodes: int
    run_id: UUID
    actions: int
    appointments: int


async def _reset(db: Database) -> None:
    async with db.public_session() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": DEMO_TENANT_ID})
        await session.commit()


async def _create_account(session: AsyncSession) -> None:
    session.add(Tenant(id=DEMO_TENANT_ID, name="Demo household", is_demo=True))
    await session.flush()
    session.add(
        User(
            id=DEMO_USER_ID,
            tenant_id=DEMO_TENANT_ID,
            display_name="Arjun (demo)",
            is_demo=True,
            preferences={},
            auth_provider=DEMO_PROVIDER,
            auth_subject=DEMO_SUBJECT,
        )
    )
    await session.flush()


async def _link_documents(session: AsyncSession) -> None:
    """User-graph document holdings (no document contents: facts come from uploads)."""
    graph = UserGraphRepository(session)
    governance = GovernanceGraphRepository(session)
    me = await graph.get_by_key("person.self")
    if me is None:
        return
    targets = await governance.by_keys([gov for _, _, gov in HELD_DOCUMENTS])
    for key, entity_type, gov_key in HELD_DOCUMENTS:
        label = targets[gov_key].label if gov_key in targets else gov_key
        node = await graph.upsert_node(entity_type=entity_type, key=key, label=label)
        await graph.link(GraphEdgeType.HAS_DOCUMENT, me, node)
        if gov_key in targets:
            await graph.link(GraphEdgeType.INSTANCE_OF, node, targets[gov_key])
    certificate = await graph.upsert_node(
        entity_type=TwinNodeType.DOCUMENT.value,
        key=UNATTESTED_MARRIAGE_CERTIFICATE,
        label="Marriage certificate (not yet attested)",
    )
    await graph.link(GraphEdgeType.HAS_DOCUMENT, me, certificate)


def _provenance(node: GraphNode | None) -> dict[str, Any]:
    if node is not None and node.provenance:
        return dict(node.provenance)
    return Provenance.ai("Planned by ADAPT from the governance graph.").model_dump(mode="json")


async def _plan_journey(session: AsyncSession, principal: Principal) -> Journey:
    """Seed-only traversal of the governance graph (the product planner is the journey
    agent's). Orders the goal services and everything they depend on, resolving
    OR-dependencies by the chosen jurisdiction."""
    governance = GovernanceGraphRepository(session)
    nodes = await governance.nodes()
    by_id = {n.id: n for n in nodes}
    by_key = {n.key: n for n in nodes}
    edges = await governance.edges_between(list(by_id))
    depends: dict[UUID, list[UUID]] = {}
    satisfied_by: dict[UUID, list[UUID]] = {}
    requires: dict[UUID, list[UUID]] = {}
    for e in edges:
        if e.relation == GraphEdgeType.DEPENDS_ON:
            depends.setdefault(e.source_node_id, []).append(e.target_node_id)
        elif e.relation == GraphEdgeType.SATISFIED_BY:
            satisfied_by.setdefault(e.source_node_id, []).append(e.target_node_id)
        elif e.relation == GraphEdgeType.REQUIRES:
            requires.setdefault(e.source_node_id, []).append(e.target_node_id)

    def resolve(node_id: UUID) -> UUID:
        node = by_id[node_id]
        if node.entity_type != "dependency":
            return node_id
        options = satisfied_by.get(node_id, [])
        for option in options:
            if (by_id[option].properties_json or {}).get("jurisdiction") == JURISDICTION:
                return option
        return options[0] if options else node_id

    order: list[UUID] = []
    parents: dict[UUID, list[UUID]] = {}
    seen: set[UUID] = set()

    def visit(node_id: UUID) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        deps = [resolve(t) for t in depends.get(node_id, [])]
        parents[node_id] = deps
        for dep in deps:
            visit(dep)
        order.append(node_id)

    for key in GOAL_SERVICES:
        if key in by_key:
            visit(by_key[key].id)

    _, _, user_edges = await UserGraphRepository(session).graph()
    held = {e.target_node_id for e in user_edges if e.relation == GraphEdgeType.INSTANCE_OF}

    journey = Journey(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        title="Arjun's move to Abu Dhabi",
        status=JourneyStatus.ACTIVE,
        summary="Company in ADGM first, then investor residency, then family sponsorship.",
        goals=["establish_company", "residency", "sponsor_family", "find_housing"],
        assumptions={"company.jurisdiction": JURISDICTION},
        considerations=[
            {
                "id": "consideration.corporate_tax",
                "title": "Corporate tax registration",
                "detail": "New UAE companies must register for corporate tax with the FTA.",
                "category": "finance",
                "provenance": Provenance.ai(
                    "Surfaced by ADAPT from the governance graph."
                ).model_dump(mode="json"),
            }
        ],
        plan={"generated_by": "seed", "jurisdiction": JURISDICTION},
    )
    session.add(journey)
    await session.flush()

    created: dict[UUID, JourneyNode] = {}
    for position, node_id in enumerate(order):
        service = by_id[node_id]
        blockers: list[dict[str, Any]] = []
        for req_id in requires.get(node_id, []):
            req = by_id.get(req_id)
            if req is None or req.entity_type != "document" or req_id in held:
                continue
            kind = (
                BlockerKind.ATTESTATION
                if req.key == "document.marriage_certificate_attested"
                else BlockerKind.MISSING_DOCUMENT
            )
            blockers.append(
                {
                    "kind": kind.value,
                    "message": f"Needs: {req.label}",
                    "resolution": "Upload it, or complete the step that produces it.",
                    "related_node_key": None,
                    "related_document": req.key,
                }
            )
        waiting_on = [p for p in parents.get(node_id, []) if p in by_id]
        if waiting_on:
            status = StepStatus.BLOCKED
            blockers.append(
                {
                    "kind": BlockerKind.DEPENDENCY.value,
                    "message": "Waiting for: " + ", ".join(by_id[p].label for p in waiting_on),
                    "resolution": None,
                    "related_node_key": by_id[waiting_on[0]].key,
                    "related_document": None,
                }
            )
        elif blockers:
            status = StepStatus.NEEDS_INFO
        else:
            status = StepStatus.READY
        row = JourneyNode(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            journey_id=journey.id,
            key=service.key,
            kind="task",
            title=service.label,
            summary=service.summary or "",
            category=CATEGORY_BY_SERVICE.get(service.key, StepCategory.DAILY_LIFE),
            status=status,
            position=position,
            governance_node_id=service.id,
            official_url=service.official_url,
            blockers=blockers,
            provenance=_provenance(service),
            basis=[
                {
                    "key": "profile.assumptions",
                    "label": "You chose ADGM for your company",
                    "fact_refs": ["profile:user_profiles:assumptions"],
                }
            ]
            if service.key == "service.company_registration_adgm"
            else [],
        )
        session.add(row)
        created[node_id] = row
    await session.flush()

    for node_id, deps in parents.items():
        for dep in deps:
            if node_id in created and dep in created:
                session.add(
                    JourneyEdge(
                        tenant_id=principal.tenant_id,
                        user_id=principal.user_id,
                        journey_id=journey.id,
                        source_node_id=created[node_id].id,
                        target_node_id=created[dep].id,
                        relation=JourneyEdgeType.DEPENDS_ON,
                    )
                )
    await session.flush()
    return journey


async def _journey_node(session: AsyncSession, journey: Journey, key: str) -> JourneyNode | None:
    return (
        await session.execute(
            select(JourneyNode).where(JourneyNode.journey_id == journey.id, JourneyNode.key == key)
        )
    ).scalar_one_or_none()


async def _documents_and_actions(
    session: AsyncSession, principal: Principal, journey: Journey, run: AgentRun
) -> tuple[list[GeneratedDocument], list[Action]]:
    owner = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
    governance = await GovernanceGraphRepository(session).by_keys(
        ["service.company_registration_adgm", "service.tawtheeq", "service.family_residence_visa"]
    )
    adgm = governance.get("service.company_registration_adgm")
    tawtheeq = governance.get("service.tawtheeq")
    family = governance.get("service.family_residence_visa")
    adgm_node = await _journey_node(session, journey, "service.company_registration_adgm")
    family_node = await _journey_node(session, journey, "service.family_residence_visa")

    now = datetime.now(UTC)
    docs = [
        GeneratedDocument(
            **owner,
            kind=GeneratedDocumentKind.CHECKLIST,
            title="Documents to prepare before you fly",
            body_markdown=(
                "# Before you fly\n\n"
                "- [x] Passport valid for at least six more months\n"
                "- [ ] Marriage certificate attested in India, then by UAE MoFA after arrival\n"
                "- [ ] Aanya's birth certificate, attested the same way\n"
                "- [ ] Passport-style photos for everyone\n\n"
                "_Confirm current requirements on the official pages linked in your journey._"
            ),
            status=GeneratedDocumentStatus.APPROVED,
            approved_at=now,
            journey_id=journey.id,
            run_id=run.id,
            provenance=_provenance(family),
        ),
        GeneratedDocument(
            **owner,
            kind=GeneratedDocumentKind.COVER_LETTER,
            title="Cover letter: family residence visa for Priya and Aanya",
            body_markdown=(
                "To whom it may concern,\n\n"
                "I, Arjun Mehta, founder of Mehta Analytics Ltd (ADGM), request residence visas "
                "for my wife Priya and our daughter Aanya under my sponsorship. Our attested "
                "marriage certificate, registered tenancy contract and proof of income are "
                "attached.\n\n"
                "Kind regards,\nArjun Mehta\n\n"
                "_Draft prepared by ADAPT for your review. Fictional demo content._"
            ),
            status=GeneratedDocumentStatus.DRAFT,
            journey_id=journey.id,
            journey_node_id=family_node.id if family_node else None,
            run_id=run.id,
            provenance=Provenance.ai("Drafted by ADAPT; review before using it.").model_dump(
                mode="json"
            ),
        ),
    ]
    session.add_all(docs)
    await session.flush()

    actions: list[Action] = []
    if adgm is not None and adgm.official_url:
        incorporate = Action(
            **owner,
            journey_id=journey.id,
            journey_node_id=adgm_node.id if adgm_node else None,
            run_id=run.id,
            task_key="service.company_registration_adgm",
            service_key=adgm.key,
            type=ActionKind.GOVERNMENT_PORTAL,
            status=ActionStatus.AWAITING_APPROVAL,
            adapter="official_handoff",
            title="Start ADGM incorporation for Mehta Analytics Ltd",
            summary="Open the ADGM online registry with your company details ready to copy.",
            consequences=[
                "Opens the ADGM registry in a new tab. Nothing is submitted by ADAPT.",
                "You complete and submit the application yourself on the official portal.",
            ],
            reversible=True,
            requires_human_approval=True,
            requires_user_authentication=False,
            official_url=adgm.official_url,
            payload={
                "company_name": "Mehta Analytics Ltd",
                "activity": "Data analytics software and consulting",
            },
            evidence=[{"source_url": adgm.official_url, "title": adgm.label}],
            is_simulated=False,
        )
        session.add(incorporate)
        await session.flush()
        session.add(
            ActionApproval(
                **owner, action_id=incorporate.id, run_id=run.id, status=ApprovalStatus.PENDING
            )
        )
        actions.append(incorporate)
    if tawtheeq is not None and tawtheeq.official_url:
        lease = Action(
            **owner,
            journey_id=journey.id,
            run_id=run.id,
            task_key="service.tawtheeq",
            service_key=tawtheeq.key,
            type=ActionKind.OFFICIAL_HANDOFF,
            status=ActionStatus.PREPARED,
            adapter="official_handoff",
            title="Register your tenancy contract (Tawtheeq)",
            summary="Once you sign a lease, register it on TAMM. You sign in there with UAE PASS.",
            consequences=[
                "Opens TAMM in a new tab. ADAPT never sees or stores your UAE PASS credentials."
            ],
            reversible=True,
            requires_human_approval=False,
            requires_user_authentication=True,
            official_url=tawtheeq.official_url,
            is_simulated=False,
        )
        session.add(lease)
        actions.append(lease)
    await session.flush()
    return docs, actions


async def _appointments(
    session: AsyncSession, principal: Principal, journey: Journey
) -> list[Appointment]:
    owner = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
    keys = [
        "appointment.medical_screening",
        "appointment.biometrics",
        "service.medical_fitness",
        "service.emirates_id",
    ]
    governance = await GovernanceGraphRepository(session).by_keys(keys)
    rows: list[Appointment] = []
    for title, key, fallback, authority in (
        (
            "Medical fitness screening",
            "appointment.medical_screening",
            "service.medical_fitness",
            "Department of Health - Abu Dhabi",
        ),
        ("Emirates ID biometrics", "appointment.biometrics", "service.emirates_id", "ICP"),
    ):
        node = governance.get(key) or governance.get(fallback)
        journey_node = await _journey_node(session, journey, fallback)
        rows.append(
            Appointment(
                **owner,
                title=title,
                service_key=node.key if node else fallback,
                governance_node_id=node.id if node else None,
                journey_id=journey.id,
                journey_node_id=journey_node.id if journey_node else None,
                authority=authority,
                official_url=node.official_url if node else None,
                status=AppointmentStatus.PLANNED,
                notes="Not booked. Book on the official channel when your entry permit is issued.",
            )
        )
    session.add_all(rows)
    await session.flush()
    return rows


async def _replay_run(
    db: Database,
    principal: Principal,
    run: AgentRun,
    journey: Journey,
    docs: list[GeneratedDocument],
    actions: list[Action],
) -> None:
    """The event log of the (seeded) journey-planning run, in the streamed JSON format."""
    events = RunEventEmitter(db, principal, run.id)
    await events.run_started(RunKind.JOURNEY, agent="journey")
    stages = [
        ("profile_analysis", "Reviewing your profile", "Founder, moving with spouse and child"),
        (
            "document_analysis",
            "Analyzing your documents",
            "Passport found; marriage certificate not attested",
        ),
        ("requirements", "Finding the rules that apply", None),
        ("dependency_analysis", "Ordering the steps", None),
        ("document_preparation", "Drafting your documents", None),
        ("action_preparation", "Preparing next actions", None),
    ]
    for index, (node, label, summary) in enumerate(stages):
        await events.node_started(node, label)
        if node == "document_analysis":
            await events.tool_called(
                "user_graph.documents",
                call_id=f"call-{index}",
                node=node,
                summary="Checking which documents you hold",
            )
            await events.tool_result(
                "user_graph.documents",
                call_id=f"call-{index}",
                ok=True,
                node=node,
                summary="2 documents linked",
            )
        if node == "requirements":
            await events.evidence_found(
                title="ICP — residence visas and Emirates ID",
                source_url="https://icp.gov.ae",
                authority="authority.icp",
                evidence_kind=EvidenceKind.OFFICIAL_GUIDANCE,
                node=node,
            )
        if node == "document_preparation":
            for doc in docs:
                await events.document_generated(
                    document_id=doc.id, kind=doc.kind.value, title=doc.title, node=node
                )
        if node == "action_preparation":
            for action in actions:
                await events.action_prepared(
                    action_id=action.id,
                    action_type=action.type.value,
                    title=action.title,
                    status=action.status.value,
                    requires_approval=action.requires_human_approval,
                    node=node,
                )
            pending = [a for a in actions if a.status is ActionStatus.AWAITING_APPROVAL]
            for action in pending:
                await events.approval_required(
                    approval_id=str(action.id),
                    action_id=action.id,
                    title=action.title,
                    summary=action.summary,
                    node="approval",
                )
        await events.node_completed(node, 120 + 40 * index, summary, label=label)
    await events.run_completed(
        summary="Your plan is ready: 1 action awaits your approval.", journey_id=journey.id
    )


async def seed_demo_household(
    db: Database, *, principal: Principal | None = None
) -> DemoSeedReport:
    """Rebuild the demo household. `db` must use the owner role (seeding bypasses RLS)."""
    reset_seed = principal is None
    principal = principal or DEMO_PRINCIPAL
    if reset_seed:
        await _reset(db)
    async with db.user_session(principal) as session:
        if reset_seed:
            await _create_account(session)
        await profile_service.onboard(session, principal, ONBOARDING)
        await _link_documents(session)
        journey = await _plan_journey(session, principal)
        run = await create_run(
            session,
            principal,
            RunKind.JOURNEY,
            agent="journey",
            input={"seeded": True},
            journey_id=journey.id,
        )
        docs, actions = await _documents_and_actions(session, principal, journey, run)
        appointments = await _appointments(session, principal, journey)
        await session.commit()
        node_count = len(
            (
                await session.execute(
                    text("SELECT id FROM journey_nodes WHERE journey_id = :id"), {"id": journey.id}
                )
            ).all()
        )
    await _replay_run(db, principal, run, journey, docs, actions)
    async with db.user_session(principal) as session:
        status = (
            await session.execute(
                text("SELECT status FROM agent_runs WHERE id = :id"), {"id": run.id}
            )
        ).scalar_one()
    assert status == RunStatus.SUCCEEDED.value
    return DemoSeedReport(
        user_id=principal.user_id,
        journey_id=journey.id,
        journey_nodes=node_count,
        run_id=run.id,
        actions=len(actions),
        appointments=len(appointments),
    )
