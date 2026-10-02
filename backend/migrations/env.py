"""Alembic environment. Migrations run as the schema OWNER (MIGRATION_DATABASE_URL)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.core import compat
from app.core.config import get_settings
from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.db.session import create_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().owner_database_url


def _include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # LangGraph checkpoint tables live in their own schema and are managed by LangGraph.
    return not (type_ == "table" and getattr(obj, "schema", None) == "langgraph")


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(_url(), pool_size=1)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    compat.run(run_migrations_online())
