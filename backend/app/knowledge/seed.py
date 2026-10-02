"""Seed the knowledge layer: corpus -> governance tables, then the cited governance graph.

Called by `python -m app.seed` after migrations, or on its own:

    uv run python -m app.knowledge.seed

Runs as the schema owner (MIGRATION_DATABASE_URL). Validation runs before any write,
and one bad reference fails the whole seed, so a partial graph is never committed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings import Embedder, HashingEmbedder
from app.knowledge.corpus import load_corpus
from app.knowledge.graph_seed import (
    GraphSeedError,
    GraphSeedReport,
    load_graph_file,
    parse_graph_seed,
    seed_graph,
)
from app.knowledge.ingest import IngestReport, ingest_corpus

logger = logging.getLogger("adapt.knowledge.seed")


@dataclass
class KnowledgeSeedReport:
    ingest: IngestReport
    graph: GraphSeedReport


async def seed_knowledge(
    session: AsyncSession, embedder: Embedder, *, now: datetime | None = None
) -> KnowledgeSeedReport:
    now = now or datetime.now(UTC)
    corpus = load_corpus(now=now)
    graph = parse_graph_seed(load_graph_file(), corpus)
    fallback = HashingEmbedder() if embedder.mode == "live" else None
    ingest, site_ids, passages = await ingest_corpus(
        session, corpus, embedder, fallback_embedder=fallback, now=now
    )
    cited = {ref for node in graph.nodes for ref in node.evidence}
    cited |= {ref for edge in graph.edges for ref in edge.evidence}
    missing = sorted(cited - set(passages))
    if missing:
        raise GraphSeedError([f"evidence not stored: {ref}" for ref in missing])
    report = await seed_graph(session, graph, passages, site_ids=site_ids, now=now)
    logger.info(
        "knowledge layer seeded: %d documents (%d new), %d nodes, %d edges, %d evidence links",
        len(corpus.sources),
        ingest.inserted,
        report.nodes,
        report.edges,
        report.evidence_links,
    )
    return KnowledgeSeedReport(ingest=ingest, graph=report)


async def main() -> None:
    from app.adapters.registry import build_adapters
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.session import Database

    settings = get_settings()
    configure_logging(settings.log_level, settings.json_logs)
    adapters = build_adapters(settings)
    db = Database(settings.owner_database_url, pool_size=1)
    try:
        async with db.public_session() as session:
            await seed_knowledge(session, adapters.embeddings)
            await session.commit()
    finally:
        await db.dispose()
        await adapters.aclose()


if __name__ == "__main__":
    from app.core import compat

    compat.run(main())
