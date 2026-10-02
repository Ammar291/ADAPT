"""The sample household a demo visitor gets: documents that open, a plan to what-if.

Each test signs in through POST /auth/demo-session with `sample_household`, as the
`?seed=sample` link and the seeded demo server do, then uses the private copy.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.container import Container
from app.seed.demo import DOCUMENTS
from tests.integration.test_journey_agent import run_job, take_job

pytestmark = pytest.mark.integration


async def _sample_household(api: httpx.AsyncClient) -> dict[str, Any]:
    response = await api.post("/api/auth/demo-session", json={"sample_household": True})
    assert response.status_code == 200, response.text
    # The rest as an API client: the session token as a bearer token, no cookie (a browser
    # sends the cookie with an allowed Origin instead).
    api.headers["Authorization"] = f"Bearer {api.cookies.get('adapt_session')}"
    api.cookies.clear()
    journeys = (await api.get("/api/journey")).json()
    assert len(journeys) == 1, journeys
    detail = await api.get(f"/api/journey/{journeys[0]['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


async def test_sample_household_documents_are_read_and_open(api: httpx.AsyncClient) -> None:
    journey = await _sample_household(api)

    documents = (await api.get("/api/documents")).json()
    assert {(d["filename"], d["kind"]) for d in documents} == {
        (d.filename, d.kind.value) for d in DOCUMENTS
    }
    for document in documents:
        # Read by the pipeline, and every question it asked was answered.
        assert document["status"] in ("extracted", "confirmed"), document
        assert document["open_review_tasks"] == 0
        detail = (await api.get(f"/api/documents/{document['id']}")).json()
        assert detail["fields"] and detail["facts"] and not detail["review_tasks"]
        assert not [f for f in detail["fields"] if f["needs_review"]], detail["fields"]
        content = await api.get(detail["content_url"])  # signed link, decrypted from storage
        assert content.status_code == 200, content.text
        assert content.headers["content-type"] == "application/pdf"
        assert content.content.startswith(b"%PDF") and b"SPECIMEN" in content.content
    assert (await api.get("/api/review-tasks")).json() == []

    by_kind = {d["kind"]: d for d in documents}
    certificate = (await api.get(f"/api/documents/{by_kind['marriage_certificate']['id']}")).json()
    attested = next(f for f in certificate["fields"] if f["name"] == "attested")
    assert attested["value"] is False  # "Attestation: Pending": not attested yet

    # What was read is in his twin, and his plan relies on it.
    passport = journey["assumptions"]["documents.passport"]
    assert passport["value"] is True and passport["source"] == "document_extracted"
    nodes = {n["key"]: n for n in journey["nodes"]}
    assert nodes["service.company_registration_adgm"]["status"] == "done"  # ADGM licence
    assert nodes["service.tawtheeq"]["status"] == "done"  # registered tenancy contract


async def test_sample_household_plan_supports_what_ifs(
    api: httpx.AsyncClient, container: Container
) -> None:
    journey = await _sample_household(api)
    journey_id = journey["id"]
    assert journey["status"] == "active" and journey["latest_run"]["status"] == "succeeded"
    # The plan snapshot, the steps and the run agree.
    assert {t["key"] for t in journey["nodes"]} and journey["risks"] and journey["evidence"]
    awaiting = [a for a in journey["actions"] if a["status"] == "awaiting_approval"]
    assert awaiting
    assert {n["key"]: n["status"] for n in journey["nodes"]}[awaiting[0]["task_key"]] == (
        "awaiting_approval"
    )

    variables = {
        v["key"]: v for v in (await api.get(f"/api/journey/{journey_id}/what-if/variables")).json()
    }
    assert variables["company.jurisdiction"]["current"] == "adgm"
    assert variables["household.move_with_spouse"]["current"] is True

    async def what_if(key: str, value: Any) -> dict[str, Any]:
        response = await api.post(
            f"/api/journey/{journey_id}/simulate", json={"changes": [{"key": key, "value": value}]}
        )
        assert response.status_code == 202, response.text
        scenario_id = response.json()["scenario_journey_id"]
        outcome = await run_job(container, "run_what_if", take_job(container, "run_what_if"))
        assert outcome == "completed"
        scenario = (await api.get(f"/api/journey/{scenario_id}")).json()
        assert scenario["status"] == "scenario" and scenario["parent_journey_id"] == journey_id
        assert scenario["latest_run"]["status"] == "succeeded"
        result: dict[str, Any] = scenario["simulation_result"]
        assert result["changed_nodes"] and result["summary"]
        return result

    alone = await what_if("household.move_with_spouse", False)
    removed = {t["key"] for t in alone["removed_tasks"]}
    assert "service.family_residence_visa@spouse" in removed

    mainland = await what_if("company.jurisdiction", "mainland")
    assert mainland["changes"][0]["from"] == "adgm"
    assert "service.commercial_license_mainland" in {t["key"] for t in mainland["added_tasks"]}
    assert "service.company_registration_adgm" in {t["key"] for t in mainland["removed_tasks"]}

    # Starts at requirement planning: the governance context comes from the plan itself,
    # since a seeded plan has no checkpoint to copy it from.
    passport = await what_if("spouse.documents.passport", True)
    assert passport["rerun_nodes"][0] == "requirement_planner"
    assert {r["id"] for r in passport["changed_risks"] if r["change"] == "removed"} >= {
        "risk:missing_user_document:spouse:document.passport"
    }

    after = (await api.get(f"/api/journey/{journey_id}")).json()
    for key in ("status", "summary", "nodes", "edges", "risks", "actions", "assumptions"):
        assert after[key] == journey[key], key  # what-ifs never touch the plan


async def test_sample_household_approval_hands_off(api: httpx.AsyncClient) -> None:
    journey = await _sample_household(api)
    action = next(a for a in journey["actions"] if a["status"] == "awaiting_approval")
    # The seeded run has finished, so approving hands the step over straight away (as for
    # an action prepared outside a run) instead of waiting to resume it.
    response = await api.post(f"/api/actions/{action['id']}/approve", json={})
    assert response.status_code == 200, response.text
    decided = response.json()
    assert decided["action"]["status"] == "handoff_required" and not decided["run_resumed"]
    assert decided["action"]["official_url"]
