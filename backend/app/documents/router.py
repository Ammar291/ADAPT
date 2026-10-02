"""Document routes: upload, list, detail, (re)process, content, delete; review tasks.

Everything here is private: routes require the owner's session, and every lookup runs in
an RLS-scoped session. Document bytes additionally need a short-lived signed URL.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import ContainerDep, PrincipalDep, UserSession
from app.contracts.user_documents import (
    DocumentDetailOut,
    DocumentOut,
    DocumentProcessRequest,
    DocumentReviewRequest,
    ReviewTaskOut,
)
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.signing import sign_document_url, verify_document_signature
from app.db.models.user_data import ReviewTask
from app.documents import service
from app.documents.catalogue import DocumentKind, DocumentSubject
from app.documents.pipeline import analysis_for
from app.personalization import review
from app.personalization.facts_model import ReviewTaskStatus
from app.personalization.presenters import document_detail_out, document_out, review_tasks_out
from app.personalization.vocabulary import FactRuleError

router = APIRouter(tags=["documents"])

# Served files may only render themselves: no scripts, no outbound requests.
CONTENT_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"


@router.post(
    "/documents/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document; it is read in the background",
    description="Multipart upload (`file`, optional `kind`, `subject`, `subject_node_id`). "
    "The file type is checked from its content. Follow `events_url` for live progress.",
)
async def upload_document(
    principal: PrincipalDep,
    container: ContainerDep,
    file: Annotated[UploadFile, File(description="A photo or PDF")],
    kind: Annotated[DocumentKind | None, Form()] = None,
    subject: Annotated[DocumentSubject, Form()] = DocumentSubject.SELF,
    subject_node_id: Annotated[UUID | None, Form()] = None,
) -> DocumentOut:
    data = await file.read(container.settings.max_upload_bytes + 1)
    document = await service.upload(
        container,
        principal,
        filename=file.filename,
        data=data,
        declared_kind=kind,
        subject=subject,
        subject_node_id=subject_node_id,
    )
    return document_out(document, open_tasks=0, api_prefix=container.settings.api_prefix)


@router.get("/documents", response_model=list[DocumentOut], summary="Your documents")
async def list_documents(
    principal: PrincipalDep, session: UserSession, container: ContainerDep
) -> list[DocumentOut]:
    counts = await service.open_task_counts(session, principal)
    return [
        document_out(d, open_tasks=counts.get(d.id, 0), api_prefix=container.settings.api_prefix)
        for d in await service.list_documents(session, principal)
    ]


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailOut,
    summary="A document, what was read from it, and what needs your check",
)
async def get_document(
    document_id: UUID, principal: PrincipalDep, session: UserSession, container: ContainerDep
) -> DocumentDetailOut:
    document = await service.get_document(session, principal, document_id)
    analysis = await analysis_for(session, principal, document)
    tasks = await review.open_tasks(session, principal, document_id=document.id)
    return await document_detail_out(
        session,
        document,
        analysis,
        tasks,
        api_prefix=container.settings.api_prefix,
        content_url=sign_document_url(container.settings, principal, document.id),
    )


@router.post(
    "/documents/{document_id}/process",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Read the document again (optionally as a different document type)",
)
async def process_document(
    document_id: UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: DocumentProcessRequest | None = None,
) -> DocumentOut:
    document = await service.reprocess(
        container, principal, document_id, kind=body.kind if body else None
    )
    return document_out(document, open_tasks=0, api_prefix=container.settings.api_prefix)


@router.post(
    "/documents/{document_id}/review",
    response_model=DocumentDetailOut,
    summary="Correct what was read and confirm the rest",
    description="Each correction targets a field by name (`value: null` removes it). With "
    "`confirm`, every other readable detail from this document is confirmed too. The same "
    "operation is available per fact via PATCH/DELETE /graph/user/facts/{id}.",
)
async def review_document(
    document_id: UUID,
    body: DocumentReviewRequest,
    principal: PrincipalDep,
    session: UserSession,
    container: ContainerDep,
) -> DocumentDetailOut:
    intelligence = service.DocumentIntelligence(container.db, principal, container.adapters)
    try:
        await intelligence.apply_corrections(
            document_id,
            [c.model_dump() for c in body.corrections],
            confirm=body.confirm,
        )
    except FactRuleError as exc:
        raise BadRequest(str(exc), code=exc.code) from exc
    return await get_document(document_id, principal, session, container)


@router.get(
    "/documents/{document_id}/content",
    summary="The document file (signed, short-lived link; never cached)",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, "image/*": {}}}},
)
async def document_content(
    document_id: UUID,
    principal: PrincipalDep,
    session: UserSession,
    container: ContainerDep,
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query(max_length=128)],
) -> Response:
    verify_document_signature(container.settings, principal, document_id, expires=expires, sig=sig)
    document = await service.get_document(session, principal, document_id)
    if document.storage_key is None:
        raise NotFound("Document not found")
    content = await container.adapters.storage.get(document.storage_key)
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": CONTENT_CSP,
        },
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document, its file, and everything read from it",
)
async def delete_document(
    document_id: UUID, principal: PrincipalDep, container: ContainerDep
) -> Response:
    await service.delete_document(container, principal, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/review-tasks",
    response_model=list[ReviewTaskOut],
    tags=["review"],
    summary="Things to check before ADAPT relies on them",
)
async def list_review_tasks(
    principal: PrincipalDep,
    session: UserSession,
    status_: Annotated[ReviewTaskStatus, Query(alias="status")] = ReviewTaskStatus.OPEN,
    document_id: UUID | None = None,
) -> list[ReviewTaskOut]:
    query = select(ReviewTask).where(
        ReviewTask.user_id == principal.user_id, ReviewTask.status == status_
    )
    if document_id is not None:
        query = query.where(ReviewTask.document_id == document_id)
    tasks = list((await session.execute(query.order_by(ReviewTask.created_at))).scalars())
    return await review_tasks_out(session, tasks)


@router.post(
    "/review-tasks/{task_id}/dismiss",
    response_model=ReviewTaskOut,
    tags=["review"],
    summary="Dismiss a document-level task (e.g. you'll add the details yourself)",
    description="Tasks about a single fact are resolved through that fact: PATCH to confirm "
    "or correct, DELETE to reject.",
)
async def dismiss_review_task(
    task_id: UUID, principal: PrincipalDep, session: UserSession
) -> ReviewTaskOut:
    task = (
        await session.execute(
            select(ReviewTask).where(
                ReviewTask.user_id == principal.user_id, ReviewTask.id == task_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Review task not found")
    if task.fact_id is not None:
        raise Conflict(
            "Confirm, correct or remove the detail itself to resolve this", code="task_has_fact"
        )
    documents = await review.dismiss_task(session, principal, task_id)
    finished = await review.refresh_document_status(session, principal, documents)
    await session.commit()
    await session.refresh(task)
    await review.notify_reviewed(principal, finished)
    [out] = await review_tasks_out(session, [task])
    return out
