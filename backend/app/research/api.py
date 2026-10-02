"""Research routes. Thin: authenticate, call the service, return contracts.

`POST /research` returns 202 as soon as the job is queued. Progress streams on the run's
event stream (`research_*` events); the finished brief is read from `GET /discover`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ContainerDep, PrincipalDep
from app.research import service
from app.research.contracts import (
    AddToJourneyRequest,
    DiscoverOut,
    ResearchJobDetail,
    ResearchJobOut,
    ResearchJobStarted,
    ResearchResultOut,
    SaveResultRequest,
    StartResearchRequest,
)

router = APIRouter(tags=["research"])


@router.post(
    "/research",
    response_model=ResearchJobStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start background research for the signed-in user",
    description="Queues research and returns immediately. While a job is queued or running "
    "the same job is returned (unless `force`). Returns 409 `consent_required` (with "
    "`extra.consent`) when the request explicitly asks for faith or community "
    "personalisation the user hasn't agreed to.",
)
async def start_research(
    body: StartResearchRequest, principal: PrincipalDep, container: ContainerDep
) -> ResearchJobStarted:
    job = await service.start_research(
        container.db,
        container.queue,
        principal,
        body,
        adapters=container.adapters,
        api_prefix=container.settings.api_prefix,
    )
    return ResearchJobStarted(job=job, events_url=job.events_url)


@router.get("/research", response_model=list[ResearchJobOut], summary="Research jobs, newest first")
async def list_research(
    principal: PrincipalDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[ResearchJobOut]:
    return await service.list_jobs(
        container.db, principal, limit=limit, api_prefix=container.settings.api_prefix
    )


@router.get(
    "/research/{job_id}", response_model=ResearchJobDetail, summary="A research job and its results"
)
async def get_research(
    job_id: UUID, principal: PrincipalDep, container: ContainerDep
) -> ResearchJobDetail:
    return await service.get_job_detail(
        container.db, principal, job_id, api_prefix=container.settings.api_prefix
    )


@router.post(
    "/research/{job_id}/seen",
    response_model=ResearchJobOut,
    summary="Mark the Life Brief notification as seen",
)
async def mark_research_seen(
    job_id: UUID, principal: PrincipalDep, container: ContainerDep
) -> ResearchJobOut:
    return await service.mark_seen(
        container.db, principal, job_id, api_prefix=container.settings.api_prefix
    )


@router.patch(
    "/research/results/{result_id}",
    response_model=ResearchResultOut,
    summary="Save or unsave a research result",
)
async def save_result(
    result_id: UUID, body: SaveResultRequest, principal: PrincipalDep, container: ContainerDep
) -> ResearchResultOut:
    return await service.set_saved(container.db, principal, result_id, body.saved)


@router.post(
    "/research/results/{result_id}/journey",
    response_model=ResearchResultOut,
    summary="Add a research result to the journey",
    description="Returns 409 `journey_required` when the user has no journey yet.",
)
async def add_result_to_journey(
    result_id: UUID, body: AddToJourneyRequest, principal: PrincipalDep, container: ContainerDep
) -> ResearchResultOut:
    return await service.add_to_journey(container.db, principal, result_id, body.journey_id)


@router.get(
    "/discover",
    response_model=DiscoverOut,
    tags=["discover"],
    summary="The latest Life Brief, grouped into Discover sections",
)
async def discover(principal: PrincipalDep, container: ContainerDep) -> DiscoverOut:
    return await service.discover(container.db, principal, api_prefix=container.settings.api_prefix)
