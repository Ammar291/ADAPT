"""Agent runs: start, status, event log (JSON or SSE) and WebSocket stream."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import ContainerDep, PrincipalDep, UserSession, websocket_principal
from app.contracts.events import AgentEvent
from app.contracts.runs import AgentEventList, AgentInfo, RunOut, RunStarted, StartAgentRunRequest
from app.core.container import Container
from app.core.errors import AppError, NotFound
from app.domain.enums import RunKind, RunStatus
from app.events.stream import HEARTBEAT, follow_run_events, load_run_events, stream_run_events
from app.repositories.runs import get_run, list_runs
from app.services import runs as run_service
from app.services.agent_registry import list_agents
from app.services.presenters import run_out

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agents"])

# WebSocket close codes (4000-4999 are application-defined).
WS_UNAUTHORIZED = 4401
WS_NOT_FOUND = 4404


def _started(container: Container, run_id: UUID, run: RunOut) -> RunStarted:
    prefix = container.settings.api_prefix
    return RunStarted(
        run=run,
        events_url=f"{prefix}/agents/{run_id}/events",
        stream_url=f"{prefix}/agents/{run_id}/stream",
    )


@router.get("/agents", response_model=list[AgentInfo], summary="Agents you can start")
async def agents_catalogue() -> list[AgentInfo]:
    return [
        AgentInfo(
            name=spec.name,
            kind=spec.kind,
            description=spec.description,
            input_schema=spec.input_model.model_json_schema(),
        )
        for spec in list_agents()
    ]


@router.post(
    "/agents/run",
    response_model=RunStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an agent run",
    description="Validates `input` against the agent's schema (see GET /api/agents), creates "
    "the run and queues it. Follow progress on `events_url` or `stream_url`.",
)
async def start_agent_run(
    body: StartAgentRunRequest, principal: PrincipalDep, container: ContainerDep
) -> RunStarted:
    run = await run_service.start_agent(container, principal, body.agent, body.input)
    return _started(container, run.id, run_out(run))


@router.get(
    "/agents/runs",
    response_model=list[RunOut],
    summary="Your agent runs, newest first",
    description="Every run the server holds for you (journeys, what-ifs, research, document "
    "reading), on any device. `active=true` keeps queued, running and paused runs.",
)
async def list_agent_runs(
    session: UserSession,
    kind: Annotated[list[RunKind] | None, Query()] = None,
    status: Annotated[list[RunStatus] | None, Query()] = None,
    active: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunOut]:
    statuses = status or []
    if active:
        statuses = [s for s in (statuses or list(RunStatus)) if not s.is_terminal]
        if not statuses:
            return []
    runs = await list_runs(session, kinds=kind, statuses=statuses, limit=limit)
    return [run_out(r) for r in runs]


@router.get("/agents/{run_id}", response_model=RunOut, summary="Status of an agent run")
async def read_run(run_id: UUID, session: UserSession) -> RunOut:
    run = await get_run(session, run_id)
    if run is None:
        raise NotFound("Run not found", code="run_not_found")
    return run_out(run)


@router.post(
    "/agents/{run_id}/cancel",
    response_model=RunOut,
    summary="Stop a run that is waiting for you",
    description="Only a paused run (`awaiting_input`) can be cancelled; its open approvals "
    "expire and nothing is executed. 409 `run_not_cancellable` otherwise.",
)
async def cancel_agent_run(
    run_id: UUID, principal: PrincipalDep, container: ContainerDep
) -> RunOut:
    return run_out(await run_service.cancel_run(container, principal, run_id))


@router.get(
    "/agents/{run_id}/events",
    response_model=AgentEventList,
    summary="Agent events (JSON replay, or live Server-Sent Events)",
    description="Returns the run's events after `after` as JSON. With `Accept: "
    "text/event-stream` the same events stream live as SSE (`id: <seq>`, `data: <event>`); "
    "reconnect with `Last-Event-ID` (or `?after=`) to resume without gaps. The stream ends "
    "after `run_completed`, `run_failed` or `run_cancelled`.",
    responses={
        200: {
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/AgentEvent"}}
            }
        }
    },
)
async def run_events(
    run_id: UUID,
    request: Request,
    principal: PrincipalDep,
    session: UserSession,
    container: ContainerDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse | JSONResponse | AgentEventList:
    if await get_run(session, run_id) is None:
        raise NotFound("Run not found", code="run_not_found")
    await session.close()  # don't hold a pooled connection for the life of a stream

    after_seq = after or 0
    if last_event_id and last_event_id.isdigit():
        after_seq = max(after_seq, int(last_event_id))

    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            stream_run_events(
                container.db, container.notifier, principal, run_id, after_seq=after_seq
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    rows, run_status = await load_run_events(container.db, principal, run_id, after_seq, limit=2000)
    assert run_status is not None
    return AgentEventList(
        run_id=run_id,
        status=run_status,
        last_seq=rows[-1].seq if rows else after_seq,
        events=[AgentEvent.model_validate(row.payload) for row in rows],
    )


@router.websocket("/agents/{run_id}/stream")
async def run_stream(
    websocket: WebSocket,
    run_id: UUID,
    after: Annotated[int, Query(ge=0)] = 0,
) -> None:
    """One JSON text frame per event (same objects as the SSE stream); `{"event": "ping"}`
    keep-alives while idle. Closes with 1000 after a terminal event, 4401 when the session
    is missing or the origin is not allowed, 4404 when the run is not yours or unknown."""
    try:
        principal = websocket_principal(websocket)
    except AppError:
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    container: Container = websocket.app.state.container
    _, run_status = await load_run_events(container.db, principal, run_id, after_seq=0, limit=1)
    if run_status is None:
        await websocket.close(code=WS_NOT_FOUND)
        return

    await websocket.accept()
    stream = follow_run_events(container.db, container.notifier, principal, run_id, after_seq=after)
    try:
        async for item in stream:
            if item is HEARTBEAT:
                await websocket.send_json({"event": "ping"})
            else:
                await websocket.send_json(item)
        await websocket.close(code=1000)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        logger.exception("run_stream_failed", extra={"run_id": str(run_id)})
        await websocket.close(code=1011)
    finally:
        await stream.aclose()
