"""LangGraph Postgres checkpointer (persistence, resume after interrupts).

Checkpoint tables live in the `langgraph` schema, owned by the runtime role. A thread id
is only discoverable through its RLS-protected `agent_runs` row, so another user cannot
address someone else's checkpoints through the API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def to_psycopg_conninfo(sqlalchemy_url: str) -> str:
    """postgresql+psycopg://... -> postgresql://... (plain libpq URL)."""
    scheme, sep, rest = sqlalchemy_url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}"


@asynccontextmanager
async def open_checkpointer(
    database_url: str, *, max_size: int = 10
) -> AsyncIterator[AsyncPostgresSaver]:
    pool = AsyncConnectionPool(
        to_psycopg_conninfo(database_url),
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=langgraph",
        },
    )
    await pool.open(wait=True)
    try:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        yield saver
    finally:
        await pool.close()
