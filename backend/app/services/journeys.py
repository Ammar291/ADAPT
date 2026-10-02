"""Reading stored journeys, and the small write helpers other workstreams share.

Journey *planning* (creation, simulation, the agent) belongs to `app.agents.journey`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.db.models import GraphNode, Journey, JourneyEdge, JourneyNode
from app.domain.enums import JourneyStatus, StepCategory, StepStatus
from app.domain.principal import Principal
from app.domain.provenance import Provenance
from app.repositories.graph import GovernanceGraphRepository


async def get_journey(session: AsyncSession, principal: Principal, journey_id: UUID) -> Journey:
    journey = (
        await session.execute(
            select(Journey).where(Journey.id == journey_id, Journey.user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    if journey is None:
        raise NotFound("Journey not found", code="journey_not_found")
    return journey


async def journey_parts(
    session: AsyncSession, journey: Journey
) -> tuple[list[JourneyNode], list[JourneyEdge]]:
    nodes = list(
        (
            await session.execute(
                select(JourneyNode)
                .where(JourneyNode.journey_id == journey.id)
                .order_by(JourneyNode.position, JourneyNode.key)
            )
        ).scalars()
    )
    edges = list(
        (
            await session.execute(select(JourneyEdge).where(JourneyEdge.journey_id == journey.id))
        ).scalars()
    )
    return nodes, edges


async def journey_graph(
    session: AsyncSession, principal: Principal, journey_id: UUID
) -> tuple[Journey, list[JourneyNode], list[JourneyEdge], list[GraphNode]]:
    journey = await get_journey(session, principal, journey_id)
    nodes, edges = await journey_parts(session, journey)
    governance_ids = [n.governance_node_id for n in nodes if n.governance_node_id is not None]
    governance = await GovernanceGraphRepository(session).by_ids(governance_ids)
    return journey, nodes, edges, governance


async def list_journeys(
    session: AsyncSession, principal: Principal
) -> list[tuple[Journey, int, int]]:
    """(journey, node count, finished node count), most recently updated first."""
    done = func.count().filter(
        JourneyNode.status.in_([StepStatus.DONE.value, StepStatus.NOT_APPLICABLE.value])
    )
    rows = await session.execute(
        select(Journey, func.count(JourneyNode.id), done)
        .outerjoin(JourneyNode, JourneyNode.journey_id == Journey.id)
        .where(Journey.user_id == principal.user_id)
        .group_by(Journey.id)
        .order_by(Journey.updated_at.desc())
    )
    return [(journey, int(total), int(finished)) for journey, total, finished in rows]


async def latest_active_journey(session: AsyncSession, principal: Principal) -> Journey | None:
    return (
        await session.execute(
            select(Journey)
            .where(
                Journey.user_id == principal.user_id,
                Journey.status.in_([JourneyStatus.ACTIVE.value, JourneyStatus.DRAFT.value]),
            )
            .order_by(Journey.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def add_journey_node(
    session: AsyncSession,
    principal: Principal,
    *,
    journey_id: UUID | None,
    title: str,
    summary: str,
    category: StepCategory,
    provenance: Provenance,
    source_ref: str,
) -> UUID:
    """Append a standalone node (e.g. a saved research result) to a journey.

    `journey_id=None` means the user's most recent active journey.
    """
    journey = (
        await get_journey(session, principal, journey_id)
        if journey_id is not None
        else await latest_active_journey(session, principal)
    )
    if journey is None:
        raise NotFound("You don't have a journey yet", code="journey_not_found")
    position = (
        await session.execute(
            select(func.coalesce(func.max(JourneyNode.position), -1)).where(
                JourneyNode.journey_id == journey.id
            )
        )
    ).scalar_one()
    key = f"added.{source_ref.replace(':', '_').lower()}"[:160]
    existing = (
        await session.execute(
            select(JourneyNode).where(JourneyNode.journey_id == journey.id, JourneyNode.key == key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    node = JourneyNode(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        journey_id=journey.id,
        key=key,
        kind="added",
        title=title,
        summary=summary,
        category=category,
        status=StepStatus.READY,
        position=int(position) + 1,
        provenance=provenance.model_dump(mode="json"),
        details={"source_ref": source_ref},
    )
    session.add(node)
    await session.flush()
    return node.id
