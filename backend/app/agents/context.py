"""Per-run dependencies handed to LangGraph nodes via `Runtime[AgentContext]`.

Runtime context is NOT checkpointed, so it may hold live objects (database, adapters,
event sink). Authorisation always comes from `principal` here — never from graph state.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.adapters.registry import Adapters
from app.db.session import Database
from app.domain.principal import Principal
from app.events.emitter import EventSink


@dataclass(frozen=True, slots=True)
class AgentContext:
    principal: Principal
    run_id: UUID
    events: EventSink
    db: Database
    adapters: Adapters
