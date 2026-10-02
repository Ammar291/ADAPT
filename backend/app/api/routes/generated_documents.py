"""Documents ADAPT generated for the user. Mounted BEFORE any `/documents/{id}` route so
the literal `/documents/generated` path always wins."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query

from app.api.deps import PrincipalDep, UserSession
from app.contracts.generated_documents import (
    ApproveGeneratedDocumentRequest,
    GeneratedDocumentOut,
    UpdateGeneratedDocumentRequest,
)
from app.domain.enums import GeneratedDocumentStatus
from app.services import generated_documents as service
from app.services.presenters import generated_document_out

router = APIRouter(tags=["generated documents"])


@router.get(
    "/documents/generated",
    response_model=list[GeneratedDocumentOut],
    summary="Documents ADAPT drafted for you",
)
async def list_generated(
    principal: PrincipalDep,
    session: UserSession,
    status: Annotated[GeneratedDocumentStatus | None, Query()] = None,
    journey_id: Annotated[UUID | None, Query()] = None,
) -> list[GeneratedDocumentOut]:
    docs = await service.list_documents(session, principal, status=status, journey_id=journey_id)
    return [generated_document_out(d) for d in docs]


@router.get(
    "/documents/generated/{document_id}",
    response_model=GeneratedDocumentOut,
    summary="One generated document",
)
async def read_generated(
    document_id: UUID, principal: PrincipalDep, session: UserSession
) -> GeneratedDocumentOut:
    return generated_document_out(await service.get_document(session, principal, document_id))


@router.patch(
    "/documents/generated/{document_id}",
    response_model=GeneratedDocumentOut,
    summary="Edit a draft (or restore a discarded one)",
    description="Saves your text; the document is (again) a draft to review. 409 "
    "`generated_document_already_approved` for an approved document.",
)
async def update_generated(
    document_id: UUID,
    body: UpdateGeneratedDocumentRequest,
    principal: PrincipalDep,
    session: UserSession,
) -> GeneratedDocumentOut:
    doc = await service.update(session, principal, document_id, body_markdown=body.body_markdown)
    await session.commit()
    return generated_document_out(doc)


@router.post(
    "/documents/generated/{document_id}/approve",
    response_model=GeneratedDocumentOut,
    summary="Approve a generated document",
    description="Marks the draft as approved (optionally with your final edits). Approving is "
    "idempotent; a discarded draft cannot be approved.",
)
async def approve_generated(
    document_id: UUID,
    principal: PrincipalDep,
    session: UserSession,
    body: Annotated[ApproveGeneratedDocumentRequest | None, Body()] = None,
) -> GeneratedDocumentOut:
    doc = await service.approve(
        session, principal, document_id, body_markdown=body.body_markdown if body else None
    )
    await session.commit()
    return generated_document_out(doc)


@router.post(
    "/documents/generated/{document_id}/discard",
    response_model=GeneratedDocumentOut,
    summary="Discard a generated draft",
)
async def discard_generated(
    document_id: UUID, principal: PrincipalDep, session: UserSession
) -> GeneratedDocumentOut:
    doc = await service.discard(session, principal, document_id)
    await session.commit()
    return generated_document_out(doc)
