from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.core import compat


def pytest_asyncio_loop_factories(config: Any, item: Any) -> Mapping[str, Callable[[], Any]]:
    # psycopg async cannot use the Windows Proactor loop (see app.core.compat).
    return {"selector": compat.new_event_loop}
