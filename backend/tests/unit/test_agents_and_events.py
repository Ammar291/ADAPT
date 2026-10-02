"""Event contract + LangGraph instrumentation and run lifecycle (in-memory, no services)."""

from __future__ import annotations

import json
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.agents.context import AgentContext
from app.agents.instrumentation import instrumented, report
from app.agents.runner import execute_run
from app.contracts.events import AgentEvent, NodeProgressEvent, parse_event
from app.core.errors import UpstreamError
from app.domain.enums import EvidenceKind, RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import MemoryEventSink, build_event
from app.events.stream import format_sse


class TestEventContract:
    def test_round_trip_every_helper(self) -> None:
        run_id = uuid4()
        event = build_event(
            run_id=run_id,
            seq=3,
            event="node_progress",
            node="plan_journey",
            data={"message": "Ordering 12 steps", "progress": 0.5},
        )
        assert isinstance(event, NodeProgressEvent)
        again = parse_event(event.model_dump(mode="json"))
        assert again == event

    def test_payload_is_validated(self) -> None:
        with pytest.raises(ValidationError):
            build_event(run_id=uuid4(), seq=1, event="node_progress", data={"progress": 2})

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentEvent.model_validate(
                {
                    "event": "node_teleported",
                    "run_id": str(uuid4()),
                    "seq": 1,
                    "ts": "2026-01-01T00:00:00Z",
                }
            )

    def test_sse_frame(self) -> None:
        frame = format_sse(7, {"event": "run_completed", "text": "Plan ready — مرحبا"})
        assert frame.startswith("id: 7\ndata: ")
        assert frame.endswith("\n\n")
        assert json.loads(frame.split("data: ", 1)[1])["text"].endswith("مرحبا")

    async def test_memory_sink_helpers_produce_valid_events(self) -> None:
        sink = MemoryEventSink(uuid4())
        await sink.run_started(RunKind.JOURNEY)
        await sink.node_started("clarify", "Ask what's missing")
        await sink.question_asked(
            "q1",
            "When does your wife plan to join you?",
            field="household.spouse_arrival",
            options=[{"value": "with_me", "label": "With me"}],
        )
        await sink.tool_called("ocr", call_id="c1", node="document_analysis")
        await sink.tool_result("ocr", call_id="c1", ok=True, node="document_analysis")
        await sink.evidence_found(
            title="ICP",
            source_url="https://icp.gov.ae",
            evidence_kind=EvidenceKind.OFFICIAL_GUIDANCE,
            quote="x" * 2000,
        )
        await sink.document_generated(document_id=uuid4(), kind="checklist", title="List")
        await sink.action_prepared(
            action_id=uuid4(),
            action_type="official_handoff",
            title="Open TAMM",
            status="prepared",
            requires_approval=False,
        )
        await sink.approval_required(approval_id=uuid4(), title="Approve", summary="Please")
        await sink.research_started(job_id=uuid4(), categories=["community"], mode="snapshot")
        await sink.research_completed(
            job_id=uuid4(),
            result_count=0,
            categories_completed=[],
            categories_failed=["community"],
            message="Nothing found",
        )
        await sink.error("upstream_error", "Timed out", node="retrieve_evidence")
        await sink.run_status(RunStatus.AWAITING_INPUT)
        await sink.run_completed("Done")
        assert [e.seq for e in sink.events] == list(range(1, 15))
        assert sink.types[-1] == "run_completed"
        evidence = sink.events[5]
        assert evidence.event == "evidence_found"
        assert len(evidence.quote or "") <= 600  # type: ignore[union-attr]

    def test_example_from_the_spec_parses(self) -> None:
        event = parse_event(
            {
                "event": "node_started",
                "run_id": str(uuid4()),
                "seq": 1,
                "ts": "2026-09-29T10:00:00Z",
                "node": "document_analysis",
                "label": "Analyzing your documents",
            }
        )
        assert event.event == "node_started"
        assert event.label == "Analyzing your documents"  # type: ignore[union-attr]
        assert "data" not in event.model_dump()


class _State(TypedDict, total=False):
    steps: list[str]
    approved: bool
    summary: str


def _ctx(sink: MemoryEventSink) -> AgentContext:
    return AgentContext(
        principal=Principal(user_id=uuid4(), tenant_id=uuid4()),
        run_id=sink.run_id,
        events=sink,
        db=None,  # type: ignore[arg-type]
        adapters=None,  # type: ignore[arg-type]
    )


@instrumented("plan_journey", "Plan your journey")
async def _plan(state: _State, runtime: Runtime[AgentContext]) -> dict[str, object]:
    await report(runtime, "Ordering steps", 0.5)
    return {"steps": ["licence", "visa"], "_summary": "2 steps"}


@instrumented("approval_gate", "Your approval")
async def _gate(state: _State, runtime: Runtime[AgentContext]) -> dict[str, object]:
    decision = interrupt({"approval_id": "a1"})
    return {"approved": decision == "approve"}


@instrumented("synthesize_plan", "Your Abu Dhabi plan")
async def _finish(state: _State, runtime: Runtime[AgentContext]) -> dict[str, object]:
    return {"summary": f"{len(state['steps'])} steps, approved={state.get('approved')}"}


@instrumented("retrieve_evidence", "Check official sources")
async def _broken(state: _State, runtime: Runtime[AgentContext]) -> dict[str, object]:
    raise UpstreamError("Retrieval service timed out")


def _graph(*nodes: tuple[str, object]):  # type: ignore[no-untyped-def]
    graph = StateGraph(_State, context_schema=AgentContext)
    previous = START
    for name, fn in nodes:
        graph.add_node(name, fn)  # type: ignore[arg-type]
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile(checkpointer=InMemorySaver())


class TestInstrumentedRuns:
    async def test_completed_run_emits_full_lifecycle(self) -> None:
        sink = MemoryEventSink(uuid4())
        graph = _graph(("plan_journey", _plan), ("synthesize_plan", _finish))
        outcome = await execute_run(
            graph=graph, ctx=_ctx(sink), kind=RunKind.JOURNEY, thread_id="t1", graph_input={}
        )
        assert outcome.status == "completed"
        assert sink.types == [
            "run_started",
            "node_started",
            "node_progress",
            "node_completed",
            "node_started",
            "node_completed",
            "run_completed",
        ]
        completed = sink.events[3]
        assert completed.node == "plan_journey"
        assert completed.summary == "2 steps"  # type: ignore[union-attr]
        assert "_summary" not in outcome.values

    async def test_interrupt_pauses_then_resumes(self) -> None:
        sink = MemoryEventSink(uuid4())
        graph = _graph(
            ("plan_journey", _plan), ("approval_gate", _gate), ("synthesize_plan", _finish)
        )
        ctx = _ctx(sink)
        first = await execute_run(
            graph=graph, ctx=ctx, kind=RunKind.JOURNEY, thread_id="t2", graph_input={}
        )
        assert first.status == "interrupted"
        assert "error" not in sink.types
        assert sink.events[-1].event == "run_status"
        assert sink.events[-1].status is RunStatus.AWAITING_INPUT  # type: ignore[union-attr]

        second = await execute_run(
            graph=graph,
            ctx=ctx,
            kind=RunKind.JOURNEY,
            thread_id="t2",
            graph_input=Command(resume="approve"),
        )
        assert second.status == "completed"
        assert second.values["summary"] == "2 steps, approved=True"
        assert sink.types[-1] == "run_completed"

    async def test_failure_is_reported_not_raised(self) -> None:
        sink = MemoryEventSink(uuid4())
        graph = _graph(("retrieve_evidence", _broken))
        outcome = await execute_run(
            graph=graph, ctx=_ctx(sink), kind=RunKind.JOURNEY, thread_id="t3", graph_input={}
        )
        assert outcome.status == "failed"
        failed = next(e for e in sink.events if e.event == "error")
        assert failed.node == "retrieve_evidence"
        assert failed.code == "upstream_error"  # type: ignore[union-attr]
        assert sink.types[-1] == "run_failed"
