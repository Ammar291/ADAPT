"""Graph repositories.

`GovernanceGraphRepository` filters on `graph_type = 'governance'` explicitly in every query
(in addition to RLS), so public endpoints can never surface user-graph rows even when
called with a user-scoped session. `UserGraphRepository` always acts for one principal
and additionally filters on its `user_id`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GraphEdge, GraphNode
from app.db.session import session_principal
from app.domain.enums import ConsentStatus, GovernanceNodeType, GraphEdgeType, GraphType
from app.domain.graph import edge_graph_type
from app.domain.principal import Principal


def _live_governance() -> Any:
    """Governance nodes retired by the curators (valid_to in the past) are hidden."""
    return (GraphNode.graph_type == GraphType.GOVERNANCE) & or_(
        GraphNode.valid_to.is_(None), GraphNode.valid_to >= date.today()
    )


class GovernanceGraphRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def nodes(
        self,
        *,
        types: Sequence[GovernanceNodeType] | None = None,
        search: str | None = None,
        limit: int = 2000,
    ) -> list[GraphNode]:
        query = select(GraphNode).where(_live_governance())
        if types:
            query = query.where(GraphNode.entity_type.in_([t.value for t in types]))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    GraphNode.label.ilike(pattern),
                    GraphNode.key.ilike(pattern),
                    GraphNode.summary.ilike(pattern),
                )
            )
        query = query.order_by(GraphNode.entity_type, GraphNode.label).limit(limit)
        return list((await self._session.execute(query)).scalars())

    async def by_ids(self, ids: Sequence[UUID]) -> list[GraphNode]:
        if not ids:
            return []
        query = select(GraphNode).where(_live_governance(), GraphNode.id.in_(ids))
        return list((await self._session.execute(query)).scalars())

    async def by_keys(self, keys: Sequence[str]) -> dict[str, GraphNode]:
        if not keys:
            return {}
        query = select(GraphNode).where(_live_governance(), GraphNode.key.in_(keys))
        return {n.key: n for n in (await self._session.execute(query)).scalars()}

    async def edges_between(self, node_ids: Sequence[UUID]) -> list[GraphEdge]:
        if not node_ids:
            return []
        query = select(GraphEdge).where(
            GraphEdge.graph_type == GraphType.GOVERNANCE,
            GraphEdge.source_node_id.in_(node_ids),
            GraphEdge.target_node_id.in_(node_ids),
        )
        return list((await self._session.execute(query)).scalars())

    async def get(self, ref: str) -> GraphNode | None:
        """Look a governance node up by UUID or by stable key."""
        query = select(GraphNode).where(_live_governance())
        try:
            query = query.where(GraphNode.id == UUID(ref))
        except ValueError:
            query = query.where(GraphNode.key == ref)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def neighbourhood(self, node_id: UUID) -> tuple[list[GraphNode], list[GraphEdge]]:
        edges = list(
            (
                await self._session.execute(
                    select(GraphEdge).where(
                        GraphEdge.graph_type == GraphType.GOVERNANCE,
                        or_(
                            GraphEdge.source_node_id == node_id,
                            GraphEdge.target_node_id == node_id,
                        ),
                    )
                )
            ).scalars()
        )
        ids = {e.source_node_id for e in edges} | {e.target_node_id for e in edges}
        ids.discard(node_id)
        return await self.by_ids(list(ids)), edges


class UserGraphRepository:
    """Reads and writes one user's private graph. Requires a `user_session(principal)`."""

    def __init__(self, session: AsyncSession) -> None:
        principal = session_principal(session)
        if principal is None:
            raise RuntimeError("UserGraphRepository requires a user-scoped session")
        self._session = session
        self._principal: Principal = principal

    @property
    def principal(self) -> Principal:
        return self._principal

    async def graph(self) -> tuple[list[GraphNode], list[GraphNode], list[GraphEdge]]:
        """Returns (user nodes, governance nodes linked from the user graph, user edges)."""
        p = self._principal
        user_nodes = list(
            (
                await self._session.execute(
                    select(GraphNode)
                    .where(GraphNode.graph_type == GraphType.USER, GraphNode.user_id == p.user_id)
                    .order_by(GraphNode.entity_type, GraphNode.label)
                )
            ).scalars()
        )
        edges = list(
            (
                await self._session.execute(
                    select(GraphEdge).where(
                        GraphEdge.graph_type == GraphType.USER, GraphEdge.user_id == p.user_id
                    )
                )
            ).scalars()
        )
        own_ids = {n.id for n in user_nodes}
        linked_ids = {e.target_node_id for e in edges if e.target_node_id not in own_ids}
        linked = await GovernanceGraphRepository(self._session).by_ids(list(linked_ids))
        return user_nodes, linked, edges

    async def get_by_key(self, key: str) -> GraphNode | None:
        p = self._principal
        return (
            await self._session.execute(
                select(GraphNode).where(
                    GraphNode.graph_type == GraphType.USER,
                    GraphNode.user_id == p.user_id,
                    GraphNode.key == key,
                )
            )
        ).scalar_one_or_none()

    async def upsert_node(
        self,
        *,
        entity_type: str,
        key: str,
        label: str,
        properties: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> GraphNode:
        """Create or update a user-graph node; new properties are merged over existing ones."""
        p = self._principal
        values: dict[str, Any] = {
            "graph_type": GraphType.USER.value,
            "tenant_id": p.tenant_id,
            "user_id": p.user_id,
            "entity_type": entity_type,
            "key": key,
            "label": label,
            "summary": summary,
            "properties_json": properties or {},
        }
        stmt = insert(GraphNode).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[GraphNode.user_id, GraphNode.key],
            index_where=text("graph_type = 'user'"),
            set_={
                "entity_type": stmt.excluded.entity_type,
                "label": stmt.excluded.label,
                "summary": stmt.excluded.summary,
                "properties_json": GraphNode.properties_json.op("||")(
                    stmt.excluded.properties_json
                ),
                "updated_at": text("now()"),
            },
        ).returning(GraphNode)
        node = (await self._session.execute(stmt)).scalar_one()
        await self._session.refresh(node)
        return node

    async def link(
        self,
        relation: GraphEdgeType,
        source: GraphNode,
        target: GraphNode,
        *,
        properties: dict[str, Any] | None = None,
    ) -> GraphEdge:
        """Add a user edge (user->user or user->governance). Validated by the domain rule,
        then again by the database trigger and RLS."""
        graph_type = edge_graph_type(
            relation, GraphType(source.graph_type), GraphType(target.graph_type)
        )
        p = self._principal
        stmt = (
            insert(GraphEdge)
            .values(
                graph_type=graph_type.value,
                tenant_id=p.tenant_id,
                user_id=p.user_id,
                relation=relation.value,
                source_node_id=source.id,
                target_node_id=target.id,
                properties_json=properties or {},
            )
            .on_conflict_do_nothing(constraint="uq_graph_edges_triple")
            .returning(GraphEdge)
        )
        edge = (await self._session.execute(stmt)).scalar_one_or_none()
        if edge is None:
            edge = (
                await self._session.execute(
                    select(GraphEdge).where(
                        GraphEdge.source_node_id == source.id,
                        GraphEdge.target_node_id == target.id,
                        GraphEdge.relation == relation,
                    )
                )
            ).scalar_one()
        return edge

    async def delete_nodes(self, keys: Sequence[str]) -> int:
        """Delete this user's nodes by key (their edges cascade)."""
        if not keys:
            return 0
        p = self._principal
        nodes = (
            await self._session.execute(
                select(GraphNode).where(
                    GraphNode.graph_type == GraphType.USER,
                    GraphNode.user_id == p.user_id,
                    GraphNode.key.in_(list(keys)),
                )
            )
        ).scalars()
        count = 0
        for node in nodes:
            await self._session.delete(node)
            count += 1
        await self._session.flush()
        return count


# Backwards-compatible name used by earlier workstreams.
TwinGraphRepository = UserGraphRepository


def faith_consent_of(preferences: dict[str, Any]) -> ConsentStatus:
    return ConsentStatus(preferences.get("faith_personalization", ConsentStatus.NOT_ASKED.value))
