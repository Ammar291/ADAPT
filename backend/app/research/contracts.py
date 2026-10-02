"""Research API contracts (exported to TypeScript through OpenAPI).

Results never expose the internal quality score. Users see a source label (Official /
Organization / Community / General web), the trust tier of the claim (`evidence_kind`)
and when the source was last checked.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.common import ApiModel
from app.domain.enums import EvidenceKind, RunStatus
from app.research.types import (
    CategoryStatus,
    ContactKind,
    RelocationType,
    ResearchCategory,
    ResearchMode,
    SourceLabel,
)

BRIEF_READY_MESSAGE = "Your Abu Dhabi Life Brief is ready."

# Discover sections, in page order: (section id, title, research category).
DISCOVER_SECTIONS: tuple[tuple[str, str, ResearchCategory], ...] = (
    ("your_communities", "Your Communities", ResearchCategory.COMMUNITY),
    ("faith", "Your Faith & Places", ResearchCategory.FAITH_AND_WORSHIP),
    ("professional", "Your Professional Network", ResearchCategory.PROFESSIONAL_NETWORK),
    ("events", "Local Events", ResearchCategory.EVENTS),
    ("culture", "Cultural Guide", ResearchCategory.CULTURE),
    ("surprises", "Things That May Surprise You", ResearchCategory.LIFESTYLE),
    ("starter_kit", "Starter Kit", ResearchCategory.STARTER_KIT),
)


# --- requests ------------------------------------------------------------------------------


class ResearchProfileInput(ApiModel):
    """Facts the user states for this research. Background and interests need community
    consent; faith needs faith consent (409 `consent_required` otherwise)."""

    relocation_type: RelocationType | None = None
    profession: str | None = Field(default=None, max_length=80)
    interests: list[str] = Field(default_factory=list, max_length=8)
    background: str | None = Field(
        default=None, max_length=80, description="Home country or community background"
    )
    faith: str | None = Field(default=None, max_length=40)


class StartResearchRequest(ApiModel):
    categories: list[ResearchCategory] | None = Field(
        default=None, description="Defaults to every category the user has consented to"
    )
    focus: str | None = Field(
        default=None, max_length=200, description="Something specific to look for"
    )
    journey_id: UUID | None = None
    profile: ResearchProfileInput | None = None
    force: bool = Field(default=False, description="Start a new job even if one is running")
    mode: Literal["auto", "snapshot"] = Field(
        default="auto",
        description="`snapshot` always uses ADAPT's curated source list (repeatable demos); "
        "`auto` searches the web when a key is configured",
    )


class SaveResultRequest(ApiModel):
    saved: bool


class AddToJourneyRequest(ApiModel):
    journey_id: UUID | None = Field(
        default=None, description="Defaults to the user's most recent active journey"
    )


# --- responses -------------------------------------------------------------------------------


class ResearchCategoryState(ApiModel):
    category: ResearchCategory
    status: CategoryStatus
    result_count: int = 0
    reason: str | None = None


class ResearchProfileOut(ApiModel):
    relocation_type: RelocationType | None
    profession: str | None
    interests: list[str]
    background: str | None
    faith: str | None
    focus: str | None
    faith_opted_in: bool
    community_opted_in: bool


class ResearchJobOut(ApiModel):
    id: UUID
    run_id: UUID
    status: RunStatus
    mode: ResearchMode
    categories: list[ResearchCategoryState]
    personalised_with: list[str]
    profile: ResearchProfileOut
    result_count: int
    brief_ready: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    seen_at: datetime | None
    events_url: str


class ResearchCitationOut(ApiModel):
    id: UUID
    url: str
    title: str
    source_domain: str
    source_label: SourceLabel
    retrieved_at: datetime
    summary: str | None
    category: ResearchCategory
    is_primary: bool


class ResearchContactOut(ApiModel):
    """Only contact details found on the cited page are ever returned."""

    kind: ContactKind
    value: str
    source_url: str
    verified_at: datetime


class ResearchEventInfo(ApiModel):
    starts_on: date | None
    ends_on: date | None
    timing_note: str | None


class ResearchRetrievalOut(ApiModel):
    """How a result's source was found and checked, in words a person can verify."""

    method: Literal["curated_snapshot", "live_web_search"]
    label: str = Field(description="e.g. 'ADAPT reviewed source list'")
    retrieved_at: datetime = Field(description="When the source page was checked")
    note: str


class ResearchResultOut(ApiModel):
    id: UUID
    job_id: UUID
    category: ResearchCategory
    title: str
    summary: str
    relevance: str = Field(description="Why this is relevant to the user")
    fact_ids: list[str] = Field(
        description="The user's stored facts behind `relevance`; explain them with "
        "POST /api/graph/user/explain"
    )
    evidence_kind: EvidenceKind
    source_label: SourceLabel
    source_url: str
    source_title: str
    source_domain: str
    retrieved_at: datetime = Field(description="When the source was last checked")
    needs_recheck: bool
    retrieval: ResearchRetrievalOut
    citations: list[ResearchCitationOut]
    contacts: list[ResearchContactOut]
    event: ResearchEventInfo | None
    saved: bool
    journey_node_id: UUID | None
    created_at: datetime


class ResearchJobStarted(ApiModel):
    job: ResearchJobOut
    events_url: str


class ResearchJobDetail(ApiModel):
    job: ResearchJobOut
    results: list[ResearchResultOut]


class DiscoverSectionOut(ApiModel):
    section: str
    title: str
    category: ResearchCategory
    status: CategoryStatus
    reason: str | None
    results: list[ResearchResultOut]


class DiscoverOut(ApiModel):
    job: ResearchJobOut | None
    sections: list[DiscoverSectionOut]
    saved: list[ResearchResultOut] = Field(description="Saved results from earlier briefs")
    message: str | None = Field(description="Set when the latest brief is ready")
