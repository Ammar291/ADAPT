"""Agent graph topology, shared with the frontend's live LangGraph visualisation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from app.contracts.common import ApiModel


class JourneyNodeId(StrEnum):
    UNDERSTAND_REQUEST = "understand_request"
    CLARIFY = "clarify"
    INGEST_DOCUMENTS = "ingest_documents"
    BUILD_TWIN = "build_twin"
    APPLY_SCENARIO = "apply_scenario"
    QUERY_GOVERNANCE = "query_governance"
    RETRIEVE_EVIDENCE = "retrieve_evidence"
    PLAN_JOURNEY = "plan_journey"
    ANALYZE_BLOCKERS = "analyze_blockers"
    DRAFT_DOCUMENTS = "draft_documents"
    PREPARE_ACTIONS = "prepare_actions"
    APPROVAL_GATE = "approval_gate"
    EXECUTE_ACTIONS = "execute_actions"
    DISPATCH_RESEARCH = "dispatch_research"
    SURFACE_CONSIDERATIONS = "surface_considerations"
    SYNTHESIZE_PLAN = "synthesize_plan"


NodeKind = Literal["agent", "tool", "human", "router"]


class TopologyNode(ApiModel):
    id: str
    label: str
    description: str
    kind: NodeKind
    lane: int = 0  # layout hint: parallel branches share a rank and differ by lane


class TopologyEdge(ApiModel):
    source: str
    target: str
    condition: str | None = None


class AgentTopology(ApiModel):
    graph: str
    version: str
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
