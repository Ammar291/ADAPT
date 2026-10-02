"""Generated-document lifecycle, appointment preparation, and consent-aware discovery."""

from __future__ import annotations

import httpx

from app.db.models import Appointment, GeneratedDocument
from app.db.session import Database
from app.domain.enums import AppointmentStatus, GeneratedDocumentKind
from app.domain.principal import Principal
from app.domain.provenance import Provenance
from app.repositories.graph import GovernanceGraphRepository
from tests.integration.conftest import auth


async def _draft(
    db: Database, principal: Principal, title: str = "Cover letter"
) -> GeneratedDocument:
    async with db.user_session(principal) as session:
        doc = GeneratedDocument(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            kind=GeneratedDocumentKind.COVER_LETTER,
            title=title,
            body_markdown="Dear team,\n\nDraft.",
            provenance=Provenance.ai("drafted").model_dump(mode="json"),
        )
        session.add(doc)
        await session.commit()
        return doc


async def test_generated_document_lifecycle(
    app_db: Database, api: httpx.AsyncClient, alice: Principal, bob: Principal
) -> None:
    doc = await _draft(app_db, alice)
    listing = (await api.get("/api/documents/generated", headers=auth(alice))).json()
    assert [d["status"] for d in listing if d["id"] == str(doc.id)] == ["draft"]
    assert (await api.get("/api/documents/generated", headers=auth(bob))).json() == []

    # Another user can neither read nor approve it.
    assert (
        await api.get(f"/api/documents/generated/{doc.id}", headers=auth(bob))
    ).status_code == 404
    assert (
        await api.post(f"/api/documents/generated/{doc.id}/approve", headers=auth(bob))
    ).status_code == 404

    approved = await api.post(
        f"/api/documents/generated/{doc.id}/approve",
        json={"body_markdown": "Dear team,\n\nFinal."},
        headers=auth(alice),
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved" and body["approved_at"]
    assert body["body_markdown"].endswith("Final.") and body["details"]["edited_by_user"] is True

    again = await api.post(f"/api/documents/generated/{doc.id}/approve", headers=auth(alice))
    assert again.status_code == 200  # idempotent
    changed = await api.post(
        f"/api/documents/generated/{doc.id}/approve",
        json={"body_markdown": "something else"},
        headers=auth(alice),
    )
    assert changed.status_code == 409
    assert (
        await api.post(f"/api/documents/generated/{doc.id}/discard", headers=auth(alice))
    ).status_code == 409

    other = await _draft(app_db, alice, "Email")
    assert (
        await api.post(f"/api/documents/generated/{other.id}/discard", headers=auth(alice))
    ).json()["status"] == "discarded"
    refused = await api.post(f"/api/documents/generated/{other.id}/approve", headers=auth(alice))
    assert refused.status_code == 409 and refused.json()["code"] == "generated_document_discarded"


async def test_appointment_preparation_never_books(
    app_db: Database, api: httpx.AsyncClient, alice: Principal, bob: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        service = await GovernanceGraphRepository(session).get("service.family_residence_visa")
        assert service is not None
        appointment = Appointment(
            tenant_id=alice.tenant_id,
            user_id=alice.user_id,
            title="Family visa typing centre visit",
            service_key=service.key,
            governance_node_id=service.id,
        )
        session.add(appointment)
        await session.commit()

    assert (
        await api.post(f"/api/appointments/{appointment.id}/prepare", headers=auth(bob))
    ).status_code == 404
    response = await api.post(f"/api/appointments/{appointment.id}/prepare", headers=auth(alice))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == AppointmentStatus.PLANNED.value and body["external_reference"] is None
    preparation = body["preparation"]
    assert preparation["items"], "requirements come from the governance graph"
    assert {i["status"] for i in preparation["items"]} <= {"ready", "missing", "check"}
    assert preparation["provenance"]["kind"] in {"official_guidance", "authoritative_requirement"}

    brief = (
        await api.get(
            f"/api/documents/generated/{preparation['brief_document_id']}", headers=auth(alice)
        )
    ).json()
    assert brief["kind"] == "appointment_brief" and brief["status"] == "draft"
    # Preparing again refreshes the same draft rather than piling up copies.
    again = (
        await api.post(f"/api/appointments/{appointment.id}/prepare", headers=auth(alice))
    ).json()
    assert again["preparation"]["brief_document_id"] == preparation["brief_document_id"]


async def test_faith_items_need_explicit_opt_in(api: httpx.AsyncClient, alice: Principal) -> None:
    communities = (await api.get("/api/communities", headers=auth(alice))).json()
    assert communities and all(c["category"] != "faith" for c in communities)
    assert all(c["source_url"] or c["is_sample"] for c in communities)

    await api.patch(
        "/api/me/preferences", json={"faith_personalization": "granted"}, headers=auth(alice)
    )
    with_consent = (await api.get("/api/communities", headers=auth(alice))).json()
    assert len(with_consent) >= len(communities)

    events = (await api.get("/api/events", headers=auth(alice))).json()
    assert events and all(e["starts_at"] or e["timing_note"] for e in events)


async def test_faith_preferences_require_consent(api: httpx.AsyncClient, bob: Principal) -> None:
    body = {"preferences": [{"category": "faith", "key": "community", "value": "yes"}]}
    refused = await api.patch("/api/profile", json=body, headers=auth(bob))
    assert refused.status_code == 422 and refused.json()["code"] == "faith_consent_required"
    body["consents"] = {"faith_personalization": "granted"}  # type: ignore[assignment]
    accepted = await api.patch("/api/profile", json=body, headers=auth(bob))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["preferences"][0]["source"] == "user_stated"
    withdrawn = await api.patch(
        "/api/profile", json={"consents": {"faith_personalization": "declined"}}, headers=auth(bob)
    )
    assert withdrawn.json()["preferences"] == []  # withdrawing consent removes faith data
