"""Cross-workstream integration on real PostgreSQL: the seams the demo journey crosses.

* the review of a paused run reports what has already been decided (the approval rows);
* concurrent last decisions on one review resume the run exactly once;
* runs are listed by the server (any device), privately;
* a paused run can be cancelled, and nothing it prepared can then be approved;
* generated drafts can be edited and restored, never once approved;
* a document is read once, and a journey started while it's being read waits for it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.adapters.ocr import ReadRequest, ReadResult
from app.agents.journey import integrations
from app.agents.journey import service as journey_service
from app.agents.journey.integrations import PlatformDocuments
from app.core.container import Container
from app.db.models import Action, ActionApproval
from app.documents import specimens
from app.documents.service import DocumentIntelligence
from app.domain.enums import ActionStatus, ApprovalStatus
from app.domain.principal import Principal
from tests.integration.conftest import auth
from tests.integration.test_document_pipeline import upload
from tests.integration.test_journey_agent import run_job, start_and_pause, take_job

pytestmark = pytest.mark.integration


async def review_of(api: httpx.AsyncClient, who: Principal, run_id: str) -> dict[str, Any]:
    r = await api.get(f"/api/agents/{run_id}/review", headers=auth(who))
    assert r.status_code == 200, r.text
    return r.json()


async def test_review_reports_decisions_already_made(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    _, run_id = await start_and_pause(api, container, alice)
    review = await review_of(api, alice, run_id)
    assert review["gate"] == "action_approval" and len(review["items"]) >= 2
    assert {i["approval_status"] for i in review["items"]} == {"pending"}

    first = review["items"][0]
    r = await api.post(f"/api/actions/{first['action_id']}/approve", json={}, headers=auth(alice))
    assert r.status_code == 200 and r.json()["run_resumed"] is False, r.text

    again = await review_of(api, alice, run_id)
    status = {i["action_id"]: i for i in again["items"]}
    assert status[first["action_id"]]["approval_status"] == "approved"
    assert status[first["action_id"]]["decided_at"]
    assert all(
        i["approval_status"] == "pending" and i["decided_at"] is None
        for i in again["items"]
        if i["action_id"] != first["action_id"]
    )


async def test_concurrent_last_decisions_resume_the_run_once(
    api: httpx.AsyncClient,
    container: Container,
    alice: Principal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, run_id = await start_and_pause(api, container, alice)
    items = (await review_of(api, alice, run_id))["items"][:2]
    for extra in (await review_of(api, alice, run_id))["items"][2:]:
        await api.post(f"/api/actions/{extra['action_id']}/approve", json={}, headers=auth(alice))

    # Force the race: both decisions count the open approvals inside their transactions
    # before either commits, so each still sees the other's approval as pending.
    barrier, calls = asyncio.Barrier(2), {"n": 0}
    count = journey_service._open_approvals

    async def overlapping_count(session: Any, review_id: str) -> int:
        result = await count(session, review_id)
        calls["n"] += 1
        if calls["n"] <= 2:
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return result

    monkeypatch.setattr(journey_service, "_open_approvals", overlapping_count)
    responses = await asyncio.gather(
        *(
            api.post(f"/api/actions/{i['action_id']}/approve", json={}, headers=auth(alice))
            for i in items
        )
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert sum(r.json()["run_resumed"] is True for r in responses) == 1
    run = (await api.get(f"/api/agents/{run_id}", headers=auth(alice))).json()
    assert run["status"] == "queued" and run["pending_review"] is None
    take_job(container, "resume_journey")
    assert not any(f == "resume_journey" for f, _ in container.queue.jobs)  # type: ignore[attr-defined]


async def test_runs_are_listed_by_the_server_and_private(
    api: httpx.AsyncClient, container: Container, alice: Principal, bob: Principal
) -> None:
    _, run_id = await start_and_pause(api, container, alice)

    listed = (await api.get("/api/agents/runs", headers=auth(alice))).json()
    assert listed[0]["id"] == run_id and listed[0]["status"] == "awaiting_input"
    active = (await api.get("/api/agents/runs?active=true", headers=auth(alice))).json()
    assert run_id in {r["id"] for r in active}
    research = (await api.get("/api/agents/runs?kind=research", headers=auth(alice))).json()
    assert run_id not in {r["id"] for r in research}
    done = (await api.get("/api/agents/runs?status=succeeded", headers=auth(alice))).json()
    assert run_id not in {r["id"] for r in done}
    contradiction = "/api/agents/runs?active=true&status=succeeded"
    assert (await api.get(contradiction, headers=auth(alice))).json() == []
    assert (await api.get("/api/agents/runs", headers=auth(bob))).json() == []


async def test_cancelling_a_paused_run_expires_its_approvals(
    api: httpx.AsyncClient, container: Container, alice: Principal, bob: Principal
) -> None:
    journey_id, run_id = await start_and_pause(api, container, alice)
    items = (await review_of(api, alice, run_id))["items"]
    waiting = {i["task_key"] for i in items}

    assert (await api.post(f"/api/agents/{run_id}/cancel", headers=auth(bob))).status_code == 404
    r = await api.post(f"/api/agents/{run_id}/cancel", headers=auth(alice))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["pending_review"] is None

    assert (await api.get(f"/api/agents/{run_id}/review", headers=auth(alice))).status_code == 404
    late = await api.post(
        f"/api/actions/{items[0]['action_id']}/approve", json={}, headers=auth(alice)
    )
    assert late.status_code == 409 and late.json()["code"] == "approval_not_pending"
    again = await api.post(f"/api/agents/{run_id}/cancel", headers=auth(alice))
    assert again.status_code == 409 and again.json()["code"] == "run_not_cancellable"

    async with container.db.user_session(alice) as session:
        ids = [UUID(i["action_id"]) for i in items]
        actions = (await session.execute(select(Action).where(Action.id.in_(ids)))).scalars()
        assert {a.status for a in actions} == {ActionStatus.DRAFT}
        approvals = (
            await session.execute(select(ActionApproval).where(ActionApproval.action_id.in_(ids)))
        ).scalars()
        assert {a.status for a in approvals} == {ApprovalStatus.EXPIRED}

    # The journey no longer shows those steps waiting for a decision nobody can make.
    detail = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()
    steps = {n["key"]: n["status"] for n in detail["nodes"]}
    assert waiting <= steps.keys()
    assert all(steps[key] != "awaiting_approval" for key in waiting)

    events = (await api.get(f"/api/agents/{run_id}/events", headers=auth(alice))).json()
    assert events["events"][-1]["event"] == "run_cancelled"
    assert not any(f == "resume_journey" for f, _ in container.queue.jobs)  # type: ignore[attr-defined]


async def test_generated_drafts_can_be_edited_and_restored_until_approved(
    api: httpx.AsyncClient, container: Container, alice: Principal, bob: Principal
) -> None:
    await start_and_pause(api, container, alice)
    drafts = (await api.get("/api/documents/generated", headers=auth(alice))).json()
    assert drafts, "the journey drafts at least one document before pausing"
    doc_id = drafts[0]["id"]
    path = f"/api/documents/generated/{doc_id}"

    edited = await api.patch(path, json={"body_markdown": "# Edited"}, headers=auth(alice))
    assert edited.status_code == 200, edited.text
    assert edited.json()["body_markdown"] == "# Edited" and edited.json()["status"] == "draft"
    assert (
        await api.patch(path, json={"body_markdown": "x"}, headers=auth(bob))
    ).status_code == 404

    await api.post(f"{path}/discard", headers=auth(alice))
    restored = await api.patch(path, json={"body_markdown": "# Back"}, headers=auth(alice))
    assert restored.json()["status"] == "draft"

    assert (await api.post(f"{path}/approve", headers=auth(alice))).status_code == 200
    locked = await api.patch(path, json={"body_markdown": "# Later"}, headers=auth(alice))
    assert locked.status_code == 409
    assert locked.json()["code"] == "generated_document_already_approved"


class GatedReader:
    """Wraps the real reader: counts reads, and holds each read until released."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.reads, self.release = inner, 0, asyncio.Event()
        self.started = asyncio.Event()

    async def read(self, request: ReadRequest) -> ReadResult:
        self.reads += 1
        self.started.set()
        await self.release.wait()
        return await self.inner.read(request)


async def test_a_document_is_read_once_and_a_journey_waits_for_it(
    api: httpx.AsyncClient,
    container: Container,
    alice: Principal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integrations, "DOCUMENT_READ_POLL_SECONDS", 0.05)
    reader = GatedReader(container.adapters.ocr)
    monkeypatch.setattr(container.adapters, "ocr", reader)
    created = await upload(api, alice, specimens.passport(), kind="passport")
    document_id = UUID(created["id"])

    # The upload's own job starts reading, then the journey asks for the same document.
    upload_job = asyncio.create_task(
        DocumentIntelligence(container.db, alice, container.adapters).analyze(document_id)
    )
    await asyncio.wait_for(reader.started.wait(), timeout=10)
    journey_read = asyncio.create_task(
        PlatformDocuments(container.db, alice, container.adapters, events=None).analyze(
            str(document_id)
        )
    )
    await asyncio.sleep(0.3)
    assert not journey_read.done(), "the journey must wait instead of planning without it"

    reader.release.set()
    await asyncio.wait_for(upload_job, timeout=20)
    analysis = await asyncio.wait_for(journey_read, timeout=20)
    assert reader.reads == 1
    assert analysis.status == "extracted"
    assert analysis.facts, "the journey gets the facts the document contributed"


async def test_answering_a_gate_is_announced_on_the_stream(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    """A UI following the run must see each gate close, not only each gate open."""
    _, run_id = await start_and_pause(api, container, alice)
    for item in (await review_of(api, alice, run_id))["items"]:
        await api.post(f"/api/actions/{item['action_id']}/approve", json={}, headers=auth(alice))
    assert (
        await run_job(container, "resume_journey", take_job(container, "resume_journey"))
        == "interrupted"
    )
    review = await review_of(api, alice, run_id)
    assert review["gate"] == "submission_confirmation"
    body = {
        "gate": "submission_confirmation",
        "review_id": review["review_id"],
        "confirmations": [
            {"action_id": i["action_id"], "outcome": "not_yet"} for i in review["items"]
        ],
    }
    r = await api.post(f"/api/agents/{run_id}/resume", json=body, headers=auth(alice))
    assert r.status_code == 202, r.text

    events = (await api.get(f"/api/agents/{run_id}/events", headers=auth(alice))).json()["events"]
    opened = [e for e in events if e["event"] == "approval_required"]
    closed = {e["approval_id"] for e in events if e["event"] == "approval_resolved"}
    assert opened and {e["approval_id"] for e in opened} <= closed
