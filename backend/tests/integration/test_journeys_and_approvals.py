"""Journey storage and creation, approval states, and the demo household seed."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.container import Container
from app.db.models import Action, ActionApproval, Journey, JourneyEdge, JourneyNode
from app.db.session import Database
from app.domain.enums import (
    ActionKind,
    ActionStatus,
    ApprovalStatus,
    ConfirmationSource,
    JourneyEdgeType,
    StepCategory,
    StepStatus,
)
from app.domain.principal import Principal
from app.domain.provenance import Provenance
from app.seed.demo import DEMO_PRINCIPAL, seed_demo_household
from app.services.journeys import add_journey_node
from tests.integration.conftest import auth

PROVENANCE = Provenance.ai("test").model_dump(mode="json")


async def _journey(
    db: Database, principal: Principal, keys: list[str]
) -> tuple[Journey, list[JourneyNode]]:
    async with db.user_session(principal) as session:
        journey = Journey(tenant_id=principal.tenant_id, user_id=principal.user_id, title="Move")
        session.add(journey)
        await session.flush()
        nodes = [
            JourneyNode(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                journey_id=journey.id,
                key=key,
                title=key,
                category=StepCategory.RESIDENCY,
                status=StepStatus.READY,
                position=i,
                provenance=PROVENANCE,
            )
            for i, key in enumerate(keys)
        ]
        session.add_all(nodes)
        await session.flush()
        for later, earlier in zip(nodes[1:], nodes, strict=False):
            session.add(
                JourneyEdge(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    journey_id=journey.id,
                    source_node_id=later.id,
                    target_node_id=earlier.id,
                    relation=JourneyEdgeType.DEPENDS_ON,
                )
            )
        await session.commit()
        return journey, nodes


# --- journeys ------------------------------------------------------------------------------------


async def test_journey_graph_round_trip(
    app_db: Database, api: httpx.AsyncClient, alice: Principal
) -> None:
    journey, nodes = await _journey(app_db, alice, ["visa.entry", "visa.medical", "visa.residence"])
    response = await api.get(f"/api/graph/journey/{journey.id}", headers=auth(alice))
    assert response.status_code == 200, response.text
    graph = response.json()
    assert [n["key"] for n in graph["nodes"]] == ["visa.entry", "visa.medical", "visa.residence"]
    assert {(e["source_node_id"], e["target_node_id"]) for e in graph["edges"]} == {
        (str(nodes[1].id), str(nodes[0].id)),
        (str(nodes[2].id), str(nodes[1].id)),
    }
    listing = (await api.get("/api/journey", headers=auth(alice))).json()
    assert any(j["id"] == str(journey.id) and j["node_count"] == 3 for j in listing)


async def test_edges_cannot_cross_journeys(app_db: Database, alice: Principal) -> None:
    first, first_nodes = await _journey(app_db, alice, ["a.one"])
    _, other_nodes = await _journey(app_db, alice, ["b.one"])
    async with app_db.user_session(alice) as session:
        session.add(
            JourneyEdge(
                tenant_id=alice.tenant_id,
                user_id=alice.user_id,
                journey_id=first.id,
                source_node_id=first_nodes[0].id,
                target_node_id=other_nodes[0].id,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_add_journey_node_appends_once(app_db: Database, alice: Principal) -> None:
    journey, _ = await _journey(app_db, alice, ["x.one"])
    async with app_db.user_session(alice) as session:
        kwargs = dict(
            journey_id=journey.id,
            title="Join a founders' meetup",
            summary="Saved from Discover",
            category=StepCategory.COMMUNITY,
            provenance=Provenance.ai("saved"),
            source_ref="research_result:123",
        )
        first = await add_journey_node(session, alice, **kwargs)  # type: ignore[arg-type]
        again = await add_journey_node(session, alice, **kwargs)  # type: ignore[arg-type]
        await session.commit()
        count = len(
            (
                await session.execute(
                    select(JourneyNode).where(JourneyNode.journey_id == journey.id)
                )
            ).all()
        )
    assert first == again and count == 2


async def test_demo_seed_creates_a_dependency_ordered_journey(
    owner_db: Database, api: httpx.AsyncClient, container: Container
) -> None:
    report = await seed_demo_household(owner_db, adapters=container.adapters)
    # idempotent: rebuilt from scratch
    again = await seed_demo_household(owner_db, adapters=container.adapters)
    assert again.journey_nodes == report.journey_nodes > 5
    assert again.documents == 5 and again.actions >= 1 and again.appointments == 2

    headers = auth(DEMO_PRINCIPAL)
    graph = (await api.get(f"/api/graph/journey/{again.journey_id}", headers=headers)).json()
    position = {n["id"]: n["position"] for n in graph["nodes"]}
    for edge in graph["edges"]:  # every prerequisite comes earlier in the plan
        assert position[edge["target_node_id"]] < position[edge["source_node_id"]]
    status = {n["id"]: n["status"] for n in graph["nodes"]}
    waiting = {e["source_node_id"] for e in graph["edges"] if status[e["target_node_id"]] != "done"}
    for node in graph["nodes"]:  # blocked exactly when something must happen first
        if node["status"] == "done":
            continue
        ready = {"ready", "needs_info", "awaiting_approval"}
        assert node["status"] in ({"blocked"} if node["id"] in waiting else ready), node["key"]
    nodes = {n["key"]: n for n in graph["nodes"]}
    family = nodes["service.family_residence_visa@spouse"]
    assert {b["kind"] for b in family["blockers"]} >= {"dependency"}
    # His ADGM licence and registered lease settle those steps.
    assert nodes["service.company_registration_adgm"]["status"] == "done"
    assert nodes["service.tawtheeq"]["status"] == "done"
    assert "service.commercial_license_mainland" not in nodes

    profile = (await api.get("/api/profile", headers=headers)).json()
    assert {m["relationship"] for m in profile["household"]} == {"spouse", "child"}
    run = (await api.get(f"/api/agents/{again.run_id}/events", headers=headers)).json()
    kinds = [e["event"] for e in run["events"]]
    assert kinds[0] == "run_started" and kinds[-1] == "run_completed"
    assert {
        "node_started",
        "tool_called",
        "document_generated",
        "action_prepared",
        "approval_required",
    } <= set(kinds)
    assert [e["seq"] for e in run["events"]] == list(range(1, len(kinds) + 1))


# --- approval states ------------------------------------------------------------------------------


async def _action(db: Database, principal: Principal, **values: object) -> Action:
    async with db.user_session(principal) as session:
        action = Action(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            type=ActionKind.GOVERNMENT_PORTAL,
            status=ActionStatus.AWAITING_APPROVAL,
            adapter="official_handoff",
            title="Start incorporation",
            official_url="https://www.adgm.com",
            is_simulated=False,
            **values,
        )
        session.add(action)
        await session.flush()
        session.add(
            ActionApproval(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                action_id=action.id,
                status=ApprovalStatus.PENDING,
            )
        )
        await session.commit()
        return action


async def _approval(db: Database, principal: Principal, action: Action) -> ActionApproval:
    async with db.user_session(principal) as session:
        return (
            await session.execute(
                select(ActionApproval).where(ActionApproval.action_id == action.id)
            )
        ).scalar_one()


async def _set_action(db: Database, principal: Principal, action: Action, **values: object) -> None:
    async with db.user_session(principal) as session:
        await session.execute(update(Action).where(Action.id == action.id).values(**values))
        await session.commit()


async def test_pending_approval_cannot_authorise(app_db: Database, alice: Principal) -> None:
    action = await _action(app_db, alice)
    approval = await _approval(app_db, alice, action)
    with pytest.raises(DBAPIError, match="needs an approved"):
        await _set_action(
            app_db, alice, action, status=ActionStatus.APPROVED, approval_id=approval.id
        )


async def test_approved_decision_moves_the_action(app_db: Database, alice: Principal) -> None:
    action = await _action(app_db, alice)
    approval = await _approval(app_db, alice, action)
    async with app_db.user_session(alice) as session:
        await session.execute(
            update(ActionApproval)
            .where(ActionApproval.id == approval.id)
            .values(status=ApprovalStatus.APPROVED, decided_at=approval.created_at)
        )
        await session.commit()
    await _set_action(app_db, alice, action, status=ActionStatus.APPROVED, approval_id=approval.id)
    await _set_action(app_db, alice, action, status=ActionStatus.HANDOFF_REQUIRED)


async def test_approved_payload_cannot_change_without_new_review(
    app_db: Database, alice: Principal
) -> None:
    action = await _action(app_db, alice)
    approval = await _approval(app_db, alice, action)
    async with app_db.user_session(alice) as session:
        await session.execute(
            update(ActionApproval)
            .where(ActionApproval.id == approval.id)
            .values(status=ApprovalStatus.APPROVED, decided_at=approval.created_at)
        )
        await session.commit()
    await _set_action(app_db, alice, action, status=ActionStatus.APPROVED, approval_id=approval.id)
    with pytest.raises(DBAPIError, match="scope is immutable"):
        await _set_action(app_db, alice, action, payload={"new_target": "not approved"})


async def test_rejected_decision_cannot_authorise(app_db: Database, alice: Principal) -> None:
    action = await _action(app_db, alice)
    approval = await _approval(app_db, alice, action)
    async with app_db.user_session(alice) as session:
        await session.execute(
            update(ActionApproval)
            .where(ActionApproval.id == approval.id)
            .values(status=ApprovalStatus.REJECTED, decided_at=approval.created_at)
        )
        await session.commit()
    with pytest.raises(DBAPIError, match="needs an approved"):
        await _set_action(
            app_db, alice, action, status=ActionStatus.SUBMITTED, approval_id=approval.id
        )


async def test_decision_timestamp_matches_status(app_db: Database, alice: Principal) -> None:
    action = await _action(app_db, alice)
    approval = await _approval(app_db, alice, action)
    async with app_db.user_session(alice) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(ActionApproval)
                .where(ActionApproval.id == approval.id)
                .values(status=ApprovalStatus.APPROVED)  # no decided_at
            )


async def test_one_approval_per_action(app_db: Database, alice: Principal) -> None:
    action = await _action(app_db, alice)
    async with app_db.user_session(alice) as session:
        session.add(
            ActionApproval(tenant_id=alice.tenant_id, user_id=alice.user_id, action_id=action.id)
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize(
    "values",
    [
        {"status": ActionStatus.COMPLETED},  # no external reference
        {"status": ActionStatus.HANDOFF_REQUIRED, "official_url": "javascript:alert(1)"},
        {"status": ActionStatus.HANDOFF_REQUIRED, "official_url": None},
    ],
)
async def test_honesty_constraints(
    app_db: Database, alice: Principal, values: dict[str, object]
) -> None:
    action = await _action(app_db, alice)
    with pytest.raises(DBAPIError):
        await _set_action(app_db, alice, action, **values)


async def test_simulated_adapters_cannot_submit(app_db: Database, alice: Principal) -> None:
    action = await _action(app_db, alice)
    approval = await _approval(app_db, alice, action)
    async with app_db.user_session(alice) as session:
        await session.execute(
            update(ActionApproval)
            .where(ActionApproval.id == approval.id)
            .values(status=ApprovalStatus.APPROVED, decided_at=approval.created_at)
        )
        await session.commit()
    with pytest.raises(IntegrityError):
        await _set_action(
            app_db,
            alice,
            action,
            is_simulated=True,
            status=ActionStatus.SUBMITTED,
            approval_id=approval.id,
        )
    # A user-typed reference is still not a provider receipt.
    with pytest.raises(DBAPIError):
        await _set_action(
            app_db,
            alice,
            action,
            is_simulated=True,
            status=ActionStatus.COMPLETED,
            approval_id=approval.id,
            confirmation_source=ConfirmationSource.USER_REPORTED,
            external_reference="APP-12345",
        )
