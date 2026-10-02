"""Seed shared reference data and the demo household: `python -m app.seed`.

Runs as the schema owner (MIGRATION_DATABASE_URL): the runtime role is not allowed to
write governance or catalogue data. Idempotent, safe to run on every deploy.

1. Governance knowledge: the knowledge layer's cited corpus + graph
   (`app.knowledge.seed.seed_knowledge`) when available, otherwise the interim
   `governance.yaml` graph.
2. Discover catalogue (`catalogue.yaml`).
3. The fictional demo household (`app.seed.demo`), unless `--no-demo`.
"""

from __future__ import annotations

import argparse
import importlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings import Embedder
from app.core import compat
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.seed.catalogue import load_catalogue, seed_catalogue
from app.seed.governance import load_seed, seed_governance

logger = logging.getLogger("adapt.seed")


def _knowledge_seed() -> Any | None:
    """`seed_knowledge` when the knowledge layer and its graph file are installed."""
    try:
        module = importlib.import_module("app.knowledge.seed")
        graph_seed = importlib.import_module("app.knowledge.graph_seed")
    except ModuleNotFoundError as exc:
        if exc.name and "app.knowledge.seed".startswith(exc.name):
            return None
        raise
    graph_file = getattr(graph_seed, "GRAPH_FILE", None)
    if graph_file is None or not Path(graph_file).exists():
        return None
    return module.seed_knowledge


async def seed_reference_data(session: AsyncSession, embedder: Embedder) -> dict[str, Any]:
    """Governance knowledge + catalogue on an owner session (caller commits)."""
    report: dict[str, Any] = {}
    knowledge = _knowledge_seed()
    if knowledge is not None:
        report["knowledge"] = await knowledge(session, embedder)
    else:
        nodes, edges = await seed_governance(session, load_seed())
        report["governance"] = {"nodes": nodes, "edges": edges, "source": "interim"}
    report["catalogue"] = await seed_catalogue(session, load_catalogue())
    return report


async def main(with_demo: bool = True) -> None:
    from app.adapters.registry import build_adapters
    from app.seed.demo import seed_demo_household

    settings = get_settings()
    configure_logging(settings.log_level, settings.json_logs)
    adapters = build_adapters(settings)
    db = Database(settings.owner_database_url, pool_size=2)
    try:
        async with db.public_session() as session:
            report = await seed_reference_data(session, adapters.embeddings)
            await session.commit()
        logger.info("reference data seeded: %s", {k: str(v) for k, v in report.items()})
        if with_demo:
            demo = await seed_demo_household(db)
            logger.info(
                "demo household seeded: journey with %d steps, %d actions, %d appointments",
                demo.journey_nodes,
                demo.actions,
                demo.appointments,
            )
    finally:
        await db.dispose()
        await adapters.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-demo", action="store_true", help="skip the demo household")
    args = parser.parse_args()
    compat.run(main(with_demo=not args.no_demo))
