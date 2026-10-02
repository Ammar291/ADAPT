"""Private profile data the user states during onboarding (RLS owner-only)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Owned, Timestamps, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import (
    FactSource,
    GoalStatus,
    GoalType,
    HouseholdRelationship,
    PreferenceCategory,
    Priority,
    RelocationPlan,
)


class UserProfile(Base, UUIDPrimaryKey, Timestamps, Owned):
    """One row per user. Identity-document data (passport numbers etc.) never lives here."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
        CheckConstraint(
            "monthly_income_aed IS NULL OR monthly_income_aed >= 0", name="income_non_negative"
        ),
        CheckConstraint(
            "nationality IS NULL OR nationality ~ '^[A-Z]{3}$'", name="nationality_iso3"
        ),
    )

    preferred_name: Mapped[str | None] = mapped_column(String(120))
    nationality: Mapped[str | None] = mapped_column(String(3))  # ISO 3166-1 alpha-3
    country_of_residence: Mapped[str | None] = mapped_column(String(3))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    occupation: Mapped[str | None] = mapped_column(String(200))
    persona: Mapped[str | None] = mapped_column(
        String(40), doc="founder | employee | investor | student | family | retiree | other"
    )
    company_name: Mapped[str | None] = mapped_column(String(200))
    business_activity: Mapped[str | None] = mapped_column(String(300))
    monthly_income_aed: Mapped[int | None] = mapped_column(Integer)
    arrival_date: Mapped[date | None] = mapped_column(Date)
    target_city: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="Abu Dhabi"
    )
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(35)), nullable=False, server_default=text("'{}'")
    )
    assumptions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        doc="Planning assumptions the user chose, e.g. {'company.jurisdiction': 'adgm'}",
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HouseholdMember(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "household_members"
    __table_args__ = (
        enum_check("relationship", HouseholdRelationship),
        enum_check("relocation_plan", RelocationPlan),
        CheckConstraint(
            "nationality IS NULL OR nationality ~ '^[A-Z]{3}$'", name="nationality_iso3"
        ),
    )

    relationship: Mapped[HouseholdRelationship] = mapped_column(
        str_enum(HouseholdRelationship), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(3))
    relocation_plan: Mapped[RelocationPlan] = mapped_column(
        str_enum(RelocationPlan), nullable=False, server_default=RelocationPlan.UNDECIDED.value
    )
    arrival_date: Mapped[date | None] = mapped_column(Date)
    needs_sponsorship: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    graph_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL")
    )


class UserPreference(Base, UUIDPrimaryKey, Timestamps, Owned):
    """Personalisation preferences (housing, budget, community interests, ...).

    Faith preferences may only ever be stated by the user (CHECK below), and services
    additionally require the user's faith-personalisation opt-in before storing them.
    """

    __tablename__ = "user_preferences"
    __table_args__ = (
        enum_check("category", PreferenceCategory),
        enum_check("source", FactSource),
        UniqueConstraint("user_id", "category", "key", name="uq_user_preferences_user_key"),
        CheckConstraint(
            "category <> 'faith' OR source = 'user_stated'", name="faith_is_user_stated"
        ),
    )

    category: Mapped[PreferenceCategory] = mapped_column(
        str_enum(PreferenceCategory), nullable=False
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    source: Mapped[FactSource] = mapped_column(
        str_enum(FactSource), nullable=False, server_default=FactSource.USER_STATED.value
    )
    graph_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL")
    )


class UserGoal(Base, UUIDPrimaryKey, Timestamps, Owned):
    __tablename__ = "user_goals"
    __table_args__ = (
        enum_check("goal_type", GoalType),
        enum_check("status", GoalStatus),
        enum_check("priority", Priority),
    )

    goal_type: Mapped[GoalType] = mapped_column(str_enum(GoalType), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[GoalStatus] = mapped_column(
        str_enum(GoalStatus), nullable=False, server_default=GoalStatus.ACTIVE.value
    )
    priority: Mapped[Priority] = mapped_column(
        str_enum(Priority), nullable=False, server_default=Priority.MEDIUM.value
    )
    target_date: Mapped[date | None] = mapped_column(Date)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # The governance service this goal pursues (e.g. service.family_residence_visa).
    governance_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL")
    )
    graph_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="SET NULL")
    )
