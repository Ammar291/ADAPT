"""ARQ worker entrypoint: `arq app.workers.settings.WorkerSettings`.

Workers run agent graphs (LangGraph), document extraction and web research — anything
slow or involving third-party calls stays off the request path.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.deps import WorkerDeps
from app.workers.tasks import run_diagnostic

logger = logging.getLogger(__name__)
_settings = get_settings()

# Feature workstreams' ARQ jobs: (module, function names). A module that is not installed
# is skipped; one that fails to import stops the worker (a half-registered worker would
# silently leave runs queued forever).
_FEATURE_JOBS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("app.agents.journey.jobs", ("run_journey", "resume_journey", "run_what_if")),
    ("app.research.tasks", ("run_research",)),
    ("app.documents.tasks", ("process_document",)),
)


def _feature_jobs() -> list[Any]:
    jobs: list[Any] = []
    for module_name, names in _FEATURE_JOBS:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name and module_name.startswith(exc.name):
                continue
            raise
        jobs.extend(getattr(module, name) for name in names if hasattr(module, name))
    return jobs


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(_settings.log_level, _settings.json_logs)
    ctx["deps"] = await WorkerDeps.create(_settings, ctx["redis"])
    logger.info(
        "adapt_worker_started",
        extra={
            "demo": ctx["deps"].adapters.demo_capabilities,
            "queue": _settings.worker_queue_name,
        },
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    deps: WorkerDeps | None = ctx.get("deps")
    if deps is not None:
        await deps.aclose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [run_diagnostic, *_feature_jobs()]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    queue_name = _settings.worker_queue_name
    max_jobs = _settings.worker_max_jobs
    job_timeout = _settings.worker_job_timeout_seconds
    keep_result = 3600
    max_tries = 1  # agent runs are not blindly retried; resumption goes through checkpoints
    health_check_interval = 30
