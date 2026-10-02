"""Wire shapes of the demo-scenario kit (`/api/demo/scenarios*`).

A scenario is a script of fixed inputs to the real public API. The presenter page and the
rehearsal script both read it from here, so they always run exactly the same sequence.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.contracts.common import ApiModel
from app.contracts.profile import OnboardingProfileRequest

ScenarioRole = Literal[
    "company",
    "residence",
    "document",
    "family",
    "appointment",
    "official_handoff",
    "missing_information",
]


class ScenarioFact(ApiModel):
    label: str
    value: str
    source: Literal["stated", "document", "missing"] = Field(
        description="Whether the persona states it during onboarding, a document supplies "
        "it, or nobody gives it (ADAPT must ask rather than guess)"
    )


class ScenarioPersonaOut(ApiModel):
    name: str
    headline: str
    summary: str
    facts: list[ScenarioFact]


class ScenarioDocumentOut(ApiModel):
    key: str
    kind: str = Field(description="The document kind sent with the upload")
    title: str
    filename: str
    url: str = Field(description="The synthetic PDF, served by this kit")
    reads: list[str] = Field(description="What the reader should find on it")
    changes: str = Field(description="What it changes in the plan")
    confirm: bool = Field(
        default=True,
        description="The persona confirms what was read (POST /documents/{id}/review)",
    )


class ScenarioJourneyIn(ApiModel):
    """The body for POST /journey (document ids are added by the client)."""

    prompt: str
    language: str = "en"
    channel: Literal["text"] = "text"
    deterministic: bool = True


class ScenarioResearchIn(ApiModel):
    """The body for POST /research (the journey id is added by the client)."""

    mode: Literal["snapshot"] = "snapshot"


class ScenarioResearchGroup(ApiModel):
    key: str
    title: str
    categories: list[str]
    description: str


class ScenarioRoleOut(ApiModel):
    role: ScenarioRole
    label: str
    task_key: str = Field(description="The journey node key this role is shown on")
    note: str


class ScenarioChange(ApiModel):
    key: str
    value: Any


class ScenarioWhatIfOut(ApiModel):
    key: str
    title: str
    description: str
    changes: list[ScenarioChange]


class ScenarioActOut(ApiModel):
    key: str
    title: str
    description: str


class DemoScenarioSummary(ApiModel):
    key: str
    title: str
    tagline: str


class DemoScenarioOut(DemoScenarioSummary):
    synthetic_notice: str
    persona: ScenarioPersonaOut
    onboarding: OnboardingProfileRequest = Field(
        description="The body for POST /onboarding/profile"
    )
    documents: list[ScenarioDocumentOut]
    journey: ScenarioJourneyIn
    research: ScenarioResearchIn
    research_groups: list[ScenarioResearchGroup]
    roles: list[ScenarioRoleOut]
    what_if: ScenarioWhatIfOut
    acts: list[ScenarioActOut]
