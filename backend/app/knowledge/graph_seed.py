"""The governance graph seed (`governance_graph.yaml`): validation and loading.

The rule is simple: **no citation, no fact.** Every node and every relationship names at
least one corpus passage (`<source_key>#<passage_key>`) that supports it, and loading
fails if any reference does not resolve. Relationship endpoints are type-checked
(`RELATION_ENDPOINTS`), `depends_on` must stay acyclic, and machine conditions on
eligibility rules must be well formed.

File format:

    nodes:
      - key: service.family_residence_visa        # prefix = entity type
        type: service
        label: Sponsor your spouse's residence visa
        summary: ...
        official_url: https://...                 # optional, official domains only
        publisher: authority.icp                  # optional: the node's primary publisher
        properties: {requires_uae_pass: true}     # eligibility rules: {condition: {...}}
        aliases: [spouse visa, wife visa]         # extra words for search
        evidence: [u_ae.family_sponsorship#eligibility]
    edges:
      - [service.family_residence_visa, requires, document.passport, [ref, ...]]
      - source: service.establishment_card
        relation: depends_on
        target: dependency.company_licence
        properties: {party: beneficiary}          # or satisfied_by: {when: <condition>}
        evidence: [ref, ...]
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.graph import GraphEdge, GraphEdgeEvidence, GraphNode, GraphNodeEvidence
from app.domain.enums import GovernanceNodeType, GraphEdgeType, GraphType
from app.domain.provenance import Citation, Provenance, is_official_source
from app.knowledge.corpus import Corpus
from app.knowledge.evaluator import PARTIES, condition_problems
from app.knowledge.evidence import PassageView, build_evidence, strongest_kind
from app.knowledge.sources import PUBLISHERS

logger = logging.getLogger("adapt.knowledge.seed")
GRAPH_FILE = Path(__file__).with_name("governance_graph.yaml")
SEED_NOTE = "Curated from the cited official pages. Confirm current details on the official page."

_T = GovernanceNodeType
RELATION_ENDPOINTS: dict[GraphEdgeType, tuple[frozenset[str], frozenset[str]]] = {
    GraphEdgeType.PROVIDES: (frozenset({_T.AUTHORITY}), frozenset({_T.SERVICE})),
    GraphEdgeType.REQUIRES: (
        frozenset({_T.SERVICE}),
        frozenset({_T.REQUIREMENT, _T.DOCUMENT, _T.ELIGIBILITY_RULE}),
    ),
    GraphEdgeType.DEPENDS_ON: (frozenset({_T.SERVICE}), frozenset({_T.SERVICE, _T.DEPENDENCY})),
    GraphEdgeType.SATISFIED_BY: (frozenset({_T.DEPENDENCY}), frozenset({_T.SERVICE})),
    GraphEdgeType.PRODUCES: (frozenset({_T.SERVICE}), frozenset({_T.DOCUMENT})),
    GraphEdgeType.APPLIES_TO: (frozenset({_T.ELIGIBILITY_RULE}), frozenset({_T.SERVICE})),
    GraphEdgeType.AVAILABLE_AT: (frozenset({_T.SERVICE, _T.APPOINTMENT}), frozenset({_T.PORTAL})),
    GraphEdgeType.MAY_REQUIRE: (frozenset({_T.SERVICE}), frozenset({_T.APPOINTMENT})),
    GraphEdgeType.GOVERNED_BY: (
        frozenset({_T.SERVICE, _T.ELIGIBILITY_RULE, _T.REQUIREMENT}),
        frozenset({_T.LEGAL_INSTRUMENT}),
    ),
    GraphEdgeType.LOCATED_IN: (
        frozenset({_T.AUTHORITY, _T.SERVICE, _T.PORTAL, _T.APPOINTMENT}),
        frozenset({_T.LOCATION}),
    ),
}


class GraphSeedError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid governance graph seed:\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True, slots=True)
class SeedNode:
    key: str
    entity_type: str
    label: str
    summary: str | None
    official_url: str | None
    publisher: str | None
    properties: dict[str, Any]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SeedEdge:
    source: str
    relation: GraphEdgeType
    target: str
    properties: dict[str, Any]
    evidence: tuple[str, ...]

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.source, self.relation.value, self.target)


@dataclass(frozen=True, slots=True)
class GraphSeed:
    nodes: list[SeedNode]
    edges: list[SeedEdge]


def load_graph_file(path: Path = GRAPH_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _edge_from(raw: Any) -> tuple[str, str, str, dict[str, Any], list[str]]:
    if isinstance(raw, list):
        if len(raw) != 4:
            raise ValueError("list edges are [source, relation, target, [evidence...]]")
        source, relation, target, evidence = raw
        return source, relation, target, {}, list(evidence or [])
    return (
        raw["source"],
        raw["relation"],
        raw["target"],
        dict(raw.get("properties") or {}),
        list(raw.get("evidence") or []),
    )


def parse_graph_seed(data: Mapping[str, Any], corpus: Corpus) -> GraphSeed:
    """Validate the seed against the corpus. Raises `GraphSeedError` listing ALL problems."""
    problems: list[str] = []
    nodes: list[SeedNode] = []
    types: dict[str, str] = {}

    def check_refs(owner: str, refs: list[str]) -> None:
        if not refs:
            problems.append(f"{owner}: no evidence (every fact must cite a passage)")
        for ref in refs:
            try:
                corpus.resolve(ref)
            except KeyError:
                problems.append(f"{owner}: evidence '{ref}' does not resolve to a passage")

    for raw in data.get("nodes") or []:
        key = str(raw.get("key", "?"))
        entity_type = str(raw.get("type", ""))
        if entity_type not in GovernanceNodeType._value2member_map_:
            problems.append(f"{key}: unknown type '{entity_type}'")
            continue
        if key.split(".", 1)[0] != entity_type or "." not in key:
            problems.append(f"{key}: key must start with '{entity_type}.'")
        if key in types:
            problems.append(f"{key}: duplicate node")
        types[key] = entity_type
        url = raw.get("official_url")
        if url and not is_official_source(url):
            problems.append(f"{key}: official_url {url} is not an official domain")
        publisher = raw.get("publisher")
        if publisher and publisher not in PUBLISHERS:
            problems.append(f"{key}: unknown publisher '{publisher}'")
        properties = dict(raw.get("properties") or {})
        if raw.get("aliases"):
            aliases = raw["aliases"]
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                problems.append(f"{key}: aliases must be a list of strings (quote numbers)")
            else:
                properties["aliases"] = list(aliases)
        if "condition" in properties:
            problems += [f"{key}: {p}" for p in condition_problems(properties["condition"])]
        refs = list(raw.get("evidence") or [])
        check_refs(key, refs)
        if not raw.get("label"):
            problems.append(f"{key}: missing label")
        nodes.append(
            SeedNode(
                key=key,
                entity_type=entity_type,
                label=str(raw.get("label", key)),
                summary=raw.get("summary"),
                official_url=url,
                publisher=publisher,
                properties=properties,
                evidence=tuple(refs),
            )
        )

    edges: list[SeedEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in data.get("edges") or []:
        try:
            source, relation_name, target, properties, refs = _edge_from(raw)
        except (KeyError, ValueError, TypeError) as exc:
            problems.append(f"malformed edge {raw!r}: {exc}")
            continue
        label = f"{source} -{relation_name}-> {target}"
        try:
            relation = GraphEdgeType(relation_name)
        except ValueError:
            problems.append(f"{label}: unknown relation")
            continue
        if relation not in RELATION_ENDPOINTS:
            problems.append(f"{label}: '{relation_name}' is not a governance relation")
            continue
        if source not in types or target not in types:
            problems.append(f"{label}: references an unknown node")
            continue
        if source == target:
            problems.append(f"{label}: self loop")
        allowed_sources, allowed_targets = RELATION_ENDPOINTS[relation]
        if types[source] not in allowed_sources or types[target] not in allowed_targets:
            problems.append(
                f"{label}: {relation_name} cannot connect {types[source]} -> {types[target]}"
            )
        if (source, relation.value, target) in seen:
            problems.append(f"{label}: duplicate edge")
        seen.add((source, relation.value, target))
        party = properties.get("party")
        if party is not None and party not in PARTIES:
            problems.append(f"{label}: unknown party '{party}'")
        if "when" in properties:
            problems += [f"{label}: when {p}" for p in condition_problems(properties["when"])]
        check_refs(label, refs)
        edges.append(SeedEdge(source, relation, target, properties, tuple(refs)))

    for node in nodes:
        if node.entity_type == _T.DEPENDENCY:
            options = [
                e for e in edges if e.source == node.key and e.relation.value == "satisfied_by"
            ]
            if len(options) < 2:
                problems.append(f"{node.key}: a dependency needs at least two satisfied_by options")
    problems += _cycle_problems(edges)
    if problems:
        raise GraphSeedError(problems)
    return GraphSeed(nodes=nodes, edges=edges)


def _cycle_problems(edges: list[SeedEdge]) -> list[str]:
    """`depends_on` / `satisfied_by` must form a DAG, or planning never terminates."""
    graph: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation in (GraphEdgeType.DEPENDS_ON, GraphEdgeType.SATISFIED_BY):
            graph.setdefault(edge.source, []).append(edge.target)
    state: dict[str, int] = {}
    problems: list[str] = []

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                problems.append("dependency cycle: " + " -> ".join([*path, node, nxt]))
            elif state.get(nxt) is None:
                visit(nxt, [*path, node])
        state[node] = 2

    for node in list(graph):
        if state.get(node) is None:
            visit(node, [])
    return problems


# --- database -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedPassage:
    """A corpus passage as stored: the live document version and its chunk(s)."""

    document_id: UUID
    chunk_ids: tuple[UUID, ...]
    view: PassageView


@dataclass
class GraphSeedReport:
    nodes: int = 0
    edges: int = 0
    evidence_links: int = 0
    edges_pruned: int = 0
    nodes_retired: int = 0


def _provenance(
    refs: tuple[str, ...], passages: Mapping[str, ResolvedPassage], now: datetime
) -> dict[str, Any]:
    evidence = [build_evidence(passages[ref].view, now=now) for ref in refs]
    citations = [
        Citation(
            source_url=e.source_url,
            source_title=e.source_title,
            authority=e.authority,
            effective_date=e.effective_date,
            retrieved_at=e.retrieved_at,
            section=e.section_or_page,
            rag_chunk_id=e.chunk_id,
            quote=e.claim[:1200],
        )
        for e in evidence
    ]
    return Provenance(
        kind=strongest_kind(evidence),  # type: ignore[arg-type]
        citations=citations,
        confidence=max(e.confidence for e in evidence),
        note=SEED_NOTE,
    ).model_dump(mode="json")


async def seed_graph(
    session: AsyncSession,
    seed: GraphSeed,
    passages: Mapping[str, ResolvedPassage],
    *,
    site_ids: Mapping[str, UUID],
    now: datetime | None = None,
) -> GraphSeedReport:
    """Upsert nodes and edges, replace their evidence links, prune what the seed dropped.

    Runs as the schema owner. Nodes that disappear from the seed are *retired*
    (`valid_to`), not deleted, so private links from user graphs keep resolving.
    Edges that disappear are deleted: nothing private points at a governance edge.
    """
    now = now or datetime.now(UTC)
    report = GraphSeedReport()
    governance = GraphType.GOVERNANCE.value

    for node in seed.nodes:
        values = {
            "graph_type": governance,
            "entity_type": node.entity_type,
            "key": node.key,
            "label": node.label,
            "summary": node.summary,
            "official_url": node.official_url,
            "properties_json": node.properties,
            "provenance": _provenance(node.evidence, passages, now),
            "source_id": site_ids.get(node.publisher or ""),
            "valid_to": None,
        }
        stmt = insert(GraphNode).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[GraphNode.key],
            index_where=text("graph_type = 'governance'"),
            set_={k: stmt.excluded[k] for k in values if k not in {"graph_type", "key"}},
        )
        await session.execute(stmt)
    report.nodes = len(seed.nodes)

    rows = await session.execute(
        select(GraphNode.key, GraphNode.id).where(GraphNode.graph_type == governance)
    )
    ids = {key: node_id for key, node_id in rows}
    keep = {node.key for node in seed.nodes}
    retired = [ids[key] for key in ids if key not in keep]
    if retired:
        result = await session.execute(
            update(GraphNode)
            .where(GraphNode.id.in_(retired), GraphNode.valid_to.is_(None))
            .values(valid_to=now.date())
        )
        report.nodes_retired = result.rowcount or 0  # type: ignore[attr-defined]

    edge_ids: dict[tuple[str, str, str], UUID] = {}
    for edge in seed.edges:
        edge_insert = insert(GraphEdge).values(
            graph_type=governance,
            relation=edge.relation.value,
            source_node_id=ids[edge.source],
            target_node_id=ids[edge.target],
            properties_json=edge.properties,
            provenance=_provenance(edge.evidence, passages, now),
        )
        upsert = edge_insert.on_conflict_do_update(
            constraint="uq_graph_edges_triple",
            set_={
                "properties_json": edge_insert.excluded.properties_json,
                "provenance": edge_insert.excluded.provenance,
            },
        ).returning(GraphEdge.id)
        edge_ids[edge.triple] = (await session.execute(upsert)).scalar_one()
    report.edges = len(seed.edges)

    existing = await session.execute(select(GraphEdge.id).where(GraphEdge.graph_type == governance))
    stale_edges = [edge_id for (edge_id,) in existing if edge_id not in set(edge_ids.values())]
    if stale_edges:
        await session.execute(delete(GraphEdge).where(GraphEdge.id.in_(stale_edges)))
        report.edges_pruned = len(stale_edges)

    # Evidence links always mirror the seed exactly.
    node_ids = [ids[n.key] for n in seed.nodes]
    await session.execute(delete(GraphNodeEvidence).where(GraphNodeEvidence.node_id.in_(node_ids)))
    await session.execute(
        delete(GraphEdgeEvidence).where(GraphEdgeEvidence.edge_id.in_(list(edge_ids.values())))
    )
    node_links = [
        {
            "node_id": ids[node.key],
            "document_id": passage.document_id,
            "chunk_id": chunk_id,
            "quote": passage.view.content[:2000],
        }
        for node in seed.nodes
        for ref in dict.fromkeys(node.evidence)
        for passage in [passages[ref]]
        for chunk_id in passage.chunk_ids
    ]
    edge_links = [
        {
            "edge_id": edge_ids[edge.triple],
            "document_id": passage.document_id,
            "chunk_id": chunk_id,
            "quote": passage.view.content[:2000],
        }
        for edge in seed.edges
        for ref in dict.fromkeys(edge.evidence)
        for passage in [passages[ref]]
        for chunk_id in passage.chunk_ids
    ]
    if node_links:
        await session.execute(insert(GraphNodeEvidence).on_conflict_do_nothing(), node_links)
    if edge_links:
        await session.execute(insert(GraphEdgeEvidence).on_conflict_do_nothing(), edge_links)
    report.evidence_links = len(node_links) + len(edge_links)
    logger.info(
        "governance graph seeded",
        extra={"nodes": report.nodes, "edges": report.edges, "retired": report.nodes_retired},
    )
    return report
