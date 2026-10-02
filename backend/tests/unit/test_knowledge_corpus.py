"""Corpus and governance-graph seed validation (pure, no database).

Covers missing and stale source metadata, publisher/domain honesty, and the rule that
every governance relationship must cite a passage from an official source.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.knowledge.corpus import (
    Corpus,
    CorpusError,
    assess_freshness,
    chunk_text,
    load_corpus,
    parse_sources,
)
from app.knowledge.graph_seed import (
    GraphSeedError,
    load_graph_file,
    parse_graph_seed,
)
from app.knowledge.schemas import Freshness
from app.knowledge.sources import classify_source

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def raw_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "key": "u_ae.family_visa",
        "title": "Residence visa for families of employees",
        "url": "https://u.ae/en/information-and-services/family",
        "authority": "authority.uae_government",
        "source_type": "service_page",
        "retrieved_at": "2026-09-29",
        "topics": ["family_residency"],
        "verification": "fetched",
        "passages": [
            {
                "key": "sponsor_income",
                "section": "Who can sponsor",
                "excerpt": "quote",
                "states_requirement": True,
                "text": "Residents can sponsor their family if they earn a minimum salary.",
            },
            {
                "key": "documents",
                "section": "Documents",
                "excerpt": "paraphrase",
                "text": "A copy of the attested marriage certificate is needed for a spouse.",
            },
        ],
    }
    source.update(overrides)
    return source


def parse_one(raw: dict[str, Any]) -> tuple[list[Any], list[str]]:
    return parse_sources([raw], origin="test.yaml", now=NOW)


class TestSourceMetadata:
    def test_complete_record_is_accepted(self) -> None:
        records, problems = parse_one(raw_source())
        assert problems == []
        [record] = records
        assert record.retrieved_at == datetime(2026, 9, 29, tzinfo=UTC)
        assert record.effective_date is None  # optional and absent: fine

    @pytest.mark.parametrize(
        "missing",
        ["title", "url", "authority", "source_type", "retrieved_at", "topics", "passages"],
    )
    def test_missing_required_metadata_is_rejected(self, missing: str) -> None:
        raw = raw_source()
        del raw[missing]
        records, problems = parse_one(raw)
        assert records == []
        assert any(missing in p for p in problems), problems

    def test_unknown_fields_are_rejected(self) -> None:
        _, problems = parse_one(raw_source(retreived_at="2026-09-29"))  # typo
        assert any("retreived_at" in p for p in problems)

    def test_ordinary_web_pages_are_rejected(self) -> None:
        _, problems = parse_one(raw_source(url="https://expat-visa-guide.com/family"))
        assert any("allowlist" in p for p in problems)

    def test_publisher_must_own_the_domain(self) -> None:
        _, problems = parse_one(raw_source(authority="authority.icp"))
        assert any("not a Federal Authority" in p for p in problems)

    def test_unknown_publisher_is_rejected(self) -> None:
        _, problems = parse_one(raw_source(authority="authority.somebody"))
        assert any("unknown publisher" in p for p in problems)

    def test_http_is_rejected(self) -> None:
        _, problems = parse_one(raw_source(url="http://u.ae/en/family"))
        assert problems

    def test_snippet_sources_cannot_claim_quotes(self) -> None:
        _, problems = parse_one(raw_source(verification="search_snippet"))
        assert any("cannot claim verbatim quotes" in p for p in problems)

    def test_future_retrieval_date_is_rejected(self) -> None:
        _, problems = parse_one(raw_source(retrieved_at="2027-01-01"))
        assert any("future" in p for p in problems)

    def test_duplicate_passage_keys_are_rejected(self) -> None:
        raw = raw_source()
        raw["passages"][1]["key"] = "sponsor_income"
        _, problems = parse_one(raw)
        assert any("passage keys" in p for p in problems)


class TestCorpusLoading:
    def test_all_problems_across_files_are_reported(self, tmp_path: Path) -> None:
        missing_date = raw_source(key="u_ae.no_date")
        del missing_date["retrieved_at"]
        (tmp_path / "a.yaml").write_text(
            yaml.safe_dump({"sources": [raw_source(), missing_date]}), encoding="utf-8"
        )
        (tmp_path / "b.yaml").write_text(
            yaml.safe_dump({"sources": [raw_source(url="https://u.ae/en/other")]}),
            encoding="utf-8",
        )
        with pytest.raises(CorpusError) as exc:
            load_corpus(tmp_path, now=NOW)
        problems = " | ".join(exc.value.problems)
        assert "u_ae.no_date" in problems and "retrieved_at" in problems
        assert "duplicate source key 'u_ae.family_visa'" in problems


class TestStaleness:
    def test_future_check_date_is_not_current(self) -> None:
        assert assess_freshness(NOW + timedelta(days=1), now=NOW) is Freshness.STALE

    def test_stale_is_a_property_of_time_not_an_error(self) -> None:
        records, problems = parse_one(raw_source(retrieved_at="2024-01-15"))
        assert problems == []
        assert assess_freshness(records[0].retrieved_at, now=NOW) is Freshness.STALE
        assert (
            assess_freshness(NOW - timedelta(days=10), now=NOW, stale_after_days=180)
            is Freshness.CURRENT
        )

    def test_content_hash_ignores_the_check_date(self) -> None:
        a = parse_one(raw_source(retrieved_at="2026-01-01"))[0][0]
        b = parse_one(raw_source(retrieved_at="2026-09-01"))[0][0]
        assert a.content_hash == b.content_hash
        changed = raw_source()
        changed["passages"][0]["text"] = "Residents can sponsor their family if they earn more."
        assert parse_one(changed)[0][0].content_hash != a.content_hash


class TestChunking:
    def test_short_passages_are_one_chunk(self) -> None:
        assert chunk_text("One short sentence.") == ["One short sentence."]

    def test_long_passages_split_on_sentences(self) -> None:
        text = " ".join(f"Sentence number {i} is here." for i in range(200))
        chunks = chunk_text(text, max_chars=300)
        assert len(chunks) > 1 and all(len(c) <= 300 for c in chunks)
        assert " ".join(chunks) == text


class TestTheCuratedCorpus:
    def test_corpus_loads_and_is_entirely_official(self) -> None:
        corpus = load_corpus(now=NOW)
        assert len(corpus.sources) >= 30
        for source in corpus.sources:
            assert classify_source(source.url, source.authority).is_official, source.key

    def test_corpus_covers_every_domain_of_the_founder_journey(self) -> None:
        topics = {t.value for s in load_corpus(now=NOW).sources for t in s.topics}
        for required in (
            "residency",
            "family_residency",
            "medical_fitness",
            "health_insurance",
            "company_formation",
            "adgm",
            "tenancy",
            "driving",
            "uae_pass",
            "newcomer",
            "culture",
        ):
            assert required in topics, required

    def test_every_source_family_is_represented(self) -> None:
        priorities = {
            classify_source(s.url, s.authority).priority for s in load_corpus(now=NOW).sources
        }
        assert {1, 2, 3, 4, 5} <= priorities


def mini_corpus() -> Corpus:
    records, problems = parse_sources(
        [
            raw_source(),
            raw_source(
                key="icp.family_permit",
                url="https://icp.gov.ae/en/family",
                authority="authority.icp",
                title="Issuing a residency permit",
            ),
        ],
        origin="mini",
        now=NOW,
    )
    assert problems == []
    return Corpus(sources=records)


def mini_graph() -> dict[str, Any]:
    cite = ["u_ae.family_visa#sponsor_income"]
    return {
        "nodes": [
            {"key": "authority.icp", "type": "authority", "label": "ICP", "evidence": cite},
            {
                "key": "service.family_visa",
                "type": "service",
                "label": "Family visa",
                "evidence": cite,
            },
            {
                "key": "document.marriage_certificate_attested",
                "type": "document",
                "label": "Attested marriage certificate",
                "evidence": ["u_ae.family_visa#documents"],
            },
            {
                "key": "eligibility_rule.income",
                "type": "eligibility_rule",
                "label": "Income",
                "properties": {
                    "condition": {"fact": "finance.monthly_income_aed", "op": "gte", "value": 4000}
                },
                "evidence": cite,
            },
        ],
        "edges": [
            ["authority.icp", "provides", "service.family_visa", ["icp.family_permit#documents"]],
            [
                "service.family_visa",
                "requires",
                "document.marriage_certificate_attested",
                ["u_ae.family_visa#documents"],
            ],
            ["eligibility_rule.income", "applies_to", "service.family_visa", cite],
        ],
    }


class TestGraphSeedRules:
    def test_valid_seed(self) -> None:
        seed = parse_graph_seed(mini_graph(), mini_corpus())
        assert len(seed.nodes) == 4 and len(seed.edges) == 3

    def test_relationship_without_citation_is_rejected(self) -> None:
        data = mini_graph()
        data["edges"].append(["service.family_visa", "requires", "eligibility_rule.income", []])
        with pytest.raises(GraphSeedError, match="no evidence"):
            parse_graph_seed(data, mini_corpus())

    def test_citation_must_resolve_to_a_real_passage(self) -> None:
        data = mini_graph()
        data["edges"][0][3] = ["icp.family_permit#made_up"]
        with pytest.raises(GraphSeedError, match="does not resolve"):
            parse_graph_seed(data, mini_corpus())

    def test_uncited_node_is_rejected(self) -> None:
        data = mini_graph()
        data["nodes"][0]["evidence"] = []
        with pytest.raises(GraphSeedError, match=r"authority\.icp: no evidence"):
            parse_graph_seed(data, mini_corpus())

    @pytest.mark.parametrize(
        "edge",
        [
            ["service.family_visa", "provides", "authority.icp"],  # reversed
            ["document.marriage_certificate_attested", "requires", "service.family_visa"],
            ["authority.icp", "depends_on", "service.family_visa"],
            ["service.family_visa", "spouse_of", "authority.icp"],  # a user-graph relation
        ],
    )
    def test_relationship_endpoints_are_type_checked(self, edge: list[str]) -> None:
        data = mini_graph()
        data["edges"].append([*edge, ["u_ae.family_visa#documents"]])
        with pytest.raises(GraphSeedError):
            parse_graph_seed(data, mini_corpus())

    def test_dependency_cycles_are_rejected(self) -> None:
        data = mini_graph()
        cite = ["u_ae.family_visa#documents"]
        data["nodes"].append(
            {"key": "service.other", "type": "service", "label": "Other", "evidence": cite}
        )
        data["edges"] += [
            ["service.family_visa", "depends_on", "service.other", cite],
            ["service.other", "depends_on", "service.family_visa", cite],
        ]
        with pytest.raises(GraphSeedError, match="cycle"):
            parse_graph_seed(data, mini_corpus())

    def test_malformed_conditions_are_rejected(self) -> None:
        data = copy.deepcopy(mini_graph())
        data["nodes"][3]["properties"]["condition"] = {"fact": "x", "op": "roughly", "value": 1}
        with pytest.raises(GraphSeedError, match="unknown op"):
            parse_graph_seed(data, mini_corpus())

    def test_key_prefix_must_match_type(self) -> None:
        data = mini_graph()
        data["nodes"][2]["key"] = "doc.marriage"
        with pytest.raises(GraphSeedError):
            parse_graph_seed(data, mini_corpus())


class TestTheCuratedGraph:
    """The shipped seed: every node and relationship cites a real official passage."""

    def test_seed_is_valid_against_the_corpus(self) -> None:
        corpus = load_corpus(now=NOW)
        seed = parse_graph_seed(load_graph_file(), corpus)
        assert len(seed.nodes) >= 40 and len(seed.edges) >= 60
        for item in [*seed.nodes, *seed.edges]:
            for ref in item.evidence:
                source, _ = corpus.resolve(ref)
                assert classify_source(source.url, source.authority).is_official

    def test_requested_vocabulary_is_populated(self) -> None:
        seed = parse_graph_seed(load_graph_file(), load_corpus(now=NOW))
        types = {n.entity_type for n in seed.nodes}
        for entity in (
            "authority",
            "service",
            "requirement",
            "eligibility_rule",
            "document",
            "dependency",
            "appointment",
            "portal",
            "location",
        ):
            assert entity in types, entity
        relations = {e.relation.value for e in seed.edges}
        for relation in ("provides", "requires", "depends_on", "available_at", "may_require"):
            assert relation in relations, relation

    def test_primary_journey_services_exist(self) -> None:
        keys = {n.key for n in parse_graph_seed(load_graph_file(), load_corpus(now=NOW)).nodes}
        for required in (
            "service.company_registration_adgm",
            "service.commercial_license_mainland",
            "service.residence_visa_investor",
            "service.family_residence_visa",
            "service.tawtheeq",
            "service.medical_fitness",
            "service.emirates_id",
        ):
            assert required in keys, required


def test_aliases_must_be_strings() -> None:
    data = mini_graph()
    data["nodes"][1]["aliases"] = ["ambulance", 998]
    with pytest.raises(GraphSeedError, match="aliases must be a list of strings"):
        parse_graph_seed(data, mini_corpus())


def test_node_scoring_tolerates_stored_non_string_aliases() -> None:
    from app.knowledge.retrieval import score_node

    assert score_node("Call an ambulance", None, ["998", 998], ["998"]) > 0  # type: ignore[list-item]
