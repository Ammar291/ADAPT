"""Worker job: read one uploaded document for its owner (ARQ function `process_document`)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import update

from app.core.errors import AppError
from app.db.models.user_data import UserDocument
from app.documents.catalogue import DocumentStatus
from app.documents.pipeline import DocumentPipeline
from app.domain.enums import RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import RunEventEmitter
from app.personalization import review
from app.personalization.facts_model import ReviewTaskKind
from app.repositories.runs import get_run

logger = logging.getLogger(__name__)
AGENT = "document_intelligence"


async def process_document(
    ctx: dict[str, Any], *, run_id: str, user_id: str, tenant_id: str, document_id: str
) -> str:
    deps = ctx["deps"]
    principal = Principal.from_job_args(user_id, tenant_id)
    async with deps.db.user_session(principal) as session:
        run = await get_run(session, UUID(run_id))
    if run is None or run.kind is not RunKind.DOCUMENT_EXTRACTION:
        logger.warning("job_run_not_found", extra={"run_id": run_id})
        return "skipped"
    if run.status is not RunStatus.QUEUED:
        return "skipped"

    events = RunEventEmitter(deps.db, principal, run.id, deps.notifier)
    await events.run_started(RunKind.DOCUMENT_EXTRACTION, agent=AGENT)
    pipeline = DocumentPipeline(deps.db, principal, deps.adapters, events=events, own_run=True)
    try:
        # Not forced: upload and reprocess set the document to `uploaded` before queueing
        # this job, so a document already claimed (e.g. by a journey that needed it first)
        # or already read returns its result instead of being read twice.
        analysis = await pipeline.run(UUID(document_id))
    except Exception as exc:
        # Never leave a real upload stuck in "processing": it goes to the person for review.
        logger.exception("document_pipeline_failed", extra={"document_id": document_id})
        await _needs_review(deps, principal, UUID(document_id))
        code, message = (
            (exc.code, exc.detail or exc.title)
            if isinstance(exc, AppError)
            else ("document_error", "The document could not be processed automatically")
        )
        await events.run_failed(code, message, retryable=True)
        return "failed"

    to_check = len(analysis.review_task_ids)
    summary = (
        f"{len(analysis.facts)} details read; {to_check} to check"
        if analysis.facts
        else "Couldn't read this document automatically. It needs your review"
    )
    await events.run_completed(summary=summary)
    return analysis.status.value


async def _needs_review(deps: Any, principal: Principal, document_id: UUID) -> None:
    try:
        async with deps.db.user_session(principal) as session:
            await session.execute(
                update(UserDocument)
                .where(
                    UserDocument.id == document_id,
                    UserDocument.user_id == principal.user_id,
                    UserDocument.status.in_([DocumentStatus.UPLOADED, DocumentStatus.PROCESSING]),
                )
                .values(
                    status=DocumentStatus.NEEDS_REVIEW,
                    status_reason="We couldn't read this document automatically",
                )
            )
            await review.open_task(
                session,
                principal,
                kind=ReviewTaskKind.EXTRACTION_FAILED,
                message="We couldn't read this document automatically. Check it and add the "
                "details yourself, or try reading it again.",
                document_id=document_id,
            )
            await session.commit()
    except Exception:
        logger.exception("document_fallback_failed", extra={"document_id": str(document_id)})
