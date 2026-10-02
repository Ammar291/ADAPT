"""Public API of the private user graph's facts.

Used by the API routes, the document pipeline, onboarding (profile projection), the
journey planner, knowledge checks and research. Every function takes a *user-scoped*
session; callers commit.

Correction flow (the person is always the authority on their own facts):
* `add_fact`: the person states something. It is accepted and confirmed, and resolves
  any pending proposal for the same detail.
* `update_fact`: confirm and/or correct. A pending proposal becomes the accepted value.
  A corrected document value keeps its document as context (`corrected=True`).
* `delete_fact`: reject or remove. Entities left without facts disappear.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.db.models import GraphNode
from app.db.models.user_data import ExtractedFact
from app.domain.enums import FactSource
from app.domain.principal import Principal
from app.domain.twin import TwinFact
from app.personalization import analytics, review
from app.personalization.facts_model import FactStatus, ReviewResolution
from app.personalization.projection import (
    FactEvidence,
    PlanningFact,
    evidence,
)
from app.personalization.projection import (
    planning_facts as project_planning_facts,
)
from app.personalization.store import UserGraph
from app.personalization.vocabulary import (
    ENTITY_SPECS,
    Cardinality,
    FactRuleError,
    UserEntityType,
    identity_token,
)

USER_ENTRY = "user_entry"
USER_CORRECTION = "user_correction"


class StoredFact(TwinFact):
    """A `TwinFact` as stored, with its identity and provenance (for basis/fact_refs)."""

    id: UUID
    node_id: UUID
    attribute: str
    status: FactStatus
    source_document_id: UUID | None = None
    extraction_method: str | None = None
    corrected: bool = False
    issues: list[str] = Field(default_factory=list)


def stored(fact: ExtractedFact) -> StoredFact:
    return StoredFact(
        id=fact.id,
        node_id=fact.node_id,
        attribute=fact.attribute,
        value=fact.value,
        source=FactSource(fact.source),
        source_ref=fact.source_ref,
        confidence=fact.confidence,
        confirmed_by_user=fact.confirmed_by_user,
        observed_at=fact.observed_at,
        status=FactStatus(fact.status),
        source_document_id=fact.source_document_id,
        extraction_method=fact.extraction_method,
        corrected=fact.corrected,
        issues=list(fact.issues or []),
    )


@dataclass(slots=True)
class FactChange:
    fact: ExtractedFact | None
    created: bool = False
    reviewed_documents: list[UUID] | None = None  # documents whose review just finished


async def _after_change(
    graph: UserGraph, node: GraphNode, documents: Iterable[UUID | None]
) -> list[UUID]:
    await graph.refresh_label(node)
    await graph.sync_governance_link(node)
    return await review.refresh_document_status(graph.session, graph.principal, documents)


# --- API: correction flow ------------------------------------------------------------------


async def add_fact(
    session: AsyncSession,
    *,
    attribute: str,
    value: Any,
    node_id: UUID | None = None,
    entity_type: UserEntityType | None = None,
    parent_id: UUID | None = None,
) -> FactChange:
    """The person states a fact about an existing entity (`node_id`) or a new/matching
    entity of `entity_type` under `parent_id` (default: the person themself)."""
    graph = UserGraph(session)
    if (node_id is None) == (entity_type is None):
        raise FactRuleError("Give either an entity or an entity type", code="invalid_target")
    if node_id is not None:
        node = await graph.node(node_id)
        if node is None:
            raise NotFound("That entity is not in your twin")
    else:
        assert entity_type is not None
        spec = ENTITY_SPECS[entity_type]
        parent = None
        if parent_id is not None:
            parent = await graph.node(parent_id)
            if parent is None:
                raise NotFound("That entity is not in your twin")
        instance = None
        if spec.cardinality is Cardinality.MANY and spec.identity == attribute:
            spec.attribute(attribute)
            try:
                instance = identity_token(spec.attributes[attribute].normalize(value).value)
            except ValueError as issue:
                raise FactRuleError(str(issue), code="invalid_value") from issue
        node = await graph.ensure_node(entity_type, parent=parent, instance=instance)

    existing = await graph.facts(node_ids=[node.id])
    current = next((f for f in existing if f.attribute == attribute), None)
    if current is not None:
        return await update_fact(session, current.id, value=value, confirm=True)

    fact = await graph.write_fact(
        node,
        attribute,
        value,
        source=FactSource.USER_STATED,
        confidence=1.0,
        extraction_method=USER_ENTRY,
        confirmed=True,
    )
    documents: list[UUID | None] = []
    pending = await graph.facts(node_ids=[node.id], statuses=(FactStatus.NEEDS_REVIEW,))
    for proposal in (p for p in pending if p.attribute == attribute):
        resolution = (
            ReviewResolution.CONFIRMED
            if proposal.value == fact.value
            else ReviewResolution.CORRECTED
        )
        documents += await review.resolve_fact_tasks(
            session, graph.principal, proposal.id, resolution
        )
        await session.delete(proposal)
    await session.flush()
    finished = await _after_change(graph, node, documents)
    analytics.track(
        "fact_added", entity_type=node.entity_type, attribute=attribute, source="user_stated"
    )
    return FactChange(fact, created=True, reviewed_documents=finished)


async def update_fact(
    session: AsyncSession, fact_id: UUID, *, value: Any = None, confirm: bool | None = None
) -> FactChange:
    """Confirm and/or correct a fact. A pending fact becomes the accepted value."""
    graph = UserGraph(session)
    fact = await graph.fact(fact_id)
    if fact is None:
        raise NotFound("That fact is not in your twin")
    node = await graph.node(fact.node_id)
    assert node is not None
    documents: list[UUID | None] = [fact.source_document_id]
    change = "confirmed"

    if value is not None:
        source = FactSource(fact.source)
        # The new value comes from the person, whatever the fact's origin.
        normalised = await graph.normalise(node, fact.attribute, value, FactSource.USER_STATED)
        if normalised != fact.value:
            change = "corrected"
            fact.value = normalised
            if source is FactSource.DOCUMENT_EXTRACTED:
                fact.corrected = True
                fact.extraction_method = USER_CORRECTION
            else:
                fact.source = FactSource.USER_STATED
                fact.source_ref = None
                fact.extraction_method = USER_ENTRY
    elif confirm is not True:
        raise FactRuleError("Nothing to change", code="invalid_value")
    if fact.value is None:
        raise FactRuleError("Add the value before confirming it", code="invalid_value")

    was_pending = fact.status is FactStatus.NEEDS_REVIEW
    fact.confirmed_by_user = True
    fact.confidence = 1.0
    fact.issues = []
    await session.flush()
    if was_pending:
        await graph.promote(fact)
    resolution = ReviewResolution.CORRECTED if change == "corrected" else ReviewResolution.CONFIRMED
    documents += await review.resolve_fact_tasks(session, graph.principal, fact.id, resolution)
    finished = await _after_change(graph, node, documents)
    analytics.track(
        "fact_reviewed", entity_type=node.entity_type, attribute=fact.attribute, change=change
    )
    return FactChange(fact, reviewed_documents=finished)


async def delete_fact(session: AsyncSession, fact_id: UUID) -> FactChange:
    """Reject a proposal or remove a fact; entities left without facts are removed."""
    graph = UserGraph(session)
    fact = await graph.fact(fact_id)
    if fact is None:
        raise NotFound("That fact is not in your twin")
    node = await graph.node(fact.node_id)
    documents = [fact.source_document_id]
    documents += await review.resolve_fact_tasks(
        session, graph.principal, fact.id, ReviewResolution.REJECTED
    )
    entity_type, attribute = (node.entity_type if node else None), fact.attribute
    await session.delete(fact)
    await session.flush()
    if node is not None and await graph.prune([node.id]) == 0:
        await graph.refresh_label(node)
        await graph.sync_governance_link(node)
    finished = await review.refresh_document_status(session, graph.principal, documents)
    analytics.track("fact_removed", entity_type=entity_type, attribute=attribute)
    return FactChange(None, reviewed_documents=finished)


# --- API for other workstreams ---------------------------------------------------------------


async def ensure_node(
    session: AsyncSession,
    principal: Principal,
    entity_type: UserEntityType | str,
    *,
    parent_id: UUID | None = None,
    instance: str | None = None,
) -> GraphNode:
    """Find or create a user-graph entity (and its edge from the parent), idempotently."""
    graph = _graph(session, principal)
    parent = None
    if parent_id is not None:
        parent = await graph.node(parent_id)
        if parent is None:
            raise NotFound("That entity is not in your twin")
    token = identity_token(instance) if instance is not None else None
    return await graph.ensure_node(UserEntityType(entity_type), parent=parent, instance=token)


async def upsert_user_stated(
    session: AsyncSession,
    principal: Principal,
    *,
    node_id: UUID,
    facts: dict[str, TwinFact],
    source_ref: str,
) -> list[StoredFact]:
    """Write user-stated facts from another source of truth (e.g. the onboarding profile).

    Facts previously written with the same `source_ref` on this node and not in `facts`
    are removed, so re-projecting a profile row replaces what it said before.
    """
    graph = _graph(session, principal)
    node = await graph.node(node_id)
    if node is None:
        raise NotFound("That entity is not in your twin")
    written = []
    for attribute, twin_fact in facts.items():
        if twin_fact.value is None:
            continue
        fact = await graph.write_fact(
            node,
            attribute,
            twin_fact.value,
            source=FactSource.USER_STATED,
            confidence=twin_fact.confidence,
            source_ref=source_ref,
            extraction_method=USER_ENTRY,
            confirmed=True,
        )
        written.append(fact)
    keep = {f.id for f in written}
    stale = [
        f.id
        for f in await graph.facts(node_ids=[node.id])
        if f.source_ref == source_ref and f.id not in keep
    ]
    if stale:
        await graph.delete_facts(ExtractedFact.id.in_(stale))
    await graph.refresh_label(node)
    return [stored(f) for f in written]


async def facts_for_nodes(
    session: AsyncSession, node_ids: Sequence[UUID]
) -> dict[UUID, dict[str, StoredFact]]:
    """Accepted facts per node: what a planner may rely on (proposals are excluded)."""
    graph = UserGraph(session)
    out: dict[UUID, dict[str, StoredFact]] = {node_id: {} for node_id in node_ids}
    for fact in await graph.facts(node_ids=list(node_ids)):
        out.setdefault(fact.node_id, {})[fact.attribute] = stored(fact)
    return out


async def planning_facts(
    session: AsyncSession,
    principal: Principal | None = None,
    keys: Sequence[str] | None = None,
    *,
    for_requirements: bool = False,
) -> list[PlanningFact]:
    """Flat, consent-gated projection with shared keys (see `projection.planning_facts`).

    Pass `for_requirements=True` when the facts feed eligibility/requirement checks (e.g.
    /api/knowledge/explain): community interests and faith are then never included.
    """
    graph = _graph(session, principal)
    return project_planning_facts(await graph.snapshot(), keys, for_requirements=for_requirements)


async def explain(session: AsyncSession, fact_ids: Iterable[UUID | str]) -> list[FactEvidence]:
    """Why a recommendation applies: each fact it used and where that fact came from."""
    ids = []
    for ref in fact_ids:
        try:
            ids.append(ref if isinstance(ref, UUID) else UUID(str(ref)))
        except ValueError:
            continue  # not a fact id (e.g. a free-form key): nothing to explain
    return evidence(await UserGraph(session).snapshot(), ids)


def _graph(session: AsyncSession, principal: Principal | None) -> UserGraph:
    graph = UserGraph(session)
    if principal is not None and principal.user_id != graph.principal.user_id:
        raise PermissionError("session and principal belong to different users")
    return graph


async def node_facts(session: AsyncSession, node_id: UUID) -> list[ExtractedFact]:
    graph = UserGraph(session)
    return await graph.facts(
        node_ids=[node_id], statuses=(FactStatus.ACCEPTED, FactStatus.NEEDS_REVIEW)
    )


__all__ = [
    "FactChange",
    "StoredFact",
    "add_fact",
    "delete_fact",
    "ensure_node",
    "explain",
    "facts_for_nodes",
    "planning_facts",
    "update_fact",
    "upsert_user_stated",
]
