"""Uploaded documents, what was read from them, and review tasks.

Document bytes are never part of these contracts: they are served from a separate
endpoint behind the session *and* a short-lived signed URL (`content_url`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, JsonValue

from app.contracts.common import ApiModel
from app.contracts.user_graph import UserFactOut
from app.documents.catalogue import DocumentKind, DocumentStatus, DocumentSubject
from app.personalization.facts_model import (
    ReviewResolution,
    ReviewTaskKind,
    ReviewTaskStatus,
)


class ExtractedFieldOut(ApiModel):
    name: str = Field(description="Canonical field name, e.g. 'date_of_birth'")
    label: str
    value: JsonValue | None = None
    value_display: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool
    fact_id: UUID | None = Field(default=None, description="Edit or confirm via the fact")
    issues: list[str] = Field(default_factory=list)


class DocumentOut(ApiModel):
    id: UUID
    kind: DocumentKind
    kind_label: str
    declared_kind: DocumentKind | None = None
    subject: DocumentSubject
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    status_reason: str | None = None
    extraction_method: str | None = Field(
        default=None, description="How it was read, e.g. 'local:pdf-text+mrz' or 'openai:<model>'"
    )
    mrz_verified: bool | None = Field(
        default=None, description="Machine-readable zone check digits verified (passports, IDs)"
    )
    open_review_tasks: int
    extraction_run_id: UUID | None = None
    events_url: str | None = Field(
        default=None, description="Live processing progress (SSE) while the run is active"
    )
    created_at: datetime
    processed_at: datetime | None = None


class ReviewTaskOut(ApiModel):
    id: UUID
    kind: ReviewTaskKind
    status: ReviewTaskStatus
    resolution: ReviewResolution | None = None
    message: str
    field: str | None = None
    document_id: UUID | None = None
    document_kind: DocumentKind | None = None
    fact: UserFactOut | None = Field(
        default=None,
        description="Confirm with PATCH, correct with PATCH {value}, reject with DELETE",
    )
    created_at: datetime
    resolved_at: datetime | None = None


class DocumentDetailOut(DocumentOut):
    fields: list[ExtractedFieldOut]
    facts: list[UserFactOut] = Field(description="Everything in your twin read from this document")
    review_tasks: list[ReviewTaskOut]
    warnings: list[str] = Field(default_factory=list)
    content_url: str = Field(description="Signed, short-lived link to view the file (no-store)")


class DocumentProcessRequest(ApiModel):
    kind: DocumentKind | None = Field(
        default=None, description="Correct the document type before reading it again"
    )


class FieldCorrection(ApiModel):
    name: str = Field(description="Field name from `fields`, e.g. 'date_of_birth'")
    value: JsonValue | None = Field(description="The right value, or null to remove it")


class DocumentReviewRequest(ApiModel):
    """Review a document in one step: apply corrections, then (by default) confirm the rest."""

    corrections: list[FieldCorrection] = Field(default_factory=list, max_length=50)
    confirm: bool = True
