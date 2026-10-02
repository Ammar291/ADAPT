"""Graph endpoints.

* `/graph/governance*` serve only the shared governance graph, on a session WITHOUT a
  principal — RLS then makes user-graph rows invisible even if a query were wrong.
* `/graph/user` serves only the caller's private graph.
* `/graph/journey/{id}` serves one of the caller's journeys as a graph.

The governance and user-graph routers are fallbacks: when the knowledge or
personalization workstream is installed, `app.api.router` mounts theirs instead.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import PrincipalDep, PublicSession, UserSession
from app.contracts.graph import (
    GovernanceGraphView,
    GovernanceNodeDetail,
    JourneyGraphView,
    TwinGraphView,
)
from app.core.errors import NotFound
from app.domain.enums import GovernanceNodeType
from app.repositories.graph import GovernanceGraphRepository, UserGraphRepository
from app.services import journeys
from app.services.presenters import (
    edge_out,
    governance_graph_out,
    governance_node_out,
    journey_graph_out,
    twin_graph_out,
)

governance_router = APIRouter(tags=["graph"])
user_router = APIRouter(tags=["graph"])
journey_router = APIRouter(tags=["graph"])


@governance_router.get(
    "/graph/governance",
    response_model=GovernanceGraphView,
    summary="Shared governance knowledge graph",
)
async def governance_graph(
    session: PublicSession,
    type: Annotated[list[GovernanceNodeType] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> GovernanceGraphView:
    repo = GovernanceGraphRepository(session)
    nodes = await repo.nodes(types=type, search=q)
    edges = await repo.edges_between([n.id for n in nodes])
    return governance_graph_out(nodes, edges)


@governance_router.get(
    "/graph/governance/nodes/{ref}",
    response_model=GovernanceNodeDetail,
    summary="A governance node (by id or key) with its direct neighbours",
)
async def governance_node(ref: str, session: PublicSession) -> GovernanceNodeDetail:
    repo = GovernanceGraphRepository(session)
    node = await repo.get(ref)
    if node is None:
        raise NotFound("No governance node matches that reference")
    neighbours, edges = await repo.neighbourhood(node.id)
    return GovernanceNodeDetail(
        node=governance_node_out(node),
        neighbours=[governance_node_out(n) for n in neighbours],
        edges=[edge_out(e) for e in edges],
    )


@user_router.get("/graph/user", response_model=TwinGraphView, summary="Your private user graph")
async def user_graph(session: UserSession) -> TwinGraphView:
    user_nodes, linked, edges = await UserGraphRepository(session).graph()
    return twin_graph_out(user_nodes, linked, edges)


@journey_router.get(
    "/graph/journey/{journey_id}",
    response_model=JourneyGraphView,
    summary="One of your journeys as a dependency graph",
)
async def journey_graph(
    journey_id: UUID, principal: PrincipalDep, session: UserSession
) -> JourneyGraphView:
    journey, nodes, edges, governance = await journeys.journey_graph(session, principal, journey_id)
    return journey_graph_out(journey, nodes, edges, governance)
