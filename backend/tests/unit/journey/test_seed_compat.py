"""The planner against the real, cited governance seed (app/knowledge/governance_graph.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.agents.journey.facts import fact
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.planning import GOAL_ROOTS, analyse_dependencies, plan
from app.agents.journey.risks import RiskInputs, detect_risks
from app.agents.journey.state import GovEdge, GovNode

SEED = Path(__file__).resolve().parents[3] / "app" / "knowledge" / "governance_graph.yaml"
pytestmark = pytest.mark.skipif(not SEED.exists(), reason="knowledge seed not present")


def real_snapshot() -> GovernanceSnapshot:
    data = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    nodes = [
        GovNode(
            key=n["key"],
            type=n["type"],
            label=n["label"],
            summary=n.get("summary"),
            official_url=n.get("official_url"),
            properties=dict(n.get("properties") or {}),
            provenance=None,
        )
        for n in data["nodes"]
    ]
    edges = []
    for raw in data["edges"]:
        if isinstance(raw, list):
            source, relation, target, _ = raw
            props: dict[str, Any] = {}
        else:
            source, relation, target = raw["source"], raw["relation"], raw["target"]
            props = dict(raw.get("properties") or {})
        edges.append(GovEdge(source=source, relation=relation, target=target, properties=props))
    return GovernanceSnapshot.of(nodes, edges)


def founder(**extra: Any) -> dict[str, Any]:
    values = {
        "goals": ["establish_company", "residency", "find_housing"],
        "profile.is_founder": True,
        "household.move_with_spouse": True,
        "company.jurisdiction": "mainland",
        **extra,
    }
    return {k: fact(k, v, "user_stated") for k, v in values.items()}


def test_goal_roots_exist_in_the_seed() -> None:
    g = real_snapshot()
    for roots in GOAL_ROOTS.values():
        for key, _ in roots:
            assert key in g.nodes, key


def test_founder_plan_from_the_seed() -> None:
    g = real_snapshot()
    result = plan(g, founder())
    analysis = analyse_dependencies(result.tasks)
    keys = {t["key"] for t in analysis.tasks}
    assert analysis.cycles == []
    assert {
        "service.commercial_license_mainland",
        "service.residence_visa_investor",
        "service.family_residence_visa@spouse",
        "service.tawtheeq",
    } <= keys
    # every planned step exists in the cited graph
    assert all(t["node_key"] in g.nodes for t in analysis.tasks)
    visa = next(t for t in analysis.tasks if t["key"] == "service.family_residence_visa@spouse")
    assert "service.family_entry_permit@spouse" in visa["depends_on"]
    # the marriage certificate applies because the beneficiary is the spouse
    assert any(
        r["node_key"] == "document.marriage_certificate_attested" for r in result.requirements
    )
    assert not any(
        r["node_key"] == "document.birth_certificate_attested" for r in result.requirements
    )


def test_conditional_requirement_needs_the_fact_not_a_guess() -> None:
    g = real_snapshot()
    unknown = plan(g, founder())
    medical = [
        r
        for r in unknown.requirements
        if r["node_key"] == "document.medical_fitness_certificate" and r["subject"] == "spouse"
    ]
    assert medical and medical[0]["status"] == "unknown"
    assert medical[0]["fact_keys"] == ["spouse.person.age"]

    adult = plan(g, founder(**{"spouse.person.age": 34}))
    medical = [
        r
        for r in adult.requirements
        if r["node_key"] == "document.medical_fitness_certificate" and r["subject"] == "spouse"
    ]
    assert medical and medical[0]["status"] != "unknown"


def test_seed_risks_reference_real_nodes() -> None:
    g = real_snapshot()
    result = plan(g, founder())
    analysis = analyse_dependencies(result.tasks)
    risks = detect_risks(
        RiskInputs(
            tasks=analysis.tasks,
            requirements=result.requirements,
            dependencies=analysis.dependencies,
            eligibility=[],
            facts=founder(),
            evidence=[],
            governance=g.context(result.root_services, result.notes),
        )
    )
    assert any(r["id"].startswith("risk:missing_information:condition:") for r in risks)
    for risk in risks:
        assert set(risk["governance_keys"]) <= set(g.nodes)


def test_beneficiary_rules_are_checked_for_the_spouse() -> None:
    from app.agents.journey.eligibility import assess

    g = real_snapshot()
    facts = founder(**{"finance.monthly_income_aed": 25000})
    result = plan(g, facts)
    context = g.context(result.root_services, result.notes)
    rules = {
        r["rule_key"]: r
        for r in assess(context, facts, {"service.family_residence_visa": "spouse"})
    }
    assert rules["eligibility_rule.family_eligible_members"]["status"] == "met"  # the spouse
    assert (
        rules["eligibility_rule.family_sponsor_income"]["status"] == "met"
    )  # the sponsor's income
