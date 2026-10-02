"""Progress instrumentation for LangGraph nodes.

Wrap every node with `@instrumented(node_id, label)`. The wrapper emits
`node.started` / `node.completed` / `node.failed` with timings, and lets the node report
intermediate progress with `await report(runtime, "message", 0.4)`.

Human-in-the-loop interrupts (`langgraph.types.interrupt`) propagate untouched: they are
pauses, not failures. The run-level status change is emitted by `execute_run`.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.core.errors import AppError

logger = logging.getLogger(__name__)

_current_node: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "adapt_current_node", default=None
)

NodeFn = Callable[[Any, Runtime[AgentContext]], Awaitable[Any]]


def instrumented(node_id: str, label: str) -> Callable[[NodeFn], NodeFn]:
    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: Any, runtime: Runtime[AgentContext]) -> Any:
            events = runtime.context.events
            token = _current_node.set(node_id)
            started = time.perf_counter()
            await events.node_started(node_id, label)
            try:
                result = await fn(state, runtime)
            except GraphBubbleUp:
                raise  # interrupt / control flow — not a failure
            except AppError as exc:
                await events.node_failed(node_id, exc.code, exc.detail or exc.title)
                raise
            except Exception:
                logger.exception("node_failed", extra={"node": node_id})
                await events.node_failed(node_id, "node_error", f"{label} did not complete")
                raise
            finally:
                _current_node.reset(token)
            summary = result.pop("_summary", None) if isinstance(result, dict) else None
            await events.node_completed(
                node_id, int((time.perf_counter() - started) * 1000), summary
            )
            return result

        # LangGraph injects `runtime` based on the wrapper's own signature.
        del wrapper.__wrapped__
        return wrapper

    return decorator


def current_node() -> str | None:
    """Id of the instrumented node executing in this task, if any."""
    return _current_node.get()


async def report(
    runtime: Runtime[AgentContext],
    message: str,
    progress: float | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Emit `node.progress` for the currently executing instrumented node."""
    node = _current_node.get()
    if node is None:
        raise RuntimeError("report() must be called inside an @instrumented node")
    await runtime.context.events.node_progress(node, message, progress, detail)
