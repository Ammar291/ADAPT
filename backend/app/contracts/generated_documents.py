"""Documents ADAPT drafts for the user (letters, emails, checklists, appointment briefs).

Drafts are never used or sent until the user approves them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.contracts.common import ApiModel
from app.domain.enums import GeneratedDocumentKind, GeneratedDocumentStatus
from app.domain.provenance import Provenance


class GeneratedDocumentOut(ApiModel):
    id: UUID
    kind: GeneratedDocumentKind
    title: str
    body_markdown: str
    status: GeneratedDocumentStatus
    journey_id: UUID | None = None
    journey_node_id: UUID | None = None
    run_id: UUID | None = None
    provenance: Provenance
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None


class UpdateGeneratedDocumentRequest(ApiModel):
    body_markdown: str = Field(min_length=1, max_length=50_000, description="The edited text")


class ApproveGeneratedDocumentRequest(ApiModel):
    body_markdown: str | None = Field(
        default=None,
        max_length=50_000,
        description="Final text, if the user edited the draft before approving it",
    )
