"""Vocabulary of the private user graph (the user's digital twin).

The user graph is separate from the shared governance graph. It holds *entities*
(`graph_nodes` with graph_type='user') connected by *relations* (`graph_edges`), and every
personal detail is a *fact* (`extracted_facts`) attached to exactly one entity, with its
own provenance: value, confidence, source, source document and extraction method.

Rules this module defines:

* **Closed vocabulary.** Each entity type has a fixed set of attributes. That keeps the
  twin minimal (nothing is stored "just in case") and makes it impossible to paste public
  governance content into a person's graph as if it were a personal fact.
* **Structure follows facts.** An entity exists because at least one fact supports it.
  Adding the first fact about a spouse creates the spouse entity and its canonical edge
  from the user; removing the last fact removes the entity. The hub `person.self`
  always exists.
* **Stable, PII-free keys.** Keys are derived deterministically (for idempotent upserts)
  and never contain names or document numbers, because keys may appear in logs and events.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.personalization.values import Normalized, ValueKind, display, normalize


class UserEntityType(StrEnum):
    """Entity types of the user graph (`graph_nodes.entity_type` where graph_type='user')."""

    PERSON = "person"
    HOUSEHOLD = "household"
    SPOUSE = "spouse"
    CHILD = "child"
    PASSPORT = "passport"
    VISA = "visa"
    NATIONALITY = "nationality"
    COMPANY = "company"
    BUSINESS_ACTIVITY = "business_activity"
    GOAL = "goal"
    HOUSING_PREFERENCE = "housing_preference"
    BUDGET = "budget"
    LANGUAGE = "language"
    PREFERENCE = "preference"
    DOCUMENT = "document"
    APPOINTMENT = "appointment"
    COMMUNITY_PREFERENCE = "community_preference"


class UserRelation(StrEnum):
    """User -> user relations (`graph_edges.relation` where graph_type='user')."""

    HAS_HOUSEHOLD_MEMBER = "has_household_member"
    MEMBER_OF = "member_of"
    HAS_DOCUMENT = "has_document"
    HOLDS_VISA = "holds_visa"
    HAS_NATIONALITY = "has_nationality"
    HAS_GOAL = "has_goal"
    PREFERS = "prefers"
    SEEKS = "seeks"
    FOUNDER_OF = "founder_of"
    ENGAGES_IN = "engages_in"
    SPEAKS = "speaks"
    HAS_BUDGET = "has_budget"
    HAS_APPOINTMENT = "has_appointment"


class Cardinality(StrEnum):
    HUB = "hub"  # exactly one per user: the user themself
    ONE = "one"  # at most one per parent (e.g. a spouse, a household)
    MANY = "many"  # any number per parent (children, goals, nationalities ...)


HUB_KEY = "person.self"


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    name: str
    label: str
    kind: ValueKind
    choices: tuple[tuple[str, str], ...] = ()  # (value, label)
    # Sensitive attributes may only be stated by the user, after explicit opt-in.
    sensitive: bool = False

    @property
    def choice_values(self) -> tuple[str, ...]:
        return tuple(value for value, _ in self.choices)

    def normalize(self, raw: Any) -> Normalized:
        return normalize(self.kind, raw, choices=self.choice_values)

    def display(self, value: Any) -> str:
        return display(self.kind, value, choice_labels=dict(self.choices))


@dataclass(frozen=True, slots=True)
class EntitySpec:
    type: UserEntityType
    label: str
    cardinality: Cardinality
    relation: UserRelation | None  # edge from the parent to this entity
    parents: tuple[UserEntityType, ...]  # allowed parent types; the first is the default
    attributes: dict[str, AttributeSpec]
    # For MANY entities: the attribute that tells two siblings apart (e.g. a nationality's
    # country). Facts about the same identity value land on the same entity.
    identity: str | None = None
    # Attributes used to label the entity, first present wins; `label_format` wraps it.
    label_from: tuple[str, ...] = ()
    label_format: str = "{value}"
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def attribute(self, name: str) -> AttributeSpec:
        try:
            return self.attributes[name]
        except KeyError:
            raise FactRuleError(
                f"'{name}' is not something ADAPT records about a {self.label.lower()}",
                code="unknown_attribute",
            ) from None


class FactRuleError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_fact") -> None:
        super().__init__(message)
        self.code = code


def _attrs(*specs: AttributeSpec) -> dict[str, AttributeSpec]:
    return {spec.name: spec for spec in specs}


def _choices(*pairs: str) -> tuple[tuple[str, str], ...]:
    """_choices("mainland", "Mainland", "adgm", "ADGM") -> (("mainland", "Mainland"), ...)."""
    return tuple(zip(pairs[::2], pairs[1::2], strict=True))


T = ValueKind
E = UserEntityType
R = UserRelation
_MEMBERS = (E.PERSON, E.SPOUSE, E.CHILD)  # entities that can hold documents, visas ...

DOCUMENT_KIND_CHOICES = _choices(
    "passport", "Passport",
    "marriage_certificate", "Marriage certificate",
    "employment_letter", "Employment letter",
    "business_document", "Business document",
    "tenancy_document", "Tenancy document",
    "identity_document", "Identity document",
    "miscellaneous", "Other document",
)  # fmt: skip

ENTITY_SPECS: dict[UserEntityType, EntitySpec] = {
    spec.type: spec
    for spec in (
        EntitySpec(
            E.PERSON,
            "You",
            Cardinality.HUB,
            None,
            (),
            _attrs(
                AttributeSpec("full_name", "Full name", T.TEXT),
                AttributeSpec("date_of_birth", "Date of birth", T.DATE),
                AttributeSpec("occupation", "Occupation", T.TEXT),
                AttributeSpec("employer", "Employer", T.TEXT),
                AttributeSpec("job_title", "Job title", T.TEXT),
                AttributeSpec("monthly_income", "Monthly income", T.MONEY),
                AttributeSpec("employment_start_date", "Employment start date", T.DATE),
                AttributeSpec(
                    "employer_provides_accommodation", "Employer provides housing", T.BOOLEAN
                ),
                AttributeSpec("current_country", "Currently living in", T.COUNTRY),
            ),
            description="The person this twin belongs to.",
        ),
        EntitySpec(
            E.HOUSEHOLD,
            "Household",
            Cardinality.ONE,
            R.MEMBER_OF,
            (E.PERSON,),
            _attrs(
                AttributeSpec("moving_together", "Moving together", T.BOOLEAN),
                AttributeSpec("planned_arrival_date", "Planned arrival", T.DATE),
                AttributeSpec("size", "People in the household", T.INTEGER),
            ),
        ),
        EntitySpec(
            E.SPOUSE,
            "Spouse",
            Cardinality.ONE,
            R.HAS_HOUSEHOLD_MEMBER,
            (E.PERSON,),
            _attrs(
                AttributeSpec("full_name", "Full name", T.TEXT),
                AttributeSpec("date_of_birth", "Date of birth", T.DATE),
                AttributeSpec("married_on", "Date of marriage", T.DATE),
                AttributeSpec("marriage_country", "Country of marriage", T.COUNTRY),
                AttributeSpec("moving_with_user", "Moving with you", T.BOOLEAN),
                AttributeSpec("occupation", "Occupation", T.TEXT),
            ),
            label_from=("full_name",),
        ),
        EntitySpec(
            E.CHILD,
            "Child",
            Cardinality.MANY,
            R.HAS_HOUSEHOLD_MEMBER,
            (E.PERSON,),
            _attrs(
                AttributeSpec("full_name", "Full name", T.TEXT),
                AttributeSpec("date_of_birth", "Date of birth", T.DATE),
                AttributeSpec("moving_with_user", "Moving with you", T.BOOLEAN),
            ),
            identity="full_name",
            label_from=("full_name",),
        ),
        EntitySpec(
            E.PASSPORT,
            "Passport",
            Cardinality.MANY,
            R.HAS_DOCUMENT,
            _MEMBERS,
            _attrs(
                AttributeSpec("issuing_country", "Issuing country", T.COUNTRY),
                AttributeSpec("expiry_date", "Expiry date", T.DATE),
            ),
            identity="issuing_country",
            label_from=("issuing_country",),
            label_format="Passport · {value}",
            description="Only the minimum needed to plan: who issued it and when it expires.",
        ),
        EntitySpec(
            E.VISA,
            "Visa",
            Cardinality.MANY,
            R.HOLDS_VISA,
            _MEMBERS,
            _attrs(
                AttributeSpec(
                    "visa_type",
                    "Visa type",
                    T.CHOICE,
                    _choices(
                        "visit",
                        "Visit",
                        "employment",
                        "Employment",
                        "investor",
                        "Investor",
                        "family",
                        "Family",
                        "golden",
                        "Golden",
                        "student",
                        "Student",
                        "remote_work",
                        "Remote work",
                        "other",
                        "Other",
                    ),
                ),
                AttributeSpec("country", "Country", T.COUNTRY),
                AttributeSpec(
                    "status",
                    "Status",
                    T.CHOICE,
                    _choices(
                        "held",
                        "Held",
                        "applying",
                        "Applying",
                        "planned",
                        "Planned",
                        "expired",
                        "Expired",
                    ),
                ),
                AttributeSpec("expiry_date", "Expiry date", T.DATE),
            ),
            identity="visa_type",
            label_from=("visa_type",),
            label_format="{value} visa",
        ),
        EntitySpec(
            E.NATIONALITY,
            "Nationality",
            Cardinality.MANY,
            R.HAS_NATIONALITY,
            _MEMBERS,
            _attrs(AttributeSpec("country", "Country", T.COUNTRY)),
            identity="country",
            label_from=("country",),
        ),
        EntitySpec(
            E.COMPANY,
            "Company",
            Cardinality.MANY,
            R.FOUNDER_OF,
            (E.PERSON,),
            _attrs(
                AttributeSpec("name", "Company name", T.TEXT),
                AttributeSpec(
                    "jurisdiction",
                    "Jurisdiction",
                    T.CHOICE,
                    _choices(
                        "mainland",
                        "Abu Dhabi mainland",
                        "adgm",
                        "ADGM (free zone)",
                        "free_zone",
                        "Another free zone",
                        "undecided",
                        "Not decided yet",
                    ),
                ),
                AttributeSpec("legal_form", "Legal form", T.TEXT),
                AttributeSpec(
                    "stage",
                    "Stage",
                    T.CHOICE,
                    _choices(
                        "idea",
                        "Idea",
                        "registering",
                        "Registering",
                        "registered",
                        "Registered",
                        "operating",
                        "Operating",
                    ),
                ),
                AttributeSpec("registration_authority", "Registration authority", T.TEXT),
            ),
            identity="name",
            label_from=("name",),
        ),
        EntitySpec(
            E.BUSINESS_ACTIVITY,
            "Business activity",
            Cardinality.MANY,
            R.ENGAGES_IN,
            (E.COMPANY,),
            _attrs(AttributeSpec("description", "Activity", T.TEXT)),
            identity="description",
            label_from=("description",),
        ),
        EntitySpec(
            E.GOAL,
            "Goal",
            Cardinality.MANY,
            R.HAS_GOAL,
            (E.PERSON,),
            _attrs(
                AttributeSpec(
                    "kind",
                    "Goal",
                    T.CHOICE,
                    _choices(
                        "relocate",
                        "Move to Abu Dhabi",
                        "start_company",
                        "Start a company",
                        "sponsor_family",
                        "Sponsor my family",
                        "find_housing",
                        "Find a home",
                        "find_school",
                        "Find a school",
                        "find_community",
                        "Find my community",
                        "find_job",
                        "Find a job",
                        "other",
                        "Something else",
                    ),
                ),
                AttributeSpec("description", "In your words", T.TEXT),
                AttributeSpec("target_date", "Target date", T.DATE),
                AttributeSpec(
                    "priority",
                    "Priority",
                    T.CHOICE,
                    _choices("high", "High", "medium", "Medium", "low", "Low"),
                ),
            ),
            identity="kind",
            label_from=("kind", "description"),
        ),
        EntitySpec(
            E.HOUSING_PREFERENCE,
            "Housing",
            Cardinality.ONE,
            R.PREFERS,
            (E.PERSON,),
            _attrs(
                AttributeSpec("preferred_area", "Preferred area", T.TEXT),
                AttributeSpec(
                    "property_type",
                    "Property type",
                    T.CHOICE,
                    _choices(
                        "apartment",
                        "Apartment",
                        "villa",
                        "Villa",
                        "townhouse",
                        "Townhouse",
                        "any",
                        "Any",
                    ),
                ),
                AttributeSpec("bedrooms", "Bedrooms", T.INTEGER),
                AttributeSpec(
                    "tenure", "Rent or buy", T.CHOICE, _choices("rent", "Rent", "buy", "Buy")
                ),
                AttributeSpec("move_in_date", "Move-in date", T.DATE),
            ),
            label_from=("preferred_area",),
            label_format="Housing in {value}",
        ),
        EntitySpec(
            E.BUDGET,
            "Budget",
            Cardinality.MANY,
            R.HAS_BUDGET,
            (E.PERSON,),
            _attrs(
                AttributeSpec(
                    "category",
                    "Budget for",
                    T.CHOICE,
                    _choices(
                        "housing",
                        "Housing",
                        "relocation",
                        "Relocation",
                        "schooling",
                        "Schooling",
                        "business_setup",
                        "Business setup",
                        "living",
                        "Living costs",
                    ),
                ),
                AttributeSpec("amount", "Amount", T.MONEY),
                AttributeSpec(
                    "period",
                    "Period",
                    T.CHOICE,
                    _choices("one_off", "One-off", "monthly", "Monthly", "yearly", "Yearly"),
                ),
            ),
            identity="category",
            label_from=("category",),
            label_format="{value} budget",
        ),
        EntitySpec(
            E.LANGUAGE,
            "Language",
            Cardinality.MANY,
            R.SPEAKS,
            _MEMBERS,
            _attrs(
                AttributeSpec("language", "Language", T.LANGUAGE),
                AttributeSpec(
                    "proficiency",
                    "Proficiency",
                    T.CHOICE,
                    _choices(
                        "native",
                        "Native",
                        "fluent",
                        "Fluent",
                        "conversational",
                        "Conversational",
                        "basic",
                        "Basic",
                    ),
                ),
            ),
            identity="language",
            label_from=("language",),
        ),
        EntitySpec(
            E.PREFERENCE,
            "Preference",
            Cardinality.MANY,
            R.PREFERS,
            (E.PERSON,),
            _attrs(
                AttributeSpec("topic", "About", T.TEXT),
                AttributeSpec("value", "Preference", T.TEXT),
            ),
            identity="topic",
            label_from=("topic",),
        ),
        EntitySpec(
            E.DOCUMENT,
            "Document",
            Cardinality.MANY,
            R.HAS_DOCUMENT,
            _MEMBERS,
            _attrs(
                AttributeSpec("document_kind", "Document type", T.CHOICE, DOCUMENT_KIND_CHOICES),
                AttributeSpec("title", "Title", T.TEXT),
                AttributeSpec("issuer", "Issued by", T.TEXT),
                AttributeSpec("issuing_country", "Issuing country", T.COUNTRY),
                AttributeSpec("issue_date", "Issue date", T.DATE),
                AttributeSpec("expiry_date", "Expiry date", T.DATE),
                AttributeSpec("attested", "UAE attestation", T.BOOLEAN),
                AttributeSpec("home_attested", "Home-country attestation", T.BOOLEAN),
                AttributeSpec("registered", "Officially registered", T.BOOLEAN),
                AttributeSpec("property_area", "Property area", T.TEXT),
                AttributeSpec("property_city", "City", T.TEXT),
                AttributeSpec("tenancy_start", "Tenancy start", T.DATE),
                AttributeSpec("tenancy_end", "Tenancy end", T.DATE),
                AttributeSpec("annual_rent", "Annual rent", T.MONEY),
            ),
            label_from=("title", "document_kind"),
            description="An uploaded document. The file itself stays encrypted in storage.",
        ),
        EntitySpec(
            E.APPOINTMENT,
            "Appointment",
            Cardinality.MANY,
            R.HAS_APPOINTMENT,
            (E.PERSON,),
            _attrs(
                AttributeSpec("title", "What for", T.TEXT),
                AttributeSpec("scheduled_for", "When", T.DATETIME),
                AttributeSpec("location", "Where", T.TEXT),
                AttributeSpec(
                    "status",
                    "Status",
                    T.CHOICE,
                    _choices(
                        "planned",
                        "Planned",
                        "booked",
                        "Booked",
                        "completed",
                        "Completed",
                        "cancelled",
                        "Cancelled",
                    ),
                ),
            ),
            label_from=("title",),
        ),
        EntitySpec(
            E.COMMUNITY_PREFERENCE,
            "Community",
            Cardinality.MANY,
            R.SEEKS,
            (E.PERSON,),
            _attrs(
                AttributeSpec("interest", "Interested in", T.TEXT),
                AttributeSpec("language", "In language", T.LANGUAGE),
                # Special-category data: user-stated only, after faith opt-in.
                AttributeSpec("faith_community", "Faith community", T.TEXT, sensitive=True),
            ),
            identity="interest",
            label_from=("interest",),
        ),
    )
}

FAITH_ATTRIBUTES = frozenset({"faith_community"})


def spec_for(entity_type: str) -> EntitySpec:
    try:
        return ENTITY_SPECS[UserEntityType(entity_type)]
    except ValueError:
        raise FactRuleError(f"Unknown entity type '{entity_type}'", code="unknown_entity") from None


def _digest(*parts: str, length: int = 12) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:length]


def identity_token(value: Any) -> str:
    """Comparison form of an identity value (case/space-insensitive for text)."""
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return repr(value)


def entity_key(
    entity_type: UserEntityType, *, parent_key: str | None, instance: str | None
) -> str | None:
    """Deterministic, PII-free node key, or None when a fresh random key is needed.

    * hub:  `person.self`
    * ONE:  `<type>.self` under the hub, `<type>.<hash(parent)>` elsewhere
    * MANY: `<type>.<hash(parent, instance)>` when an instance is known
    """
    spec = ENTITY_SPECS[entity_type]
    if spec.cardinality is Cardinality.HUB:
        return HUB_KEY
    parent = parent_key or HUB_KEY
    if spec.cardinality is Cardinality.ONE:
        return (
            f"{entity_type.value}.self" if parent == HUB_KEY else f"{entity_type}.{_digest(parent)}"
        )
    if instance is None:
        return None
    return f"{entity_type.value}.{_digest(parent, instance)}"


def entity_label(spec: EntitySpec, facts: dict[str, Any]) -> str:
    """Label from the entity's (accepted) facts, e.g. 'Passport · India'."""
    for name in spec.label_from:
        if name in facts and facts[name] not in (None, ""):
            text = spec.attributes[name].display(facts[name])
            label = spec.label_format.format(value=text)
            return label[:300]
    return spec.label


def check_parent(spec: EntitySpec, parent_type: UserEntityType | None) -> None:
    if spec.cardinality is Cardinality.HUB:
        return
    if parent_type not in spec.parents:
        allowed = ", ".join(p.value for p in spec.parents)
        raise FactRuleError(
            f"A {spec.label.lower()} belongs to one of: {allowed}", code="invalid_parent"
        )
