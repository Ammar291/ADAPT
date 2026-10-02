"""Deterministic planning, eligibility and risk detection over the governance graph."""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.journey import eligibility
from app.agents.journey.facts import fact
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.planning import analyse_dependencies, plan, prerequisite_chain
from app.agents.journey.risks import RiskInputs, detect_risks
from app.agents.journey.state import EligibilityResult, GovernanceContext, UserFact
from app.agents.journey.vocab import RiskKind, TaskStatus

from .governance_fixture import EDGES, NODES, _e, _n, snapshot


def facts(**values: Any) -> dict[str, UserFact]:
    """facts(goals=[...], household__move_with_spouse=True) -> fact dict ('__' = '.')."""
    out: dict[str, UserFact] = {}
    for name, value in values.items():
        key = name.replace("__", ".")
        source = "assumed" if isinstance(value, tuple) and value[0] == "assumed" else "user_stated"
        out[key] = fact(
            key, value[1] if source == "assumed" else value, source, fact_ids=[f"f:{key}"]
        )  # type: ignore[arg-type]
    return out


FOUNDER = dict(
    goals=["establish_company", "residency", "find_housing"],
    profile__is_founder=True,
    household__move_with_spouse=True,
    company__jurisdiction="mainland",
)


def keys(result: Any) -> set[str]:
    return {t["key"] for t in result.tasks}


class TestPlanner:
    def test_every_task_and_requirement_is_a_governance_node(self) -> None:
        """No hallucinated obligations: everything planned exists in the official graph."""
        g = snapshot()
        result = plan(g, facts(**FOUNDER))
        assert result.tasks
        for task in result.tasks:
            assert task["node_key"] in g.nodes
            assert task["evidence_ids"][0] == f"ref:{task['node_key']}"
            for link in task["links"]:
                assert link["via"] in g.nodes
        for req in result.requirements:
            assert req["node_key"] in g.nodes

    def test_founder_moving_with_spouse(self) -> None:
        result = plan(snapshot(), facts(**FOUNDER))
        assert {
            "service.commercial_license_mainland",
            "service.establishment_card",
            "service.residence_visa_investor",
            "service.tawtheeq",
            "service.family_residence_visa@spouse",
            "service.medical_fitness@spouse",
            "service.mofa_attestation",
        } <= keys(result)
        assert "service.company_registration_adgm" not in keys(result)
        visa = next(t for t in result.tasks if t["key"] == "service.family_residence_visa@spouse")
        # party=sponsor/household edges point at the user's own steps, beneficiary at the spouse's
        assert set(visa["depends_on"]) == {
            "service.residence_visa_investor",
            "service.tawtheeq",
            "service.mofa_attestation",
            "service.health_insurance@spouse",
            "service.medical_fitness@spouse",
        }
        assert "household.move_with_spouse" in visa["fact_keys"]
        assert visa["fact_ids"] == ["f:goals", "f:household.move_with_spouse"]

    def test_jurisdiction_selects_the_or_alternative(self) -> None:
        result = plan(snapshot(), facts(**{**FOUNDER, "company__jurisdiction": "adgm"}))
        assert "service.company_registration_adgm" in keys(result)
        assert not {"service.commercial_license_mainland", "service.trade_name_reservation"} & keys(
            result
        )
        card = next(t for t in result.tasks if t["key"] == "service.establishment_card")
        link = next(link for link in card["links"] if link["kind"] == "alternative")
        assert link["any_of"] == "dependency.company_licence"
        assert result.alternatives[0]["chosen"] == "service.company_registration_adgm"

    def test_not_moving_with_spouse_removes_family_steps(self) -> None:
        result = plan(snapshot(), facts(**{**FOUNDER, "household__move_with_spouse": False}))
        assert not [k for k in keys(result) if k.endswith("@spouse")]
        assert "service.family_residence_visa@spouse" not in keys(result)
        assert "service.mofa_attestation" not in keys(result)

    def test_held_documents_satisfy_requirements(self) -> None:
        result = plan(snapshot(), facts(**FOUNDER, documents__passport=True))
        passport = [
            r
            for r in result.requirements
            if r["node_key"] == "document.passport" and r["subject"] == "self"
        ]
        assert passport and all(r["status"] == "satisfied" for r in passport)
        spouse = [
            r
            for r in result.requirements
            if r["node_key"] == "document.passport" and r["subject"] == "spouse"
        ]
        assert spouse and all(r["status"] == "missing" for r in spouse)

    def test_completed_services_are_done_and_not_expanded(self) -> None:
        result = plan(snapshot(), facts(**FOUNDER, completed__residence_visa_investor=True))
        visa = next(t for t in result.tasks if t["key"] == "service.residence_visa_investor")
        assert visa["status"] == TaskStatus.DONE
        assert "service.entry_permit_investor" not in keys(result)  # prerequisite of a done step

    def test_holding_a_produced_document_counts_as_done(self) -> None:
        result = plan(snapshot(), facts(**FOUNDER, documents__residence_visa=True))
        visa = next(t for t in result.tasks if t["key"] == "service.residence_visa_investor")
        assert visa["status"] == TaskStatus.DONE

    def test_goals_without_governance_coverage_are_notes_not_tasks(self) -> None:
        result = plan(snapshot(), facts(goals=["residency", "schooling"]))
        assert result.tasks == []
        assert set(result.uncovered_goals) == {"residency", "schooling"}
        assert any("own company" in n for n in result.notes)

    def test_missing_root_service_is_reported(self) -> None:
        g = GovernanceSnapshot.of([n for n in NODES if n["key"] != "service.tawtheeq"], EDGES)
        result = plan(g, facts(goals=["find_housing"]))
        assert result.tasks == [] and result.uncovered_goals == ["find_housing"]

    def test_plan_is_deterministic(self) -> None:
        assert plan(snapshot(), facts(**FOUNDER)).tasks == plan(snapshot(), facts(**FOUNDER)).tasks


class TestDependencyAnalysis:
    def test_topological_order_levels_and_readiness(self) -> None:
        analysis = analyse_dependencies(plan(snapshot(), facts(**FOUNDER)).tasks)
        order = {t["key"]: t["order"] for t in analysis.tasks}
        for dep in analysis.dependencies:
            assert order[dep["depends_on"]] < order[dep["task"]], dep["id"]
        by_key = {t["key"]: t for t in analysis.tasks}
        assert by_key["service.trade_name_reservation"]["status"] == TaskStatus.READY
        assert by_key["service.trade_name_reservation"]["level"] == 0
        assert by_key["service.family_residence_visa@spouse"]["status"] == TaskStatus.BLOCKED
        assert analysis.critical_path[0] == "service.trade_name_reservation"
        assert analysis.critical_path[-1] == "service.family_residence_visa@spouse"
        assert analysis.cycles == []

    def test_done_prerequisites_make_dependents_ready(self) -> None:
        tasks = plan(snapshot(), facts(**FOUNDER, completed__trade_name_reservation=True)).tasks
        by_key = {t["key"]: t for t in analyse_dependencies(tasks).tasks}
        assert by_key["service.initial_approval"]["status"] == TaskStatus.READY

    def test_cycles_are_detected_not_guessed(self) -> None:
        cyclic = GovernanceSnapshot.of(
            [*NODES, _n("service.a", "A"), _n("service.b", "B")],
            [
                *EDGES,
                _e("service.tawtheeq", "depends_on", "service.a"),
                _e("service.a", "depends_on", "service.b"),
                _e("service.b", "depends_on", "service.a"),
            ],
        )
        analysis = analyse_dependencies(plan(cyclic, facts(goals=["find_housing"])).tasks)
        assert sorted(analysis.cycles[0]) == ["service.a", "service.b"]
        by_key = {t["key"]: t for t in analysis.tasks}
        assert by_key["service.a"]["level"] == -1
        assert by_key["service.tawtheeq"]["status"] == TaskStatus.BLOCKED

    def test_prerequisite_chain(self) -> None:
        analysis = analyse_dependencies(plan(snapshot(), facts(**FOUNDER)).tasks)
        chain = prerequisite_chain("service.entry_permit_investor", analysis.dependencies)
        assert chain[0] == "service.establishment_card"
        assert "service.trade_name_reservation" in chain


RULE = {
    "any": [
        {"fact": "finance.monthly_income_aed", "op": "gte", "value": 4000},
        {
            "all": [
                {"fact": "finance.monthly_income_aed", "op": "gte", "value": 3000},
                {"fact": "housing.accommodation_provided", "op": "eq", "value": True},
            ]
        },
    ]
}


class TestEligibility:
    @pytest.mark.parametrize(
        ("values", "status"),
        [
            ({"finance__monthly_income_aed": 5000}, "met"),
            ({"finance__monthly_income_aed": 3500, "housing__accommodation_provided": True}, "met"),
            (
                {"finance__monthly_income_aed": 3500, "housing__accommodation_provided": False},
                "unmet",
            ),
            ({"finance__monthly_income_aed": 2000}, "unmet"),
            ({"finance__monthly_income_aed": 3500}, "unknown"),  # accommodation not stated
            ({}, "unknown"),
        ],
    )
    def test_three_valued(self, values: dict[str, Any], status: str) -> None:
        assert eligibility.evaluate(RULE, facts(**values)).status == status

    def test_missing_facts_are_named(self) -> None:
        result = eligibility.evaluate(RULE, facts())
        assert result.missing == ["finance.monthly_income_aed", "housing.accommodation_provided"]

    def test_assumed_values_never_decide_eligibility(self) -> None:
        assumed = facts(finance__monthly_income_aed=("assumed", 9000))
        assert eligibility.evaluate(RULE, assumed).status == "unknown"
        assert eligibility.evaluate(RULE, assumed, allow_assumed=True).status == "met"

    def test_legacy_thresholds_become_a_condition(self) -> None:
        condition = eligibility.condition_of(
            {"threshold_aed": 4000, "threshold_with_accommodation_aed": 3000}
        )
        assert condition == RULE

    def test_describe(self) -> None:
        text = eligibility.describe(RULE)
        assert "monthly income (AED) at least 4,000" in text and "is yes" in text


def _inputs(
    values: dict[str, Any], eligibility_results: list[EligibilityResult] | None = None
) -> RiskInputs:
    g = snapshot()
    f = facts(**values)
    result = plan(g, f)
    analysis = analyse_dependencies(result.tasks)
    roots = result.root_services
    context: GovernanceContext = g.context(roots, result.notes)
    return RiskInputs(
        tasks=analysis.tasks,
        requirements=result.requirements,
        dependencies=analysis.dependencies,
        eligibility=eligibility_results or [],
        facts=f,
        evidence=[],
        governance=context,
    )


def _eligibility(
    status: str, missing: list[str] | None = None, verify: bool = True
) -> EligibilityResult:
    return EligibilityResult(
        rule_key="eligibility_rule.family_sponsor_income",
        service_key="service.family_residence_visa",
        subject="spouse",
        status=status,
        explanation="Sponsor income threshold: ...",  # type: ignore[typeddict-item]
        missing_facts=missing or [],
        fact_keys=["finance.monthly_income_aed"],
        evidence_ids=["ref:eligibility_rule.family_sponsor_income"],
        verify_on_official_page=verify,
    )


class TestRisks:
    def kinds(self, risks: list[Any]) -> set[str]:
        return {r["kind"] for r in risks}

    def test_founder_risks(self) -> None:
        risks = detect_risks(_inputs({**FOUNDER, "company__jurisdiction": ("assumed", "mainland")}))
        assert {
            RiskKind.MISSING_USER_DOCUMENT,
            RiskKind.MISSING_INFORMATION,
            RiskKind.TIMELINE_DEPENDENCY,
            RiskKind.EXTERNAL_LOGIN_REQUIRED,
        } <= self.kinds(risks)
        spouse_passport = next(
            r for r in risks if r["id"] == "risk:missing_user_document:spouse:document.passport"
        )
        assert spouse_passport["task_keys"] == [
            "service.family_residence_visa@spouse",
            "service.medical_fitness@spouse",
        ]
        assumed = next(
            r for r in risks if r["id"] == "risk:missing_information:company.jurisdiction"
        )
        assert "mainland" in assumed["title"]

    def test_every_risk_points_at_something_real(self) -> None:
        """A risk is tied to a governance node, a planned task or a known fact key."""
        inputs = _inputs(
            {**FOUNDER, "company__jurisdiction": ("assumed", "mainland")},
            [_eligibility("unknown", ["finance.monthly_income_aed"])],
        )
        tasks = {t["key"] for t in inputs.tasks}
        for risk in detect_risks(inputs):
            assert risk["governance_keys"] or risk["task_keys"] or risk["fact_keys"], risk["id"]
            assert set(risk["task_keys"]) <= tasks
            assert set(risk["governance_keys"]) <= set(snapshot().nodes)

    def test_eligibility_risks(self) -> None:
        unknown = detect_risks(
            _inputs(FOUNDER, [_eligibility("unknown", ["finance.monthly_income_aed"])])
        )
        assert "risk:missing_information:eligibility_rule.family_sponsor_income:spouse" in {
            r["id"] for r in unknown
        }
        assert "risk:missing_source_evidence:eligibility_rule.family_sponsor_income" in {
            r["id"] for r in unknown
        }
        gap = detect_risks(_inputs(FOUNDER, [_eligibility("unmet")]))
        risk = next(r for r in gap if r["kind"] == RiskKind.ELIGIBILITY_GAP)
        assert risk["severity"] == "warning"  # curated threshold, not a quoted passage

    def test_no_timeline_risk_when_spouse_follows_later(self) -> None:
        risks = detect_risks(_inputs({**FOUNDER, "household__spouse_relocation": "later"}))
        assert not [
            r for r in risks if r["id"].startswith("risk:timeline_dependency:service.family")
        ]

    def test_done_before_prerequisite_is_an_ordering_conflict(self) -> None:
        risks = detect_risks(_inputs({**FOUNDER, "completed__establishment_card": True}))
        conflict = [r for r in risks if r["kind"] == RiskKind.INCOMPATIBLE_TASK_ORDERING]
        assert conflict and "service.establishment_card" in conflict[0]["task_keys"]

    def test_ids_are_deterministic_and_sorted_by_severity(self) -> None:
        a = detect_risks(_inputs(FOUNDER))
        b = detect_risks(_inputs(FOUNDER))
        assert [r["id"] for r in a] == [r["id"] for r in b]
        order = {"blocking": 0, "warning": 1, "info": 2}
        assert [order[r["severity"]] for r in a] == sorted(order[r["severity"]] for r in a)


def test_a_decided_condition_asks_for_nothing() -> None:
    """Once an `any` is met (or an `all` unmet), undecided branches don't ask for facts."""
    met = eligibility.evaluate(RULE, facts(finance__monthly_income_aed=5000))
    assert met.status == "met" and met.missing == []
    unmet = eligibility.evaluate(
        {"all": [{"fact": "a.x", "op": "eq", "value": 1}, {"fact": "a.y", "op": "eq", "value": 2}]},
        facts(a__x=0),
    )
    assert unmet.status == "unmet" and unmet.missing == []


def test_rules_of_unchosen_alternatives_raise_no_risks() -> None:
    adgm_rule = _eligibility("unknown", ["company.has_resident_signatory"])
    adgm_rule = {
        **adgm_rule,
        "rule_key": "eligibility_rule.adgm_signatory_residency",
        "service_key": "service.company_registration_adgm",
    }
    risks = detect_risks(_inputs(FOUNDER, [adgm_rule]))  # mainland plan
    assert not [
        r for r in risks if "eligibility_rule.adgm_signatory_residency" in r["governance_keys"]
    ]
