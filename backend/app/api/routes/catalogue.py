"""Discover catalogue: communities and events (shared reference content).

Signed-in only: which items are listed depends on the user's own consents (faith items
appear only after an explicit opt-in), never on anything inferred about them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import PrincipalDep, UserSession
from app.contracts.catalogue import CommunityOut, CulturalGuideOut, EventOut
from app.domain.enums import CommunityCategory, EventCategory, GuideTopic
from app.repositories.accounts import read_preferences
from app.services import catalogue
from app.services.presenters import community_out, event_out, guide_out
from app.services.profile import require_user

router = APIRouter(tags=["discover"])


@router.get("/communities", response_model=list[CommunityOut], summary="Communities in Abu Dhabi")
async def communities(
    principal: PrincipalDep,
    session: UserSession,
    category: Annotated[CommunityCategory | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[CommunityOut]:
    consent = read_preferences(await require_user(session, principal)).faith_personalization
    rows = await catalogue.list_communities(
        session, faith_consent=consent, category=category, search=q
    )
    return [community_out(r) for r in rows]


@router.get("/events", response_model=list[EventOut], summary="Upcoming events")
async def events(
    principal: PrincipalDep,
    session: UserSession,
    category: Annotated[EventCategory | None, Query()] = None,
    starts_after: Annotated[datetime | None, Query(alias="from")] = None,
    starts_before: Annotated[datetime | None, Query(alias="to")] = None,
) -> list[EventOut]:
    consent = read_preferences(await require_user(session, principal)).faith_personalization
    rows = await catalogue.list_events(
        session,
        faith_consent=consent,
        category=category,
        starts_after=starts_after,
        starts_before=starts_before,
    )
    return [event_out(r) for r in rows]


@router.get(
    "/cultural-guides",
    response_model=list[CulturalGuideOut],
    summary="Cultural guides and practical starter kit",
)
async def cultural_guides(
    principal: PrincipalDep,
    session: UserSession,
    topic: Annotated[GuideTopic | None, Query()] = None,
    section: Annotated[str | None, Query(pattern="^(culture|surprises|starter_kit)$")] = None,
) -> list[CulturalGuideOut]:
    rows = await catalogue.list_guides(session, topic=topic, section=section)
    return [guide_out(r) for r in rows]
