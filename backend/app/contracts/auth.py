from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.contracts.common import ApiModel
from app.domain.enums import ConsentStatus


class UserPreferences(ApiModel):
    """User-controlled personalisation. Faith personalisation is strictly opt-in."""

    preferred_language: str = Field(default="en", description="BCP-47 tag for conversation")
    ui_locale: str = Field(default="en", description="BCP-47 tag for the interface")
    faith_personalization: ConsentStatus = ConsentStatus.NOT_ASKED
    community_personalization: ConsentStatus = ConsentStatus.NOT_ASKED
    voice_transcripts_retained: bool = False


class UserPreferencesUpdate(ApiModel):
    preferred_language: str | None = Field(default=None, max_length=35)
    ui_locale: str | None = Field(default=None, max_length=35)
    faith_personalization: ConsentStatus | None = None
    community_personalization: ConsentStatus | None = None
    voice_transcripts_retained: bool | None = None


class UserOut(ApiModel):
    id: UUID
    tenant_id: UUID
    display_name: str | None
    is_demo: bool
    preferences: UserPreferences
    created_at: datetime


class SessionOut(ApiModel):
    user: UserOut
    expires_at: datetime


class DemoSessionRequest(ApiModel):
    display_name: str | None = Field(default=None, max_length=120)
    ui_locale: str | None = Field(default=None, max_length=35)
    sample_household: bool = Field(
        default=False,
        description="Sign in to the seeded, fictional demo household instead of a fresh "
        "private account (development and demos only; shared by everyone who uses it)",
    )
