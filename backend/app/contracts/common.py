"""Base types for API contracts.

Every model in `app.contracts` is exported to TypeScript (`packages/contracts`) through
the OpenAPI document, so keep them JSON-friendly and free of business logic.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=False,
        # Response fields with defaults are always serialised, so mark them required in the
        # serialization-mode JSON schema (gives non-optional TypeScript properties).
        json_schema_serialization_defaults_required=True,
    )


class FieldError(ApiModel):
    loc: list[str]
    message: str
    type: str


class ProblemDetail(ApiModel):
    """RFC 9457 problem details. `code` is stable and machine-readable."""

    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[FieldError] | None = None
    extra: dict[str, Any] | None = None
