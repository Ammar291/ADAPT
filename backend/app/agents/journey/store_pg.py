"""JourneyStore on PostgreSQL. Every private read and write goes through a
`user_session(principal)`, so row-level security scopes it to the user.

Honesty rules are enforced again here by the database: CHECK constraints on `actions`
and a trigger that only lets an action past approval when its `action_approvals` row is
really `approved`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.agents.journey import persistence
from app.agents.journey.considerations import detect_considerations
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.integrations import load_planning_facts
from app.agents.journey.ports import ApprovalRow
from app.agents.journey.state import ActionRecord, Dependency, GovEdge, GovNode, Task, UserFact
from app.db.models import (
    Action,
    ActionApproval,
    AgentRun,
    GeneratedDocument,
    GraphEdge,
    GraphNode,
    Journey,
    JourneyEdge,
    JourneyNode,
    User,
)
from app.db.session import Database
from app.domain.enums import (
    ActionStatus,
    GraphType,
    JourneyEdgeType,
    JourneyStatus,
)
from app.domain.principal import Principal

_EXECUTED = {ActionStatus.HANDOFF_REQUIRED, ActionStatus.SUBMITTED, ActionStatus.COMPLETED}


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def action_record(row: Action) -> ActionRecord:
    return ActionRecord(
        id=str(row.id),
        type=row.type.value,
        status=row.status.value,
        reversible=row.reversible,
        requires_human_approval=row.requires_human_approval,
        requires_user_authentication=row.requires_user_authentication,
        official_url=row.official_url,
        payload=dict(row.payload or {}),
        evidence=[str(e.get("id")) for e in row.evidence or [] if e.get("id")],
        title=row.title,
        summary=row.summary,
        consequences=list(row.consequences or []),
        task_key=row.task_key or "",
        service_key=row.service_key or "",
        adapter=row.adapter,
        is_simulated=row.is_simulated,
        simulation_label=(row.response_metadata or {}).get("simulation_label"),
        approval_id=str(row.approval_id) if row.approval_id else None,
        external_reference=row.external_reference,
        confirmation_source=row.confirmation_source.value if row.confirmation_source else None,
        response_metadata=dict(row.response_metadata or {}),
    )


class PgJourneyStore:
    def __init__(self, db: Database, principal: Principal) -> None:
        self._db = db
        self._principal = principal
        self._governance: GovernanceSnapshot | None = None
        self._governance_ids: dict[str, UUID] = {}

    # --- reads -------------------------------------------------------------------------
    async def governance(self) -> GovernanceSnapshot:
        if self._governance is None:
            async with self._db.public_session() as session:
                nodes = list(
                    (
                        await session.execute(
                            select(GraphNode).where(GraphNode.graph_type == GraphType.GOVERNANCE)
                        )
                    ).scalars()
                )
                edges = list(
                    (
                        await session.execute(
                            select(GraphEdge).where(GraphEdge.graph_type == GraphType.GOVERNANCE)
                        )
                    ).scalars()
                )
            keys = {n.id: n.key for n in nodes}
            self._governance_ids = {n.key: n.id for n in nodes}
            self._governance = GovernanceSnapshot.of(
                [
                    GovNode(
                        key=n.key,
                        type=n.entity_type,
                        label=n.label,
                        summary=n.summary,
                        official_url=n.official_url,
                        properties=dict(n.properties_json or {}),
                        provenance=n.provenance,
                    )
                    for n in nodes
                ],
                [
                    GovEdge(
                        source=keys[e.source_node_id],
                        relation=e.relation.value,
                        target=keys[e.target_node_id],
                        properties=dict(e.properties_json or {}),
                    )
                    for e in edges
                    if e.source_node_id in keys and e.target_node_id in keys
                ],
            )
        return self._governance

    async def user_facts(self) -> list[UserFact]:
        return await load_planning_facts(self._db, self._principal)

    async def preferences(self) -> dict[str, Any]:
        async with self._db.user_session(self._principal) as session:
            user = await session.get(User, self._principal.user_id)
            return dict(user.preferences or {}) if user else {}

    async def load_actions(self, action_ids: list[str]) -> dict[str, ActionRecord]:
        if not action_ids:
            return {}
        async with self._db.user_session(self._principal) as session:
            rows = (
                await session.execute(
                    select(Action).where(Action.id.in_([UUID(i) for i in action_ids]))
                )
            ).scalars()
            return {str(r.id): action_record(r) for r in rows}

    async def approvals(self, action_ids: list[str]) -> dict[str, ApprovalRow]:
        if not action_ids:
            return {}
        async with self._db.user_session(self._principal) as session:
            rows = (
                await session.execute(
                    select(ActionApproval).where(
                        ActionApproval.action_id.in_([UUID(i) for i in action_ids])
                    )
                )
            ).scalars()
            return {
                str(r.action_id): ApprovalRow(
                    id=str(r.id),
                    action_id=str(r.action_id),
                    status=r.status.value,
                    decided_at=r.decided_at.isoformat() if r.decided_at else None,
                    note=r.note,
                    expires_at=r.expires_at.isoformat() if r.expires_at else None,
                )
                for r in rows
            }

    # --- writes ------------------------------------------------------------------------
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
    ) -> str:
        async with self._db.user_session(self._principal) as session:
            doc = GeneratedDocument(
                tenant_id=self._principal.tenant_id,
                user_id=self._principal.user_id,
                kind=kind,
                title=title[:300],
                body_markdown=body_markdown,
                journey_id=UUID(journey_id),
                run_id=UUID(run_id),
                provenance=provenance,
                details={"task_key": task_key, "source": "journey_agent"},
            )
            session.add(doc)
            await session.commit()
            return str(doc.id)

    async def save_actions(
        self, *, journey_id: str, run_id: str, actions: list[ActionRecord]
    ) -> None:
        now = datetime.now(UTC)
        async with self._db.user_session(self._principal) as session:
            for action in actions:
                status = ActionStatus(action["status"])
                values: dict[str, Any] = {
                    "tenant_id": self._principal.tenant_id,
                    "user_id": self._principal.user_id,
                    "journey_id": _uuid(journey_id),
                    "run_id": _uuid(run_id),
                    "task_key": action["task_key"] or None,
                    "service_key": action["service_key"] or None,
                    "type": action["type"],
                    "status": status.value,
                    "adapter": action["adapter"],
                    "title": action["title"][:300],
                    "summary": action["summary"],
                    "consequences": action["consequences"],
                    "reversible": action["reversible"],
                    "requires_human_approval": action["requires_human_approval"],
                    "requires_user_authentication": action["requires_user_authentication"],
                    "official_url": action["official_url"],
                    "payload": action["payload"],
                    "evidence": [{"id": e} for e in action["evidence"]],
                    "response_metadata": {
                        **action["response_metadata"],
                        "simulation_label": action["simulation_label"],
                    },
                    "is_simulated": action["is_simulated"],
                    "confirmation_source": action["confirmation_source"],
                    "external_reference": action["external_reference"],
                    "approval_id": _uuid(action["approval_id"]),
                }
                stmt = insert(Action).values(id=UUID(action["id"]), **values)
                changes = {k: v for k, v in values.items() if k not in ("tenant_id", "user_id")}
                if status in _EXECUTED:
                    changes["executed_at"] = now
                stmt = stmt.on_conflict_do_update(index_elements=[Action.id], set_=changes)
                await session.execute(stmt)
            await session.commit()

    async def ensure_approvals(
        self, *, run_id: str, review_id: str, action_ids: list[str]
    ) -> dict[str, tuple[str, bool]]:
        async with self._db.user_session(self._principal) as session:
            created: set[str] = set()
            for action_id in action_ids:
                row = (
                    await session.execute(
                        insert(ActionApproval)
                        .values(
                            tenant_id=self._principal.tenant_id,
                            user_id=self._principal.user_id,
                            action_id=UUID(action_id),
                            run_id=UUID(run_id),
                            review_id=review_id,
                        )
                        .on_conflict_do_nothing(constraint="uq_action_approvals_action_id")
                        .returning(ActionApproval.action_id)
                    )
                ).scalar_one_or_none()
                if row is not None:
                    created.add(action_id)
            rows = (
                await session.execute(
                    select(ActionApproval.action_id, ActionApproval.id).where(
                        ActionApproval.action_id.in_([UUID(i) for i in action_ids])
                    )
                )
            ).all()
            await session.commit()
        return {str(a): (str(i), str(a) in created) for a, i in rows}

    async def set_pending_review(self, *, run_id: str, review: dict[str, Any] | None) -> None:
        async with self._db.user_session(self._principal) as session:
            await session.execute(
                update(AgentRun).where(AgentRun.id == UUID(run_id)).values(pending_review=review)
            )
            await session.commit()

    async def save_plan(
        self,
        *,
        journey_id: str,
        plan: dict[str, Any],
        tasks: list[Task],
        dependencies: list[Dependency],
        status: str,
        summary: str | None,
        simulation: dict[str, Any] | None = None,
    ) -> None:
        """Replace the journey's plan: journey row, nodes (upserted by key) and edges."""
        snapshot = await self.governance()
        journey = UUID(journey_id)
        rows = persistence.node_rows(plan, snapshot.nodes)  # type: ignore[arg-type]
        async with self._db.user_session(self._principal) as session:
            values: dict[str, Any] = {
                "status": JourneyStatus(status).value,
                "goals": plan.get("goals", []),
                "assumptions": persistence.assumptions(plan),
                "considerations": detect_considerations(plan, snapshot.nodes),
                "plan": plan,
            }
            if summary is not None:
                values["summary"] = summary
            if simulation is not None:
                values["simulation"] = simulation
            await session.execute(update(Journey).where(Journey.id == journey).values(**values))

            ids: dict[str, UUID] = {}
            for row in rows:
                data = {
                    "kind": row["kind"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "category": row["category"].value,
                    "status": row["status"].value,
                    "position": row["position"],
                    "governance_node_id": self._governance_ids.get(row["governance_key"]),
                    "authority": row["authority"],
                    "official_url": row["official_url"],
                    "blockers": row["blockers"],
                    "provenance": row["provenance"],
                    "basis": row["basis"],
                    "details": row["details"],
                }
                upsert = (
                    insert(JourneyNode)
                    .values(
                        tenant_id=self._principal.tenant_id,
                        user_id=self._principal.user_id,
                        journey_id=journey,
                        key=row["key"],
                        **data,
                    )
                    .on_conflict_do_update(constraint="uq_journey_nodes_journey_key", set_=data)
                    .returning(JourneyNode.id)
                )
                ids[row["key"]] = (await session.execute(upsert)).scalar_one()
            await session.execute(
                delete(JourneyNode).where(
                    JourneyNode.journey_id == journey, JourneyNode.key.not_in(list(ids) or [""])
                )
            )
            await session.execute(delete(JourneyEdge).where(JourneyEdge.journey_id == journey))
            for edge in persistence.edge_rows(plan):
                if edge["source"] in ids and edge["target"] in ids:
                    session.add(
                        JourneyEdge(
                            tenant_id=self._principal.tenant_id,
                            user_id=self._principal.user_id,
                            journey_id=journey,
                            source_node_id=ids[edge["source"]],
                            target_node_id=ids[edge["target"]],
                            relation=JourneyEdgeType.DEPENDS_ON,
                            properties_json=edge["properties"],
                        )
                    )
            for key, node_id in ids.items():
                await session.execute(
                    update(Action)
                    .where(Action.journey_id == journey, Action.task_key == key)
                    .values(journey_node_id=node_id)
                )
                await session.execute(
                    update(GeneratedDocument)
                    .where(
                        GeneratedDocument.journey_id == journey,
                        GeneratedDocument.details["task_key"].astext == key,
                    )
                    .values(journey_node_id=node_id)
                )
            await session.commit()
