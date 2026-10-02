"""Action honesty: statuses, approvals, adapters. Nothing is 'submitted' or 'completed'
because a mock ran."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.adapters.actions import (
    AppointmentAdapter,
    DocumentSubmissionAdapter,
    GovernmentPortalAdapter,
    OfficialHandoffAdapter,
    build_action_registry,
    demo_slots,
    resolve_actions_mode,
)
from app.core.errors import ApprovalRequired, BadRequest
from app.domain.actions import (
    SIMULATION_LABEL,
    ActionOutcome,
    ActionRequest,
    ActionTransitionError,
    ApprovalGrant,
    PreparedAction,
    UserConfirmation,
    check_transition,
    confirmation_status,
)
from app.domain.enums import ActionKind, ActionStatus, ApprovalStatus

S = ActionStatus
NOW = datetime(2026, 10, 1, tzinfo=UTC)
TAMM = "https://www.tamm.abudhabi/services/x"


def request(
    kind: ActionKind, action_id: str = "a1", url: str = TAMM, **payload: object
) -> ActionRequest:
    return ActionRequest(
        kind=kind,
        service_key="service.x",
        title="Do the thing",
        action_id=action_id,
        parameters={
            "official_url": url,
            "channel_name": "TAMM",
            "requires_uae_pass": True,
            "preferred_after": "2026-10-01",
        },
        payload=dict(payload),
    )


def grant(action_id: str = "a1") -> ApprovalGrant:
    return ApprovalGrant(
        approval_id=uuid4(),
        user_id=uuid4(),
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        decided_at=NOW,
    )


class TestOutcomeHonesty:
    @pytest.mark.parametrize("status", [S.SUBMITTED, S.COMPLETED])
    def test_simulated_adapters_cannot_claim_success(self, status: ActionStatus) -> None:
        with pytest.raises(ValidationError, match="simulated"):
            ActionOutcome(
                status=status,
                adapter="demo",
                message="Booked",
                external_reference="R1",
                is_simulated=True,
                simulation_label=SIMULATION_LABEL,
            )

    def test_completed_requires_reference(self) -> None:
        with pytest.raises(ValidationError, match="reference"):
            ActionOutcome(status=S.COMPLETED, adapter="x", message="done")

    def test_handoff_must_be_official(self) -> None:
        with pytest.raises(ValidationError, match="official"):
            ActionOutcome(
                status=S.HANDOFF_REQUIRED,
                adapter="x",
                message="go",
                official_url="https://example.com",
            )

    def test_simulated_outcomes_are_labelled(self) -> None:
        with pytest.raises(ValidationError, match="DEMO / SIMULATED"):
            ActionOutcome(
                status=S.HANDOFF_REQUIRED,
                adapter="x",
                message="go",
                official_url=TAMM,
                is_simulated=True,
            )

    @pytest.mark.parametrize("status", [S.APPROVED, S.DRAFT, S.AWAITING_APPROVAL])
    def test_adapters_cannot_report_decisions(self, status: ActionStatus) -> None:
        with pytest.raises(ValidationError, match="cannot report"):
            ActionOutcome(status=status, adapter="x", message="?")

    def test_grant_only_from_approval(self) -> None:
        with pytest.raises(ValidationError):
            ApprovalGrant(
                approval_id=uuid4(),
                user_id=uuid4(),
                action_id="a1",
                status=ApprovalStatus.REJECTED,
                decided_at=NOW,
            )

    def test_consequential_actions_always_need_approval(self) -> None:
        with pytest.raises(ValidationError, match="need approval"):
            PreparedAction(
                request=request(ActionKind.APPOINTMENT),
                adapter="x",
                summary="s",
                requires_approval=False,
                official_url=TAMM,
            )

    def test_completed_confirmation_needs_reference(self) -> None:
        with pytest.raises(ValidationError, match="reference"):
            UserConfirmation(outcome="completed")
        assert confirmation_status(UserConfirmation(outcome="not_yet")) is None


class TestStateMachine:
    def test_happy_path(self) -> None:
        check_transition(
            S.DRAFT,
            S.PREPARED,
            source="agent",
            requires_approval=True,
            approved=False,
            is_simulated=False,
        )
        check_transition(
            S.PREPARED,
            S.AWAITING_APPROVAL,
            source="agent",
            requires_approval=True,
            approved=False,
            is_simulated=False,
        )
        check_transition(
            S.AWAITING_APPROVAL,
            S.APPROVED,
            source="user",
            requires_approval=True,
            approved=True,
            is_simulated=False,
        )
        check_transition(
            S.APPROVED,
            S.HANDOFF_REQUIRED,
            source="adapter",
            requires_approval=True,
            approved=True,
            is_simulated=True,
            official_url=TAMM,
        )
        check_transition(
            S.HANDOFF_REQUIRED,
            S.SUBMITTED,
            source="adapter",
            requires_approval=True,
            approved=True,
            is_simulated=False,
            external_reference="PROVIDER-1",
        )

    @pytest.mark.parametrize("target", [S.SUBMITTED, S.COMPLETED])
    @pytest.mark.parametrize("simulated", [True, False])
    def test_user_reference_never_proves_external_success(
        self, target: ActionStatus, simulated: bool
    ) -> None:
        with pytest.raises(ActionTransitionError, match="only a real adapter"):
            check_transition(
                S.HANDOFF_REQUIRED,
                target,
                source="user",
                requires_approval=True,
                approved=True,
                is_simulated=simulated,
                external_reference="USER-TYPED-1",
            )

    def test_user_report_is_kept_as_handoff(self) -> None:
        for outcome in ("submitted", "completed"):
            assert (
                confirmation_status(UserConfirmation(outcome=outcome, reference="R1"))
                is S.HANDOFF_REQUIRED
            )

    def test_expired_approval_cannot_be_minted(self) -> None:
        with pytest.raises(ValidationError, match="expired"):
            ApprovalGrant(
                approval_id=uuid4(),
                user_id=uuid4(),
                action_id="a1",
                status=ApprovalStatus.APPROVED,
                decided_at=NOW,
                expires_at=datetime(2000, 1, 1, tzinfo=UTC),
            )

    def test_agent_cannot_mark_submitted(self) -> None:
        with pytest.raises(ActionTransitionError, match="agent cannot"):
            check_transition(
                S.APPROVED,
                S.SUBMITTED,
                source="agent",
                requires_approval=True,
                approved=True,
                is_simulated=False,
            )

    def test_simulated_adapter_cannot_mark_submitted_or_completed(self) -> None:
        for target in (S.SUBMITTED, S.COMPLETED):
            with pytest.raises(ActionTransitionError, match="simulated"):
                check_transition(
                    S.APPROVED,
                    target,
                    source="adapter",
                    requires_approval=True,
                    approved=True,
                    is_simulated=True,
                    external_reference="X",
                )

    def test_no_submission_without_approval(self) -> None:
        with pytest.raises(ActionTransitionError, match="approval"):
            check_transition(
                S.HANDOFF_REQUIRED,
                S.SUBMITTED,
                source="user",
                requires_approval=True,
                approved=False,
                is_simulated=False,
            )
        with pytest.raises(ActionTransitionError, match="only the user's approval"):
            check_transition(
                S.AWAITING_APPROVAL,
                S.APPROVED,
                source="agent",
                requires_approval=True,
                approved=False,
                is_simulated=False,
            )

    def test_illegal_jumps(self) -> None:
        with pytest.raises(ActionTransitionError):
            check_transition(
                S.PREPARED,
                S.COMPLETED,
                source="adapter",
                requires_approval=True,
                approved=True,
                is_simulated=False,
                external_reference="R",
            )
        with pytest.raises(ActionTransitionError):
            check_transition(
                S.COMPLETED,
                S.FAILED,
                source="adapter",
                requires_approval=True,
                approved=True,
                is_simulated=False,
            )

    def test_rejection_goes_back_to_draft(self) -> None:
        check_transition(
            S.AWAITING_APPROVAL,
            S.DRAFT,
            source="user",
            requires_approval=True,
            approved=False,
            is_simulated=False,
        )


class TestAdapters:
    async def test_portal_is_a_real_handoff_that_needs_approval(self) -> None:
        adapter = GovernmentPortalAdapter()
        prepared = await adapter.prepare(
            request(ActionKind.GOVERNMENT_PORTAL, documents=["Passport"])
        )
        assert prepared.requires_approval and prepared.requires_user_authentication
        assert not prepared.is_simulated and not prepared.reversible
        assert any("UAE PASS" in c for c in prepared.consequences)
        with pytest.raises(ApprovalRequired):
            await adapter.execute(prepared)
        outcome = await adapter.execute(prepared, grant())
        assert outcome.status is S.HANDOFF_REQUIRED and outcome.official_url == TAMM
        assert not outcome.is_simulated

    async def test_grant_is_bound_to_one_action(self) -> None:
        adapter = GovernmentPortalAdapter()
        prepared = await adapter.prepare(request(ActionKind.GOVERNMENT_PORTAL, action_id="a1"))
        with pytest.raises(ApprovalRequired, match="different action"):
            await adapter.execute(prepared, grant("a2"))

    async def test_demo_appointment_is_labelled_and_never_booked(self) -> None:
        adapter = AppointmentAdapter(simulated=True)
        prepared = await adapter.prepare(request(ActionKind.APPOINTMENT))
        assert prepared.is_simulated and prepared.simulation_label == SIMULATION_LABEL
        assert prepared.demo_response and prepared.demo_response["booked"] is False
        assert prepared.consequences[0].startswith(SIMULATION_LABEL)
        outcome = await adapter.execute(prepared, grant())
        assert outcome.status is S.HANDOFF_REQUIRED
        assert outcome.is_simulated and outcome.simulation_label == SIMULATION_LABEL
        assert outcome.response_metadata["booked"] is False
        assert outcome.external_reference is None

    async def test_live_appointment_is_a_plain_handoff(self) -> None:
        prepared = await AppointmentAdapter(simulated=False).prepare(
            request(ActionKind.APPOINTMENT)
        )
        assert not prepared.is_simulated and prepared.demo_response is None

    async def test_demo_submission_checks_completeness_only(self) -> None:
        adapter = DocumentSubmissionAdapter(simulated=True)
        prepared = await adapter.prepare(
            request(
                ActionKind.DOCUMENT_SUBMISSION,
                documents=["Passport"],
                missing_documents=["Marriage certificate"],
            )
        )
        assert prepared.demo_response == {
            "label": SIMULATION_LABEL,
            "checks": [
                {"document": "Passport", "status": "ready"},
                {"document": "Marriage certificate", "status": "missing"},
            ],
            "submitted": False,
        }
        outcome = await adapter.execute(prepared, grant())
        assert (
            outcome.status is S.HANDOFF_REQUIRED and outcome.response_metadata["submitted"] is False
        )

    async def test_opening_an_official_page_needs_no_grant(self) -> None:
        adapter = OfficialHandoffAdapter()
        prepared = await adapter.prepare(request(ActionKind.OFFICIAL_HANDOFF))
        assert not prepared.requires_approval
        assert (await adapter.execute(prepared)).status is S.HANDOFF_REQUIRED

    async def test_unverified_links_are_refused(self) -> None:
        for adapter in (
            OfficialHandoffAdapter(),
            GovernmentPortalAdapter(),
            AppointmentAdapter(simulated=True),
        ):
            with pytest.raises(BadRequest):
                await adapter.prepare(
                    request(ActionKind.OFFICIAL_HANDOFF, url="https://tamm.example.com")
                )

    def test_demo_slots_are_deterministic_working_days(self) -> None:
        a = demo_slots("service.medical_fitness", date(2026, 10, 1))
        assert a == demo_slots("service.medical_fitness", date(2026, 10, 1))
        assert len(a) == 3
        assert all(datetime.fromisoformat(s["starts_at"]).weekday() < 5 for s in a)
        assert all("(example)" in s["label"] for s in a)

    def test_registry_modes(self) -> None:
        assert build_action_registry("demo").mode == "demo"
        assert build_action_registry("live").mode == "live"
        live = build_action_registry("live")
        assert not live.resolve(ActionKind.APPOINTMENT).is_simulated
        assert live.resolve(ActionKind.GOVERNMENT_PORTAL).name == "government_portal"

    def test_mode_resolution(self) -> None:
        assert resolve_actions_mode("auto", production=False) == "demo"
        assert resolve_actions_mode("auto", production=True) == "live"
        assert resolve_actions_mode(None, production=False) == "demo"
        with pytest.raises(ValueError, match="production"):
            resolve_actions_mode("demo", production=True)
