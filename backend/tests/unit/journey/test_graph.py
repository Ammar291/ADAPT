"""Graph transitions, human-in-the-loop gates and approvals, on the real compiled graph
(in-memory checkpointer and ports; events validated by the platform's MemoryEventSink)."""

from __future__ import annotations

import json
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.journey.context import JourneyContext
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.nodes import JOURNEY_SEQUENCE
from app.agents.journey.nodes.human import compose_summary
from app.agents.journey.review import (
    PENDING_REVIEW,
    REVIEW_RESPONSE,
    ReviewMismatch,
    validate_response,
)
from app.agents.journey.spec import NodeContractError, NodeSpec, journey_node, spec_of
from app.agents.journey.state import JourneyState
from app.agents.journey.vocab import NodeId
from app.agents.runner import execute_run
from app.domain.enums import ActionStatus, RunKind
from app.domain.principal import Principal
from app.events.emitter import MemoryEventSink

from .fakes import FOUNDER_WITH_SPOUSE, approve_all, harness, spouse_passport
from .governance_fixture import EDGES, NODES

SEQUENCE = [spec_of(n).id.value for n in JOURNEY_SEQUENCE]


def confirm(
    h: Any, outcomes: dict[str, tuple[str, str | None]] | None = None, default: str = "not_yet"
) -> dict[str, Any]:
    review = h.review
    assert review["gate"] == "submission_confirmation"
    return {
        "gate": "submission_confirmation",
        "review_id": review["review_id"],
        "confirmations": [
            {
                "action_id": i["action_id"],
                "outcome": (outcomes or {}).get(i["title"], (default, None))[0],
                "reference": (outcomes or {}).get(i["title"], (default, None))[1],
            }
            for i in review["items"]
        ],
    }


def assert_json_only(value: Any, path: str = "state") -> None:
    """Checkpointed state must be plain JSON: no enums, models or objects."""
    if isinstance(value, dict):
        for k, v in value.items():
            assert type(k) is str, f"{path}: key {k!r}"
            assert_json_only(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            assert_json_only(v, f"{path}[{i}]")
    else:
        assert type(value) in (str, int, float, bool, type(None)), f"{path}: {type(value).__name__}"


@pytest.mark.parametrize(
    ("source", "simulated", "reference", "provider_confirmed"),
    [
        ("user_reported", False, "REPORT-123", False),
        ("adapter", True, "DEMO-123", False),
        ("adapter", False, " ", False),
        (None, False, "REF-123", False),
        ("adapter", False, "RECEIPT-123", True),
    ],
)
def test_summary_requires_provider_evidence(
    source: str | None, simulated: bool, reference: str, provider_confirmed: bool
) -> None:
    summary = compose_summary(
        {
            "actions": [
                {
                    "status": ActionStatus.COMPLETED,
                    "confirmation_source": source,
                    "is_simulated": simulated,
                    "external_reference": reference,
                }
            ],
        }
    )
    assert ("External providers confirmed" in summary) is provider_confirmed
    assert "You confirmed" not in summary


class TestTransitions:
    async def test_rag_metadata_survives_the_plan_and_api_contract(self) -> None:
        from app.agents.journey.schemas import EvidenceOut

        h = harness(passages={"service.trade_name_reservation": "Check trade name requirements."})
        await h.start()
        state = await h.state()
        passages = [r for r in state["evidence"] if r["kind"] == "official_passage"]
        assert passages
        for raw in passages:
            record = EvidenceOut.model_validate(raw).model_dump()
            assert record["source_url"] and record["authority"] and record["retrieved_at"]
            assert record["claim"] == record["quote"]
            assert record["excerpt"] == "quote"
            assert record["section_or_page"] == "Requirements"
            assert record["freshness"] == "current"
            assert record["chunk_id"]

    async def test_runs_every_node_in_order_and_pauses_for_approval(self) -> None:
        h = harness()
        outcome = await h.start()
        assert outcome.status == "interrupted"
        assert h.node_order() == SEQUENCE[: SEQUENCE.index("human_approval") + 1]
        review = PENDING_REVIEW.validate_python(h.review)
        assert review.gate.value == "action_approval"
        assert review.items and all(i.approval_id for i in review.items)
        # the run is paused, announced and persisted
        assert h.sink.types[-1] == "run_status"
        assert h.events("run_status")[-1].status == "awaiting_input"
        required = h.events("approval_required")
        assert {str(e.action_id) for e in required} == {i.action_id for i in review.items}
        assert all(e.gate == "action_approval" for e in required)
        assert h.store.plans[h.journey_id]["status"] == "draft"
        for item in review.items:
            assert h.store.actions[item.action_id]["status"] == ActionStatus.AWAITING_APPROVAL

    async def test_full_workflow_to_final_plan(self) -> None:
        h = harness()
        await h.start()
        await h.resume(approve_all(h))
        assert h.review["gate"] == "submission_confirmation"
        outcome = await h.resume(confirm(h, {"Reserve a trade name": ("submitted", "TAMM-123")}))
        assert outcome.status == "completed"
        assert h.node_order() == SEQUENCE
        state = await h.state()
        assert state["final_summary"].startswith("Your plan has")
        assert "ready to continue on official sites" in state["final_summary"]
        assert "External providers confirmed" not in state["final_summary"]
        completed = h.events("run_completed")[-1]
        assert completed.summary == state["final_summary"]
        assert str(completed.journey_id) == h.journey_id
        assert h.store.plans[h.journey_id]["status"] == "active"
        assert h.research.started == [h.journey_id]
        assert state["research_job_ids"]
        assert_json_only(state)

    async def test_every_node_emits_start_and_complete_and_tools_stream(self) -> None:
        h = harness()
        await h.start()
        await h.resume(approve_all(h))
        await h.resume(confirm(h))
        started = {e.node for e in h.events("node_started")}
        completed = {e.node for e in h.events("node_completed")}
        assert started == completed == set(SEQUENCE)
        calls = {e.call_id: e for e in h.events("tool_called")}
        results = {e.call_id: e for e in h.events("tool_result")}
        assert calls and calls.keys() == results.keys()
        assert {e.tool for e in calls.values()} >= {
            "get_user_graph",
            "get_governance_graph",
            "retrieve_evidence",
            "generate_document",
            "prepare_action",
            "prepare_appointment",
            "start_research",
        }
        assert all(results[i].ok for i in calls)
        assert all(e.node in SEQUENCE for e in calls.values())

    async def test_state_journal_records_nodes_tools_and_gates(self) -> None:
        h = harness()
        await h.start()
        await h.resume(approve_all(h))
        await h.resume(confirm(h))
        journal = (await h.state())["events"]
        starts = [e["node"] for e in journal if e["type"] == "node_start"]
        assert starts == SEQUENCE
        types = {e["type"] for e in journal}
        assert types == {
            "node_start",
            "node_complete",
            "tool_call",
            "tool_result",
            "approval_required",
            "approval_resolved",
        }

    async def test_no_consequential_actions_means_no_gates(self) -> None:
        # A housing-only plan whose service has no login portal: only an informational handoff.
        nodes = [n for n in NODES if n["key"] != "portal.tamm"]
        edges = [e for e in EDGES if e["target"] != "portal.tamm"]
        h = harness(governance=GovernanceSnapshot.of(nodes, edges))
        outcome = await h.start("I want to rent an apartment in Abu Dhabi")
        assert outcome.status == "completed"
        assert "approval_required" not in h.sink.types
        state = await h.state()
        (action,) = state["actions"]
        assert action["type"] == "official_handoff" and not action["requires_human_approval"]
        assert action["status"] == ActionStatus.HANDOFF_REQUIRED

    async def test_invalid_resume_fails_the_run_and_changes_nothing(self) -> None:
        h = harness()
        await h.start()
        before = dict(h.store.actions)
        outcome = await h.resume(
            {"gate": "action_approval", "review_id": "rev_forged", "decisions": []}
        )
        assert outcome.status == "failed"
        assert h.sink.types[-1] == "run_failed"
        assert h.store.actions == before


class TestApprovals:
    async def test_duplicate_conflicting_decisions_are_rejected_before_any_approval(self) -> None:
        h = harness()
        await h.start()
        review = PENDING_REVIEW.validate_python(h.review)
        action_id = h.review["items"][0]["action_id"]
        answer = REVIEW_RESPONSE.validate_python(
            {
                "gate": "action_approval",
                "review_id": h.review["review_id"],
                "decisions": [
                    {"action_id": action_id, "decision": "approve"},
                    {"action_id": action_id, "decision": "reject"},
                ],
            }
        )
        with pytest.raises(ReviewMismatch, match="only once"):
            validate_response(review, answer)
        assert all(
            action["status"] == "awaiting_approval"
            for action in h.store.actions.values()
            if action["requires_human_approval"]
        )

    async def test_approved_and_rejected_actions(self) -> None:
        h = harness()
        await h.start()
        items = h.review["items"]
        rejected = items[0]["action_id"]
        await h.resume(approve_all(h, reject={rejected}))
        # paused inside execution_or_handoff: the stored actions hold the executed outcomes
        by_id = h.store.actions
        assert by_id[rejected]["status"] == ActionStatus.DRAFT  # rejected: back to draft
        for item in items[1:]:
            assert by_id[item["action_id"]]["status"] == ActionStatus.HANDOFF_REQUIRED
            assert by_id[item["action_id"]]["approval_id"]
        confirmation = {i["action_id"] for i in h.review["items"]}
        assert rejected not in confirmation

    async def test_rejecting_everything_skips_execution_confirmation(self) -> None:
        h = harness()
        await h.start()
        outcome = await h.resume(approve_all(h, reject={i["action_id"] for i in h.review["items"]}))
        assert outcome.status == "completed"
        state = await h.state()
        consequential = [a for a in state["actions"] if a["requires_human_approval"]]
        assert consequential and all(a["status"] == ActionStatus.DRAFT for a in consequential)

    async def test_nothing_executes_without_a_recorded_approval(self) -> None:
        """Resuming without deciding (e.g. a forged 'go on') executes nothing."""
        h = harness()
        await h.start()
        review = h.review
        await h.resume(
            {"gate": "action_approval", "review_id": review["review_id"], "decisions": []}
        )
        state = await h.state()
        for item in review["items"]:
            action = next(a for a in state["actions"] if a["id"] == item["action_id"])
            assert action["status"] == ActionStatus.DRAFT

    async def test_demo_actions_are_never_submitted_by_the_adapter(self) -> None:
        h = harness(actions_mode="demo")
        await h.start()
        await h.resume(approve_all(h))
        await h.resume(confirm(h))
        state = await h.state()
        simulated = [a for a in state["actions"] if a["is_simulated"]]
        assert simulated
        for action in simulated:
            assert action["status"] == ActionStatus.HANDOFF_REQUIRED
            assert action["simulation_label"] == "DEMO / SIMULATED"
            assert action["external_reference"] is None
            assert action["response_metadata"]["outcome"]["booked"] is False

    async def test_user_reports_never_complete_government_actions(self) -> None:
        h = harness()
        await h.start()
        await h.resume(approve_all(h))
        await h.resume(
            confirm(
                h,
                {
                    "Reserve a trade name": ("submitted", "TAMM-123"),
                    "Emirates ID biometrics": ("completed", "EID-9"),
                    "Medical screening appointment": ("could_not_complete", None),
                },
            )
        )
        by_title = {a["title"]: a for a in (await h.state())["actions"]}
        assert by_title["Reserve a trade name"]["status"] == ActionStatus.HANDOFF_REQUIRED
        assert by_title["Reserve a trade name"]["confirmation_source"] is None
        assert by_title["Reserve a trade name"]["external_reference"] is None
        report = by_title["Reserve a trade name"]["response_metadata"]["user_report"]
        assert report["reference"] == "TAMM-123" and report["verified"] is False
        assert by_title["Emirates ID biometrics"]["status"] == ActionStatus.HANDOFF_REQUIRED
        assert by_title["Medical screening appointment"]["status"] == ActionStatus.FAILED
        assert (
            by_title["Medical screening appointment for your spouse"]["status"]
            == ActionStatus.HANDOFF_REQUIRED
        )

    async def test_completed_without_reference_is_rejected(self) -> None:
        h = harness()
        await h.start()
        await h.resume(approve_all(h))
        outcome = await h.resume(confirm(h, {"Reserve a trade name": ("completed", None)}))
        assert outcome.status == "failed"

    async def test_resumed_nodes_do_not_repeat_side_effects(self) -> None:
        h = harness()
        await h.start()
        approvals_created = h.store.writes["approval"]
        await h.resume(approve_all(h))
        assert h.store.writes["approval"] == approvals_created  # ensure_approvals is idempotent
        handed_off = {
            a["id"]: a
            for a in h.store.actions.values()
            if a["status"] == ActionStatus.HANDOFF_REQUIRED
        }
        await h.resume(confirm(h))
        # execution re-ran on resume but reused the stored outcomes
        for action_id, action in handed_off.items():
            assert h.store.actions[action_id]["response_metadata"] == action["response_metadata"]


class TestDocumentCorrections:
    async def test_low_confidence_fields_pause_for_correction(self) -> None:
        doc = spouse_passport()
        h = harness(documents={doc.document_id: doc})
        outcome = await h.start(document_ids=[doc.document_id])
        assert outcome.status == "interrupted"
        assert h.node_order()[-1] == "document_analysis"
        review = h.review
        assert review["gate"] == "document_correction"
        (item,) = review["items"]
        assert item["holder"] == "spouse" and item["review_task_ids"] == ["review-1"]
        low = [f for f in item["fields"] if f["needs_review"]]
        assert [f["name"] for f in low] == ["passport_number"]
        (event,) = h.events("approval_required")
        assert event.gate == "document_correction" and str(event.approval_id) == review["review_id"]

        await h.resume(
            {
                "gate": "document_correction",
                "review_id": review["review_id"],
                "documents": [
                    {
                        "document_id": doc.document_id,
                        "corrections": [{"name": "passport_number", "value": "Z0000009"}],
                    }
                ],
            }
        )
        assert h.documents.corrections == [
            (doc.document_id, [{"name": "passport_number", "value": "Z0000009"}], True)
        ]
        assert h.documents.analyze_calls[doc.document_id] == 2  # re-run used the stored result
        state = await h.state()
        assert state["user_facts"]["spouse.documents.passport"]["confirmed"] is True
        # the spouse's passport is no longer a missing-document risk
        assert "risk:missing_user_document:spouse:document.passport" not in {
            r["id"] for r in state["risks"]
        }
        assert h.review["gate"] == "action_approval"

    async def test_rejected_document_values_are_not_used(self) -> None:
        doc = spouse_passport()
        h = harness(documents={doc.document_id: doc})
        await h.start(document_ids=[doc.document_id])
        await h.resume(
            {
                "gate": "document_correction",
                "review_id": h.review["review_id"],
                "documents": [{"document_id": doc.document_id, "confirm": False}],
            }
        )
        state = await h.state()
        assert "spouse.documents.passport" not in state["user_facts"]

    async def test_confident_documents_do_not_pause(self) -> None:
        doc = spouse_passport()
        doc = type(doc)(**{**doc.__dict__, "status": "confirmed"})
        h = harness(documents={doc.document_id: doc})
        await h.start(document_ids=[doc.document_id])
        assert h.review["gate"] == "action_approval"


class _In(TypedDict):
    user_facts: dict[str, Any]


class _Out(TypedDict, total=False):
    risks: list[Any]


class TestNodeContracts:
    def _graph(self, fn: Any) -> Any:
        graph = StateGraph(JourneyState, context_schema=JourneyContext)
        graph.add_node("n", fn)
        graph.add_edge(START, "n")
        graph.add_edge("n", END)
        return graph.compile(checkpointer=InMemorySaver())

    def _ctx(self) -> JourneyContext:
        sink = MemoryEventSink(uuid4())
        return JourneyContext(
            principal=Principal(uuid4(), uuid4()),
            run_id=sink.run_id,
            events=sink,
            db=None,
            adapters=None,
        )  # type: ignore[arg-type]

    async def _run(self, fn: Any, state: dict[str, Any]) -> Any:
        return await execute_run(
            graph=self._graph(fn),
            ctx=self._ctx(),
            kind=RunKind.JOURNEY,
            thread_id=str(uuid4()),
            graph_input=state,
        )

    async def test_node_sees_only_declared_inputs(self) -> None:
        seen: list[set[str]] = []
        spec = NodeSpec(NodeId.RISK_DETECTION, "t", "t", "agent", _In, _Out)

        @journey_node(spec)
        async def node(state: Any, runtime: Any) -> dict[str, Any]:
            seen.append(set(state))
            return {"risks": []}

        outcome = await self._run(
            node, {"user_facts": {}, "tasks": [{"x": 1}], "final_summary": "s"}
        )
        assert outcome.status == "completed" and seen == [{"user_facts"}]

    async def test_undeclared_write_is_refused(self) -> None:
        spec = NodeSpec(NodeId.RISK_DETECTION, "t", "t", "agent", _In, _Out)

        @journey_node(spec)
        async def node(state: Any, runtime: Any) -> dict[str, Any]:
            return {"risks": [], "tasks": []}  # tasks belong to the planner

        outcome = await self._run(node, {"user_facts": {}})
        assert outcome.status == "failed"
        with pytest.raises(NodeContractError, match="undeclared state keys"):
            await node({"user_facts": {}}, type("R", (), {"context": self._ctx()})())

    async def test_invalid_output_type_is_refused(self) -> None:
        spec = NodeSpec(NodeId.RISK_DETECTION, "t", "t", "agent", _In, _Out)

        @journey_node(spec)
        async def node(state: Any, runtime: Any) -> dict[str, Any]:
            return {"risks": "not a list"}

        runtime = type("R", (), {"context": self._ctx()})()
        with pytest.raises(NodeContractError, match="invalid output"):
            await node({"user_facts": {}}, runtime)

    async def test_missing_required_input_is_refused(self) -> None:
        spec = NodeSpec(NodeId.RISK_DETECTION, "t", "t", "agent", _In, _Out)

        @journey_node(spec)
        async def node(state: Any, runtime: Any) -> dict[str, Any]:
            return {}

        runtime = type("R", (), {"context": self._ctx()})()
        with pytest.raises(NodeContractError, match="invalid input"):
            await node({}, runtime)

    def test_every_journey_node_declares_its_writes(self) -> None:
        owners: dict[str, list[str]] = {}
        for node in JOURNEY_SEQUENCE:
            spec = spec_of(node)
            assert spec.writes, spec.id
            for key in spec.writes:
                owners.setdefault(key, []).append(spec.id.value)
        # single-owner keys are complete values; shared keys have merge reducers
        from app.agents.journey.state import STATE_REDUCERS

        for key, writers in owners.items():
            if len(writers) > 1:
                assert key in STATE_REDUCERS or key == "tasks", (key, writers)
        assert owners["tasks"] == ["requirement_planner", "dependency_analysis"]
        assert owners["risks"] == ["risk_detection"]


async def test_state_is_json_serialisable_at_every_pause() -> None:
    h = harness()
    await h.start(FOUNDER_WITH_SPOUSE)
    assert_json_only(await h.state())
    json.dumps(h.review)
