"""The consent-filtered view of a person that research may use.

Privacy rules (the trust contract for research):

* Research never sees the user's name, so nothing can be inferred from it.
* Language only sets the language results are written in. It is never used to target
  communities.
* Background (home country) and interests are used only with community-personalisation
  consent.
* Faith is used only when the user stated it themselves AND opted in to faith
  personalisation. It is never derived from nationality, background, language or name.
* Without faith opt-in, no faith terms appear in any search query, and faith-specific
  groups and events are filtered out of community results (see `mentions_faith`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ConsentStatus
from app.research.types import RelocationType

MAX_TEXT = 80
MAX_INTERESTS = 8
MAX_INTEREST_LEN = 40
MAX_GOALS = 6
MAX_FOCUS = 200

# --- faith guard -------------------------------------------------------------------------

_FAITH_PATTERN = re.compile(
    r"\b("
    r"mosques?|masjids?|churche?s?|cathedrals?|chapels?|parish(es)?|temples?|mandirs?|"
    r"gurd?waras?|gurudwaras?|synagogues?|monaster(y|ies)|worship\w*|prayers?|"
    r"congregations?|dioceses?|religio\w*|faiths?|spiritual\w*|"
    r"islam\w*|muslims?|christian\w*|catholic\w*|orthodox|protestant\w*|anglican\w*|"
    r"evangelical\w*|pentecostal\w*|hindu\w*|sikh\w*|buddhis\w*|jewish|juda\w*|jains?|"
    r"baha'?is?|zoroastrian\w*|quran|qur'an|bible|biblical|imams?|priests?|pastors?|"
    r"eid|diwali|deepavali|christmas|easter|ramadan|iftars?|suhoor|vesak|hanukkah|holi|"
    r"navratri|gurpurab"
    r")\b",
    re.IGNORECASE,
)


def mentions_faith(*texts: str | None) -> bool:
    """True when any text refers to religion, a place of worship or a religious festival."""
    return any(text and _FAITH_PATTERN.search(text) for text in texts)


# --- normalisation -------------------------------------------------------------------------


def clean_text(value: str | None, limit: int = MAX_TEXT) -> str | None:
    """Collapse whitespace, drop control characters, bound the length. Empty -> None."""
    if value is None:
        return None
    text = "".join(ch for ch in unicodedata.normalize("NFKC", value) if ch.isprintable())
    text = " ".join(text.split())[:limit].strip()
    return text or None


def clean_list(values: list[str] | tuple[str, ...] | None, *, limit: int, size: int) -> list[str]:
    seen: dict[str, str] = {}
    for raw in values or []:
        text = clean_text(raw, size)
        if text and text.casefold() not in seen:
            seen[text.casefold()] = text
    return list(seen.values())[:limit]


# ISO 3166-1 alpha-3 -> English short name, for countries with sizeable communities in Abu
# Dhabi. Unknown codes fall back to the code itself (still user-provided, never inferred).
_ISO3_NAMES: dict[str, str] = {
    "AFG": "Afghanistan",
    "ARE": "the UAE",
    "AUS": "Australia",
    "BGD": "Bangladesh",
    "BHR": "Bahrain",
    "BRA": "Brazil",
    "CAN": "Canada",
    "CHN": "China",
    "COL": "Colombia",
    "DEU": "Germany",
    "DZA": "Algeria",
    "EGY": "Egypt",
    "ESP": "Spain",
    "ETH": "Ethiopia",
    "FRA": "France",
    "GBR": "the United Kingdom",
    "GHA": "Ghana",
    "GRC": "Greece",
    "IDN": "Indonesia",
    "IND": "India",
    "IRL": "Ireland",
    "IRN": "Iran",
    "IRQ": "Iraq",
    "ITA": "Italy",
    "JOR": "Jordan",
    "JPN": "Japan",
    "KAZ": "Kazakhstan",
    "KEN": "Kenya",
    "KOR": "South Korea",
    "KWT": "Kuwait",
    "LBN": "Lebanon",
    "LKA": "Sri Lanka",
    "MAR": "Morocco",
    "MEX": "Mexico",
    "MYS": "Malaysia",
    "NGA": "Nigeria",
    "NLD": "the Netherlands",
    "NPL": "Nepal",
    "NZL": "New Zealand",
    "OMN": "Oman",
    "PAK": "Pakistan",
    "PHL": "the Philippines",
    "POL": "Poland",
    "PRT": "Portugal",
    "PSE": "Palestine",
    "QAT": "Qatar",
    "ROU": "Romania",
    "RUS": "Russia",
    "SAU": "Saudi Arabia",
    "SDN": "Sudan",
    "SOM": "Somalia",
    "SWE": "Sweden",
    "SYR": "Syria",
    "THA": "Thailand",
    "TUN": "Tunisia",
    "TUR": "Türkiye",
    "UGA": "Uganda",
    "UKR": "Ukraine",
    "USA": "the United States",
    "UZB": "Uzbekistan",
    "VNM": "Vietnam",
    "YEM": "Yemen",
    "ZAF": "South Africa",
    "ZWE": "Zimbabwe",
}


def country_name(code_or_name: str | None) -> str | None:
    text = clean_text(code_or_name)
    if text is None:
        return None
    return _ISO3_NAMES.get(text.upper(), text) if len(text) == 3 else text


PERSONA_TO_RELOCATION: dict[str, RelocationType] = {
    "founder": RelocationType.BUSINESS,
    "investor": RelocationType.BUSINESS,
    "employee": RelocationType.WORK,
    "student": RelocationType.STUDY,
    "family": RelocationType.FAMILY,
    "retiree": RelocationType.RETIREMENT,
    "other": RelocationType.OTHER,
}

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ar": "Arabic",
    "hi": "Hindi",
    "ur": "Urdu",
    "ml": "Malayalam",
    "tl": "Tagalog",
    "fil": "Filipino",
    "ru": "Russian",
    "fr": "French",
    "zh": "Chinese",
    "es": "Spanish",
    "de": "German",
    "bn": "Bengali",
    "ta": "Tamil",
    "fa": "Persian",
}


def language_name(tag: str) -> str:
    return LANGUAGE_NAMES.get(tag.split("-")[0].lower(), "English")


# --- inputs & profile ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatedValue:
    """A value plus whether the user themselves stated it (vs. extracted or inferred)."""

    value: str
    user_stated: bool


@dataclass(slots=True)
class ProfileFacts:
    """Raw facts gathered by the service (request, profile tables, journey) before the
    consent rules are applied. Deliberately has no name field."""

    language: str = "en"
    faith_consent: ConsentStatus = ConsentStatus.NOT_ASKED
    community_consent: ConsentStatus = ConsentStatus.NOT_ASKED
    relocation_type: RelocationType | None = None
    profession: str | None = None
    interests: list[str] = field(default_factory=list)
    background: StatedValue | None = None
    faith: StatedValue | None = None
    focus: str | None = None
    journey_goals: list[str] = field(default_factory=list)
    arrival_date: date | None = None
    # Profile dimension -> ids of the stored user facts it came from.
    fact_ids: dict[str, list[str]] = field(default_factory=dict)


class ResearchProfile(BaseModel):
    """Everything research is allowed to know. Stored with the job for transparency."""

    model_config = ConfigDict(frozen=True)

    language: str = "en"
    relocation_type: RelocationType | None = None
    profession: str | None = None
    interests: tuple[str, ...] = ()
    background: str | None = None
    faith: str | None = None
    focus: str | None = None
    journey_goals: tuple[str, ...] = ()
    arrival_date: date | None = None
    faith_opted_in: bool = False
    community_opted_in: bool = False
    withheld: tuple[str, ...] = Field(
        default=(), description="Facts that were available but not used, and why"
    )
    fact_ids: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Dimension -> stored user facts it came from (only dimensions used)",
    )

    def fact_ids_for(self, dimensions: list[str]) -> list[str]:
        """The stored user facts behind a result's relevance, for `explain`."""
        ids = [i for d in dimensions for i in self.fact_ids.get(d, ())]
        return list(dict.fromkeys(ids))

    @property
    def language_name(self) -> str:
        return language_name(self.language)

    def basis(self) -> list[str]:
        """Human-readable list of what personalised this research."""
        items: list[str] = []
        if self.relocation_type:
            items.append(f"Moving for: {self.relocation_type.value}")
        if self.profession:
            items.append(f"Work: {self.profession}")
        if self.interests:
            items.append(f"Interests: {', '.join(self.interests)}")
        if self.background:
            items.append(f"Background: {self.background}")
        if self.faith:
            items.append(f"Faith: {self.faith} (you told us)")
        elif self.faith_opted_in:
            items.append("Faith communities: all faiths")
        if self.focus:
            items.append(f"Looking for: {self.focus}")
        if self.journey_goals:
            items.append(f"Your plan: {'; '.join(self.journey_goals[:3])}")
        return items

    def prompt_facts(self) -> str:
        """The only rendering of the person that is ever sent to a model."""
        lines = [f"- Writes in: {self.language_name}"]
        if self.relocation_type:
            lines.append(f"- Reason for moving to Abu Dhabi: {self.relocation_type.value}")
        if self.profession:
            lines.append(f"- Profession: {self.profession}")
        if self.interests:
            lines.append(f"- Interests: {', '.join(self.interests)}")
        if self.background:
            lines.append(f"- Home country / background (stated by them): {self.background}")
        if self.faith:
            lines.append(f"- Faith (stated by them, opted in): {self.faith}")
        if self.focus:
            lines.append(f"- Specifically looking for: {self.focus}")
        if self.journey_goals:
            lines.append(f"- Goals in their relocation plan: {'; '.join(self.journey_goals)}")
        if self.arrival_date:
            lines.append(f"- Arriving: {self.arrival_date.isoformat()}")
        if not self.faith:
            lines.append("- Faith: not provided. Do not guess or assume any religion.")
        return "\n".join(lines)


def build_research_profile(facts: ProfileFacts) -> ResearchProfile:
    """Apply the consent and sensitivity rules. The only way to make a `ResearchProfile`
    from user data."""
    faith_ok = facts.faith_consent is ConsentStatus.GRANTED
    community_ok = facts.community_consent is ConsentStatus.GRANTED
    withheld: list[str] = []

    faith: str | None = None
    if facts.faith is not None:
        if not facts.faith.user_stated:
            withheld.append("faith: not stated by you, so it is never used")
        elif not faith_ok:
            withheld.append("faith: you haven't opted in to faith suggestions")
        else:
            faith = clean_text(facts.faith.value, 40)

    background: str | None = None
    if facts.background is not None:
        if not facts.background.user_stated:
            withheld.append("background: not provided by you")
        elif not community_ok:
            withheld.append("background: community personalisation is off")
        else:
            background = country_name(facts.background.value)

    interests = clean_list(facts.interests, limit=MAX_INTERESTS, size=MAX_INTEREST_LEN)
    if interests and not community_ok:
        withheld.append("interests: community personalisation is off")
        interests = []

    focus = clean_text(facts.focus, MAX_FOCUS)
    if focus and mentions_faith(focus) and not faith_ok:
        withheld.append("focus: mentions faith, which you haven't opted in to")
        focus = None

    used = {
        "relocation_type": facts.relocation_type is not None,
        "profession": clean_text(facts.profession) is not None,
        "interests": bool(interests),
        "background": background is not None,
        "faith": faith is not None,
    }
    return ResearchProfile(
        language=clean_text(facts.language, 12) or "en",
        relocation_type=facts.relocation_type,
        profession=clean_text(facts.profession),
        interests=tuple(interests),
        background=background,
        faith=faith,
        focus=focus,
        # Withheld facts leave no trace, not even their ids.
        fact_ids={
            dimension: tuple(ids)
            for dimension, ids in facts.fact_ids.items()
            if used.get(dimension) and ids
        },
        journey_goals=tuple(clean_list(facts.journey_goals, limit=MAX_GOALS, size=120)),
        arrival_date=facts.arrival_date,
        faith_opted_in=faith_ok,
        community_opted_in=community_ok,
        withheld=tuple(withheld),
    )
