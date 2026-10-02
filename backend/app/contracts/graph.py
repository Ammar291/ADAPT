"""Graph read models: the shared governance graph, the private user graph, and journeys.

The views are separate types on purpose: `GovernanceGraphView` can never carry user-graph
data, and `TwinGraphView` / `JourneyGraphView` are only ever served to their owner.
Field names follow the storage vocabulary (`graph_type`, `entity_type`, `relation`,
`source_node_id`, `target_node_id`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.contracts.common import ApiModel
from app.contracts.journey import JourneyEdgeOut, JourneyNodeOut
from app.domain.enums import GovernanceNodeType, GraphEdgeType, GraphType, TwinNodeType
from app.domain.provenance import Provenance
from app.domain.twin import TwinFact


class GovernanceNodeOut(ApiModel):
    id: UUID
    graph_type: Literal["governance"] = "governance"
    entity_type: GovernanceNodeType
    key: str = Field(description="Stable slug, e.g. 'service.family_residence_visa'")
    label: str
    summary: str | None = None
    properties: dict[str, Any]
    provenance: Provenance | None = None
    official_url: str | None = None
    source_id: UUID | None = None


class GraphEdgeOut(ApiModel):
    id: UUID
    graph_type: GraphType
    relation: GraphEdgeType
    source_node_id: UUID
    target_node_id: UUID
    label: str | None = None
    properties: dict[str, Any]


class GovernanceGraphView(ApiModel):
    nodes: list[GovernanceNodeOut]
    edges: list[GraphEdgeOut]
    generated_at: datetime


class GovernanceNodeDetail(ApiModel):
    node: GovernanceNodeOut
    neighbours: list[GovernanceNodeOut]
    edges: list[GraphEdgeOut]


class TwinNodeOut(ApiModel):
    """A node of the caller's private user graph (their digital twin)."""

    id: UUID
    graph_type: Literal["user"] = "user"
    entity_type: TwinNodeType
    key: str
    label: str
    facts: dict[str, TwinFact]
    updated_at: datetime


class TwinGraphView(ApiModel):
    """The caller's private user graph plus the governance nodes it links to."""

    nodes: list[TwinNodeOut]
    linked_governance_nodes: list[GovernanceNodeOut]
    edges: list[GraphEdgeOut]
    generated_at: datetime


class JourneyGraphView(ApiModel):
    """A journey as a graph: plan nodes, dependency edges, and the governance nodes the
    plan is grounded in."""

    journey_id: UUID
    nodes: list[JourneyNodeOut]
    edges: list[JourneyEdgeOut]
    governance_nodes: list[GovernanceNodeOut]
    generated_at: datetime
