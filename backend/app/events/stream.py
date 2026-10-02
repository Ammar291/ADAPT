"""Live delivery of one run's events: Server-Sent Events and WebSocket.

Both transports share `follow_run_events`, which replays from Postgres after a sequence
number and then follows new events. It subscribes to wake-ups *before* reading, so an
event written between the read and the subscribe cannot be missed; every wake-up re-reads
from Postgres and deduplicates by `seq`. Delivery ends after a terminal event.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.contracts.events import TERMINAL_EVENT_TYPES
from app.db.models import AgentEvent, AgentRun
from app.db.session import Database
from app.domain.enums import RunStatus
from app.domain.principal import Principal
from app.events.notifier import EventNotifier

SSE_RETRY_MS = 3000
HEARTBEAT = object()  # yielded by `follow_run_events` when a keep-alive is due


def format_sse(seq: int, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"id: {seq}\ndata: {data}\n\n"


async def load_run_events(
    db: Database, principal: Principal, run_id: UUID, after_seq: int = 0, limit: int = 500
) -> tuple[list[AgentEvent], RunStatus | None]:
    """Events after `after_seq` (oldest first) and the run status. RLS hides other users'
    runs entirely: for them the status is None and the list is empty."""
    async with db.user_session(principal) as session:
        status = (
            await session.execute(select(AgentRun.status).where(AgentRun.id == run_id))
        ).scalar_one_or_none()
        rows = (
            await session.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id, AgentEvent.seq > after_seq)
                .order_by(AgentEvent.seq)
                .limit(limit)
            )
        ).scalars()
        return list(rows), status


async def follow_run_events(
    db: Database,
    notifier: EventNotifier,
    principal: Principal,
    run_id: UUID,
    *,
    after_seq: int = 0,
    heartbeat_seconds: float = 15.0,
    poll_seconds: float = 5.0,
) -> AsyncIterator[dict[str, Any] | object]:
    """Yield event payloads (dicts) in order, and `HEARTBEAT` when the stream is idle."""
    last_seq = after_seq
    last_sent = time.monotonic()
    async with notifier.subscribe(run_id) as subscription:
        while True:
            rows, status = await load_run_events(db, principal, run_id, last_seq)
            for row in rows:
                yield row.payload
                last_seq = row.seq
                last_sent = time.monotonic()
                if row.event in TERMINAL_EVENT_TYPES:
                    return
            if not rows and (status is None or status.is_terminal):
                return
            if rows:
                continue  # there may be more than one page
            await subscription.wait(poll_seconds)
            if time.monotonic() - last_sent >= heartbeat_seconds:
                yield HEARTBEAT
                last_sent = time.monotonic()


async def stream_run_events(
    db: Database,
    notifier: EventNotifier,
    principal: Principal,
    run_id: UUID,
    *,
    after_seq: int = 0,
    heartbeat_seconds: float = 15.0,
    poll_seconds: float = 5.0,
) -> AsyncIterator[str]:
    """Server-Sent Events frames (`id: <seq>` / `data: <event JSON>`)."""
    yield f"retry: {SSE_RETRY_MS}\n\n"
    async for item in follow_run_events(
        db,
        notifier,
        principal,
        run_id,
        after_seq=after_seq,
        heartbeat_seconds=heartbeat_seconds,
        poll_seconds=poll_seconds,
    ):
        if item is HEARTBEAT:
            yield ": keep-alive\n\n"
        else:
            assert isinstance(item, dict)
            yield format_sse(int(item["seq"]), item)
