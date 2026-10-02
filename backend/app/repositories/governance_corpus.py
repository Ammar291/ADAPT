"""Low-level retrieval over the governance corpus (pgvector).

`similarity_search` is the primitive: cosine k-nearest-neighbours over
`governance_chunks.embedding`, restricted to chunks embedded by the same embedder
(`embedding_model`) and to live document versions (`superseded_at IS NULL`). Ranking,
hybrid lexical fusion and evidence objects are built on top of it by the knowledge layer
(`app.knowledge`).

The corpus is public: these queries run on any session and never touch private tables.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GovernanceChunk, GovernanceDocument

ChunkHit = tuple[GovernanceChunk, GovernanceDocument, float]


def _filters(authorities: Sequence[str] | None, document_types: Sequence[str] | None) -> list[Any]:
    clauses: list[Any] = [GovernanceDocument.superseded_at.is_(None)]
    if authorities:
        clauses.append(GovernanceDocument.authority.in_(list(authorities)))
    if document_types:
        clauses.append(GovernanceDocument.document_type.in_(list(document_types)))
    return clauses


async def similarity_search(
    session: AsyncSession,
    query_embedding: Sequence[float],
    *,
    k: int = 8,
    embedding_model: str,
    authorities: Sequence[str] | None = None,
    document_types: Sequence[str] | None = None,
) -> list[ChunkHit]:
    """Nearest chunks first, as (chunk, document, cosine distance in [0, 2])."""
    distance = GovernanceChunk.embedding.cosine_distance(list(query_embedding)).label("distance")
    query = (
        select(GovernanceChunk, GovernanceDocument, distance)
        .join(GovernanceDocument, GovernanceDocument.id == GovernanceChunk.document_id)
        .where(
            GovernanceChunk.embedding.is_not(None),
            GovernanceChunk.embedding_model == embedding_model,
            *_filters(authorities, document_types),
        )
        .order_by(distance)
        .limit(max(1, min(k, 100)))
    )
    rows = await session.execute(query)
    return [(chunk, document, float(dist)) for chunk, document, dist in rows]


async def lexical_search(
    session: AsyncSession,
    query_text: str,
    *,
    k: int = 8,
    authorities: Sequence[str] | None = None,
    document_types: Sequence[str] | None = None,
) -> list[tuple[GovernanceChunk, GovernanceDocument, float]]:
    """Full-text match on `content_tsv` ('simple' config), best `ts_rank` first. Used when
    no chunk was embedded with the current embedder, or fused with vector hits."""
    tsquery = func.websearch_to_tsquery("simple", query_text)
    rank = func.ts_rank(GovernanceChunk.content_tsv, tsquery).label("rank")
    query = (
        select(GovernanceChunk, GovernanceDocument, rank)
        .join(GovernanceDocument, GovernanceDocument.id == GovernanceChunk.document_id)
        .where(
            GovernanceChunk.content_tsv.op("@@")(tsquery), *_filters(authorities, document_types)
        )
        .order_by(rank.desc())
        .limit(max(1, min(k, 100)))
    )
    rows = await session.execute(query)
    return [(chunk, document, float(score)) for chunk, document, score in rows]


async def count_embedded(session: AsyncSession, embedding_model: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(GovernanceChunk)
            .where(GovernanceChunk.embedding_model == embedding_model)
        )
    ).scalar_one()
