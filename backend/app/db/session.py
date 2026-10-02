"""Engine and session management with row-level-security context.

Private tables are protected by PostgreSQL RLS policies that compare each row's
`tenant_id`/`user_id` with the transaction-local settings `app.tenant_id` and
`app.user_id`. A session opened with `user_session(principal)` sets them at the start
of every transaction (including after commits), so a query that forgets a WHERE
clause still cannot read another user's rows. Sessions opened without a principal see
only public (governance) data.

The runtime role (`DATABASE_URL`) must NOT be a superuser or the table owner, because
both bypass RLS.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from app.core.errors import AdapterUnavailable
from app.domain.principal import Principal

_PRINCIPAL_KEY = "adapt.principal"
_SET_CONTEXT = text(
    "SELECT set_config('app.user_id', :user_id, true), "
    "set_config('app.tenant_id', :tenant_id, true)"
)


@event.listens_for(Session, "after_begin")
def _apply_rls_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    principal: Principal | None = session.info.get(_PRINCIPAL_KEY)
    connection.execute(
        _SET_CONTEXT,
        {
            "user_id": str(principal.user_id) if principal else "",
            "tenant_id": str(principal.tenant_id) if principal else "",
        },
    )


def create_engine(url: str, *, pool_size: int = 10, echo: bool = False) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        echo=echo,
        hide_parameters=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class Database:
    """Owns the engine and hands out sessions. One instance per process."""

    def __init__(
        self, url: str, *, pool_size: int = 10, echo: bool = False, require_rls: bool = False
    ) -> None:
        self.engine = create_engine(url, pool_size=pool_size, echo=echo)
        self.session_factory = create_session_factory(self.engine)
        self._require_rls, self._role_checked = require_rls, False

    async def verify_runtime_role(self) -> None:
        """Fail closed if a runtime connection can bypass the private-table policies."""
        if not self._require_rls or self._role_checked:
            return
        from app.db.models import PRIVATE_TABLES

        async with self.engine.connect() as connection:
            safe = (
                await connection.execute(
                    text("""
                SELECT NOT (r.rolsuper OR r.rolbypassrls) AND NOT EXISTS (
                  SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'public' AND c.relkind = 'r'
                    AND (c.relowner = r.oid OR (c.relname = ANY(:protected)
                         AND NOT c.relrowsecurity))
                ) FROM pg_roles r WHERE r.rolname = current_user
            """),
                    {
                        "protected": [
                            *PRIVATE_TABLES,
                            "graph_nodes",
                            "graph_edges",
                            "users",
                            "tenants",
                        ]
                    },
                )
            ).scalar_one()
        if not safe:
            raise AdapterUnavailable(
                "Private data access is unavailable due to database configuration",
                code="unsafe_database_role",
            )
        self._role_checked = True

    @asynccontextmanager
    async def public_session(self) -> AsyncIterator[AsyncSession]:
        """Session without a principal: only governance/public rows are visible."""
        await self.verify_runtime_role()
        async with self.session_factory() as session:
            yield session

    @asynccontextmanager
    async def user_session(self, principal: Principal) -> AsyncIterator[AsyncSession]:
        """Session scoped to one user by RLS for its whole lifetime."""
        await self.verify_runtime_role()
        async with self.session_factory() as session:
            session.info[_PRINCIPAL_KEY] = principal
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


def session_principal(session: AsyncSession) -> Principal | None:
    return session.info.get(_PRINCIPAL_KEY)
