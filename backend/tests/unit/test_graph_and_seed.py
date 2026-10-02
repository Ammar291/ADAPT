from __future__ import annotations

import pytest

from app.db.models.catalogue import Community, Event
from app.domain.enums import EvidenceKind, GovernanceNodeType, GraphEdgeType, GraphType
from app.domain.graph import GraphRuleError, edge_graph_type
from app.domain.provenance import is_official_source
from app.seed.catalogue import catalogue_row, load_catalogue
from app.seed.demo import ONBOARDING
from app.seed.governance import load_seed, normalise_edges

G, U = GraphType.GOVERNANCE, GraphType.USER


class TestEdgeRules:
    def test_governance_edges_stay_public(self) -> None:
        assert edge_graph_type(GraphEdgeType.REQUIRES, G, G) is G

    @pytest.mark.parametrize("source,target", [(U, G), (G, U), (U, U)])
    def test_governance_edges_never_touch_user_nodes(
        self, source: GraphType, target: GraphType
    ) -> None:
        with pytest.raises(GraphRuleError):
            edge_graph_type(GraphEdgeType.REQUIRES, source, target)

    def test_personalisation_links_are_private(self) -> None:
        assert edge_graph_type(GraphEdgeType.PURSUES, U, G) is U

    def test_personalisation_links_cannot_start_in_governance(self) -> None:
        with pytest.raises(GraphRuleError):
            edge_graph_type(GraphEdgeType.SATISFIES, G, U)

    def test_user_internal_edges(self) -> None:
        assert edge_graph_type(GraphEdgeType.HAS_HOUSEHOLD_MEMBER, U, U) is U
        with pytest.raises(GraphRuleError):
            edge_graph_type(GraphEdgeType.HAS_HOUSEHOLD_MEMBER, U, G)


class TestInterimGovernanceSeed:
    def test_seed_is_consistent(self) -> None:
        data = load_seed()
        keys = [n["key"] for n in data["nodes"]]
        assert len(keys) == len(set(keys)), "duplicate node keys"
        types = {n["key"]: n["type"] for n in data["nodes"]}
        for node in data["nodes"]:
            GovernanceNodeType(node["type"])
            assert node["key"].split(".", 1)[0] == node["type"], node["key"]
            assert is_official_source(node["official_url"]), node["key"]
        for source, relation, target, _ in normalise_edges(data["edges"]):
            assert source in types and target in types, (source, target)
            edge_graph_type(relation, G, G)

    def test_or_dependencies_are_dependency_nodes(self) -> None:
        data = load_seed()
        edges = normalise_edges(data["edges"])
        satisfied = {t for s, r, t, _ in edges if r is GraphEdgeType.SATISFIED_BY}
        assert satisfied == {
            "service.commercial_license_mainland",
            "service.company_registration_adgm",
        }
        assert all(not props for *_, props in edges), "OR groups must not hide in properties"


class TestCatalogueSeed:
    def test_every_row_is_cited_or_sample(self) -> None:
        data = load_catalogue()
        for section in ("communities", "events", "cultural_guides"):
            for row in data.get(section) or []:
                assert row.get("source_url") or row.get("is_sample"), row["key"]

    def test_official_guidance_requires_an_official_source(self) -> None:
        row = catalogue_row(
            Community,
            {
                "key": "community.x",
                "name": "X",
                "category": "social",
                "description": "d",
                "source_url": "https://example.com/x",
                "evidence_kind": "official_guidance",
            },
            "2026-09-29",
        )
        assert row["evidence_kind"] == EvidenceKind.COMMUNITY_WEB.value

    def test_undated_events_get_a_timing_note(self) -> None:
        row = catalogue_row(
            Event,
            {
                "key": "events.x",
                "title": "X",
                "description": "d",
                "category": "culture",
                "source_url": "https://example.com",
            },
            "2026-09-29",
        )
        assert row["timing_note"] and row.get("starts_at") is None


class TestDemoPersona:
    def test_demo_household_is_complete(self) -> None:
        assert ONBOARDING.profile.nationality == "IND"
        relationships = {m.relationship.value for m in ONBOARDING.household}
        assert relationships == {"spouse", "child"}
        assert len(ONBOARDING.goals) >= 4
        # No faith data in the demo: it requires an explicit opt-in the persona never gave.
        assert all(p.category.value != "faith" for p in ONBOARDING.preferences)
