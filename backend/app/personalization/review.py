"""Review tasks: what a person needs to check before ADAPT relies on it.

A task is opened for every fact read with low confidence (or failing validation), for a
value that conflicts with the twin, for a document nothing could be read from, and for a
document that doesn't look like what the person said it was. Resolving the fact (confirm,
correct, reject) resolves its task. Document status follows the open tasks:
needs_review while any is open, then confirmed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_data import ExtractedFact, ReviewTask, UserDocument
from app.documents import hooks
from app.documents.catalogue import DocumentStatus
from app.domain.principal import Principal
from app.personalization.facts_model import ReviewResolution, ReviewTaskKind, ReviewTaskStatus

logger = logging.getLogger(__name__)

SETTLED = frozenset(
    {DocumentStatus.EXTRACTED, DocumentStatus.NEEDS_REVIEW, DocumentStatus.CONFIRMED}
)


async def open_task(
    session: AsyncSession,
    principal: Principal,
    *,
    kind: ReviewTaskKind,
    message: str,
    document_id: UUID | None = None,
    fact_id: UUID | None = None,
    field: str | None = None,
) -> ReviewTask:
    if fact_id is not None:  # one open task per fact: supersede an older one
        await resolve_fact_tasks(session, principal, fact_id, ReviewResolution.SUPERSEDED)
    task = ReviewTask(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        kind=kind,
        message=message[:1000],
        document_id=document_id,
        fact_id=fact_id,
        field=field,
    )
    session.add(task)
    await session.flush()
    return task


async def _resolve(
    session: AsyncSession,
    principal: Principal,
    where: ColumnElement[bool],
    resolution: ReviewResolution,
) -> list[UUID]:
    status = (
        ReviewTaskStatus.DISMISSED
        if resolution in (ReviewResolution.DISMISSED, ReviewResolution.SUPERSEDED)
        else ReviewTaskStatus.RESOLVED
    )
    rows = await session.execute(
        update(ReviewTask)
        .where(
            ReviewTask.user_id == principal.user_id,
            ReviewTask.status == ReviewTaskStatus.OPEN,
            where,
        )
        .values(status=status, resolution=resolution, resolved_at=datetime.now(UTC))
        .returning(ReviewTask.document_id)
    )
    return [d for d in rows.scalars() if d is not None]


async def resolve_fact_tasks(
    session: AsyncSession, principal: Principal, fact_id: UUID, resolution: ReviewResolution
) -> list[UUID]:
    """Close the fact's open task; returns affected document ids."""
    return await _resolve(session, principal, ReviewTask.fact_id == fact_id, resolution)


async def supersede_document_tasks(
    session: AsyncSession, principal: Principal, document_id: UUID
) -> None:
    await _resolve(
        session, principal, ReviewTask.document_id == document_id, ReviewResolution.SUPERSEDED
    )


async def dismiss_task(session: AsyncSession, principal: Principal, task_id: UUID) -> list[UUID]:
    return await _resolve(session, principal, ReviewTask.id == task_id, ReviewResolution.DISMISSED)


async def open_tasks(
    session: AsyncSession, principal: Principal, *, document_id: UUID | None = None
) -> list[ReviewTask]:
    query = select(ReviewTask).where(
        ReviewTask.user_id == principal.user_id, ReviewTask.status == ReviewTaskStatus.OPEN
    )
    if document_id is not None:
        query = query.where(ReviewTask.document_id == document_id)
    return list((await session.execute(query.order_by(ReviewTask.created_at))).scalars())


async def refresh_document_status(
    session: AsyncSession, principal: Principal, document_ids: Iterable[UUID | None]
) -> list[UUID]:
    """Recompute review-driven statuses; returns documents whose review just finished."""
    finished: list[UUID] = []
    for document_id in {d for d in document_ids if d is not None}:
        document = (
            await session.execute(
                select(UserDocument).where(
                    UserDocument.user_id == principal.user_id, UserDocument.id == document_id
                )
            )
        ).scalar_one_or_none()
        if document is None or document.status not in SETTLED:
            continue
        open_count = (
            await session.execute(
                select(func.count()).where(
                    ReviewTask.user_id == principal.user_id,
                    ReviewTask.document_id == document_id,
                    ReviewTask.status == ReviewTaskStatus.OPEN,
                )
            )
        ).scalar_one()
        facts = (
            await session.execute(
                select(ExtractedFact.confirmed_by_user).where(
                    ExtractedFact.user_id == principal.user_id,
                    ExtractedFact.source_document_id == document_id,
                )
            )
        ).scalars()
        confirmations = list(facts)
        had_review = (
            await session.execute(
                select(func.count()).where(
                    ReviewTask.user_id == principal.user_id,
                    ReviewTask.document_id == document_id,
                    ReviewTask.resolution.in_(
                        [
                            ReviewResolution.CONFIRMED,
                            ReviewResolution.CORRECTED,
                            ReviewResolution.REJECTED,
                            ReviewResolution.DISMISSED,
                        ]
                    ),
                )
            )
        ).scalar_one()
        if open_count:
            status = DocumentStatus.NEEDS_REVIEW
        elif had_review or (confirmations and all(confirmations)):
            status = DocumentStatus.CONFIRMED
        else:
            status = DocumentStatus.EXTRACTED
        if status is not document.status:
            if document.status is DocumentStatus.NEEDS_REVIEW:
                finished.append(document_id)
                document.status_reason = None
            document.status = status
    await session.flush()
    return finished


async def notify_reviewed(principal: Principal, document_ids: Iterable[UUID]) -> None:
    """Tell listeners (e.g. a journey run paused at a correction gate) after commit."""
    for document_id in document_ids:
        for listener in list(hooks.document_reviewed_listeners):
            try:
                await listener(principal, document_id)
            except Exception:  # a listener must never break the person's request
                logger.exception("document_reviewed_listener_failed")
