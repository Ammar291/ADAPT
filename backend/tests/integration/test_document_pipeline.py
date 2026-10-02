"""Document pipeline end to end against real Postgres: upload → worker → twin → review.

Uses real specimen PDFs (text layer + passport MRZ) read by the local reader, a recording
queue instead of Redis, and the actual worker job function.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.core.container import Container
from app.db.models import AgentEvent
from app.db.models.user_data import ExtractedFact, UserDocument
from app.documents import specimens
from app.documents.service import DocumentIntelligence
from app.documents.tasks import process_document
from app.domain.principal import Principal
from app.events.notifier import NullNotifier
from app.personalization import analytics
from app.personalization.facts import explain, planning_facts
from tests.integration.conftest import auth

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
PII = ("Arjun", "ARJUN", "Mehta", "MEHTA", "Priya", "1990-04-12", "Z0000000", "32000", "32,000")


async def upload(
    api: httpx.AsyncClient,
    who: Principal,
    content: bytes,
    *,
    kind: str | None = None,
    filename: str = "scan.pdf",
    **form: str,
) -> dict[str, Any]:
    data = {"kind": kind, **form} if kind else dict(form)
    response = await api.post(
        "/api/documents/upload",
        files={"file": (filename, content, "application/octet-stream")},
        data=data,
        headers=auth(who),
    )
    assert response.status_code == 202, response.text
    return response.json()


async def drain(container: Container) -> list[str]:
    """Run queued document jobs the way the worker would."""
    ctx = {
        "deps": SimpleNamespace(
            db=container.db, notifier=NullNotifier(), adapters=container.adapters
        )
    }
    outcomes = []
    queue = container.queue
    while queue.jobs:  # type: ignore[attr-defined]
        function, kwargs = queue.jobs.pop(0)  # type: ignore[attr-defined]
        assert function == "process_document"
        outcomes.append(await process_document(ctx, **kwargs))
    return outcomes


async def detail(api: httpx.AsyncClient, who: Principal, document_id: str) -> dict[str, Any]:
    response = await api.get(f"/api/documents/{document_id}", headers=auth(who))
    assert response.status_code == 200, response.text
    return response.json()


def field(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return next(f for f in doc["fields"] if f["name"] == name)


async def test_passport_upload_extracts_minimum_verified_facts(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(api, alice, specimens.passport(), kind="passport")
    assert created["status"] == "uploaded"
    assert created["events_url"].endswith("/events")
    assert await drain(container) == ["extracted"]

    doc = await detail(api, alice, created["id"])
    assert doc["status"] == "extracted" and doc["open_review_tasks"] == 0
    assert doc["mrz_verified"] is True
    assert doc["extraction_method"] == "local:pdf-text"
    dob = field(doc, "date_of_birth")
    assert dob["value"] == "1990-04-12" and dob["confidence"] >= 0.98 and not dob["needs_review"]
    # Every fact carries value, confidence, source document and extraction method.
    for fact in doc["facts"]:
        assert fact["source"] == "document_extracted"
        assert fact["source_document_id"] == created["id"]
        assert fact["extraction_method"] and fact["confidence"] >= 0.85
        assert fact["status"] == "accepted" and not fact["confirmed_by_user"]
    assert {f["attribute"] for f in doc["facts"]} == {
        "full_name",
        "date_of_birth",
        "country",
        "issuing_country",
        "expiry_date",
    }  # fmt: skip — minimum fields; no passport number anywhere

    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    types = {n["type"] for n in graph["nodes"]}
    assert {"person", "nationality", "passport"} <= types
    passport = next(n for n in graph["nodes"] if n["type"] == "passport")
    assert passport["label"] == "Passport · India" and passport["relation"] == "has_document"
    # The passport links to public knowledge by reference, not by copy.
    assert [g["key"] for g in graph["linked_governance_nodes"]] == ["document.passport"]
    assert "Z0000000" not in str(graph)


async def test_low_confidence_creates_review_tasks_and_correction_flow(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    await upload(api, alice, specimens.passport(), kind="passport")
    created = await upload(
        api, alice, specimens.marriage_certificate(), kind="marriage_certificate"
    )
    await drain(container)

    doc = await detail(api, alice, created["id"])
    assert doc["status"] == "needs_review"
    [task] = doc["review_tasks"]
    assert task["kind"] == "low_confidence" and task["fact"]["attribute"] == "attested"
    assert task["fact"]["status"] == "needs_review" and task["fact"]["value"] is None
    spouse = field(doc, "spouse_2_name")
    assert spouse["value"] == "Priya Mehta" and not spouse["needs_review"]

    # Proposals are never projected for planning; accepted spouse facts are.
    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    assert any(n["type"] == "spouse" and n["label"] == "Priya Mehta" for n in graph["nodes"])
    assert graph["open_review_tasks"] == 1

    # Correct the unreadable attestation: the task resolves and the document is confirmed.
    fact_id = task["fact"]["id"]
    fixed = await api.patch(
        f"/api/graph/user/facts/{fact_id}", json={"value": "no"}, headers=auth(alice)
    )
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    assert body["status"] == "accepted" and body["value"] is False
    assert body["confirmed_by_user"] and body["corrected"] and body["confidence"] == 1.0
    assert body["origin"].startswith("Corrected by you (originally read from your marriage")
    doc = await detail(api, alice, created["id"])
    assert doc["status"] == "confirmed" and doc["review_tasks"] == []

    # Confirming a value the person agrees with keeps its origin and marks it confirmed.
    name_id = field(doc, "spouse_2_name")["fact_id"]
    confirmed = await api.patch(
        f"/api/graph/user/facts/{name_id}", json={"confirm": True}, headers=auth(alice)
    )
    assert confirmed.json()["confirmed_by_user"] and not confirmed.json()["corrected"]

    # Rejecting a fact removes it; entities without facts disappear.
    married_on = field(doc, "date_of_marriage")["fact_id"]
    assert (
        await api.delete(f"/api/graph/user/facts/{married_on}", headers=auth(alice))
    ).status_code == 204
    facts = (await detail(api, alice, created["id"]))["facts"]
    assert all(f["attribute"] != "married_on" for f in facts)


async def test_attesting_links_the_certificate_to_governance(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(
        api, alice, specimens.marriage_certificate(attestation="Yes"), kind="marriage_certificate"
    )
    await drain(container)
    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    assert "document.marriage_certificate_attested" in {
        g["key"] for g in graph["linked_governance_nodes"]
    }
    facts = await planning_facts_for(container, alice)
    assert facts["documents.marriage_certificate_attested"].value is True
    assert created["kind"] == "marriage_certificate"


async def planning_facts_for(container: Container, who: Principal) -> dict[str, Any]:
    async with container.db.user_session(who) as session:
        return {p.key: p for p in await planning_facts(session, who)}


async def test_image_without_a_vision_provider_needs_review_and_invents_nothing(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(api, alice, PNG, kind="passport", filename="photo.png")
    assert await drain(container) == ["needs_review"]
    doc = await detail(api, alice, created["id"])
    assert doc["status"] == "needs_review"
    assert doc["facts"] == [] and doc["fields"] == []
    [task] = doc["review_tasks"]
    assert task["kind"] == "extraction_failed" and task["fact"] is None
    # The person can dismiss it once they've added the details themselves.
    dismissed = await api.post(f"/api/review-tasks/{task['id']}/dismiss", headers=auth(alice))
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    assert (await detail(api, alice, created["id"]))["status"] == "confirmed"


async def test_kind_mismatch_is_flagged(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(api, alice, specimens.marriage_certificate(), kind="passport")
    await drain(container)
    doc = await detail(api, alice, created["id"])
    assert "kind_mismatch" in {t["kind"] for t in doc["review_tasks"]}
    # Reading it again as the right kind replaces the earlier result.
    again = await api.post(
        f"/api/documents/{created['id']}/process",
        json={"kind": "marriage_certificate"},
        headers=auth(alice),
    )
    assert again.status_code == 202
    await drain(container)
    doc = await detail(api, alice, created["id"])
    assert doc["kind"] == "marriage_certificate"
    assert "kind_mismatch" not in {t["kind"] for t in doc["review_tasks"]}


async def test_conflicting_values_never_silently_replace_the_twin(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    stated = await api.post(
        "/api/graph/user/facts",
        json={"entity_type": "person", "attribute": "date_of_birth", "value": "1990-04-13"},
        headers=auth(alice),
    )
    assert stated.status_code == 201
    created = await upload(api, alice, specimens.passport(), kind="passport")
    await drain(container)
    doc = await detail(api, alice, created["id"])
    task = next(t for t in doc["review_tasks"] if t["fact"]["attribute"] == "date_of_birth")
    assert task["kind"] == "conflict"
    async with container.db.user_session(alice) as session:
        facts = await planning_facts(session, alice, ["person.age"])
    assert facts[0].source == "user_stated"  # the person's statement still stands


async def test_upload_validation(api: httpx.AsyncClient, alice: Principal) -> None:
    fake_pdf = await api.post(
        "/api/documents/upload",
        files={"file": ("x.pdf", b"<html>not a pdf</html>", "application/pdf")},
        headers=auth(alice),
    )
    assert fake_pdf.status_code == 415 and fake_pdf.json()["code"] == "unsupported_media"
    empty = await api.post(
        "/api/documents/upload",
        files={"file": ("x.pdf", b"", "application/pdf")},
        headers=auth(alice),
    )
    assert empty.status_code == 400
    child = await api.post(
        "/api/documents/upload",
        files={"file": ("p.pdf", specimens.passport(), "application/pdf")},
        data={"subject": "child"},
        headers=auth(alice),
    )
    assert child.json()["code"] == "subject_required"


async def test_bytes_are_encrypted_and_served_only_with_a_signed_link(
    api: httpx.AsyncClient, container: Container, alice: Principal, bob: Principal
) -> None:
    pdf = specimens.passport()
    created = await upload(api, alice, pdf, kind="passport")
    stored = next(container.settings.document_storage_dir.rglob("*.bin")).read_bytes()
    assert b"MEHTA" not in stored and b"%PDF" not in stored

    url = (await detail(api, alice, created["id"]))["content_url"]
    content = await api.get(url, headers=auth(alice))
    assert content.status_code == 200 and content.content == pdf
    assert content.headers["cache-control"].startswith("no-store")
    unsigned = await api.get(f"/api/documents/{created['id']}/content", headers=auth(alice))
    assert unsigned.status_code == 422
    tampered = await api.get(url.replace("sig=", "sig=0"), headers=auth(alice))
    assert tampered.status_code == 403
    assert (await api.get(url, headers=auth(bob))).status_code == 403  # bound to Alice


async def test_delete_destroys_bytes_and_everything_read(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(api, alice, specimens.passport(), kind="passport")
    await drain(container)
    assert list(container.settings.document_storage_dir.rglob("*.bin"))
    assert (
        await api.delete(f"/api/documents/{created['id']}", headers=auth(alice))
    ).status_code == 204

    assert not list(container.settings.document_storage_dir.rglob("*.bin"))
    assert (
        await api.get(f"/api/documents/{created['id']}", headers=auth(alice))
    ).status_code == 404
    assert created["id"] not in {
        d["id"] for d in (await api.get("/api/documents", headers=auth(alice))).json()
    }
    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    assert [n["type"] for n in graph["nodes"]] == ["person"]
    async with container.db.user_session(alice) as session:
        tombstone = await session.get(UserDocument, UUID(created["id"]))
        assert tombstone is not None and tombstone.status == "deleted"
        assert tombstone.filename == "Deleted document" and tombstone.storage_key is None
        facts = (await session.execute(select(ExtractedFact))).scalars().all()
        assert facts == []


async def test_documents_and_facts_are_isolated_between_users(
    api: httpx.AsyncClient, container: Container, alice: Principal, bob: Principal
) -> None:
    created = await upload(
        api, alice, specimens.marriage_certificate(), kind="marriage_certificate"
    )
    await drain(container)
    doc = await detail(api, alice, created["id"])
    fact_id = doc["facts"][0]["id"]

    assert (await api.get("/api/documents", headers=auth(bob))).json() == []
    assert (await api.get(f"/api/documents/{created['id']}", headers=auth(bob))).status_code == 404
    assert (
        await api.delete(f"/api/documents/{created['id']}", headers=auth(bob))
    ).status_code == 404
    assert (
        await api.post(f"/api/documents/{created['id']}/process", headers=auth(bob))
    ).status_code == 404
    assert (await api.get("/api/review-tasks", headers=auth(bob))).json() == []
    patched = await api.patch(
        f"/api/graph/user/facts/{fact_id}", json={"value": "x"}, headers=auth(bob)
    )
    assert patched.status_code == 404
    assert (
        await api.delete(f"/api/graph/user/facts/{fact_id}", headers=auth(bob))
    ).status_code == 404
    bob_graph = (await api.get("/api/graph/user", headers=auth(bob))).json()
    assert [n["type"] for n in bob_graph["nodes"]] == ["person"]
    assert "Priya" not in str(bob_graph)
    # Unauthenticated callers get nothing.
    assert (await api.get("/api/graph/user")).status_code == 401
    assert (await api.get("/api/documents")).status_code == 401


async def test_public_endpoints_never_expose_the_user_graph(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    await upload(api, alice, specimens.marriage_certificate(), kind="marriage_certificate")
    await drain(container)
    for path in ("/api/graph/governance", "/api/graph/governance?q=Priya"):
        body = (await api.get(path)).text
        assert "Priya" not in body and '"graph_type":"user"' not in body.replace(" ", "")
    authed = (await api.get("/api/graph/governance", headers=auth(alice))).text
    assert "Priya" not in authed


async def test_no_personal_data_in_events_logs_or_analytics(
    api: httpx.AsyncClient,
    container: Container,
    alice: Principal,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorded: list[dict[str, Any]] = []
    analytics.sinks.append(recorded.append)
    caplog.set_level(logging.DEBUG)
    try:
        await upload(
            api, alice, specimens.passport(), kind="passport", filename="arjun-passport.pdf"
        )
        await upload(api, alice, specimens.employment_letter(), kind="employment_letter")
        await drain(container)
    finally:
        analytics.sinks.remove(recorded.append)

    assert {r["event"] for r in recorded} >= {"document_uploaded", "document_processed"}
    for record in recorded:
        assert "user_id" not in record and "tenant_id" not in record
        assert not any(p in str(record) for p in (*PII, "arjun"))
    for log in caplog.records:
        text = log.getMessage() + str(log.__dict__.get("analytics", "")) + str(log.args)
        assert not any(p in text for p in PII), log.getMessage()
    async with container.db.user_session(alice) as session:
        payloads = [e.payload for e in (await session.execute(select(AgentEvent))).scalars()]
    assert payloads, "the extraction runs stream progress events"
    assert not any(p in str(payloads) for p in PII)


async def test_journey_agent_port_is_idempotent_and_explains(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(
        api, alice, specimens.marriage_certificate(), kind="marriage_certificate"
    )
    await drain(container)
    port = DocumentIntelligence(container.db, alice, container.adapters)

    class Exploding:
        provider, mode = "boom", "demo"

        async def read(self, request: Any) -> Any:
            raise AssertionError("an already-read document must not be read again")

    port.adapters = SimpleNamespace(**{**vars(container.adapters), "ocr": Exploding()})  # type: ignore[assignment]
    analysis = await port.analyze(UUID(created["id"]))
    assert analysis.status.value == "needs_review" and analysis.review_task_ids
    assert analysis.holder.value == "self"

    # The planner sees the spouse from the certificate and can explain why.
    facts = await planning_facts_for(container, alice)
    moving = facts["household.move_with_spouse"]
    assert moving.value is True and moving.source == "inferred"
    async with container.db.user_session(alice) as session:
        why = await explain(session, moving.fact_ids)
    assert {w.entity_label for w in why} == {"Spouse"}
    assert all(w.origin == "Read from your marriage certificate, not yet confirmed" for w in why)

    # Corrections through the port confirm everything else and finish the review.
    changes = await port.apply_corrections(
        UUID(created["id"]), [{"name": "attested", "value": "yes"}]
    )
    assert changes
    doc = await detail(api, alice, created["id"])
    assert doc["status"] == "confirmed"
    assert all(f["confirmed_by_user"] for f in doc["facts"])


async def test_one_step_review_corrects_and_confirms(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    created = await upload(
        api, alice, specimens.marriage_certificate(), kind="marriage_certificate"
    )
    await drain(container)
    reviewed = await api.post(
        f"/api/documents/{created['id']}/review",
        json={"corrections": [{"name": "attested", "value": "yes"}], "confirm": True},
        headers=auth(alice),
    )
    assert reviewed.status_code == 200, reviewed.text
    doc = reviewed.json()
    assert doc["status"] == "confirmed" and doc["review_tasks"] == []
    assert field(doc, "attested")["value"] is True
    assert all(f["confirmed_by_user"] for f in doc["facts"])
    unknown = await api.post(
        f"/api/documents/{created['id']}/review",
        json={"corrections": [{"name": "passport_number", "value": "Z1"}]},
        headers=auth(alice),
    )
    assert unknown.status_code == 404
