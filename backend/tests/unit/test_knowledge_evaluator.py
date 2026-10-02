"""Requirement evaluation over a governance subgraph (pure, no database)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge.evaluator import (
    GEdge,
    GNode,
    GovernanceSubgraph,
    RequirementEvaluator,
    condition_problems,
    evaluate_condition,
)
from app.knowledge.schemas import CheckKind, CheckStatus, NextAction

MET, UNMET, UNKNOWN = CheckStatus.MET, CheckStatus.UNMET, CheckStatus.UNKNOWN

INCOME_RULE = {
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


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, GNode] = {}
        self.edges: list[GEdge] = []

    def node(self, key: str, label: str | None = None, **properties: Any) -> GraphBuilder:
        self.nodes[key] = GNode(
            id=uuid4(),
            key=key,
            entity_type=key.split(".")[0],
            label=label or key.split(".")[1].replace("_", " ").title(),
            properties=properties,
            official_url=f"https://u.ae/{key}",
        )
        return self

    def edge(self, source: str, relation: str, target: str, **properties: Any) -> GraphBuilder:
        self.edges.append(
            GEdge(
                id=uuid4(),
                relation=relation,
                source=self.nodes[source].id,
                target=self.nodes[target].id,
                properties=properties,
            )
        )
        return self

    def build(self) -> GovernanceSubgraph:
        return GovernanceSubgraph(list(self.nodes.values()), self.edges)


def founder_graph() -> GovernanceSubgraph:
    b = GraphBuilder()
    for key in (
        "service.family_residence_visa",
        "service.residence_visa_investor",
        "service.establishment_card",
        "service.commercial_license_mainland",
        "service.company_registration_adgm",
        "service.mofa_attestation",
        "service.tawtheeq",
        "document.passport",
        "document.marriage_certificate_attested",
        "document.residence_visa",
        "dependency.company_licence",
        "appointment.medical_screening",
        "portal.icp_services",
        "portal.tamm",
        "authority.icp",
    ):
        b.node(key)
    b.node("eligibility_rule.family_sponsor_income", condition=INCOME_RULE)
    b.node(
        "service.family_residence_visa",
        "Sponsor your spouse's residence visa",
        requires_uae_pass=True,
    )
    fam = "service.family_residence_visa"
    b.edge("authority.icp", "provides", fam)
    b.edge("eligibility_rule.family_sponsor_income", "applies_to", fam)
    b.edge(fam, "requires", "document.passport", party="beneficiary")
    b.edge(fam, "requires", "document.marriage_certificate_attested", party="household")
    b.edge(fam, "depends_on", "service.residence_visa_investor", party="sponsor")
    b.edge(fam, "depends_on", "service.tawtheeq")
    b.edge(fam, "available_at", "portal.icp_services")
    b.edge(fam, "may_require", "appointment.medical_screening")
    b.edge("appointment.medical_screening", "available_at", "portal.tamm")
    b.edge("service.mofa_attestation", "produces", "document.marriage_certificate_attested")
    b.edge("service.residence_visa_investor", "produces", "document.residence_visa")
    b.edge("service.residence_visa_investor", "depends_on", "service.establishment_card")
    b.edge("service.establishment_card", "depends_on", "dependency.company_licence")
    b.edge("service.establishment_card", "available_at", "portal.icp_services")
    when_mainland = {"fact": "company.jurisdiction", "op": "eq", "value": "mainland"}
    when_adgm = {"fact": "company.jurisdiction", "op": "eq", "value": "adgm"}
    b.edge(
        "dependency.company_licence",
        "satisfied_by",
        "service.commercial_license_mainland",
        when=when_mainland,
    )
    b.edge(
        "dependency.company_licence",
        "satisfied_by",
        "service.company_registration_adgm",
        when=when_adgm,
    )
    b.edge("service.commercial_license_mainland", "available_at", "portal.tamm")
    return b.build()


def assess(facts: dict[str, Any], subject: str | None = None):  # type: ignore[no-untyped-def]
    graph = founder_graph()
    evaluator = RequirementEvaluator(graph, facts, subject=subject)
    return graph, evaluator.assess(graph.by_key["service.family_residence_visa"])


def check(assessment, kind: CheckKind, key: str):  # type: ignore[no-untyped-def]
    return next(c for c in assessment.checks if c.kind is kind and c.node_key == key)


class TestConditions:
    def test_tri_state_and_or(self) -> None:
        assert evaluate_condition(INCOME_RULE, {"finance.monthly_income_aed": 25000}).status is MET
        assert evaluate_condition(INCOME_RULE, {"finance.monthly_income_aed": 2500}).status is UNMET
        assert evaluate_condition(INCOME_RULE, {}).status is UNKNOWN
        partial = evaluate_condition(INCOME_RULE, {"finance.monthly_income_aed": 3500})
        assert partial.status is UNKNOWN  # depends on accommodation, which is unknown
        assert partial.missing == ["housing.accommodation_provided"]
        assert (
            evaluate_condition(
                INCOME_RULE,
                {"finance.monthly_income_aed": 3500, "housing.accommodation_provided": True},
            ).status
            is MET
        )

    def test_numbers_as_strings_and_case_insensitive_equality(self) -> None:
        assert (
            evaluate_condition({"fact": "x", "op": "gte", "value": 10}, {"x": "12"}).status is MET
        )
        assert (
            evaluate_condition(
                {"fact": "company.jurisdiction", "op": "eq", "value": "adgm"},
                {"company.jurisdiction": "ADGM"},
            ).status
            is MET
        )
        assert (
            evaluate_condition({"fact": "x", "op": "gte", "value": 1}, {"x": "lots"}).status
            is UNKNOWN
        )

    def test_condition_validation(self) -> None:
        assert condition_problems(INCOME_RULE) == []
        assert condition_problems({"fact": "x", "op": "approx", "value": 1})
        assert condition_problems({"any": []})
        assert condition_problems({"fact": "x", "op": "gte"})


class TestAssessment:
    def test_nothing_known_asks_for_eligibility_first(self) -> None:
        _, result = assess({})
        assert result.overall == "needs_information"
        assert result.next_step.action is NextAction.PROVIDE_INFORMATION
        assert "finance.monthly_income_aed" in result.next_step.missing_facts

    def test_income_below_threshold_is_not_eligible(self) -> None:
        _, result = assess({"finance.monthly_income_aed": 2000})
        assert (
            check(result, CheckKind.ELIGIBILITY, "eligibility_rule.family_sponsor_income").status
            is UNMET
        )
        assert result.overall == "not_eligible"
        assert result.next_step.action is NextAction.REVIEW_ELIGIBILITY

    def test_missing_fact_is_unknown_never_unmet(self) -> None:
        _, result = assess({"finance.monthly_income_aed": 30000})
        doc = check(result, CheckKind.DOCUMENT, "document.passport")
        assert doc.status is UNKNOWN
        assert doc.facts[0].provided is False

    def test_eligible_founder_starts_the_longest_prerequisite_chain(self) -> None:
        graph, result = assess(
            {"finance.monthly_income_aed": 30000, "company.jurisdiction": "adgm"}
        )
        assert result.overall == "needs_information"
        step = result.next_step
        assert step.action is NextAction.COMPLETE_PREREQUISITE
        # residence visa -> establishment card -> company licence (ADGM path) comes first.
        assert step.task is not None
        assert step.task.key == "service.company_registration_adgm"
        assert graph.nodes[step.node_id].key == "service.company_registration_adgm"

    def test_unknown_jurisdiction_asks_which_path(self) -> None:
        graph = founder_graph()
        evaluator = RequirementEvaluator(graph, {"finance.monthly_income_aed": 30000})
        card = evaluator.assess(graph.by_key["service.establishment_card"])
        dep = check(card, CheckKind.DEPENDENCY, "dependency.company_licence")
        assert dep.status is UNKNOWN and dep.task is None
        assert card.next_step.action is NextAction.PROVIDE_INFORMATION
        assert card.next_step.missing_facts == ["company.jurisdiction"]

    def test_or_dependency_satisfied_by_any_alternative(self) -> None:
        graph = founder_graph()
        evaluator = RequirementEvaluator(graph, {"completed.commercial_license_mainland": True})
        card = evaluator.assess(graph.by_key["service.establishment_card"])
        assert check(card, CheckKind.DEPENDENCY, "dependency.company_licence").status is MET
        assert card.next_step.action is NextAction.APPLY
        assert card.next_step.portal is not None and card.next_step.portal.label == "Icp Services"

    def test_holding_the_output_document_completes_the_service(self) -> None:
        _, result = assess({"finance.monthly_income_aed": 30000, "documents.residence_visa": True})
        assert check(result, CheckKind.DEPENDENCY, "service.residence_visa_investor").status is MET

    def test_missing_document_points_at_the_service_that_issues_it(self) -> None:
        _, result = assess(
            {
                "finance.monthly_income_aed": 30000,
                "completed.residence_visa_investor": True,
                "completed.tawtheeq": True,
                "documents.passport": True,
                "documents.marriage_certificate_attested": False,
            }
        )
        doc = check(result, CheckKind.DOCUMENT, "document.marriage_certificate_attested")
        assert doc.status is UNMET and doc.task is not None
        assert doc.task.key == "service.mofa_attestation"
        assert result.overall == "blocked"
        assert result.next_step.action is NextAction.OBTAIN_DOCUMENT
        assert result.next_step.task is not None
        assert result.next_step.task.key == "service.mofa_attestation"

    def test_subject_reads_the_beneficiary_facts(self) -> None:
        facts = {
            "finance.monthly_income_aed": 30000,
            "documents.passport": False,  # the SPONSOR's passport: irrelevant here
            "spouse.documents.passport": True,
        }
        _, result = assess(facts, subject="spouse")
        passport = check(result, CheckKind.DOCUMENT, "document.passport")
        assert passport.status is MET
        assert [f.key for f in passport.facts] == ["spouse.documents.passport"]
        # household documents stay unprefixed
        marriage = check(result, CheckKind.DOCUMENT, "document.marriage_certificate_attested")
        assert marriage.facts[0].key == "documents.marriage_certificate_attested"

    def test_everything_in_place_books_then_applies(self) -> None:
        facts = {
            "finance.monthly_income_aed": 30000,
            "completed.residence_visa_investor": True,
            "completed.tawtheeq": True,
            "documents.passport": True,
            "documents.marriage_certificate_attested": True,
        }
        _, result = assess(facts)
        assert result.overall == "ready"
        step = result.next_step
        assert step.action is NextAction.BOOK_APPOINTMENT
        assert step.portal is not None and step.portal.label == "Tamm"
        assert step.handoff is True

        _, done = assess({**facts, "completed.family_residence_visa": True})
        assert done.next_step.action is NextAction.APPLY
        assert done.next_step.requires_uae_pass is True

    def test_every_check_points_at_a_real_graph_node_and_edge(self) -> None:
        graph, result = assess({"finance.monthly_income_aed": 30000})
        edge_ids = {e.id for e in graph.edges}
        for item in result.checks:
            assert item.node_id in graph.nodes
            assert item.edge_id in edge_ids
            assert graph.nodes[item.node_id].key == item.node_key


class TestConditionalEdges:
    def graph(self) -> GovernanceSubgraph:
        b = GraphBuilder()
        b.node("service.family_residence_visa")
        b.node("document.medical_fitness_certificate")
        b.edge(
            "service.family_residence_visa",
            "requires",
            "document.medical_fitness_certificate",
            party="beneficiary",
            when={"fact": "person.age", "op": "gte", "value": 18},
        )
        return b.build()

    def medical_check(self, facts: dict[str, Any]):  # type: ignore[no-untyped-def]
        graph = self.graph()
        result = RequirementEvaluator(graph, facts, subject="spouse").assess(
            graph.by_key["service.family_residence_visa"]
        )
        return [c for c in result.checks if c.node_key == "document.medical_fitness_certificate"]

    def test_applies_when_the_condition_holds(self) -> None:
        [item] = self.medical_check(
            {"spouse.person.age": 34, "spouse.documents.medical_fitness_certificate": False}
        )
        assert item.status is UNMET
        assert {f.key for f in item.facts} == {
            "spouse.documents.medical_fitness_certificate",
            "spouse.person.age",
        }

    def test_skipped_when_the_condition_does_not_hold(self) -> None:
        assert self.medical_check({"spouse.person.age": 12}) == []

    def test_undecided_condition_cannot_block(self) -> None:
        [item] = self.medical_check({"spouse.documents.medical_fitness_certificate": False})
        assert item.status is UNKNOWN
        assert any(f.key == "spouse.person.age" and not f.provided for f in item.facts)


class TestNextStepOrdering:
    def graph(self) -> GovernanceSubgraph:
        b = GraphBuilder()
        for key in (
            "service.family_residence_visa",
            "service.residence_visa_investor",
            "service.entry_permit_investor",
            "service.family_entry_permit",
            "service.sponsor_file",
            "service.tawtheeq",
            "document.residence_visa",
            "document.tenancy_contract_registered",
        ):
            b.node(key)
        b.node(
            "requirement.family_accommodation",
            condition={"fact": "documents.tenancy_contract_registered", "op": "truthy"},
        )
        fam = "service.family_residence_visa"
        b.edge(fam, "requires", "document.residence_visa", party="sponsor")
        b.edge(fam, "requires", "requirement.family_accommodation")
        b.edge(fam, "depends_on", "service.family_entry_permit", party="beneficiary")
        b.edge("service.family_entry_permit", "depends_on", "service.sponsor_file")
        b.edge("service.residence_visa_investor", "produces", "document.residence_visa")
        b.edge("service.residence_visa_investor", "depends_on", "service.entry_permit_investor")
        b.edge("service.tawtheeq", "produces", "document.tenancy_contract_registered")
        return b.build()

    def test_the_sponsors_own_residence_comes_first(self) -> None:
        graph = self.graph()
        result = RequirementEvaluator(graph, {}, subject="spouse").assess(
            graph.by_key["service.family_residence_visa"]
        )
        step = result.next_step
        assert step.action is NextAction.COMPLETE_PREREQUISITE
        assert step.task is not None and step.task.key == "service.entry_permit_investor"

    def test_requirement_satisfied_by_a_document_points_at_its_issuer(self) -> None:
        graph = self.graph()
        result = RequirementEvaluator(graph, {}).assess(
            graph.by_key["service.family_residence_visa"]
        )
        housing = next(c for c in result.checks if c.node_key == "requirement.family_accommodation")
        assert housing.task is not None and housing.task.key == "service.tawtheeq"


def test_decided_rules_only_show_the_facts_they_used() -> None:
    graph = founder_graph()
    result = RequirementEvaluator(graph, {"finance.monthly_income_aed": 30000}).assess(
        graph.by_key["service.family_residence_visa"]
    )
    income = next(c for c in result.checks if c.kind is CheckKind.ELIGIBILITY)
    assert income.status is MET
    assert [f.key for f in income.facts] == ["finance.monthly_income_aed"]
