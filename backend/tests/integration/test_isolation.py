"""User isolation and graph isolation, enforced by PostgreSQL RLS and verified end to end.

Two layers are tested: the database (an unfiltered query as another user sees nothing,
forged ownership is rejected) and the HTTP API (another user's resources are 404).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.container import Container
from app.db.models import (
    PRIVATE_TABLES,
    AgentRun,
    GraphEdge,
    GraphNode,
    Journey,
    User,
    UserProfile,
)
from app.db.session import Database
from app.domain.enums import GraphEdgeType, GraphType, RunKind, TwinNodeType
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.main import create_app
from app.repositories.graph import GovernanceGraphRepository, UserGraphRepository
from app.repositories.runs import create_run, get_run
from tests.integration.conftest import auth, make_principal, make_settings


async def test_sample_household_sessions_never_share_private_graphs(api: httpx.AsyncClient) -> None:
    first = await api.post("/api/auth/demo-session", json={"sample_household": True})
    assert first.status_code == 200, first.text
    alice_user = first.json()["user"]
    alice_token = api.cookies.get("adapt_session")
    # A second visitor requests the same synthetic persona, with an independent session.
    api.cookies.clear()
    second = await api.post("/api/auth/demo-session", json={"sample_household": True})
    assert second.status_code == 200, second.text
    bob_user = second.json()["user"]
    bob_token = api.cookies.get("adapt_session")
    assert alice_user["id"] != bob_user["id"] and alice_user["tenant_id"] != bob_user["tenant_id"]
    alice_graph = (
        await api.get("/api/graph/user", headers={"Authorization": f"Bearer {alice_token}"})
    ).json()
    bob_graph = (
        await api.get("/api/graph/user", headers={"Authorization": f"Bearer {bob_token}"})
    ).json()
    alice_nodes = {n["id"] for n in alice_graph["nodes"]}
    bob_nodes = {n["id"] for n in bob_graph["nodes"]}
    assert alice_nodes and bob_nodes and alice_nodes.isdisjoint(bob_nodes)
    api.cookies.clear()


async def test_seeded_demo_server_gives_every_new_visitor_the_sample_household(
    container: Container, tmp_path: Path
) -> None:
    # A visitor who opens the seeded server without `?seed=sample` still gets the household.
    seeded = replace(container, settings=make_settings(tmp_path, demo_seed_sample_household=True))
    transport = httpx.ASGITransport(create_app(seeded.settings, seeded))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await api.post("/api/auth/demo-session", json={})
        assert response.status_code == 200, response.text
        profile = (await api.get("/api/profile")).json()
    assert profile["household"], "the sample household was not copied into the new account"


ONBOARDING = {
    "display_name": "Test founder",
    "profile": {
        "nationality": "IND",
        "persona": "founder",
        "arrival_date": "2026-11-15",
        "company_name": "Example Labs",
        "assumptions": {"company.jurisdiction": "adgm"},
    },
    "household": [{"relationship": "spouse", "name": "Sam", "relocation_plan": "later"}],
    "goals": [{"goal_type": "sponsor_family"}, {"goal_type": "establish_company"}],
    "preferences": [{"category": "housing", "key": "preferred_area", "value": "Al Reem Island"}],
}


async def _user_node(db: Database, principal: Principal, key: str = "person.self") -> GraphNode:
    async with db.user_session(principal) as session:
        node = await UserGraphRepository(session).upsert_node(
            entity_type=TwinNodeType.PERSON.value, key=key, label="Me"
        )
        await session.commit()
        return node


# --- database layer ----------------------------------------------------------------------------


async def test_every_private_table_has_an_owner_policy(owner_db: Database) -> None:
    async with owner_db.public_session() as session:
        rows = await session.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_policies p ON p.tablename = c.relname "
                "WHERE c.relrowsecurity AND p.policyname = c.relname || '_owner'"
            )
        )
        protected = {r[0] for r in rows}
    assert protected == set(PRIVATE_TABLES)


async def test_accounts_are_invisible_to_other_users(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    async with app_db.user_session(bob) as session:
        users = list((await session.execute(select(User.id))).scalars())
    assert users == [bob.user_id]
    async with app_db.public_session() as session:
        assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 0


async def test_user_graph_rows_are_invisible_to_other_users(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    await _user_node(app_db, alice)
    async with app_db.user_session(bob) as session:
        nodes, _, _ = await UserGraphRepository(session).graph()
        # Even an unfiltered query cannot see Alice's rows.
        visible = (
            await session.execute(
                select(func.count()).where(GraphNode.graph_type == GraphType.USER)
            )
        ).scalar_one()
    assert nodes == []
    assert visible == 0


async def test_public_session_sees_governance_only(app_db: Database, alice: Principal) -> None:
    await _user_node(app_db, alice)
    async with app_db.public_session() as session:
        graph_types = set(
            (await session.execute(select(GraphNode.graph_type).distinct())).scalars()
        )
        services = await GovernanceGraphRepository(session).nodes()
    assert graph_types == {GraphType.GOVERNANCE}
    assert len(services) >= 30


async def test_governance_repository_never_returns_user_rows(
    app_db: Database, alice: Principal
) -> None:
    node = await _user_node(app_db, alice, key="person.probe")
    async with app_db.user_session(alice) as session:
        repo = GovernanceGraphRepository(session)
        assert await repo.get(str(node.id)) is None
        assert await repo.get("person.probe") is None
        assert all(n.graph_type is GraphType.GOVERNANCE for n in await repo.nodes(search="Me"))


async def test_runtime_role_cannot_write_governance(app_db: Database) -> None:
    async with app_db.public_session() as session:
        session.add(
            GraphNode(
                graph_type=GraphType.GOVERNANCE,
                entity_type="service",
                key="service.fake",
                label="Fake",
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.commit()


async def test_cannot_forge_ownership(app_db: Database, alice: Principal, bob: Principal) -> None:
    async with app_db.user_session(bob) as session:
        session.add(
            GraphNode(
                graph_type=GraphType.USER,
                tenant_id=alice.tenant_id,
                user_id=alice.user_id,
                entity_type="goal",
                key="goal.injected",
                label="Injected",
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.commit()


async def test_cannot_link_to_another_users_node(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    alice_node = await _user_node(app_db, alice, key="person.alice")
    bob_node = await _user_node(app_db, bob, key="person.bob")
    async with app_db.user_session(bob) as session:
        session.add(
            GraphEdge(
                graph_type=GraphType.USER,
                tenant_id=bob.tenant_id,
                user_id=bob.user_id,
                relation=GraphEdgeType.HAS_HOUSEHOLD_MEMBER,
                source_node_id=bob_node.id,
                target_node_id=alice_node.id,
            )
        )
        with pytest.raises(DBAPIError, match="not found"):
            await session.commit()


async def test_governance_edges_cannot_touch_user_nodes(
    owner_db: Database, app_db: Database, alice: Principal
) -> None:
    user_node = await _user_node(app_db, alice, key="person.edge_probe")
    async with owner_db.public_session() as session:
        service_id = (
            (
                await session.execute(
                    select(GraphNode.id).where(
                        GraphNode.graph_type == GraphType.GOVERNANCE,
                        GraphNode.entity_type == "service",
                    )
                )
            )
            .scalars()
            .first()
        )
        session.add(
            GraphEdge(
                graph_type=GraphType.GOVERNANCE,
                relation=GraphEdgeType.REQUIRES,
                source_node_id=service_id,
                target_node_id=user_node.id,
            )
        )
        with pytest.raises(DBAPIError, match="governance edges may only connect governance"):
            await session.commit()


async def test_personalisation_link_to_governance(app_db: Database, alice: Principal) -> None:
    async with app_db.user_session(alice) as session:
        repo = UserGraphRepository(session)
        goal = await repo.upsert_node(
            entity_type=TwinNodeType.GOAL.value, key="goal.sponsor_family", label="Sponsor my wife"
        )
        service = await GovernanceGraphRepository(session).get("service.family_residence_visa")
        assert service is not None
        await repo.link(GraphEdgeType.PURSUES, goal, service)
        await session.commit()
        _, linked, edges = await repo.graph()
    assert [n.key for n in linked] == ["service.family_residence_visa"]
    assert edges[0].graph_type is GraphType.USER


async def test_runs_and_events_are_private(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        run = await create_run(session, alice, RunKind.DIAGNOSTIC)
        await session.commit()
    await RunEventEmitter(app_db, alice, run.id).run_started(RunKind.DIAGNOSTIC)
    async with app_db.user_session(bob) as session:
        assert await get_run(session, run.id) is None
        assert (await session.execute(select(func.count()).select_from(AgentRun))).scalar_one() == 0
        events = (await session.execute(text("SELECT count(*) FROM agent_events"))).scalar_one()
    assert events == 0


async def test_deleting_an_account_removes_all_private_data(
    owner_db: Database, app_db: Database, api: httpx.AsyncClient
) -> None:
    principal = await make_principal(app_db)
    assert (
        await api.post("/api/onboarding/profile", json=ONBOARDING, headers=auth(principal))
    ).status_code == 200
    assert (await api.delete("/api/me", headers=auth(principal))).status_code == 204
    async with owner_db.public_session() as session:
        for model in (GraphNode, UserProfile, User):
            remaining = (
                await session.execute(
                    select(func.count())
                    .select_from(model)
                    .where((model.id if model is User else model.user_id) == principal.user_id)  # type: ignore[attr-defined]
                )
            ).scalar_one()
            assert remaining == 0, model.__tablename__


# --- API layer --------------------------------------------------------------------------------


async def test_api_requires_a_session(api: httpx.AsyncClient) -> None:
    for path in (
        "/api/profile",
        "/api/graph/user",
        f"/api/agents/{uuid4()}",
        "/api/documents/generated",
    ):
        response = await api.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "session_missing"


async def test_profile_and_user_graph_are_isolated(
    api: httpx.AsyncClient, alice: Principal, bob: Principal
) -> None:
    created = await api.post("/api/onboarding/profile", json=ONBOARDING, headers=auth(alice))
    assert created.status_code == 200, created.text
    assert created.json()["completeness"]["complete"] is True

    bob_profile = (await api.get("/api/profile", headers=auth(bob))).json()
    assert bob_profile["household"] == [] and bob_profile["goals"] == []

    alice_graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    bob_graph = (await api.get("/api/graph/user", headers=auth(bob))).json()
    assert alice_graph["nodes"], "onboarding projects the profile into the user graph"
    alice_ids = {n["id"] for n in alice_graph["nodes"]}
    assert not alice_ids & {n["id"] for n in bob_graph["nodes"]}
    assert all(n["graph_type"] == "user" for n in alice_graph["nodes"])
    # Personalisation links (if any) point into the shared governance graph only.
    assert all(n["graph_type"] == "governance" for n in alice_graph["linked_governance_nodes"])

    governance = (await api.get("/api/graph/governance")).json()
    governance_ids = {n["id"] for n in governance["nodes"]}
    assert governance_ids and not governance_ids & alice_ids


async def test_another_users_resources_are_not_found(
    app_db: Database, api: httpx.AsyncClient, alice: Principal, bob: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        journey = Journey(tenant_id=alice.tenant_id, user_id=alice.user_id, title="Alice's move")
        session.add(journey)
        run = await create_run(session, alice, RunKind.DIAGNOSTIC)
        await session.commit()
    ids: dict[str, UUID] = {"journey": journey.id, "run": run.id}
    for path in (
        f"/api/graph/journey/{ids['journey']}",
        f"/api/journey/{ids['journey']}",
        f"/api/agents/{ids['run']}",
        f"/api/agents/{ids['run']}/events",
    ):
        own = await api.get(path, headers=auth(alice))
        other = await api.get(path, headers=auth(bob))
        assert own.status_code == 200, (path, own.text)
        assert other.status_code == 404, path
