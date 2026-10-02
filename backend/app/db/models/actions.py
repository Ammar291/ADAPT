"""Consequential actions, their human approvals, generated documents and appointments.

The honesty rules are enforced here as well as in code: CHECK constraints make it
impossible to store a completed action without an external reference, a simulated
submission, or a handoff to a non-https link, and a trigger (see migration 0002) requires
the linked approval to actually be `approved` before an action can move past approval.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Owned, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import (
    ActionKind,
    ActionStatus,
    AppointmentStatus,
    ApprovalStatus,
    ConfirmationSource,
    GeneratedDocumentKind,
    GeneratedDocumentStatus,
)


class Action(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "actions"
    __table_args__ = (
        enum_check("type", ActionKind),
        enum_check("status", ActionStatus),
        CheckConstraint(
            "confirmation_source IS NULL OR confirmation_source IN ('adapter', 'user_reported')",
            name="confirmation_source_valid",
        ),
        CheckConstraint(
            "status <> 'completed' OR (coalesce(length(trim(external_reference)), 0) > 0 "
            "AND coalesce(confirmation_source, '') = 'adapter' AND NOT is_simulated)",
            name="completed_requires_reference",
        ),
        CheckConstraint(
            "status NOT IN ('submitted', 'completed') OR (approval_id IS NOT NULL AND "
            "NOT is_simulated AND coalesce(confirmation_source, '') = 'adapter' AND "
            "coalesce(length(trim(external_reference)), 0) > 0)",
            name="submission_requires_approval_and_real_adapter",
        ),
        CheckConstraint(
            "status <> 'approved' OR approval_id IS NOT NULL", name="approved_requires_approval"
        ),
        CheckConstraint(
            "status <> 'handoff_required' OR "
            "coalesce(starts_with(official_url, 'https://'), false)",
            name="handoff_requires_https_url",
        ),
        Index("ix_actions_user_status", "user_id", "status"),
    )

    journey_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journeys.id", ondelete="CASCADE"), index=True
    )
    journey_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journey_nodes.id", ondelete="SET NULL")
    )
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    task_key: Mapped[str | None] = mapped_column(String(160))
    service_key: Mapped[str | None] = mapped_column(
        String(200), doc="Governance graph key of the target service"
    )
    type: Mapped[ActionKind] = mapped_column(str_enum(ActionKind), nullable=False)
    status: Mapped[ActionStatus] = mapped_column(
        str_enum(ActionStatus), nullable=False, server_default=ActionStatus.PREPARED.value
    )
    adapter: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    consequences: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    requires_user_authentication: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    official_url: Mapped[str | None] = mapped_column(String(2048))
    # Exactly what would be sent or prefilled — shown to the user before approval.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    response_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmation_source: Mapped[ConfirmationSource | None] = mapped_column(
        str_enum(ConfirmationSource, 20)
    )
    external_reference: Mapped[str | None] = mapped_column(String(200))
    # The approval that authorised execution (see action_approvals.action_id for the reverse).
    approval_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "action_approvals.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_actions_approval_id_action_approvals",
        )
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionApproval(Base, UUIDPrimaryKey, Timestamps, Owned):
    """The user's decision on one action. Only a human decision moves it out of `pending`."""

    __tablename__ = "action_approvals"
    __table_args__ = (
        enum_check("status", ApprovalStatus),
        UniqueConstraint("action_id", name="uq_action_approvals_action_id"),
        CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)", name="decided_at_matches_status"
        ),
    )

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("actions.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    review_id: Mapped[str | None] = mapped_column(
        String(120), doc="Interrupt/review identifier of the agent gate that asked"
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus), nullable=False, server_default=ApprovalStatus.PENDING.value
    )
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeneratedDocument(Base, UUIDPrimaryKey, Timestamps, Owned):
    """Letters, emails, checklists and briefs drafted for the user. Always reviewed first."""

    __tablename__ = "generated_documents"
    __table_args__ = (
        enum_check("kind", GeneratedDocumentKind),
        enum_check("status", GeneratedDocumentStatus),
        CheckConstraint(
            "(status = 'approved') = (approved_at IS NOT NULL)", name="approved_at_matches_status"
        ),
        Index("ix_generated_documents_user_created", "user_id", "created_at"),
    )

    kind: Mapped[GeneratedDocumentKind] = mapped_column(
        str_enum(GeneratedDocumentKind), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GeneratedDocumentStatus] = mapped_column(
        str_enum(GeneratedDocumentStatus),
        nullable=False,
        server_default=GeneratedDocumentStatus.DRAFT.value,
    )
    journey_id: Mapped[UUID | None] = mapped_column(ForeignKey("journeys.id", ondelete="CASCADE"))
    journey_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journey_nodes.id", ondelete="SET NULL")
    )
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Appointment(Base, UUIDPrimaryKey, Timestamps, Owned):
    """An in-person step (medical screening, biometrics, ...). ADAPT never books one
    without a real integration: `confirmed` requires the external system's reference."""

    __tablename__ = "appointments"
    __table_args__ = (
        enum_check("status", AppointmentStatus),
        CheckConstraint(
            "status NOT IN ('confirmed', 'completed') OR ("
            "coalesce(length(trim(external_reference)), 0) > 0 AND "
            "coalesce(booking_confirmation->>'reference', '') = external_reference AND "
            "coalesce(length(trim(booking_confirmation->>'provider')), 0) > 0 AND "
            "coalesce(length(booking_confirmation->>'confirmed_at'), 0) > 0)",
            name="confirmed_requires_reference",
        ),
        CheckConstraint(
            "official_url IS NULL OR starts_with(official_url, 'https://')", name="https_url"
        ),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    service_key: Mapped[str | None] = mapped_column(String(200))
    governance_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL")
    )
    journey_id: Mapped[UUID | None] = mapped_column(ForeignKey("journeys.id", ondelete="SET NULL"))
    journey_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journey_nodes.id", ondelete="SET NULL")
    )
    authority: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(300))
    official_url: Mapped[str | None] = mapped_column(String(2048))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        str_enum(AppointmentStatus), nullable=False, server_default=AppointmentStatus.PLANNED.value
    )
    external_reference: Mapped[str | None] = mapped_column(String(200))
    action_id: Mapped[UUID | None] = mapped_column(ForeignKey("actions.id", ondelete="SET NULL"))
    booking_confirmation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    preparation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    brief_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
