"""Research tables: ResearchJob, ResearchResult, ResearchCitation (private, owner-only RLS).

Loaded by `app.db.models` as a feature model module; must import cleanly with no
application-level side effects (and must not import `app.db.models`).

Honesty rules are repeated here as CHECK constraints (the third layer after the Pydantic
`Provenance` validator and the processing step): law and official guidance require an
official source, and every result and citation points at a real web page.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Owned, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import EvidenceKind
from app.research.types import ResearchCategory, ResearchMode, SourceLabel

PRIVATE_TABLES: tuple[str, ...] = ("research_jobs", "research_results", "research_citations")

_CATEGORY_ARRAY = ", ".join(f"'{c.value}'" for c in ResearchCategory)


class ResearchJob(Base, UUIDPrimaryKey, Timestamps, Owned):
    """One background research request. Lifecycle status lives on its `agent_runs` row."""

    __tablename__ = "research_jobs"
    __table_args__ = (
        enum_check("mode", ResearchMode),
        CheckConstraint(
            f"categories <@ ARRAY[{_CATEGORY_ARRAY}]::varchar[]", name="categories_valid"
        ),
        CheckConstraint("cardinality(categories) > 0", name="categories_present"),
        Index("ix_research_jobs_user_created", "user_id", "created_at"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    journey_id: Mapped[UUID | None] = mapped_column(ForeignKey("journeys.id", ondelete="SET NULL"))
    categories: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    # {category: {status, result_count, reason}} updated atomically per category.
    category_status: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # The consent-filtered ResearchProfile actually used (never the user's name).
    profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    mode: Mapped[ResearchMode] = mapped_column(str_enum(ResearchMode, 20), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchResult(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "research_results"
    __table_args__ = (
        enum_check("category", ResearchCategory),
        enum_check("evidence_kind", EvidenceKind),
        enum_check("source_label", SourceLabel),
        CheckConstraint(
            "evidence_kind NOT IN ('authoritative_requirement', 'official_guidance') "
            "OR source_label = 'official'",
            name="official_claims_need_official_source",
        ),
        CheckConstraint(
            "source_label <> 'official' OR starts_with(source_url, 'https://')",
            name="official_sources_are_https",
        ),
        CheckConstraint(
            "starts_with(source_url, 'http://') OR starts_with(source_url, 'https://')",
            name="source_url_is_web",
        ),
        CheckConstraint("quality_score BETWEEN 0 AND 1", name="quality_score_range"),
        CheckConstraint(
            "event_ends_on IS NULL OR event_starts_on IS NULL OR event_ends_on >= event_starts_on",
            name="event_dates_ordered",
        ),
        UniqueConstraint("job_id", "category", "dedupe_key", name="uq_research_results_dedupe"),
        Index("ix_research_results_user_saved", "user_id", "saved_at"),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[ResearchCategory] = mapped_column(str_enum(ResearchCategory), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    relevance: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_kind: Mapped[EvidenceKind] = mapped_column(str_enum(EvidenceKind), nullable=False)
    source_label: Mapped[SourceLabel] = mapped_column(str_enum(SourceLabel, 20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Internal ranking only: never exposed through the API.
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    event_starts_on: Mapped[date | None] = mapped_column(Date)
    event_ends_on: Mapped[date | None] = mapped_column(Date)
    event_timing: Mapped[str | None] = mapped_column(String(200))
    fact_keys: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'")
    )
    # Stored user facts (`extracted_facts` ids) behind the relevance, for `explain`.
    fact_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default=text("'{}'")
    )
    position: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journey_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journey_nodes.id", ondelete="SET NULL")
    )


class ResearchCitation(Base, UUIDPrimaryKey, Owned):
    """A source page behind a result (primary first). Web pages only, always dated."""

    __tablename__ = "research_citations"
    __table_args__ = (
        enum_check("category", ResearchCategory),
        enum_check("source_label", SourceLabel),
        CheckConstraint(
            "starts_with(url, 'http://') OR starts_with(url, 'https://')", name="url_is_web"
        ),
        UniqueConstraint("result_id", "canonical_url", name="uq_research_citations_result_url"),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    result_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[ResearchCategory] = mapped_column(str_enum(ResearchCategory), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_label: Mapped[SourceLabel] = mapped_column(str_enum(SourceLabel, 20), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
