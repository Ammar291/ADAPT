"""Gathering the raw facts research may use: consents, stored profile facts, the request,
and the current journey. The consent rules are applied afterwards, in
`profile.build_research_profile`. This module only collects facts, deliberately without
the user's name.

Stored facts come from the personalisation service (`planning_facts`) when it's
available, otherwise straight from the profile tables. Either way, only facts the user
provided count as "stated".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ConsentStatus
from app.domain.principal import Principal
from app.research.contracts import StartResearchRequest
from app.research.profile import PERSONA_TO_RELOCATION, ProfileFacts, StatedValue
from app.research.types import RelocationType

logger = logging.getLogger(__name__)

FACT_KEYS = ["person.occupation", "community.interests", "nationality", "goals", "community.faith"]

_GOAL_HINTS: tuple[tuple[tuple[str, ...], RelocationType], ...] = (
    (("company", "business", "licen", "invest", "startup"), RelocationType.BUSINESS),
    (("family", "sponsor", "spouse", "child"), RelocationType.FAMILY),
    (("study", "university", "student"), RelocationType.STUDY),
    (("retire",), RelocationType.RETIREMENT),
    (("job", "work", "employ", "career"), RelocationType.WORK),
)


@dataclass(frozen=True, slots=True)
class Stored:
    """A stored fact: its value, whether the user provided it, and its fact ids (for
    "why is this relevant" explanations via `app.personalization.facts.explain`)."""

    value: Any
    user_stated: bool
    fact_ids: tuple[str, ...] = ()


def relocation_from_goals(goals: list[str]) -> RelocationType | None:
    text = " ".join(goals).casefold()
    for hints, relocation in _GOAL_HINTS:
        if any(hint in text for hint in hints):
            return relocation
    return None


def _consent(value: Any) -> ConsentStatus:
    try:
        return ConsentStatus(value)
    except ValueError:
        return ConsentStatus.NOT_ASKED


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list | tuple):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


async def _preferences(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    from app.db.models import User

    user = (
        await session.execute(
            select(User).where(User.id == principal.user_id, User.tenant_id == principal.tenant_id)
        )
    ).scalar_one_or_none()
    return dict(user.preferences or {}) if user else {}


async def _stored_from_personalization(
    session: AsyncSession, principal: Principal
) -> dict[str, Stored] | None:
    try:
        from app.personalization.facts import planning_facts  # type: ignore[import-not-found]
    except ImportError:
        return None
    facts = await planning_facts(session, principal, keys=FACT_KEYS)
    return {
        fact.key: Stored(
            fact.value,
            fact.source == "user_stated" or bool(fact.confirmed),
            tuple(str(i) for i in fact.fact_ids),
        )
        for fact in facts
    }


async def _stored_from_profile_tables(
    session: AsyncSession, principal: Principal
) -> dict[str, Stored]:
    from app.db.models import UserGoal, UserPreference, UserProfile

    stored: dict[str, Stored] = {}
    profile = (await session.execute(select(UserProfile).limit(1))).scalar_one_or_none()
    if profile is not None:
        if profile.occupation:
            stored["person.occupation"] = Stored(profile.occupation, True)
        if profile.nationality:
            stored["nationality"] = Stored([profile.nationality], True)
        if profile.persona:
            stored["persona"] = Stored(profile.persona, True)
        if profile.arrival_date:
            stored["arrival_date"] = Stored(profile.arrival_date, True)
    preferences = (await session.execute(select(UserPreference))).scalars().all()
    for pref in preferences:
        category = getattr(pref.category, "value", pref.category)
        user_stated = getattr(pref.source, "value", pref.source) == "user_stated"
        if category == "community":
            existing = stored.get("community.interests", Stored([], True)).value
            stored["community.interests"] = Stored([*existing, *_as_list(pref.value)], user_stated)
        elif category == "faith" and user_stated:
            stored["community.faith"] = Stored(pref.value, True)
    goals = (await session.execute(select(UserGoal))).scalars().all()
    if goals:
        stored["goals"] = Stored(
            [f"{getattr(g.goal_type, 'value', g.goal_type)} {g.title}" for g in goals],
            True,
        )
    return stored


# The journey planner's goal keys, in words (shown on Discover and given to the search model).
_GOAL_WORDS = {
    "establish_company": "setting up a company",
    "residency": "a residence visa",
    "sponsor_family": "sponsoring family",
    "find_housing": "finding a home",
}


async def _journey_goals(session: AsyncSession, journey_id: UUID | None) -> list[str]:
    from app.db.models import Journey

    query = select(Journey)
    query = (
        query.where(Journey.id == journey_id)
        if journey_id
        # The person's plan, never a what-if copy of it.
        else query.where(Journey.parent_journey_id.is_(None)).order_by(Journey.updated_at.desc())
    )
    journey = (await session.execute(query.limit(1))).scalar_one_or_none()
    if journey is None:
        return []
    goals = [
        _GOAL_WORDS.get(g, g.replace("_", " "))
        if isinstance(g, str)
        else str(g.get("title") or g.get("kind") or "")
        for g in (journey.goals or [])
    ]
    return [g for g in goals if g] or [journey.title]


async def gather_profile_facts(
    session: AsyncSession, principal: Principal, request: StartResearchRequest
) -> ProfileFacts:
    prefs = await _preferences(session, principal)
    facts = ProfileFacts(
        language=str(prefs.get("preferred_language") or "en"),
        faith_consent=_consent(prefs.get("faith_personalization")),
        community_consent=_consent(prefs.get("community_personalization")),
    )

    try:
        stored = await _stored_from_personalization(session, principal)
        if stored is None:
            stored = await _stored_from_profile_tables(session, principal)
    except Exception:  # stored facts only enrich research; never block it
        logger.warning("research_profile_facts_unavailable", exc_info=True)
        stored = {}

    def use(key: str, dimension: str) -> Stored | None:
        found = stored.get(key)
        if found is not None and found.value not in (None, "", []):
            facts.fact_ids[dimension] = list(found.fact_ids)
            return found
        return None

    if found := use("person.occupation", "profession"):
        facts.profession = str(found.value)
    if (found := use("community.interests", "interests")) and found.user_stated:
        facts.interests = _as_list(found.value)
    if (found := use("nationality", "background")) and _as_list(found.value):
        facts.background = StatedValue(_as_list(found.value)[0], user_stated=found.user_stated)
    if found := use("community.faith", "faith"):
        facts.faith = StatedValue(str(found.value), user_stated=found.user_stated)
    if found := use("persona", "relocation_type"):
        facts.relocation_type = PERSONA_TO_RELOCATION.get(str(found.value))
    if facts.relocation_type is None and (found := use("goals", "relocation_type")):
        facts.relocation_type = relocation_from_goals(_as_list(found.value))
    if found := stored.get("arrival_date"):
        facts.arrival_date = found.value

    try:
        facts.journey_goals = await _journey_goals(session, request.journey_id)
    except Exception:
        logger.warning("research_journey_unavailable", exc_info=True)

    # What the user states in the request wins (it is, by definition, user-stated).
    if given := request.profile:
        if given.relocation_type:
            facts.relocation_type = given.relocation_type
            facts.fact_ids.pop("relocation_type", None)
        if given.profession:
            facts.profession = given.profession
            facts.fact_ids.pop("profession", None)
        if given.interests:
            facts.interests = list(given.interests)
            facts.fact_ids.pop("interests", None)
        if given.background:
            facts.background = StatedValue(given.background, user_stated=True)
            facts.fact_ids.pop("background", None)
        if given.faith:
            facts.faith = StatedValue(given.faith, user_stated=True)
            facts.fact_ids.pop("faith", None)
    facts.focus = request.focus
    return facts
