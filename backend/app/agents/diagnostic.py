"""A tiny real LangGraph graph used to verify the agent pipeline end to end:
API -> ARQ worker -> LangGraph (instrumented nodes, checkpointer) -> run_events ->
Redis wake-up -> SSE -> browser. It reads only public data and adapter metadata.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from sqlalchemy import func, select

from app.agents.context import AgentContext
from app.agents.instrumentation import instrumented, report
from app.db.models import GraphNode
from app.domain.enums import GraphType


class DiagnosticState(TypedDict, total=False):
    governance_nodes: int
    demo_capabilities: list[str]
    summary: str


@instrumented("check_governance_graph", "Check the governance graph")
async def check_governance_graph(
    state: DiagnosticState, runtime: Runtime[AgentContext]
) -> dict[str, object]:
    async with runtime.context.db.public_session() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(GraphNode)
                .where(GraphNode.graph_type == GraphType.GOVERNANCE)
            )
        ).scalar_one()
    await report(runtime, f"{count} governance nodes available", 1.0)
    return {"governance_nodes": count, "_summary": f"{count} governance nodes"}


@instrumented("check_adapters", "Check integrations")
async def check_adapters(
    state: DiagnosticState, runtime: Runtime[AgentContext]
) -> dict[str, object]:
    demo = runtime.context.adapters.demo_capabilities
    for index, info in enumerate(runtime.context.adapters.infos(), start=1):
        await report(runtime, f"{info.capability}: {info.mode}", index / 6)
        await asyncio.sleep(0.15)  # paced so the live stream is visible in the UI
    live = len(runtime.context.adapters.infos()) - len(demo)
    return {"demo_capabilities": demo, "_summary": f"{live} live, {len(demo)} in demo mode"}


@instrumented("summarize", "Summarise")
async def summarize(state: DiagnosticState, runtime: Runtime[AgentContext]) -> dict[str, object]:
    demo = state.get("demo_capabilities") or []
    mode = f"demo adapters: {', '.join(demo)}" if demo else "all integrations live"
    nodes = state.get("governance_nodes", 0)
    return {"summary": f"Pipeline healthy — {nodes} governance nodes; {mode}."}


def build_diagnostic_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph: StateGraph[Any, Any, Any, Any] = StateGraph(DiagnosticState, context_schema=AgentContext)
    graph.add_node("check_governance_graph", check_governance_graph)  # type: ignore[call-overload]
    graph.add_node("check_adapters", check_adapters)  # type: ignore[call-overload]
    graph.add_node("summarize", summarize)  # type: ignore[call-overload]
    graph.add_edge(START, "check_governance_graph")
    graph.add_edge("check_governance_graph", "check_adapters")
    graph.add_edge("check_adapters", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile(checkpointer=checkpointer)
