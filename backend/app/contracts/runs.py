"""Agent runs: starting them, reading their status, and replaying their event log."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.contracts.common import ApiModel, ProblemDetail
from app.contracts.events import AgentEvent
from app.domain.enums import RunKind, RunStatus


class RunOut(ApiModel):
    id: UUID
    agent: str
    kind: RunKind
    status: RunStatus
    journey_id: UUID | None = None
    last_event_seq: int
    pending_review: dict[str, Any] | None = Field(
        default=None, description="The open human-in-the-loop gate while awaiting input"
    )
    error: ProblemDetail | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunStarted(ApiModel):
    run: RunOut
    events_url: str = Field(description="JSON replay, or SSE with Accept: text/event-stream")
    stream_url: str = Field(description="WebSocket stream of the same events")


class StartAgentRunRequest(ApiModel):
    agent: str = Field(min_length=1, max_length=80, description="A name from GET /api/agents")
    input: dict[str, Any] = Field(default_factory=dict)


class AgentInfo(ApiModel):
    name: str
    kind: RunKind
    description: str
    input_schema: dict[str, Any]


class AgentEventList(ApiModel):
    run_id: UUID
    status: RunStatus
    last_seq: int
    events: list[AgentEvent]
