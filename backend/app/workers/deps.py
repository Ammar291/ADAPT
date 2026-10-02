"""Long-lived worker dependencies, created once in ARQ's `on_startup`."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass

from arq.connections import ArqRedis
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.adapters.registry import Adapters, build_adapters
from app.agents.checkpointer import open_checkpointer
from app.core.config import Settings
from app.db.session import Database
from app.events.notifier import EventNotifier, RedisNotifier
from app.workers.queue import JobQueue


@dataclass
class WorkerDeps:
    settings: Settings
    db: Database
    notifier: EventNotifier
    adapters: Adapters
    checkpointer: AsyncPostgresSaver
    queue: JobQueue  # lets a job dispatch follow-up jobs (e.g. research) without waiting
    _stack: AsyncExitStack

    @classmethod
    async def create(cls, settings: Settings, redis: ArqRedis) -> WorkerDeps:
        stack = AsyncExitStack()
        db = Database(
            settings.database_url, pool_size=settings.database_pool_size, require_rls=True
        )
        await db.verify_runtime_role()
        stack.push_async_callback(db.dispose)
        adapters = build_adapters(settings)
        stack.push_async_callback(adapters.aclose)
        checkpointer = await stack.enter_async_context(open_checkpointer(settings.database_url))
        return cls(
            settings=settings,
            db=db,
            notifier=RedisNotifier(redis),
            adapters=adapters,
            checkpointer=checkpointer,
            queue=JobQueue(redis, settings.worker_queue_name),
            _stack=stack,
        )

    async def aclose(self) -> None:
        await self._stack.aclose()
