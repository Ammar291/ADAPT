"""Discover catalogue: communities, events and cultural guides.

Every item says where it came from (`source_url`, `source_title`, `retrieved_at`,
`evidence_kind`) or is explicitly `is_sample` demo content with no source.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.contracts.common import ApiModel
from app.domain.enums import CommunityCategory, EventCategory, EvidenceKind, GuideTopic


class _Sourced(ApiModel):
    source_url: str | None = None
    source_title: str | None = None
    retrieved_at: datetime | None = None
    evidence_kind: EvidenceKind
    is_sample: bool


class CommunityOut(_Sourced):
    id: UUID
    key: str
    name: str
    category: CommunityCategory
    description: str
    languages: list[str]
    area: str | None = None
    website_url: str | None = None
    tags: list[str]


class EventOut(_Sourced):
    id: UUID
    key: str
    title: str
    description: str
    category: EventCategory
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timing_note: str | None = None
    venue: str | None = None
    area: str | None = None
    community_id: UUID | None = None
    url: str | None = None
    is_free: bool | None = None
    languages: list[str]
    tags: list[str]


class CulturalGuideOut(_Sourced):
    id: UUID
    key: str
    title: str
    topic: GuideTopic
    section: str
    summary: str
    body_markdown: str
    language: str
    authority: str | None = None
    binding: bool = False
