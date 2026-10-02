"""Personalised journeys: a plan graph of journey nodes and dependency edges (RLS owner-only).

Journey edges reference their nodes through composite foreign keys on
(journey_id, node id), so an edge can never connect nodes of two different journeys.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Owned, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import JourneyEdgeType, JourneyStatus, StepCategory, StepStatus


class Journey(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "journeys"
    __table_args__ = (
        enum_check("status", JourneyStatus),
        Index("ix_journeys_user_updated", "user_id", "updated_at"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[JourneyStatus] = mapped_column(
        str_enum(JourneyStatus), nullable=False, server_default=JourneyStatus.DRAFT.value
    )
    summary: Mapped[str | None] = mapped_column(Text)
    goals: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    assumptions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    considerations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Agent snapshot: tasks, dependencies, risks, requirements, eligibility, facts used.
    plan: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # What-if scenarios: the diff against the parent journey.
    simulation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parent_journey_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journeys.id", ondelete="CASCADE")
    )


class JourneyNode(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "journey_nodes"
    __table_args__ = (
        enum_check("status", StepStatus),
        enum_check("category", StepCategory),
        UniqueConstraint("journey_id", "key", name="uq_journey_nodes_journey_key"),
        # Target of the composite foreign keys on journey_edges.
        UniqueConstraint("journey_id", "id", name="uq_journey_nodes_journey_id_id"),
    )

    journey_id: Mapped[UUID] = mapped_column(
        ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="task", doc="task | milestone | risk | ..."
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    category: Mapped[StepCategory] = mapped_column(str_enum(StepCategory), nullable=False)
    status: Mapped[StepStatus] = mapped_column(str_enum(StepStatus), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    governance_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL")
    )
    authority: Mapped[str | None] = mapped_column(String(200))
    official_url: Mapped[str | None] = mapped_column(String(2048))
    estimated_duration_days: Mapped[int | None] = mapped_column(Integer)
    due_by: Mapped[date | None] = mapped_column(Date)
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Which user-graph facts informed this node: [{key, label, fact_refs[]}] — IDs only.
    basis: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class JourneyEdge(Base, UUIDPrimaryKey, Owned):
    __tablename__ = "journey_edges"
    __table_args__ = (
        enum_check("relation", JourneyEdgeType),
        CheckConstraint("source_node_id <> target_node_id", name="no_self_loops"),
        UniqueConstraint(
            "source_node_id", "target_node_id", "relation", name="uq_journey_edges_triple"
        ),
        ForeignKeyConstraint(
            ["journey_id", "source_node_id"],
            ["journey_nodes.journey_id", "journey_nodes.id"],
            name="fk_journey_edges_source_same_journey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["journey_id", "target_node_id"],
            ["journey_nodes.journey_id", "journey_nodes.id"],
            name="fk_journey_edges_target_same_journey",
            ondelete="CASCADE",
        ),
    )

    journey_id: Mapped[UUID] = mapped_column(
        ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[UUID] = mapped_column(nullable=False)
    target_node_id: Mapped[UUID] = mapped_column(nullable=False)
    relation: Mapped[JourneyEdgeType] = mapped_column(
        str_enum(JourneyEdgeType), nullable=False, server_default=JourneyEdgeType.DEPENDS_ON.value
    )
    properties_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
