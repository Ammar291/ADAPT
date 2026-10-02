"""Consequential actions and their human approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.common import ApiModel
from app.domain.enums import ActionKind, ActionStatus, ApprovalStatus, ConfirmationSource


class ActionApprovalOut(ApiModel):
    id: UUID
    action_id: UUID
    run_id: UUID | None = None
    status: ApprovalStatus
    note: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime | None = None


class ActionOut(ApiModel):
    """What the approval sheet shows: exactly what would happen, before it happens."""

    id: UUID
    type: ActionKind
    status: ActionStatus
    adapter: str
    title: str
    summary: str
    consequences: list[str]
    task_key: str | None = None
    service_key: str | None = None
    journey_id: UUID | None = None
    journey_node_id: UUID | None = None
    run_id: UUID | None = None
    reversible: bool
    requires_human_approval: bool
    requires_user_authentication: bool = Field(
        description="The official service needs the user's own login (e.g. UAE PASS)"
    )
    official_url: str | None = None
    payload: dict[str, Any] = Field(description="Exactly what will be sent or prefilled")
    is_simulated: bool
    simulation_label: str | None = Field(
        default=None, description="Shown on every simulated (demo) action, e.g. 'DEMO / SIMULATED'"
    )
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    confirmation_source: ConfirmationSource | None = None
    external_reference: str | None = Field(
        default=None, description="Only present when the external system returned one"
    )
    approval: ActionApprovalOut | None = None
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None = None

    @model_validator(mode="after")
    def _external_status(self) -> ActionOut:
        if self.status in {ActionStatus.SUBMITTED, ActionStatus.COMPLETED} and (
            self.is_simulated
            or self.confirmation_source is not ConfirmationSource.ADAPTER
            or not (self.external_reference and self.external_reference.strip())
        ):
            raise ValueError("External status requires a real adapter confirmation")
        return self


class ActionDecisionRequest(ApiModel):
    note: str | None = Field(default=None, max_length=1000)
