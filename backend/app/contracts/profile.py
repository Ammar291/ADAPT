"""Onboarding and profile: what the user tells ADAPT about themselves and their household.

Everything here is user-stated. Identity-document data (passport numbers, document
contents) is never part of the profile — it lives with the documents and their facts.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, JsonValue, field_validator

from app.contracts.auth import UserOut, UserPreferencesUpdate
from app.contracts.common import ApiModel
from app.domain.enums import (
    FactSource,
    GoalStatus,
    GoalType,
    HouseholdRelationship,
    PreferenceCategory,
    Priority,
    RelocationPlan,
)

Persona = str  # founder | employee | investor | student | family | retiree | other
PERSONAS: frozenset[str] = frozenset(
    {"founder", "employee", "investor", "student", "family", "retiree", "other"}
)


def _iso3(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("use an ISO 3166-1 alpha-3 country code, e.g. 'IND'")
    return code


class ProfileFields(ApiModel):
    preferred_name: str | None = Field(default=None, max_length=120)
    nationality: str | None = Field(default=None, description="ISO 3166-1 alpha-3")
    country_of_residence: str | None = Field(default=None, description="ISO 3166-1 alpha-3")
    date_of_birth: date | None = None
    occupation: str | None = Field(default=None, max_length=200)
    persona: Persona | None = Field(
        default=None,
        description="founder | employee | investor | student | family | retiree | other",
    )
    company_name: str | None = Field(default=None, max_length=200)
    business_activity: str | None = Field(default=None, max_length=300)
    monthly_income_aed: int | None = Field(default=None, ge=0)
    arrival_date: date | None = None
    target_city: str | None = Field(default=None, max_length=100)
    languages: list[str] | None = Field(default=None, max_length=10)
    assumptions: dict[str, JsonValue] | None = Field(
        default=None,
        description="Planning assumptions, e.g. {'company.jurisdiction': 'adgm'}",
    )

    @field_validator("nationality", "country_of_residence")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        return _iso3(value)

    @field_validator("persona")
    @classmethod
    def _persona(cls, value: str | None) -> str | None:
        if value is not None and value not in PERSONAS:
            raise ValueError(f"persona must be one of {sorted(PERSONAS)}")
        return value


class ProfileOut(ProfileFields):
    target_city: str | None = "Abu Dhabi"
    languages: list[str] | None = Field(default_factory=list)
    assumptions: dict[str, JsonValue] | None = Field(default_factory=dict)
    onboarding_completed_at: datetime | None = None
    updated_at: datetime | None = None


class HouseholdMemberIn(ApiModel):
    relationship: HouseholdRelationship
    name: str = Field(min_length=1, max_length=120, description="How the user refers to them")
    date_of_birth: date | None = None
    nationality: str | None = None
    relocation_plan: RelocationPlan = RelocationPlan.UNDECIDED
    arrival_date: date | None = None
    needs_sponsorship: bool = True
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("nationality")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        return _iso3(value)


class HouseholdMemberOut(HouseholdMemberIn):
    id: UUID
    position: int
    graph_node_id: UUID | None = None


class UserGoalIn(ApiModel):
    goal_type: GoalType
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority = Priority.MEDIUM
    status: GoalStatus = GoalStatus.ACTIVE
    target_date: date | None = None
    service_key: str | None = Field(
        default=None,
        description="Governance service the goal pursues, e.g. 'service.family_residence_visa'",
    )


class UserGoalOut(ApiModel):
    id: UUID
    goal_type: GoalType
    title: str
    description: str | None = None
    priority: Priority
    status: GoalStatus
    target_date: date | None = None
    service_key: str | None = None
    governance_node_id: UUID | None = None
    graph_node_id: UUID | None = None


class UserPreferenceIn(ApiModel):
    category: PreferenceCategory
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    value: JsonValue


class UserPreferenceOut(UserPreferenceIn):
    id: UUID
    source: FactSource


class OnboardingProfileRequest(ApiModel):
    """Complete onboarding in one call. Household, goals and preferences replace any
    previous answers; the user graph is rebuilt from them in the same transaction."""

    display_name: str | None = Field(default=None, max_length=120)
    profile: ProfileFields = Field(default_factory=ProfileFields)
    household: list[HouseholdMemberIn] = Field(default_factory=list, max_length=20)
    goals: list[UserGoalIn] = Field(default_factory=list, max_length=20)
    preferences: list[UserPreferenceIn] = Field(default_factory=list, max_length=50)
    consents: UserPreferencesUpdate | None = None


class ProfileUpdate(ApiModel):
    """Partial update. Omitted fields are unchanged; a provided list replaces the set."""

    display_name: str | None = Field(default=None, max_length=120)
    profile: ProfileFields | None = None
    household: list[HouseholdMemberIn] | None = Field(default=None, max_length=20)
    goals: list[UserGoalIn] | None = Field(default=None, max_length=20)
    preferences: list[UserPreferenceIn] | None = Field(default=None, max_length=50)
    consents: UserPreferencesUpdate | None = None


class ProfileCompleteness(ApiModel):
    complete: bool
    missing: list[str] = Field(description="Profile fields ADAPT still needs for planning")


class FullProfileOut(ApiModel):
    user: UserOut
    profile: ProfileOut
    household: list[HouseholdMemberOut]
    goals: list[UserGoalOut]
    preferences: list[UserPreferenceOut]
    completeness: ProfileCompleteness


def profile_values(fields: ProfileFields) -> dict[str, Any]:
    """Only the fields the caller actually sent."""
    return fields.model_dump(exclude_unset=True, mode="python")
