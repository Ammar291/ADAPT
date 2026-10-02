"""Search plans per research category.

Queries are built from templates rather than by a model, so what leaves ADAPT is
predictable and auditable: faith terms appear only for users who opted in, background and
interests only with community consent, and never the user's name. Follow-up queries
proposed by the model pass through the same guard (`sanitize_follow_ups`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.adapters.web_search import SearchDepth
from app.research.profile import ResearchProfile, clean_text, mentions_faith
from app.research.types import COMPLEX_CATEGORIES, RelocationType, ResearchCategory

# Official UAE / Abu Dhabi domains for rules and guidance (subdomains included).
OFFICIAL_SEARCH_DOMAINS: list[str] = [
    "u.ae",
    "gov.ae",
    "abudhabi.ae",
    "tamm.abudhabi",
    "adgm.com",
]

# Approximate first days of Ramadan (astronomical estimates; the actual start is announced
# after moon sighting). Used only to decide whether Ramadan guidance is timely. These
# dates are never shown to users.
_RAMADAN_STARTS_APPROX: tuple[date, ...] = (
    date(2026, 2, 18),
    date(2027, 2, 8),
    date(2028, 1, 28),
    date(2029, 1, 16),
    date(2030, 1, 6),
)


def ramadan_is_relevant(today: date, arrival: date | None = None) -> bool:
    """True when Ramadan falls within the next ~6 months (or is under way) for someone
    arriving now or on their arrival date."""
    for anchor in {today, arrival or today}:
        for start in _RAMADAN_STARTS_APPROX:
            if start - timedelta(days=183) <= anchor <= start + timedelta(days=30):
                return True
    return False


@dataclass(frozen=True, slots=True)
class PlannedQuery:
    query: str
    depth: SearchDepth = "quick"
    allowed_domains: tuple[str, ...] | None = None


def _depth(category: ResearchCategory) -> SearchDepth:
    return "agentic" if category in COMPLEX_CATEGORIES else "quick"


def build_query_plan(
    category: ResearchCategory, profile: ResearchProfile, today: date
) -> list[PlannedQuery]:
    depth = _depth(category)
    official = tuple(OFFICIAL_SEARCH_DOMAINS)
    month = today.strftime("%B %Y")
    interests = ", ".join(profile.interests[:3])
    q: list[PlannedQuery] = []

    match category:
        case ResearchCategory.COMMUNITY:
            q.append(
                PlannedQuery(
                    "recognised community associations, social clubs and newcomer groups in "
                    "Abu Dhabi with their official websites",
                    depth,
                )
            )
            if profile.background:
                q.append(
                    PlannedQuery(
                        f"recognised {profile.background} community association or social and "
                        "cultural centre in Abu Dhabi, official website",
                        depth,
                    )
                )
            if interests:
                q.append(
                    PlannedQuery(f"{interests} clubs and community groups in Abu Dhabi", depth)
                )
            if profile.focus:
                q.append(PlannedQuery(f"{profile.focus} in Abu Dhabi", depth))
            if profile.relocation_type is RelocationType.FAMILY:
                q.append(PlannedQuery("parent and family community groups in Abu Dhabi", depth))
        case ResearchCategory.FAITH_AND_WORSHIP:
            if not profile.faith_opted_in:
                return []  # never searched without explicit opt-in
            if profile.faith:
                q.append(
                    PlannedQuery(
                        f"{profile.faith} places of worship and faith communities in Abu Dhabi, "
                        "official websites",
                        depth,
                    )
                )
            else:
                q.append(
                    PlannedQuery(
                        "places of worship for different faiths in Abu Dhabi, official websites",
                        depth,
                    )
                )
        case ResearchCategory.PROFESSIONAL_NETWORK:
            if profile.profession:
                q.append(
                    PlannedQuery(
                        f"{profile.profession} professional associations and networking groups in "
                        "Abu Dhabi",
                        depth,
                    )
                )
            if profile.relocation_type is RelocationType.BUSINESS:
                q.append(
                    PlannedQuery(
                        "startup founder and SME support programmes and networks in Abu Dhabi, "
                        "official",
                        depth,
                    )
                )
            q.append(
                PlannedQuery(
                    "business councils and professional networks for expatriates in Abu Dhabi",
                    depth,
                )
            )
        case ResearchCategory.EVENTS:
            q.append(
                PlannedQuery(f"upcoming events in Abu Dhabi {month}, official calendar", depth)
            )
            if interests:
                q.append(PlannedQuery(f"{interests} events in Abu Dhabi {month}", depth))
            if profile.relocation_type is RelocationType.FAMILY:
                q.append(PlannedQuery(f"family events in Abu Dhabi {month}", depth))
            elif profile.relocation_type is RelocationType.BUSINESS:
                q.append(
                    PlannedQuery(
                        f"business and startup networking events in Abu Dhabi {month}", depth
                    )
                )
        case ResearchCategory.CULTURE:
            q.append(
                PlannedQuery(
                    "Abu Dhabi cultural etiquette and customs guidance for residents and visitors",
                    depth,
                    official,
                )
            )
            q.append(
                PlannedQuery(
                    "UAE laws on public behaviour, dress and decency that residents should know",
                    depth,
                    official,
                )
            )
            if ramadan_is_relevant(today, profile.arrival_date):
                q.append(
                    PlannedQuery(
                        "Ramadan etiquette in Abu Dhabi for all residents and visitors, official "
                        "guidance",
                        depth,
                        official,
                    )
                )
        case ResearchCategory.LIFESTYLE:
            q.append(
                PlannedQuery(
                    "everyday life in Abu Dhabi that surprises newcomers: working week, climate, "
                    "customs",
                    depth,
                )
            )
            q.append(
                PlannedQuery(
                    "UAE working week, weekend and public holidays, official", depth, official
                )
            )
            q.append(
                PlannedQuery(
                    "UAE summer midday break rule for outdoor work, official", depth, official
                )
            )
        case ResearchCategory.STARTER_KIT:
            q.append(
                PlannedQuery(
                    "essential steps for new residents in Abu Dhabi: Emirates ID, health "
                    "insurance, TAMM government services",
                    depth,
                    official,
                )
            )
            q.append(
                PlannedQuery(
                    "getting around Abu Dhabi for new residents: public buses, Hafilat card, "
                    "Darb road tolls",
                    depth,
                )
            )
            if profile.relocation_type is RelocationType.FAMILY:
                q.append(
                    PlannedQuery(
                        "enrolling children in schools in Abu Dhabi for new residents, ADEK",
                        depth,
                        official,
                    )
                )
    return _guard(q, category, profile)


def _guard(
    queries: list[PlannedQuery], category: ResearchCategory, profile: ResearchProfile
) -> list[PlannedQuery]:
    """Drop duplicate queries, and any that mention faith for a user who hasn't opted in.
    Culture keeps its Ramadan etiquette query: it applies to everyone living in Abu Dhabi."""
    out: list[PlannedQuery] = []
    seen: set[str] = set()
    for item in queries:
        key = item.query.casefold()
        if key in seen:
            continue
        seen.add(key)
        if (
            not profile.faith_opted_in
            and category is not ResearchCategory.CULTURE
            and mentions_faith(item.query)
        ):
            continue
        out.append(item)
    return out


def sanitize_follow_ups(
    queries: list[str], category: ResearchCategory, profile: ResearchProfile, *, limit: int = 2
) -> list[PlannedQuery]:
    """Model-proposed follow-up searches, bounded and passed through the privacy guard."""
    cleaned: list[PlannedQuery] = []
    for raw in queries:
        text = clean_text(raw, 200)
        if not text:
            continue
        if "abu dhabi" not in text.casefold():
            text = f"{text} Abu Dhabi"
        cleaned.append(PlannedQuery(text, _depth(category)))
    return _guard(cleaned, category, profile)[:limit]
