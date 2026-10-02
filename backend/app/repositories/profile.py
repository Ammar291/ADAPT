"""Profile data access: user_profiles, household_members, user_goals, user_preferences.

All functions require a user-scoped session; RLS confines every statement to the
principal's rows and the explicit `user_id` filters make the intent visible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HouseholdMember, User, UserGoal, UserPreference, UserProfile
from app.domain.principal import Principal


@dataclass
class ProfileBundle:
    """Everything the user stated during onboarding (ORM rows)."""

    user: User
    profile: UserProfile | None
    household: list[HouseholdMember] = field(default_factory=list)
    goals: list[UserGoal] = field(default_factory=list)
    preferences: list[UserPreference] = field(default_factory=list)


async def get_profile(session: AsyncSession, principal: Principal) -> UserProfile | None:
    return (
        await session.execute(select(UserProfile).where(UserProfile.user_id == principal.user_id))
    ).scalar_one_or_none()


async def upsert_profile(
    session: AsyncSession, principal: Principal, values: dict[str, Any]
) -> UserProfile:
    profile = await get_profile(session, principal)
    if profile is None:
        profile = UserProfile(tenant_id=principal.tenant_id, user_id=principal.user_id)
        session.add(profile)
    for name, value in values.items():
        if value is None and name in {"languages", "assumptions", "target_city"}:
            continue  # NOT NULL columns keep their current/default value
        setattr(profile, name, value)
    await session.flush()
    return profile


async def list_household(session: AsyncSession, principal: Principal) -> list[HouseholdMember]:
    return list(
        (
            await session.execute(
                select(HouseholdMember)
                .where(HouseholdMember.user_id == principal.user_id)
                .order_by(HouseholdMember.position, HouseholdMember.created_at)
            )
        ).scalars()
    )


async def list_goals(session: AsyncSession, principal: Principal) -> list[UserGoal]:
    return list(
        (
            await session.execute(
                select(UserGoal)
                .where(UserGoal.user_id == principal.user_id)
                .order_by(UserGoal.position, UserGoal.created_at)
            )
        ).scalars()
    )


async def list_preferences(session: AsyncSession, principal: Principal) -> list[UserPreference]:
    return list(
        (
            await session.execute(
                select(UserPreference)
                .where(UserPreference.user_id == principal.user_id)
                .order_by(UserPreference.category, UserPreference.key)
            )
        ).scalars()
    )


async def replace_household(
    session: AsyncSession, principal: Principal, members: Sequence[dict[str, Any]]
) -> list[HouseholdMember]:
    await session.execute(
        delete(HouseholdMember).where(HouseholdMember.user_id == principal.user_id)
    )
    rows = [
        HouseholdMember(
            tenant_id=principal.tenant_id, user_id=principal.user_id, position=i, **values
        )
        for i, values in enumerate(members)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def replace_goals(
    session: AsyncSession, principal: Principal, goals: Sequence[dict[str, Any]]
) -> list[UserGoal]:
    await session.execute(delete(UserGoal).where(UserGoal.user_id == principal.user_id))
    rows = [
        UserGoal(tenant_id=principal.tenant_id, user_id=principal.user_id, position=i, **values)
        for i, values in enumerate(goals)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def replace_preferences(
    session: AsyncSession, principal: Principal, preferences: Sequence[dict[str, Any]]
) -> list[UserPreference]:
    await session.execute(delete(UserPreference).where(UserPreference.user_id == principal.user_id))
    rows = [
        UserPreference(tenant_id=principal.tenant_id, user_id=principal.user_id, **values)
        for values in preferences
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def load_bundle(session: AsyncSession, principal: Principal, user: User) -> ProfileBundle:
    return ProfileBundle(
        user=user,
        profile=await get_profile(session, principal),
        household=await list_household(session, principal),
        goals=await list_goals(session, principal),
        preferences=await list_preferences(session, principal),
    )
