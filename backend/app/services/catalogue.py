"""Discover catalogue queries (communities, events, cultural guides).

Faith communities and faith events are only listed for users who opted in to faith
personalisation; nothing about the user is inferred to decide what they see.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Community, CulturalGuide, Event
from app.domain.enums import CommunityCategory, ConsentStatus, EventCategory, GuideTopic


async def list_communities(
    session: AsyncSession,
    *,
    faith_consent: ConsentStatus,
    category: CommunityCategory | None = None,
    search: str | None = None,
    limit: int = 100,
) -> list[Community]:
    query = select(Community)
    if faith_consent is not ConsentStatus.GRANTED:
        query = query.where(Community.category != CommunityCategory.FAITH)
    if category is not None:
        query = query.where(Community.category == category)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(Community.name.ilike(pattern), Community.description.ilike(pattern))
        )
    query = query.order_by(Community.is_sample, Community.name).limit(limit)
    return list((await session.execute(query)).scalars())


async def list_events(
    session: AsyncSession,
    *,
    faith_consent: ConsentStatus,
    category: EventCategory | None = None,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    limit: int = 100,
) -> list[Event]:
    """Upcoming dated events first, then recurring events without a confirmed date."""
    after = starts_after or datetime.now(UTC)
    query = select(Event).where(or_(Event.starts_at.is_(None), Event.starts_at >= after))
    if starts_before is not None:
        query = query.where(Event.starts_at.is_not(None), Event.starts_at <= starts_before)
    if faith_consent is not ConsentStatus.GRANTED:
        query = query.where(Event.category != EventCategory.FAITH)
    if category is not None:
        query = query.where(Event.category == category)
    query = query.order_by(Event.starts_at.asc().nulls_last(), Event.title).limit(limit)
    return list((await session.execute(query)).scalars())


async def list_guides(
    session: AsyncSession,
    *,
    topic: GuideTopic | None = None,
    section: str | None = None,
) -> list[CulturalGuide]:
    query = select(CulturalGuide)
    if topic is not None:
        query = query.where(CulturalGuide.topic == topic)
    if section is not None:
        query = query.where(CulturalGuide.section == section)
    query = query.order_by(CulturalGuide.section, CulturalGuide.position, CulturalGuide.title)
    return list((await session.execute(query)).scalars())
