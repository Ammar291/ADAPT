"""User-fact helpers and the canonical fact keys the journey agent reads.

One vocabulary is shared with document intelligence (planning_facts) and the knowledge
layer (FACT_KEYS in app/knowledge/facts.py):

* unprefixed keys describe the user; household members use a subject prefix
  (`spouse.documents.passport`, `child1.documents.passport`);
* `documents.<doc>` is true when the user holds governance document `document.<doc>`,
  false only when they said they don't, absent when unknown;
* `completed.<service>` is true when the user reported governance service
  `service.<service>` done.
"""

from __future__ import annotations

from typing import Any

from app.agents.journey.state import FactOrigin, UserFact
from app.agents.journey.vocab import Subject

# Goals the planner understands (a subset of domain GoalType values).
GOAL_ESTABLISH_COMPANY = "establish_company"
GOAL_RESIDENCY = "residency"
GOAL_SPONSOR_FAMILY = "sponsor_family"
GOAL_FIND_HOUSING = "find_housing"

K_GOALS = "goals"
K_IS_FOUNDER = "profile.is_founder"
K_HAS_SPOUSE = "household.has_spouse"
K_MOVE_WITH_SPOUSE = "household.move_with_spouse"
K_SPOUSE_RELOCATION = "household.spouse_relocation"  # with_user | later | ...
K_CHILDREN = "household.children_count"
K_JURISDICTION = "company.jurisdiction"  # mainland | adgm
K_INCOME = "finance.monthly_income_aed"
K_ACCOMMODATION = "housing.accommodation_provided"
K_ARRIVAL = "household.planned_arrival_date"
K_ARRIVAL_TEXT = "move.arrival_timing"  # verbatim phrase, e.g. "next month"


def fact(
    key: str,
    value: Any,
    source: FactOrigin,
    *,
    source_ref: str | None = None,
    confidence: float = 1.0,
    confirmed: bool = False,
    fact_ids: list[str] | None = None,
) -> UserFact:
    return UserFact(
        key=key,
        value=value,
        source=source,
        source_ref=source_ref,
        confidence=confidence,
        confirmed=confirmed,
        fact_ids=list(fact_ids or []),
    )


def value_of(facts: dict[str, UserFact], key: str, default: Any = None) -> Any:
    item = facts.get(key)
    return default if item is None or item["value"] is None else item["value"]


def known(facts: dict[str, UserFact], key: str) -> bool:
    item = facts.get(key)
    return item is not None and item["value"] is not None and item["source"] != "assumed"


def subject_key(subject: str, key: str) -> str:
    """`documents.passport` for the user, `spouse.documents.passport` for the spouse."""
    return key if subject == Subject.SELF else f"{subject}.{key}"


def suffix(governance_key: str) -> str:
    """`document.passport` -> `passport`; `service.tawtheeq` -> `tawtheeq`."""
    return governance_key.split(".", 1)[1] if "." in governance_key else governance_key


def document_fact_key(document_key: str, subject: str = Subject.SELF) -> str:
    return subject_key(subject, f"documents.{suffix(document_key)}")


def completed_fact_key(service_key: str, subject: str = Subject.SELF) -> str:
    return subject_key(subject, f"completed.{suffix(service_key)}")


def fact_ids_for(facts: dict[str, UserFact], keys: list[str]) -> list[str]:
    ids: list[str] = []
    for key in keys:
        item = facts.get(key)
        for fact_id in item["fact_ids"] if item else []:
            if fact_id not in ids:
                ids.append(fact_id)
    return ids


def goals_of(facts: dict[str, UserFact]) -> list[str]:
    """Effective goals. Derived on read (never stored), so what-if changes propagate."""
    stated = value_of(facts, K_GOALS, []) or []
    goals = [g for g in stated if isinstance(g, str)]
    if value_of(facts, K_IS_FOUNDER) is True and GOAL_ESTABLISH_COMPANY not in goals:
        goals.append(GOAL_ESTABLISH_COMPANY)
    moving_with_spouse = value_of(facts, K_MOVE_WITH_SPOUSE)
    if moving_with_spouse is True and GOAL_SPONSOR_FAMILY not in goals:
        goals.append(GOAL_SPONSOR_FAMILY)
    if moving_with_spouse is False and GOAL_SPONSOR_FAMILY in goals:
        goals.remove(GOAL_SPONSOR_FAMILY)
    return goals
