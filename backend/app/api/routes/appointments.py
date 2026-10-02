"""Appointments and preparation (never booking)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import PrincipalDep, UserSession
from app.contracts.appointments import AppointmentOut
from app.services import appointments as service
from app.services.presenters import appointment_out

router = APIRouter(tags=["appointments"])


@router.get("/appointments", response_model=list[AppointmentOut], summary="Your appointments")
async def list_appointments(principal: PrincipalDep, session: UserSession) -> list[AppointmentOut]:
    return [appointment_out(a) for a in await service.list_appointments(session, principal)]


@router.get(
    "/appointments/{appointment_id}", response_model=AppointmentOut, summary="One appointment"
)
async def read_appointment(
    appointment_id: UUID, principal: PrincipalDep, session: UserSession
) -> AppointmentOut:
    return appointment_out(await service.get_appointment(session, principal, appointment_id))


@router.post(
    "/appointments/{appointment_id}/prepare",
    response_model=AppointmentOut,
    summary="Prepare for an appointment",
    description="Builds a checklist from the service's official requirements and your "
    "documents, and drafts an appointment brief (a generated document) for you to review. "
    "Nothing is booked.",
)
async def prepare_appointment(
    appointment_id: UUID, principal: PrincipalDep, session: UserSession
) -> AppointmentOut:
    appointment = await service.prepare(session, principal, appointment_id)
    await session.commit()
    return appointment_out(appointment)
