"""Extension points other workstreams register at import time.

`document_reviewed_listeners`: `async fn(principal, document_id)` called after a person
finishes reviewing a document (its last open review task was resolved), outside the
database transaction. The journey agent uses it to resume a run paused at its
document-correction gate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.domain.principal import Principal

DocumentReviewedListener = Callable[[Principal, UUID], Awaitable[None]]

document_reviewed_listeners: list[DocumentReviewedListener] = []
