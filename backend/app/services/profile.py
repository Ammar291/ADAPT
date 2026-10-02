"""Onboarding and profile use cases.

The profile tables are the canonical store for what the user states about themselves.
Every write is projected into the private user graph in the same transaction:

* by `app.personalization.onboarding.project_profile(session, principal, bundle)` when
  the personalization workstream is installed (it owns the user-graph vocabulary), or
* by a minimal built-in projection otherwise (person, household members, company, goals
  and goal -> governance service links).
"""

from __future__ import annotations

import hashlib
import importlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.auth import UserPreferencesUpdate
from app.contracts.profile import (
    HouseholdMemberIn,
    OnboardingProfileRequest,
    ProfileFields,
    ProfileUpdate,
    UserGoalIn,
    UserPreferenceIn,
    profile_values,
)
from app.core.errors import Unauthorized, UnprocessableEntity
from app.db.models import User
from app.domain.enums import (
    ConsentStatus,
    FactSource,
    GoalType,
    GraphEdgeType,
    HouseholdRelationship,
    PreferenceCategory,
    TwinNodeType,
)
from app.domain.principal import Principal
from app.domain.twin import TwinFact
from app.repositories import accounts
from app.repositories import profile as repo
from app.repositories.graph import GovernanceGraphRepository, UserGraphRepository

logger = logging.getLogger(__name__)

ProjectFn = Callable[[AsyncSession, Principal, repo.ProfileBundle], Awaitable[Any]]

# Governance service a goal pursues when the user did not name one. Keys that are not in
# the governance graph are simply not linked.
DEFAULT_GOAL_SERVICES: dict[GoalType, str] = {
    GoalType.SPONSOR_FAMILY: "service.family_residence_visa",
    GoalType.FIND_HOUSING: "service.tawtheeq",
    GoalType.RESIDENCY: "service.residence_visa_investor",
}
JURISDICTION_SERVICES: dict[str, str] = {
    "adgm": "service.company_registration_adgm",
    "mainland": "service.commercial_license_mainland",
}
GOAL_TITLES: dict[GoalType, str] = {
    GoalType.ESTABLISH_COMPANY: "Set up my company",
    GoalType.RESIDENCY: "Get my UAE residency",
    GoalType.SPONSOR_FAMILY: "Sponsor my family",
    GoalType.FIND_HOUSING: "Find a home",
    GoalType.SCHOOLING: "Enrol my children in school",
    GoalType.HEALTHCARE: "Arrange healthcare",
    GoalType.BANKING: "Open a bank account",
    GoalType.EMPLOYMENT: "Start my job",
    GoalType.COMMUNITY: "Find my community",
    GoalType.DRIVING: "Get a UAE driving licence",
    GoalType.OTHER: "Another goal",
}
PLANNING_FIELDS: tuple[str, ...] = ("nationality", "persona", "arrival_date")


async def require_user(session: AsyncSession, principal: Principal) -> User:
    user = await accounts.get_user(session, principal.user_id, principal.tenant_id)
    if user is None:
        raise Unauthorized("Your account no longer exists", code="account_missing")
    return user


def _faith_consent(user: User) -> ConsentStatus:
    return accounts.read_preferences(user).faith_personalization


def _check_preferences(user: User, preferences: list[UserPreferenceIn]) -> None:
    if any(p.category is PreferenceCategory.FAITH for p in preferences) and (
        _faith_consent(user) is not ConsentStatus.GRANTED
    ):
        raise UnprocessableEntity(
            "Faith preferences can only be saved after you opt in to faith personalisation",
            code="faith_consent_required",
        )


async def _goal_rows(
    session: AsyncSession, goals: list[UserGoalIn], assumptions: dict[str, Any]
) -> list[dict[str, Any]]:
    jurisdiction = str(assumptions.get("company.jurisdiction", "")).lower()
    wanted: dict[int, str] = {}
    for index, goal in enumerate(goals):
        key = goal.service_key
        if key is None and goal.goal_type is GoalType.ESTABLISH_COMPANY:
            key = JURISDICTION_SERVICES.get(jurisdiction)
        if key is None:
            key = DEFAULT_GOAL_SERVICES.get(goal.goal_type)
        if key:
            wanted[index] = key
    known = await GovernanceGraphRepository(session).by_keys(sorted(set(wanted.values())))
    for goal in goals:
        if goal.service_key and goal.service_key not in known:
            raise UnprocessableEntity(
                f"'{goal.service_key}' is not a known government service",
                code="unknown_service",
            )
    rows = []
    for index, goal in enumerate(goals):
        node = known.get(wanted.get(index, ""))
        rows.append(
            {
                "goal_type": goal.goal_type,
                "title": goal.title or GOAL_TITLES[goal.goal_type],
                "description": goal.description,
                "priority": goal.priority,
                "status": goal.status,
                "target_date": goal.target_date,
                "governance_node_id": node.id if node else None,
            }
        )
    return rows


def _member_rows(members: list[HouseholdMemberIn]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="python") for m in members]


def _preference_rows(preferences: list[UserPreferenceIn]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    rows = []
    for pref in preferences:
        ident = (pref.category.value, pref.key)
        if ident in seen:
            raise UnprocessableEntity(
                f"Preference '{pref.category.value}.{pref.key}' is listed twice",
                code="duplicate_preference",
            )
        seen.add(ident)
        rows.append(
            {
                "category": pref.category,
                "key": pref.key,
                "value": pref.value,
                "source": FactSource.USER_STATED,
            }
        )
    return rows


async def _apply(
    session: AsyncSession,
    principal: Principal,
    *,
    display_name: str | None,
    fields: ProfileFields | None,
    household: list[HouseholdMemberIn] | None,
    goals: list[UserGoalIn] | None,
    preferences: list[UserPreferenceIn] | None,
    consents: UserPreferencesUpdate | None,
    complete_onboarding: bool,
) -> repo.ProfileBundle:
    user = await require_user(session, principal)
    if display_name is not None:
        user.display_name = display_name
    if consents is not None:
        user = await accounts.update_preferences(session, user, consents)
    if preferences is not None:
        _check_preferences(user, preferences)

    values = profile_values(fields) if fields is not None else {}
    if complete_onboarding:
        values["onboarding_completed_at"] = datetime.now(UTC)
    profile = await repo.upsert_profile(session, principal, values)

    if household is not None:
        await repo.replace_household(session, principal, _member_rows(household))
    if goals is not None:
        rows = await _goal_rows(session, goals, dict(profile.assumptions or {}))
        await repo.replace_goals(session, principal, rows)
    if preferences is not None:
        await repo.replace_preferences(session, principal, _preference_rows(preferences))
    elif consents is not None and _faith_consent(user) is not ConsentStatus.GRANTED:
        # Withdrawing faith consent removes what was stored under it.
        kept = [p for p in await repo.list_preferences(session, principal)]
        if any(p.category is PreferenceCategory.FAITH for p in kept):
            await repo.replace_preferences(
                session,
                principal,
                [
                    {"category": p.category, "key": p.key, "value": p.value, "source": p.source}
                    for p in kept
                    if p.category is not PreferenceCategory.FAITH
                ],
            )

    bundle = await repo.load_bundle(session, principal, user)
    await project_to_user_graph(session, principal, bundle)
    await session.flush()
    return await repo.load_bundle(session, principal, user)


async def onboard(
    session: AsyncSession, principal: Principal, request: OnboardingProfileRequest
) -> repo.ProfileBundle:
    return await _apply(
        session,
        principal,
        display_name=request.display_name,
        fields=request.profile,
        household=request.household,
        goals=request.goals,
        preferences=request.preferences,
        consents=request.consents,
        complete_onboarding=True,
    )


async def update(
    session: AsyncSession, principal: Principal, request: ProfileUpdate
) -> repo.ProfileBundle:
    return await _apply(
        session,
        principal,
        display_name=request.display_name,
        fields=request.profile,
        household=request.household,
        goals=request.goals,
        preferences=request.preferences,
        consents=request.consents,
        complete_onboarding=False,
    )


async def load(session: AsyncSession, principal: Principal) -> repo.ProfileBundle:
    return await repo.load_bundle(session, principal, await require_user(session, principal))


def missing_for_planning(bundle: repo.ProfileBundle) -> list[str]:
    missing = [
        name
        for name in PLANNING_FIELDS
        if bundle.profile is None or getattr(bundle.profile, name) is None
    ]
    if not bundle.goals:
        missing.append("goals")
    return missing


# --- user-graph projection ------------------------------------------------------------------


def _feature_projection() -> ProjectFn | None:
    try:
        module = importlib.import_module("app.personalization.onboarding")
    except ModuleNotFoundError as exc:
        if exc.name and "app.personalization.onboarding".startswith(exc.name):
            return None
        raise
    fn = getattr(module, "project_profile", None)
    return fn if callable(fn) else None


async def project_to_user_graph(
    session: AsyncSession, principal: Principal, bundle: repo.ProfileBundle
) -> None:
    feature = _feature_projection()
    if feature is not None:
        await feature(session, principal, bundle)
        return
    await _fallback_projection(session, principal, bundle)


def _short_hash(value: UUID) -> str:
    return hashlib.sha256(value.bytes).hexdigest()[:12]


def _facts(ref: str, **values: Any) -> dict[str, Any]:
    return {
        name: TwinFact(value=value, source=FactSource.USER_STATED, source_ref=ref).model_dump(
            mode="json"
        )
        for name, value in values.items()
        if value is not None
    }


_PROJECTED_PREFIXES = ("spouse.", "child.", "goal.", "company.")


async def _fallback_projection(
    session: AsyncSession, principal: Principal, bundle: repo.ProfileBundle
) -> None:
    graph = UserGraphRepository(session)
    existing, _, _ = await graph.graph()
    await graph.delete_nodes([n.key for n in existing if n.key.startswith(_PROJECTED_PREFIXES)])

    profile = bundle.profile
    ref = f"profile:user_profiles:{profile.id}" if profile else "profile:users"
    me = await graph.upsert_node(
        entity_type=TwinNodeType.PERSON.value,
        key="person.self",
        label=(profile.preferred_name if profile else None) or bundle.user.display_name or "You",
        properties=_facts(
            ref,
            occupation=profile.occupation if profile else None,
            persona=profile.persona if profile else None,
            nationality=profile.nationality if profile else None,
            arrival_date=profile.arrival_date.isoformat()
            if profile and profile.arrival_date
            else None,
        ),
    )
    if profile and profile.company_name:
        company = await graph.upsert_node(
            entity_type=TwinNodeType.COMPANY.value,
            key="company.self",
            label=profile.company_name,
            properties=_facts(
                ref,
                business_activity=profile.business_activity,
                jurisdiction=(profile.assumptions or {}).get("company.jurisdiction"),
            ),
        )
        await graph.link(GraphEdgeType.FOUNDER_OF, me, company)

    for member in bundle.household:
        entity = (
            TwinNodeType.SPOUSE
            if member.relationship is HouseholdRelationship.SPOUSE
            else TwinNodeType.CHILD
            if member.relationship is HouseholdRelationship.CHILD
            else None
        )
        if entity is None:
            continue
        node = await graph.upsert_node(
            entity_type=entity.value,
            key=f"{entity.value}.{_short_hash(member.id)}",
            label=member.name,
            properties=_facts(
                f"profile:household_members:{member.id}",
                relocation_plan=member.relocation_plan.value,
                nationality=member.nationality,
                needs_sponsorship=member.needs_sponsorship,
            ),
        )
        member.graph_node_id = node.id
        await graph.link(GraphEdgeType.HAS_HOUSEHOLD_MEMBER, me, node)

    governance = GovernanceGraphRepository(session)
    for goal in bundle.goals:
        node = await graph.upsert_node(
            entity_type=TwinNodeType.GOAL.value,
            key=f"goal.{goal.goal_type.value}.{_short_hash(goal.id)}",
            label=goal.title,
            properties=_facts(
                f"profile:user_goals:{goal.id}",
                goal_type=goal.goal_type.value,
                priority=goal.priority.value,
                target_date=goal.target_date.isoformat() if goal.target_date else None,
            ),
        )
        goal.graph_node_id = node.id
        await graph.link(GraphEdgeType.HAS_GOAL, me, node)
        if goal.governance_node_id is not None:
            services = await governance.by_ids([goal.governance_node_id])
            if services:
                await graph.link(GraphEdgeType.PURSUES, node, services[0])
