"""Structured agent events.

Agents and workers emit events through an `EventSink`. The production sink
(`RunEventEmitter`) assigns a gap-free per-run sequence number, persists the event to
`agent_events` (RLS-scoped to the run's owner), keeps `agent_runs.status` in step with
lifecycle events, and then wakes up live listeners (SSE and WebSocket).

Every helper validates its payload against the `AgentEvent` contract before anything is
persisted, so a malformed event can never reach a client.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import update

from app.contracts.events import AgentEvent, AgentEventType, AgentEventUnion
from app.db.models import AgentEvent as AgentEventRow
from app.db.models import AgentRun
from app.db.session import Database
from app.domain.enums import ArtifactType, EvidenceKind, RunKind, RunStatus
from app.domain.principal import Principal
from app.events.notifier import EventNotifier, NullNotifier

logger = logging.getLogger(__name__)


def build_event(
    *,
    run_id: UUID,
    seq: int,
    event: AgentEventType,
    data: BaseModel | dict[str, Any] | None = None,
    node: str | None = None,
    ts: datetime | None = None,
) -> AgentEventUnion:
    fields = data.model_dump(mode="json") if isinstance(data, BaseModel) else dict(data or {})
    return AgentEvent.model_validate(
        {
            **fields,
            "event": event,
            "run_id": run_id,
            "seq": seq,
            "ts": ts or datetime.now(UTC),
            "node": node,
        }
    ).root


class EventSink(ABC):
    """Typed helpers over a single `emit` primitive. Implementations decide persistence."""

    run_id: UUID

    @abstractmethod
    async def emit(
        self,
        event: AgentEventType,
        data: BaseModel | dict[str, Any] | None = None,
        *,
        node: str | None = None,
    ) -> AgentEventUnion: ...

    # --- run lifecycle ---------------------------------------------------------------------
    async def run_started(self, kind: RunKind, agent: str | None = None) -> AgentEventUnion:
        return await self.emit("run_started", {"kind": kind, "agent": agent})

    async def run_status(self, status: RunStatus, reason: str | None = None) -> AgentEventUnion:
        return await self.emit("run_status", {"status": status, "reason": reason})

    async def run_completed(
        self, summary: str | None = None, journey_id: UUID | None = None
    ) -> AgentEventUnion:
        return await self.emit("run_completed", {"summary": summary, "journey_id": journey_id})

    async def run_failed(self, code: str, message: str, retryable: bool = False) -> AgentEventUnion:
        return await self.emit(
            "run_failed", {"code": code, "message": message, "retryable": retryable}
        )

    async def run_cancelled(self, reason: str | None = None) -> AgentEventUnion:
        return await self.emit("run_cancelled", {"reason": reason})

    # --- nodes -------------------------------------------------------------------------------
    async def node_started(self, node: str, label: str, attempt: int = 1) -> AgentEventUnion:
        return await self.emit("node_started", {"label": label, "attempt": attempt}, node=node)

    async def node_progress(
        self,
        node: str,
        message: str,
        progress: float | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "node_progress",
            {"message": message, "progress": progress, "detail": detail},
            node=node,
        )

    async def node_completed(
        self, node: str, duration_ms: int, summary: str | None = None, label: str | None = None
    ) -> AgentEventUnion:
        return await self.emit(
            "node_completed",
            {"duration_ms": duration_ms, "summary": summary, "label": label},
            node=node,
        )

    async def node_failed(
        self, node: str, code: str, message: str, retryable: bool = False
    ) -> AgentEventUnion:
        return await self.error(code, message, retryable=retryable, node=node)

    async def error(
        self, code: str, message: str, *, retryable: bool = False, node: str | None = None
    ) -> AgentEventUnion:
        return await self.emit(
            "error", {"code": code, "message": message, "retryable": retryable}, node=node
        )

    # --- tools & evidence ---------------------------------------------------------------------
    async def tool_called(
        self, tool: str, *, call_id: str, summary: str | None = None, node: str | None = None
    ) -> AgentEventUnion:
        return await self.emit(
            "tool_called", {"tool": tool, "call_id": call_id, "summary": summary}, node=node
        )

    async def tool_result(
        self,
        tool: str,
        *,
        call_id: str,
        ok: bool,
        summary: str | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "tool_result",
            {"tool": tool, "call_id": call_id, "ok": ok, "summary": summary},
            node=node,
        )

    async def evidence_found(
        self,
        *,
        title: str,
        source_url: str,
        evidence_kind: EvidenceKind,
        authority: str | None = None,
        chunk_id: UUID | None = None,
        quote: str | None = None,
        score: float | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "evidence_found",
            {
                "title": title,
                "source_url": source_url,
                "evidence_kind": evidence_kind,
                "authority": authority,
                "chunk_id": chunk_id,
                "quote": quote[:600] if quote else None,
                "score": score,
            },
            node=node,
        )

    # --- outputs & human-in-the-loop -------------------------------------------------------------
    async def document_generated(
        self, *, document_id: UUID, kind: str, title: str, node: str | None = None
    ) -> AgentEventUnion:
        return await self.emit(
            "document_generated",
            {"document_id": document_id, "kind": kind, "title": title},
            node=node,
        )

    async def action_prepared(
        self,
        *,
        action_id: UUID,
        action_type: str,
        title: str,
        status: str,
        requires_approval: bool,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "action_prepared",
            {
                "action_id": action_id,
                "action_type": action_type,
                "title": title,
                "status": status,
                "requires_approval": requires_approval,
            },
            node=node,
        )

    async def approval_required(
        self,
        *,
        approval_id: UUID | str,
        title: str,
        summary: str,
        gate: str = "action_approval",
        item_count: int = 1,
        action_id: UUID | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "approval_required",
            {
                "approval_id": approval_id,
                "action_id": action_id,
                "title": title,
                "summary": summary,
                "gate": gate,
                "item_count": item_count,
            },
            node=node,
        )

    async def approval_resolved(
        self,
        *,
        approval_id: UUID | str,
        decision: str,
        gate: str | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "approval_resolved",
            {"approval_id": approval_id, "decision": decision, "gate": gate},
            node=node,
        )

    async def question_asked(
        self,
        question_id: str,
        prompt: str,
        *,
        field: str | None = None,
        options: list[dict[str, str]] | None = None,
        reason: str | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "question_asked",
            {
                "question_id": question_id,
                "prompt": prompt,
                "field": field,
                "options": options,
                "reason": reason,
            },
            node=node,
        )

    async def message_delta(
        self, message_id: str, text: str, *, node: str | None = None
    ) -> AgentEventUnion:
        return await self.emit("message_delta", {"message_id": message_id, "text": text}, node=node)

    async def artifact(
        self,
        artifact_type: ArtifactType,
        artifact_id: str,
        *,
        title: str | None = None,
        node: str | None = None,
        created: bool = True,
    ) -> AgentEventUnion:
        return await self.emit(
            "artifact_created" if created else "artifact_updated",
            {"artifact_type": artifact_type, "artifact_id": artifact_id, "title": title},
            node=node,
        )

    # --- research ---------------------------------------------------------------------------------
    async def research_started(
        self, *, job_id: UUID, categories: Sequence[str], mode: str, node: str | None = None
    ) -> AgentEventUnion:
        return await self.emit(
            "research_started",
            {"job_id": job_id, "categories": list(categories), "mode": mode},
            node=node,
        )

    async def research_source_found(
        self,
        *,
        job_id: UUID,
        category: str,
        result_id: UUID,
        title: str,
        url: str,
        source_domain: str,
        source_label: str,
        citation_id: UUID | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "research_source_found",
            {
                "job_id": job_id,
                "category": category,
                "result_id": result_id,
                "citation_id": citation_id,
                "title": title,
                "url": url,
                "source_domain": source_domain,
                "source_label": source_label,
            },
            node=node,
        )

    async def research_category_completed(
        self,
        *,
        job_id: UUID,
        category: str,
        status: str,
        result_count: int,
        reason: str | None = None,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "research_category_completed",
            {
                "job_id": job_id,
                "category": category,
                "status": status,
                "result_count": result_count,
                "reason": reason,
            },
            node=node,
        )

    async def research_completed(
        self,
        *,
        job_id: UUID,
        result_count: int,
        categories_completed: Sequence[str],
        categories_failed: Sequence[str],
        message: str,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "research_completed",
            {
                "job_id": job_id,
                "result_count": result_count,
                "categories_completed": list(categories_completed),
                "categories_failed": list(categories_failed),
                "message": message,
            },
            node=node,
        )

    async def research_failed(
        self,
        *,
        code: str,
        message: str,
        job_id: UUID | None = None,
        retryable: bool = False,
        node: str | None = None,
    ) -> AgentEventUnion:
        return await self.emit(
            "research_failed",
            {"job_id": job_id, "code": code, "message": message, "retryable": retryable},
            node=node,
        )


class MemoryEventSink(EventSink):
    """In-memory sink for tests and local experiments."""

    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        self.events: list[AgentEventUnion] = []

    async def emit(
        self,
        event: AgentEventType,
        data: BaseModel | dict[str, Any] | None = None,
        *,
        node: str | None = None,
    ) -> AgentEventUnion:
        built = build_event(
            run_id=self.run_id, seq=len(self.events) + 1, event=event, data=data, node=node
        )
        self.events.append(built)
        return built

    @property
    def types(self) -> list[str]:
        return [e.event for e in self.events]


_LIFECYCLE_STATUS: dict[str, RunStatus] = {
    "run_started": RunStatus.RUNNING,
    "run_completed": RunStatus.SUCCEEDED,
    "run_failed": RunStatus.FAILED,
    "run_cancelled": RunStatus.CANCELLED,
}


class RunEventEmitter(EventSink):
    """Persists events for one run on behalf of its owner, then notifies listeners."""

    def __init__(
        self,
        db: Database,
        principal: Principal,
        run_id: UUID,
        notifier: EventNotifier | None = None,
    ) -> None:
        self._db = db
        self._principal = principal
        self.run_id = run_id
        self._notifier = notifier or NullNotifier()

    async def emit(
        self,
        event: AgentEventType,
        data: BaseModel | dict[str, Any] | None = None,
        *,
        node: str | None = None,
    ) -> AgentEventUnion:
        # Validate before touching the database (seq is a placeholder here).
        fields = data.model_dump(mode="json") if isinstance(data, BaseModel) else dict(data or {})
        build_event(run_id=self.run_id, seq=1, event=event, data=fields, node=node)

        async with self._db.user_session(self._principal) as session:
            values: dict[str, Any] = {"event_seq": AgentRun.event_seq + 1}
            status = _LIFECYCLE_STATUS.get(event)
            if event == "run_status":
                status = RunStatus(fields["status"])
            if status is not None:
                values["status"] = status
                now = datetime.now(UTC)
                if event == "run_started":
                    values["started_at"] = now
                if status.is_terminal:
                    values["finished_at"] = now
            if event == "run_failed":
                values["error"] = {k: fields.get(k) for k in ("code", "message", "retryable")}

            seq = (
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == self.run_id)
                    .values(**values)
                    .returning(AgentRun.event_seq)
                )
            ).scalar_one()
            built = build_event(run_id=self.run_id, seq=seq, event=event, data=fields, node=node)
            session.add(
                AgentEventRow(
                    run_id=self.run_id,
                    seq=seq,
                    event=event,
                    node=node,
                    payload=built.model_dump(mode="json"),
                    tenant_id=self._principal.tenant_id,
                    user_id=self._principal.user_id,
                )
            )
            await session.commit()
        await self._notifier.notify(self.run_id, seq)
        return built
