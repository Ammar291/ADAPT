"""Understanding the user's request: a structured extraction, never inference.

The schema has no field for sensitive attributes (faith, ethnicity, health). The model
extracts only what the user said. Live mode uses the LLM with this schema. Demo mode
uses `parse_request`, a deterministic keyword parser registered as the `journey.intake`
demo responder.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.journey.facts import (
    GOAL_ESTABLISH_COMPANY,
    GOAL_FIND_HOUSING,
    GOAL_RESIDENCY,
    GOAL_SPONSOR_FAMILY,
    K_ACCOMMODATION,
    K_ARRIVAL_TEXT,
    K_CHILDREN,
    K_GOALS,
    K_HAS_SPOUSE,
    K_INCOME,
    K_IS_FOUNDER,
    K_JURISDICTION,
    K_MOVE_WITH_SPOUSE,
    K_SPOUSE_RELOCATION,
    fact,
)
from app.agents.journey.state import UserFact

INTAKE_PURPOSE = "journey.intake"
INTAKE_INSTRUCTIONS = (
    "Extract a relocation request to Abu Dhabi into the given schema. Only record what the "
    "user explicitly said; use null when something was not said. Never infer nationality, "
    "religion, ethnicity or health from names, languages or places. Goals: "
    "establish_company (setting up a business), residency (getting a UAE residence visa, "
    "e.g. when moving there), sponsor_family (sponsoring a spouse's visa), find_housing "
    "(finding or renting a home)."
)

Goal = Literal["establish_company", "residency", "sponsor_family", "find_housing"]


class IntakeExtraction(BaseModel):
    goals: list[Goal] = Field(default_factory=list)
    is_founder: bool | None = None
    has_spouse: bool | None = None
    move_with_spouse: bool | None = None
    spouse_relocation: Literal["with_user", "later"] | None = None
    children_count: int | None = Field(default=None, ge=0, le=20)
    company_jurisdiction: Literal["mainland", "adgm"] | None = None
    monthly_income_aed: float | None = Field(default=None, ge=0)
    accommodation_provided: bool | None = None
    arrival_timing: str | None = Field(default=None, max_length=80)


def facts_from_intake(extraction: IntakeExtraction) -> dict[str, UserFact]:
    values: dict[str, object] = {
        K_GOALS: list(dict.fromkeys(extraction.goals)) or None,
        K_IS_FOUNDER: extraction.is_founder,
        K_HAS_SPOUSE: extraction.has_spouse,
        K_MOVE_WITH_SPOUSE: extraction.move_with_spouse,
        K_SPOUSE_RELOCATION: extraction.spouse_relocation,
        K_CHILDREN: extraction.children_count,
        K_JURISDICTION: extraction.company_jurisdiction,
        K_INCOME: extraction.monthly_income_aed,
        K_ACCOMMODATION: extraction.accommodation_provided,
        K_ARRIVAL_TEXT: extraction.arrival_timing,
    }
    return {
        key: fact(key, value, "user_stated", source_ref="request", confidence=0.9)
        for key, value in values.items()
        if value is not None
    }


# --- deterministic demo parser ------------------------------------------------------------

_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a": 1, "an": 1}
_SPOUSE = r"(wife|husband|spouse|partner)"


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def parse_request(text: str) -> IntakeExtraction:
    t = " ".join(text.lower().split())
    goals: list[Goal] = []
    founder = _has(
        t,
        r"\bfounder\b",
        r"\bstart-?up\b",
        r"(set ?up|start|open|launch|register) (my|a|our) (company|business|startup)",
        r"\bmy (company|business)\b",
    )
    if founder or _has(t, r"\b(company|business) (setup|formation|licen[cs]e)\b"):
        goals.append("establish_company")
    moving = _has(t, r"\bmov(e|ing)\b", r"\brelocat", r"\bresiden(cy|ce visa)\b", r"\bvisa\b")
    if moving:
        goals.append("residency")
    has_spouse = _has(t, rf"\bmy {_SPOUSE}\b", rf"\b{_SPOUSE}\b")
    later = _has(
        t, rf"{_SPOUSE} (will )?(join|follow|come)s? (me )?(later|after)", r"\blater\b.*" + _SPOUSE
    )
    together = (
        has_spouse
        and not later
        and _has(
            t,
            rf"with my {_SPOUSE}",
            rf"(bring|bringing|sponsor|sponsoring) (my )?{_SPOUSE}",
            rf"{_SPOUSE} and i",
            r"sponsor (her|his|their) visa",
        )
    )
    sponsor = has_spouse and _has(
        t, r"\bsponsor", r"(her|his|their|spouse'?s?|wife'?s?|husband'?s?) visa"
    )
    if sponsor or together or later:
        goals.append("sponsor_family")
    if _has(t, r"\b(home|house|apartment|flat|villa|rent|lease|housing|accommodation)\b"):
        goals.append("find_housing")

    jurisdiction: Literal["mainland", "adgm"] | None = None
    if _has(t, r"\badgm\b", r"free ?zone", r"abu dhabi global market"):
        jurisdiction = "adgm"
    elif _has(t, r"\bmainland\b", r"\bded\b", r"\badded\b"):
        jurisdiction = "mainland"

    income = None
    match = re.search(
        r"(?:aed|dhs?|dirhams?)\s*([\d,.]+)\s*(k)?|([\d,.]+)\s*(k)?\s*(?:aed|dhs?|dirhams?)", t
    )
    if match and _has(t, r"\b(income|salary|earn|month|monthly|per month)\b"):
        raw = (match.group(1) or match.group(3) or "").replace(",", "")
        try:
            income = float(raw) * (1000 if (match.group(2) or match.group(4)) else 1)
        except ValueError:
            income = None

    children = None
    kids = re.search(
        r"\b(\d+|one|two|three|four|five|a|an)\s+(?:school[- ]age\s+)?"
        r"(child|children|kids?|sons?|daughters?)\b",
        t,
    )
    if kids:
        children = int(kids.group(1)) if kids.group(1).isdigit() else _NUMBERS.get(kids.group(1))

    arrival = None
    when = re.search(
        r"\b(next (week|month|year)|in (\d+|two|three|six) (weeks|months)"
        r"|this (month|summer|year)|in (january|february|march|april|may|june|july|august"
        r"|september|october|november|december))\b",
        t,
    )
    if when:
        arrival = when.group(0)

    return IntakeExtraction(
        goals=list(dict.fromkeys(goals)),
        is_founder=True if founder else None,
        has_spouse=True if has_spouse else None,
        # The spouse relocates (now or later); `spouse_relocation` carries the timing.
        move_with_spouse=True if (together or sponsor or later) else None,
        spouse_relocation="later" if later else ("with_user" if together else None),
        children_count=children,
        company_jurisdiction=jurisdiction,
        monthly_income_aed=income,
        accommodation_provided=True
        if _has(t, r"accommodation (is )?provided", r"housing allowance")
        else None,
        arrival_timing=arrival,
    )


GOAL_TITLES = {
    GOAL_ESTABLISH_COMPANY: "Set up your company",
    GOAL_RESIDENCY: "Get your residence visa",
    GOAL_SPONSOR_FAMILY: "Bring your spouse",
    GOAL_FIND_HOUSING: "Find and register your home",
}
