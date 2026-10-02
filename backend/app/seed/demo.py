"""The fictional demo household: a complete, consistent private dataset for one user.

Everything here is invented for the demo — no real person's data. The household:
Arjun Mehta (founder of "Mehta Analytics Ltd", licensed in ADGM), his wife Priya and
their daughter Aanya, who join him later. His documents are the clearly-marked SPECIMEN
PDFs in `app.documents.specimens`.

Nothing is written straight into the private tables. The seed does what Arjun would do:

1. onboarding: profile, household, goals, preferences and consents;
2. documents: uploads his SPECIMEN PDFs into encrypted document storage, has the
   document pipeline read them (with the local text-layer reader only, so nothing leaves
   the server) and answers the questions the pipeline asks about what it read;
3. planning: runs the journey agent's own nodes on his request, scripted (rule-based
   request parser and drafting templates, no model, web or embeddings call). That
   produces the plan snapshot, the journey steps and their dependencies, the drafts, the
   prepared actions and the run with its event log, exactly as a scripted run would, so
   what-ifs of this plan work like those of any other plan. The run doesn't pause at the
   approval gate: approval-gated actions wait on the Approvals page instead;
4. appointments: planned, never booked.

The shared demo account has fixed ids and is rebuilt from scratch on every run; each
visitor who asks for the sample household gets a private copy (`principal`). Nothing
claims external success: actions are prepared or awaiting approval, appointments are
only planned.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import DemoLLM
from app.adapters.ocr import LocalTextReader
from app.adapters.registry import Adapters
from app.adapters.storage import DocumentStorage
from app.agents.instrumentation import instrumented
from app.agents.journey.context import JourneyContext, JourneyServices, ctx
from app.agents.journey.demo import register_demo_responders
from app.agents.journey.emit import emit
from app.agents.journey.graph import journey_input
from app.agents.journey.integrations import PlatformDocuments, PlatformResearch
from app.agents.journey.nodes import JOURNEY_SEQUENCE
from app.agents.journey.nodes.human import HUMAN_APPROVAL
from app.agents.journey.ports import EvidenceHit
from app.agents.journey.spec import spec_of
from app.agents.journey.state import JourneyState
from app.agents.journey.store_pg import PgJourneyStore
from app.agents.journey.vocab import NodeId
from app.agents.runner import execute_run
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
    Journey,
    JourneyNode,
    Tenant,
    User,
)
from app.db.models import AgentEvent as AgentEventRow
from app.db.models.user_data import UserDocument
from app.db.session import Database
from app.documents import specimens
from app.documents.catalogue import DocumentKind, DocumentStatus, DocumentSubject
from app.documents.pipeline import DocumentPipeline
from app.domain.actions import check_transition
from app.domain.enums import (
    ActionStatus,
    AppointmentStatus,
    ConsentStatus,
    GoalType,
    HouseholdRelationship,
    JourneyStatus,
    PreferenceCategory,
    Priority,
    RelocationPlan,
    RunKind,
    RunStatus,
)
from app.domain.principal import Principal
from app.events.emitter import MemoryEventSink
from app.personalization import facts as twin_facts
from app.personalization import review
from app.repositories.graph import GovernanceGraphRepository
from app.repositories.runs import create_run
from app.services import profile as profile_service

logger = logging.getLogger("adapt.seed")

DEMO_TENANT_ID = UUID("5eed0000-0000-4000-8000-000000000001")
DEMO_USER_ID = UUID("5eed0000-0000-4000-8000-000000000002")
DEMO_PROVIDER = "demo"
DEMO_SUBJECT = "seed:demo-household"
DEMO_PRINCIPAL = Principal(user_id=DEMO_USER_ID, tenant_id=DEMO_TENANT_ID, is_demo=True)
JURISDICTION = "adgm"
JOURNEY_TITLE = "Arjun's move to Abu Dhabi"

# Names and income as printed on his documents, so reading them confirms the profile
# instead of raising conflicts.
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
        monthly_income_aed=32000,
        arrival_date=date(2026, 11, 15),
        target_city="Abu Dhabi",
        languages=["en", "hi"],
        assumptions={"company.jurisdiction": JURISDICTION},
    ),
    household=[
        HouseholdMemberIn(
            relationship=HouseholdRelationship.SPOUSE,
            name="Priya Mehta",
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

# What Arjun asked ADAPT. The plan's goals come from it, as in any journey run.
PROMPT = (
    "I'm the founder of Mehta Analytics and I've set up my company in ADGM. I'm moving to "
    "Abu Dhabi in November and need my residence visa. My wife will join me later with our "
    "daughter, and I want to sponsor their visas. We've rented a family apartment on Al "
    "Reem Island."
)


@dataclass(frozen=True)
class SeedDocument:
    filename: str
    kind: DocumentKind
    content: Callable[[], bytes]


# His documents, all clearly-marked SPECIMEN PDFs. The licence and the registered lease
# are what make company registration and Tawtheeq done in his plan.
DOCUMENTS: tuple[SeedDocument, ...] = (
    SeedDocument("passport-arjun-mehta.pdf", DocumentKind.PASSPORT, specimens.passport),
    SeedDocument(
        "marriage-certificate.pdf",
        DocumentKind.MARRIAGE_CERTIFICATE,
        specimens.marriage_certificate,
    ),
    SeedDocument(
        "adgm-commercial-licence.pdf", DocumentKind.BUSINESS_DOCUMENT, specimens.business_document
    ),
    SeedDocument(
        "salary-certificate.pdf", DocumentKind.EMPLOYMENT_LETTER, specimens.employment_letter
    ),
    SeedDocument("tenancy-contract.pdf", DocumentKind.TENANCY_DOCUMENT, specimens.tenancy_document),
)
# How Arjun answers what the pipeline asks him to check, by field: the marriage
# certificate is not attested yet ("Attestation: Pending"); every other value it flagged
# (dates whose day and month could be swapped) was read correctly.
REVIEW_ANSWERS: dict[str, Any] = {"attested": False}

# (title, journey steps to attach it to in order of preference, authority if the step
# names none)
APPOINTMENTS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "Medical fitness screening",
        ("appointment.visa_screening", "service.medical_fitness"),
        "Department of Health - Abu Dhabi",
    ),
    (
        "Emirates ID biometrics",
        ("appointment.emirates_id_biometrics", "service.emirates_id"),
        "ICP",
    ),
)


@dataclass
class DemoSeedReport:
    user_id: UUID
    journey_id: UUID
    journey_nodes: int
    run_id: UUID
    actions: int
    appointments: int
    documents: int


# --- account -------------------------------------------------------------------------------


async def _reset(db: Database, storage: DocumentStorage) -> None:
    async with db.public_session() as session:
        keys = list(
            (
                await session.execute(
                    select(UserDocument.storage_key).where(
                        UserDocument.tenant_id == DEMO_TENANT_ID,
                        UserDocument.storage_key.is_not(None),
                    )
                )
            ).scalars()
        )
        await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": DEMO_TENANT_ID})
        await session.commit()
    for key in keys:
        if key:
            await storage.delete(key)


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


# --- documents ------------------------------------------------------------------------------


def _reading(adapters: Adapters) -> Adapters:
    """The SPECIMEN PDFs carry their text, so the local reader reads them exactly; the
    vision model is never asked (no network call, nothing leaves the server)."""
    return replace(adapters, ocr=LocalTextReader())


async def _upload_documents(db: Database, principal: Principal, adapters: Adapters) -> list[UUID]:
    """Upload and read each document as an upload is read (encrypted storage, then the
    document pipeline), then answer its review questions. Returns the documents that need
    nothing more from the person."""
    pipeline = DocumentPipeline(db, principal, _reading(adapters))
    ids: list[UUID] = []
    for document in DOCUMENTS:  # the passport first: it names its holder
        data = document.content()
        storage_key = f"{principal.user_id}/{uuid4()}"
        await adapters.storage.put(storage_key, data)
        async with db.user_session(principal) as session:
            row = UserDocument(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                kind=document.kind,
                declared_kind=document.kind,
                subject=DocumentSubject.SELF,
                filename=document.filename,
                content_type="application/pdf",
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                storage_key=storage_key,
                status=DocumentStatus.UPLOADED,
            )
            session.add(row)
            await session.flush()
            document_id = row.id
            await session.commit()
        await pipeline.run(document_id)
        ids.append(document_id)

    async with db.user_session(principal) as session:
        # As on the Documents page, one fact at a time (PATCH /graph/user/facts/{id}). No
        # journey is waiting on these documents yet, so no review listener is notified.
        for task in await review.open_tasks(session, principal):
            if task.fact_id is None:
                continue  # nothing the persona can answer: it stays open for the visitor
            if task.field in REVIEW_ANSWERS:
                await twin_facts.update_fact(
                    session, task.fact_id, value=REVIEW_ANSWERS[task.field]
                )
            else:
                await twin_facts.update_fact(session, task.fact_id, confirm=True)
        await session.commit()
        waiting = {t.document_id for t in await review.open_tasks(session, principal)}
    if waiting:
        logger.warning("demo_documents_need_review", extra={"documents": len(waiting)})
    return [i for i in ids if i not in waiting]


# --- planning ---------------------------------------------------------------------------------


class _NoPassages:
    """Evidence without retrieval (retrieval needs the embeddings model): every step cites
    its governance node's official page, as when no passage matches."""

    async def retrieve(
        self, query: str, *, governance_keys: list[str], top_k: int
    ) -> list[EvidenceHit]:
        return []


class _RunLog(MemoryEventSink):
    """The seeded run's event log, written in one transaction when the run ends instead
    of one transaction per event: nobody can be watching a run that is still being
    created. The rows and the run's status are those `RunEventEmitter` would write."""

    async def save(self, db: Database, principal: Principal) -> None:
        if not self.events:
            return
        last = self.events[-1]
        values: dict[str, Any] = {
            "event_seq": len(self.events),
            "started_at": self.events[0].ts,
            "status": RunStatus.SUCCEEDED if last.event == "run_completed" else RunStatus.FAILED,
            "finished_at": last.ts,
        }
        if last.event == "run_failed":
            payload = last.model_dump(mode="json")
            values["error"] = {k: payload.get(k) for k in ("code", "message", "retryable")}
        async with db.user_session(principal) as session:
            await session.execute(
                update(AgentRun).where(AgentRun.id == self.run_id).values(**values)
            )
            session.add_all(
                AgentEventRow(
                    run_id=self.run_id,
                    seq=event.seq,
                    event=event.event,
                    node=event.node,
                    payload=event.model_dump(mode="json"),
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                )
                for event in self.events
            )
            await session.commit()


@instrumented(HUMAN_APPROVAL.id.value, HUMAN_APPROVAL.label)
async def _ask_for_approval(state: dict[str, Any], runtime: Runtime[Any]) -> dict[str, Any]:
    """HUMAN_APPROVAL without the pause. A seeded run can't be resumed (it keeps no
    checkpoint), so each approval-gated action waits on its own, like an action prepared
    outside a run: approving it hands it over to the official site straight away."""
    context = ctx(runtime)
    principal = context.principal
    pending = [
        a
        for a in state.get("actions", [])
        if a["status"] == ActionStatus.PREPARED and a["requires_human_approval"]
    ]
    if not pending:
        return {"_summary": "Nothing needs your approval"}
    awaiting: list[dict[str, Any]] = []
    async with context.db.user_session(principal) as session:
        for action in pending:
            check_transition(
                ActionStatus.PREPARED,
                ActionStatus.AWAITING_APPROVAL,
                source="agent",
                requires_approval=True,
                approved=False,
                is_simulated=action["is_simulated"],
            )
            approval = ActionApproval(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                action_id=UUID(action["id"]),
                review_id=f"manual:{action['id']}",
            )
            session.add(approval)
            await session.flush()
            awaiting.append(
                {
                    **action,
                    "status": ActionStatus.AWAITING_APPROVAL.value,
                    "approval_id": str(approval.id),
                }
            )
        await session.commit()
    await context.svc.store.save_actions(
        journey_id=state["journey_id"],
        run_id=state["run_id"],
        actions=awaiting,  # type: ignore[arg-type]
    )
    for action in awaiting:
        await emit(
            context,
            "approval_required",
            approval_id=action["approval_id"],
            action_id=UUID(action["id"]),
            title=action["title"],
            summary=action["summary"],
            item_count=len(awaiting),
        )
    return {"actions": awaiting, "_summary": f"{len(awaiting)} step(s) wait for your approval"}


def _planning_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """The journey graph without its pauses: execution only ever follows an approval, and
    the approval gate is `_ask_for_approval`. Checkpoints stay in memory."""
    graph = StateGraph(JourneyState, context_schema=JourneyContext)
    previous = START
    for node in JOURNEY_SEQUENCE:
        name = spec_of(node).id
        if name is NodeId.EXECUTION_OR_HANDOFF:
            continue
        step: Any = _ask_for_approval if name is NodeId.HUMAN_APPROVAL else node
        graph.add_node(name.value, step)
        graph.add_edge(previous, name.value)
        previous = name.value
    graph.add_edge(previous, END)
    return graph.compile(checkpointer=InMemorySaver())


async def _plan(
    db: Database, principal: Principal, adapters: Adapters, document_ids: list[UUID]
) -> tuple[UUID, UUID]:
    documents = [str(d) for d in document_ids]
    async with db.user_session(principal) as session:
        journey = Journey(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            title=JOURNEY_TITLE,
            status=JourneyStatus.DRAFT,
        )
        session.add(journey)
        await session.flush()
        journey_id = journey.id
        # The run's request, as POST /journey records it. `deterministic` also makes its
        # what-ifs scripted.
        run = await create_run(
            session,
            principal,
            RunKind.JOURNEY,
            agent="journey",
            input={
                "prompt": PROMPT,
                "language": "en",
                "channel": "text",
                "document_ids": documents,
                "journey_id": str(journey_id),
                "deterministic": True,
                "seeded": True,
            },
            journey_id=journey_id,
        )
        run_id, thread_id = run.id, run.thread_id
        await session.commit()

    events = _RunLog(run_id)
    llm = DemoLLM()
    register_demo_responders(llm)
    context = JourneyContext(
        principal=principal,
        run_id=run_id,
        events=events,
        db=db,
        adapters=adapters,
        services=JourneyServices(
            store=PgJourneyStore(db, principal),
            documents=PlatformDocuments(db, principal, _reading(adapters), events),
            evidence=_NoPassages(),
            research=PlatformResearch(db, None, principal, adapters),  # none: no queue
            actions=adapters.actions,
            llm=llm,
        ),
    )
    outcome = await execute_run(
        graph=_planning_graph(),
        ctx=context,
        kind=RunKind.JOURNEY,
        thread_id=thread_id,
        graph_input=journey_input(
            user_id=str(principal.user_id),
            journey_id=str(journey_id),
            run_id=str(run_id),
            text=PROMPT,
            document_ids=documents,
        ),
        summary_key="final_summary",
    )
    await events.save(db, principal)
    if outcome.status != "completed":
        raise RuntimeError(f"planning the demo household's journey {outcome.status}")
    return journey_id, run_id


# --- appointments -----------------------------------------------------------------------------


async def _appointments(session: AsyncSession, principal: Principal, journey_id: UUID) -> int:
    nodes = {
        n.key: n
        for n in (
            await session.execute(select(JourneyNode).where(JourneyNode.journey_id == journey_id))
        ).scalars()
    }
    governance = await GovernanceGraphRepository(session).by_keys(
        [key for _, keys, _ in APPOINTMENTS for key in keys]
    )
    for title, keys, authority in APPOINTMENTS:
        key = next((k for k in keys if k in nodes), keys[-1])
        node, official = nodes.get(key), governance.get(key)
        session.add(
            Appointment(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                title=title,
                service_key=key,
                governance_node_id=official.id if official else None,
                journey_id=journey_id,
                journey_node_id=node.id if node else None,
                authority=(node.authority if node else None) or authority,
                official_url=(node.official_url if node else None)
                or (official.official_url if official else None),
                status=AppointmentStatus.PLANNED,
                notes="Not booked. Book on the official channel when your entry permit is issued.",
            )
        )
    await session.flush()
    return len(APPOINTMENTS)


# --- the household ----------------------------------------------------------------------------


async def seed_demo_household(
    db: Database, *, adapters: Adapters, principal: Principal | None = None
) -> DemoSeedReport:
    """Build the demo household for `principal` (a visitor's private copy) or, by default,
    rebuild the shared demo account from scratch (that needs the owner role: the reset
    bypasses RLS). `adapters` provide document storage and the action adapters; no model,
    vision or web search is called, so seeding is quick and the same every time."""
    reset_seed = principal is None
    principal = principal or DEMO_PRINCIPAL
    if reset_seed:
        await _reset(db, adapters.storage)
    async with db.user_session(principal) as session:
        if reset_seed:
            await _create_account(session)
        await profile_service.onboard(session, principal, ONBOARDING)
        await session.commit()
    documents = await _upload_documents(db, principal, adapters)
    journey_id, run_id = await _plan(db, principal, adapters, documents)
    async with db.user_session(principal) as session:
        appointments = await _appointments(session, principal, journey_id)
        await session.commit()
        node_count = (
            await session.execute(
                select(func.count())
                .select_from(JourneyNode)
                .where(JourneyNode.journey_id == journey_id)
            )
        ).scalar_one()
        action_count = (
            await session.execute(
                select(func.count()).select_from(Action).where(Action.journey_id == journey_id)
            )
        ).scalar_one()
        document_count = (
            await session.execute(
                select(func.count())
                .select_from(UserDocument)
                .where(UserDocument.user_id == principal.user_id)
            )
        ).scalar_one()
        status = (
            await session.execute(select(AgentRun.status).where(AgentRun.id == run_id))
        ).scalar_one()
    assert status == RunStatus.SUCCEEDED, status
    return DemoSeedReport(
        user_id=principal.user_id,
        journey_id=journey_id,
        journey_nodes=node_count,
        run_id=run_id,
        actions=action_count,
        appointments=appointments,
        documents=document_count,
    )
