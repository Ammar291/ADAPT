"""Runs a compiled LangGraph for one `agent_runs` row and emits run-level events.

Lifecycle mapping:
  first invocation      -> run.started
  resume after approval -> run.status(running)
  graph interrupted     -> run.status(awaiting_input)   (resumable via Command(resume=...))
  graph finished        -> run.completed
  exception             -> run.failed                   (the error is not re-raised)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agents.context import AgentContext
from app.core.errors import AppError
from app.domain.enums import RunKind, RunStatus

logger = logging.getLogger(__name__)


InterruptHook = Callable[[dict[str, Any], list[Any]], Awaitable[None]]
CompleteHook = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RunOutcome:
    status: Literal["completed", "interrupted", "failed"]
    values: dict[str, Any]
    interrupts: list[Any]


def graph_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}


async def execute_run(
    *,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    ctx: AgentContext,
    kind: RunKind,
    thread_id: str,
    graph_input: dict[str, Any] | Command,
    summary_key: str = "summary",
    on_interrupt: InterruptHook | None = None,
    on_complete: CompleteHook | None = None,
) -> RunOutcome:
    """`on_interrupt(values, interrupts)` runs once each time the graph really pauses,
    before `run.status(awaiting_input)`, e.g. to persist and announce a review gate.
    `on_complete(values)` runs before `run.completed`, e.g. to store a result the UI
    will fetch as soon as it sees the completion."""
    config = graph_config(thread_id)
    resuming = isinstance(graph_input, Command)
    if resuming:
        await ctx.events.run_status(RunStatus.RUNNING, "resumed")
    else:
        await ctx.events.run_started(kind)

    try:
        async for _ in graph.astream(
            graph_input, config=config, context=ctx, stream_mode="updates"
        ):
            pass  # nodes emit progress themselves; the checkpointer persists state
        snapshot = await graph.aget_state(config)
    except AppError as exc:
        await ctx.events.run_failed(exc.code, exc.detail or exc.title, retryable=exc.status >= 500)
        return RunOutcome("failed", {}, [])
    except Exception:
        logger.exception("run_failed", extra={"run_id": str(ctx.run_id)})
        await ctx.events.run_failed("run_error", "The run stopped unexpectedly", retryable=True)
        return RunOutcome("failed", {}, [])

    values = dict(snapshot.values or {})
    if snapshot.interrupts:
        if on_interrupt is not None:
            try:
                await on_interrupt(values, list(snapshot.interrupts))
            except Exception:
                logger.exception("interrupt_hook_failed", extra={"run_id": str(ctx.run_id)})
                await ctx.events.run_failed(
                    "review_unavailable", "The run paused but its review could not be saved"
                )
                return RunOutcome("failed", values, list(snapshot.interrupts))
        await ctx.events.run_status(RunStatus.AWAITING_INPUT, "waiting for your input")
        return RunOutcome("interrupted", values, list(snapshot.interrupts))

    if on_complete is not None:
        try:
            await on_complete(values)
        except Exception:
            logger.exception("complete_hook_failed", extra={"run_id": str(ctx.run_id)})
            await ctx.events.run_failed(
                "result_unavailable", "The run finished but its result could not be saved"
            )
            return RunOutcome("failed", values, [])
    summary = values.get(summary_key)
    journey_id = values.get("journey_id")
    await ctx.events.run_completed(
        summary=summary if isinstance(summary, str) else None,
        journey_id=UUID(journey_id) if isinstance(journey_id, str) else None,
    )
    return RunOutcome("completed", values, [])
