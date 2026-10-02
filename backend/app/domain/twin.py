"""Private User Digital Twin: fact model and sensitive-attribute rules.

A twin node's `properties` is a map of attribute name -> `TwinFact`. Every fact records
where it came from, so the UI can show "you told us" vs "read from your passport" vs
"ADAPT inferred", and so the user can confirm or correct it.

Sensitive attributes (faith, ethnicity, health, ...) may only ever be *stated by the
user*, and only after they opted in. ADAPT never infers them — in particular, never from
nationality, ethnicity, language or name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import ConsentStatus, FactSource

SENSITIVE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "religion",
        "faith",
        "faith_community",
        "religious_practice",
        "ethnicity",
        "caste",
        "sexual_orientation",
        "political_opinion",
        "health_condition",
        "disability",
    }
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TwinFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: JsonValue
    source: FactSource
    source_ref: str | None = Field(
        default=None,
        max_length=200,
        description="Pointer to the origin, e.g. 'document:<uuid>' or 'conversation:<turn-id>'",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confirmed_by_user: bool = False
    observed_at: datetime = Field(default_factory=_utcnow)


class SensitiveAttributeError(ValueError):
    pass


def validate_twin_facts(
    facts: dict[str, TwinFact], *, faith_consent: ConsentStatus = ConsentStatus.NOT_ASKED
) -> None:
    """Raise `SensitiveAttributeError` if a sensitive attribute breaks the rules."""
    for name, fact in facts.items():
        attribute = name.strip().casefold().replace("-", "_").replace(" ", "_")
        if attribute not in SENSITIVE_ATTRIBUTES:
            continue
        if fact.source is not FactSource.USER_STATED:
            raise SensitiveAttributeError(
                f"'{name}' is sensitive and may only be stated by the user "
                f"(got source={fact.source.value}); ADAPT never infers it"
            )
        if attribute in {"religion", "faith", "faith_community", "religious_practice"} and (
            faith_consent is not ConsentStatus.GRANTED
        ):
            raise SensitiveAttributeError(
                f"'{name}' requires the user to opt in to faith personalisation first"
            )


class TwinFactSet(BaseModel):
    """Validated container used when writing twin node properties."""

    facts: dict[str, TwinFact]
    faith_consent: ConsentStatus = ConsentStatus.NOT_ASKED

    @model_validator(mode="after")
    def _rules(self) -> TwinFactSet:
        validate_twin_facts(self.facts, faith_consent=self.faith_consent)
        return self

    def to_properties(self) -> dict[str, Any]:
        return {name: fact.model_dump(mode="json") for name, fact in self.facts.items()}
