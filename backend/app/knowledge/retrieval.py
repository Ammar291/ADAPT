"""Hybrid retrieval over the governance corpus, returning ranked `Evidence`.

1. Candidates: semantic kNN (`similarity_search`, pgvector cosine, same embedder only)
   and lexical matches (`content_tsv @@ tsquery`, any expanded query term).
2. Filters: live versions only, then publisher / family / source type / topic / language
   / freshness / official-only / governance-node scope. Trust-related filters use the
   family derived from the URL, never stored labels.
3. Fusion: weighted score fusion of the two lists (BM25-heavy with the demo embedder).
4. Ranking: relevance x source priority x freshness; at most 3 passages per page.
5. Top-k `Evidence`, each listing the governance nodes it supports.

If the embedder is unreachable (no network, no key) retrieval degrades to lexical-only
and says so in `RetrievalInfo`. The corpus itself is always local.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, literal_column, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings import Embedder
from app.core.errors import UpstreamError
from app.db.models.governance import GovernanceChunk, GovernanceDocument
from app.db.models.graph import GraphEdge, GraphEdgeEvidence, GraphNode, GraphNodeEvidence
from app.domain.enums import GraphType
from app.knowledge.corpus import DEFAULT_STALE_AFTER_DAYS, assess_freshness
from app.knowledge.evidence import PassageView, build_evidence
from app.knowledge.ranking import (
    RankItem,
    bm25,
    embedding_text,
    expand_terms,
    fuse,
    lexical_query,
    query_terms,
    rank,
    tokenize,
    tsquery_term,
    weighted_terms,
)
from app.knowledge.schemas import (
    Evidence,
    Freshness,
    NodeMatch,
    RetrievalFilters,
    RetrievalInfo,
    RetrieveResponse,
)
from app.knowledge.sources import classify_source
from app.repositories.governance_corpus import similarity_search

logger = logging.getLogger("adapt.knowledge.retrieval")
CANDIDATE_POOL = 60
LEXICAL_CANDIDATES = 400
# Fusion weights. The demo embedder hashes words (no semantics, no IDF), so in demo mode
# BM25 carries most of the weight; with a semantic embedder the two share it equally.
DEMO_VECTOR_WEIGHT = 0.25


def passage_view(chunk: GovernanceChunk, document: GovernanceDocument) -> PassageView:
    meta: dict[str, Any] = chunk.metadata_ or {}
    doc_meta: dict[str, Any] = document.metadata_ or {}
    excerpt = meta.get("excerpt")
    verification = meta.get("verification") or doc_meta.get("verification")
    return PassageView(
        document_id=document.id,
        chunk_id=chunk.id,
        content=chunk.content,
        source_url=document.source_url,
        title=document.title,
        authority=document.authority,
        retrieved_at=document.retrieved_at,
        effective_date=document.effective_date,
        superseded_at=document.superseded_at,
        section_or_page=chunk.page_or_section or chunk.section,
        # Unknown provenance is treated as the weaker option, never the stronger one.
        excerpt="quote" if excerpt == "quote" else "paraphrase",
        states_requirement=bool(meta.get("states_requirement")),
        verification="fetched" if verification == "fetched" else "search_snippet",
        topics=tuple(meta.get("topics") or doc_meta.get("topics") or ()),
    )


@dataclass
class _Candidate:
    chunk: GovernanceChunk
    document: GovernanceDocument
    view: PassageView


def _passes(
    candidate: _Candidate, filters: RetrievalFilters, now: datetime, stale_after_days: int
) -> tuple[bool, bool]:
    """(keep?, dropped for staleness?)"""
    view, document = candidate.view, candidate.document
    source = classify_source(view.source_url, view.authority)
    if filters.official_only and not source.is_official:
        return False, False
    if filters.authorities and view.authority not in filters.authorities:
        return False, False
    if filters.source_families and source.family not in filters.source_families:
        return False, False
    if filters.source_types and document.document_type not in filters.source_types:
        return False, False
    if filters.languages and document.language not in filters.languages:
        return False, False
    if filters.topics and not set(view.topics) & {t.value for t in filters.topics}:
        return False, False
    if filters.max_age_days is not None and now - view.retrieved_at > timedelta(
        days=filters.max_age_days
    ):
        return False, True
    if not filters.include_stale and (
        assess_freshness(view.retrieved_at, now=now, stale_after_days=stale_after_days)
        is Freshness.STALE
    ):
        return False, True
    return True, False


async def scoped_chunk_ids(session: AsyncSession, keys: Sequence[str]) -> set[UUID]:
    """Chunks cited by the given governance nodes or by relationships touching them."""
    nodes = select(GraphNode.id).where(
        GraphNode.graph_type == GraphType.GOVERNANCE, GraphNode.key.in_(list(keys))
    )
    by_node = select(GraphNodeEvidence.chunk_id).where(GraphNodeEvidence.node_id.in_(nodes))
    by_edge = (
        select(GraphEdgeEvidence.chunk_id)
        .join(GraphEdge, GraphEdge.id == GraphEdgeEvidence.edge_id)
        .where(or_(GraphEdge.source_node_id.in_(nodes), GraphEdge.target_node_id.in_(nodes)))
    )
    rows = await session.execute(union(by_node, by_edge))
    return {chunk_id for (chunk_id,) in rows if chunk_id is not None}


async def governance_keys_by_chunk(
    session: AsyncSession, chunk_ids: Sequence[UUID]
) -> dict[UUID, list[str]]:
    """chunk -> keys of the governance nodes whose facts (or relationships) it supports."""
    if not chunk_ids:
        return {}
    live = or_(GraphNode.valid_to.is_(None), GraphNode.valid_to > func.current_date())
    by_node = (
        select(GraphNodeEvidence.chunk_id, GraphNode.key)
        .join(GraphNode, GraphNode.id == GraphNodeEvidence.node_id)
        .where(GraphNodeEvidence.chunk_id.in_(list(chunk_ids)), live)
    )
    by_edge = (
        select(GraphEdgeEvidence.chunk_id, GraphNode.key)
        .join(GraphEdge, GraphEdge.id == GraphEdgeEvidence.edge_id)
        .join(
            GraphNode,
            or_(GraphNode.id == GraphEdge.source_node_id, GraphNode.id == GraphEdge.target_node_id),
        )
        .where(GraphEdgeEvidence.chunk_id.in_(list(chunk_ids)), live)
    )
    result: dict[UUID, set[str]] = {}
    for chunk_id, key in await session.execute(union(by_node, by_edge)):
        if chunk_id is not None:
            result.setdefault(chunk_id, set()).add(key)
    return {chunk_id: sorted(keys) for chunk_id, keys in result.items()}


async def _lexical(
    session: AsyncSession, query: str, filters: RetrievalFilters, limit: int
) -> list[tuple[GovernanceChunk, GovernanceDocument, float]]:
    """Candidates matching any expanded term (tsvector), ranked by BM25 with corpus-wide
    document frequencies."""
    terms = query_terms(query)
    weights = weighted_terms(terms)
    expression = lexical_query(query)
    if expression is None:
        return []
    tsquery = func.to_tsquery(literal_column("'simple'::regconfig"), expression)
    live = GovernanceDocument.superseded_at.is_(None)
    stmt = (
        select(GovernanceChunk, GovernanceDocument)
        .join(GovernanceDocument, GovernanceDocument.id == GovernanceChunk.document_id)
        .where(live, GovernanceChunk.content_tsv.op("@@")(tsquery))
        .order_by(func.ts_rank_cd(GovernanceChunk.content_tsv, tsquery).desc())
        .limit(LEXICAL_CANDIDATES)
    )
    if filters.authorities:
        stmt = stmt.where(GovernanceDocument.authority.in_(filters.authorities))
    if filters.source_types:
        stmt = stmt.where(
            GovernanceDocument.document_type.in_([t.value for t in filters.source_types])
        )
    rows = list(await session.execute(stmt))
    if not rows:
        return []

    def term_query(key: str) -> Any:
        return func.to_tsquery(literal_column("'simple'::regconfig"), tsquery_term(key))

    counts = (
        await session.execute(
            select(
                func.count(),
                *(
                    func.count().filter(GovernanceChunk.content_tsv.op("@@")(term_query(t)))
                    for t in weights
                ),
            )
            .select_from(GovernanceChunk)
            .join(GovernanceDocument, GovernanceDocument.id == GovernanceChunk.document_id)
            .where(live)
        )
    ).one()
    n_docs, df = counts[0], dict(zip(weights, counts[1:], strict=True))
    by_id = {chunk.id: (chunk, document) for chunk, document in rows}
    tokens = {chunk.id: tokenize(f"{chunk.context or ''} {chunk.content}") for chunk, _ in rows}
    scored = bm25(tokens, weights, df, n_docs)[:limit]
    return [(*by_id[chunk_id], score) for chunk_id, score in scored]


async def retrieve(
    session: AsyncSession,
    embedder: Embedder,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    top_k: int = 8,
    min_score: float | None = None,
    now: datetime | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> RetrieveResponse:
    filters = filters or RetrievalFilters()
    now = now or datetime.now(UTC)
    pool = max(top_k * 6, CANDIDATE_POOL)
    note: str | None = None

    vector_rows: list[tuple[GovernanceChunk, GovernanceDocument, float]] = []
    vector_ran = False
    try:
        [vector] = await embedder.embed([embedding_text(query)])
        vector_rows = [
            (chunk, document, 1.0 - float(distance))
            for chunk, document, distance in await similarity_search(
                session,
                vector,
                k=pool,
                embedding_model=embedder.model_id,
                authorities=filters.authorities or None,
                document_types=[t.value for t in filters.source_types] or None,
            )
        ]
        vector_ran = True
    except UpstreamError:
        note = "Semantic search is unavailable right now; results use keyword matching only."
        logger.warning("query embedding failed; lexical retrieval only")
    lexical_rows = await _lexical(session, query, filters, pool)

    scope = (
        await scoped_chunk_ids(session, filters.governance_keys)
        if filters.governance_keys
        else None
    )
    candidates: dict[UUID, _Candidate] = {}
    filtered_stale = 0

    def admit(
        rows: list[tuple[GovernanceChunk, GovernanceDocument, float]],
    ) -> list[tuple[UUID, float]]:
        nonlocal filtered_stale
        admitted: list[tuple[UUID, float]] = []
        for chunk, document, score in rows:
            if document.superseded_at is not None or (scope is not None and chunk.id not in scope):
                continue
            candidate = candidates.get(chunk.id) or _Candidate(
                chunk, document, passage_view(chunk, document)
            )
            keep, stale = _passes(candidate, filters, now, stale_after_days)
            if not keep:
                filtered_stale += stale
                continue
            candidates[chunk.id] = candidate
            admitted.append((chunk.id, score))
        return admitted

    vector_hits = admit(vector_rows)
    lexical_hits = admit(lexical_rows)
    demo = embedder.mode == "demo"
    relevance = fuse(
        vector_hits,
        lexical_hits,
        vector_weight=DEMO_VECTOR_WEIGHT if demo else 0.5,
        lexical_weight=1 - DEMO_VECTOR_WEIGHT if demo else 0.5,
    )
    if demo:
        # Hashed "embeddings" are not semantic: every query has nearest neighbours, even
        # gibberish. They may re-rank keyword matches but never admit a passage alone.
        lexical_ids = {chunk_id for chunk_id, _ in lexical_hits}
        relevance = {k: v for k, v in relevance.items() if k in lexical_ids}

    items = []
    for chunk_id, score in relevance.items():
        view = candidates[chunk_id].view
        items.append(
            RankItem(
                key=chunk_id,
                group=view.document_id,
                relevance=score,
                priority=classify_source(view.source_url, view.authority).priority,
                freshness=assess_freshness(
                    view.retrieved_at, now=now, stale_after_days=stale_after_days
                ),
                retrieved_at=view.retrieved_at,
            )
        )
    ranked = rank(items, top_k=top_k, min_score=min_score)
    ranked_ids = [cast(UUID, item.key) for item, _ in ranked]
    keys_by_chunk = await governance_keys_by_chunk(session, ranked_ids)
    evidence = [
        build_evidence(
            candidates[chunk_id].view,
            now=now,
            stale_after_days=stale_after_days,
            score=score,
            rank=position,
            governance_keys=keys_by_chunk.get(chunk_id, []),
        )
        for position, (chunk_id, (_, score)) in enumerate(zip(ranked_ids, ranked, strict=True), 1)
    ]
    if vector_ran and vector_hits and lexical_hits:
        mode = "hybrid"
    elif vector_ran and vector_hits:
        mode = "vector"
    elif lexical_hits:
        mode = "lexical"
    else:
        mode = "hybrid" if vector_ran else "lexical"
    return RetrieveResponse(
        query=query,
        evidence=evidence,
        retrieval=RetrievalInfo(
            mode=mode,
            embedding_model=embedder.model_id if vector_ran else None,
            candidates=len(candidates),
            filtered_stale=filtered_stale,
            note=note,
        ),
        applied_filters=filters,
    )


# --- governance node matching ---------------------------------------------------------------


def score_node(
    label: str, summary: str | None, aliases: Sequence[str], terms: Sequence[str]
) -> float:
    """Lexical match of expanded query terms against a node's label, aliases and summary."""
    if not terms:
        return 0.0
    fields = (
        (set(query_terms(label)), 3.0),
        ({t for alias in aliases for t in query_terms(str(alias))}, 2.0),
        (set(query_terms(summary or "")), 1.0),
    )
    total = 0.0
    for term in terms:
        best = 0.0
        for words, weight in fields:
            if term in words or (len(term) >= 5 and any(w.startswith(term) for w in words)):
                best = max(best, weight)
        total += best
    return total / (3.0 * len(terms))


async def match_nodes(
    session: AsyncSession,
    query: str,
    *,
    evidence: Sequence[Evidence] = (),
    types: Sequence[str] | None = None,
    limit: int = 5,
    require_lexical: bool = False,
) -> list[NodeMatch]:
    """Governance nodes for a query: lexical match on the node itself, boosted by the nodes
    that the best retrieved passages support (so semantic hits carry over). With
    `require_lexical` (demo embedder), a node needs at least one matching word."""
    stmt = select(GraphNode).where(
        GraphNode.graph_type == GraphType.GOVERNANCE,
        or_(GraphNode.valid_to.is_(None), GraphNode.valid_to > func.current_date()),
    )
    if types:
        stmt = stmt.where(GraphNode.entity_type.in_(list(types)))
    nodes = list((await session.execute(stmt)).scalars())
    terms = query_terms(query)
    expanded = expand_terms(terms)
    votes: dict[str, float] = {}
    for position, item in enumerate(evidence):
        for key in item.governance_keys:
            votes[key] = votes.get(key, 0.0) + 1.0 / (position + 2)
    top_vote = max(votes.values(), default=0.0) or 1.0
    scored = []
    for node in nodes:
        aliases = (node.properties_json or {}).get("aliases") or []
        lexical = max(
            score_node(node.label, node.summary, aliases, terms),
            0.8 * score_node(node.label, node.summary, aliases, expanded),
        )
        if require_lexical and lexical == 0:
            continue
        score = 0.7 * lexical + 0.3 * (votes.get(node.key, 0.0) / top_vote)
        if score > 0.05:
            scored.append((score, node))
    scored.sort(key=lambda pair: (-pair[0], pair[1].entity_type != "service", pair[1].label))
    return [
        NodeMatch(
            id=node.id,
            key=node.key,
            entity_type=node.entity_type,
            label=node.label,
            summary=node.summary,
            official_url=node.official_url,
            score=round(score, 4),
        )
        for score, node in scored[:limit]
    ]
