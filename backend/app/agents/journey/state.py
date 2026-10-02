"""Typed LangGraph state of the personalised settlement journey.

State is checkpointed to Postgres after every node, so it stays JSON-only: TypedDicts of
plain values, never ORM objects or live clients. Private artefacts that have their own
RLS-protected tables (documents, generated documents, actions, approvals) are persisted
there; the state keeps their ids plus the fields the next nodes reason over.

Reducers decide how a node's update combines with the current value:

* no reducer (last value wins) — the single owning node always writes the complete
  value (e.g. `tasks` is rebuilt by the planner and enriched by dependency analysis);
* `merge_facts` — facts merge by key, so a node can only add or restate its own facts;
* `merge_by_id` — lists of records merge by `id`, so a node that updates one action
  cannot silently drop or rewrite the others;
* `operator.add` — append-only journals (`events`, `sim_trace`).

Which node may write which key is declared by each node's typed output (see `spec.py`)
and enforced at runtime.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import JsonValue

# --- reducers ---------------------------------------------------------------------------


def merge_facts(
    current: dict[str, UserFact] | None, update: dict[str, UserFact] | None
) -> dict[str, UserFact]:
    return {**(current or {}), **(update or {})}


def merge_by_id[T: Any](current: list[T] | None, update: list[T] | None) -> list[T]:
    """Upsert records by their `id` (or `review_id`), keeping first-seen order."""
    merged: dict[str, T] = {}
    for record in [*(current or []), *(update or [])]:
        key = record.get("id") or record.get("review_id")  # type: ignore[attr-defined]
        merged[key] = {**merged[key], **record} if key in merged else record  # type: ignore[assignment,dict-item]
    return list(merged.values())


# --- request & facts ----------------------------------------------------------------------


class UserRequest(TypedDict):
    text: str
    language: str
    channel: Literal["text", "voice"]


FactOrigin = Literal[
    "user_stated",  # said in this request
    "document_extracted",  # read from an uploaded document
    "user_graph",  # already in the user's private graph
    "scenario",  # a what-if override (simulations only)
    "assumed",  # a default ADAPT had to assume; always surfaced as a risk
]


class UserFact(TypedDict):
    key: str  # canonical fact key, e.g. "household.move_with_spouse", "spouse.documents.passport"
    value: JsonValue
    source: FactOrigin
    source_ref: str | None  # e.g. "request", "document:<uuid>", "fact:<uuid>"
    confidence: float
    confirmed: bool
    fact_ids: list[str]  # personalization fact ids this value came from (for explanations)


# --- governance context ---------------------------------------------------------------------


class GovNode(TypedDict):
    key: str
    type: str  # governance entity type: service, document, requirement, dependency, ...
    label: str
    summary: str | None
    official_url: str | None
    properties: dict[str, Any]
    provenance: dict[str, Any] | None


class GovEdge(TypedDict):
    source: str  # governance key
    relation: str
    target: str  # governance key
    properties: dict[str, Any]


class GovernanceContext(TypedDict):
    root_services: list[str]  # services selected directly from the user's goals
    nodes: dict[str, GovNode]  # the reachable governance subgraph, by key
    edges: list[GovEdge]
    notes: list[str]  # why services were (not) selected


# --- evidence ------------------------------------------------------------------------------

EvidenceRecordKind = Literal[
    "official_passage",  # a quoted passage retrieved from an official source
    "official_reference",  # a governance node's citation of an official page (no quote)
    "user_document",  # a value read from the user's document
    "user_statement",  # something the user told ADAPT
]


class EvidenceRecord(TypedDict):
    id: str  # deterministic, so re-runs and simulations produce the same ids
    kind: EvidenceRecordKind
    trust: str  # EvidenceKind: authoritative_requirement | official_guidance | ...
    title: str
    source_url: str | None
    authority: str | None
    quote: str | None
    governance_key: str | None
    document_id: str | None
    tool_call_id: str | None
    retrieved_at: str | None
    claim: NotRequired[str | None]
    section_or_page: NotRequired[str | None]
    effective_date: NotRequired[str | None]
    excerpt: NotRequired[str | None]
    source_family: NotRequired[str | None]
    freshness: NotRequired[str | None]
    chunk_id: NotRequired[str | None]


# --- analysis & plan -------------------------------------------------------------------------


class EligibilityResult(TypedDict):
    rule_key: str
    service_key: str
    subject: str
    status: Literal["met", "unmet", "unknown"]
    explanation: str
    missing_facts: list[str]
    fact_keys: list[str]
    evidence_ids: list[str]
    verify_on_official_page: bool


class Requirement(TypedDict):
    id: str  # "<task_key>-><governance key>"
    task_key: str
    node_key: str
    node_type: str  # document | requirement
    label: str
    subject: str
    status: Literal["satisfied", "produced_by_task", "missing", "unknown", "checked_by_authority"]
    satisfied_by: str | None  # fact key or task key
    fact_keys: list[str]
    evidence_ids: list[str]


class TaskLink(TypedDict):
    """A prerequisite found by the planner; dependency analysis turns links into edges."""

    depends_on: str  # prerequisite task key
    kind: str  # DependencyKind
    via: str  # governance key the link was derived from
    any_of: str | None


class Task(TypedDict):
    key: str  # governance key, suffixed "@<subject>" for household members
    node_key: str
    subject: str
    kind: str  # TaskKind
    title: str
    summary: str
    area: str  # StepCategory
    authority: str | None
    official_url: str | None
    portal: str | None
    requires_login: bool  # the official channel needs the user's own login (UAE PASS)
    action_type: str | None  # how ADAPT can help: government_portal | appointment | ...
    status: str  # TaskStatus
    order: int
    level: int
    links: list[TaskLink]
    depends_on: list[str]
    requirement_ids: list[str]
    evidence_ids: list[str]
    fact_keys: list[str]
    fact_ids: list[str]
    why: str  # why this task is in the plan


class Dependency(TypedDict):
    id: str
    task: str  # the dependent task key
    depends_on: str  # the prerequisite task key
    kind: str  # DependencyKind
    via: str  # the governance key the edge was derived from
    any_of: str | None  # OR-group key when this is one alternative
    evidence_ids: list[str]


class Risk(TypedDict):
    id: str
    kind: str  # RiskKind
    severity: str  # RiskSeverity
    title: str
    detail: str
    resolution: str | None
    task_keys: list[str]
    fact_keys: list[str]
    governance_keys: list[str]
    evidence_ids: list[str]
    fact_ids: list[str]


class GeneratedDocumentRef(TypedDict):
    id: str
    kind: str
    title: str
    task_key: str | None
    persisted: bool  # false for what-if previews
    evidence_ids: list[str]


class ActionRecord(TypedDict):
    id: str
    type: str  # ActionKind
    status: str  # ActionStatus
    reversible: bool
    requires_human_approval: bool
    requires_user_authentication: bool
    official_url: str | None
    payload: dict[str, Any]
    evidence: list[str]  # evidence ids
    title: str
    summary: str
    consequences: list[str]
    task_key: str
    service_key: str
    adapter: str
    is_simulated: bool
    simulation_label: str | None
    approval_id: str | None
    external_reference: str | None
    confirmation_source: str | None
    response_metadata: dict[str, Any]


class ApprovalRequest(TypedDict):
    review_id: str
    gate: str  # ReviewGate
    status: Literal["pending", "resolved"]
    item_ids: list[str]
    outcome: dict[str, str]  # item id -> decision / outcome


JournalType = Literal[
    "node_start",
    "node_complete",
    "tool_call",
    "tool_result",
    "approval_required",
    "approval_resolved",
]


class JournalEvent(TypedDict):
    """Compact audit trail kept in state (the full event log lives in the events table)."""

    type: JournalType
    node: str
    ts: str
    detail: str
    ref: str | None  # tool call id, review id, ...


# --- what-if ---------------------------------------------------------------------------------


class ScenarioChange(TypedDict):
    key: str
    label: str
    previous: JsonValue
    value: JsonValue


class Scenario(TypedDict):
    base_journey_id: str | None
    base_run_id: str | None
    changes: list[ScenarioChange]
    changed_facts: list[str]
    baseline: dict[str, Any]  # the base journey's values of every key a re-run may change


class SimTrace(TypedDict):
    node: str
    changed_keys: list[str]


# --- the state ---------------------------------------------------------------------------


class JourneyState(TypedDict, total=False):
    # identity & input
    user_id: str
    journey_id: str
    run_id: str
    mode: Literal["journey", "simulation"]
    request: UserRequest
    document_ids: list[str]

    # understanding
    user_facts: Annotated[dict[str, UserFact], merge_facts]
    governance_context: GovernanceContext
    eligibility: list[EligibilityResult]
    evidence: Annotated[list[EvidenceRecord], merge_by_id]

    # plan
    requirements: list[Requirement]
    tasks: list[Task]
    dependencies: list[Dependency]
    risks: list[Risk]

    # outputs & human in the loop
    generated_documents: list[GeneratedDocumentRef]
    actions: Annotated[list[ActionRecord], merge_by_id]
    approval_requests: Annotated[list[ApprovalRequest], merge_by_id]
    research_job_ids: list[str]
    events: Annotated[list[JournalEvent], operator.add]
    final_summary: str

    # what-if only
    scenario: NotRequired[Scenario]
    sim_trace: Annotated[list[SimTrace], operator.add]
    simulation: dict[str, Any]


# Reducers by key, so simulations can compute a node's merged output exactly as LangGraph
# will apply it (see simulation.py).
STATE_REDUCERS: dict[str, Callable[[Any, Any], Any]] = {
    "user_facts": merge_facts,
    "evidence": merge_by_id,
    "actions": merge_by_id,
    "approval_requests": merge_by_id,
    "events": operator.add,
    "sim_trace": operator.add,
}
