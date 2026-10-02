"""Public Discover catalogue: communities, events and cultural guides.

Shared, non-personal reference content (readable by every signed-in user, written only by
the owner role through curation/seeding). Every row either cites where it came from or is
explicitly flagged `is_sample` — sample rows are demo content, never presented as real.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import CommunityCategory, EventCategory, EvidenceKind, GuideTopic

_CITED_OR_SAMPLE = "is_sample OR source_url IS NOT NULL"
_NEVER_AUTHORITATIVE = "evidence_kind <> 'authoritative_requirement'"


class _Sourced:
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_title: Mapped[str | None] = mapped_column(String(500))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_kind: Mapped[EvidenceKind] = mapped_column(str_enum(EvidenceKind), nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class Community(Base, UUIDPrimaryKey, Timestamps, _Sourced):
    __tablename__ = "communities"
    __table_args__ = (
        UniqueConstraint("key", name="uq_communities_key"),
        enum_check("category", CommunityCategory),
        enum_check("evidence_kind", EvidenceKind),
        CheckConstraint(_CITED_OR_SAMPLE, name="cited_or_sample"),
        CheckConstraint(_NEVER_AUTHORITATIVE, name="never_authoritative"),
        Index("ix_communities_category", "category"),
    )

    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[CommunityCategory] = mapped_column(str_enum(CommunityCategory), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(35)), nullable=False, server_default=text("'{}'")
    )
    area: Mapped[str | None] = mapped_column(String(200))
    website_url: Mapped[str | None] = mapped_column(String(2048))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), nullable=False, server_default=text("'{}'")
    )


class Event(Base, UUIDPrimaryKey, Timestamps, _Sourced):
    """A community or cultural event (table `events`; unrelated to agent events)."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("key", name="uq_events_key"),
        enum_check("category", EventCategory),
        enum_check("evidence_kind", EvidenceKind),
        CheckConstraint(_CITED_OR_SAMPLE, name="cited_or_sample"),
        CheckConstraint(_NEVER_AUTHORITATIVE, name="never_authoritative"),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at", name="ends_after_start"
        ),
        CheckConstraint("starts_at IS NOT NULL OR timing_note IS NOT NULL", name="has_timing"),
        Index("ix_events_starts_at", "starts_at"),
    )

    key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[EventCategory] = mapped_column(str_enum(EventCategory), nullable=False)
    # NULL for recurring events whose next date is not confirmed: see `timing_note`.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timing_note: Mapped[str | None] = mapped_column(String(200))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(300))
    area: Mapped[str | None] = mapped_column(String(200))
    community_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("communities.id", ondelete="SET NULL")
    )
    url: Mapped[str | None] = mapped_column(String(2048))
    is_free: Mapped[bool | None] = mapped_column(Boolean)
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(35)), nullable=False, server_default=text("'{}'")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), nullable=False, server_default=text("'{}'")
    )


class CulturalGuide(Base, UUIDPrimaryKey, Timestamps, _Sourced):
    __tablename__ = "cultural_guides"
    __table_args__ = (
        UniqueConstraint("key", name="uq_cultural_guides_key"),
        enum_check("topic", GuideTopic),
        enum_check("evidence_kind", EvidenceKind),
        CheckConstraint(_CITED_OR_SAMPLE, name="cited_or_sample"),
        CheckConstraint(_NEVER_AUTHORITATIVE, name="never_authoritative"),
        CheckConstraint("section IN ('culture', 'surprises', 'starter_kit')", name="section_valid"),
    )

    key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    topic: Mapped[GuideTopic] = mapped_column(str_enum(GuideTopic), nullable=False)
    section: Mapped[str] = mapped_column(String(40), nullable=False, server_default="culture")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False, server_default="en")
    authority: Mapped[str | None] = mapped_column(String(200))
    # States a legal rule (e.g. the midday outdoor-work break). Still never stored as an
    # authoritative requirement; clients may label it "Law" when the source is official.
    binding: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
