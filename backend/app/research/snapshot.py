"""Offline research: the curated, URL-verified Abu Dhabi catalogue, matched to a profile.

The catalogue (`app/seed/catalogue.yaml`, shared with the public catalogue tables) lists
real organisations, places, events and guidance. Every entry was checked by loading its
page, and `retrieved_at` is the date it was reviewed, so "last checked" stays truthful.
Offline research never invents entries, contact details or dates. It selects and explains
catalogue entries using the same consent rules as live research.

Entry tags drive matching, as prefixed strings: `relocation:business`,
`profession:founder`, `interest:running`, `background:india`, `faith:christian`,
`faith:multi`. Identity tags (background, faith) need a positive match: a country-of-origin
centre is only shown to someone who stated that background with community consent.
Situational tags rank rather than gate: matching interests rank first but never hide
anything, and profession/relocation exclude only when the profile has a different known
value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.domain.enums import EvidenceKind
from app.domain.provenance import is_official_source
from app.research.profile import ResearchProfile
from app.research.sources import classify_source
from app.research.types import (
    Candidate,
    ClaimedSourceType,
    RelocationType,
    ResearchCategory,
    SourceLabel,
)

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "seed" / "catalogue.yaml"

PROFESSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "founder": (
        "founder",
        "co-founder",
        "cofounder",
        "entrepreneur",
        "entrepreneurs",
        "startup",
        "start-up",
        "business owner",
        "own business",
        "ceo",
        "sme",
    ),
    "technology": (
        "software",
        "tech",
        "technology",
        "developer",
        "programmer",
        "data",
        "ai",
        "product manager",
        "cyber",
        "cloud",
        "it",
    ),
    "finance": (
        "finance",
        "financial",
        "bank",
        "banker",
        "banking",
        "accountant",
        "accounting",
        "investment",
        "investor",
        "audit",
        "fintech",
    ),
    "healthcare": (
        "doctor",
        "nurse",
        "physician",
        "health",
        "healthcare",
        "medical",
        "pharmacist",
        "dentist",
        "clinic",
        "hospital",
        "surgeon",
    ),
    "education": (
        "teacher",
        "lecturer",
        "professor",
        "education",
        "school",
        "tutor",
        "academic",
        "researcher",
    ),
    "engineering": ("engineer", "engineering", "architect", "construction"),
    "creative": (
        "designer",
        "artist",
        "writer",
        "photographer",
        "film",
        "media",
        "marketing",
        "creative",
        "musician",
    ),
    "legal": ("lawyer", "legal", "attorney", "solicitor", "barrister", "paralegal"),
    "hospitality": ("hospitality", "hotel", "chef", "restaurant", "tourism"),
    "energy": ("energy", "oil", "gas", "petroleum", "renewable", "renewables", "solar"),
}

INTEREST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "running": ("run", "runs", "running", "runner", "marathon", "jogging", "parkrun"),
    "cycling": ("cycling", "cycle", "bike", "biking", "cyclist", "triathlon"),
    "football": ("football", "soccer"),
    "cricket": ("cricket",),
    "racket_sports": ("padel", "tennis", "squash", "badminton", "racket sports"),
    "swimming": ("swim", "swimming"),
    "diving": ("diving", "scuba", "snorkelling", "snorkeling", "freediving"),
    "outdoors": (
        "hiking",
        "outdoor",
        "outdoors",
        "desert",
        "camping",
        "kayaking",
        "nature",
        "climbing",
    ),
    "arts": (
        "art",
        "arts",
        "museum",
        "museums",
        "gallery",
        "galleries",
        "painting",
        "theatre",
        "theater",
    ),
    "music": ("music", "concert", "concerts", "choir", "singing", "band"),
    "books": ("book", "books", "reading", "literature", "library"),
    "food": ("food", "cooking", "restaurants", "dining", "baking", "cuisine"),
    "photography": ("photo", "photos", "photography"),
    "volunteering": ("volunteer", "volunteering", "charity"),
    "family_activities": ("kids", "children", "family", "parenting"),
    "board_games": ("board game", "board games", "chess", "games night"),
    "wellness": ("yoga", "wellness", "meditation", "fitness", "pilates", "gym"),
    "motorsport": ("motorsport", "formula 1", "f1", "racing", "cars"),
    "heritage": ("heritage", "history", "archaeology"),
}

FAITH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "christian": (
        "christian",
        "christianity",
        "catholic",
        "orthodox",
        "protestant",
        "anglican",
        "evangelical",
        "pentecostal",
        "coptic",
        "maronite",
        "church",
    ),
    "muslim": ("muslim", "islam", "islamic", "sunni", "shia"),
    "hindu": ("hindu", "hinduism", "sanatan"),
    "sikh": ("sikh", "sikhism"),
    "buddhist": ("buddhist", "buddhism"),
    "jewish": ("jewish", "judaism", "jew"),
}

_COUNTRY_ALIASES: dict[str, str] = {
    "united kingdom": "uk",
    "great britain": "uk",
    "britain": "uk",
    "england": "uk",
    "scotland": "uk",
    "wales": "uk",
    "united states": "usa",
    "us": "usa",
    "america": "usa",
    "the netherlands": "netherlands",
    "uae": "united arab emirates",
}


def _keywords_in(text: str, table: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Tag -> the keyword that matched, using whole-word matching."""
    found: dict[str, str] = {}
    lowered = text.casefold()
    for tag, words in table.items():
        for word in words:
            if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", lowered):
                found[tag] = word
                break
    return found


def country_tag(name: str) -> str:
    text = name.casefold().strip().removeprefix("the ").strip()
    return _COUNTRY_ALIASES.get(text, text)


# --- catalogue ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    key: str
    category: ResearchCategory
    title: str
    summary: str
    url: str
    source_title: str
    evidence_kind: EvidenceKind
    retrieved_at: datetime
    tags: dict[str, frozenset[str]] = field(default_factory=dict)
    starts_on: date | None = None
    ends_on: date | None = None
    timing_note: str | None = None
    position: int = 0  # the curators' order within a section, used to break ties


def _tags(raw: list[str] | None) -> dict[str, frozenset[str]]:
    grouped: dict[str, set[str]] = {}
    for item in raw or []:
        prefix, _, value = str(item).partition(":")
        if value:
            grouped.setdefault(prefix.strip().lower(), set()).add(value.strip().lower())
    return {k: frozenset(v) for k, v in grouped.items()}


def _when(value: Any, reviewed: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return reviewed


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    return None


_COMMUNITY_CATEGORY = {
    "faith": ResearchCategory.FAITH_AND_WORSHIP,
    "professional": ResearchCategory.PROFESSIONAL_NETWORK,
}
_GUIDE_SECTION = {
    "culture": ResearchCategory.CULTURE,
    "surprises": ResearchCategory.LIFESTYLE,
    "starter_kit": ResearchCategory.STARTER_KIT,
}


def parse_catalogue(data: dict[str, Any]) -> list[CatalogueEntry]:
    """Read the shared catalogue format. Sample rows and rows without a source are skipped:
    offline research only ever returns real, checked pages."""
    reviewed = _when(data.get("reviewed_on"), datetime(2026, 9, 29, tzinfo=UTC))
    entries: list[CatalogueEntry] = []

    def add(row: dict[str, Any], category: ResearchCategory, title: str, summary: str) -> None:
        url = row.get("source_url") or row.get("website_url") or row.get("url")
        if row.get("is_sample") or not url:
            return
        kind = EvidenceKind(row.get("evidence_kind", "community_web"))
        if row.get("binding") and is_official_source(str(url)):
            kind = EvidenceKind.AUTHORITATIVE_REQUIREMENT  # a legal rule on an official page
        entries.append(
            CatalogueEntry(
                key=str(row["key"]),
                category=category,
                title=title,
                summary=summary,
                url=str(url),
                source_title=str(row.get("source_title") or title),
                evidence_kind=kind,
                retrieved_at=_when(row.get("retrieved_at"), reviewed),
                tags=_tags(row.get("tags")),
                starts_on=_day(row.get("starts_at")),
                ends_on=_day(row.get("ends_at")),
                timing_note=row.get("timing_note"),
                position=int(row.get("position") or 0),
            )
        )

    for row in data.get("communities") or []:
        category = _COMMUNITY_CATEGORY.get(row.get("category"), ResearchCategory.COMMUNITY)
        add(row, category, row["name"], row.get("description", ""))
    for row in data.get("events") or []:
        add(row, ResearchCategory.EVENTS, row["title"], row.get("description", ""))
    for row in sorted(data.get("cultural_guides") or [], key=lambda r: r.get("position", 0)):
        category = _GUIDE_SECTION.get(row.get("section"), ResearchCategory.CULTURE)
        add(row, category, row["title"], row.get("summary", ""))
    return entries


@lru_cache(maxsize=4)
def load_catalogue(path: Path = CATALOGUE_PATH) -> tuple[CatalogueEntry, ...]:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as handle:
        return tuple(parse_catalogue(yaml.safe_load(handle) or {}))


# --- matching ---------------------------------------------------------------------------------

_GENERIC_RELEVANCE: dict[ResearchCategory, str] = {
    ResearchCategory.COMMUNITY: "A good way to meet people when you're new to Abu Dhabi.",
    ResearchCategory.FAITH_AND_WORSHIP: (
        "One of Abu Dhabi's places of worship. Shown because you asked to include faith "
        "communities."
    ),
    ResearchCategory.PROFESSIONAL_NETWORK: "Useful for building your network in Abu Dhabi.",
    ResearchCategory.EVENTS: "One of Abu Dhabi's regular highlights, worth planning around.",
    ResearchCategory.CULTURE: "Helpful for everyone living in Abu Dhabi.",
    ResearchCategory.LIFESTYLE: "Many newcomers don't expect this.",
    ResearchCategory.STARTER_KIT: "One of the first things most new residents sort out.",
}

_RELOCATION_RELEVANCE: dict[RelocationType, str] = {
    RelocationType.BUSINESS: "Useful when you're setting up a business here.",
    RelocationType.WORK: "Useful when you're moving for work.",
    RelocationType.FAMILY: "Useful for families settling in.",
    RelocationType.STUDY: "Useful for students.",
    RelocationType.RETIREMENT: "Useful when you're retiring here.",
    RelocationType.OTHER: "Useful for your move.",
}

_LABEL_ORDER = {
    SourceLabel.OFFICIAL: 0,
    SourceLabel.ORGANIZATION: 1,
    SourceLabel.COMMUNITY: 2,
    SourceLabel.GENERAL_WEB: 3,
}


@dataclass(frozen=True, slots=True)
class Match:
    entry: CatalogueEntry
    score: float
    relevance: str
    fact_keys: tuple[str, ...]


def match_entry(entry: CatalogueEntry, profile: ResearchProfile) -> Match | None:
    """Score one entry for a profile, or None when it targets someone else."""
    reasons: list[str] = []
    keys: list[str] = []
    score = 1.0

    if wanted := entry.tags.get("background"):
        if not profile.background or country_tag(profile.background) not in wanted:
            return None
        reasons.append(f"A community for people from {profile.background}.")
        keys.append("background")
        score += 3

    # Situational tags. Interests only ever add rank. A known, different profession or
    # relocation type excludes; an unknown one doesn't (no bonus, generic explanation).
    if wanted := entry.tags.get("interest"):
        mine = _keywords_in(" ".join(profile.interests), INTEREST_KEYWORDS)
        hit = next((mine[t] for t in sorted(wanted) if t in mine), None)
        if hit is not None:  # a match ranks first; other interests never hide an entry
            reasons.append(f"Matches your interest in {hit}.")
            keys.append("interests")
            score += 2

    if wanted := entry.tags.get("profession"):
        mine = _keywords_in(profile.profession or "", PROFESSION_KEYWORDS)
        if wanted & mine.keys():
            reasons.append(f"Relevant to your work ({profile.profession}).")
            keys.append("profession")
            score += 2
        elif mine:
            return None

    if wanted := entry.tags.get("relocation"):
        if profile.relocation_type is not None and profile.relocation_type.value in wanted:
            reasons.append(_RELOCATION_RELEVANCE[profile.relocation_type])
            keys.append("relocation_type")
            score += 1
        elif profile.relocation_type is not None:
            return None

    if entry.category is ResearchCategory.FAITH_AND_WORSHIP:
        if not profile.faith_opted_in:
            return None
        faiths = entry.tags.get("faith", frozenset())
        stated = set(_keywords_in(profile.faith or "", FAITH_KEYWORDS))
        if "multi" in faiths:
            reasons.insert(0, "Welcomes people of all faiths.")
            score += 1
        elif profile.faith:
            if not stated & faiths:
                return None
            reasons.insert(0, "Matches the faith you told us about.")
            keys.append("faith")
            score += 2

    relevance = " ".join(reasons) or _GENERIC_RELEVANCE[entry.category]
    return Match(entry, score, relevance, tuple(keys))


def select_entries(
    entries: tuple[CatalogueEntry, ...] | list[CatalogueEntry],
    category: ResearchCategory,
    profile: ResearchProfile,
    *,
    limit: int,
) -> list[Match]:
    matches = [m for e in entries if e.category is category and (m := match_entry(e, profile))]
    matches.sort(
        key=lambda m: (
            -m.score,
            _LABEL_ORDER[classify_source(m.entry.url)],
            m.entry.position,
            m.entry.title,
        )
    )
    return matches[:limit]


def to_candidate(match: Match) -> Candidate:
    entry = match.entry
    return Candidate(
        category=entry.category,
        title=entry.title,
        summary=entry.summary,
        relevance=match.relevance,
        claim_kind=entry.evidence_kind,
        primary_url=entry.url,
        # Curated rows cite the organisation's own site; community platforms and news
        # sites are still recognised by domain in `classify_source`.
        claimed_source_type=ClaimedSourceType.ORGANIZATION_SITE,
        involves_faith=entry.category is ResearchCategory.FAITH_AND_WORSHIP
        or "faith" in entry.tags,
        event_starts_on=entry.starts_on,
        event_ends_on=entry.ends_on,
        event_timing=entry.timing_note,
        fact_keys=list(match.fact_keys),
    )
