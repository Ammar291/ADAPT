"""Projection of the onboarding profile into the private user graph.

The profile tables (`user_profiles`, `household_members`, `user_goals`, `user_preferences`)
are the canonical record of what the person said during onboarding. After every profile
save, `project_profile` rewrites the user-stated facts they imply, in the same
transaction:

* each fact carries `source_ref = 'profile:<table>:<row id>'`;
* facts from rows that no longer exist (or no longer say it) are removed, and bare
  entities pruned;
* a value that came from somewhere else (a document or a direct statement) is never
  overwritten by the profile: the more specific source wins.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.db.models import GraphNode
from app.db.models.user_data import ExtractedFact
from app.domain.enums import FactSource, GraphEdgeType, GraphType
from app.domain.principal import Principal
from app.personalization.facts import USER_ENTRY
from app.personalization.store import UserGraph
from app.personalization.vocabulary import FactRuleError, UserEntityType, identity_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.repositories.profile import ProfileBundle

logger = logging.getLogger(__name__)
E = UserEntityType

GOAL_KINDS = {
    "establish_company": "start_company",
    "residency": "relocate",
    "sponsor_family": "sponsor_family",
    "find_housing": "find_housing",
    "schooling": "find_school",
    "community": "find_community",
    "employment": "find_job",
}
MOVING = {"with_user": True, "later": True, "already_in_uae": True, "not_relocating": False}
BUDGET_WORDS = (
    ("hous", "housing"),
    ("rent", "housing"),
    ("school", "schooling"),
    ("relocat", "relocation"),
    ("business", "business_setup"),
    ("setup", "business_setup"),
)
HOUSING_KEYS = {
    "area": "preferred_area",
    "preferred_area": "preferred_area",
    "property_type": "property_type",
    "bedrooms": "bedrooms",
    "tenure": "tenure",
    "move_in_date": "move_in_date",
}


def _value(raw: Any) -> Any:
    return raw.value if hasattr(raw, "value") else raw


class _Projection:
    def __init__(self, graph: UserGraph) -> None:
        self.graph = graph
        self.written: set[UUID] = set()

    async def put(self, node: GraphNode, attribute: str, value: Any, ref: str) -> None:
        if value is None or value == "" or value == []:
            return
        current = next(
            (f for f in await self.graph.facts(node_ids=[node.id]) if f.attribute == attribute),
            None,
        )
        if current is not None and not (current.source_ref or "").startswith("profile:"):
            return  # a document or a direct statement is more specific than the profile
        try:
            fact = await self.graph.write_fact(
                node,
                attribute,
                value,
                source=FactSource.USER_STATED,
                source_ref=ref,
                extraction_method=USER_ENTRY,
                confirmed=True,
            )
        except FactRuleError:
            logger.info(
                "profile_fact_skipped",
                extra={"entity_type": node.entity_type, "attribute": attribute},
            )
            return
        self.written.add(fact.id)

    async def entity(
        self, entity_type: UserEntityType, *, parent: GraphNode | None = None, instance: Any = None
    ) -> GraphNode:
        token = identity_token(instance) if instance not in (None, "") else None
        return await self.graph.ensure_node(entity_type, parent=parent, instance=token)

    async def nationality(self, holder: GraphNode, code: str | None, ref: str) -> None:
        if code:
            node = await self.entity(E.NATIONALITY, parent=holder, instance=code)
            await self.put(node, "country", code, ref)


async def project_profile(
    session: AsyncSession, principal: Principal, bundle: ProfileBundle
) -> None:
    graph = UserGraph(session)
    if graph.principal.user_id != principal.user_id:
        raise PermissionError("session and principal belong to different users")
    p = _Projection(graph)
    hub = await graph.hub()

    profile = bundle.profile
    if profile is not None:
        ref = f"profile:user_profiles:{profile.id}"
        await p.put(hub, "date_of_birth", profile.date_of_birth, ref)
        await p.put(hub, "occupation", profile.occupation, ref)
        await p.put(hub, "current_country", profile.country_of_residence, ref)
        if profile.monthly_income_aed is not None:
            income = {"amount": profile.monthly_income_aed, "currency": "AED"}
            await p.put(hub, "monthly_income", income, ref)
        await p.nationality(hub, profile.nationality, ref)
        if profile.arrival_date is not None:
            household = await p.entity(E.HOUSEHOLD)
            await p.put(household, "planned_arrival_date", profile.arrival_date, ref)
        for language in profile.languages or []:
            node = await p.entity(E.LANGUAGE, instance=language.split("-")[0].lower())
            await p.put(node, "language", language, ref)
        jurisdiction = (profile.assumptions or {}).get("company.jurisdiction")
        if profile.company_name or profile.business_activity or jurisdiction:
            company = await p.entity(E.COMPANY, instance=profile.company_name or "profile")
            await p.put(company, "name", profile.company_name, ref)
            await p.put(company, "jurisdiction", jurisdiction, ref)
            if profile.business_activity:
                activity = await p.entity(
                    E.BUSINESS_ACTIVITY, parent=company, instance=profile.business_activity
                )
                await p.put(activity, "description", profile.business_activity, ref)

    for member in bundle.household:
        ref = f"profile:household_members:{member.id}"
        relationship = _value(member.relationship)
        if relationship == "spouse":
            node = await p.entity(E.SPOUSE)
        elif relationship == "child":
            node = await p.entity(E.CHILD, instance=member.name)
        else:
            continue  # only spouses and children are part of the twin's vocabulary
        await p.put(node, "full_name", member.name, ref)
        await p.put(node, "date_of_birth", member.date_of_birth, ref)
        await p.put(node, "moving_with_user", MOVING.get(_value(member.relocation_plan)), ref)
        await p.nationality(node, member.nationality, ref)
        member.graph_node_id = node.id

    for goal in bundle.goals:
        if _value(goal.status) in ("achieved", "dropped"):
            continue
        ref = f"profile:user_goals:{goal.id}"
        kind = GOAL_KINDS.get(_value(goal.goal_type), "other")
        node = await p.entity(E.GOAL, instance=kind if kind != "other" else f"goal:{goal.id}")
        await p.put(node, "kind", kind, ref)
        await p.put(node, "description", goal.title, ref)
        await p.put(node, "target_date", goal.target_date, ref)
        await p.put(node, "priority", _value(goal.priority), ref)
        goal.graph_node_id = node.id
        service_key = getattr(goal, "service_key", None)
        if service_key:
            service = (
                await session.execute(
                    select(GraphNode).where(
                        GraphNode.graph_type == GraphType.GOVERNANCE, GraphNode.key == service_key
                    )
                )
            ).scalar_one_or_none()
            if service is not None:
                await graph.link(GraphEdgeType.PURSUES, node, service)

    for pref in bundle.preferences:
        ref = f"profile:user_preferences:{pref.id}"
        category, key, value = _value(pref.category), pref.key, pref.value
        pref_node: GraphNode | None = None
        if category == "housing" and key in HOUSING_KEYS:
            pref_node = await p.entity(E.HOUSING_PREFERENCE)
            await p.put(pref_node, HOUSING_KEYS[key], value, ref)
        elif category == "budget" and isinstance(value, int | float | dict):
            budget_for = next((c for word, c in BUDGET_WORDS if word in key), "living")
            pref_node = await p.entity(E.BUDGET, instance=budget_for)
            await p.put(pref_node, "category", budget_for, ref)
            amount = value if isinstance(value, dict) else {"amount": value, "currency": "AED"}
            await p.put(pref_node, "amount", amount, ref)
            period = (
                "monthly"
                if "month" in key
                else "yearly"
                if "year" in key or "annual" in key
                else None
            )
            await p.put(pref_node, "period", period, ref)
        elif category == "language":
            for language in value if isinstance(value, list) else [value]:
                pref_node = await p.entity(E.LANGUAGE, instance=str(language).split("-")[0].lower())
                await p.put(pref_node, "language", language, ref)
        elif category == "community":
            for interest in value if isinstance(value, list) else [value]:
                pref_node = await p.entity(E.COMMUNITY_PREFERENCE, instance=str(interest))
                await p.put(pref_node, "interest", str(interest), ref)
        elif category == "faith":
            pref_node = await p.entity(E.COMMUNITY_PREFERENCE, instance="faith")
            await p.put(pref_node, "faith_community", str(value), ref)
        else:
            pref_node = await p.entity(E.PREFERENCE, instance=f"{category}:{key}")
            await p.put(pref_node, "topic", key.replace("_", " ").capitalize(), ref)
            await p.put(pref_node, "value", value if isinstance(value, str) else str(value), ref)
        if pref_node is not None:
            pref.graph_node_id = pref_node.id

    # The profile is canonical: drop what it no longer says, then bare entities.
    stale = [
        f.id
        for f in await graph.facts()
        if (f.source_ref or "").startswith("profile:") and f.id not in p.written
    ]
    if stale:
        await graph.delete_facts(ExtractedFact.id.in_(stale))
    await graph.prune()
    for node in await graph.nodes():
        await graph.refresh_label(node)
