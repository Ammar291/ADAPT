"""Explain a requirement for a user: graph nodes + evidence + reasoning inputs + next step.

The response is shaped for visual tracing. Every check (`ReasoningInput`) links

    fact:<key>  --checked_against-->  node:<requirement>  --evidenced_by-->  evidence:<id>
                                                           --supports-->     task:<service key>

and `links` flattens those chains, so the UI can highlight one path end to end.
Facts are used for this computation only: they are never stored or logged.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings import Embedder
from app.core.errors import NotFound
from app.knowledge.evaluator import GNode, GovernanceSubgraph, RequirementEvaluator
from app.knowledge.graph_view import EvidenceBook, knowledge_edge, knowledge_node, load_snapshot
from app.knowledge.retrieval import match_nodes, retrieve
from app.knowledge.schemas import (
    Evidence,
    ExplainRequest,
    ExplainResponse,
    FactUse,
    HighlightLink,
    ReasoningInput,
    ResolvedRequirement,
    RetrievalFilters,
)

RESOLVABLE_TYPES = (
    "service",
    "requirement",
    "eligibility_rule",
    "document",
    "appointment",
    "dependency",
)


async def resolve_requirement(
    session: AsyncSession, embedder: Embedder, text: str, graph: GovernanceSubgraph
) -> tuple[GNode, ResolvedRequirement, list[Evidence]]:
    """A node key or id resolves exactly; plain words resolve by search."""
    node = graph.by_key.get(text.strip())
    if node is None:
        try:
            node = graph.nodes.get(UUID(text.strip()))
        except ValueError:
            node = None
    if node is not None:
        resolved = ResolvedRequirement(
            node_id=node.id,
            key=node.key,
            label=node.label,
            entity_type=node.entity_type,
            method="key",
            confidence=1.0,
        )
        return node, resolved, []
    found = await retrieve(session, embedder, text, top_k=8)
    matches = await match_nodes(
        session,
        text,
        evidence=found.evidence,
        types=RESOLVABLE_TYPES,
        limit=4,
        require_lexical=embedder.mode == "demo",
    )
    matches = [m for m in matches if m.id in graph.nodes]
    if not matches:
        raise NotFound(
            "No governance service or requirement matches that description",
            code="requirement_not_found",
        )
    best = graph.nodes[matches[0].id]
    resolved = ResolvedRequirement(
        node_id=best.id,
        key=best.key,
        label=best.label,
        entity_type=best.entity_type,
        method="search",
        confidence=min(1.0, round(matches[0].score, 2)),
        alternatives=matches[1:],
    )
    return best, resolved, found.evidence


def service_for(node: GNode, graph: GovernanceSubgraph) -> GNode:
    """The service whose requirements answer a question about `node`."""
    if node.entity_type == "service":
        return node
    candidates: list[GNode] = []
    if node.entity_type == "document":
        candidates = graph.producers_of(node) + [s for _, s in graph.inc(node, "requires")]
    elif node.entity_type == "eligibility_rule":
        candidates = [s for _, s in graph.out(node, "applies_to")] + [
            s for _, s in graph.inc(node, "requires")
        ]
    elif node.entity_type == "requirement":
        candidates = [s for _, s in graph.inc(node, "requires")]
    elif node.entity_type == "appointment":
        candidates = [s for _, s in graph.inc(node, "may_require")]
    elif node.entity_type == "dependency":
        candidates = [s for _, s in graph.inc(node, "depends_on")]
    services = [c for c in candidates if c.entity_type == "service"]
    if not services:
        raise NotFound(
            f"'{node.label}' is not linked to a service ADAPT can assess",
            code="requirement_not_assessable",
        )
    return services[0]


def _related_nodes(
    graph: GovernanceSubgraph, service: GNode, checks: list[ReasoningInput]
) -> set[UUID]:
    ids = {service.id}
    ids |= {c.node_id for c in checks}
    ids |= {c.task.node_id for c in checks if c.task}
    for relation in ("available_at", "may_require", "produces"):
        ids |= {n.id for _, n in graph.out(service, relation)}
    ids |= {n.id for _, n in graph.inc(service, "provides")}
    for check in checks:
        node = graph.nodes[check.node_id]
        if node.entity_type == "dependency":
            ids |= {n.id for _, n in graph.out(node, "satisfied_by")}
        if check.task:
            task_node = graph.nodes[check.task.node_id]
            ids |= {n.id for _, n in graph.out(task_node, "available_at")}
    return ids


def _dedup(items: Iterable[Evidence]) -> list[Evidence]:
    seen: dict[str, Evidence] = {}
    for item in items:
        seen.setdefault(item.id, item)
    return list(seen.values())


async def explain(
    session: AsyncSession,
    embedder: Embedder,
    request: ExplainRequest,
    *,
    now: datetime | None = None,
) -> ExplainResponse:
    now = now or datetime.now(UTC)
    snapshot = await load_snapshot(session)
    graph = snapshot.subgraph()
    focus, resolved, found = await resolve_requirement(
        session, embedder, request.requirement, graph
    )
    service = service_for(focus, graph)

    facts = {f.key: f.value for f in request.facts}
    labels = {f.key: f.label for f in request.facts}
    assessment = RequirementEvaluator(
        graph, facts, subject=request.subject, fact_labels=labels
    ).assess(service)

    book = EvidenceBook(snapshot, now=now)
    checks = assessment.checks
    for check in checks:
        evidence = (book.for_edge(check.edge_id) if check.edge_id else []) + book.for_node(
            check.node_id
        )
        check.evidence_ids = [e.id for e in _dedup(evidence)]
    step = assessment.next_step
    step_evidence = [eid for c in checks if c.id in step.check_ids for eid in c.evidence_ids]
    step_evidence += [e.id for e in book.for_node(step.node_id)]
    step.evidence_ids = list(dict.fromkeys(step_evidence))

    query = request.requirement if resolved.method == "search" else service.label
    if not found or resolved.method == "key":
        found = (
            await retrieve(
                session,
                embedder,
                query,
                top_k=request.top_k,
                filters=RetrievalFilters(official_only=True),
                now=now,
            )
        ).evidence
    retrieved = found[: request.top_k]

    node_ids = _related_nodes(graph, service, checks) | {focus.id}
    by_id = {n.id: n for n in snapshot.nodes}
    nodes = [knowledge_node(by_id[i], book.for_node(i)) for i in node_ids if i in by_id]
    nodes.sort(key=lambda n: (n.id != service.id, n.entity_type, n.label))
    edges = [
        knowledge_edge(e, book.for_edge(e.id))
        for e in snapshot.edges
        if e.source_node_id in node_ids and e.target_node_id in node_ids
    ]

    links: list[HighlightLink] = []
    for check in checks:
        for fact in check.facts:
            links.append(
                HighlightLink(
                    source=f"fact:{fact.key}",
                    target=f"node:{check.node_id}",
                    relation="checked_against",
                    check_id=check.id,
                    status=check.status,
                )
            )
        task_target = f"task:{check.task.key}" if check.task else None
        for eid in check.evidence_ids:
            links.append(
                HighlightLink(
                    source=f"node:{check.node_id}",
                    target=f"evidence:{eid}",
                    relation="evidenced_by",
                    check_id=check.id,
                    status=check.status,
                )
            )
            if task_target:
                links.append(
                    HighlightLink(
                        source=f"evidence:{eid}",
                        target=task_target,
                        relation="supports",
                        check_id=check.id,
                        status=check.status,
                    )
                )
        if task_target and not check.evidence_ids:
            links.append(
                HighlightLink(
                    source=f"node:{check.node_id}",
                    target=task_target,
                    relation="supports",
                    check_id=check.id,
                    status=check.status,
                )
            )

    facts_used: dict[str, FactUse] = {}
    for check in checks:
        for fact in check.facts:
            facts_used.setdefault(fact.key, fact)

    evidence = _dedup([*book.used(), *retrieved])
    return ExplainResponse(
        requirement=resolved,
        overall=assessment.overall,
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        retrieved_evidence_ids=[e.id for e in retrieved],
        reasoning_inputs=checks,
        links=links,
        next_step=step,
        facts_used=list(facts_used.values()),
        generated_at=now,
    )
