"""The governance knowledge graph as the frontend draws it: entities, relationships, the
source pages that support them (`entity_type = 'source'`, joined by `evidenced_by`), and
the evidence objects every node and relationship cites."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.governance import GovernanceChunk, GovernanceDocument
from app.db.models.graph import GraphEdge, GraphEdgeEvidence, GraphNode, GraphNodeEvidence
from app.domain.enums import GraphType
from app.knowledge.corpus import DEFAULT_STALE_AFTER_DAYS, assess_freshness
from app.knowledge.evaluator import GEdge, GNode, GovernanceSubgraph
from app.knowledge.evidence import PassageView, build_evidence, evidence_id, strongest_kind
from app.knowledge.ranking import expand_terms, query_terms
from app.knowledge.retrieval import passage_view, score_node
from app.knowledge.schemas import (
    Evidence,
    KnowledgeEdge,
    KnowledgeGraphView,
    KnowledgeNode,
    SourceSummary,
)
from app.knowledge.sources import classify_source, publisher_name


@dataclass
class GovernanceSnapshot:
    """Live governance nodes and edges plus the passages they cite."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    node_chunks: dict[UUID, list[UUID]] = field(default_factory=dict)
    edge_chunks: dict[UUID, list[UUID]] = field(default_factory=dict)
    views: dict[UUID, PassageView] = field(default_factory=dict)
    documents: dict[UUID, GovernanceDocument] = field(default_factory=dict)

    def subgraph(self) -> GovernanceSubgraph:
        return GovernanceSubgraph(
            [
                GNode(
                    id=n.id,
                    key=n.key,
                    entity_type=n.entity_type,
                    label=n.label,
                    summary=n.summary,
                    properties=n.properties_json or {},
                    official_url=n.official_url,
                )
                for n in self.nodes
            ],
            [
                GEdge(
                    id=e.id,
                    relation=str(e.relation.value if hasattr(e.relation, "value") else e.relation),
                    source=e.source_node_id,
                    target=e.target_node_id,
                    properties=e.properties_json or {},
                )
                for e in self.edges
            ],
        )


async def load_snapshot(session: AsyncSession) -> GovernanceSnapshot:
    live = or_(GraphNode.valid_to.is_(None), GraphNode.valid_to > func.current_date())
    nodes = list(
        (
            await session.execute(
                select(GraphNode)
                .where(GraphNode.graph_type == GraphType.GOVERNANCE, live)
                .order_by(GraphNode.entity_type, GraphNode.label)
            )
        ).scalars()
    )
    ids = {n.id for n in nodes}
    edges = [
        e
        for e in (
            await session.execute(
                select(GraphEdge).where(GraphEdge.graph_type == GraphType.GOVERNANCE)
            )
        ).scalars()
        if e.source_node_id in ids and e.target_node_id in ids
    ]
    snapshot = GovernanceSnapshot(nodes=nodes, edges=edges)
    for node_id, chunk_id in await session.execute(
        select(GraphNodeEvidence.node_id, GraphNodeEvidence.chunk_id).where(
            GraphNodeEvidence.chunk_id.is_not(None)
        )
    ):
        if node_id in ids and chunk_id is not None:
            snapshot.node_chunks.setdefault(node_id, []).append(chunk_id)
    edge_ids = {e.id for e in edges}
    for edge_id, chunk_id in await session.execute(
        select(GraphEdgeEvidence.edge_id, GraphEdgeEvidence.chunk_id).where(
            GraphEdgeEvidence.chunk_id.is_not(None)
        )
    ):
        if edge_id in edge_ids and chunk_id is not None:
            snapshot.edge_chunks.setdefault(edge_id, []).append(chunk_id)
    chunk_ids = {c for cs in snapshot.node_chunks.values() for c in cs} | {
        c for cs in snapshot.edge_chunks.values() for c in cs
    }
    if chunk_ids:
        rows = await session.execute(
            select(GovernanceChunk, GovernanceDocument)
            .join(GovernanceDocument, GovernanceDocument.id == GovernanceChunk.document_id)
            .where(GovernanceChunk.id.in_(list(chunk_ids)))
        )
        for chunk, document in rows:
            snapshot.views[chunk.id] = passage_view(chunk, document)
            snapshot.documents[document.id] = document
    return snapshot


class EvidenceBook:
    """Builds and de-duplicates evidence for a snapshot, with governance keys attached."""

    def __init__(
        self,
        snapshot: GovernanceSnapshot,
        *,
        now: datetime,
        stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    ) -> None:
        self.snapshot = snapshot
        self.now = now
        self.stale_after_days = stale_after_days
        keys: dict[UUID, set[str]] = {}
        node_key = {n.id: n.key for n in snapshot.nodes}
        for node_id, chunks in snapshot.node_chunks.items():
            for chunk in chunks:
                keys.setdefault(chunk, set()).add(node_key[node_id])
        for edge in snapshot.edges:
            for chunk in snapshot.edge_chunks.get(edge.id, []):
                keys.setdefault(chunk, set()).update(
                    {node_key[edge.source_node_id], node_key[edge.target_node_id]}
                )
        self._keys = keys
        self._built: dict[UUID, Evidence] = {}

    def get(self, chunk_id: UUID) -> Evidence | None:
        if chunk_id not in self._built:
            view = self.snapshot.views.get(chunk_id)
            if view is None:
                return None
            self._built[chunk_id] = build_evidence(
                view,
                now=self.now,
                stale_after_days=self.stale_after_days,
                governance_keys=sorted(self._keys.get(chunk_id, ())),
            )
        return self._built[chunk_id]

    def for_node(self, node_id: UUID) -> list[Evidence]:
        return [e for c in self.snapshot.node_chunks.get(node_id, []) if (e := self.get(c))]

    def for_edge(self, edge_id: UUID) -> list[Evidence]:
        return [e for c in self.snapshot.edge_chunks.get(edge_id, []) if (e := self.get(c))]

    def used(self) -> list[Evidence]:
        return sorted(self._built.values(), key=lambda e: (e.source_priority, e.id))


def knowledge_node(node: GraphNode, evidence: Sequence[Evidence]) -> KnowledgeNode:
    return KnowledgeNode(
        id=node.id,
        key=node.key,
        entity_type=node.entity_type,
        label=node.label,
        summary=node.summary,
        properties=node.properties_json or {},
        official_url=node.official_url,
        evidence_kind=strongest_kind(list(evidence)),
        evidence_ids=[e.id for e in evidence],
    )


def knowledge_edge(edge: GraphEdge, evidence: Sequence[Evidence]) -> KnowledgeEdge:
    relation = edge.relation.value if hasattr(edge.relation, "value") else str(edge.relation)
    return KnowledgeEdge(
        id=str(edge.id),
        relation=relation,
        source=edge.source_node_id,
        target=edge.target_node_id,
        properties=edge.properties_json or {},
        evidence_ids=[e.id for e in evidence],
    )


def source_nodes(
    book: EvidenceBook, node_ids: Iterable[UUID]
) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
    """One `source` node per cited page, and `evidenced_by` edges from the nodes citing it."""
    snapshot = book.snapshot
    nodes: dict[UUID, KnowledgeNode] = {}
    edges: dict[str, KnowledgeEdge] = {}
    for node_id in node_ids:
        for chunk_id in snapshot.node_chunks.get(node_id, []):
            view = snapshot.views.get(chunk_id)
            evidence = book.get(chunk_id)
            if view is None or evidence is None:
                continue
            document = snapshot.documents[view.document_id]
            if document.id not in nodes:
                source = classify_source(document.source_url, document.authority)
                nodes[document.id] = KnowledgeNode(
                    id=document.id,
                    key=str((document.metadata_ or {}).get("key") or f"source.{document.id.hex}"),
                    entity_type="source",
                    label=document.title,
                    official_url=document.source_url,
                    source=SourceSummary(
                        title=document.title,
                        url=document.source_url,
                        authority=publisher_name(document.authority),
                        authority_key=document.authority,
                        source_family=source.family,
                        source_priority=source.priority,
                        source_type=document.document_type,
                        retrieved_at=document.retrieved_at,
                        effective_date=document.effective_date,
                        freshness=assess_freshness(
                            document.retrieved_at,
                            now=book.now,
                            stale_after_days=book.stale_after_days,
                        ),
                    ),
                )
            edge_id = f"evidenced_by:{node_id}:{document.id}"
            edge = edges.setdefault(
                edge_id,
                KnowledgeEdge(
                    id=edge_id, relation="evidenced_by", source=node_id, target=document.id
                ),
            )
            edge.evidence_ids.append(evidence_id(chunk_id))
            nodes[document.id].evidence_ids.append(evidence_id(chunk_id))
    for node in nodes.values():
        node.evidence_ids = list(dict.fromkeys(node.evidence_ids))
    return list(nodes.values()), list(edges.values())


def _focus(snapshot: GovernanceSnapshot, key: str, depth: int) -> set[UUID]:
    by_key = {n.key: n.id for n in snapshot.nodes}
    start = by_key.get(key)
    if start is None:
        return set()
    adjacency: dict[UUID, set[UUID]] = {}
    for edge in snapshot.edges:
        adjacency.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
        adjacency.setdefault(edge.target_node_id, set()).add(edge.source_node_id)
    seen, frontier = {start}, {start}
    for _ in range(depth):
        frontier = {n for f in frontier for n in adjacency.get(f, ())} - seen
        seen |= frontier
    return seen


async def governance_view(
    session: AsyncSession,
    *,
    entity_types: Sequence[str] | None = None,
    q: str | None = None,
    focus: str | None = None,
    depth: int = 1,
    include_sources: bool = True,
    now: datetime | None = None,
) -> KnowledgeGraphView:
    now = now or datetime.now(UTC)
    snapshot = await load_snapshot(session)
    selected = {n.id for n in snapshot.nodes}
    if focus:
        selected &= _focus(snapshot, focus, depth)
    if entity_types:
        selected &= {n.id for n in snapshot.nodes if n.entity_type in entity_types}
    if q:
        terms = expand_terms(query_terms(q))
        selected &= {
            n.id
            for n in snapshot.nodes
            if score_node(n.label, n.summary, (n.properties_json or {}).get("aliases") or [], terms)
            > 0
        }
    book = EvidenceBook(snapshot, now=now)
    nodes = [knowledge_node(n, book.for_node(n.id)) for n in snapshot.nodes if n.id in selected]
    edges = [
        knowledge_edge(e, book.for_edge(e.id))
        for e in snapshot.edges
        if e.source_node_id in selected and e.target_node_id in selected
    ]
    if include_sources:
        sources, evidenced_by = source_nodes(book, selected)
        nodes += sources
        edges += evidenced_by
    return KnowledgeGraphView(nodes=nodes, edges=edges, evidence=book.used(), generated_at=now)
