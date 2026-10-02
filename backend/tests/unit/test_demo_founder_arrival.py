"""The "Founder Arrival" demo scenario: synthetic documents, what they change in the plan,
the findings it surfaces, its research and the scenario kit API."""

from __future__ import annotations

import io
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pypdf import PdfReader

from app.adapters.ocr import LocalTextReader, ReadRequest
from app.agents.journey.considerations import detect_considerations
from app.agents.journey.facts import fact
from app.agents.journey.planning import analyse_dependencies, plan
from app.demo_scenarios import founder_arrival
from app.demo_scenarios.documents import BY_KEY, DOCUMENTS, PERSONA
from app.documents.catalogue import READ_SCHEMA, DocumentKind
from app.documents.structuring import SELF, StructuringContext, governance_document_key, structure
from app.documents.validation import validate_reading
from app.main import create_app
from app.personalization.vocabulary import UserEntityType
from app.research.engines import SnapshotResearchEngine, build_research_engine
from app.research.presenters import retrieval_out
from app.research.profile import ResearchProfile
from app.research.snapshot import load_catalogue, select_entries
from app.research.types import RelocationType, ResearchCategory, ResearchMode

sys.path.insert(0, str(Path(__file__).parent / "journey"))
from test_seed_compat import real_snapshot

sys.path.insert(0, str(Path(__file__).parent))
from test_personalization_projection import Graph, by_key, extracted
from test_platform import settings

E = UserEntityType


async def read(key: str) -> Any:
    doc = BY_KEY[key]
    reading = await LocalTextReader().read(
        ReadRequest(doc.build(), "application/pdf", READ_SCHEMA, doc.kind)
    )
    return reading, validate_reading(DocumentKind(doc.kind), reading, today=date(2026, 10, 2))


# --- documents -------------------------------------------------------------------------------


class TestSyntheticDocuments:
    @pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda d: d.key)
    def test_clearly_synthetic_on_every_page(self, doc: Any) -> None:
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(doc.build())).pages)
        assert "SPECIMEN - SYNTHETIC DEMO DOCUMENT" in text
        assert "fictional" in text

    @pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda d: d.key)
    async def test_every_field_reads_back_without_review(self, doc: Any) -> None:
        reading, outcome = await read(doc.key)
        assert reading.detected_type == doc.kind
        assert reading.type_confidence >= 0.95
        assert outcome.fields
        assert [n for n, f in outcome.fields.items() if f.needs_review] == []

    async def test_passport_mrz_verifies_the_visual_zone(self) -> None:
        _, outcome = await read("passport")
        assert outcome.mrz is not None and outcome.mrz.valid
        assert outcome.value("nationality") == "IND"
        assert outcome.value("date_of_birth") == PERSONA.date_of_birth.isoformat()
        assert all(f.method.endswith("+mrz") for f in outcome.fields.values())

    async def test_marriage_certificate_spouse_and_attestation(self) -> None:
        _, outcome = await read("marriage_certificate")
        ctx = StructuringContext(uuid4(), SELF, 0.95, "local:pdf-text", self_name="Kabir Rahman")
        facts = {(f.entity.type, f.attribute): f.value for f in structure(outcome, ctx).facts}
        assert facts[(E.SPOUSE, "full_name")] == PERSONA.spouse_name
        assert facts[(E.SPOUSE, "date_of_birth")] == PERSONA.spouse_date_of_birth.isoformat()
        assert facts[(E.DOCUMENT, "home_attested")] is True
        assert facts[(E.DOCUMENT, "attested")] is False
        # Not UAE-attested yet, so it is not the governance document the family visa needs.
        assert (
            governance_document_key(
                E.DOCUMENT, {"document_kind": "marriage_certificate", "attested": False}
            )
            is None
        )

    async def test_business_profile_is_a_plan_not_a_licence(self) -> None:
        _, outcome = await read("business_profile")
        result = structure(outcome, StructuringContext(uuid4(), SELF, 0.95, "local:pdf-text"))
        facts = {(f.entity.type, f.attribute): f for f in result.facts}
        assert facts[(E.COMPANY, "jurisdiction")].value == "adgm"
        assert not facts[(E.COMPANY, "jurisdiction")].needs_review
        assert facts[(E.COMPANY, "stage")].value == "idea"
        assert (E.DOCUMENT, "issuer") not in facts  # ADGM did not issue the founder's plan
        title = facts[(E.DOCUMENT, "title")].value
        assert (
            governance_document_key(
                E.DOCUMENT, {"document_kind": "business_document", "title": title}
            )
            is None
        )


class TestHomeAttestationProjection:
    def test_home_attested_certificate_meets_the_requirement(self) -> None:
        g = Graph()
        doc = g.node(E.DOCUMENT, g.hub)
        kind = g.fact(doc, "document_kind", "marriage_certificate", **extracted())
        home = g.fact(doc, "home_attested", True, **extracted())
        projected = by_key(g.snapshot())["meets.home_country_attestation"]
        assert projected.value is True  # type: ignore[attr-defined]
        assert set(projected.fact_ids) == {kind.id, home.id}  # type: ignore[attr-defined]

    def test_not_projected_when_not_attested_or_with_children(self) -> None:
        g = Graph()
        doc = g.node(E.DOCUMENT, g.hub)
        g.fact(doc, "document_kind", "marriage_certificate", **extracted())
        g.fact(doc, "home_attested", False, **extracted())
        assert "meets.home_country_attestation" not in by_key(g.snapshot())

        g = Graph()
        doc = g.node(E.DOCUMENT, g.hub)
        g.fact(doc, "document_kind", "marriage_certificate", **extracted())
        g.fact(doc, "home_attested", True, **extracted())
        child = g.node(E.CHILD, g.hub)
        g.fact(child, "full_name", "A Child")
        assert "meets.home_country_attestation" not in by_key(g.snapshot())


# --- plan and findings -----------------------------------------------------------------------

SCENARIO_FACTS: dict[str, Any] = {
    "goals": ["establish_company", "residency", "find_housing", "sponsor_family"],
    "profile.is_founder": True,
    "household.move_with_spouse": True,
    "company.jurisdiction": "adgm",
    "nationality": ["IND"],
    "documents.passport": True,
    "meets.home_country_attestation": True,
    "spouse.person.age": 32,
}


def scenario_plan(**overrides: Any) -> dict[str, Any]:
    g = real_snapshot()
    values = {**SCENARIO_FACTS, **overrides}
    facts = {k: fact(k, v, "document_extracted", fact_ids=[f"fact:{k}"]) for k, v in values.items()}
    result = plan(g, facts)
    analysis = analyse_dependencies(result.tasks)
    keys = {t["node_key"] for t in analysis.tasks} | {r["node_key"] for r in result.requirements}
    evidence = [  # what retrieve_evidence attaches: an official reference per node used
        {"id": f"ref:{k}", "kind": "official_reference", "governance_key": k,
         "source_url": "https://icp.gov.ae/en/", "title": k}
        for k in sorted(keys)
    ]  # fmt: skip
    return {
        "tasks": analysis.tasks,
        "dependencies": analysis.dependencies,
        "requirements": result.requirements,
        "facts": list(facts.values()),
        "evidence": evidence,
    }


class TestScenarioPlan:
    def test_featured_roles_are_in_the_plan(self) -> None:
        tasks = {t["key"]: t for t in scenario_plan()["tasks"]}
        for role in founder_arrival.definition().roles:
            assert role.task_key in tasks, role
        # The documents shape the plan: ADGM, the chain starts at the mission visit, and the
        # spouse's age settles the medical-certificate condition.
        assert "service.commercial_license_mainland" not in tasks
        assert "requirement.home_country_attestation" not in tasks
        assert tasks["appointment.uae_mission_visit"]["status"] == "ready"
        assert tasks["appointment.uae_mission_visit"]["action_type"] == "appointment"
        assert tasks["service.sponsor_file"]["area"] == "family"
        assert tasks["service.adgm_business_application"]["area"] == "business"

    def test_spouse_age_resolves_the_medical_condition(self) -> None:
        unknown = [
            r for r in scenario_plan()["requirements"] if r["status"] == "unknown"
        ]  # fmt: skip
        assert unknown == []

    def test_two_cited_findings(self) -> None:
        found = detect_considerations(scenario_plan(), real_snapshot().nodes)
        assert [c["id"] for c in found] == [
            "consideration:attestation_abroad",
            "consideration:lease_before_family_visa",
        ]
        attestation, lease = found
        assert "already carries" in attestation["detail"]
        assert attestation["fact_keys"] == ["meets.home_country_attestation"]
        assert attestation["fact_ids"] == ["fact:meets.home_country_attestation"]
        assert "service.family_residence_visa@spouse" in attestation["task_keys"]
        assert "Tawtheeq" in lease["detail"] and "emirates id" in lease["detail"].lower()
        for item in found:
            assert item["evidence_ids"], item["id"]
            assert set(item["task_keys"]) <= {t["key"] for t in scenario_plan()["tasks"]}

    def test_findings_follow_the_household(self) -> None:
        alone = scenario_plan(**{"household.move_with_spouse": False})
        assert detect_considerations(alone, real_snapshot().nodes) == []

    def test_no_citation_no_finding(self) -> None:
        uncited = {**scenario_plan(), "evidence": []}
        assert detect_considerations(uncited, real_snapshot().nodes) == []


# --- research --------------------------------------------------------------------------------

PROFILE = ResearchProfile(
    relocation_type=RelocationType.BUSINESS,
    profession="Technology start-up founder",
    interests=("Indian community", "start-up founders"),
    background="India",
    faith="Muslim",
    faith_opted_in=True,
    community_opted_in=True,
)


def titles(category: ResearchCategory) -> list[str]:
    return [m.entry.title for m in select_entries(load_catalogue(), category, PROFILE, limit=6)]


class TestScenarioResearch:
    def test_indian_and_muslim_resources_need_the_stated_facts(self) -> None:
        assert any("India" in t for t in titles(ResearchCategory.COMMUNITY))
        faith = titles(ResearchCategory.FAITH_AND_WORSHIP)
        assert any("Awqaf" in t for t in faith) and any("Sheikh Zayed" in t for t in faith)
        neutral = PROFILE.model_copy(update={"background": None, "faith_opted_in": False})
        community = select_entries(load_catalogue(), ResearchCategory.COMMUNITY, neutral, limit=6)
        assert not any("India" in m.entry.title for m in community)
        assert (
            select_entries(load_catalogue(), ResearchCategory.FAITH_AND_WORSHIP, neutral, limit=6)
            == []
        )

    def test_startup_and_starter_services(self) -> None:
        professional = titles(ResearchCategory.PROFESSIONAL_NETWORK)
        assert any("Hub71" in t for t in professional)
        assert any("ADGM" in t or "Abu Dhabi Global Market" in t for t in professional)
        assert not any("Khalifa" in t for t in professional)  # for Emirati entrepreneurs
        starter = titles(ResearchCategory.STARTER_KIT)
        assert starter[0].startswith("TAMM")
        assert any("Electricity and water" in t for t in starter)

    def test_snapshot_mode_is_honoured_and_labelled(self) -> None:
        class Live:
            mode = "live"

        adapters: Any = type("Adapters", (), {"web_search": Live(), "llm": Live()})()
        assert isinstance(build_research_engine(adapters, snapshot=True), SnapshotResearchEngine)
        checked = datetime(2026, 9, 29, tzinfo=UTC)
        snap = retrieval_out(ResearchMode.SNAPSHOT, checked)
        assert snap.method == "curated_snapshot"
        assert "29 Sep 2026" in snap.note and "Not a live web search" in snap.note
        assert retrieval_out(ResearchMode.LIVE, checked).method == "live_web_search"


# --- scenario kit API ------------------------------------------------------------------------


class TestScenarioKit:
    @pytest.fixture
    def app(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        return create_app(settings(document_storage_dir=tmp_path, demo_auth_enabled=True))

    async def test_definition_and_documents(self, app: Any) -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            listed = (await c.get("/api/demo/scenarios")).json()
            assert [s["key"] for s in listed] == ["founder-arrival"]
            scenario = (await c.get("/api/demo/scenarios/founder-arrival")).json()
            assert scenario["journey"]["deterministic"] is True
            assert scenario["research"]["mode"] == "snapshot"
            consents = scenario["onboarding"]["consents"]
            assert consents["faith_personalization"] == "granted"
            assert "nationality" not in {
                k for k, v in scenario["onboarding"]["profile"].items() if v
            }
            for doc in scenario["documents"]:
                pdf = await c.get(doc["url"])
                assert pdf.status_code == 200
                assert pdf.headers["content-type"] == "application/pdf"
                assert pdf.content.startswith(b"%PDF")
            assert (await c.get("/api/demo/scenarios/unknown")).status_code == 404
            info = (await c.get("/api/system/info")).json()
            assert info["features"]["demo_scenarios"] is True

    async def test_not_available_without_demo_sign_in(self, tmp_path: Path) -> None:
        app = create_app(settings(document_storage_dir=tmp_path, demo_auth_enabled=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            assert (await c.get("/api/demo/scenarios")).status_code == 404
            path = "/api/demo/scenarios/founder-arrival/documents/passport"
            assert (await c.get(path)).status_code == 404
