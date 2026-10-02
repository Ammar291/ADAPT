"""What-if simulation: copies the journey, re-runs only what a change affects, never
mutates the active journey."""

from __future__ import annotations

import copy
from typing import Any
from uuid import uuid4

import pytest

from app.agents.journey.ports import ReadOnlyStore, SimulationWriteError
from app.agents.journey.simulation import (
    ScenarioError,
    build_simulation_graph,
    build_simulation_state,
    run_simulation,
    validate_changes,
    variable_for,
)
from app.agents.journey.vocab import NodeId

from .fakes import Harness, approve_all, harness


async def completed_journey(text: str | None = None) -> Harness:
    h = harness()
    await (h.start(text) if text else h.start())
    await h.resume(approve_all(h))
    review = h.review
    await h.resume(
        {
            "gate": "submission_confirmation",
            "review_id": review["review_id"],
            "confirmations": [
                {"action_id": i["action_id"], "outcome": "not_yet"} for i in review["items"]
            ],
        }
    )
    assert (await h.state())["final_summary"]
    return h


async def simulate(h: Harness, changes: list[dict[str, Any]]) -> tuple[dict[str, Any], Any]:
    sim_graph = build_simulation_graph(h.checkpointer)
    outcome = await run_simulation(
        journey_graph=h.graph,
        simulation_graph=sim_graph,
        context=h.context,
        base_thread_id=h.thread_id,
        base_journey_id=h.journey_id,
        base_run_id=str(h.run_id),
        scenario_journey_id=str(uuid4()),
        thread_id=f"what_if:{uuid4()}",
        changes=changes,
    )
    assert outcome.status == "completed", outcome
    return outcome.values["simulation"], outcome


class TestWhatIf:
    async def test_not_moving_with_spouse_branches_the_plan(self) -> None:
        h = await completed_journey()
        result, outcome = await simulate(h, [{"key": "household.move_with_spouse", "value": False}])
        removed = {t["key"] for t in result["removed_tasks"]}
        assert {
            "service.family_residence_visa@spouse",
            "service.medical_fitness@spouse",
            "service.health_insurance@spouse",
            "service.mofa_attestation",
        } <= removed
        assert result["added_tasks"] == []
        assert any(
            d["source"] == "service.family_residence_visa@spouse" and d["change"] == "removed"
            for d in result["changed_dependencies"]
        )
        gone = {r["id"] for r in result["changed_risks"] if r["change"] == "removed"}
        assert "risk:missing_user_document:spouse:document.passport" in gone
        changed = {n["node"] for n in result["changed_nodes"]}
        assert {"requirement_planner", "dependency_analysis", "risk_detection"} <= changed
        assert result["changes"] == [
            {
                "key": "household.move_with_spouse",
                "label": "Your spouse moves to Abu Dhabi",
                "from": True,
                "to": False,
            }
        ]
        assert result["summary"].startswith("If you move without your spouse for now:")
        assert "your plan was not changed" in result["summary"]
        assert outcome.values["final_summary"] == result["summary"]

    async def test_the_active_journey_is_never_mutated(self) -> None:
        h = await completed_journey()
        base_state = copy.deepcopy(await h.state())
        base_history = [c.config for c in [c async for c in h.graph.aget_state_history(h.config)]]
        writes, actions, plans = (
            dict(h.store.writes),
            copy.deepcopy(h.store.actions),
            copy.deepcopy(h.store.plans),
        )

        await simulate(h, [{"key": "household.move_with_spouse", "value": False}])
        await simulate(h, [{"key": "company.jurisdiction", "value": "adgm"}])

        assert await h.state() == base_state
        assert [c.config async for c in h.graph.aget_state_history(h.config)] == base_history
        assert dict(h.store.writes) == writes
        assert h.store.actions == actions and h.store.plans == plans

    async def test_simulation_services_refuse_writes(self) -> None:
        h = harness()
        store = ReadOnlyStore(h.store)  # type: ignore[arg-type]
        assert await store.user_facts() == []
        with pytest.raises(SimulationWriteError):
            await store.save_actions(journey_id="j", run_id="r", actions=[])
        with pytest.raises(SimulationWriteError):
            await store.save_plan(
                journey_id="j", plan={}, tasks=[], dependencies=[], status="active", summary=None
            )

    async def test_only_affected_nodes_rerun(self) -> None:
        h = await completed_journey()
        # income matters to eligibility rules and risks, not to which steps exist
        result, _ = await simulate(h, [{"key": "finance.monthly_income_aed", "value": 2500}])
        assert NodeId.REQUIREMENT_PLANNER.value not in result["rerun_nodes"]
        assert NodeId.DEPENDENCY_ANALYSIS.value not in result["rerun_nodes"]
        assert result["rerun_nodes"][:1] == [NodeId.ELIGIBILITY_ANALYSIS.value]
        assert NodeId.RISK_DETECTION.value in result["rerun_nodes"]
        assert result["added_tasks"] == result["removed_tasks"] == []
        added = {r["kind"] for r in result["changed_risks"] if r["change"] == "added"}
        assert "eligibility_gap" in added

    async def test_new_input_variable_is_allowed(self) -> None:
        h = await completed_journey()
        base_facts = (await h.state())["user_facts"]
        assert "finance.monthly_income_aed" not in base_facts
        result, _ = await simulate(h, [{"key": "finance.monthly_income_aed", "value": 25000}])
        assert result["changes"][0]["from"] is None
        resolved = {r["id"] for r in result["changed_risks"] if r["change"] == "removed"}
        assert "risk:missing_information:eligibility_rule.family_sponsor_income:spouse" in resolved

    async def test_jurisdiction_switches_the_alternative(self) -> None:
        h = await completed_journey()
        result, _ = await simulate(h, [{"key": "company.jurisdiction", "value": "adgm"}])
        assert {t["key"] for t in result["added_tasks"]} == {"service.company_registration_adgm"}
        assert {"service.commercial_license_mainland", "service.trade_name_reservation"} <= {
            t["key"] for t in result["removed_tasks"]
        }
        assert {
            "source": "service.establishment_card",
            "target": "service.company_registration_adgm",
            "relation": "alternative",
            "change": "added",
        } in result["changed_dependencies"]

    async def test_no_change_reruns_nothing(self) -> None:
        h = await completed_journey()
        result, _ = await simulate(h, [{"key": "household.move_with_spouse", "value": True}])
        assert result["rerun_nodes"] == [] and result["changed_nodes"] == []
        assert result["summary"].endswith("nothing in your plan changes.")

    async def test_previews_are_not_persisted(self) -> None:
        h = await completed_journey()
        _, outcome = await simulate(h, [{"key": "company.jurisdiction", "value": "adgm"}])
        docs = outcome.values["generated_documents"]
        assert docs and all(not d["persisted"] for d in docs if d["id"].startswith("preview:"))
        assert all(a["id"].startswith("preview:") for a in outcome.values["actions"])
        assert outcome.values["approval_requests"] == []

    async def test_simulation_streams_its_own_nodes(self) -> None:
        h = await completed_journey()
        before = len(h.sink.events)
        result, _ = await simulate(h, [{"key": "household.move_with_spouse", "value": False}])
        started = [e.node for e in h.sink.events[before:] if e.event == "node_started"]
        assert started == ["apply_scenario", *result["rerun_nodes"], "compare_scenarios"]
        assert not [
            e
            for e in h.sink.events[before:]
            if e.event in ("approval_required", "action_prepared", "document_generated")
        ]


class TestScenarioValidation:
    def test_unknown_variables_are_refused(self) -> None:
        with pytest.raises(ScenarioError, match="can't be changed"):
            validate_changes([{"key": "profile.religion", "value": "x"}], {})

    def test_values_are_coerced_or_refused(self) -> None:
        (change,) = validate_changes([{"key": "household.move_with_spouse", "value": "no"}], {})
        assert change["value"] is False
        with pytest.raises(ScenarioError):
            validate_changes([{"key": "company.jurisdiction", "value": "dubai"}], {})
        with pytest.raises(ScenarioError):
            validate_changes([{"key": "finance.monthly_income_aed", "value": -1}], {})

    def test_document_patterns(self) -> None:
        assert variable_for("spouse.documents.passport").type == "boolean"
        with pytest.raises(ScenarioError):
            variable_for("spouse.documents.passport.number")

    def test_a_journey_without_a_plan_cannot_be_simulated(self) -> None:
        with pytest.raises(ScenarioError, match="no plan"):
            build_simulation_state(
                {"tasks": []},
                [{"key": "household.move_with_spouse", "value": False}],
                base_journey_id="b",
                base_run_id=None,
                scenario_journey_id="s",
                run_id="r",
            )
