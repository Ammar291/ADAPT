"""Process-wide dependencies for the API. Built in the FastAPI lifespan."""

from __future__ import annotations

from dataclasses import dataclass

from arq.connections import ArqRedis

from app.adapters.registry import Adapters, build_adapters
from app.core.config import Settings
from app.db.session import Database
from app.events.notifier import EventNotifier, RedisNotifier
from app.workers.queue import JobQueue


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: ArqRedis
    notifier: EventNotifier
    adapters: Adapters
    queue: JobQueue

    @classmethod
    def create(cls, settings: Settings) -> Container:
        """Construct without connecting: the API starts (degraded) even if Redis or
        Postgres are briefly unavailable; readiness reports their state."""
        redis = ArqRedis.from_url(settings.redis_url)
        return cls(
            settings=settings,
            db=Database(
                settings.database_url,
                pool_size=settings.database_pool_size,
                echo=settings.database_echo,
                require_rls=True,
            ),
            redis=redis,
            notifier=RedisNotifier(redis),
            adapters=build_adapters(settings),
            queue=JobQueue(redis, settings.worker_queue_name),
        )

    async def aclose(self) -> None:
        await self.adapters.aclose()
        await self.redis.aclose()
        await self.db.dispose()
