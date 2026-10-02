"""Document use cases: upload, (re)process, delete, and the journey agent's port.

Uploads are checked by content (magic bytes, not the client's content type), encrypted
into document storage, and processed asynchronously in the worker. Deleting a document
destroys its bytes, removes every fact read from it, and leaves only a tombstone row.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update

from app.adapters.ocr import SUPPORTED_CONTENT_TYPES, sniff_content_type
from app.adapters.registry import Adapters
from app.core.container import Container
from app.core.errors import (
    AdapterUnavailable,
    AppError,
    BadRequest,
    Conflict,
    NotFound,
    PayloadTooLarge,
)
from app.db.models import AgentRun, GraphNode
from app.db.models.user_data import ExtractedFact, ReviewTask, UserDocument
from app.db.session import Database
from app.documents.catalogue import DocumentKind, DocumentStatus, DocumentSubject
from app.documents.pipeline import DocumentAnalysis, DocumentPipeline, analysis_for
from app.domain.enums import GraphType, RunKind, RunStatus
from app.domain.principal import Principal
from app.events.emitter import EventSink
from app.personalization import analytics, facts, review
from app.personalization.facts import FactChange
from app.personalization.facts_model import FactStatus
from app.personalization.store import UserGraph
from app.repositories.runs import create_run

logger = logging.getLogger(__name__)

PROCESS_JOB = "process_document"
AGENT = "document_intelligence"
MEMBER_TYPES = {"person", "spouse", "child"}


class UnsupportedMedia(AppError):
    status, code, title = 415, "unsupported_media", "This file type isn't supported"


def safe_filename(name: str | None) -> str:
    """Display name only (storage keys are server-generated): no paths, no control chars."""
    base = re.split(r"[\\/]", name or "")[-1]
    cleaned = "".join(ch for ch in unicodedata.normalize("NFC", base) if ch.isprintable())
    cleaned = cleaned.strip().strip(".") or "document"
    return cleaned[-255:]


async def _get(session: Any, principal: Principal, document_id: UUID) -> UserDocument:
    document = (
        await session.execute(
            select(UserDocument).where(
                UserDocument.user_id == principal.user_id,
                UserDocument.id == document_id,
                UserDocument.status != DocumentStatus.DELETED,
            )
        )
    ).scalar_one_or_none()
    if document is None:
        raise NotFound("Document not found")
    return document


async def _enqueue(container: Container, principal: Principal, document: UserDocument) -> None:
    """Create the extraction run and hand the document to the worker."""
    async with container.db.user_session(principal) as session:
        run = await create_run(
            session,
            principal,
            RunKind.DOCUMENT_EXTRACTION,
            agent=AGENT,
            input={"document_id": str(document.id)},
        )
        await session.execute(
            update(UserDocument)
            .where(UserDocument.id == document.id, UserDocument.user_id == principal.user_id)
            .values(extraction_run_id=run.id, status=DocumentStatus.UPLOADED, status_reason=None)
        )
        await session.commit()
    document.extraction_run_id = run.id
    document.status = DocumentStatus.UPLOADED
    try:
        await container.queue.enqueue(
            PROCESS_JOB,
            job_id=str(run.id),
            run_id=str(run.id),
            document_id=str(document.id),
            **principal.as_job_args(),
        )
    except AdapterUnavailable:
        async with container.db.user_session(principal) as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run.id)
                .values(status=RunStatus.FAILED, error={"code": "queue_unavailable"})
            )
            await session.execute(
                update(UserDocument)
                .where(UserDocument.id == document.id)
                .values(status_reason="Waiting to be read. Try again in a moment.")
            )
            await session.commit()
        raise


async def upload(
    container: Container,
    principal: Principal,
    *,
    filename: str | None,
    data: bytes,
    declared_kind: DocumentKind | None = None,
    subject: DocumentSubject = DocumentSubject.SELF,
    subject_node_id: UUID | None = None,
) -> UserDocument:
    settings = container.settings
    if not data:
        raise BadRequest("The file is empty", code="empty_upload")
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLarge(
            f"Files can be up to {settings.max_upload_bytes // (1024 * 1024)} MB",
            code="upload_too_large",
        )
    content_type = sniff_content_type(data)
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise UnsupportedMedia("Upload a photo (JPEG, PNG, WebP, HEIC) or a PDF")
    if subject is DocumentSubject.CHILD and subject_node_id is None:
        raise BadRequest("Choose which child this document belongs to", code="subject_required")

    async with container.db.user_session(principal) as session:
        if subject_node_id is not None:
            node = await UserGraph(session).node(subject_node_id)
            expected = {"self": "person", "spouse": "spouse", "child": "child"}[subject.value]
            if node is None or node.entity_type != expected:
                raise BadRequest("That person is not in your twin", code="invalid_subject")

    storage_key = f"{principal.user_id}/{uuid4()}"
    await container.adapters.storage.put(storage_key, data)
    try:
        async with container.db.user_session(principal) as session:
            document = UserDocument(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                kind=declared_kind or DocumentKind.MISCELLANEOUS,
                declared_kind=declared_kind,
                subject=subject,
                subject_node_id=subject_node_id,
                filename=safe_filename(filename),
                content_type=content_type,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                storage_key=storage_key,
                status=DocumentStatus.UPLOADED,
            )
            session.add(document)
            await session.commit()
            await session.refresh(document)
    except Exception:
        await container.adapters.storage.delete(storage_key)
        raise
    analytics.track(
        "document_uploaded",
        declared_kind=declared_kind.value if declared_kind else None,
        subject=subject.value,
        size_kb=len(data) // 1024,
    )
    await _enqueue(container, principal, document)
    return document


async def reprocess(
    container: Container, principal: Principal, document_id: UUID, *, kind: DocumentKind | None
) -> UserDocument:
    async with container.db.user_session(principal) as session:
        document = await _get(session, principal, document_id)
        if document.status is DocumentStatus.PROCESSING:
            raise Conflict("This document is being read right now", code="document_processing")
        if kind is not None:
            document.declared_kind = kind
            document.kind = kind
        await session.commit()
    await _enqueue(container, principal, document)
    return document


async def delete_document(container: Container, principal: Principal, document_id: UUID) -> None:
    """Destroy the bytes, remove everything read from it, keep a tombstone."""
    async with container.db.user_session(principal) as session:
        document = await _get(session, principal, document_id)
        graph = UserGraph(session)
        removed = await graph.delete_facts(ExtractedFact.source_document_id == document.id)
        await session.execute(
            delete(ReviewTask).where(
                ReviewTask.user_id == principal.user_id, ReviewTask.document_id == document.id
            )
        )
        node_ids = {node_id for node_id, _ in removed}
        if document.node_id is not None:
            node_ids.add(document.node_id)
        storage_key = document.storage_key
        document.status = DocumentStatus.DELETED
        document.deleted_at = datetime.now(UTC)
        document.filename = "Deleted document"
        document.sha256 = None
        document.storage_key = None
        document.size_bytes = 0
        document.extraction = None
        document.status_reason = None
        document.node_id = None
        document.subject_node_id = None
        await session.flush()
        await graph.prune(node_ids)
        for node in await graph.nodes():
            if node.id in node_ids:
                await graph.refresh_label(node)
                await graph.sync_governance_link(node)
        await session.commit()
    if storage_key:
        await container.adapters.storage.delete(storage_key)
    analytics.track("document_deleted", fact_count=len(removed))


async def list_documents(session: Any, principal: Principal) -> list[UserDocument]:
    query = (
        select(UserDocument)
        .where(
            UserDocument.user_id == principal.user_id,
            UserDocument.status != DocumentStatus.DELETED,
        )
        .order_by(UserDocument.created_at.desc())
    )
    return list((await session.execute(query)).scalars())


async def open_task_counts(session: Any, principal: Principal) -> dict[UUID, int]:
    tasks = await review.open_tasks(session, principal)
    counts: dict[UUID, int] = {}
    for task in tasks:
        if task.document_id is not None:
            counts[task.document_id] = counts.get(task.document_id, 0) + 1
    return counts


get_document = _get


class DocumentIntelligence:
    """Port for agents (e.g. the journey agent's document node).

    `analyze` is idempotent: a document that was already read returns its stored result
    without reading it again, so a LangGraph node can safely re-run after an interrupt.
    """

    def __init__(
        self,
        db: Database,
        principal: Principal,
        adapters: Adapters,
        events: EventSink | None = None,
        node: str = "document_analysis",
    ) -> None:
        self.db, self.principal, self.adapters = db, principal, adapters
        self.events, self.node = events, node

    async def analyze(self, document_id: UUID) -> DocumentAnalysis:
        pipeline = DocumentPipeline(
            self.db, self.principal, self.adapters, events=self.events, node=self.node
        )
        return await pipeline.run(document_id)

    async def apply_corrections(
        self, document_id: UUID, corrections: list[dict[str, Any]], confirm: bool = True
    ) -> list[FactChange]:
        """Correct fields by name ({name, value}); with `confirm`, accept the rest too."""
        changes: list[FactChange] = []
        finished: list[UUID] = []
        async with self.db.user_session(self.principal) as session:
            document = await _get(session, self.principal, document_id)
            analysis = await analysis_for(session, self.principal, document)
            by_field = {f.name: f.fact_id for f in analysis.fields if f.fact_id}
            corrected: set[UUID] = set()
            for correction in corrections:
                fact_id = by_field.get(str(correction.get("name")))
                if fact_id is None:
                    raise NotFound(f"No field named {correction.get('name')!r} on this document")
                if correction.get("value") is None:
                    change = await facts.delete_fact(session, fact_id)
                else:
                    change = await facts.update_fact(session, fact_id, value=correction["value"])
                corrected.add(fact_id)
                changes.append(change)
                finished += change.reviewed_documents or []
            if confirm:
                pending = await UserGraph(session).facts(
                    document_id=document.id,
                    statuses=(FactStatus.ACCEPTED, FactStatus.NEEDS_REVIEW),
                )
                for fact in pending:
                    if fact.id in corrected or (
                        fact.confirmed_by_user and fact.status is FactStatus.ACCEPTED
                    ):
                        continue
                    if fact.value is None:
                        continue  # nothing to confirm; it stays open for the person
                    change = await facts.update_fact(session, fact.id, confirm=True)
                    changes.append(change)
                    finished += change.reviewed_documents or []
            await session.commit()
        await review.notify_reviewed(self.principal, set(finished))
        return changes


async def member_node(session: Any, principal: Principal, node_id: UUID) -> GraphNode | None:
    node = (
        await session.execute(
            select(GraphNode).where(
                GraphNode.id == node_id,
                GraphNode.graph_type == GraphType.USER,
                GraphNode.user_id == principal.user_id,
            )
        )
    ).scalar_one_or_none()
    return node if node is not None and node.entity_type in MEMBER_TYPES else None
