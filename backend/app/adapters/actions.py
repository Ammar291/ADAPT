"""Action adapters: the only code allowed to touch external government services.

Contract:
* `prepare()` has no side effects. It describes what would happen so the user can
  review and approve it.
* `execute()` requires an `ApprovalGrant` for this exact action whenever the prepared
  action `requires_approval`. Opening an official page (`official_handoff`) needs none;
  portal applications, appointments and document submissions always do.
* Outcomes are `ActionOutcome`s, whose validators forbid reporting a submission or
  completion without a real external reference, and from any simulated adapter.

ADAPT has no authenticated integration with Abu Dhabi government systems, so the real
("live") adapters resolve every action to an OFFICIAL HANDOFF. ADAPT prepares
everything, and the user completes the step on the official channel, signing in there
(UAE PASS) and never through ADAPT. The demo adapters return deterministic previews
labelled "DEMO / SIMULATED", for example an example appointment slot. They never book or
submit anything.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from app.core.errors import ApprovalRequired, BadRequest
from app.domain.actions import (
    CONSEQUENTIAL_KINDS,
    REVERSIBLE_KINDS,
    SIMULATION_LABEL,
    ActionOutcome,
    ActionRequest,
    ApprovalGrant,
    PreparedAction,
)
from app.domain.enums import ActionKind, ActionStatus
from app.domain.provenance import is_official_source

ActionsMode = Literal["live", "demo"]


def _official_url(request: ActionRequest) -> str:
    url = str(request.parameters.get("official_url") or "")
    if not is_official_source(url):
        raise BadRequest(
            "This service has no verified official link yet", code="no_official_channel"
        )
    return url


def _channel(request: ActionRequest) -> str:
    return str(request.parameters.get("channel_name") or "the official service portal")


def _login_consequence(needs_login: bool) -> list[str]:
    if not needs_login:
        return []
    return ["You sign in there with UAE PASS. ADAPT never sees or stores your credentials."]


class ActionAdapter(ABC):
    name: str
    kinds: frozenset[ActionKind]
    is_simulated: bool = False

    @abstractmethod
    async def prepare(self, request: ActionRequest) -> PreparedAction: ...

    async def execute(
        self, prepared: PreparedAction, grant: ApprovalGrant | None = None
    ) -> ActionOutcome:
        if prepared.requires_approval:
            if grant is None:
                raise ApprovalRequired(f"'{prepared.request.title}' needs your approval first")
            try:
                ApprovalGrant.model_validate(grant.model_dump())
            except ValueError as exc:
                raise ApprovalRequired("The action needs a current approval") from exc
            if prepared.request.action_id and grant.action_id != prepared.request.action_id:
                raise ApprovalRequired("That approval was given for a different action")
        return await self._execute(prepared, grant)

    @abstractmethod
    async def _execute(
        self, prepared: PreparedAction, grant: ApprovalGrant | None
    ) -> ActionOutcome: ...

    def _handoff(self, prepared: PreparedAction, message: str, **metadata: Any) -> ActionOutcome:
        assert prepared.official_url is not None
        return ActionOutcome(
            status=ActionStatus.HANDOFF_REQUIRED,
            adapter=self.name,
            message=message,
            official_url=prepared.official_url,
            is_simulated=self.is_simulated,
            simulation_label=SIMULATION_LABEL if self.is_simulated else None,
            response_metadata={"simulated": self.is_simulated, **metadata},
        )


class OfficialHandoffAdapter(ActionAdapter):
    """Opens the official page for a step. Informational: needs no approval."""

    name = "official_handoff"
    kinds = frozenset({ActionKind.OFFICIAL_HANDOFF})

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        url = _official_url(request)
        needs_login = bool(request.parameters.get("requires_uae_pass", False))
        return PreparedAction(
            request=request,
            adapter=self.name,
            summary=f"Open the official page for '{request.title}'",
            consequences=[
                f"Opens {_channel(request)} in a new tab. Nothing is submitted by ADAPT.",
                *_login_consequence(needs_login),
            ],
            requires_approval=request.kind in CONSEQUENTIAL_KINDS,
            requires_user_authentication=needs_login,
            reversible=True,
            official_url=url,
        )

    async def _execute(
        self, prepared: PreparedAction, grant: ApprovalGrant | None
    ) -> ActionOutcome:
        return self._handoff(prepared, "Ready on the official site.")


class GovernmentPortalAdapter(ActionAdapter):
    """An application on an official portal (TAMM, ICP). ADAPT prepares a checklist and
    what to enter; the user applies there with their own login. Always a real handoff."""

    name = "government_portal"
    kinds = frozenset({ActionKind.GOVERNMENT_PORTAL})

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        url = _official_url(request)
        needs_login = bool(request.parameters.get("requires_uae_pass", False))
        have_ready = [str(d) for d in request.payload.get("documents", [])]
        consequences = [
            f"Opens {_channel(request)} to apply for '{request.title}'. "
            "ADAPT does not submit the application for you.",
            *_login_consequence(needs_login),
            "Government applications usually can't be withdrawn once you submit them.",
        ]
        if have_ready:
            consequences.append(f"Have these ready: {', '.join(have_ready)}.")
        return PreparedAction(
            request=request,
            adapter=self.name,
            summary=f"Apply for '{request.title}' on {_channel(request)}",
            consequences=consequences,
            requires_approval=True,
            requires_user_authentication=needs_login,
            reversible=ActionKind.GOVERNMENT_PORTAL in REVERSIBLE_KINDS,
            official_url=url,
        )

    async def _execute(
        self, prepared: PreparedAction, grant: ApprovalGrant | None
    ) -> ActionOutcome:
        return self._handoff(
            prepared, "Continue on the official portal. Tell ADAPT when you've submitted it."
        )


def _stable_int(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def demo_slots(service_key: str, after: date, count: int = 3) -> list[dict[str, str]]:
    """Deterministic example slots on UAE working days (Mon-Fri). Illustrative only."""
    seed = _stable_int(service_key, after.isoformat())
    day = after + timedelta(days=2 + seed % 3)
    slots: list[dict[str, str]] = []
    while len(slots) < count:
        if day.weekday() < 5:
            start = time(8 + (seed + len(slots) * 3) % 7, 30 if (seed >> len(slots)) & 1 else 0)
            slots.append(
                {
                    "starts_at": datetime.combine(day, start, tzinfo=UTC).isoformat(),
                    "label": f"{day:%a %d %b} {start:%H:%M} (example)",
                }
            )
        day += timedelta(days=1)
    return slots


class AppointmentAdapter(ActionAdapter):
    """Appointments (medical screening, biometrics).

    Live: a handoff to the official booking channel. Demo: the same handoff plus
    deterministic example slots, labelled DEMO / SIMULATED. Nothing is ever booked.
    """

    kinds = frozenset({ActionKind.APPOINTMENT})

    def __init__(self, *, simulated: bool) -> None:
        self.is_simulated = simulated
        self.name = "appointment_demo" if simulated else "appointment"

    def _after(self, request: ActionRequest) -> date:
        raw = request.parameters.get("preferred_after")
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                pass
        return datetime.now(UTC).date()

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        url = _official_url(request)
        needs_login = bool(request.parameters.get("requires_uae_pass", False))
        demo = None
        consequences = [
            f"Opens {_channel(request)} to book '{request.title}'. ADAPT does not book it for you.",
            *_login_consequence(needs_login),
            "Appointments can usually be moved or cancelled on the same channel.",
        ]
        if self.is_simulated:
            slots = demo_slots(request.service_key, self._after(request))
            demo = {"label": SIMULATION_LABEL, "example_slots": slots, "booked": False}
            consequences.insert(
                0, f"{SIMULATION_LABEL}: the times shown are examples, not real availability."
            )
        return PreparedAction(
            request=request,
            adapter=self.name,
            summary=f"Book '{request.title}'",
            consequences=consequences,
            requires_approval=True,
            requires_user_authentication=needs_login,
            reversible=True,
            official_url=url,
            is_simulated=self.is_simulated,
            simulation_label=SIMULATION_LABEL if self.is_simulated else None,
            demo_response=demo,
        )

    async def _execute(
        self, prepared: PreparedAction, grant: ApprovalGrant | None
    ) -> ActionOutcome:
        if self.is_simulated:
            slot = (prepared.demo_response or {}).get("example_slots", [{}])[0]
            return self._handoff(
                prepared,
                f"{SIMULATION_LABEL}: example slot {slot.get('label', '')} shown; nothing was "
                "booked. Book on the official channel.",
                demo_slot=slot,
                booked=False,
            )
        return self._handoff(
            prepared, "Book on the official channel, then tell ADAPT the reference."
        )


class DocumentSubmissionAdapter(ActionAdapter):
    """Submitting documents (e.g. for attestation).

    Live: a handoff to the official submission channel. Demo: the same handoff plus a
    deterministic completeness check of what would be submitted, labelled DEMO / SIMULATED.
    """

    kinds = frozenset({ActionKind.DOCUMENT_SUBMISSION})

    def __init__(self, *, simulated: bool) -> None:
        self.is_simulated = simulated
        self.name = "document_submission_demo" if simulated else "document_submission"

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        url = _official_url(request)
        needs_login = bool(request.parameters.get("requires_uae_pass", False))
        documents = [str(d) for d in request.payload.get("documents", [])]
        missing = [str(d) for d in request.payload.get("missing_documents", [])]
        consequences = [
            f"Opens {_channel(request)} to submit documents for '{request.title}'. "
            "ADAPT does not send them for you.",
            *_login_consequence(needs_login),
            "A submitted application usually can't be withdrawn.",
        ]
        if missing:
            consequences.append(f"Still missing: {', '.join(missing)}.")
        demo = None
        if self.is_simulated:
            demo = {
                "label": SIMULATION_LABEL,
                "checks": [{"document": d, "status": "ready"} for d in documents]
                + [{"document": d, "status": "missing"} for d in missing],
                "submitted": False,
            }
            consequences.insert(0, f"{SIMULATION_LABEL}: completeness check only.")
        return PreparedAction(
            request=request,
            adapter=self.name,
            summary=f"Submit documents for '{request.title}'",
            consequences=consequences,
            requires_approval=True,
            requires_user_authentication=needs_login,
            reversible=False,
            official_url=url,
            is_simulated=self.is_simulated,
            simulation_label=SIMULATION_LABEL if self.is_simulated else None,
            demo_response=demo,
        )

    async def _execute(
        self, prepared: PreparedAction, grant: ApprovalGrant | None
    ) -> ActionOutcome:
        if self.is_simulated:
            return self._handoff(
                prepared,
                f"{SIMULATION_LABEL}: documents checked for completeness; nothing was "
                "submitted. Submit them on the official channel.",
                checks=(prepared.demo_response or {}).get("checks", []),
                submitted=False,
            )
        return self._handoff(
            prepared, "Submit on the official channel, then tell ADAPT the reference."
        )


class ActionAdapterRegistry:
    """Chooses the adapter for an action type. Unknown types fall back to a handoff."""

    def __init__(self, adapters: list[ActionAdapter], fallback: ActionAdapter) -> None:
        self._fallback = fallback
        self._by_kind: dict[ActionKind, ActionAdapter] = {}
        for adapter in adapters:
            for kind in adapter.kinds:
                self._by_kind.setdefault(kind, adapter)

    def resolve(self, kind: ActionKind) -> ActionAdapter:
        return self._by_kind.get(kind, self._fallback)

    @property
    def names(self) -> list[str]:
        return sorted({a.name for a in self._by_kind.values()} | {self._fallback.name})

    @property
    def mode(self) -> ActionsMode:
        return "demo" if any(a.is_simulated for a in self._by_kind.values()) else "live"


def build_action_registry(mode: ActionsMode) -> ActionAdapterRegistry:
    simulated = mode == "demo"
    handoff = OfficialHandoffAdapter()
    return ActionAdapterRegistry(
        adapters=[
            GovernmentPortalAdapter(),
            AppointmentAdapter(simulated=simulated),
            DocumentSubmissionAdapter(simulated=simulated),
            handoff,
        ],
        fallback=handoff,
    )


def resolve_actions_mode(setting: str | None, *, production: bool) -> ActionsMode:
    """`ADAPTER_ACTIONS` = auto | live | demo. Auto means demo previews in development and
    real handoffs in production. Demo previews are refused in production."""
    value = (setting or "auto").lower()
    if value == "demo":
        if production:
            raise ValueError("ADAPTER_ACTIONS=demo is not allowed in production")
        return "demo"
    if value == "live":
        return "live"
    return "live" if production else "demo"
