"""API contracts of the journey-agent routes (exported to TypeScript via OpenAPI).

Shared read shapes (JourneyOut, ActionOut, RunOut, ...) come from `app.contracts`; these
add what only the journey agent produces: gates, risks, evidence and simulation results.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.agents.journey.review import (
    ActionApprovalReview,
    DocumentCorrectionReview,
    SubmissionConfirmationReview,
)
from app.contracts.actions import ActionApprovalOut, ActionOut
from app.contracts.common import ApiModel
from app.contracts.generated_documents import GeneratedDocumentOut
from app.contracts.journey import JourneyOut
from app.contracts.runs import RunOut
from app.domain.enums import ActionKind, Channel

# --- requests -------------------------------------------------------------------------------


class StartJourneyRequest(ApiModel):
    prompt: str = Field(
        min_length=3, max_length=4000, description="The move in the user's own words"
    )
    language: str = Field(default="en", max_length=35)
    channel: Channel = Channel.TEXT
    document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    deterministic: bool = Field(
        default=False,
        description="Use ADAPT's rule-based request parser and drafting templates, and the "
        "curated research source list, even when an LLM key is configured (repeatable demos)",
    )
    journey_id: UUID | None = Field(default=None, description="Set by the API; leave empty")


class ScenarioChangeIn(ApiModel):
    key: str = Field(max_length=160, description="See GET /journey/{id}/what-if/variables")
    value: Any


class WhatIfRequest(ApiModel):
    changes: list[ScenarioChangeIn] = Field(min_length=1, max_length=10)


class WhatIfAgentInput(ApiModel):
    """Input of the `what_if` agent for POST /api/agents/run."""

    base_journey_id: UUID
    changes: list[ScenarioChangeIn] = Field(min_length=1, max_length=10)


class PrepareActionRequest(ApiModel):
    """Prepare one step of a journey as an action awaiting approval. No side effects."""

    journey_id: UUID
    task_key: str | None = Field(default=None, max_length=160)
    journey_node_id: UUID | None = None
    service_key: str | None = Field(default=None, max_length=200)
    type: ActionKind | None = Field(default=None, description="Override the step's action type")


class NodeAnswer(ApiModel):
    answer: str = Field(min_length=1, max_length=500, description="e.g. '25000', 'yes', 'adgm'")
    key: str | None = Field(
        default=None,
        max_length=160,
        description="Which fact this answers (see the node's details.open_questions); "
        "defaults to the most decisive open question",
    )


class ActionDecisionBody(ApiModel):
    note: str | None = Field(default=None, max_length=1000)


# --- responses --------------------------------------------------------------------------------


class JourneyStarted(ApiModel):
    journey_id: UUID
    run: RunOut
    events_url: str
    stream_url: str


class WhatIfStarted(ApiModel):
    base_journey_id: UUID
    scenario_journey_id: UUID
    run: RunOut
    events_url: str
    stream_url: str


class ScenarioVariableOut(ApiModel):
    key: str = Field(description="A fact key; `*` marks a family such as documents.*")
    label: str
    type: Literal["boolean", "enum", "number", "integer", "date"]
    options: list[str] = Field(default_factory=list)
    current: Any = Field(default=None, description="The value in the journey, if any")


class RiskOut(ApiModel):
    id: str
    kind: Literal[
        "missing_user_document",
        "missing_information",
        "missing_source_evidence",
        "timeline_dependency",
        "incompatible_task_ordering",
        "external_login_required",
        "eligibility_gap",
    ]
    severity: Literal["info", "warning", "blocking"]
    title: str
    detail: str
    resolution: str | None = None
    task_keys: list[str]
    fact_keys: list[str]
    fact_ids: list[str] = Field(default_factory=list)
    governance_keys: list[str]
    evidence_ids: list[str]


class ConsiderationOut(ApiModel):
    """Something the person may not have considered: a cited consequence of the rules.

    Not a risk (nothing is wrong) and not a step (nothing new to do)."""

    id: str
    title: str
    detail: str
    area: str = "daily_life"
    task_keys: list[str] = Field(default_factory=list)
    governance_keys: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    fact_keys: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)

    @classmethod
    def stored(cls, raw: Any) -> ConsiderationOut | None:
        """A stored consideration, or None for rows of an older shape (journeys saved before
        considerations had their own rules stored their risks in this column)."""
        if not isinstance(raw, dict) or "severity" in raw or not raw.get("title"):
            return None
        return cls.model_validate(
            {
                **raw,
                "area": raw.get("area") or raw.get("category") or "daily_life",
                "detail": raw.get("detail") or "",
            }
        )


class RequirementOut(ApiModel):
    id: str
    task_key: str
    node_key: str
    node_type: str
    label: str
    subject: str
    status: Literal["satisfied", "produced_by_task", "missing", "unknown", "checked_by_authority"]
    satisfied_by: str | None = None
    evidence_ids: list[str]


class EligibilityOut(ApiModel):
    rule_key: str
    service_key: str
    subject: str
    status: Literal["met", "unmet", "unknown"]
    explanation: str
    missing_facts: list[str]
    verify_on_official_page: bool
    evidence_ids: list[str]


class EvidenceOut(ApiModel):
    id: str
    kind: Literal["official_passage", "official_reference", "user_document", "user_statement"]
    trust: str = Field(description="EvidenceKind trust tier")
    title: str
    source_url: str | None = None
    authority: str | None = None
    quote: str | None = None
    governance_key: str | None = None
    document_id: str | None = None
    retrieved_at: str | None = None
    claim: str | None = None
    section_or_page: str | None = None
    effective_date: str | None = None
    excerpt: Literal["quote", "paraphrase"] | None = None
    source_family: str | None = None
    freshness: Literal["current", "stale"] | None = None
    chunk_id: str | None = None


class ScenarioChangeOut(ApiModel):
    key: str
    label: str
    from_: Any = Field(default=None, alias="from")
    to: Any = None


class ChangedNodeOut(ApiModel):
    node: str
    label: str
    changed_keys: list[str]


class TaskBriefOut(ApiModel):
    key: str
    title: str
    area: str


class DependencyChangeOut(ApiModel):
    source: str = Field(description="The dependent step")
    target: str = Field(description="What it waits for")
    relation: str
    change: Literal["added", "removed"]


class RiskChangeOut(ApiModel):
    id: str
    kind: str
    severity: str
    title: str
    change: Literal["added", "removed", "changed"]


class SimulationResultOut(ApiModel):
    scenario_journey_id: UUID | None = None
    base_journey_id: UUID | None = None
    changes: list[ScenarioChangeOut]
    rerun_nodes: list[str]
    changed_nodes: list[ChangedNodeOut]
    added_tasks: list[TaskBriefOut]
    removed_tasks: list[TaskBriefOut]
    changed_dependencies: list[DependencyChangeOut]
    changed_risks: list[RiskChangeOut]
    summary: str


PendingReviewOut = ActionApprovalReview | DocumentCorrectionReview | SubmissionConfirmationReview


class JourneyDetailOut(JourneyOut):
    """A JourneyOut plus everything the journey agent produced for it."""

    considerations: list[ConsiderationOut] = Field(default_factory=list)  # type: ignore[assignment]
    risks: list[RiskOut] = Field(default_factory=list)
    requirements: list[RequirementOut] = Field(default_factory=list)
    eligibility: list[EligibilityOut] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)
    actions: list[ActionOut] = Field(default_factory=list)
    generated_documents: list[GeneratedDocumentOut] = Field(default_factory=list)
    latest_run: RunOut | None = None
    pending_review: PendingReviewOut | None = Field(default=None, discriminator="gate")
    simulation_result: SimulationResultOut | None = None


class PreparedActionOut(ApiModel):
    action: ActionOut
    approval: ActionApprovalOut


class ActionDecisionOut(ApiModel):
    action: ActionOut
    message: str
    run_resumed: bool = Field(
        description="True when this was the last open decision of a paused run"
    )


class ReviewAccepted(ApiModel):
    run: RunOut
    resumed: bool
    remaining: int = Field(description="Decisions still open in this review (action approvals)")
