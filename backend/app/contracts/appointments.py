"""Appointments (medical screening, biometrics, ...) and how ADAPT prepares the user.

ADAPT never books an appointment without a real integration: `confirmed` always carries
the external system's reference, and preparation is a checklist, not a booking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.common import ApiModel
from app.domain.enums import AppointmentStatus
from app.domain.provenance import Provenance


class PreparationItem(ApiModel):
    key: str
    label: str
    status: Literal["ready", "missing", "check"] = Field(
        description="ready: ADAPT sees it in your documents; missing: not found; "
        "check: ADAPT cannot tell, please confirm"
    )
    note: str | None = None


class AppointmentPreparation(ApiModel):
    items: list[PreparationItem]
    tips: list[str]
    official_url: str | None = None
    provenance: Provenance
    brief_document_id: UUID | None = None
    prepared_at: datetime


class BookingConfirmation(ApiModel):
    """Receipt returned by an external provider, populated only by a server adapter."""

    provider: str = Field(min_length=1, max_length=200)
    reference: str = Field(min_length=1, max_length=200)
    confirmed_at: datetime


class AppointmentOut(ApiModel):
    id: UUID
    title: str
    service_key: str | None = None
    governance_node_id: UUID | None = None
    journey_id: UUID | None = None
    journey_node_id: UUID | None = None
    authority: str | None = None
    location: str | None = None
    official_url: str | None = None
    scheduled_at: datetime | None = None
    status: AppointmentStatus
    external_reference: str | None = None
    booking_confirmation: BookingConfirmation | None = None
    preparation: AppointmentPreparation | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _provider_confirmation(self) -> AppointmentOut:
        if self.status in {AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED}:
            receipt = self.booking_confirmation
            if not receipt or not receipt.provider.strip() or not receipt.reference.strip():
                raise ValueError("A booked appointment needs an external provider confirmation")
            if receipt.reference != self.external_reference:
                raise ValueError("The booking reference must match the provider confirmation")
        return self
