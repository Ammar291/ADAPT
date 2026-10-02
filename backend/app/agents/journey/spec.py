"""Node contracts: every journey node has a typed input and a typed output.

`@journey_node(spec)` turns an async function `(inputs, runtime) -> outputs` into a
LangGraph node that:

* receives ONLY the state keys its input TypedDict declares (validated);
* may return ONLY the keys its output TypedDict declares (validated). Writing any other
  key raises `NodeContractError`, so a node can never silently change unrelated state;
* emits node_started / node_completed / node_failed progress events (via @instrumented)
  and appends `node_start` / `node_complete` entries, plus any tool calls, to the
  state's `events` journal.

The declared keys also drive what-if simulation: a node re-runs only when a fact it
depends on (`fact_keys`) or a state key it reads has changed.
"""

from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from functools import cached_property
from typing import Any, Literal

from langgraph.runtime import Runtime
from pydantic import TypeAdapter, ValidationError

from app.agents.instrumentation import instrumented
from app.agents.journey.state import JournalEvent, JournalType
from app.agents.journey.vocab import NodeId

NodeKind = Literal["agent", "tool", "human"]
ALWAYS_WRITABLE = frozenset({"events", "sim_trace"})  # journals maintained by the wrappers


class NodeContractError(RuntimeError):
    """A node read or wrote state outside its declared contract (a programming error)."""


@dataclass(frozen=True)
class NodeSpec:
    id: NodeId
    label: str
    description: str
    kind: NodeKind
    input: type  # TypedDict of the state keys the node reads
    output: type  # TypedDict of the state keys the node may write
    fact_keys: frozenset[str] | None = None  # facts it depends on; None = any fact
    lane: int = 0

    @cached_property
    def reads(self) -> frozenset[str]:
        return frozenset(self.input.__required_keys__ | self.input.__optional_keys__)  # type: ignore[attr-defined]

    @cached_property
    def writes(self) -> frozenset[str]:
        return frozenset(self.output.__required_keys__ | self.output.__optional_keys__)  # type: ignore[attr-defined]

    def depends_on_fact(self, key: str) -> bool:
        """Glob patterns: `household.*`, `*.documents.*` (any household member)."""
        if self.fact_keys is None:
            return True
        return any(fnmatchcase(key, pattern) for pattern in self.fact_keys)


# --- journal ------------------------------------------------------------------------------

_journal: contextvars.ContextVar[tuple[str, list[JournalEvent]] | None] = contextvars.ContextVar(
    "adapt_journey_journal", default=None
)


def journal(type_: JournalType, detail: str, ref: str | None = None) -> None:
    """Append to the running node's `events` journal (no-op outside a journey node)."""
    current = _journal.get()
    if current is None:
        return
    node, entries = current
    entries.append(
        JournalEvent(
            type=type_, node=node, ts=datetime.now(UTC).isoformat(), detail=detail, ref=ref
        )
    )


# --- the decorator ----------------------------------------------------------------------

NodeImpl = Callable[[Any, Runtime[Any]], Awaitable[dict[str, Any]]]


def journey_node(spec: NodeSpec) -> Callable[[NodeImpl], Any]:
    input_adapter: TypeAdapter[Any] = TypeAdapter(spec.input)
    output_adapter: TypeAdapter[Any] = TypeAdapter(spec.output)

    def decorator(fn: NodeImpl) -> Any:
        async def node(state: dict[str, Any], runtime: Runtime[Any]) -> dict[str, Any]:
            inputs = {k: state[k] for k in spec.reads if k in state}
            try:
                input_adapter.validate_python(inputs)
            except ValidationError as exc:
                raise NodeContractError(f"{spec.id}: invalid input: {exc}") from exc

            entries: list[JournalEvent] = []
            token = _journal.set((spec.id.value, entries))
            try:
                journal("node_start", spec.label)
                result = await fn(inputs, runtime)
                undeclared = set(result) - spec.writes - ALWAYS_WRITABLE - {"_summary"}
                if undeclared:
                    raise NodeContractError(
                        f"{spec.id} wrote undeclared state keys: {sorted(undeclared)}"
                    )
                output = {k: v for k, v in result.items() if k in spec.writes}
                try:
                    output_adapter.validate_python(output)
                except ValidationError as exc:
                    raise NodeContractError(f"{spec.id}: invalid output: {exc}") from exc
                journal("node_complete", str(result.get("_summary") or spec.label))
            finally:
                _journal.reset(token)
            return {**result, "events": [*result.get("events", []), *entries]}

        node.__name__ = fn.__name__
        node.__doc__ = fn.__doc__
        wrapped = instrumented(spec.id.value, spec.label)(node)
        wrapped.spec = spec  # type: ignore[attr-defined]
        wrapped.impl = fn  # type: ignore[attr-defined]
        return wrapped

    return decorator


def spec_of(node: Any) -> NodeSpec:
    return node.spec  # type: ignore[no-any-return]
