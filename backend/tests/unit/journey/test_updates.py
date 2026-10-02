"""Editing a plan without a run: steps marked done and answers re-plan deterministically."""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.journey import updates
from app.agents.journey.facts import fact
from app.agents.journey.nodes.human import plan_snapshot
from app.agents.journey.simulation import ScenarioError
from app.agents.journey.vocab import TaskStatus

from .governance_fixture import snapshot
from .test_simulation import completed_journey


async def base_plan() -> dict[str, Any]:
    h = await completed_journey()
    state = await h.state()
    return plan_snapshot(state, state["final_summary"])


def by_key(plan: dict[str, Any]) -> dict[str, Any]:
    return {t["key"]: t for t in plan["tasks"]}


def with_fact(plan: dict[str, Any], item: Any) -> dict[str, Any]:
    return {**{f["key"]: f for f in plan["facts"]}, item["key"]: item}


async def test_marking_a_step_done_unblocks_what_waited_for_it() -> None:
    plan = await base_plan()
    assert by_key(plan)["service.initial_approval"]["status"] == TaskStatus.BLOCKED
    task = by_key(plan)["service.trade_name_reservation"]
    item = updates.done_fact(task, "j-1")
    assert item["key"] == "completed.trade_name_reservation" and item["source"] == "user_stated"
    new = updates.replan(snapshot(), plan, with_fact(plan, item), plan["actions"])
    tasks = by_key(new)
    assert tasks["service.trade_name_reservation"]["status"] == TaskStatus.DONE
    assert tasks["service.initial_approval"]["status"] == TaskStatus.READY
    assert new["summary"].startswith("Your plan has")


async def test_answering_the_income_question_checks_the_rule() -> None:
    plan = await base_plan()
    visa = "service.family_residence_visa@spouse"
    key = updates.open_question(visa, plan)
    assert key == "finance.monthly_income_aed"
    value = updates.parse_answer(key, "AED 2,500")
    assert value == 2500.0
    new = updates.replan(
        snapshot(), plan, with_fact(plan, fact(key, value, "user_stated")), plan["actions"]
    )
    assert {r["kind"] for r in new["risks"] if visa in r["task_keys"]} >= {"eligibility_gap"}
    assert next(e for e in new["eligibility"])["status"] == "unmet"


async def test_steps_without_a_question_are_refused() -> None:
    plan = await base_plan()
    with pytest.raises(updates.NothingToAnswer):
        updates.open_question("service.trade_name_reservation", plan)


@pytest.mark.parametrize(
    ("key", "answer", "value"),
    [
        ("finance.monthly_income_aed", "25k", 25000.0),
        ("housing.accommodation_provided", "yes", True),
        ("company.jurisdiction", "adgm", "adgm"),
        ("spouse.person.age", "34", 34),
        ("meets.registered_premises", "done", True),
    ],
)
def test_parse_answer(key: str, answer: str, value: Any) -> None:
    assert updates.parse_answer(key, answer) == value


def test_invalid_answers_are_refused() -> None:
    with pytest.raises(ScenarioError):
        updates.parse_answer("company.jurisdiction", "dubai")
