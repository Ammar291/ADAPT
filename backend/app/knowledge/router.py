"""Knowledge-layer routes. Public governance knowledge: no principal is needed, and the
sessions carry none, so row-level security keeps every private row invisible.

`router`       /knowledge/search, /knowledge/retrieve, /knowledge/explain
`graph_router` /graph/governance (the evidence-backed governance graph view)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, PublicSession
from app.knowledge.explain import explain
from app.knowledge.graph_view import governance_view
from app.knowledge.retrieval import match_nodes, retrieve
from app.knowledge.schemas import (
    ExplainRequest,
    ExplainResponse,
    KnowledgeGraphView,
    KnowledgeSearchResponse,
    KnowledgeTopic,
    RetrievalFilters,
    RetrieveRequest,
    RetrieveResponse,
    SourceType,
)
from app.knowledge.sources import SourceFamily

router = APIRouter(tags=["knowledge"])
graph_router = APIRouter(tags=["governance"])


@router.get(
    "/knowledge/search",
    response_model=KnowledgeSearchResponse,
    summary="Search official sources and governance entities",
)
async def search_knowledge(
    session: PublicSession,
    container: ContainerDep,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    k: Annotated[int, Query(ge=1, le=20)] = 8,
    node: Annotated[
        list[str] | None, Query(description="Scope to passages cited by these governance keys")
    ] = None,
    authority: Annotated[list[str] | None, Query(description="Publisher keys")] = None,
    family: Annotated[list[SourceFamily] | None, Query()] = None,
    source_type: Annotated[list[SourceType] | None, Query()] = None,
    topic: Annotated[list[KnowledgeTopic] | None, Query()] = None,
    official_only: bool = True,
    max_age_days: Annotated[int | None, Query(ge=1, le=3650)] = None,
) -> KnowledgeSearchResponse:
    filters = RetrievalFilters(
        authorities=authority or [],
        source_families=family or [],
        source_types=source_type or [],
        topics=topic or [],
        governance_keys=node or [],
        official_only=official_only,
        max_age_days=max_age_days,
    )
    embedder = container.adapters.embeddings
    found = await retrieve(session, embedder, q, filters=filters, top_k=k)
    nodes = await match_nodes(
        session, q, evidence=found.evidence, require_lexical=embedder.mode == "demo"
    )
    return KnowledgeSearchResponse(
        query=q, results=found.evidence, nodes=nodes, retrieval=found.retrieval
    )


@router.post(
    "/knowledge/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve ranked official evidence for a query (for agents)",
)
async def retrieve_knowledge(
    body: RetrieveRequest, session: PublicSession, container: ContainerDep
) -> RetrieveResponse:
    return await retrieve(
        session,
        container.adapters.embeddings,
        body.query,
        filters=body.filters,
        top_k=body.top_k,
        min_score=body.min_score,
    )


@router.post(
    "/knowledge/explain",
    response_model=ExplainResponse,
    summary="Explain a requirement for given user facts: graph, evidence, checks, next step",
)
async def explain_requirement(
    body: ExplainRequest, session: PublicSession, container: ContainerDep
) -> ExplainResponse:
    return await explain(session, container.adapters.embeddings, body)


@graph_router.get(
    "/graph/governance",
    response_model=KnowledgeGraphView,
    summary="Governance knowledge graph with its supporting sources and evidence",
)
async def governance_graph(
    session: PublicSession,
    type: Annotated[list[str] | None, Query(description="Entity types to include")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    focus: Annotated[str | None, Query(description="Node key to centre on")] = None,
    depth: Annotated[int, Query(ge=1, le=4)] = 1,
    include_sources: bool = True,
) -> KnowledgeGraphView:
    return await governance_view(
        session,
        entity_types=type,
        q=q,
        focus=focus,
        depth=depth,
        include_sources=include_sources,
    )
