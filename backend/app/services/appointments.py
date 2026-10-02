"""Appointments and appointment preparation.

`prepare` builds a checklist from the governance graph (what the service requires) and
the user's own graph (which of those documents the user holds), then drafts an
appointment brief for the user to review. It never books anything: an appointment only
becomes `confirmed` with a reference from a real booking integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.appointments import AppointmentPreparation, PreparationItem
from app.core.errors import Conflict, NotFound
from app.db.models import Appointment, GeneratedDocument, GraphEdge, GraphNode
from app.domain.enums import (
    AppointmentStatus,
    GeneratedDocumentKind,
    GeneratedDocumentStatus,
    GovernanceNodeType,
    GraphEdgeType,
    GraphType,
)
from app.domain.principal import Principal
from app.domain.provenance import Provenance
from app.repositories.graph import GovernanceGraphRepository, UserGraphRepository

GENERAL_TIPS: tuple[str, ...] = (
    "Bring the original documents and a copy of each.",
    "Check the official page for the latest requirements, opening hours and fees before you go.",
    "If the service needs UAE PASS, sign in on the official channel yourself; ADAPT never asks "
    "for your credentials.",
)


async def list_appointments(session: AsyncSession, principal: Principal) -> list[Appointment]:
    return list(
        (
            await session.execute(
                select(Appointment)
                .where(Appointment.user_id == principal.user_id)
                .order_by(Appointment.scheduled_at.asc().nulls_last(), Appointment.created_at)
            )
        ).scalars()
    )


async def get_appointment(
    session: AsyncSession, principal: Principal, appointment_id: UUID
) -> Appointment:
    row = (
        await session.execute(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.user_id == principal.user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Appointment not found", code="appointment_not_found")
    return row


async def _service_nodes(session: AsyncSession, appointment: Appointment) -> list[GraphNode]:
    """The governance service(s) whose requirements apply to this appointment."""
    governance = GovernanceGraphRepository(session)
    node = None
    if appointment.governance_node_id is not None:
        found = await governance.by_ids([appointment.governance_node_id])
        node = found[0] if found else None
    if node is None and appointment.service_key:
        node = (await governance.by_keys([appointment.service_key])).get(appointment.service_key)
    if node is None:
        return []
    if node.entity_type == GovernanceNodeType.APPOINTMENT.value:
        # An appointment node: the services that may require it carry the requirements.
        rows = await session.execute(
            select(GraphNode)
            .join(GraphEdge, GraphEdge.source_node_id == GraphNode.id)
            .where(
                GraphEdge.graph_type == GraphType.GOVERNANCE,
                GraphEdge.relation == GraphEdgeType.MAY_REQUIRE,
                GraphEdge.target_node_id == node.id,
            )
        )
        return [node, *rows.scalars()]
    return [node]


async def _requirements(session: AsyncSession, services: list[GraphNode]) -> list[GraphNode]:
    if not services:
        return []
    rows = await session.execute(
        select(GraphNode)
        .join(GraphEdge, GraphEdge.target_node_id == GraphNode.id)
        .where(
            GraphEdge.graph_type == GraphType.GOVERNANCE,
            GraphEdge.relation == GraphEdgeType.REQUIRES,
            GraphEdge.source_node_id.in_([s.id for s in services]),
            or_(GraphNode.valid_to.is_(None), GraphNode.valid_to >= datetime.now(UTC).date()),
        )
        .order_by(GraphNode.entity_type, GraphNode.label)
    )
    unique: dict[UUID, GraphNode] = {}
    for node in rows.scalars():
        unique.setdefault(node.id, node)
    return list(unique.values())


async def _held_document_types(session: AsyncSession) -> set[UUID]:
    """Governance document types the user holds: user-graph `instance_of` link targets."""
    _, _, edges = await UserGraphRepository(session).graph()
    return {e.target_node_id for e in edges if e.relation == GraphEdgeType.INSTANCE_OF}


def _brief_markdown(appointment: Appointment, preparation: AppointmentPreparation) -> str:
    marks = {"ready": "[x]", "missing": "[ ]", "check": "[?]"}
    lines = [f"# Preparing for: {appointment.title}", ""]
    if appointment.authority:
        lines.append(f"Authority: {appointment.authority}")
    if appointment.location:
        lines.append(f"Where: {appointment.location}")
    if preparation.official_url:
        lines.append(f"Official page: {preparation.official_url}")
    lines += ["", "## Bring with you", ""]
    for item in preparation.items:
        note = f" — {item.note}" if item.note else ""
        lines.append(f"- {marks[item.status]} {item.label}{note}")
    if not preparation.items:
        lines.append(
            "- ADAPT has no requirement list for this service yet; check the official page."
        )
    lines += ["", "## Tips", ""] + [f"- {tip}" for tip in preparation.tips]
    lines += [
        "",
        "_Prepared by ADAPT from official guidance and your documents. "
        "Confirm current requirements on the official page._",
    ]
    return "\n".join(lines)


async def prepare(session: AsyncSession, principal: Principal, appointment_id: UUID) -> Appointment:
    appointment = await get_appointment(session, principal, appointment_id)
    if appointment.status in (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED):
        raise Conflict("This appointment is no longer upcoming", code="appointment_not_upcoming")
    services = await _service_nodes(session, appointment)
    requirements = await _requirements(session, services)
    held = await _held_document_types(session)

    items: list[PreparationItem] = []
    for req in requirements:
        if req.entity_type == GovernanceNodeType.DOCUMENT.value:
            have = req.id in held
            items.append(
                PreparationItem(
                    key=req.key,
                    label=req.label,
                    status="ready" if have else "missing",
                    note=None if have else "Not found in your documents yet",
                )
            )
        else:
            items.append(
                PreparationItem(key=req.key, label=req.label, status="check", note=req.summary)
            )

    primary = services[0] if services else None
    provenance = (
        Provenance.model_validate(primary.provenance)
        if primary is not None and primary.provenance
        else Provenance.ai("Prepared by ADAPT; no official requirement list is linked yet.")
    )
    official_url = appointment.official_url or (primary.official_url if primary else None)
    now = datetime.now(UTC)
    preparation = AppointmentPreparation(
        items=items,
        tips=list(GENERAL_TIPS),
        official_url=official_url,
        provenance=provenance,
        brief_document_id=appointment.brief_document_id,
        prepared_at=now,
    )

    body = _brief_markdown(appointment, preparation)
    brief = None
    if appointment.brief_document_id is not None:
        brief = await session.get(GeneratedDocument, appointment.brief_document_id)
    if brief is None or brief.status is not GeneratedDocumentStatus.DRAFT:
        brief = GeneratedDocument(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            kind=GeneratedDocumentKind.APPOINTMENT_BRIEF,
            title=f"Appointment brief: {appointment.title}",
            body_markdown=body,
            journey_id=None,
            journey_node_id=appointment.journey_node_id,
            provenance=provenance.model_dump(mode="json"),
            details={"appointment_id": str(appointment.id)},
        )
        session.add(brief)
        await session.flush()
    else:
        brief.body_markdown = body
        brief.provenance = provenance.model_dump(mode="json")

    preparation.brief_document_id = brief.id
    appointment.preparation = preparation.model_dump(mode="json")
    appointment.prepared_at = now
    appointment.brief_document_id = brief.id
    await session.flush()
    await session.refresh(appointment)
    return appointment
