"""ORM → API contracts for the private user graph and documents."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.contracts.graph import GovernanceNodeOut
from app.contracts.user_documents import (
    DocumentDetailOut,
    DocumentOut,
    ExtractedFieldOut,
    ReviewTaskOut,
)
from app.contracts.user_graph import (
    AttributeSchemaOut,
    EntitySchemaOut,
    FactEvidenceOut,
    PersonalisationView,
    PlanningFactOut,
    UserEdgeOut,
    UserEntityOut,
    UserFactOut,
    UserGraphSchema,
    UserGraphView,
)
from app.db.models import GraphEdge, GraphNode
from app.db.models.user_data import ExtractedFact, ReviewTask, UserDocument
from app.documents.catalogue import KIND_LABELS, DocumentStatus
from app.documents.pipeline import DocumentAnalysis
from app.domain.enums import GraphType, TwinNodeType
from app.personalization.facts_model import FactStatus, ReviewTaskStatus
from app.personalization.projection import FactEvidence, PlanningFact, origin
from app.personalization.store import UserGraph, fact_view
from app.personalization.vocabulary import ENTITY_SPECS, UserEntityType
from app.services.presenters import governance_node_out


def _display(entity_type: str, attribute: str, value: Any) -> str | None:
    spec = ENTITY_SPECS.get(UserEntityType(entity_type))
    attr = spec.attributes.get(attribute) if spec else None
    if value is None:
        return None
    return attr.display(value) if attr else str(value)


def fact_out(
    fact: ExtractedFact, entity_type: str, document_kind: str | None = None
) -> UserFactOut:
    spec = ENTITY_SPECS[UserEntityType(entity_type)]
    attr = spec.attributes.get(fact.attribute)
    return UserFactOut(
        id=fact.id,
        node_id=fact.node_id,
        entity_type=TwinNodeType(entity_type),
        attribute=fact.attribute,
        attribute_label=attr.label if attr else fact.attribute,
        value=fact.value,
        value_display=_display(entity_type, fact.attribute, fact.value),
        confidence=fact.confidence,
        source=fact.source,
        source_document_id=fact.source_document_id,
        source_document_kind=document_kind,
        source_ref=fact.source_ref,
        extraction_method=fact.extraction_method,
        status=fact.status,
        confirmed_by_user=fact.confirmed_by_user,
        corrected=fact.corrected,
        issues=list(fact.issues or []),
        origin=origin(fact_view(fact, document_kind)),
        observed_at=fact.observed_at,
        updated_at=fact.updated_at,
    )


async def facts_out(session: Any, facts: Iterable[ExtractedFact]) -> list[UserFactOut]:
    """Present facts with their entity types and source-document kinds."""
    facts = list(facts)
    if not facts:
        return []
    types = dict(
        (
            await session.execute(
                select(GraphNode.id, GraphNode.entity_type).where(
                    GraphNode.id.in_({f.node_id for f in facts})
                )
            )
        ).all()
    )
    doc_ids = {f.source_document_id for f in facts if f.source_document_id}
    kinds: dict[UUID, str] = {}
    if doc_ids:
        rows = await session.execute(
            select(UserDocument.id, UserDocument.kind).where(UserDocument.id.in_(doc_ids))
        )
        kinds = {r[0]: r[1].value for r in rows.all()}
    return [
        fact_out(f, types[f.node_id], kinds.get(f.source_document_id))  # type: ignore[arg-type]
        for f in facts
        if f.node_id in types
    ]


async def user_graph_view(session: Any) -> UserGraphView:
    graph = UserGraph(session)
    nodes = await graph.nodes()
    facts = await facts_out(
        session, await graph.facts(statuses=(FactStatus.ACCEPTED, FactStatus.NEEDS_REVIEW))
    )
    edges = list(
        (
            await session.execute(
                select(GraphEdge).where(
                    GraphEdge.graph_type == GraphType.USER,
                    GraphEdge.user_id == graph.principal.user_id,
                )
            )
        ).scalars()
    )
    ids = {n.id for n in nodes}
    parents: dict[UUID, GraphEdge] = {}
    for edge in edges:
        if edge.target_node_id in ids:
            parents.setdefault(edge.target_node_id, edge)
    linked_ids = {e.target_node_id for e in edges if e.target_node_id not in ids}
    linked: list[GovernanceNodeOut] = []
    if linked_ids:
        governance = (
            await session.execute(
                select(GraphNode).where(
                    GraphNode.graph_type == GraphType.GOVERNANCE, GraphNode.id.in_(linked_ids)
                )
            )
        ).scalars()
        linked = [governance_node_out(n) for n in governance]
    by_node: dict[UUID, list[UserFactOut]] = {}
    for fact in facts:
        by_node.setdefault(fact.node_id, []).append(fact)
    open_tasks = (
        await session.execute(
            select(func.count()).where(
                ReviewTask.user_id == graph.principal.user_id,
                ReviewTask.status == ReviewTaskStatus.OPEN,
            )
        )
    ).scalar_one()

    def status(node_facts: list[UserFactOut]) -> str:
        accepted = [f for f in node_facts if f.status is FactStatus.ACCEPTED]
        if not accepted:
            return "proposed"
        return "confirmed" if all(f.confirmed_by_user for f in accepted) else "unconfirmed"

    return UserGraphView(
        nodes=[
            UserEntityOut(
                id=n.id,
                type=TwinNodeType(n.entity_type),
                key=n.key,
                label=n.label,
                parent_id=parents[n.id].source_node_id if n.id in parents else None,
                relation=parents[n.id].relation if n.id in parents else None,
                status=status(by_node.get(n.id, [])),  # type: ignore[arg-type]
                facts=by_node.get(n.id, []),
            )
            for n in nodes
        ],
        edges=[
            UserEdgeOut(
                id=e.id,
                relation=e.relation,
                source=e.source_node_id,
                target=e.target_node_id,
                links_to_governance=e.target_node_id not in ids,
            )
            for e in edges
        ],
        linked_governance_nodes=linked,
        open_review_tasks=open_tasks,
        generated_at=datetime.now(UTC),
    )


def schema_out() -> UserGraphSchema:
    return UserGraphSchema(
        entities=[
            EntitySchemaOut(
                type=TwinNodeType(spec.type.value),
                label=spec.label,
                cardinality=spec.cardinality.value,  # type: ignore[arg-type]
                relation=spec.relation.value if spec.relation else None,  # type: ignore[arg-type]
                parents=[TwinNodeType(p.value) for p in spec.parents],
                identity=spec.identity,
                attributes=[
                    AttributeSchemaOut(
                        name=a.name,
                        label=a.label,
                        kind=a.kind.value,
                        choices=[{"value": v, "label": label} for v, label in a.choices],
                        sensitive=a.sensitive,
                    )
                    for a in spec.attributes.values()
                ],
            )
            for spec in ENTITY_SPECS.values()
        ]
    )


def evidence_out(item: FactEvidence) -> FactEvidenceOut:
    return FactEvidenceOut(
        fact_id=item.fact_id,
        removed=item.removed,
        entity_type=TwinNodeType(item.entity_type) if item.entity_type else None,
        entity_label=item.entity_label,
        attribute=item.attribute,
        attribute_label=item.attribute_label,
        value_display=item.value_display,
        origin=item.origin,
        source=item.source,  # type: ignore[arg-type]
        source_document_id=item.source_document_id,
        confirmed_by_user=item.confirmed_by_user,
        statement=item.statement,
    )


def personalisation_out(
    facts: list[PlanningFact], evidence_by_fact: dict[UUID, FactEvidence]
) -> PersonalisationView:
    return PersonalisationView(
        facts=[
            PlanningFactOut(
                key=p.key,
                label=p.label,
                value=p.value,
                source=p.source,  # type: ignore[arg-type]
                confidence=p.confidence,
                confirmed=p.confirmed,
                fact_ids=p.fact_ids,
                basis=[
                    evidence_out(evidence_by_fact[i]) for i in p.fact_ids if i in evidence_by_fact
                ],
            )
            for p in facts
        ],
        generated_at=datetime.now(UTC),
    )


def document_out(document: UserDocument, *, open_tasks: int, api_prefix: str) -> DocumentOut:
    extraction = document.extraction or {}
    active = document.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING)
    return DocumentOut(
        id=document.id,
        kind=document.kind,
        kind_label=KIND_LABELS[document.kind],
        declared_kind=document.declared_kind,
        subject=document.subject,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=document.status,
        status_reason=document.status_reason,
        extraction_method=extraction.get("method"),
        mrz_verified=None if extraction.get("mrz") is None else extraction.get("mrz") == "verified",
        open_review_tasks=open_tasks,
        extraction_run_id=document.extraction_run_id,
        events_url=(
            f"{api_prefix}/agents/{document.extraction_run_id}/events"
            if active and document.extraction_run_id
            else None
        ),
        created_at=document.created_at,
        processed_at=document.processed_at,
    )


async def review_tasks_out(session: Any, tasks: list[ReviewTask]) -> list[ReviewTaskOut]:
    fact_ids = [t.fact_id for t in tasks if t.fact_id]
    facts = {}
    if fact_ids:
        rows = (
            await session.execute(select(ExtractedFact).where(ExtractedFact.id.in_(fact_ids)))
        ).scalars()
        facts = {f.id: f for f in await facts_out(session, rows)}
    doc_ids = {t.document_id for t in tasks if t.document_id}
    kinds = {}
    if doc_ids:
        kinds = dict(
            (
                await session.execute(
                    select(UserDocument.id, UserDocument.kind).where(UserDocument.id.in_(doc_ids))
                )
            ).all()
        )
    return [
        ReviewTaskOut(
            id=t.id,
            kind=t.kind,
            status=t.status,
            resolution=t.resolution,
            message=t.message,
            field=t.field,
            document_id=t.document_id,
            document_kind=kinds.get(t.document_id),
            fact=facts.get(t.fact_id) if t.fact_id else None,
            created_at=t.created_at,
            resolved_at=t.resolved_at,
        )
        for t in tasks
    ]


async def document_detail_out(
    session: Any,
    document: UserDocument,
    analysis: DocumentAnalysis,
    tasks: list[ReviewTask],
    *,
    api_prefix: str,
    content_url: str,
) -> DocumentDetailOut:
    facts = await facts_out(
        session,
        (
            await session.execute(
                select(ExtractedFact).where(ExtractedFact.source_document_id == document.id)
            )
        ).scalars(),
    )
    by_id = {f.id: f for f in facts}
    base = document_out(document, open_tasks=len(tasks), api_prefix=api_prefix)
    return DocumentDetailOut(
        **base.model_dump(),
        fields=[
            ExtractedFieldOut(
                name=f.name,
                label=f.label,
                value=f.value,
                # A list (e.g. business activities) is several facts: show every item.
                value_display=", ".join(str(v) for v in f.value)
                if isinstance(f.value, list)
                else by_id[f.fact_id].value_display
                if f.fact_id in by_id
                else None,
                confidence=f.confidence,
                needs_review=f.needs_review,
                fact_id=f.fact_id,
                issues=f.issues,
            )
            for f in analysis.fields
        ],
        facts=facts,
        review_tasks=await review_tasks_out(session, tasks),
        warnings=list((document.extraction or {}).get("warnings", [])),
        content_url=content_url,
    )
