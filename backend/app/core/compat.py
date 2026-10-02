"""Platform compatibility helpers.

psycopg's async driver cannot run on Windows' default Proactor event loop. Containers run
Linux, so this only matters for native Windows development:

* scripts/alembic/tests start loops through `run()` / `new_event_loop`;
* uvicorn: `uvicorn app.main:app --loop app.core.compat:new_event_loop`.
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any

IS_WINDOWS = sys.platform == "win32"


def new_event_loop() -> asyncio.AbstractEventLoop:
    if IS_WINDOWS:
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro, loop_factory=new_event_loop)
