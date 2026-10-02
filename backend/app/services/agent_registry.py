"""Registry of agents that `POST /api/agents/run` can start.

Each agent workstream registers its agents when its module is imported (the API router
imports feature routers, the worker imports feature jobs):

    register_agent(AgentSpec(name="journey", kind=RunKind.JOURNEY, job="run_journey",
                             input_model=StartJourneyInput, description="..."))

The API validates the request `input` against `input_model` and enqueues `job` with
`run_id`, `user_id`, `tenant_id` and the validated input fields as keyword arguments.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.core.errors import NotFound
from app.domain.enums import RunKind


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    kind: RunKind
    job: str
    input_model: type[BaseModel]
    description: str


_REGISTRY: dict[str, AgentSpec] = {}


def register_agent(spec: AgentSpec) -> AgentSpec:
    _REGISTRY[spec.name] = spec
    return spec


def get_agent(name: str) -> AgentSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise NotFound(f"No agent named '{name}'", code="unknown_agent") from None


def list_agents() -> list[AgentSpec]:
    return sorted(_REGISTRY.values(), key=lambda spec: spec.name)


DIAGNOSTIC = register_agent(
    AgentSpec(
        name="diagnostic",
        kind=RunKind.DIAGNOSTIC,
        job="run_diagnostic",
        input_model=NoInput,
        description="Checks the whole agent pipeline end to end, using public data only.",
    )
)
