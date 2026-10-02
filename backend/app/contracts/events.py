"""Streamed agent events — structured JSON, one object per event.

Every event is a flat JSON object discriminated by `event`, sharing the envelope
`run_id`, `seq` (gap-free, strictly increasing per run, starting at 1), `ts` and `node`
(the emitting agent node, or null). Example:

    {"event": "node_started", "run_id": "…", "seq": 3, "ts": "…",
     "node": "document_analysis", "label": "Analyzing your documents"}

Transports (same objects everywhere):
* `GET /api/agents/{run_id}/events` — JSON replay, or Server-Sent Events when the client
  sends `Accept: text/event-stream` (`id: <seq>`, `data: <event JSON>`; resume with
  `Last-Event-ID` or `?after=`);
* `WS /api/agents/{run_id}/stream` — one text frame per event (`?after=` to resume).

Events carry pointers and short labels, never private payloads (document contents,
extracted identity fields, prompts). Clients fetch artifacts from their own endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, RootModel

from app.contracts.common import ApiModel
from app.domain.enums import ArtifactType, EvidenceKind, RunKind, RunStatus


class _EventBase(ApiModel):
    run_id: UUID
    seq: int = Field(ge=1)
    ts: datetime
    node: str | None = Field(
        default=None, description="Agent node that emitted the event (see the agent topology)"
    )


# --- run lifecycle ------------------------------------------------------------------------


class RunStartedEvent(_EventBase):
    event: Literal["run_started"]
    kind: RunKind
    agent: str | None = None


class RunStatusEvent(_EventBase):
    """Non-terminal status changes, e.g. running -> awaiting_input -> running."""

    event: Literal["run_status"]
    status: RunStatus
    reason: str | None = None


class RunCompletedEvent(_EventBase):
    event: Literal["run_completed"]
    summary: str | None = None
    journey_id: UUID | None = None


class RunFailedEvent(_EventBase):
    event: Literal["run_failed"]
    code: str
    message: str
    retryable: bool = False


class RunCancelledEvent(_EventBase):
    event: Literal["run_cancelled"]
    reason: str | None = None


# --- nodes -------------------------------------------------------------------------------------


class NodeStartedEvent(_EventBase):
    event: Literal["node_started"]
    label: str
    attempt: int = 1


class NodeProgressEvent(_EventBase):
    event: Literal["node_progress"]
    message: str
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    detail: dict[str, Any] | None = None


class NodeCompletedEvent(_EventBase):
    event: Literal["node_completed"]
    label: str | None = None
    summary: str | None = None
    duration_ms: int


class ErrorEvent(_EventBase):
    """A non-terminal error (e.g. a node failed). `run_failed` follows if the run stops."""

    event: Literal["error"]
    code: str
    message: str
    retryable: bool = False


# --- tools & evidence ----------------------------------------------------------------------------


class ToolCalledEvent(_EventBase):
    event: Literal["tool_called"]
    tool: str
    call_id: str
    summary: str | None = Field(default=None, description="Short, non-sensitive description")


class ToolResultEvent(_EventBase):
    event: Literal["tool_result"]
    tool: str
    call_id: str
    ok: bool
    summary: str | None = None


class EvidenceFoundEvent(_EventBase):
    event: Literal["evidence_found"]
    title: str
    source_url: str
    authority: str | None = None
    evidence_kind: EvidenceKind
    chunk_id: UUID | None = None
    quote: str | None = Field(default=None, max_length=600)
    score: float | None = None


# --- outputs & human-in-the-loop ----------------------------------------------------------


class DocumentGeneratedEvent(_EventBase):
    event: Literal["document_generated"]
    document_id: UUID
    kind: str
    title: str


class ActionPreparedEvent(_EventBase):
    event: Literal["action_prepared"]
    action_id: UUID
    action_type: str
    title: str
    status: str
    requires_approval: bool


class ApprovalRequiredEvent(_EventBase):
    event: Literal["approval_required"]
    approval_id: UUID | str = Field(description="Approval row id, or the agent's review id")
    action_id: UUID | None = None
    title: str
    summary: str
    gate: str = Field(
        default="action_approval",
        description="action_approval | document_correction | submission_confirmation",
    )
    item_count: int = 1


class ApprovalResolvedEvent(_EventBase):
    event: Literal["approval_resolved"]
    approval_id: UUID | str
    decision: Literal["approved", "rejected", "expired"]
    gate: str | None = None


class QuestionOption(ApiModel):
    value: str
    label: str


class QuestionAskedEvent(_EventBase):
    event: Literal["question_asked"]
    question_id: str
    prompt: str
    field: str | None = Field(default=None, description="Profile/graph attribute the answer fills")
    options: list[QuestionOption] | None = None
    reason: str | None = Field(default=None, description="Why ADAPT needs this")


class MessageDeltaEvent(_EventBase):
    event: Literal["message_delta"]
    message_id: str
    text: str


class ArtifactCreatedEvent(_EventBase):
    event: Literal["artifact_created"]
    artifact_type: ArtifactType
    artifact_id: str
    title: str | None = None


class ArtifactUpdatedEvent(_EventBase):
    event: Literal["artifact_updated"]
    artifact_type: ArtifactType
    artifact_id: str
    title: str | None = None


# --- research (payloads defined with the research workstream) ----------------------------


class ResearchStartedEvent(_EventBase):
    event: Literal["research_started"]
    job_id: UUID
    categories: list[str]
    mode: Literal["live", "snapshot"]


class ResearchSourceFoundEvent(_EventBase):
    event: Literal["research_source_found"]
    job_id: UUID
    category: str
    result_id: UUID
    citation_id: UUID | None = None
    title: str
    url: str
    source_domain: str
    source_label: Literal["official", "organization", "community", "general_web"]


class ResearchCategoryCompletedEvent(_EventBase):
    event: Literal["research_category_completed"]
    job_id: UUID
    category: str
    status: Literal["completed", "failed", "skipped"]
    result_count: int
    reason: str | None = None


class ResearchCompletedEvent(_EventBase):
    event: Literal["research_completed"]
    job_id: UUID
    result_count: int
    categories_completed: list[str]
    categories_failed: list[str]
    message: str


class ResearchFailedEvent(_EventBase):
    event: Literal["research_failed"]
    job_id: UUID | None = None
    code: str
    message: str
    retryable: bool = False


AgentEventUnion = Annotated[
    RunStartedEvent
    | RunStatusEvent
    | RunCompletedEvent
    | RunFailedEvent
    | RunCancelledEvent
    | NodeStartedEvent
    | NodeProgressEvent
    | NodeCompletedEvent
    | ErrorEvent
    | ToolCalledEvent
    | ToolResultEvent
    | EvidenceFoundEvent
    | DocumentGeneratedEvent
    | ActionPreparedEvent
    | ApprovalRequiredEvent
    | ApprovalResolvedEvent
    | QuestionAskedEvent
    | MessageDeltaEvent
    | ArtifactCreatedEvent
    | ArtifactUpdatedEvent
    | ResearchStartedEvent
    | ResearchSourceFoundEvent
    | ResearchCategoryCompletedEvent
    | ResearchCompletedEvent
    | ResearchFailedEvent,
    Field(discriminator="event"),
]


class AgentEvent(RootModel[AgentEventUnion]):
    """Any agent event (discriminated by `event`)."""


AgentEventType = Literal[
    "run_started",
    "run_status",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "node_started",
    "node_progress",
    "node_completed",
    "error",
    "tool_called",
    "tool_result",
    "evidence_found",
    "document_generated",
    "action_prepared",
    "approval_required",
    "approval_resolved",
    "question_asked",
    "message_delta",
    "artifact_created",
    "artifact_updated",
    "research_started",
    "research_source_found",
    "research_category_completed",
    "research_completed",
    "research_failed",
]

TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"run_completed", "run_failed", "run_cancelled"})


def parse_event(payload: dict[str, Any]) -> AgentEventUnion:
    return AgentEvent.model_validate(payload).root
