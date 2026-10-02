"""Ports: what the journey agent needs from storage and from other workstreams.

Nodes and tools depend only on these protocols. Production implementations live in
`store_pg.py` / `integrations.py` (Postgres + RLS, document intelligence, knowledge
retrieval, research); unit tests use in-memory fakes. A what-if simulation wraps the
store in `ReadOnlyStore`, so it can read the active journey but can never change it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.state import ActionRecord, Dependency, Task, UserFact


@dataclass(frozen=True)
class ExtractedField:
    name: str
    label: str
    value: str | None
    confidence: float
    needs_review: bool
    fact_id: str | None = None


@dataclass(frozen=True)
class DocumentAnalysis:
    document_id: str
    kind: str  # DocumentKind
    holder: str  # self | spouse | child1 ...
    status: str  # DocumentStatus
    fields: list[ExtractedField]
    facts: list[UserFact]
    review_task_ids: list[str] = field(default_factory=list)
    cached: bool = False  # true when a stored result was returned without re-running OCR

    @property
    def needs_review(self) -> bool:
        return self.status != "confirmed" and any(f.needs_review for f in self.fields)


@dataclass(frozen=True)
class EvidenceHit:
    id: str
    title: str
    source_url: str
    authority: str | None
    quote: str | None
    governance_key: str | None
    trust: str  # EvidenceKind
    score: float
    retrieved_at: str | None = None
    claim: str | None = None
    section_or_page: str | None = None
    effective_date: str | None = None
    excerpt: str | None = None
    source_family: str | None = None
    freshness: str | None = None
    chunk_id: str | None = None


@dataclass(frozen=True)
class ApprovalRow:
    id: str
    action_id: str
    status: str  # ApprovalStatus
    decided_at: str | None
    note: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class ResearchStart:
    job_id: str
    run_id: str | None
    status: str


class JourneyStore(Protocol):
    """Private, RLS-scoped persistence for one user's journey."""

    async def governance(self) -> GovernanceSnapshot: ...

    async def user_facts(self) -> list[UserFact]: ...

    async def preferences(self) -> dict[str, Any]: ...

    async def save_generated_document(
        self,
        *,
        journey_id: str,
        run_id: str,
        kind: str,
        title: str,
        body_markdown: str,
        task_key: str | None,
        provenance: dict[str, Any],
    ) -> str: ...

    async def save_actions(
        self, *, journey_id: str, run_id: str, actions: list[ActionRecord]
    ) -> None:
        """Upsert by id. Status changes must already have passed `check_transition`."""
        ...

    async def load_actions(self, action_ids: list[str]) -> dict[str, ActionRecord]:
        """The stored actions: authoritative when a node re-runs after a resume."""
        ...

    async def set_pending_review(self, *, run_id: str, review: dict[str, Any] | None) -> None: ...

    async def ensure_approvals(
        self, *, run_id: str, review_id: str, action_ids: list[str]
    ) -> dict[str, tuple[str, bool]]:
        """Create one pending approval per action, or return the existing one.
        Returns action id -> (approval id, created now)."""
        ...

    async def approvals(self, action_ids: list[str]) -> dict[str, ApprovalRow]: ...

    async def save_plan(
        self,
        *,
        journey_id: str,
        plan: dict[str, Any],
        tasks: list[Task],
        dependencies: list[Dependency],
        status: str,
        summary: str | None,
    ) -> None: ...


class DocumentAnalyzer(Protocol):
    async def analyze(self, document_id: str) -> DocumentAnalysis: ...

    async def apply_corrections(
        self, document_id: str, corrections: list[dict[str, Any]], *, confirm: bool
    ) -> list[UserFact]: ...


class EvidenceRetriever(Protocol):
    async def retrieve(
        self, query: str, *, governance_keys: list[str], top_k: int
    ) -> list[EvidenceHit]: ...


class ResearchStarter(Protocol):
    async def start(self, *, journey_id: str) -> ResearchStart | None:
        """Start background research without waiting for it. None when unavailable."""
        ...


class SimulationWriteError(RuntimeError):
    """A what-if simulation tried to write. Simulations copy the journey; never mutate it."""


class ReadOnlyStore:
    """Wraps a store for simulations: reads pass through, every write raises."""

    def __init__(self, inner: JourneyStore) -> None:
        self._inner = inner

    async def governance(self) -> GovernanceSnapshot:
        return await self._inner.governance()

    async def user_facts(self) -> list[UserFact]:
        return await self._inner.user_facts()

    async def preferences(self) -> dict[str, Any]:
        return await self._inner.preferences()

    async def approvals(self, action_ids: list[str]) -> dict[str, ApprovalRow]:
        return await self._inner.approvals(action_ids)

    async def load_actions(self, action_ids: list[str]) -> dict[str, ActionRecord]:
        return await self._inner.load_actions(action_ids)

    def __getattr__(self, name: str) -> Any:
        async def refuse(*args: Any, **kwargs: Any) -> Any:
            raise SimulationWriteError(f"a what-if simulation may not call {name}()")

        return refuse
