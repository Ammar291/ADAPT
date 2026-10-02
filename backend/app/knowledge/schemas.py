"""API contracts of the knowledge layer (exported to `@adapt/contracts` through OpenAPI).

Identifier namespaces are disjoint so the frontend can keep one highlight map across a
whole explanation: graph node and document ids are UUIDs, evidence ids are `ev_<hex>`,
user facts are addressed by their key, and journey tasks by their governance service key.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator

from app.contracts.common import ApiModel
from app.domain.enums import EvidenceKind, FactSource
from app.domain.twin import SENSITIVE_ATTRIBUTES
from app.knowledge.sources import SourceFamily


class KnowledgeTopic(StrEnum):
    RESIDENCY = "residency"
    FAMILY_RESIDENCY = "family_residency"
    EMIRATES_ID = "emirates_id"
    MEDICAL_FITNESS = "medical_fitness"
    HEALTH_INSURANCE = "health_insurance"
    HEALTHCARE = "healthcare"
    COMPANY_FORMATION = "company_formation"
    ADGM = "adgm"
    CORPORATE_TAX = "corporate_tax"
    HOUSING = "housing"
    TENANCY = "tenancy"
    TRANSPORT = "transport"
    DRIVING = "driving"
    UAE_PASS = "uae_pass"
    ATTESTATION = "attestation"
    NEWCOMER = "newcomer"
    CULTURE = "culture"


class SourceType(StrEnum):
    SERVICE_PAGE = "service_page"
    GUIDANCE_PAGE = "guidance_page"
    FAQ = "faq"
    REGULATION = "regulation"
    PORTAL_PAGE = "portal_page"
    NEWS = "news"


class Freshness(StrEnum):
    CURRENT = "current"  # checked within the freshness window
    STALE = "stale"  # checked longer ago than the window: confirm on the official page


class EvidenceCaveat(StrEnum):
    STALE_SOURCE = "stale_source"
    PARAPHRASED = "paraphrased"  # the claim restates the page rather than quoting it
    SNIPPET_ONLY = "snippet_only"  # only a search-result snippet of the page was readable
    NOT_YET_EFFECTIVE = "not_yet_effective"  # the page's effective date is in the future
    SUPERSEDED_SOURCE = "superseded_source"  # a newer version of the page exists
    UNOFFICIAL_SOURCE = "unofficial_source"  # never a government requirement


# --- evidence ----------------------------------------------------------------------------


class Evidence(ApiModel):
    """One passage from one version of one source page, with everything needed to cite it."""

    id: str = Field(description="Stable per passage version: 'ev_' + chunk id (hex)")
    claim: str = Field(description="The statement the passage makes (the passage text)")
    source_title: str
    source_url: str
    authority: str | None = Field(description="Publisher display name")
    authority_key: str | None = Field(description="Publisher key, e.g. 'authority.icp'")
    section_or_page: str | None = None
    retrieved_at: datetime
    effective_date: date | None = None
    confidence: float = Field(
        ge=0, le=1, description="Trust in the source (priority, freshness, verbatim or not)"
    )
    evidence_kind: EvidenceKind
    excerpt: Literal["quote", "paraphrase"]
    source_family: SourceFamily
    source_priority: int = Field(description="1 = highest (Abu Dhabi Government / TAMM)")
    freshness: Freshness
    caveats: list[EvidenceCaveat] = Field(default_factory=list)
    score: float | None = Field(
        default=None,
        description="Retrieval relevance after ranking; null for graph-linked evidence",
    )
    rank: int | None = None
    governance_keys: list[str] = Field(
        default_factory=list, description="Governance nodes whose facts this passage supports"
    )
    topics: list[KnowledgeTopic] = Field(default_factory=list)
    document_id: UUID
    chunk_id: UUID


# --- search / retrieve ---------------------------------------------------------------------


class RetrievalFilters(ApiModel):
    authorities: list[str] = Field(default_factory=list, description="Publisher keys")
    source_families: list[SourceFamily] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    topics: list[KnowledgeTopic] = Field(default_factory=list)
    governance_keys: list[str] = Field(
        default_factory=list,
        description="Only passages cited by these nodes or by their relationships",
    )
    languages: list[str] = Field(default_factory=list)
    official_only: bool = True
    include_stale: bool = True
    max_age_days: int | None = Field(default=None, ge=1, le=3650)


class RetrieveRequest(ApiModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=8, ge=1, le=50)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    min_score: float | None = Field(default=None, ge=0, le=1)


class RetrievalInfo(ApiModel):
    mode: Literal["hybrid", "lexical", "vector", "none"]
    embedding_model: str | None = None
    candidates: int = Field(description="Passages considered before top-k")
    filtered_stale: int = 0
    note: str | None = None


class RetrieveResponse(ApiModel):
    query: str
    evidence: list[Evidence]
    retrieval: RetrievalInfo
    applied_filters: RetrievalFilters


class NodeMatch(ApiModel):
    id: UUID
    key: str
    entity_type: str
    label: str
    summary: str | None = None
    official_url: str | None = None
    score: float


class KnowledgeSearchResponse(ApiModel):
    query: str
    results: list[Evidence]
    nodes: list[NodeMatch]
    retrieval: RetrievalInfo


# --- governance knowledge graph --------------------------------------------------------------


class SourceSummary(ApiModel):
    title: str
    url: str
    authority: str | None
    authority_key: str | None
    source_family: SourceFamily
    source_priority: int
    source_type: str
    retrieved_at: datetime
    effective_date: date | None = None
    freshness: Freshness


class KnowledgeNode(ApiModel):
    """A governance entity, or (entity_type = 'source') a cited source page."""

    id: UUID
    key: str
    entity_type: str = Field(
        description="authority | service | requirement | eligibility_rule | document | "
        "dependency | appointment | portal | location | … | source"
    )
    label: str
    summary: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    official_url: str | None = None
    evidence_kind: EvidenceKind | None = Field(
        default=None, description="Trust tier of the node's strongest evidence"
    )
    evidence_ids: list[str] = Field(default_factory=list)
    source: SourceSummary | None = Field(default=None, description="Set for source nodes")


class KnowledgeEdge(ApiModel):
    id: str = Field(description="Edge UUID, or 'evidenced_by:<node>:<document>' for evidence")
    relation: str = Field(
        description="provides | requires | depends_on | satisfied_by | produces | applies_to | "
        "available_at | may_require | located_in | governed_by | evidenced_by"
    )
    source: UUID
    target: UUID
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class KnowledgeGraphView(ApiModel):
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    evidence: list[Evidence]
    generated_at: datetime


# --- explain -------------------------------------------------------------------------------


class UserFactIn(ApiModel):
    key: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$",
        max_length=120,
        description="e.g. 'sponsor.monthly_income_aed', 'has_document.passport'",
    )
    value: JsonValue
    label: str | None = Field(default=None, max_length=200)
    source: FactSource = FactSource.USER_STATED

    @field_validator("key")
    @classmethod
    def _not_sensitive(cls, key: str) -> str:
        if any(part in SENSITIVE_ATTRIBUTES for part in key.split(".")):
            raise ValueError(
                "sensitive attributes are never used to assess government requirements"
            )
        return key


class ExplainRequest(ApiModel):
    requirement: str = Field(
        min_length=2,
        max_length=300,
        description="A governance node key or id, or plain words ('sponsor my wife')",
    )
    facts: list[UserFactIn] = Field(default_factory=list, max_length=200)
    subject: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*$",
        max_length=40,
        description="Who the service is for when it is not the user, e.g. 'spouse': checks on "
        "the beneficiary's documents then read '<subject>.documents.*' facts",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="Retrieved passages to add")


class CheckStatus(StrEnum):
    MET = "met"
    UNMET = "unmet"
    UNKNOWN = "unknown"  # ADAPT lacks the facts to decide
    INFORMATIONAL = "informational"  # checked by the authority while processing; never blocks


class CheckKind(StrEnum):
    ELIGIBILITY = "eligibility"
    REQUIREMENT = "requirement"
    DOCUMENT = "document"
    DEPENDENCY = "dependency"
    APPOINTMENT = "appointment"


class NextAction(StrEnum):
    REVIEW_ELIGIBILITY = "review_eligibility"  # a rule is not met: talk to the authority
    PROVIDE_INFORMATION = "provide_information"  # ADAPT needs facts from the user
    COMPLETE_PREREQUISITE = "complete_prerequisite"  # another service comes first
    OBTAIN_DOCUMENT = "obtain_document"  # get or upload a required document
    BOOK_APPOINTMENT = "book_appointment"  # on the official channel
    APPLY = "apply"  # everything known is in place: apply on the official channel


class ResolvedRequirement(ApiModel):
    node_id: UUID
    key: str
    label: str
    entity_type: str
    method: Literal["key", "search"]
    confidence: float = Field(ge=0, le=1)
    alternatives: list[NodeMatch] = Field(default_factory=list)


class FactUse(ApiModel):
    key: str
    label: str | None = None
    value: JsonValue | None = None
    provided: bool = Field(description="False when the check needed this fact but it is missing")


class JourneyTaskRef(ApiModel):
    key: str = Field(description="Governance service key; journey steps use the same key")
    title: str
    node_id: UUID


class ReasoningInput(ApiModel):
    """One check and everything it was decided from: the unit the UI highlights."""

    id: str
    kind: CheckKind
    status: CheckStatus
    statement: str = Field(description="What was checked, in plain words")
    explanation: str = Field(description="Why the status is what it is")
    node_id: UUID = Field(description="The governance requirement/document/rule/service")
    node_key: str
    edge_id: UUID | None = Field(default=None, description="The relationship that was checked")
    facts: list[FactUse] = Field(default_factory=list)
    condition: dict[str, Any] | None = Field(default=None, description="Machine rule, if any")
    evidence_ids: list[str] = Field(default_factory=list)
    task: JourneyTaskRef | None = Field(default=None, description="The journey task it affects")


class HighlightLink(ApiModel):
    """One segment of a user fact -> requirement -> evidence -> journey task chain."""

    source: str = Field(description="'fact:<key>' | 'node:<uuid>' | 'evidence:<id>'")
    target: str = Field(description="'node:<uuid>' | 'evidence:<id>' | 'task:<key>'")
    relation: Literal["checked_against", "evidenced_by", "supports"]
    check_id: str
    status: CheckStatus


class PortalRef(ApiModel):
    node_id: UUID
    label: str
    url: str | None = None


class NextStep(ApiModel):
    action: NextAction
    title: str
    detail: str
    node_id: UUID
    task: JourneyTaskRef | None = None
    portal: PortalRef | None = None
    official_url: str | None = None
    requires_uae_pass: bool = False
    handoff: bool = Field(
        default=True,
        description="ADAPT prepares; the user completes the step on the official channel",
    )
    missing_facts: list[str] = Field(default_factory=list)
    check_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ExplainResponse(ApiModel):
    requirement: ResolvedRequirement
    overall: Literal["ready", "needs_information", "blocked", "not_eligible"]
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    evidence: list[Evidence]
    retrieved_evidence_ids: list[str] = Field(
        description="Passages found by retrieval (the rest are linked from the graph)"
    )
    reasoning_inputs: list[ReasoningInput]
    links: list[HighlightLink]
    next_step: NextStep
    facts_used: list[FactUse]
    generated_at: datetime
