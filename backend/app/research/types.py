"""Research vocabularies and the value objects passed between engines and processing.

Enum values are part of the API contract (exported to TypeScript), so renaming a member is
a breaking change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from app.domain.enums import EvidenceKind


class ResearchCategory(StrEnum):
    """What a research job looks for. Each maps to one Discover section."""

    COMMUNITY = "community"  # Your Communities
    FAITH_AND_WORSHIP = "faith_and_worship"  # Your Faith & Places (explicit opt-in only)
    PROFESSIONAL_NETWORK = "professional_network"  # Your Professional Network
    EVENTS = "events"  # Local Events
    CULTURE = "culture"  # Cultural Guide
    LIFESTYLE = "lifestyle"  # Things That May Surprise You
    STARTER_KIT = "starter_kit"  # Starter Kit


ALL_CATEGORIES: tuple[ResearchCategory, ...] = tuple(ResearchCategory)

# Open-ended "find organisations" searches: agentic multi-step search (reasoning model that
# searches several times, then a gap-filling follow-up round).
COMPLEX_CATEGORIES: frozenset[ResearchCategory] = frozenset(
    {
        ResearchCategory.COMMUNITY,
        ResearchCategory.FAITH_AND_WORSHIP,
        ResearchCategory.PROFESSIONAL_NETWORK,
        ResearchCategory.EVENTS,
    }
)

# Categories whose results are about groups/events a person might join. Without faith
# opt-in, faith-specific results are removed from these, so faith content is never
# targeted at someone based on their nationality, background or interests.
FAITH_GUARDED_CATEGORIES: frozenset[ResearchCategory] = frozenset(
    {
        ResearchCategory.COMMUNITY,
        ResearchCategory.PROFESSIONAL_NETWORK,
        ResearchCategory.EVENTS,
    }
)


class SourceLabel(StrEnum):
    """Human-readable source type shown instead of any numeric score."""

    OFFICIAL = "official"  # UAE / Abu Dhabi government domain
    ORGANIZATION = "organization"  # the organisation's own website
    COMMUNITY = "community"  # community platforms (Meetup, InterNations, social media)
    GENERAL_WEB = "general_web"  # news, blogs, listings, everything else


class ClaimedSourceType(StrEnum):
    """What the extraction model says a source is. A hint only: domain rules win."""

    GOVERNMENT = "government"
    ORGANIZATION_SITE = "organization_site"
    COMMUNITY_PLATFORM = "community_platform"
    NEWS_OR_BLOG = "news_or_blog"
    OTHER = "other"


class CategoryStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResearchMode(StrEnum):
    LIVE = "live"  # OpenAI web search, now
    SNAPSHOT = "snapshot"  # curated, URL-verified offline source list


class RelocationType(StrEnum):
    WORK = "work"
    BUSINESS = "business"
    FAMILY = "family"
    STUDY = "study"
    RETIREMENT = "retirement"
    OTHER = "other"


class ContactKind(StrEnum):
    WEBSITE = "website"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"


# --- engine output ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A page an engine actually read (a web-search citation or a curated snapshot URL)."""

    url: str
    title: str
    retrieved_at: datetime
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class ContactCandidate:
    kind: ContactKind
    value: str
    source_url: str


@dataclass(slots=True)
class Candidate:
    """One proposed result, before validation, classification, scoring and dedup."""

    category: ResearchCategory
    title: str
    summary: str
    relevance: str
    claim_kind: EvidenceKind
    primary_url: str
    source_urls: list[str] = field(default_factory=list)
    claimed_source_type: ClaimedSourceType | None = None
    contacts: list[ContactCandidate] = field(default_factory=list)
    event_starts_on: date | None = None
    event_ends_on: date | None = None
    event_timing: str | None = None
    involves_faith: bool = False
    fact_keys: list[str] = field(default_factory=list)  # profile facts the relevance used


@dataclass(slots=True)
class CategoryFindings:
    """What an engine found for one category. `sources` is the grounding set: a candidate
    may only cite URLs that appear here (anything else is treated as hallucinated)."""

    category: ResearchCategory
    mode: ResearchMode
    candidates: list[Candidate]
    sources: dict[str, SourceRef]  # canonical URL -> source
    queries: list[str] = field(default_factory=list)


# --- processing output -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessedCitation:
    url: str
    canonical_url: str
    title: str
    source_domain: str
    source_label: SourceLabel
    retrieved_at: datetime
    summary: str | None
    is_primary: bool


@dataclass(frozen=True, slots=True)
class VerifiedContact:
    kind: ContactKind
    value: str
    source_url: str
    verified_at: datetime


@dataclass(slots=True)
class ProcessedResult:
    category: ResearchCategory
    title: str
    summary: str
    relevance: str
    claim_kind: EvidenceKind
    source_label: SourceLabel
    citations: list[ProcessedCitation]  # primary first
    quality_score: float  # internal ranking only; never shown to users
    dedupe_key: str
    contacts: list[VerifiedContact] = field(default_factory=list)
    event_starts_on: date | None = None
    event_ends_on: date | None = None
    event_timing: str | None = None
    fact_keys: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)  # stored user facts behind relevance
    notes: list[str] = field(default_factory=list)  # processing decisions, for logs/tests

    @property
    def primary(self) -> ProcessedCitation:
        return self.citations[0]
