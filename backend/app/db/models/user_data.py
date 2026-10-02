"""Private user data owned by document intelligence & personalization (migration 0004).

* `user_documents`: uploaded documents. The bytes are encrypted in document storage; this
  row holds metadata plus a value-free summary of what was read.
* `extracted_facts`: every personal detail in the private user graph, one row per
  (entity, attribute), with provenance: value, confidence, source, source document,
  extraction method.
* `review_tasks`: things a person needs to check (low confidence, conflicts, documents
  that could not be read).

All three are owner-only under row-level security, and a trigger rejects references to
governance nodes or to another user's nodes and documents (FK checks bypass RLS).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Owned, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.documents.catalogue import DocumentKind, DocumentStatus, DocumentSubject
from app.domain.enums import FactSource
from app.personalization.facts_model import (
    FactStatus,
    ReviewResolution,
    ReviewTaskKind,
    ReviewTaskStatus,
)

PRIVATE_TABLES: tuple[str, ...] = ("user_documents", "extracted_facts", "review_tasks")


class UserDocument(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "user_documents"
    __table_args__ = (
        enum_check("kind", DocumentKind),
        enum_check("status", DocumentStatus),
        enum_check("subject", DocumentSubject),
        CheckConstraint(
            "(status = 'deleted') = (deleted_at IS NOT NULL)", name="deleted_at_matches_status"
        ),
        CheckConstraint(
            "status = 'deleted' OR (storage_key IS NOT NULL AND size_bytes > 0)",
            name="live_documents_have_bytes",
        ),
        CheckConstraint(
            "kind_confidence IS NULL OR kind_confidence BETWEEN 0 AND 1",
            name="kind_confidence_range",
        ),
        Index("ix_user_documents_user_created", "user_id", "created_at"),
    )

    kind: Mapped[DocumentKind] = mapped_column(str_enum(DocumentKind), nullable=False)
    declared_kind: Mapped[DocumentKind | None] = mapped_column(
        str_enum(DocumentKind), doc="What the person said the document is, if anything"
    )
    kind_confidence: Mapped[float | None] = mapped_column(Float)
    subject: Mapped[DocumentSubject] = mapped_column(
        str_enum(DocumentSubject), nullable=False, server_default=DocumentSubject.SELF.value
    )
    subject_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL"),
        doc="The person, spouse or child node this document belongs to",
    )
    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL"),
        doc="The user-graph node representing this document (passport or document entity)",
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(300), unique=True)
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus), nullable=False, server_default=DocumentStatus.UPLOADED.value
    )
    status_reason: Mapped[str | None] = mapped_column(String(300))
    # Value-free summary of the last extraction: method, detected kind, per-field confidence
    # and issues, fact ids. Values live only in extracted_facts.
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractedFact(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "extracted_facts"
    __table_args__ = (
        enum_check("source", FactSource),
        enum_check("status", FactStatus),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint(
            "status <> 'accepted' OR (value IS NOT NULL AND value <> 'null'::jsonb)",
            name="accepted_facts_have_values",
        ),
        CheckConstraint(
            "source <> 'document_extracted' "
            "OR (source_document_id IS NOT NULL AND extraction_method IS NOT NULL)",
            name="extracted_facts_cite_document",
        ),
        CheckConstraint(
            "attribute <> 'faith_community' OR source = 'user_stated'",
            name="faith_is_user_stated",
        ),
        Index(
            "uq_extracted_facts_accepted",
            "node_id",
            "attribute",
            unique=True,
            postgresql_where=text("status = 'accepted'"),
        ),
        Index(
            "uq_extracted_facts_pending",
            "node_id",
            "attribute",
            unique=True,
            postgresql_where=text("status = 'needs_review'"),
        ),
        Index("ix_extracted_facts_source_document_id", "source_document_id"),
    )

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    attribute: Mapped[str] = mapped_column(String(60), nullable=False)
    # Null only while a fact awaits review (CHECK accepted_facts_have_values).
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[FactSource] = mapped_column(str_enum(FactSource), nullable=False)
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_documents.id", ondelete="CASCADE")
    )
    source_ref: Mapped[str | None] = mapped_column(
        String(200), doc="Other origins, e.g. 'profile:user_goals:<id>'"
    )
    extraction_method: Mapped[str | None] = mapped_column(String(80))
    field: Mapped[str | None] = mapped_column(String(60), doc="Document field it was read from")
    status: Mapped[FactStatus] = mapped_column(
        str_enum(FactStatus), nullable=False, server_default=FactStatus.ACCEPTED.value
    )
    confirmed_by_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    issues: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewTask(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "review_tasks"
    __table_args__ = (
        enum_check("kind", ReviewTaskKind),
        enum_check("status", ReviewTaskStatus),
        enum_check("resolution", ReviewResolution),
        CheckConstraint(
            "(status = 'open') = (resolved_at IS NULL)", name="resolved_at_matches_status"
        ),
        CheckConstraint(
            "(status = 'open') = (resolution IS NULL)", name="resolution_matches_status"
        ),
        Index(
            "uq_review_tasks_open_fact",
            "fact_id",
            unique=True,
            postgresql_where=text("status = 'open' AND fact_id IS NOT NULL"),
        ),
        Index("ix_review_tasks_user_status", "user_id", "status"),
    )

    kind: Mapped[ReviewTaskKind] = mapped_column(str_enum(ReviewTaskKind), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_documents.id", ondelete="CASCADE"), index=True
    )
    fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extracted_facts.id", ondelete="SET NULL")
    )
    field: Mapped[str | None] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReviewTaskStatus] = mapped_column(
        str_enum(ReviewTaskStatus), nullable=False, server_default=ReviewTaskStatus.OPEN.value
    )
    resolution: Mapped[ReviewResolution | None] = mapped_column(str_enum(ReviewResolution))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
