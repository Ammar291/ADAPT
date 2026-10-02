"""Consequential-action invariants and the action state machine.

These types make the product's honesty rules impossible to break by accident:

* Only a real adapter can report SUBMITTED or COMPLETED. User reports are kept as
  unverified notes on an official handoff, even if a reference is supplied.
* COMPLETED always carries an external reference.
* HANDOFF_REQUIRED always points at an official government https URL.
* Executing an action that needs approval requires an `ApprovalGrant`. A grant can only
  be minted from an approved decision, and it is bound to one action.

The same rules are enforced again by CHECK constraints and a trigger on `actions`.

Lifecycle (ActionStatus):

    draft -> prepared -> awaiting_approval -> approved -> handoff_required -> submitted -> completed
                 |                |                          (provider confirms)
                 |                +-> draft (rejected: back to draft, nothing happened)
                 +-> handoff_required (no approval needed: opening an official page)
    any open state -> blocked | failed
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ActionKind, ActionStatus, ApprovalStatus
from app.domain.provenance import is_official_source

SIMULATION_LABEL = "DEMO / SIMULATED"

# Action types whose execution is consequential (applications, bookings, submissions).
# Opening an official page for information needs no approval.
CONSEQUENTIAL_KINDS: frozenset[ActionKind] = frozenset(
    {ActionKind.GOVERNMENT_PORTAL, ActionKind.APPOINTMENT, ActionKind.DOCUMENT_SUBMISSION}
)
REVERSIBLE_KINDS: frozenset[ActionKind] = frozenset(
    {ActionKind.APPOINTMENT, ActionKind.OFFICIAL_HANDOFF}  # a booking can be moved or cancelled
)


class ActionRequest(BaseModel):
    """What the agent wants to do. Never contains credentials (no UAE PASS)."""

    model_config = ConfigDict(frozen=True)

    kind: ActionKind
    service_key: str = Field(description="Governance graph key of the target service")
    title: str
    action_id: str | None = Field(default=None, description="The actions row this is for")
    task_key: str | None = None
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="official_url, channel_name, requires_uae_pass, preferred_after, ...",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Exactly what would be submitted or prefilled"
    )


class PreparedAction(BaseModel):
    """Side-effect-free description of an action, shown to the user for approval."""

    model_config = ConfigDict(frozen=True)

    request: ActionRequest
    adapter: str
    summary: str
    consequences: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    requires_user_authentication: bool = Field(
        default=False,
        description="The official service needs the user's own login (e.g. UAE PASS); "
        "ADAPT then only prepares an official handoff",
    )
    reversible: bool = False
    official_url: str | None = None
    is_simulated: bool = False
    simulation_label: str | None = None
    demo_response: dict[str, Any] | None = Field(
        default=None, description="Deterministic demo preview; never a real booking"
    )

    @model_validator(mode="after")
    def _rules(self) -> PreparedAction:
        if self.request.kind in CONSEQUENTIAL_KINDS and not self.requires_approval:
            raise ValueError(f"{self.request.kind.value} actions always need approval")
        if self.is_simulated and self.simulation_label != SIMULATION_LABEL:
            raise ValueError(f"simulated actions must be labelled {SIMULATION_LABEL!r}")
        if self.official_url is not None and not is_official_source(self.official_url):
            raise ValueError("actions may only link to official government https URLs")
        return self


class ApprovalGrant(BaseModel):
    """Proof that a human approved a specific action. Required by `ActionAdapter.execute`."""

    model_config = ConfigDict(frozen=True)

    approval_id: UUID
    user_id: UUID
    action_id: str
    status: ApprovalStatus
    decided_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _must_be_approved(self) -> ApprovalGrant:
        if self.status is not ApprovalStatus.APPROVED:
            raise ValueError("an ApprovalGrant can only be created from an approved decision")
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None or self.expires_at <= datetime.now(UTC)
        ):
            raise ValueError("the action approval has expired")
        return self


class ActionOutcome(BaseModel):
    """What an adapter's `execute` returns."""

    model_config = ConfigDict(frozen=True)

    status: ActionStatus
    adapter: str
    message: str
    external_reference: str | None = None
    official_url: str | None = None
    is_simulated: bool = False
    simulation_label: str | None = None
    response_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _honesty_rules(self) -> ActionOutcome:
        if self.status not in (
            ActionStatus.HANDOFF_REQUIRED,
            ActionStatus.SUBMITTED,
            ActionStatus.COMPLETED,
            ActionStatus.FAILED,
            ActionStatus.BLOCKED,
        ):
            raise ValueError(f"an adapter cannot report status={self.status.value}")
        if self.status in (ActionStatus.SUBMITTED, ActionStatus.COMPLETED):
            if self.is_simulated:
                raise ValueError(
                    f"a simulated adapter cannot report status={self.status.value}; "
                    "use handoff_required"
                )
            if not (self.external_reference and self.external_reference.strip()):
                raise ValueError("an external action requires the external system's reference")
        if self.status is ActionStatus.HANDOFF_REQUIRED and not (
            self.official_url and is_official_source(self.official_url)
        ):
            raise ValueError("a handoff must point to an official government https URL")
        if self.is_simulated and self.simulation_label != SIMULATION_LABEL:
            raise ValueError(f"simulated outcomes must be labelled {SIMULATION_LABEL!r}")
        return self


class UserConfirmation(BaseModel):
    """The user's own report of an external step they did on the official channel."""

    model_config = ConfigDict(frozen=True)

    outcome: Literal["submitted", "completed", "not_yet", "could_not_complete"]
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reference(self) -> UserConfirmation:
        if self.outcome == "completed" and not (self.reference and self.reference.strip()):
            raise ValueError("confirming a step as completed needs the reference you received")
        return self


# --- state machine ----------------------------------------------------------------------

S = ActionStatus
TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    S.DRAFT: frozenset({S.PREPARED, S.BLOCKED, S.FAILED}),
    S.PREPARED: frozenset({S.AWAITING_APPROVAL, S.HANDOFF_REQUIRED, S.BLOCKED, S.FAILED, S.DRAFT}),
    S.AWAITING_APPROVAL: frozenset({S.APPROVED, S.DRAFT, S.REJECTED, S.CANCELLED}),
    S.APPROVED: frozenset({S.HANDOFF_REQUIRED, S.SUBMITTED, S.COMPLETED, S.FAILED, S.BLOCKED}),
    S.HANDOFF_REQUIRED: frozenset({S.HANDOFF_REQUIRED, S.SUBMITTED, S.COMPLETED, S.FAILED}),
    S.SUBMITTED: frozenset({S.COMPLETED, S.FAILED}),
    S.BLOCKED: frozenset({S.PREPARED, S.DRAFT, S.BLOCKED}),
    S.FAILED: frozenset({S.PREPARED, S.DRAFT}),
    S.REJECTED: frozenset({S.DRAFT}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}

TransitionSource = Literal["agent", "adapter", "user"]


class ActionTransitionError(ValueError):
    pass


def check_transition(
    current: ActionStatus,
    target: ActionStatus,
    *,
    source: TransitionSource,
    requires_approval: bool,
    approved: bool,
    is_simulated: bool,
    external_reference: str | None = None,
    official_url: str | None = None,
) -> None:
    """Raise `ActionTransitionError` unless `current -> target` is legal and honest."""
    if target not in TRANSITIONS[current]:
        raise ActionTransitionError(f"an action cannot go from {current.value} to {target.value}")
    if target is S.APPROVED and (not approved or source != "user"):
        raise ActionTransitionError("only the user's approval can approve an action")
    if target in (S.SUBMITTED, S.COMPLETED):
        if requires_approval and not approved:
            raise ActionTransitionError(f"{target.value} requires the user's approval first")
        if source != "adapter":
            raise ActionTransitionError(
                f"the {source} cannot mark an action {target.value}; only a real adapter can"
            )
        if source == "adapter" and is_simulated:
            raise ActionTransitionError(f"a simulated adapter cannot mark an action {target.value}")
        if not (external_reference and external_reference.strip()):
            raise ActionTransitionError("external status requires an external reference")
    if target is S.HANDOFF_REQUIRED and not (official_url and is_official_source(official_url)):
        raise ActionTransitionError("a handoff must point to an official government https URL")


def confirmation_status(confirmation: UserConfirmation) -> ActionStatus | None:
    """The status a user confirmation moves a handed-off action to (None = unchanged)."""
    return {
        "submitted": S.HANDOFF_REQUIRED,
        "completed": S.HANDOFF_REQUIRED,
        "could_not_complete": S.FAILED,
    }.get(confirmation.outcome)
