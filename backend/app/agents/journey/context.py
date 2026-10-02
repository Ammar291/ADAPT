"""Runtime context of the journey graph (not checkpointed; may hold live clients)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from langgraph.runtime import Runtime

from app.adapters.actions import ActionAdapterRegistry
from app.adapters.llm import LLMClient
from app.agents.context import AgentContext
from app.agents.journey.ports import (
    DocumentAnalyzer,
    EvidenceRetriever,
    JourneyStore,
    ReadOnlyStore,
    ResearchStarter,
)


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True)
class JourneyServices:
    store: JourneyStore
    documents: DocumentAnalyzer
    evidence: EvidenceRetriever
    research: ResearchStarter
    actions: ActionAdapterRegistry
    llm: LLMClient
    today: Callable[[], date] = field(default=_today)

    def read_only(self) -> JourneyServices:
        """The same services, with every storage write refused (for what-if runs)."""
        return JourneyServices(
            store=ReadOnlyStore(self.store),  # type: ignore[arg-type]
            documents=self.documents,
            evidence=self.evidence,
            research=self.research,
            actions=self.actions,
            llm=self.llm,
            today=self.today,
        )


@dataclass(frozen=True, slots=True)
class JourneyContext(AgentContext):
    services: JourneyServices | None = None
    simulation: bool = False  # what-if: preview only, no side effects of any kind

    @property
    def svc(self) -> JourneyServices:
        if self.services is None:
            raise RuntimeError("the journey graph needs JourneyContext.services")
        return self.services


def ctx(runtime: Runtime[Any]) -> JourneyContext:
    context = runtime.context
    if not isinstance(context, JourneyContext):
        raise RuntimeError("journey nodes need a JourneyContext")
    return context
