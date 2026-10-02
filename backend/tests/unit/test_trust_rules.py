"""The product's trust contract: provenance tiers, sensitive attributes, honest actions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import ConsentStatus, EvidenceKind, FactSource
from app.domain.provenance import Citation, Provenance, is_official_source
from app.domain.twin import SensitiveAttributeError, TwinFact, TwinFactSet, validate_twin_facts

NOW = datetime(2026, 9, 29, tzinfo=UTC)


class TestOfficialSources:
    @pytest.mark.parametrize(
        "url",
        [
            "https://icp.gov.ae",
            "https://www.tamm.abudhabi/en/services",
            "https://u.ae/en/information-and-services",
            "https://www.adgm.com/registration-authority",
            "https://added.gov.ae/path?q=1",
        ],
    )
    def test_official(self, url: str) -> None:
        assert is_official_source(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://icp.gov.ae",  # not https
            "https://gov.ae.example.com",  # suffix trick
            "https://notgov.ae",  # substring, not a subdomain
            "https://visitabudhabi.ae",  # tourism site, not a government service authority
            "https://www.reddit.com/r/abudhabi",
            "not a url",
        ],
    )
    def test_not_official(self, url: str) -> None:
        assert not is_official_source(url)


class TestProvenance:
    def test_authoritative_requires_official_citation(self) -> None:
        with pytest.raises(ValidationError, match="official government source"):
            Provenance(
                kind=EvidenceKind.AUTHORITATIVE_REQUIREMENT,
                citations=[Citation(source_url="https://example.com/blog", source_title="Blog")],
            )

    def test_official_guidance_with_official_citation(self) -> None:
        p = Provenance(
            kind=EvidenceKind.OFFICIAL_GUIDANCE,
            citations=[Citation(source_url="https://icp.gov.ae", source_title="ICP")],
        )
        assert p.citations[0].is_official

    def test_community_web_requires_retrieval_time(self) -> None:
        with pytest.raises(ValidationError, match="retrieved_at"):
            Provenance(
                kind=EvidenceKind.COMMUNITY_WEB,
                citations=[Citation(source_url="https://example.com", source_title="Example")],
            )
        Provenance(
            kind=EvidenceKind.COMMUNITY_WEB,
            citations=[
                Citation(source_url="https://example.com", source_title="Ex", retrieved_at=NOW)
            ],
        )

    def test_ai_recommendation_needs_no_citation(self) -> None:
        assert Provenance.ai("Consider opening a bank account early").citations == []


class TestSensitiveAttributes:
    def test_faith_is_never_inferred(self) -> None:
        facts = {"religion": TwinFact(value="x", source=FactSource.INFERRED)}
        with pytest.raises(SensitiveAttributeError, match="never infers"):
            validate_twin_facts(facts, faith_consent=ConsentStatus.GRANTED)

    def test_faith_not_taken_from_documents(self) -> None:
        facts = {"religion": TwinFact(value="x", source=FactSource.DOCUMENT_EXTRACTED)}
        with pytest.raises(SensitiveAttributeError):
            validate_twin_facts(facts, faith_consent=ConsentStatus.GRANTED)

    def test_faith_requires_opt_in(self) -> None:
        facts = {"faith_community": TwinFact(value="x", source=FactSource.USER_STATED)}
        with pytest.raises(SensitiveAttributeError, match="opt in"):
            validate_twin_facts(facts, faith_consent=ConsentStatus.DECLINED)
        validate_twin_facts(facts, faith_consent=ConsentStatus.GRANTED)

    def test_ethnicity_stated_by_user_is_allowed(self) -> None:
        validate_twin_facts({"ethnicity": TwinFact(value="x", source=FactSource.USER_STATED)})

    def test_nationality_is_not_sensitive(self) -> None:
        facts = TwinFactSet(
            facts={"nationality": TwinFact(value="IND", source=FactSource.DOCUMENT_EXTRACTED)}
        )
        assert facts.to_properties()["nationality"]["value"] == "IND"

    def test_fact_set_validates_on_construction(self) -> None:
        with pytest.raises(ValidationError):
            TwinFactSet(facts={"Religion": TwinFact(value="x", source=FactSource.INFERRED)})
