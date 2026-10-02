"""`python -m app.workers` — run the ARQ worker with a psycopg-compatible event loop.

Equivalent to `arq app.workers.settings.WorkerSettings` (used in Docker), but also works
on native Windows development machines.
"""

from __future__ import annotations

from arq.worker import create_worker

from app.core import compat
from app.workers.settings import WorkerSettings


async def main() -> None:
    worker = create_worker(WorkerSettings)  # type: ignore[arg-type]
    try:
        await worker.async_run()
    finally:
        await worker.close()


if __name__ == "__main__":
    compat.run(main())
