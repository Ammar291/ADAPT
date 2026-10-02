"""Planning facts and explanations derived from a private user graph snapshot."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from app.personalization.projection import (
    FactView,
    GraphSnapshot,
    NodeView,
    evidence,
    planning_facts,
)
from app.personalization.vocabulary import UserEntityType

E = UserEntityType
TODAY = date(2026, 9, 29)
MARRIAGE_DOC = uuid4()


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[UUID, NodeView] = {}
        self.facts: list[FactView] = []
        self.instance_of: dict[UUID, list[str]] = {}
        self.hub = self.node(E.PERSON, None)

    def node(self, type_: UserEntityType, parent: NodeView | None) -> NodeView:
        node = NodeView(uuid4(), type_, f"{type_.value}.{len(self.nodes)}", type_.value,
                        parent.id if parent else None, len(self.nodes))  # fmt: skip
        self.nodes[node.id] = node
        return node

    def fact(self, node: NodeView, attribute: str, value: object, **kw: object) -> FactView:
        base: dict[str, object] = {
            "source": "user_stated", "confidence": 1.0, "confirmed_by_user": True,
            "status": "accepted",
        }  # fmt: skip
        base.update(kw)
        fact = FactView(uuid4(), node.id, attribute, value, **base)  # type: ignore[arg-type]
        self.facts.append(fact)
        return fact

    def snapshot(self, **kw: bool) -> GraphSnapshot:
        return GraphSnapshot(self.nodes, self.facts, self.instance_of, **kw)


def by_key(snap: GraphSnapshot, keys: list[str] | None = None) -> dict[str, object]:
    return {p.key: p for p in planning_facts(snap, keys, today=TODAY)}


def extracted(**kw: object) -> dict[str, object]:
    return {
        "source": "document_extracted", "confidence": 0.9, "confirmed_by_user": False,
        "source_document_id": MARRIAGE_DOC, "source_document_kind": "marriage_certificate",
        "extraction_method": "local:pdf-text", **kw,
    }  # fmt: skip


def test_spouse_from_marriage_certificate_implies_moving_with_spouse() -> None:
    g = Graph()
    spouse = g.node(E.SPOUSE, g.hub)
    name = g.fact(spouse, "full_name", "Priya Mehta", **extracted())
    married = g.fact(spouse, "married_on", "2019-11-23", **extracted())
    fact = by_key(g.snapshot())["household.move_with_spouse"]
    assert fact.value is True  # type: ignore[attr-defined]
    assert fact.source == "inferred" and not fact.confirmed  # type: ignore[attr-defined]
    assert set(fact.fact_ids) == {name.id, married.id}  # type: ignore[attr-defined]

    [why, *_] = evidence(g.snapshot(), fact.fact_ids)  # type: ignore[attr-defined]
    assert why.entity_label == "Spouse"
    assert why.origin == "Read from your marriage certificate, not yet confirmed"
    assert why.source_document_id == MARRIAGE_DOC


def test_explicit_statement_beats_inference() -> None:
    g = Graph()
    spouse = g.node(E.SPOUSE, g.hub)
    g.fact(spouse, "full_name", "Priya Mehta", **extracted())
    staying = g.fact(spouse, "moving_with_user", False)
    fact = by_key(g.snapshot())["household.move_with_spouse"]
    assert (fact.value, fact.source, fact.fact_ids) == (False, "user_stated", [staying.id])  # type: ignore[attr-defined]


def test_facts_awaiting_review_are_never_projected() -> None:
    g = Graph()
    spouse = g.node(E.SPOUSE, g.hub)
    g.fact(spouse, "full_name", "Pr1ya", status="needs_review", **extracted(confidence=0.4))
    assert "household.move_with_spouse" not in by_key(g.snapshot())


def test_shared_knowledge_keys_and_member_prefixes() -> None:
    g = Graph()
    g.fact(g.hub, "date_of_birth", "1990-04-12")
    g.fact(g.hub, "monthly_income", {"amount": 32000.0, "currency": "AED"})
    passport = g.node(E.PASSPORT, g.hub)
    g.fact(passport, "expiry_date", "2032-01-09")
    g.instance_of[passport.id] = ["document.passport"]
    spouse = g.node(E.SPOUSE, g.hub)
    g.fact(spouse, "full_name", "Priya Mehta")
    spouse_passport = g.node(E.PASSPORT, spouse)
    g.fact(spouse_passport, "issuing_country", "IND")
    g.instance_of[spouse_passport.id] = ["document.passport"]
    company = g.node(E.COMPANY, g.hub)
    g.fact(company, "jurisdiction", "adgm")
    child = g.node(E.CHILD, g.hub)
    g.fact(child, "date_of_birth", "2018-01-01")

    facts = by_key(g.snapshot())
    assert facts["person.age"].value == 36  # type: ignore[attr-defined]
    assert facts["finance.monthly_income_aed"].value == 32000.0  # type: ignore[attr-defined]
    assert facts["documents.passport"].value is True  # type: ignore[attr-defined]
    assert facts["spouse.documents.passport"].value is True  # type: ignore[attr-defined]
    assert facts["company.jurisdiction"].value == "adgm"  # type: ignore[attr-defined]
    assert facts["household.children_count"].value == 1  # type: ignore[attr-defined]
    assert facts["child1.person.age"].value == 8  # type: ignore[attr-defined]
    assert facts["passport.expiry_date"].value == "2032-01-09"  # type: ignore[attr-defined]
    assert set(by_key(g.snapshot(), ["company.jurisdiction"])) == {"company.jurisdiction"}


def test_consent_gates_community_and_faith() -> None:
    g = Graph()
    community = g.node(E.COMMUNITY_PREFERENCE, g.hub)
    g.fact(community, "interest", "Founders")
    g.fact(community, "faith_community", "Hindu")
    assert not {"community.interests", "community.faith"} & set(by_key(g.snapshot()))
    granted = by_key(g.snapshot(community_consent=True, faith_consent=True))
    assert granted["community.interests"].value == ["Founders"]  # type: ignore[attr-defined]
    assert granted["community.faith"].value == "Hindu"  # type: ignore[attr-defined]


def test_evidence_for_removed_and_corrected_facts() -> None:
    g = Graph()
    spouse = g.node(E.SPOUSE, g.hub)
    corrected = g.fact(spouse, "full_name", "Priya Mehta", corrected=True, **extracted())
    gone = uuid4()
    first, second = evidence(g.snapshot(), [corrected.id, gone])
    assert first.origin == "Corrected by you (originally read from your marriage certificate)"
    assert first.statement == (
        "Spouse · Full name: corrected by you (originally read from your marriage certificate)"
    )
    assert second.removed and second.statement == "A detail you have since removed"


def test_requirement_checks_never_see_community_or_faith() -> None:
    g = Graph()
    community = g.node(E.COMMUNITY_PREFERENCE, g.hub)
    g.fact(community, "interest", "Founders")
    g.fact(community, "faith_community", "Hindu")
    g.fact(g.hub, "monthly_income", {"amount": 32000.0, "currency": "AED"})
    snap = g.snapshot(community_consent=True, faith_consent=True)
    keys = {p.key for p in planning_facts(snap, today=TODAY, for_requirements=True)}
    assert keys == {"finance.monthly_income_aed"}
