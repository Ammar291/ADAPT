from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun
from app.domain.enums import RunKind, RunStatus
from app.domain.principal import Principal


async def create_run(
    session: AsyncSession,
    principal: Principal,
    kind: RunKind,
    *,
    agent: str | None = None,
    input: dict[str, Any] | None = None,
    journey_id: UUID | None = None,
) -> AgentRun:
    run = AgentRun(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        agent=agent or kind.value,
        kind=kind,
        thread_id=f"{agent or kind.value}:{uuid.uuid4()}",
        input=input or {},
        journey_id=journey_id,
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    *,
    kinds: list[RunKind] | None = None,
    statuses: list[RunStatus] | None = None,
    limit: int = 20,
) -> list[AgentRun]:
    """The caller's runs, newest first (RLS limits them to the owner)."""
    query = select(AgentRun)
    if kinds:
        query = query.where(AgentRun.kind.in_(kinds))
    if statuses:
        query = query.where(AgentRun.status.in_(statuses))
    query = query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(limit)
    return list((await session.execute(query)).scalars())


async def get_run(session: AsyncSession, run_id: UUID) -> AgentRun | None:
    """RLS guarantees only the owner's runs are visible."""
    return (
        await session.execute(select(AgentRun).where(AgentRun.id == run_id))
    ).scalar_one_or_none()
