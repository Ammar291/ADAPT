"""Generated documents: review and approval. Nothing drafted is used until approved."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.db.models import GeneratedDocument
from app.domain.enums import GeneratedDocumentStatus
from app.domain.principal import Principal


async def list_documents(
    session: AsyncSession,
    principal: Principal,
    *,
    status: GeneratedDocumentStatus | None = None,
    journey_id: UUID | None = None,
) -> list[GeneratedDocument]:
    query = select(GeneratedDocument).where(GeneratedDocument.user_id == principal.user_id)
    if status is not None:
        query = query.where(GeneratedDocument.status == status)
    if journey_id is not None:
        query = query.where(GeneratedDocument.journey_id == journey_id)
    query = query.order_by(GeneratedDocument.created_at.desc())
    return list((await session.execute(query)).scalars())


async def get_document(
    session: AsyncSession, principal: Principal, document_id: UUID
) -> GeneratedDocument:
    doc = (
        await session.execute(
            select(GeneratedDocument).where(
                GeneratedDocument.id == document_id,
                GeneratedDocument.user_id == principal.user_id,
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFound("Document not found", code="generated_document_not_found")
    return doc


async def approve(
    session: AsyncSession,
    principal: Principal,
    document_id: UUID,
    *,
    body_markdown: str | None = None,
) -> GeneratedDocument:
    doc = await get_document(session, principal, document_id)
    if doc.status is GeneratedDocumentStatus.DISCARDED:
        raise Conflict("A discarded draft can't be approved", code="generated_document_discarded")
    if doc.status is GeneratedDocumentStatus.APPROVED:
        if body_markdown is not None and body_markdown != doc.body_markdown:
            raise Conflict(
                "This document is already approved; ask ADAPT for a new draft to change it",
                code="generated_document_already_approved",
            )
        return doc
    if body_markdown is not None:
        doc.body_markdown = body_markdown
        doc.details = {**(doc.details or {}), "edited_by_user": True}
    doc.status = GeneratedDocumentStatus.APPROVED
    doc.approved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(doc)
    return doc


async def update(
    session: AsyncSession, principal: Principal, document_id: UUID, *, body_markdown: str
) -> GeneratedDocument:
    """Edit a draft, or restore a discarded one (it comes back as a draft with this text).
    An approved document is final: ask ADAPT for a new draft to change it."""
    doc = await get_document(session, principal, document_id)
    if doc.status is GeneratedDocumentStatus.APPROVED:
        raise Conflict(
            "This document is already approved; ask ADAPT for a new draft to change it",
            code="generated_document_already_approved",
        )
    if body_markdown != doc.body_markdown:
        doc.body_markdown = body_markdown
        doc.details = {**(doc.details or {}), "edited_by_user": True}
    doc.status = GeneratedDocumentStatus.DRAFT
    await session.flush()
    await session.refresh(doc)
    return doc


async def discard(
    session: AsyncSession, principal: Principal, document_id: UUID
) -> GeneratedDocument:
    doc = await get_document(session, principal, document_id)
    if doc.status is GeneratedDocumentStatus.APPROVED:
        raise Conflict(
            "An approved document can't be discarded", code="generated_document_approved"
        )
    doc.status = GeneratedDocumentStatus.DISCARDED
    await session.flush()
    await session.refresh(doc)
    return doc
