"""What the rest of ADAPT reads from the private user graph, and how it is explained.

Pure functions over a `GraphSnapshot` (built from the database by `facts.py`):

* `planning_facts()`: a flat, curated projection with stable keys, used by the journey
  planner, the knowledge layer's rule checks and research personalisation. Keys follow
  the shared vocabulary in `app.knowledge.facts` (e.g. `documents.passport`,
  `finance.monthly_income_aed`, `household.move_with_spouse`), prefixed with `spouse.` /
  `childN.` for household members. Every planning fact lists the fact ids it rests on.
* `evidence()`: per-fact explanation ("Spouse · Full name, read from your marriage
  certificate"), used to render "which of your details were used" under a recommendation.

Only *accepted* facts are projected. Facts awaiting review never drive a plan.
Consent gates apply here as well as in consumers: community interests need community
consent, and faith needs faith consent plus a user-stated source.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.personalization.vocabulary import (
    ENTITY_SPECS,
    FAITH_ATTRIBUTES,
    UserEntityType,
)

E = UserEntityType

DOCUMENT_KIND_PHRASES = {
    "passport": "your passport",
    "marriage_certificate": "your marriage certificate",
    "employment_letter": "your employment letter",
    "business_document": "your business document",
    "tenancy_document": "your tenancy document",
    "identity_document": "your identity document",
    "miscellaneous": "a document you uploaded",
}


@dataclass(frozen=True, slots=True)
class NodeView:
    id: UUID
    type: UserEntityType
    key: str
    label: str
    parent_id: UUID | None
    position: int = 0  # creation order among siblings of the same type


@dataclass(frozen=True, slots=True)
class FactView:
    id: UUID
    node_id: UUID
    attribute: str
    value: Any
    source: str  # user_stated | document_extracted | inferred | system
    confidence: float
    confirmed_by_user: bool
    status: str  # accepted | needs_review
    corrected: bool = False
    source_document_id: UUID | None = None
    source_document_kind: str | None = None
    source_ref: str | None = None
    extraction_method: str | None = None


@dataclass(slots=True)
class GraphSnapshot:
    nodes: dict[UUID, NodeView]
    facts: list[FactView]
    # governance keys each user node is an `instance_of` (e.g. 'document.passport')
    instance_of: dict[UUID, list[str]] = field(default_factory=dict)
    faith_consent: bool = False
    community_consent: bool = False

    def accepted(self, node_id: UUID) -> dict[str, FactView]:
        return {
            f.attribute: f for f in self.facts if f.node_id == node_id and f.status == "accepted"
        }

    def children_of(self, node_id: UUID | None, entity_type: UserEntityType) -> list[NodeView]:
        found = [n for n in self.nodes.values() if n.parent_id == node_id and n.type is entity_type]
        return sorted(found, key=lambda n: n.position)

    def hub(self) -> NodeView | None:
        return next((n for n in self.nodes.values() if n.type is E.PERSON), None)


@dataclass(slots=True)
class PlanningFact:
    key: str
    value: Any
    label: str
    source: str
    confidence: float
    confirmed: bool
    fact_ids: list[UUID]


@dataclass(slots=True)
class FactEvidence:
    fact_id: UUID
    entity_type: str | None = None
    entity_label: str | None = None
    attribute: str | None = None
    attribute_label: str | None = None
    value_display: str | None = None
    origin: str = "No longer in your twin"
    source: str | None = None
    source_document_id: UUID | None = None
    confirmed_by_user: bool = False
    removed: bool = True

    @property
    def statement(self) -> str:
        if self.removed:
            return "A detail you have since removed"
        return f"{self.entity_label} · {self.attribute_label}: {self.origin.lower()}"


_SOURCE_RANK = {"inferred": 0, "document_extracted": 1, "system": 2, "user_stated": 3}
_LABELS = {
    "person.age": "Age",
    "person.occupation": "Occupation",
    "finance.monthly_income_aed": "Monthly income (AED)",
    "housing.accommodation_provided": "Accommodation provided by employer",
    "household.move_with_spouse": "Moving with a spouse",
    "household.children_count": "Children moving with you",
    "household.planned_arrival_date": "Planned arrival",
    "nationality": "Nationality",
    "passport.expiry_date": "Passport expiry",
    "company.jurisdiction": "Company jurisdiction",
    "company.stage": "Company stage",
    "company.activities": "Business activities",
    "goals": "Goals",
    "housing.preferred_area": "Preferred housing area",
    "languages": "Languages",
    "community.interests": "Community interests",
    "community.faith": "Faith community",
    "meets.home_country_attestation": "Attested by the issuing country",
}


def fact_key_label(key: str) -> str:
    base = key.split(".", 1)[1] if key.split(".", 1)[0].startswith(("spouse", "child")) else key
    if base.startswith("documents."):
        return "Holds " + base.removeprefix("documents.").replace("_", " ")
    return _LABELS.get(base, base.replace(".", " ").replace("_", " ").capitalize())


def _combine(
    key: str, value: Any, facts: Sequence[FactView], *, inferred: bool = False
) -> PlanningFact:
    sources = [f.source for f in facts]
    source = "inferred" if inferred else min(sources, key=lambda s: _SOURCE_RANK.get(s, 0))
    return PlanningFact(
        key=key,
        value=value,
        label=fact_key_label(key),
        source=source,
        confidence=round(
            min((f.confidence for f in facts), default=1.0) * (0.8 if inferred else 1), 3
        ),
        confirmed=bool(facts) and not inferred and all(f.confirmed_by_user for f in facts),
        fact_ids=[f.id for f in facts],
    )


def _age(dob: Any, today: date) -> int | None:
    try:
        born = date.fromisoformat(str(dob))
    except ValueError:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _member_facts(
    snap: GraphSnapshot, member: NodeView, prefix: str, today: date
) -> list[PlanningFact]:
    out: list[PlanningFact] = []
    own = snap.accepted(member.id)
    if (dob := own.get("date_of_birth")) is not None and (
        age := _age(dob.value, today)
    ) is not None:
        out.append(_combine(f"{prefix}person.age", age, [dob]))
    nationalities = [
        f
        for n in snap.children_of(member.id, E.NATIONALITY)
        if (f := snap.accepted(n.id).get("country")) is not None
    ]
    if nationalities:
        out.append(
            _combine(f"{prefix}nationality", [f.value for f in nationalities], nationalities)
        )
    expiries = [
        f
        for n in snap.children_of(member.id, E.PASSPORT)
        if (f := snap.accepted(n.id).get("expiry_date")) is not None
    ]
    if expiries:
        soonest = min(expiries, key=lambda f: str(f.value))
        out.append(_combine(f"{prefix}passport.expiry_date", soonest.value, [soonest]))
    for doc_type in (E.PASSPORT, E.DOCUMENT):
        for node in snap.children_of(member.id, doc_type):
            facts = list(snap.accepted(node.id).values())
            if not facts:
                continue
            for gov_key in snap.instance_of.get(node.id, []):
                key = f"{prefix}documents.{gov_key.removeprefix('document.')}"
                if all(p.key != key for p in out):
                    out.append(_combine(key, True, facts))
    return out


def _home_attestation(snap: GraphSnapshot, hub: NodeView) -> list[PlanningFact]:
    """`meets.home_country_attestation` from a marriage certificate that already carries
    the issuing country's foreign-ministry attestation.

    The governance requirement is one step of the chain for every foreign document the
    household needs. Without children the marriage certificate is the only one, so its
    stamp meets it; with children their birth certificates need the same step, which no
    document tells ADAPT about, so nothing is projected."""
    for node in snap.children_of(hub.id, E.DOCUMENT):
        facts = snap.accepted(node.id)
        kind, home = facts.get("document_kind"), facts.get("home_attested")
        if (
            kind is not None
            and kind.value == "marriage_certificate"
            and home is not None
            and home.value is True
        ):
            return [_combine("meets.home_country_attestation", True, [kind, home])]
    return []


# Never an input to a government requirement: community interests can hint at special-
# category data, and faith is special-category data. `for_requirements` drops them.
NOT_FOR_REQUIREMENTS_PREFIXES = ("community.",)


def _base_key(key: str) -> str:
    head, _, rest = key.partition(".")
    return rest if head == "spouse" or (head.startswith("child") and head[5:].isdigit()) else key


def planning_facts(
    snap: GraphSnapshot,
    keys: Iterable[str] | None = None,
    *,
    today: date | None = None,
    for_requirements: bool = False,
) -> list[PlanningFact]:
    today = today or date.today()
    hub = snap.hub()
    if hub is None:
        return []
    me = snap.accepted(hub.id)
    out = _member_facts(snap, hub, "", today)

    if (occupation := me.get("occupation") or me.get("job_title")) is not None:
        out.append(_combine("person.occupation", occupation.value, [occupation]))
    income = me.get("monthly_income")
    if (
        income is not None
        and isinstance(income.value, dict)
        and income.value.get("currency") == "AED"
    ):
        out.append(_combine("finance.monthly_income_aed", income.value.get("amount"), [income]))
    if (housing := me.get("employer_provides_accommodation")) is not None:
        out.append(_combine("housing.accommodation_provided", housing.value, [housing]))

    household = next(iter(snap.children_of(hub.id, E.HOUSEHOLD)), None)
    hh = snap.accepted(household.id) if household else {}
    if (arrival := hh.get("planned_arrival_date")) is not None:
        out.append(_combine("household.planned_arrival_date", arrival.value, [arrival]))

    spouse = next(iter(snap.children_of(hub.id, E.SPOUSE)), None)
    spouse_facts = snap.accepted(spouse.id) if spouse else {}
    if spouse is not None and spouse_facts:
        stated = spouse_facts.get("moving_with_user") or hh.get("moving_together")
        if stated is not None:
            out.append(_combine("household.move_with_spouse", stated.value, [stated]))
        else:
            # A spouse is in the twin and nobody said they're staying behind. Assume they
            # are moving, but mark it inferred so the plan asks to confirm it.
            basis = sorted(spouse_facts.values(), key=lambda f: f.attribute)
            out.append(_combine("household.move_with_spouse", True, basis, inferred=True))
        out += _member_facts(snap, spouse, "spouse.", today)

    children = [c for c in snap.children_of(hub.id, E.CHILD) if snap.accepted(c.id)]
    moving = [c for c in children if snap.accepted(c.id).get("moving_with_user") is None
              or snap.accepted(c.id)["moving_with_user"].value is not False]  # fmt: skip
    if children:
        basis = [next(iter(snap.accepted(c.id).values())) for c in moving]
        out.append(_combine("household.children_count", len(moving), basis))
    for index, child in enumerate(children, start=1):
        out += _member_facts(snap, child, f"child{index}.", today)
    if not children:
        out += _home_attestation(snap, hub)

    companies = snap.children_of(hub.id, E.COMPANY)
    for company in companies[:1]:  # the primary venture drives the plan
        cf = snap.accepted(company.id)
        jurisdiction = cf.get("jurisdiction")
        if jurisdiction is not None and jurisdiction.value in ("mainland", "adgm"):
            out.append(_combine("company.jurisdiction", jurisdiction.value, [jurisdiction]))
        if (stage := cf.get("stage")) is not None:
            out.append(_combine("company.stage", stage.value, [stage]))
        activities = [
            f
            for n in snap.children_of(company.id, E.BUSINESS_ACTIVITY)
            if (f := snap.accepted(n.id).get("description")) is not None
        ]
        if activities:
            out.append(_combine("company.activities", [f.value for f in activities], activities))

    goals = [f for n in snap.children_of(hub.id, E.GOAL) if (f := snap.accepted(n.id).get("kind"))]
    if goals:
        out.append(_combine("goals", [f.value for f in goals], goals))

    for pref in snap.children_of(hub.id, E.HOUSING_PREFERENCE):
        if (area := snap.accepted(pref.id).get("preferred_area")) is not None:
            out.append(_combine("housing.preferred_area", area.value, [area]))

    languages = [
        f
        for n in snap.children_of(hub.id, E.LANGUAGE)
        if (f := snap.accepted(n.id).get("language")) is not None
    ]
    if languages:
        out.append(_combine("languages", [f.value for f in languages], languages))

    communities = snap.children_of(hub.id, E.COMMUNITY_PREFERENCE)
    if snap.community_consent:
        interests = [
            f for n in communities if (f := snap.accepted(n.id).get("interest")) is not None
        ]
        if interests:
            out.append(_combine("community.interests", [f.value for f in interests], interests))
    if snap.faith_consent:
        faith = [
            f
            for n in communities
            for name in FAITH_ATTRIBUTES
            if (f := snap.accepted(n.id).get(name)) is not None and f.source == "user_stated"
        ]
        if faith:
            out.append(_combine("community.faith", faith[0].value, faith[:1]))

    if for_requirements:
        out = [p for p in out if not _base_key(p.key).startswith(NOT_FOR_REQUIREMENTS_PREFIXES)]
    if keys is not None:
        wanted = set(keys)
        out = [p for p in out if p.key in wanted]
    return out


def origin(fact: FactView) -> str:
    """Where a fact came from, phrased for people."""
    document = DOCUMENT_KIND_PHRASES.get(fact.source_document_kind or "", "a document you uploaded")
    if fact.corrected:
        return f"Corrected by you (originally read from {document})"
    if fact.source == "document_extracted":
        return f"Read from {document}" + ("" if fact.confirmed_by_user else ", not yet confirmed")
    if fact.source == "user_stated":
        return (
            "From your profile"
            if (fact.source_ref or "").startswith("profile:")
            else "You told ADAPT"
        )
    if fact.source == "inferred":
        return "Inferred by ADAPT"
    return "Set by ADAPT"


def evidence(snap: GraphSnapshot, fact_ids: Iterable[UUID]) -> list[FactEvidence]:
    by_id = {f.id: f for f in snap.facts}
    out: list[FactEvidence] = []
    for fact_id in fact_ids:
        fact = by_id.get(fact_id)
        if fact is None:
            out.append(FactEvidence(fact_id=fact_id))
            continue
        node = snap.nodes.get(fact.node_id)
        spec = ENTITY_SPECS[node.type] if node else None
        attribute = spec.attributes.get(fact.attribute) if spec else None
        out.append(
            FactEvidence(
                fact_id=fact.id,
                entity_type=node.type.value if node else None,
                entity_label=spec.label if spec else None,
                attribute=fact.attribute,
                attribute_label=attribute.label if attribute else fact.attribute,
                value_display=attribute.display(fact.value) if attribute else str(fact.value),
                origin=origin(fact),
                source=fact.source,
                source_document_id=fact.source_document_id,
                confirmed_by_user=fact.confirmed_by_user,
                removed=False,
            )
        )
    return out
