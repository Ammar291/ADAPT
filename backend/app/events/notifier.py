"""Low-latency wake-ups for event streams (Redis pub/sub).

Postgres (`run_events`) is the source of truth; Redis only tells listeners "something
new was written for run X", so a missed or dropped notification costs latency, never
data. Streams also poll on a short interval when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def run_channel(run_id: UUID) -> str:
    return f"adapt:run:{run_id}:events"


class Subscription(Protocol):
    async def wait(self, timeout: float) -> bool:
        """Block until a notification arrives (True) or `timeout` elapses (False)."""
        ...


class EventNotifier(Protocol):
    async def notify(self, run_id: UUID, seq: int) -> None: ...

    def subscribe(self, run_id: UUID) -> AsyncIterator[Subscription]: ...


class _SleepSubscription:
    async def wait(self, timeout: float) -> bool:
        await asyncio.sleep(min(timeout, 1.0))
        return False


class NullNotifier:
    """Poll-only fallback (tests, or when Redis is down)."""

    async def notify(self, run_id: UUID, seq: int) -> None:
        return None

    @asynccontextmanager
    async def subscribe(self, run_id: UUID) -> AsyncIterator[Subscription]:
        yield _SleepSubscription()


class _RedisSubscription:
    def __init__(self, pubsub) -> None:  # type: ignore[no-untyped-def]
        self._pubsub = pubsub

    async def wait(self, timeout: float) -> bool:
        try:
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=timeout
            )
        except RedisError:
            await asyncio.sleep(min(timeout, 1.0))
            return False
        return message is not None


class RedisNotifier:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def notify(self, run_id: UUID, seq: int) -> None:
        try:
            await self._redis.publish(run_channel(run_id), str(seq))
        except RedisError:
            logger.warning("event_notify_failed", extra={"run_id": str(run_id)})

    @asynccontextmanager
    async def subscribe(self, run_id: UUID) -> AsyncIterator[Subscription]:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(run_channel(run_id))
        except RedisError:
            logger.warning("event_subscribe_failed", extra={"run_id": str(run_id)})
            await pubsub.aclose()
            yield _SleepSubscription()
            return
        try:
            yield _RedisSubscription(pubsub)
        finally:
            try:
                await pubsub.unsubscribe()
            finally:
                await pubsub.aclose()
