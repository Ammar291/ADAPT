"""In-memory implementations of the journey ports, plus a harness that runs the real
graph (InMemorySaver checkpointer, MemoryEventSink) end to end."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.adapters.actions import build_action_registry
from app.adapters.llm import DemoLLM
from app.agents.journey.context import JourneyContext, JourneyServices
from app.agents.journey.demo import register_demo_responders
from app.agents.journey.facts import fact
from app.agents.journey.gates import review_announcer
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.graph import build_journey_graph, journey_input
from app.agents.journey.ports import (
    ApprovalRow,
    DocumentAnalysis,
    EvidenceHit,
    ExtractedField,
    ResearchStart,
)
from app.agents.journey.state import ActionRecord, Dependency, Task, UserFact
from app.agents.runner import RunOutcome, execute_run
from app.domain.enums import ApprovalStatus, RunKind
from app.domain.principal import Principal
from app.events.emitter import MemoryEventSink

from .governance_fixture import snapshot as fixture_snapshot


class InMemoryStore:
    def __init__(self, governance: GovernanceSnapshot, facts: list[UserFact] | None = None) -> None:
        self._governance = governance
        self.facts = list(facts or [])
        self.preferences_value: dict[str, Any] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.actions: dict[str, ActionRecord] = {}
        self.approval_rows: dict[str, ApprovalRow] = {}  # by action id
        self.plans: dict[str, dict[str, Any]] = {}
        self.pending_reviews: dict[str, dict[str, Any] | None] = {}
        self.writes: Counter[str] = Counter()

    async def governance(self) -> GovernanceSnapshot:
        return self._governance

    async def user_facts(self) -> list[UserFact]:
        return copy.deepcopy(self.facts)

    async def preferences(self) -> dict[str, Any]:
        return dict(self.preferences_value)

    async def save_generated_document(self, **kwargs: Any) -> str:
        self.writes["generated_document"] += 1
        doc_id = str(uuid4())
        self.documents[doc_id] = kwargs
        return doc_id

    async def save_actions(
        self, *, journey_id: str, run_id: str, actions: list[ActionRecord]
    ) -> None:
        self.writes["actions"] += 1
        for action in actions:
            self.actions[action["id"]] = copy.deepcopy(action)

    async def load_actions(self, action_ids: list[str]) -> dict[str, ActionRecord]:
        return {i: copy.deepcopy(self.actions[i]) for i in action_ids if i in self.actions}

    async def set_pending_review(self, *, run_id: str, review: dict[str, Any] | None) -> None:
        self.writes["pending_review"] += 1
        self.pending_reviews[run_id] = review

    async def ensure_approvals(
        self, *, run_id: str, review_id: str, action_ids: list[str]
    ) -> dict[str, tuple[str, bool]]:
        out = {}
        for action_id in action_ids:
            created = action_id not in self.approval_rows
            if created:
                self.writes["approval"] += 1
                self.approval_rows[action_id] = ApprovalRow(
                    id=str(uuid4()), action_id=action_id, status="pending", decided_at=None
                )
            out[action_id] = (self.approval_rows[action_id].id, created)
        return out

    async def approvals(self, action_ids: list[str]) -> dict[str, ApprovalRow]:
        return {i: self.approval_rows[i] for i in action_ids if i in self.approval_rows}

    async def save_plan(
        self,
        *,
        journey_id: str,
        plan: dict[str, Any],
        tasks: list[Task],
        dependencies: list[Dependency],
        status: str,
        summary: str | None,
    ) -> None:
        self.writes[f"plan:{status}"] += 1
        self.plans[journey_id] = {"plan": copy.deepcopy(plan), "status": status, "summary": summary}

    # --- what the approve/reject API does ---------------------------------------------------
    def decide(self, action_id: str, decision: str) -> None:
        row = self.approval_rows[action_id]
        status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
        self.approval_rows[action_id] = ApprovalRow(
            id=row.id,
            action_id=action_id,
            status=status.value,
            decided_at=datetime.now(UTC).isoformat(),
        )


def field_(
    name: str, value: str | None, confidence: float, review: bool | None = None
) -> ExtractedField:
    return ExtractedField(
        name=name,
        label=name.replace("_", " ").title(),
        value=value,
        confidence=confidence,
        needs_review=confidence < 0.85 if review is None else review,
    )


class FakeDocuments:
    def __init__(self, analyses: dict[str, DocumentAnalysis] | None = None) -> None:
        self.analyses = dict(analyses or {})
        self.analyze_calls: Counter[str] = Counter()
        self.corrections: list[tuple[str, list[dict[str, Any]], bool]] = []

    async def analyze(self, document_id: str) -> DocumentAnalysis:
        self.analyze_calls[document_id] += 1
        analysis = self.analyses[document_id]
        if self.analyze_calls[document_id] > 1:  # stored result, no OCR
            analysis = DocumentAnalysis(**{**analysis.__dict__, "cached": True})
        return analysis

    async def apply_corrections(
        self, document_id: str, corrections: list[dict[str, Any]], *, confirm: bool
    ) -> list[UserFact]:
        self.corrections.append((document_id, corrections, confirm))
        analysis = self.analyses[document_id]
        return [{**f, "confirmed": True, "confidence": 1.0} for f in analysis.facts]


def spouse_passport(document_id: str = "doc-spouse-passport") -> DocumentAnalysis:
    return DocumentAnalysis(
        document_id=document_id,
        kind="passport",
        holder="spouse",
        status="needs_review",
        fields=[
            field_("full_name", "PRIYA MEHTA", 0.97),
            field_("passport_number", "Z0000001", 0.62),
        ],
        facts=[
            fact(
                "spouse.documents.passport",
                True,
                "document_extracted",
                source_ref=f"document:{document_id}",
                confidence=0.9,
                fact_ids=["fact-sp-1"],
            ),
            fact(
                "spouse.full_name",
                "PRIYA MEHTA",
                "document_extracted",
                source_ref=f"document:{document_id}",
                confidence=0.97,
                fact_ids=["fact-sp-2"],
            ),
        ],
        review_task_ids=["review-1"],
    )


class FakeEvidence:
    def __init__(self, passages: dict[str, str] | None = None) -> None:
        self.passages = passages or {}  # governance key -> quote
        self.queries: list[str] = []

    async def retrieve(
        self, query: str, *, governance_keys: list[str], top_k: int
    ) -> list[EvidenceHit]:
        self.queries.append(query)
        return [
            EvidenceHit(
                id=f"chunk-{key}",
                title=f"Official page for {key}",
                source_url="https://u.ae/en/information-and-services",
                authority="u.ae",
                quote=quote,
                governance_key=key,
                trust="official_guidance",
                score=0.9,
                retrieved_at="2026-09-29T00:00:00+00:00",
                claim=quote,
                section_or_page="Requirements",
                excerpt="quote",
                source_family="federal_government",
                freshness="current",
                chunk_id=f"chunk-{key}",
            )
            for key, quote in self.passages.items()
            if key in governance_keys
        ][:top_k]


class FakeResearch:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.started: list[str] = []

    async def start(self, *, journey_id: str) -> ResearchStart | None:
        if not self.available:
            return None
        self.started.append(journey_id)
        return ResearchStart(job_id=str(uuid4()), run_id=str(uuid4()), status="queued")


FOUNDER_WITH_SPOUSE = (
    "I'm a founder moving next month with my wife. I want to set up my company, find a home "
    "and sponsor her visa."
)


@dataclass
class Harness:
    store: InMemoryStore
    documents: FakeDocuments
    evidence: FakeEvidence
    research: FakeResearch
    actions_mode: str = "demo"
    sink: MemoryEventSink = field(init=False)
    principal: Principal = field(
        default_factory=lambda: Principal(user_id=uuid4(), tenant_id=uuid4())
    )
    run_id: UUID = field(default_factory=uuid4)
    journey_id: str = field(default_factory=lambda: str(uuid4()))
    checkpointer: InMemorySaver = field(default_factory=InMemorySaver)

    def __post_init__(self) -> None:
        self.sink = MemoryEventSink(self.run_id)
        llm = DemoLLM()
        register_demo_responders(llm)
        self.services = JourneyServices(
            store=self.store,
            documents=self.documents,
            evidence=self.evidence,  # type: ignore[arg-type]
            research=self.research,
            actions=build_action_registry(self.actions_mode),  # type: ignore[arg-type]
            llm=llm,
            today=lambda: date(2026, 10, 1),
        )
        self.context = JourneyContext(
            principal=self.principal,
            run_id=self.run_id,
            events=self.sink,
            db=None,  # type: ignore[arg-type]
            adapters=None,
            services=self.services,  # type: ignore[arg-type]
        )
        self.graph = build_journey_graph(self.checkpointer)
        self.thread_id = f"journey:{self.run_id}"

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.thread_id}}

    async def start(
        self, text: str = FOUNDER_WITH_SPOUSE, document_ids: list[str] | None = None
    ) -> RunOutcome:
        return await execute_run(
            graph=self.graph,
            ctx=self.context,
            kind=RunKind.JOURNEY,
            thread_id=self.thread_id,
            graph_input=journey_input(
                user_id=str(self.principal.user_id),
                journey_id=self.journey_id,
                run_id=str(self.run_id),
                text=text,
                document_ids=document_ids,
            ),
            summary_key="final_summary",
            on_interrupt=review_announcer(self.context),
        )

    async def resume(self, answer: dict[str, Any]) -> RunOutcome:
        return await execute_run(
            graph=self.graph,
            ctx=self.context,
            kind=RunKind.JOURNEY,
            thread_id=self.thread_id,
            graph_input=Command(resume=answer),
            summary_key="final_summary",
            on_interrupt=review_announcer(self.context),
        )

    @property
    def review(self) -> dict[str, Any]:
        review = self.store.pending_reviews.get(str(self.run_id))
        assert review is not None, "the run is not paused at a review"
        return review

    async def state(self) -> dict[str, Any]:
        return dict((await self.graph.aget_state(self.config)).values)  # type: ignore[arg-type]

    def events(self, name: str) -> list[Any]:
        return [e for e in self.sink.events if e.event == name]

    def node_order(self) -> list[str]:
        """Nodes in the order they first started."""
        seen: list[str] = []
        for event in self.events("node_started"):
            if event.node not in seen:
                seen.append(event.node)
        return seen


def harness(
    *,
    facts: list[UserFact] | None = None,
    documents: dict[str, DocumentAnalysis] | None = None,
    passages: dict[str, str] | None = None,
    governance: GovernanceSnapshot | None = None,
    actions_mode: str = "demo",
) -> Harness:
    return Harness(
        store=InMemoryStore(governance or fixture_snapshot(), facts),
        documents=FakeDocuments(documents),
        evidence=FakeEvidence(passages),
        research=FakeResearch(),
        actions_mode=actions_mode,
    )


def approve_all(h: Harness, *, reject: set[str] | None = None) -> dict[str, Any]:
    """Decide every pending action (as the approve/reject routes do), then build the resume."""
    review = h.review
    for item in review["items"]:
        h.store.decide(
            item["action_id"], "reject" if item["action_id"] in (reject or set()) else "approve"
        )
    return {"gate": "action_approval", "review_id": review["review_id"], "decisions": []}
