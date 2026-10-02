"""Persistence for one user's private graph: entities, relations and facts.

`UserGraph` needs a user-scoped session (`Database.user_session(principal)`): row-level
security confines every statement to the caller's rows, and every query also filters
on the caller's `user_id` and `graph_type = 'user'` explicitly.

Invariants enforced here (and again by the database where it can):
* facts use the closed vocabulary; values are normalised to their canonical form;
* sensitive attributes are user-stated only, and faith needs the person's opt-in;
* at most one accepted and one pending value per (entity, attribute);
* entities exist while facts support them; `prune` removes the rest (never the hub);
* documents link to public governance nodes by reference (`instance_of`), never by copy.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GraphEdge, GraphNode, User
from app.db.models.user_data import ExtractedFact, UserDocument
from app.db.session import session_principal
from app.documents.structuring import EntityRef, governance_document_key
from app.domain.enums import FactSource, GraphEdgeType, GraphType
from app.domain.principal import Principal
from app.personalization.facts_model import FactStatus
from app.personalization.projection import FactView, GraphSnapshot, NodeView
from app.personalization.values import ValueIssue
from app.personalization.vocabulary import (
    ENTITY_SPECS,
    FAITH_ATTRIBUTES,
    HUB_KEY,
    Cardinality,
    FactRuleError,
    UserEntityType,
    UserRelation,
    check_parent,
    entity_key,
    entity_label,
    spec_for,
)

USER_RELATIONS = frozenset(GraphEdgeType(r.value) for r in UserRelation)


def _entity(node: GraphNode) -> UserEntityType:
    return UserEntityType(node.entity_type)


class UserGraph:
    def __init__(self, session: AsyncSession) -> None:
        principal = session_principal(session)
        if principal is None:
            raise RuntimeError("UserGraph requires a user-scoped session")
        self.session = session
        self.principal: Principal = principal

    # --- consent ---------------------------------------------------------------------
    async def consents(self) -> tuple[bool, bool]:
        """(faith personalisation granted, community personalisation granted)."""
        prefs: dict[str, Any] = (
            await self.session.execute(
                select(User.preferences).where(User.id == self.principal.user_id)
            )
        ).scalar_one_or_none() or {}
        return (
            prefs.get("faith_personalization") == "granted",
            prefs.get("community_personalization") == "granted",
        )

    # --- nodes -----------------------------------------------------------------------
    def _mine(self) -> Any:
        return and_(
            GraphNode.graph_type == GraphType.USER, GraphNode.user_id == self.principal.user_id
        )

    async def nodes(self) -> list[GraphNode]:
        query = select(GraphNode).where(self._mine()).order_by(GraphNode.created_at, GraphNode.key)
        return list((await self.session.execute(query)).scalars())

    async def node(self, node_id: UUID) -> GraphNode | None:
        query = select(GraphNode).where(self._mine(), GraphNode.id == node_id)
        return (await self.session.execute(query)).scalar_one_or_none()

    async def by_key(self, key: str) -> GraphNode | None:
        query = select(GraphNode).where(self._mine(), GraphNode.key == key)
        return (await self.session.execute(query)).scalar_one_or_none()

    async def hub(self) -> GraphNode:
        return await self._insert_node(UserEntityType.PERSON, HUB_KEY)

    async def _insert_node(self, entity_type: UserEntityType, key: str) -> GraphNode:
        p = self.principal
        stmt = (
            insert(GraphNode)
            .values(
                graph_type=GraphType.USER.value,
                tenant_id=p.tenant_id,
                user_id=p.user_id,
                entity_type=entity_type.value,
                key=key,
                label=ENTITY_SPECS[entity_type].label,
            )
            .on_conflict_do_nothing(
                index_elements=[GraphNode.user_id, GraphNode.key],
                # A literal predicate: Postgres can't infer a partial index from a parameter.
                index_where=text("graph_type = 'user'"),
            )
            .returning(GraphNode)
        )
        node = (await self.session.execute(stmt)).scalar_one_or_none()
        if node is None:
            node = await self.by_key(key)
            if node is None:  # pragma: no cover - conflicting row invisible under RLS
                raise RuntimeError("user graph node could not be created")
            if node.entity_type != entity_type.value:
                raise FactRuleError("That entity already exists with another type")
        return node

    async def ensure_node(
        self,
        entity_type: UserEntityType,
        *,
        parent: GraphNode | None = None,
        instance: str | None = None,
    ) -> GraphNode:
        """Find or create an entity under `parent` (default: the user) and its edge."""
        spec = ENTITY_SPECS[entity_type]
        if spec.cardinality is Cardinality.HUB:
            return await self.hub()
        parent = parent or await self.hub()
        check_parent(spec, _entity(parent))
        key = entity_key(entity_type, parent_key=parent.key, instance=instance)
        node = await self._insert_node(
            entity_type, key or f"{entity_type.value}.{uuid4().hex[:12]}"
        )
        assert spec.relation is not None
        await self.link(GraphEdgeType(spec.relation.value), parent, node)
        return node

    async def resolve(self, ref: EntityRef) -> GraphNode:
        if ref.node_id is not None:
            node = await self.node(ref.node_id)
            if node is None or _entity(node) is not ref.type:
                raise FactRuleError("That entity is not in your twin", code="unknown_entity")
            return node
        parent = await self.resolve(ref.parent) if ref.parent is not None else None
        return await self.ensure_node(ref.type, parent=parent, instance=ref.instance)

    async def parent_of(self, node: GraphNode) -> GraphNode | None:
        spec = ENTITY_SPECS[_entity(node)]
        if spec.relation is None:
            return None
        query = (
            select(GraphNode)
            .join(GraphEdge, GraphEdge.source_node_id == GraphNode.id)
            .where(
                self._mine(),
                GraphEdge.target_node_id == node.id,
                GraphEdge.relation == GraphEdgeType(spec.relation.value),
            )
            .limit(1)
        )
        return (await self.session.execute(query)).scalar_one_or_none()

    async def link(self, relation: GraphEdgeType, source: GraphNode, target: GraphNode) -> None:
        p = self.principal
        stmt = (
            insert(GraphEdge)
            .values(
                graph_type=GraphType.USER.value,
                tenant_id=p.tenant_id,
                user_id=p.user_id,
                relation=relation.value,
                source_node_id=source.id,
                target_node_id=target.id,
            )
            .on_conflict_do_nothing(constraint="uq_graph_edges_triple")
        )
        await self.session.execute(stmt)

    async def refresh_label(self, node: GraphNode) -> None:
        values = {f.attribute: f.value for f in await self.facts(node_ids=[node.id])}
        label = entity_label(ENTITY_SPECS[_entity(node)], values)
        if node.label != label:
            node.label = label
            await self.session.flush()

    async def sync_governance_link(self, node: GraphNode) -> str | None:
        """Keep `node -instance_of-> governance document` in step with the node's facts."""
        entity_type = _entity(node)
        if entity_type not in (UserEntityType.PASSPORT, UserEntityType.DOCUMENT):
            return None
        values = {f.attribute: f.value for f in await self.facts(node_ids=[node.id])}
        key = governance_document_key(entity_type, values)
        target = None
        if key is not None:
            target = (
                await self.session.execute(
                    select(GraphNode).where(
                        GraphNode.graph_type == GraphType.GOVERNANCE, GraphNode.key == key
                    )
                )
            ).scalar_one_or_none()
        stale = delete(GraphEdge).where(
            GraphEdge.user_id == self.principal.user_id,
            GraphEdge.source_node_id == node.id,
            GraphEdge.relation == GraphEdgeType.INSTANCE_OF,
        )
        if target is not None:
            stale = stale.where(GraphEdge.target_node_id != target.id)
        await self.session.execute(stale)
        if target is not None:
            await self.link(GraphEdgeType.INSTANCE_OF, node, target)
            return key
        return None

    async def prune(self, node_ids: Iterable[UUID] | None = None) -> int:
        """Delete entities no fact supports any more (and that have no child entities)."""
        removed = 0
        while True:
            has_facts = exists().where(ExtractedFact.node_id == GraphNode.id)
            has_children = exists().where(
                GraphEdge.source_node_id == GraphNode.id, GraphEdge.relation.in_(USER_RELATIONS)
            )
            query = select(GraphNode.id).where(
                self._mine(), GraphNode.key != HUB_KEY, ~has_facts, ~has_children
            )
            if node_ids is not None:
                query = query.where(GraphNode.id.in_(list(node_ids)))
            ids = list((await self.session.execute(query)).scalars())
            if not ids:
                return removed
            parents = select(GraphEdge.source_node_id).where(
                GraphEdge.target_node_id.in_(ids), GraphEdge.relation.in_(USER_RELATIONS)
            )
            parent_ids = set((await self.session.execute(parents)).scalars())
            await self.session.execute(delete(GraphNode).where(self._mine(), GraphNode.id.in_(ids)))
            removed += len(ids)
            if node_ids is None:
                continue
            node_ids = parent_ids  # a parent may now be bare too

    # --- facts -----------------------------------------------------------------------
    async def facts(
        self,
        *,
        node_ids: Sequence[UUID] | None = None,
        statuses: Sequence[FactStatus] = (FactStatus.ACCEPTED,),
        document_id: UUID | None = None,
    ) -> list[ExtractedFact]:
        query = select(ExtractedFact).where(
            ExtractedFact.user_id == self.principal.user_id,
            ExtractedFact.status.in_([s.value for s in statuses]),
        )
        if node_ids is not None:
            query = query.where(ExtractedFact.node_id.in_(list(node_ids)))
        if document_id is not None:
            query = query.where(ExtractedFact.source_document_id == document_id)
        query = query.order_by(ExtractedFact.created_at, ExtractedFact.attribute)
        return list((await self.session.execute(query)).scalars())

    async def fact(self, fact_id: UUID) -> ExtractedFact | None:
        query = select(ExtractedFact).where(
            ExtractedFact.user_id == self.principal.user_id, ExtractedFact.id == fact_id
        )
        return (await self.session.execute(query)).scalar_one_or_none()

    async def normalise(self, node: GraphNode, attribute: str, raw: Any, source: FactSource) -> Any:
        """Validate a value for an entity's attribute; returns the canonical value."""
        spec = spec_for(node.entity_type)
        attr = spec.attribute(attribute)
        if attr.sensitive:
            if source is not FactSource.USER_STATED:
                raise FactRuleError(
                    f"{attr.label} is only ever recorded when you state it yourself",
                    code="sensitive_attribute",
                )
            faith, _ = await self.consents()
            if attribute in FAITH_ATTRIBUTES and not faith:
                raise FactRuleError(
                    "Turn on faith personalisation in Settings before adding this",
                    code="consent_required",
                )
        if raw is None:
            return None
        try:
            return attr.normalize(raw).value
        except ValueIssue as issue:
            raise FactRuleError(f"{attr.label}: {issue}", code="invalid_value") from issue

    async def write_fact(
        self,
        node: GraphNode,
        attribute: str,
        raw_value: Any,
        *,
        source: FactSource,
        status: FactStatus = FactStatus.ACCEPTED,
        confidence: float = 1.0,
        source_document_id: UUID | None = None,
        source_ref: str | None = None,
        extraction_method: str | None = None,
        field: str | None = None,
        confirmed: bool = False,
        corrected: bool = False,
        issues: Sequence[str] = (),
    ) -> ExtractedFact:
        """Insert or replace the (entity, attribute) fact with the given status."""
        value = await self.normalise(node, attribute, raw_value, source)
        if status is FactStatus.ACCEPTED and value is None:
            raise FactRuleError("A value is required", code="invalid_value")
        existing = (
            await self.session.execute(
                select(ExtractedFact).where(
                    ExtractedFact.user_id == self.principal.user_id,
                    ExtractedFact.node_id == node.id,
                    ExtractedFact.attribute == attribute,
                    ExtractedFact.status == status.value,
                )
            )
        ).scalar_one_or_none()
        fact = existing or ExtractedFact(
            tenant_id=self.principal.tenant_id,
            user_id=self.principal.user_id,
            node_id=node.id,
            attribute=attribute,
            status=status,
        )
        fact.value = value
        fact.confidence = round(max(0.0, min(1.0, confidence)), 3)
        fact.source = source
        fact.source_document_id = source_document_id
        fact.source_ref = source_ref
        fact.extraction_method = extraction_method
        fact.field = field
        fact.confirmed_by_user = confirmed
        fact.corrected = corrected
        fact.issues = list(issues)
        if existing is None:
            self.session.add(fact)
        await self.session.flush()
        return fact

    async def promote(self, fact: ExtractedFact) -> None:
        """Make a pending fact the accepted one (replacing any earlier accepted value)."""
        if fact.status is FactStatus.ACCEPTED:
            return
        await self.session.execute(
            delete(ExtractedFact).where(
                ExtractedFact.user_id == self.principal.user_id,
                ExtractedFact.node_id == fact.node_id,
                ExtractedFact.attribute == fact.attribute,
                ExtractedFact.status == FactStatus.ACCEPTED.value,
            )
        )
        await self.session.flush()
        fact.status = FactStatus.ACCEPTED
        fact.issues = []
        await self.session.flush()

    async def delete_facts(self, where: Any) -> list[tuple[UUID, UUID | None]]:
        """Delete facts matching `where`; returns (node_id, source_document_id) pairs."""
        rows = (
            await self.session.execute(
                delete(ExtractedFact)
                .where(ExtractedFact.user_id == self.principal.user_id, where)
                .returning(ExtractedFact.node_id, ExtractedFact.source_document_id)
            )
        ).all()
        return [(r[0], r[1]) for r in rows]

    # --- projection ------------------------------------------------------------------
    async def snapshot(self) -> GraphSnapshot:
        nodes = await self.nodes()
        edges = list(
            (
                await self.session.execute(
                    select(GraphEdge).where(
                        GraphEdge.graph_type == GraphType.USER,
                        GraphEdge.user_id == self.principal.user_id,
                    )
                )
            ).scalars()
        )
        by_id = {n.id: n for n in nodes}
        parents: dict[UUID, UUID] = {}
        instance_targets: dict[UUID, list[UUID]] = {}
        for edge in edges:
            target = by_id.get(edge.target_node_id)
            if target is None:
                if edge.relation is GraphEdgeType.INSTANCE_OF:
                    instance_targets.setdefault(edge.source_node_id, []).append(edge.target_node_id)
                continue
            relation = ENTITY_SPECS[_entity(target)].relation
            if relation is not None and edge.relation.value == relation.value:
                parents[target.id] = edge.source_node_id
        governance_keys: dict[UUID, str] = {}
        wanted = {t for ts in instance_targets.values() for t in ts}
        if wanted:
            keyed = await self.session.execute(
                select(GraphNode.id, GraphNode.key).where(
                    GraphNode.graph_type == GraphType.GOVERNANCE, GraphNode.id.in_(wanted)
                )
            )
            governance_keys = {r[0]: r[1] for r in keyed}

        rows = await self.session.execute(
            select(ExtractedFact, UserDocument.kind)
            .outerjoin(UserDocument, UserDocument.id == ExtractedFact.source_document_id)
            .where(ExtractedFact.user_id == self.principal.user_id)
            .order_by(ExtractedFact.created_at)
        )
        facts = [fact_view(f, kind.value if kind else None) for f, kind in rows.all()]
        faith, community = await self.consents()
        return GraphSnapshot(
            nodes={
                n.id: NodeView(n.id, _entity(n), n.key, n.label, parents.get(n.id), i)
                for i, n in enumerate(nodes)
            },
            facts=facts,
            instance_of={
                node_id: [governance_keys[t] for t in targets if t in governance_keys]
                for node_id, targets in instance_targets.items()
            },
            faith_consent=faith,
            community_consent=community,
        )


def fact_view(fact: ExtractedFact, document_kind: str | None = None) -> FactView:
    return FactView(
        id=fact.id,
        node_id=fact.node_id,
        attribute=fact.attribute,
        value=fact.value,
        source=FactSource(fact.source).value,
        confidence=fact.confidence,
        confirmed_by_user=fact.confirmed_by_user,
        status=FactStatus(fact.status).value,
        corrected=fact.corrected,
        source_document_id=fact.source_document_id,
        source_document_kind=document_kind,
        source_ref=fact.source_ref,
        extraction_method=fact.extraction_method,
    )
