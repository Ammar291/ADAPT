"""Typed property graph for BOTH logical graphs (`graph_type` = governance | user).

Ownership invariants (enforced by CHECK constraints, a trigger and RLS policies):

* governance rows have NULL tenant_id/user_id and are shared by everyone;
* user rows always carry tenant_id/user_id and are visible only to that user;
* a governance edge can only connect governance nodes;
* a user edge starts at a user node of the same owner and ends either at a user node of
  the same owner or at a governance node (a private personalisation link).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
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

from app.core.config import EMBEDDING_DIMENSIONS
from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import GovernanceNodeType, GraphEdgeType, GraphType, TwinNodeType

OWNERSHIP_RULE = (
    "(graph_type = 'governance' AND tenant_id IS NULL AND user_id IS NULL) OR "
    "(graph_type = 'user' AND tenant_id IS NOT NULL AND user_id IS NOT NULL)"
)
_GOV_TYPES = ", ".join(f"'{t.value}'" for t in GovernanceNodeType)
_USER_TYPES = ", ".join(f"'{t.value}'" for t in TwinNodeType)
ENTITY_TYPE_RULE = (
    f"(graph_type = 'governance' AND entity_type IN ({_GOV_TYPES})) OR "
    f"(graph_type = 'user' AND entity_type IN ({_USER_TYPES}))"
)


class GraphNode(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        enum_check("graph_type", GraphType),
        CheckConstraint(OWNERSHIP_RULE, name="ownership_matches_graph"),
        CheckConstraint(ENTITY_TYPE_RULE, name="entity_type_matches_graph"),
        CheckConstraint("key ~ '^[a-z0-9_]+(\\.[a-z0-9_:-]+)*$'", name="key_format"),
        Index(
            "uq_graph_nodes_governance_key",
            "key",
            unique=True,
            postgresql_where=text("graph_type = 'governance'"),
        ),
        Index(
            "uq_graph_nodes_user_key",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("graph_type = 'user'"),
        ),
        Index("ix_graph_nodes_graph_type_entity_type", "graph_type", "entity_type"),
        Index("ix_graph_nodes_properties_json", "properties_json", postgresql_using="gin"),
        Index(
            "ix_graph_nodes_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    graph_type: Mapped[GraphType] = mapped_column(str_enum(GraphType, 20), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    properties_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Governance nodes: the publisher the node was curated from (see governance_sources).
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_sources.id", ondelete="SET NULL")
    )
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    official_url: Mapped[str | None] = mapped_column(String(2048))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class GraphEdge(Base, UUIDPrimaryKey):
    __tablename__ = "graph_edges"
    __table_args__ = (
        enum_check("graph_type", GraphType),
        enum_check("relation", GraphEdgeType),
        CheckConstraint(OWNERSHIP_RULE, name="ownership_matches_graph"),
        CheckConstraint("source_node_id <> target_node_id", name="no_self_loops"),
        UniqueConstraint(
            "source_node_id", "target_node_id", "relation", name="uq_graph_edges_triple"
        ),
        Index("ix_graph_edges_target", "target_node_id"),
        Index("ix_graph_edges_graph_type_relation", "graph_type", "relation"),
    )

    graph_type: Mapped[GraphType] = mapped_column(str_enum(GraphType, 20), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[GraphEdgeType] = mapped_column(str_enum(GraphEdgeType), nullable=False)
    source_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(200))
    properties_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GraphNodeEvidence(Base, UUIDPrimaryKey):
    """Links a governance node to the corpus passages that support it."""

    __tablename__ = "graph_node_evidence"
    __table_args__ = (
        UniqueConstraint("node_id", "chunk_id", name="uq_graph_node_evidence_node_chunk"),
    )

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_chunks.id", ondelete="CASCADE")
    )
    quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GraphEdgeEvidence(Base, UUIDPrimaryKey):
    """Links a governance edge (e.g. "service REQUIRES document") to supporting passages."""

    __tablename__ = "graph_edge_evidence"
    __table_args__ = (
        UniqueConstraint("edge_id", "chunk_id", name="uq_graph_edge_evidence_edge_chunk"),
    )

    edge_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_edges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_chunks.id", ondelete="CASCADE")
    )
    quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
