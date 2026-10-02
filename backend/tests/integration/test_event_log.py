"""Agent event log and its transports (JSON replay, SSE, WebSocket) against real Postgres."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core import compat
from app.db.session import Database
from app.domain.enums import EvidenceKind, RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.events.notifier import NullNotifier
from app.events.stream import stream_run_events
from app.main import create_app
from app.repositories.runs import create_run, get_run
from tests.integration.conftest import auth, make_settings


async def _new_run(db: Database, principal: Principal):  # type: ignore[no-untyped-def]
    async with db.user_session(principal) as session:
        run = await create_run(session, principal, RunKind.DIAGNOSTIC)
        await session.commit()
        return run


async def _finished_run(db: Database, principal: Principal):  # type: ignore[no-untyped-def]
    run = await _new_run(db, principal)
    events = RunEventEmitter(db, principal, run.id)
    await events.run_started(RunKind.DIAGNOSTIC, agent="diagnostic")
    await events.node_started("document_analysis", "Analyzing your documents")
    await events.tool_called("ocr", call_id="c1", node="document_analysis")
    await events.tool_result("ocr", call_id="c1", ok=True, node="document_analysis")
    await events.evidence_found(
        title="ICP", source_url="https://icp.gov.ae", evidence_kind=EvidenceKind.OFFICIAL_GUIDANCE
    )
    await events.node_completed("document_analysis", 12, "done")
    await events.run_completed("All done")
    return run


async def test_sequence_and_status_follow_lifecycle(app_db: Database, alice: Principal) -> None:
    run = await _new_run(app_db, alice)
    emitter = RunEventEmitter(app_db, alice, run.id)
    await emitter.run_started(RunKind.DIAGNOSTIC)
    await asyncio.gather(*(emitter.node_progress("n", f"step {i}") for i in range(10)))
    await emitter.run_status(RunStatus.AWAITING_INPUT, "approval")
    async with app_db.user_session(alice) as session:
        paused = await get_run(session, run.id)
    assert paused is not None and paused.status is RunStatus.AWAITING_INPUT
    await emitter.run_completed("done")

    async with app_db.user_session(alice) as session:
        finished = await get_run(session, run.id)
    assert finished is not None
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.started_at is not None and finished.finished_at is not None
    assert finished.event_seq == 13


async def test_events_are_flat_structured_json(
    app_db: Database, api: httpx.AsyncClient, alice: Principal
) -> None:
    run = await _finished_run(app_db, alice)
    body = (await api.get(f"/api/agents/{run.id}/events", headers=auth(alice))).json()
    assert body["status"] == "succeeded" and body["last_seq"] == 7
    first_node = body["events"][1]
    assert first_node == {
        "event": "node_started",
        "run_id": str(run.id),
        "seq": 2,
        "ts": first_node["ts"],
        "node": "document_analysis",
        "label": "Analyzing your documents",
        "attempt": 1,
    }
    assert [e["event"] for e in body["events"]] == [
        "run_started",
        "node_started",
        "tool_called",
        "tool_result",
        "evidence_found",
        "node_completed",
        "run_completed",
    ]
    after = (await api.get(f"/api/agents/{run.id}/events?after=5", headers=auth(alice))).json()
    assert [e["seq"] for e in after["events"]] == [6, 7]


async def test_sse_replays_and_terminates(
    app_db: Database, api: httpx.AsyncClient, alice: Principal
) -> None:
    run = await _finished_run(app_db, alice)
    headers = {**auth(alice), "Accept": "text/event-stream", "Last-Event-ID": "4"}
    response = await api.get(f"/api/agents/{run.id}/events", headers=headers)
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [f for f in response.text.split("\n\n") if f.startswith("id: ")]
    assert [int(f.split("\n")[0][4:]) for f in frames] == [5, 6, 7]
    assert json.loads(frames[-1].split("data: ", 1)[1])["event"] == "run_completed"


async def test_stream_delivers_live_events(app_db: Database, alice: Principal) -> None:
    run = await _new_run(app_db, alice)
    emitter = RunEventEmitter(app_db, alice, run.id)
    received: list[str] = []

    async def consume() -> None:
        async for frame in stream_run_events(
            app_db, NullNotifier(), alice, run.id, poll_seconds=0.2
        ):
            if frame.startswith("id: "):
                received.append(json.loads(frame.split("data: ", 1)[1])["event"])

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await emitter.run_started(RunKind.DIAGNOSTIC)
    await emitter.error("boom", "Something failed", node="n")
    await emitter.run_failed("boom", "Something failed")
    await asyncio.wait_for(consumer, timeout=10)
    assert received == ["run_started", "error", "run_failed"]


async def test_stream_is_empty_for_other_users(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    run = await _new_run(app_db, alice)
    await RunEventEmitter(app_db, alice, run.id).run_started(RunKind.DIAGNOSTIC)
    frames = [f async for f in stream_run_events(app_db, NullNotifier(), bob, run.id)]
    assert not any(f.startswith("id: ") for f in frames)


async def test_start_agent_run_validates_and_enqueues(
    api: httpx.AsyncClient,
    container,
    alice: Principal,  # type: ignore[no-untyped-def]
) -> None:
    catalogue = (await api.get("/api/agents", headers=auth(alice))).json()
    assert "diagnostic" in {a["name"] for a in catalogue}
    started = await api.post(
        "/api/agents/run", json={"agent": "diagnostic", "input": {}}, headers=auth(alice)
    )
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["run"]["status"] == "queued" and body["run"]["agent"] == "diagnostic"
    assert body["stream_url"].endswith("/stream")
    job, kwargs = container.queue.jobs[-1]
    assert job == "run_diagnostic" and kwargs["user_id"] == str(alice.user_id)

    bad = await api.post(
        "/api/agents/run", json={"agent": "diagnostic", "input": {"x": 1}}, headers=auth(alice)
    )
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_agent_input"
    unknown = await api.post("/api/agents/run", json={"agent": "nope"}, headers=auth(alice))
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_agent"


def _websocket_frames(settings_dir: Path, run_id: str, headers: dict[str, str]) -> list[dict]:  # type: ignore[type-arg]
    """Drive the WebSocket in its own thread and event loop (TestClient), with its own pool."""
    result: list[dict] = []  # type: ignore[type-arg]
    error: list[BaseException] = []

    def run() -> None:
        app = create_app(make_settings(settings_dir))
        try:
            options = {"loop_factory": compat.new_event_loop}
            path = f"/api/agents/{run_id}/stream"
            with (
                TestClient(app, backend_options=options) as client,
                client.websocket_connect(path, headers=headers) as ws,
            ):
                while True:
                    frame = ws.receive_json()
                    result.append(frame)
                    if frame.get("event") in {"run_completed", "run_failed", "run_cancelled"}:
                        break
        except BaseException as exc:  # surfaced to the test below
            error.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=30)
    if error:
        raise error[0]
    return result


async def test_websocket_streams_the_same_events(
    app_db: Database, alice: Principal, bob: Principal, tmp_path: Path
) -> None:
    run = await _finished_run(app_db, alice)
    frames = await asyncio.to_thread(_websocket_frames, tmp_path, str(run.id), auth(alice))
    assert [f["seq"] for f in frames] == list(range(1, 8))
    assert frames[1]["event"] == "node_started" and frames[1]["label"] == "Analyzing your documents"

    with pytest.raises(WebSocketDisconnect) as closed:
        await asyncio.to_thread(_websocket_frames, tmp_path, str(run.id), auth(bob))
    assert closed.value.code == 4404
    with pytest.raises(WebSocketDisconnect) as foreign:
        await asyncio.to_thread(
            _websocket_frames,
            tmp_path,
            str(run.id),
            {**auth(alice), "Origin": "https://evil.example"},
        )
    assert foreign.value.code == 4401
