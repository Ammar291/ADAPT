"""The private user graph against real Postgres: creation, facts, isolation, invariants."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.models import GraphNode
from app.db.models.user_data import ExtractedFact, UserDocument
from app.db.session import Database
from app.domain.enums import FactSource, GraphType
from app.domain.principal import Principal
from app.domain.twin import TwinFact
from app.personalization import facts
from app.personalization.store import UserGraph
from app.personalization.vocabulary import UserEntityType
from tests.integration.conftest import auth

E = UserEntityType


async def post_fact(api: httpx.AsyncClient, who: Principal, **body: Any) -> httpx.Response:
    return await api.post("/api/graph/user/facts", json=body, headers=auth(who))


async def test_facts_build_the_graph_structure(api: httpx.AsyncClient, alice: Principal) -> None:
    assert (
        await post_fact(
            api, alice, entity_type="spouse", attribute="full_name", value="Priya Mehta"
        )
    ).status_code == 201
    assert (
        await post_fact(api, alice, entity_type="nationality", attribute="country", value="India")
    ).status_code == 201
    goal = await post_fact(api, alice, entity_type="goal", attribute="kind", value="start_company")
    housing = await post_fact(
        api,
        alice,
        entity_type="housing_preference",
        attribute="preferred_area",
        value="Al Reem Island",
    )
    community = await post_fact(
        api, alice, entity_type="community_preference", attribute="interest", value="Founders"
    )
    assert goal.json()["value_display"] == "Start a company"
    assert housing.status_code == community.status_code == 201

    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    nodes = {n["type"]: n for n in graph["nodes"]}
    hub = nodes["person"]
    assert hub["key"] == "person.self" and hub["label"] == "You"
    expected = {
        "spouse": "has_household_member",
        "nationality": "has_nationality",
        "goal": "has_goal",
        "housing_preference": "prefers",
        "community_preference": "seeks",
    }
    for entity_type, relation in expected.items():
        node = nodes[entity_type]
        assert node["parent_id"] == hub["id"] and node["relation"] == relation
        assert node["status"] == "confirmed"
    assert nodes["nationality"]["label"] == "India"
    assert nodes["housing_preference"]["label"] == "Housing in Al Reem Island"
    fact = nodes["spouse"]["facts"][0]
    assert (fact["source"], fact["extraction_method"], fact["origin"]) == (
        "user_stated", "user_entry", "You told ADAPT",
    )  # fmt: skip
    # Keys never contain personal data.
    assert all(
        "priya" not in n["key"].lower() and "reem" not in n["key"].lower() for n in graph["nodes"]
    )


async def test_identity_attributes_reuse_entities(api: httpx.AsyncClient, alice: Principal) -> None:
    first = (
        await post_fact(api, alice, entity_type="nationality", attribute="country", value="IND")
    ).json()
    again = await post_fact(
        api, alice, entity_type="nationality", attribute="country", value="India"
    )
    assert again.status_code == 200 and again.json()["node_id"] == first["node_id"]
    child_a = (
        await post_fact(api, alice, entity_type="child", attribute="full_name", value="Aarav")
    ).json()
    child_b = (
        await post_fact(api, alice, entity_type="child", attribute="full_name", value="Anya")
    ).json()
    assert child_a["node_id"] != child_b["node_id"]
    dob = await post_fact(
        api, alice, node_id=child_a["node_id"], attribute="date_of_birth", value="12/03/2018"
    )
    assert dob.json()["value"] == "2018-03-12"
    company = (
        await post_fact(
            api, alice, entity_type="company", attribute="name", value="Mehta Analytics"
        )
    ).json()
    activity = await post_fact(
        api, alice, entity_type="business_activity", parent_id=company["node_id"],
        attribute="description", value="Software development",
    )  # fmt: skip
    assert activity.status_code == 201


async def test_invalid_facts_are_rejected(api: httpx.AsyncClient, alice: Principal) -> None:
    def fact(entity_type: str, attribute: str, value: str) -> dict[str, str]:
        return {"entity_type": entity_type, "attribute": attribute, "value": value}

    cases = [
        (fact("passport", "passport_number", "Z1"), "unknown_attribute"),
        (fact("person", "date_of_birth", "someday"), "invalid_value"),
        (fact("business_activity", "description", "x"), "invalid_parent"),
        (fact("community_preference", "faith_community", "Hindu"), "consent_required"),
        ({"attribute": "occupation", "value": "Engineer"}, "invalid_target"),
    ]
    for body, code in cases:
        response = await post_fact(api, alice, **body)
        assert response.status_code == 400, body
        assert response.json()["code"] == code, response.json()


async def test_faith_only_after_opt_in(api: httpx.AsyncClient, alice: Principal) -> None:
    consent = await api.patch(
        "/api/me/preferences", json={"faith_personalization": "granted"}, headers=auth(alice)
    )
    assert consent.status_code == 200
    stated = await post_fact(
        api, alice, entity_type="community_preference", attribute="faith_community", value="Hindu"
    )
    assert stated.status_code == 201 and stated.json()["source"] == "user_stated"


async def test_correcting_a_user_statement_and_deleting_prunes(
    api: httpx.AsyncClient, alice: Principal
) -> None:
    fact = (
        await post_fact(api, alice, entity_type="spouse", attribute="full_name", value="Priya")
    ).json()
    patched = await api.patch(
        f"/api/graph/user/facts/{fact['id']}", json={"value": "Priya Mehta"}, headers=auth(alice)
    )
    assert patched.json()["value"] == "Priya Mehta" and not patched.json()["corrected"]
    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    assert any(n["label"] == "Priya Mehta" for n in graph["nodes"])
    assert (
        await api.delete(f"/api/graph/user/facts/{fact['id']}", headers=auth(alice))
    ).status_code == 204
    graph = (await api.get("/api/graph/user", headers=auth(alice))).json()
    assert [n["type"] for n in graph["nodes"]] == ["person"]
    assert graph["edges"] == []
    assert (
        await api.delete(f"/api/graph/user/facts/{fact['id']}", headers=auth(alice))
    ).status_code == 404


async def test_user_graph_is_invisible_to_other_users(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        change = await facts.add_fact(
            session, entity_type=E.SPOUSE, attribute="full_name", value="Priya"
        )
        await session.commit()
    async with app_db.user_session(bob) as session:
        graph = UserGraph(session)
        assert await graph.fact(change.fact.id) is None  # type: ignore[union-attr]
        unfiltered = (await session.execute(select(ExtractedFact))).scalars().all()
        user_nodes = (
            (await session.execute(select(GraphNode).where(GraphNode.graph_type == GraphType.USER)))
            .scalars()
            .all()
        )
    assert unfiltered == [] and user_nodes == []


async def test_database_rejects_cross_user_and_governance_references(
    app_db: Database, alice: Principal, bob: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        hub = await UserGraph(session).hub()
        document = UserDocument(
            tenant_id=alice.tenant_id, user_id=alice.user_id, kind="passport", filename="p.pdf",
            content_type="application/pdf", size_bytes=10, storage_key=f"{uuid4()}/{uuid4()}",
        )  # fmt: skip
        session.add(document)
        await session.commit()
        hub_id, document_id = hub.id, document.id
    async with app_db.public_session() as session:
        governance_id = (
            await session.execute(select(GraphNode.id).where(GraphNode.key == "document.passport"))
        ).scalar_one()

    def fact(owner: Principal, node_id: Any, **kw: Any) -> ExtractedFact:
        return ExtractedFact(
            tenant_id=owner.tenant_id, user_id=owner.user_id, node_id=node_id,
            attribute="full_name", value="X", confidence=1.0, source="user_stated", **kw,
        )  # fmt: skip

    async with app_db.user_session(alice) as session:
        session.add(fact(alice, governance_id))  # personal data on a public node
        with pytest.raises(DBAPIError, match="not part of this user's private graph"):
            await session.commit()
    async with app_db.user_session(bob) as session:
        bob_hub = await UserGraph(session).hub()
        await session.flush()
        session.add(fact(bob, bob_hub.id, source_document_id=document_id))  # Alice's document
        with pytest.raises(DBAPIError, match="does not belong to this user"):
            await session.commit()
    async with app_db.user_session(bob) as session:
        session.add(fact(bob, hub_id))  # Alice's node (forged ownership is RLS-denied too)
        with pytest.raises(DBAPIError):
            await session.commit()


async def test_database_invariants_on_facts(app_db: Database, alice: Principal) -> None:
    async with app_db.user_session(alice) as session:
        hub = await UserGraph(session).hub()
        await session.commit()
    base = {
        "tenant_id": alice.tenant_id, "user_id": alice.user_id, "node_id": hub.id,
        "attribute": "occupation", "confidence": 0.9,
    }  # fmt: skip
    bad = [
        {"value": None, "source": "user_stated", "status": "accepted"},  # accepted needs a value
        {"value": "X", "source": "document_extracted"},  # must cite a document + method
        {"value": "X", "source": "user_stated", "confidence": 1.5},
        {"value": "X", "source": "inferred", "attribute": "faith_community"},
    ]
    for case in bad:
        async with app_db.user_session(alice) as session:
            session.add(ExtractedFact(**{**base, **case}))
            with pytest.raises(IntegrityError):
                await session.commit()
    async with app_db.user_session(alice) as session:
        session.add(ExtractedFact(**base, value="A", source="user_stated"))
        await session.commit()
    async with app_db.user_session(alice) as session:
        session.add(ExtractedFact(**base, value="B", source="user_stated"))  # second accepted
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_user_nodes_cannot_carry_properties(
    owner_db: Database, app_db: Database, alice: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        hub = await UserGraph(session).hub()
        await session.commit()
    async with app_db.user_session(alice) as session:
        with pytest.raises(IntegrityError, match="user_nodes_have_no_properties"):
            await session.execute(
                text("UPDATE graph_nodes SET properties_json = '{\"x\": 1}' WHERE id = :id"),
                {"id": hub.id},
            )


async def test_every_private_table_has_an_owner_policy(owner_db: Database) -> None:
    async with owner_db.public_session() as session:
        rows = await session.execute(
            text(
                "SELECT tablename FROM pg_policies WHERE tablename IN "
                "('user_documents', 'extracted_facts', 'review_tasks') "
                "AND policyname = tablename || '_owner'"
            )
        )
    assert {r[0] for r in rows} == {"user_documents", "extracted_facts", "review_tasks"}


async def test_profile_projection_and_the_planner_contract(
    app_db: Database, alice: Principal
) -> None:
    async with app_db.user_session(alice) as session:
        graph = UserGraph(session)
        spouse = await facts.ensure_node(session, alice, E.SPOUSE)
        again = await facts.ensure_node(session, alice, "spouse")
        assert spouse.id == again.id and spouse.key == "spouse.self"
        written = await facts.upsert_user_stated(
            session, alice, node_id=spouse.id, source_ref="profile:household_members:1",
            facts={
                "full_name": TwinFact(value="Priya Mehta", source=FactSource.USER_STATED),
                "moving_with_user": TwinFact(value=True, source=FactSource.USER_STATED),
            },
        )  # fmt: skip
        assert {f.attribute for f in written} == {"full_name", "moving_with_user"}
        # Re-projection replaces what the same profile row said before.
        await facts.upsert_user_stated(
            session, alice, node_id=spouse.id, source_ref="profile:household_members:1",
            facts={"full_name": TwinFact(value="Priya Mehta", source=FactSource.USER_STATED)},
        )  # fmt: skip
        by_node = await facts.facts_for_nodes(session, [spouse.id])
        assert set(by_node[spouse.id]) == {"full_name"}
        stored = by_node[spouse.id]["full_name"]
        assert stored.id and stored.source is FactSource.USER_STATED and stored.confirmed_by_user
        planning = {p.key: p for p in await facts.planning_facts(session, alice)}
        assert planning["household.move_with_spouse"].source == "inferred"
        assert (await graph.by_key("spouse.self")) is not None
        await session.commit()


async def test_onboarding_profile_projects_into_the_user_graph(
    app_db: Database, alice: Principal
) -> None:
    from datetime import date

    from app.personalization.onboarding import project_profile
    from app.repositories import accounts, profile

    async def project() -> dict[str, dict[str, Any]]:
        async with app_db.user_session(alice) as session:
            user = await accounts.get_user(session, alice.user_id, alice.tenant_id)
            assert user is not None
            await project_profile(session, alice, await profile.load_bundle(session, alice, user))
            await session.commit()
            snapshot = await UserGraph(session).snapshot()
        out: dict[str, dict[str, Any]] = {}
        for fact in snapshot.facts:
            node = snapshot.nodes[fact.node_id]
            out.setdefault(f"{node.type.value}:{node.label}", {})[fact.attribute] = fact
        return out

    async with app_db.user_session(alice) as session:
        # A detail the person stated directly is more specific than the profile.
        await facts.add_fact(session, entity_type=E.PERSON, attribute="occupation", value="Founder")
        await profile.upsert_profile(
            session, alice,
            {"nationality": "IND", "date_of_birth": date(1990, 4, 12), "occupation": "Engineer",
             "monthly_income_aed": 32000, "arrival_date": date(2026, 11, 1),
             "languages": ["en", "hi"], "company_name": "Mehta Analytics",
             "assumptions": {"company.jurisdiction": "adgm"}},
        )  # fmt: skip
        await profile.replace_household(
            session, alice,
            [{"relationship": "spouse", "name": "Priya Mehta", "relocation_plan": "with_user"},
             {"relationship": "child", "name": "Aarav Mehta", "date_of_birth": date(2018, 3, 12)}],
        )  # fmt: skip
        await profile.replace_goals(
            session, alice, [{"goal_type": "establish_company", "title": "Open my consultancy"}]
        )
        await profile.replace_preferences(
            session, alice,
            [{"category": "housing", "key": "area", "value": "Al Reem Island"},
             {"category": "budget", "key": "monthly_housing_aed", "value": 12000}],
        )  # fmt: skip
        await session.commit()

    graph = await project()
    me = graph["person:You"]
    assert me["occupation"].value == "Founder" and me["occupation"].source_ref is None
    assert me["monthly_income"].value == {"amount": 32000.0, "currency": "AED"}
    assert me["date_of_birth"].source_ref.startswith("profile:user_profiles:")
    assert graph["nationality:India"]["country"].value == "IND"
    assert graph["spouse:Priya Mehta"]["moving_with_user"].value is True
    assert graph["child:Aarav Mehta"]["date_of_birth"].value == "2018-03-12"
    assert graph["goal:Start a company"]["kind"].value == "start_company"
    assert graph["company:Mehta Analytics"]["jurisdiction"].value == "adgm"
    assert graph["housing_preference:Housing in Al Reem Island"]["preferred_area"].value
    assert graph["budget:Housing budget"]["amount"].value == {"amount": 12000.0, "currency": "AED"}
    assert {"language:English", "language:Hindi"} <= set(graph)
    async with app_db.user_session(alice) as session:
        planning = {p.key: p for p in await facts.planning_facts(session, alice)}
    assert planning["household.move_with_spouse"].source == "user_stated"
    assert planning["company.jurisdiction"].value == "adgm"
    assert planning["household.children_count"].value == 1

    # The profile is canonical: re-projecting after removing the child removes it.
    async with app_db.user_session(alice) as session:
        spouse = {"relationship": "spouse", "name": "Priya Mehta"}
        await profile.replace_household(
            session, alice, [{**spouse, "relocation_plan": "not_relocating"}]
        )
        await session.commit()
    graph = await project()
    assert not any(key.startswith("child:") for key in graph)
    assert graph["spouse:Priya Mehta"]["moving_with_user"].value is False
