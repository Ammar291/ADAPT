"""The persisted, resumable journey graph.

    START -> intake -> profile_analysis -> document_analysis -> eligibility_analysis
          -> requirement_planner -> dependency_analysis -> risk_detection
          -> document_preparation -> action_preparation -> human_approval
          -> execution_or_handoff -> final_plan -> END

Compiled with the Postgres checkpointer (`AsyncPostgresSaver`), so the state is saved
after every node. A run paused at a human gate (`interrupt`) resumes on the same
`thread_id` with `Command(resume=answer)`, even in another worker process days later.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.journey.context import JourneyContext
from app.agents.journey.nodes import JOURNEY_SEQUENCE
from app.agents.journey.spec import spec_of
from app.agents.journey.state import JourneyState, UserRequest


def build_journey_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(JourneyState, context_schema=JourneyContext)
    previous = START
    for node in JOURNEY_SEQUENCE:
        name = spec_of(node).id.value
        graph.add_node(name, node)
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile(checkpointer=checkpointer)


def journey_input(
    *,
    user_id: str,
    journey_id: str,
    run_id: str,
    text: str,
    language: str = "en",
    channel: str = "text",
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    """The initial state of a journey run."""
    return {
        "user_id": user_id,
        "journey_id": journey_id,
        "run_id": run_id,
        "mode": "journey",
        "request": UserRequest(text=text, language=language, channel=channel),  # type: ignore[typeddict-item]
        "document_ids": list(document_ids or []),
        "user_facts": {},
        "evidence": [],
        "eligibility": [],
        "requirements": [],
        "tasks": [],
        "dependencies": [],
        "risks": [],
        "generated_documents": [],
        "actions": [],
        "approval_requests": [],
        "research_job_ids": [],
        "events": [],
        "final_summary": "",
    }
