"""Read-only journey routes, used only when the journey-agent workstream's router
(`app.agents.journey.api`) is not installed. Creating and simulating journeys belongs to
that workstream."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import PrincipalDep, UserSession
from app.contracts.journey import JourneyOut, JourneySummary
from app.services import journeys
from app.services.presenters import journey_out, journey_summary

router = APIRouter(tags=["journey"])


@router.get("/journey", response_model=list[JourneySummary], summary="Your journeys, newest first")
async def list_journeys(principal: PrincipalDep, session: UserSession) -> list[JourneySummary]:
    rows = await journeys.list_journeys(session, principal)
    return [journey_summary(j, total, done) for j, total, done in rows]


@router.get("/journey/{journey_id}", response_model=JourneyOut, summary="One journey")
async def read_journey(
    journey_id: UUID, principal: PrincipalDep, session: UserSession
) -> JourneyOut:
    journey = await journeys.get_journey(session, principal, journey_id)
    nodes, edges = await journeys.journey_parts(session, journey)
    return journey_out(journey, nodes, edges)
