"""Enqueueing background jobs (ARQ over Redis)."""

from __future__ import annotations

import logging
from typing import Any

from arq.connections import ArqRedis
from redis.exceptions import RedisError

from app.core.errors import AdapterUnavailable

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, redis: ArqRedis, queue_name: str) -> None:
        self._redis = redis
        self._queue_name = queue_name

    async def enqueue(self, function: str, *, job_id: str, **kwargs: Any) -> str:
        """Enqueue idempotently: re-enqueueing the same `job_id` is a no-op."""
        try:
            job = await self._redis.enqueue_job(
                function, _job_id=job_id, _queue_name=self._queue_name, **kwargs
            )
        except (RedisError, OSError) as exc:
            logger.warning("enqueue_failed", extra={"function": function})
            raise AdapterUnavailable(
                "Background processing is unavailable right now. Try again shortly.",
                code="queue_unavailable",
            ) from exc
        return job.job_id if job is not None else job_id
