"""`/api/demo/scenarios*`: the demo-scenario kit.

Only available where demo sign-in is enabled (never in production, see config). It serves
scripted inputs and synthetic documents; it creates nothing and needs no session.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Response

from app.api.deps import ContainerDep
from app.core.errors import NotFound
from app.demo_scenarios import founder_arrival
from app.demo_scenarios.contracts import DemoScenarioOut, DemoScenarioSummary
from app.demo_scenarios.documents import BY_KEY

router = APIRouter(prefix="/demo/scenarios", tags=["demo"])

SCENARIOS: dict[str, Callable[[str], DemoScenarioOut]] = {
    founder_arrival.KEY: founder_arrival.definition,
}


def _enabled(container: ContainerDep) -> str:
    if not container.settings.demo_auth_enabled:
        raise NotFound("Demo scenarios are not available here")
    return container.settings.api_prefix


@router.get("", response_model=list[DemoScenarioSummary], summary="Demo scenarios")
async def list_scenarios(container: ContainerDep) -> list[DemoScenarioSummary]:
    prefix = _enabled(container)
    return [
        DemoScenarioSummary(key=s.key, title=s.title, tagline=s.tagline)
        for s in (build(prefix) for build in SCENARIOS.values())
    ]


@router.get("/{key}", response_model=DemoScenarioOut, summary="One demo scenario's script")
async def get_scenario(key: str, container: ContainerDep) -> DemoScenarioOut:
    prefix = _enabled(container)
    if key not in SCENARIOS:
        raise NotFound("No such demo scenario")
    return SCENARIOS[key](prefix)


@router.get(
    "/{key}/documents/{document}",
    summary="A synthetic document of a demo scenario (PDF)",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def scenario_document(key: str, document: str, container: ContainerDep) -> Response:
    _enabled(container)
    if key not in SCENARIOS or document not in BY_KEY:
        raise NotFound("No such demo document")
    doc = BY_KEY[document]
    return Response(
        content=doc.build(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )
