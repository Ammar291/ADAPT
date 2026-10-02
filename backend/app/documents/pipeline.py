"""The document pipeline: classify → read (OCR/VLM) → validate → structure → review → twin.

Runs in the worker (its own `document_extraction` run) or inside another agent run (the
journey agent's document node), emitting progress to whichever event sink it is given.
Events carry stage names and counts only, never values read from the document.

Honesty rules:
* nothing is invented: if no reader can read the document, it goes to "needs review"
  with a task asking the person to check it, and no facts are created;
* confident, valid values become accepted facts (unconfirmed until the person says so);
  everything else becomes a pending fact plus a review task;
* a value that differs from one already in the twin never silently replaces it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.adapters.ocr import DocumentUnreadable, ReaderFailed, ReadRequest, ReadResult
from app.adapters.registry import Adapters
from app.db.models import GraphNode
from app.db.models.user_data import ExtractedFact, UserDocument
from app.db.session import Database
from app.documents.catalogue import (
    KIND_LABELS,
    READ_SCHEMA,
    REVIEW_THRESHOLD,
    DocumentKind,
    DocumentStatus,
    DocumentSubject,
    field_kind,
    field_label,
)
from app.documents.structuring import (
    SELF,
    SPOUSE,
    EntityRef,
    ProposedFact,
    StructuringContext,
    structure,
)
from app.documents.validation import ValidationOutcome, validate_reading
from app.domain.enums import ArtifactType, FactSource
from app.domain.principal import Principal
from app.events.emitter import EventSink
from app.personalization import analytics, review
from app.personalization.facts_model import FactStatus, ReviewTaskKind
from app.personalization.store import UserGraph
from app.personalization.vocabulary import ENTITY_SPECS, FactRuleError, UserEntityType

logger = logging.getLogger(__name__)

STAGES = {
    "classify": "Identifying your document",
    "extract": "Reading the details",
    "validate": "Checking what was read",
    "structure": "Organising the details",
    "update_twin": "Updating your private twin",
}
UNREADABLE_MESSAGE = (
    "We couldn't read this document automatically. Check it and add the details yourself, "
    "or try a clearer photo or the original PDF."
)
SETTLED = (DocumentStatus.EXTRACTED, DocumentStatus.NEEDS_REVIEW, DocumentStatus.CONFIRMED)


@dataclass(slots=True)
class FieldResult:
    name: str
    label: str
    value: Any
    confidence: float
    needs_review: bool
    fact_id: UUID | None
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FactResult:
    id: UUID
    entity_type: str
    attribute: str
    value: Any
    confidence: float
    source: str
    status: str


@dataclass(slots=True)
class DocumentAnalysis:
    document_id: UUID
    kind: DocumentKind
    holder: DocumentSubject
    status: DocumentStatus
    fields: list[FieldResult]
    facts: list[FactResult]
    review_task_ids: list[UUID]


class _Stages:
    """Stage events: own run → node_started/completed per stage; embedded → progress."""

    def __init__(self, events: EventSink | None, node: str, own_run: bool) -> None:
        self.events, self.node, self.own_run = events, node, own_run
        self._started = 0.0
        self._current = ""

    async def start(self, stage: str) -> None:
        self._current, self._started = stage, time.perf_counter()
        if self.events is None:
            return
        if self.own_run:
            await self.events.node_started(stage, STAGES[stage])
        else:
            await self.events.node_progress(self.node, STAGES[stage], detail={"stage": stage})

    async def done(self, summary: str | None = None) -> None:
        if self.events is not None and self.own_run:
            elapsed = int((time.perf_counter() - self._started) * 1000)
            await self.events.node_completed(self._current, elapsed, summary, STAGES[self._current])


def _subject_ref(document: UserDocument) -> EntityRef:
    if document.subject is DocumentSubject.SPOUSE:
        return SPOUSE
    if document.subject is DocumentSubject.CHILD and document.subject_node_id is not None:
        return EntityRef(UserEntityType.CHILD, SELF, node_id=document.subject_node_id)
    return SELF


def _resolve_kind(
    document: UserDocument, reading: ReadResult | None
) -> tuple[DocumentKind, float, bool]:
    """(kind, confidence in the kind, whether the declared kind looks wrong)."""
    detected = DocumentKind(reading.detected_type) if reading and reading.detected_type else None
    declared = document.declared_kind
    if declared is not None:
        mismatch = (
            detected is not None
            and detected is not declared
            and reading is not None
            and reading.type_confidence >= REVIEW_THRESHOLD
        )
        return declared, 1.0, mismatch
    if detected is not None and reading is not None:
        return detected, reading.type_confidence, False
    return DocumentKind.MISCELLANEOUS, 0.5, False


class DocumentPipeline:
    def __init__(
        self,
        db: Database,
        principal: Principal,
        adapters: Adapters,
        *,
        events: EventSink | None = None,
        node: str = "document_analysis",
        own_run: bool = False,
    ) -> None:
        self.db = db
        self.principal = principal
        self.adapters = adapters
        self.stages = _Stages(events, node, own_run)
        self.events = events
        self.node = node

    async def run(self, document_id: UUID, *, force: bool = False) -> DocumentAnalysis:
        """Process a document. Idempotent unless `force`: a document that was already
        processed returns its stored analysis without calling any reader again."""
        async with self.db.user_session(self.principal) as session:
            # Locked: the upload's own job and a journey run can both ask for the same
            # document, and only one of them may read it (the other gets its result).
            document = await _get(session, self.principal, document_id, lock=True)
            if document.status in SETTLED and not force:
                return await analysis_for(session, self.principal, document)
            if document.status is DocumentStatus.PROCESSING and not force:
                return await analysis_for(session, self.principal, document)
            document.status = DocumentStatus.PROCESSING
            document.status_reason = None
            storage_key, content_type = document.storage_key, document.content_type
            declared = document.declared_kind.value if document.declared_kind else None
            await session.commit()

        started = time.perf_counter()
        assert storage_key is not None
        content = await self.adapters.storage.get(storage_key)

        await self.stages.start("classify")
        reading: ReadResult | None = None
        try:
            reading = await self.adapters.ocr.read(
                ReadRequest(content, content_type, READ_SCHEMA, type_hint=declared)
            )
        except (DocumentUnreadable, ReaderFailed) as exc:
            logger.info(
                "document_unreadable",
                extra={"document_id": str(document_id), "reason": type(exc).__name__},
            )
        finally:
            del content  # the plaintext bytes are not kept around

        async with self.db.user_session(self.principal) as session:
            document = await _get(session, self.principal, document_id)
            kind, kind_confidence, mismatch = _resolve_kind(document, reading)
            await self.stages.done(KIND_LABELS[kind])
            if reading is None:
                outcome = await self._unreadable(session, document, kind)
            else:
                outcome = await self._process(
                    session, document, reading, kind, kind_confidence, mismatch
                )
            await session.commit()
            result = await analysis_for(session, self.principal, document)

        analytics.track(
            "document_processed",
            kind=kind.value,
            declared_kind=document.declared_kind.value if document.declared_kind else None,
            subject=document.subject.value,
            method=reading.method if reading else None,
            outcome=outcome,
            field_count=len(result.fields),
            accepted_count=sum(1 for f in result.facts if f.status == FactStatus.ACCEPTED),
            needs_review_count=sum(1 for f in result.facts if f.status == FactStatus.NEEDS_REVIEW),
            task_count=len(result.review_task_ids),
            kind_mismatch=mismatch,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        if self.events is not None:
            await self.events.artifact(
                ArtifactType.DOCUMENT_EXTRACTION,
                str(document_id),
                title=KIND_LABELS[kind],
                node=self.node if not self.stages.own_run else "update_twin",
            )
        return result

    async def _unreadable(self, session: Any, document: UserDocument, kind: DocumentKind) -> str:
        """No reader could read it: say so, ask the person, invent nothing."""
        await review.supersede_document_tasks(session, self.principal, document.id)
        await review.open_task(
            session,
            self.principal,
            kind=ReviewTaskKind.EXTRACTION_FAILED,
            message=UNREADABLE_MESSAGE,
            document_id=document.id,
        )
        document.kind = kind
        document.status = DocumentStatus.NEEDS_REVIEW
        document.status_reason = "We couldn't read this document automatically"
        document.processed_at = datetime.now(UTC)
        document.extraction = {
            "outcome": "unreadable",
            "method": None,
            "detected_kind": None,
            "fields": [],
            "warnings": [],
            "extracted_at": document.processed_at.isoformat(),
        }
        return "unreadable"

    async def _process(
        self,
        session: Any,
        document: UserDocument,
        reading: ReadResult,
        kind: DocumentKind,
        kind_confidence: float,
        mismatch: bool,
    ) -> str:
        await self.stages.start("extract")
        await self.stages.done(f"{reading.filled()} fields read")

        await self.stages.start("validate")
        outcome: ValidationOutcome = validate_reading(kind, reading)
        flagged = sum(1 for f in outcome.fields.values() if f.needs_review)
        await self.stages.done(f"{flagged} to check" if flagged else "All checks passed")

        await self.stages.start("structure")
        graph = UserGraph(session)
        hub = await graph.hub()
        subject_ref = _subject_ref(document)
        self_facts = {f.attribute: f.value for f in await graph.facts(node_ids=[hub.id])}
        subject_name = self_facts.get("full_name")
        if subject_ref is not SELF:
            existing = await _existing(graph, subject_ref)
            subject_name = (
                {f.attribute: f.value for f in await graph.facts(node_ids=[existing.id])}.get(
                    "full_name"
                )
                if existing
                else None
            )
        structured = structure(
            outcome,
            StructuringContext(
                document_id=document.id,
                subject=subject_ref,
                kind_confidence=kind_confidence,
                method=reading.method,
                self_name=self_facts.get("full_name"),
                subject_name=subject_name,
            ),
        )
        await self.stages.done(f"{len(structured.facts)} details")

        await self.stages.start("update_twin")
        # Re-extraction replaces what this document said before, except what the person
        # already confirmed or corrected.
        await review.supersede_document_tasks(session, self.principal, document.id)
        replaced = await graph.delete_facts(
            (ExtractedFact.source_document_id == document.id)
            & (ExtractedFact.confirmed_by_user.is_(False))
        )
        touched: dict[UUID, GraphNode] = {}
        fields: dict[str, dict[str, Any]] = {}
        for proposal in structured.facts:
            fact = await self._write(session, graph, document, proposal, touched)
            if proposal.field and proposal.field not in fields and fact is not None:
                fields[proposal.field] = {
                    "name": proposal.field,
                    "label": field_label(proposal.field),
                    "confidence": round(proposal.confidence, 3),
                    "needs_review": fact.status is FactStatus.NEEDS_REVIEW,
                    "issues": list(fact.issues or []),
                    "fact_id": str(fact.id),
                }
        document_node = await graph.resolve(structured.document_entity)
        document.node_id = document_node.id
        subject_node = await graph.resolve(subject_ref) if subject_ref is not SELF else hub
        document.subject_node_id = subject_node.id
        touched[document_node.id] = document_node
        for node in touched.values():
            await graph.refresh_label(node)
            await graph.sync_governance_link(node)
        await graph.prune([node_id for node_id, _ in replaced])

        if mismatch and reading.detected_type:
            await review.open_task(
                session,
                self.principal,
                kind=ReviewTaskKind.KIND_MISMATCH,
                message=(
                    f"This looks like a {KIND_LABELS[DocumentKind(reading.detected_type)].lower()}"
                    f" rather than a {KIND_LABELS[kind].lower()}. Check the document type."
                ),
                document_id=document.id,
            )
        open_tasks = await review.open_tasks(session, self.principal, document_id=document.id)
        document.kind = kind
        document.kind_confidence = round(kind_confidence, 3)
        document.processed_at = datetime.now(UTC)
        document.status = DocumentStatus.NEEDS_REVIEW if open_tasks else DocumentStatus.EXTRACTED
        document.status_reason = (
            f"{len(open_tasks)} detail{'s' if len(open_tasks) != 1 else ''} to check"
            if open_tasks
            else None
        )
        document.extraction = {
            "outcome": "read",
            "method": reading.method,
            "detected_kind": reading.detected_type,
            "kind_confidence": round(kind_confidence, 3),
            "mrz": None if outcome.mrz is None else ("verified" if outcome.mrz.valid else "failed"),
            "fields": list(fields.values()),
            "warnings": outcome.warnings + structured.warnings,
            "extracted_at": document.processed_at.isoformat(),
        }
        await self.stages.done(
            f"{len(open_tasks)} to check" if open_tasks else "Everything added to your twin"
        )
        return "needs_review" if open_tasks else "extracted"

    async def _write(
        self,
        session: Any,
        graph: UserGraph,
        document: UserDocument,
        proposal: ProposedFact,
        touched: dict[UUID, GraphNode],
    ) -> ExtractedFact | None:
        node = await graph.resolve(proposal.entity)
        touched[node.id] = node
        accepted = {f.attribute: f for f in await graph.facts(node_ids=[node.id])}
        current = accepted.get(proposal.attribute)
        issues = list(proposal.issues)
        task_kind = ReviewTaskKind.LOW_CONFIDENCE
        if current is not None:
            if current.value == proposal.value or proposal.value is None:
                return current  # already known (or unreadable here): keep what the twin has
            if proposal.value is not None:
                issues.append("This differs from what's already in your twin")
                task_kind = ReviewTaskKind.CONFLICT
        pending = proposal.needs_review or bool(issues)
        try:
            fact = await graph.write_fact(
                node,
                proposal.attribute,
                proposal.value,
                source=FactSource.DOCUMENT_EXTRACTED,
                status=FactStatus.NEEDS_REVIEW if pending else FactStatus.ACCEPTED,
                confidence=proposal.confidence,
                source_document_id=document.id,
                extraction_method=proposal.method,
                field=proposal.field,
                issues=issues,
            )
        except FactRuleError:
            logger.info(
                "document_fact_skipped",
                extra={"entity_type": node.entity_type, "attribute": proposal.attribute},
            )
            return None
        if pending:
            spec = ENTITY_SPECS[UserEntityType(node.entity_type)]
            attribute = spec.attributes[proposal.attribute].label
            what = (
                attribute
                if spec.type in (UserEntityType.DOCUMENT, UserEntityType.PASSPORT)
                else f"{spec.label}'s {attribute.lower()}"
            )
            reason = issues[0] if issues else "We're not sure we read it correctly"
            reason = reason[:1].lower() + reason[1:]
            await review.open_task(
                session,
                self.principal,
                kind=task_kind,
                message=f"{what} on your {KIND_LABELS[document.kind].lower()}: {reason}",
                document_id=document.id,
                fact_id=fact.id,
                field=proposal.field,
            )
        return fact


async def _existing(graph: UserGraph, ref: EntityRef) -> GraphNode | None:
    """An entity that already exists for `ref` (without creating it)."""
    if ref.node_id is not None:
        return await graph.node(ref.node_id)
    if ref.type is UserEntityType.SPOUSE:
        return await graph.by_key("spouse.self")
    return None


async def _get(
    session: Any, principal: Principal, document_id: UUID, *, lock: bool = False
) -> UserDocument:
    from app.core.errors import NotFound

    query = select(UserDocument).where(
        UserDocument.user_id == principal.user_id,
        UserDocument.id == document_id,
        UserDocument.status != DocumentStatus.DELETED,
    )
    if lock:
        query = query.with_for_update()
    document = (await session.execute(query)).scalar_one_or_none()
    if document is None:
        raise NotFound("Document not found")
    return document


async def analysis_for(
    session: Any, principal: Principal, document: UserDocument
) -> DocumentAnalysis:
    graph = UserGraph(session)
    facts = await graph.facts(
        document_id=document.id, statuses=(FactStatus.ACCEPTED, FactStatus.NEEDS_REVIEW)
    )
    nodes = {n.id: n for n in await graph.nodes()}
    by_id = {f.id: f for f in facts}
    entries = (document.extraction or {}).get("fields", [])
    # A value the twin already held (e.g. a spouse's name the person stated) is not written
    # again; its field points at that fact. Show it as read, not as missing.
    for entry in entries:
        if entry.get("fact_id") and UUID(entry["fact_id"]) not in by_id:
            agreeing = await graph.fact(UUID(entry["fact_id"]))
            if agreeing is not None and agreeing.status in (
                FactStatus.ACCEPTED,
                FactStatus.NEEDS_REVIEW,
            ):
                by_id[agreeing.id] = agreeing
    # A list field (e.g. business activities) became one fact per item: show them all.
    items: dict[str, list[Any]] = {}
    for fact in facts:
        if fact.field and field_kind(DocumentKind(document.kind), fact.field) == "list":
            items.setdefault(fact.field, []).append(fact.value)
    fields = []
    for entry in entries:
        fact = by_id.get(UUID(entry["fact_id"])) if entry.get("fact_id") else None
        fields.append(
            FieldResult(
                name=entry["name"],
                label=entry["label"],
                value=items[entry["name"]]
                if len(items.get(entry["name"], [])) > 1
                else fact.value
                if fact
                else None,
                # The reader's own confidence when the value agreed with an existing fact.
                confidence=fact.confidence
                if fact and fact.source_document_id == document.id
                else entry.get("confidence", 0.0),
                needs_review=fact.status is FactStatus.NEEDS_REVIEW if fact else True,
                fact_id=fact.id if fact else None,
                issues=list(fact.issues or []) if fact else entry.get("issues", []),
            )
        )
    tasks = await review.open_tasks(session, principal, document_id=document.id)
    return DocumentAnalysis(
        document_id=document.id,
        kind=document.kind,
        holder=document.subject,
        status=document.status,
        fields=fields,
        facts=[
            FactResult(
                id=f.id,
                entity_type=nodes[f.node_id].entity_type if f.node_id in nodes else "unknown",
                attribute=f.attribute,
                value=f.value,
                confidence=f.confidence,
                source=FactSource(f.source).value,
                status=FactStatus(f.status).value,
            )
            for f in facts
        ],
        review_task_ids=[t.id for t in tasks],
    )
