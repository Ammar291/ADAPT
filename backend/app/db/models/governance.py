"""Governance corpus for retrieval-augmented generation (public, never user-scoped).

* `governance_sources`   — a publisher / site registry entry (e.g. the ICP website).
* `governance_documents` — one retrieved VERSION of one page or document. Re-ingesting
  changed content inserts a new row and stamps the previous one `superseded_at`, so at
  most one live version exists per `source_url` and citations keep pointing at the exact
  version they quoted.
* `governance_chunks`    — retrievable passages with a pgvector embedding and a
  language-agnostic tsvector.

The runtime role can only read these tables. Writes happen through the owner connection
(migrations, seeding, curated ingestion).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import EMBEDDING_DIMENSIONS
from app.db.base import Base, Timestamps, UUIDPrimaryKey


class GovernanceSource(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "governance_sources"
    __table_args__ = (
        UniqueConstraint("key", name="uq_governance_sources_key"),
        Index("ix_governance_sources_authority", "authority"),
    )

    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    authority: Mapped[str | None] = mapped_column(
        String(200), doc="Governance graph key of the authority, e.g. 'authority.icp'"
    )
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(60), nullable=False, doc="portal | legislation | guidance | open_data | other"
    )
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class GovernanceDocument(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "governance_documents"
    __table_args__ = (
        UniqueConstraint("source_url", "content_hash", name="uq_governance_documents_url_hash"),
        Index(
            "uq_governance_documents_live_url",
            "source_url",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_governance_documents_authority", "authority"),
        Index("ix_governance_documents_document_type", "document_type"),
    )

    governance_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_sources.id", ondelete="SET NULL"), index=True
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(200))
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False, server_default="en")
    effective_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class GovernanceChunk(Base, UUIDPrimaryKey):
    __tablename__ = "governance_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_governance_chunks_document_index"),
        Index(
            "ix_governance_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_governance_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index("ix_governance_chunks_embedding_model", "embedding_model"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Title + section heading, prepended for lexical matching and shown with citations.
    context: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(String(500))
    page: Mapped[int | None] = mapped_column(Integer)
    page_or_section: Mapped[str | None] = mapped_column(
        Text, Computed("coalesce(section, 'p. ' || page::text)", persisted=True)
    )
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # Which embedder produced `embedding`; retrieval only compares like with like.
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    # 'simple' config: language-agnostic lexical matching for Arabic + English content.
    content_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(context, '') || ' ' || content)", persisted=True),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
