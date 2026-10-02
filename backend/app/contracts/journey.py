"""Journey read models: a dependency-aware plan of journey nodes and edges.

Journey creation, simulation and the planning logic belong to the journey agent
(`app.agents.journey`); these are the shared read shapes for the stored journey.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.contracts.common import ApiModel
from app.domain.enums import (
    BlockerKind,
    JourneyEdgeType,
    JourneyStatus,
    StepCategory,
    StepStatus,
)
from app.domain.provenance import Provenance


class Blocker(ApiModel):
    kind: BlockerKind
    message: str
    resolution: str | None = Field(default=None, description="What the user can do about it")
    related_node_key: str | None = None
    related_document: str | None = None


class BasisRef(ApiModel):
    """A user-graph fact the plan relied on (IDs/keys only, never values)."""

    key: str
    label: str
    fact_refs: list[str] = Field(default_factory=list)


class JourneyNodeOut(ApiModel):
    id: UUID
    key: str = Field(description="Stable within a journey; used for dependencies and diffs")
    kind: str
    title: str
    summary: str
    category: StepCategory
    status: StepStatus
    position: int
    governance_node_id: UUID | None = None
    authority: str | None = None
    official_url: str | None = None
    estimated_duration_days: int | None = None
    due_by: date | None = None
    blockers: list[Blocker] = Field(default_factory=list)
    provenance: Provenance
    basis: list[BasisRef] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class JourneyEdgeOut(ApiModel):
    id: UUID
    source_node_id: UUID = Field(description="The node that depends on the target")
    target_node_id: UUID
    relation: JourneyEdgeType
    properties: dict[str, Any] = Field(default_factory=dict)


class JourneyOut(ApiModel):
    id: UUID
    title: str
    status: JourneyStatus
    summary: str | None = None
    goals: list[Any]
    assumptions: dict[str, Any]
    considerations: list[dict[str, Any]]
    nodes: list[JourneyNodeOut]
    edges: list[JourneyEdgeOut]
    simulation: dict[str, Any] | None = None
    parent_journey_id: UUID | None = Field(
        default=None, description="Set for what-if scenarios: the journey they branched from"
    )
    created_at: datetime
    updated_at: datetime


class JourneySummary(ApiModel):
    id: UUID
    title: str
    status: JourneyStatus
    node_count: int
    completed_node_count: int
    parent_journey_id: UUID | None = None
    updated_at: datetime
