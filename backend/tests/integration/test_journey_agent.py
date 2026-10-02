"""The journey agent end to end on real PostgreSQL: HTTP routes, ARQ jobs (run in
process), the Postgres checkpointer, row-level security, the approval trigger and the
honesty CHECK constraints.

Every job opens its own checkpointer connection pool, so each resume is a genuine
restore from the persisted checkpoint, as in a different worker process.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.agents.checkpointer import open_checkpointer
from app.agents.journey import jobs
from app.agents.journey.store_pg import PgJourneyStore
from app.core.container import Container
from app.db.models import Action, AgentRun, Journey
from app.domain.enums import ActionStatus, RunStatus
from app.domain.principal import Principal
from app.events.notifier import NullNotifier
from app.workers.deps import WorkerDeps

from .conftest import APP_URL, auth

pytestmark = pytest.mark.integration

PROMPT = (
    "I'm a founder moving next month with my wife. I want to set up my company, "
    "find a home and sponsor her visa."
)


async def run_job(container: Container, name: str, kwargs: dict[str, Any]) -> str:
    """Execute one queued job the way the ARQ worker would, with a fresh checkpointer."""
    assert APP_URL
    async with open_checkpointer(APP_URL, max_size=2) as checkpointer:
        deps = WorkerDeps(
            settings=container.settings,
            db=container.db,
            notifier=NullNotifier(),
            adapters=container.adapters,
            checkpointer=checkpointer,
            queue=container.queue,
            _stack=AsyncExitStack(),
        )
        return await getattr(jobs, name)({"deps": deps}, **kwargs)


def take_job(container: Container, name: str) -> dict[str, Any]:
    jobs_seen = container.queue.jobs  # type: ignore[attr-defined]
    for index, (function, kwargs) in enumerate(jobs_seen):
        if function == name:
            jobs_seen.pop(index)
            return kwargs
    raise AssertionError(f"no {name} job queued: {[f for f, _ in jobs_seen]}")


async def start_and_pause(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> tuple[str, str]:
    r = await api.post("/api/journey", json={"prompt": PROMPT}, headers=auth(alice))
    assert r.status_code == 202, r.text
    body = r.json()
    assert (
        await run_job(container, "run_journey", take_job(container, "run_journey")) == "interrupted"
    )
    return body["journey_id"], body["run"]["id"]


async def test_journey_end_to_end(
    api: httpx.AsyncClient, container: Container, alice: Principal, bob: Principal
) -> None:
    journey_id, run_id = await start_and_pause(api, container, alice)

    # --- paused at the approval gate ----------------------------------------------------------
    r = await api.get(f"/api/agents/{run_id}/review", headers=auth(alice))
    assert r.status_code == 200, r.text
    review = r.json()
    assert review["gate"] == "action_approval" and review["items"]
    detail = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()
    assert detail["status"] == "draft" and detail["nodes"] and detail["edges"]
    assert detail["pending_review"]["review_id"] == review["review_id"]
    assert detail["latest_run"]["status"] == "awaiting_input"
    assert {a["status"] for a in detail["actions"] if a["requires_human_approval"]} == {
        "awaiting_approval"
    }
    assert all(n["provenance"]["kind"] for n in detail["nodes"])

    # --- other users see nothing ------------------------------------------------------------
    assert (await api.get(f"/api/journey/{journey_id}", headers=auth(bob))).status_code == 404
    assert (await api.get(f"/api/agents/{run_id}/review", headers=auth(bob))).status_code == 404
    item = review["items"][0]
    assert (
        await api.post(f"/api/actions/{item['action_id']}/approve", headers=auth(bob))
    ).status_code == 404

    # --- decide each action; the last decision resumes the run --------------------------------
    rejected = review["items"][0]["action_id"]
    resumed = []
    for item in review["items"]:
        verb = "reject" if item["action_id"] == rejected else "approve"
        r = await api.post(f"/api/actions/{item['action_id']}/{verb}", json={}, headers=auth(alice))
        assert r.status_code == 200, r.text
        resumed.append(r.json()["run_resumed"])
    assert resumed[-1] is True and not any(resumed[:-1])
    again = await api.post(
        f"/api/actions/{review['items'][1]['action_id']}/approve", headers=auth(alice)
    )
    assert again.status_code == 409  # already decided
    assert (
        await run_job(container, "resume_journey", take_job(container, "resume_journey"))
        == "interrupted"
    )

    # --- confirm how the official steps went ---------------------------------------------------
    review = (await api.get(f"/api/agents/{run_id}/review", headers=auth(alice))).json()
    assert review["gate"] == "submission_confirmation"
    confirmations = [
        {
            "action_id": i["action_id"],
            "outcome": "submitted" if n == 0 else "not_yet",
            "reference": "REF-1" if n == 0 else None,
        }
        for n, i in enumerate(review["items"])
    ]
    body = {
        "gate": "submission_confirmation",
        "review_id": review["review_id"],
        "confirmations": confirmations,
    }
    r = await api.post(f"/api/agents/{run_id}/resume", json=body, headers=auth(alice))
    assert r.status_code == 202 and r.json()["resumed"] is True, r.text
    assert (
        await api.post(f"/api/agents/{run_id}/resume", json=body, headers=auth(alice))
    ).status_code == 404
    assert (
        await run_job(container, "resume_journey", take_job(container, "resume_journey"))
        == "completed"
    )

    # --- the final plan -------------------------------------------------------------------------
    detail = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()
    assert detail["status"] == "active" and detail["summary"].startswith("Your plan has")
    assert detail["pending_review"] is None and detail["latest_run"]["status"] == "succeeded"
    assert detail["risks"] and detail["generated_documents"]
    by_id = {a["id"]: a for a in detail["actions"]}
    assert by_id[rejected]["status"] == "draft"
    first = by_id[confirmations[0]["action_id"]]
    assert first["status"] == "handoff_required" and first["confirmation_source"] is None
    assert first["external_reference"] is None
    for action in detail["actions"]:
        if action["is_simulated"]:
            assert action["simulation_label"] == "DEMO / SIMULATED"
            assert action["status"] in ("handoff_required", "draft")
    statuses = {n["key"]: n["status"] for n in detail["nodes"]}
    assert statuses and set(statuses.values()) <= {
        "ready",
        "blocked",
        "needs_info",
        "handoff",
        "in_progress",
        "awaiting_approval",
        "done",
    }


async def test_database_refuses_dishonest_statuses(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    journey_id, _ = await start_and_pause(api, container, alice)
    store = PgJourneyStore(container.db, alice)
    async with container.db.user_session(alice) as session:
        action = (
            (
                await session.execute(
                    select(Action).where(
                        Action.journey_id == UUID(journey_id), Action.requires_human_approval
                    )
                )
            )
            .scalars()
            .first()
        )
    assert action is not None
    record = (await store.load_actions([str(action.id)]))[str(action.id)]
    # the agent can't mark it completed without a reference or an approved approval
    with pytest.raises(DBAPIError):
        await store.save_actions(
            journey_id=journey_id,
            run_id="",
            actions=[{**record, "status": ActionStatus.COMPLETED.value}],
        )
    with pytest.raises(DBAPIError):
        await store.save_actions(
            journey_id=journey_id,
            run_id="",
            actions=[{**record, "status": ActionStatus.APPROVED.value}],
        )
    with pytest.raises(DBAPIError):
        await store.save_actions(
            journey_id=journey_id,
            run_id="",
            actions=[
                {
                    **record,
                    "status": ActionStatus.SUBMITTED.value,
                    "is_simulated": True,
                    "external_reference": "X",
                }
            ],
        )


async def test_what_if_never_touches_the_active_journey(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    journey_id, run_id = await start_and_pause(api, container, alice)
    # finish quickly: reject everything
    review = (await api.get(f"/api/agents/{run_id}/review", headers=auth(alice))).json()
    for item in review["items"]:
        await api.post(f"/api/actions/{item['action_id']}/reject", headers=auth(alice))
    assert (
        await run_job(container, "resume_journey", take_job(container, "resume_journey"))
        == "completed"
    )
    before = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()

    r = await api.get(f"/api/journey/{journey_id}/what-if/variables", headers=auth(alice))
    variables = {v["key"]: v for v in r.json()}
    assert variables["household.move_with_spouse"]["current"] is True

    r = await api.post(
        f"/api/journey/{journey_id}/simulate",
        json={"changes": [{"key": "household.move_with_spouse", "value": False}]},
        headers=auth(alice),
    )
    assert r.status_code == 202, r.text
    scenario_id = r.json()["scenario_journey_id"]
    assert (
        await run_job(container, "run_what_if", take_job(container, "run_what_if")) == "completed"
    )

    scenario = (await api.get(f"/api/journey/{scenario_id}", headers=auth(alice))).json()
    assert scenario["status"] == "scenario" and scenario["parent_journey_id"] == journey_id
    result = scenario["simulation_result"]
    removed = {t["key"] for t in result["removed_tasks"]}
    assert "service.family_residence_visa@spouse" in removed
    assert result["changed_nodes"] and result["summary"]
    assert not [n for n in scenario["nodes"] if n["key"].endswith("@spouse")]

    after = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()
    for key in (
        "status",
        "summary",
        "nodes",
        "edges",
        "risks",
        "actions",
        "considerations",
        "assumptions",
    ):
        assert after[key] == before[key], key

    bad = await api.post(
        f"/api/journey/{journey_id}/simulate",
        json={"changes": [{"key": "profile.religion", "value": "x"}]},
        headers=auth(alice),
    )
    assert bad.status_code == 422


async def test_generic_agent_route_starts_a_journey(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    r = await api.post(
        "/api/agents/run",
        json={"agent": "journey", "input": {"prompt": PROMPT}},
        headers=auth(alice),
    )
    assert r.status_code == 202, r.text
    run_id = r.json()["run"]["id"]
    assert (
        await run_job(container, "run_journey", take_job(container, "run_journey")) == "interrupted"
    )
    async with container.db.user_session(alice) as session:
        run = await session.get(AgentRun, UUID(run_id))
        assert (
            run is not None
            and run.journey_id is not None
            and run.status is RunStatus.AWAITING_INPUT
        )
        journey = await session.get(Journey, run.journey_id)
        assert journey is not None and journey.plan.get("tasks")


async def test_checkpoints_are_in_postgres(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    _, run_id = await start_and_pause(api, container, alice)
    async with container.db.user_session(alice) as session:
        run = await session.get(AgentRun, UUID(run_id))
        assert run is not None
        count = (
            await session.execute(
                text("SELECT count(*) FROM langgraph.checkpoints WHERE thread_id = :t"),
                {"t": run.thread_id},
            )
        ).scalar_one()
    assert count > 0
    # a stray duplicate delivery of the start job is ignored
    assert (
        await run_job(
            container,
            "run_journey",
            {
                "run_id": run_id,
                "user_id": str(alice.user_id),
                "tenant_id": str(alice.tenant_id),
                "prompt": PROMPT,
            },
        )
        == "skipped"
    )
    _ = uuid4


async def test_official_step_requires_provider_confirmation_and_answers_replan(
    api: httpx.AsyncClient, container: Container, alice: Principal
) -> None:
    journey_id, run_id = await start_and_pause(api, container, alice)
    review = (await api.get(f"/api/agents/{run_id}/review", headers=auth(alice))).json()
    for item in review["items"]:
        await api.post(f"/api/actions/{item['action_id']}/reject", headers=auth(alice))
    assert (
        await run_job(container, "resume_journey", take_job(container, "resume_journey"))
        == "completed"
    )
    before = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()
    nodes = {n["key"]: n for n in before["nodes"]}
    first = next(
        k
        for k, n in nodes.items()
        if n["status"] in ("ready", "needs_info") and n["kind"] == "task"
    )

    r = await api.post(f"/api/journey/{journey_id}/nodes/{first}/done", headers=auth(alice))
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "provider_confirmation_required"
    after = (await api.get(f"/api/journey/{journey_id}", headers=auth(alice))).json()
    assert next(n for n in after["nodes"] if n["key"] == first)["status"] == nodes[first]["status"]

    visa = "service.family_residence_visa@spouse"
    questions = {n["key"]: n["details"]["open_questions"] for n in after["nodes"]}[visa]
    assert questions[0]["key"] == "finance.monthly_income_aed"
    r = await api.post(
        f"/api/journey/{journey_id}/nodes/{visa}/answer",
        json={"answer": "AED 2,000"},
        headers=auth(alice),
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["assumptions"]["finance.monthly_income_aed"]["value"] == 2000.0
    assert any(e["status"] == "unmet" for e in detail["eligibility"])
    assert any(risk["kind"] == "eligibility_gap" for risk in detail["risks"])
    nothing = await api.post(
        f"/api/journey/{journey_id}/nodes/{first}/answer", json={"answer": "x"}, headers=auth(alice)
    )
    assert nothing.status_code == 409

    # a what-if copies the edited plan, not the older checkpoint
    r = await api.post(
        f"/api/journey/{journey_id}/simulate",
        json={"changes": [{"key": "finance.monthly_income_aed", "value": 30000}]},
        headers=auth(alice),
    )
    assert (
        await run_job(container, "run_what_if", take_job(container, "run_what_if")) == "completed"
    )
    result = (
        await api.get(f"/api/journey/{r.json()['scenario_journey_id']}", headers=auth(alice))
    ).json()["simulation_result"]
    assert result["changes"][0]["from"] == 2000.0
    assert any(
        risk["kind"] == "eligibility_gap" and risk["change"] == "removed"
        for risk in result["changed_risks"]
    )
