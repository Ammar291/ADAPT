"""Private user graph routes (the person's digital twin). Owner-only, RLS-scoped.

The shared governance graph has its own public routes; nothing here is reachable without
the owner's session, and nothing here is cached.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import PrincipalDep, UserSession
from app.contracts.user_graph import (
    FactEvidenceOut,
    FactExplainRequest,
    PersonalisationView,
    UserFactCreate,
    UserFactOut,
    UserFactUpdate,
    UserGraphSchema,
    UserGraphView,
)
from app.core.errors import BadRequest, NotFound
from app.personalization import facts, review
from app.personalization.presenters import (
    evidence_out,
    facts_out,
    personalisation_out,
    schema_out,
    user_graph_view,
)
from app.personalization.projection import evidence
from app.personalization.projection import planning_facts as project
from app.personalization.store import UserGraph
from app.personalization.vocabulary import FactRuleError, UserEntityType

router = APIRouter(tags=["user graph"])


def _bad_request(exc: FactRuleError) -> BadRequest:
    return BadRequest(str(exc), code=exc.code)


async def _fact_out(session: UserSession, fact_id: UUID) -> UserFactOut:
    fact = await UserGraph(session).fact(fact_id)
    if fact is None:
        raise NotFound("That fact is not in your twin")
    [out] = await facts_out(session, [fact])
    return out


@router.get("/graph/user", response_model=UserGraphView, summary="Your private digital twin")
async def get_user_graph(session: UserSession) -> UserGraphView:
    await UserGraph(session).hub()
    view = await user_graph_view(session)
    await session.commit()
    return view


@router.get(
    "/graph/user/schema",
    response_model=UserGraphSchema,
    summary="What ADAPT can record in your twin (entities, attributes, options)",
)
async def get_user_graph_schema(_: PrincipalDep) -> UserGraphSchema:
    return schema_out()


@router.post(
    "/graph/user/facts",
    response_model=UserFactOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tell ADAPT something about yourself",
    responses={200: {"description": "An existing fact was updated", "model": UserFactOut}},
)
async def create_fact(
    body: UserFactCreate, principal: PrincipalDep, session: UserSession, response: Response
) -> UserFactOut:
    try:
        change = await facts.add_fact(
            session,
            attribute=body.attribute,
            value=body.value,
            node_id=body.node_id,
            entity_type=UserEntityType(body.entity_type.value) if body.entity_type else None,
            parent_id=body.parent_id,
        )
    except FactRuleError as exc:
        raise _bad_request(exc) from exc
    assert change.fact is not None
    fact_id = change.fact.id
    await session.commit()
    await review.notify_reviewed(principal, change.reviewed_documents or [])
    if not change.created:
        response.status_code = status.HTTP_200_OK
    return await _fact_out(session, fact_id)


@router.patch(
    "/graph/user/facts/{fact_id}",
    response_model=UserFactOut,
    summary="Confirm or correct a fact",
)
async def update_fact(
    fact_id: UUID, body: UserFactUpdate, principal: PrincipalDep, session: UserSession
) -> UserFactOut:
    try:
        change = await facts.update_fact(session, fact_id, value=body.value, confirm=body.confirm)
    except FactRuleError as exc:
        raise _bad_request(exc) from exc
    await session.commit()
    await review.notify_reviewed(principal, change.reviewed_documents or [])
    return await _fact_out(session, fact_id)


@router.delete(
    "/graph/user/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a fact (or reject a proposed one)",
)
async def delete_fact(fact_id: UUID, principal: PrincipalDep, session: UserSession) -> Response:
    change = await facts.delete_fact(session, fact_id)
    await session.commit()
    await review.notify_reviewed(principal, change.reviewed_documents or [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/graph/user/personalisation",
    response_model=PersonalisationView,
    summary="What ADAPT takes into account when planning, and why",
)
async def get_personalisation(session: UserSession) -> PersonalisationView:
    snapshot = await UserGraph(session).snapshot()
    planning = project(snapshot)
    ids = {i for p in planning for i in p.fact_ids}
    return personalisation_out(planning, {e.fact_id: e for e in evidence(snapshot, ids)})


@router.post(
    "/graph/user/explain",
    response_model=list[FactEvidenceOut],
    summary="Explain which of your details a recommendation used",
)
async def explain_facts(body: FactExplainRequest, session: UserSession) -> list[FactEvidenceOut]:
    return [evidence_out(item) for item in await facts.explain(session, body.fact_ids)]
