"""The user-fact vocabulary the knowledge layer reasons over.

Shared with the journey agent (intake/profile nodes) and the personalization engine, which
map what they learn onto these keys. Three families are pattern-based:

* `documents.<doc>`      bool   the user holds governance document `document.<doc>`
* `completed.<service>`  bool   the user has completed governance service `service.<service>`
* `meets.<requirement>`  bool   the user meets `requirement.<requirement>` (no machine rule)

A missing fact is *unknown*, never false: ADAPT asks rather than assumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FactType = Literal["number", "boolean", "string", "enum"]


@dataclass(frozen=True, slots=True)
class FactKey:
    key: str
    label: str
    type: FactType
    description: str
    values: tuple[str, ...] = ()


FACT_KEYS: dict[str, FactKey] = {
    f.key: f
    for f in (
        FactKey(
            "finance.monthly_income_aed",
            "Monthly income (AED)",
            "number",
            "The sponsoring resident's monthly salary or income in dirhams.",
        ),
        FactKey(
            "housing.accommodation_provided",
            "Accommodation provided by employer",
            "boolean",
            "Whether the sponsor's employer provides their accommodation.",
        ),
        FactKey(
            "company.jurisdiction",
            "Company jurisdiction",
            "enum",
            "Where the founder's company is (or will be) licensed.",
            ("mainland", "adgm"),
        ),
        FactKey(
            "household.move_with_spouse",
            "Moving with a spouse",
            "boolean",
            "Whether the user's spouse is relocating with them.",
        ),
        FactKey(
            "company.legal_form",
            "Company legal form",
            "enum",
            "The legal form of the founder's company.",
            (
                "llc",
                "sole_establishment",
                "limited_partnership",
                "pjsc",
                "prjsc",
                "branch",
                "other",
            ),
        ),
        FactKey(
            "company.has_resident_signatory",
            "Resident authorised signatory",
            "boolean",
            "Whether at least one authorised signatory is a GCC national or holds a UAE "
            "residence visa.",
        ),
        FactKey(
            "company.investment_aed",
            "Investment in the company (AED)",
            "number",
            "The founder's cash contribution to the company's capital, in dirhams.",
        ),
        FactKey(
            "person.age",
            "Age",
            "number",
            "Age in years. Prefixed for household members, e.g. 'spouse.person.age'.",
        ),
        FactKey(
            "person.relationship_to_sponsor",
            "Relationship to the sponsor",
            "enum",
            "How a sponsored household member relates to the sponsor.",
            ("spouse", "son", "daughter", "parent", "other"),
        ),
        FactKey(
            "person.married",
            "Married",
            "boolean",
            "Marital status of a sponsored child.",
        ),
        FactKey(
            "person.special_needs",
            "Person of determination",
            "boolean",
            "Whether a sponsored child has special needs.",
        ),
        FactKey(
            "driving.licence_exchangeable",
            "Licence eligible for exchange",
            "boolean",
            "Whether the user's foreign driving licence is valid and from a country whose "
            "licences can be exchanged (confirmed on the official channel).",
        ),
    )
}

PATTERN_PREFIXES: dict[str, str] = {
    "documents.": "document.",
    "completed.": "service.",
    "meets.": "requirement.",
}


def document_fact(document_key: str) -> str:
    """`document.passport` -> `documents.passport`."""
    return "documents." + document_key.removeprefix("document.")


def completed_fact(service_key: str) -> str:
    """`service.tawtheeq` -> `completed.tawtheeq`."""
    return "completed." + service_key.removeprefix("service.")


def meets_fact(requirement_key: str) -> str:
    """`requirement.registered_premises` -> `meets.registered_premises`."""
    return "meets." + requirement_key.removeprefix("requirement.")


def fact_label(key: str) -> str | None:
    known = FACT_KEYS.get(key)
    return known.label if known else None
