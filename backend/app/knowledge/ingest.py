"""Ingest the curated corpus into the governance tables. Runs as the schema owner.

Idempotent and version-aware:

* each publisher becomes a `governance_sources` row (with its priority);
* each corpus record becomes a live `governance_documents` version keyed by URL:
  - same content hash      -> kept; `retrieved_at` refreshed if the page was re-checked
  - different content hash -> old version stamped `superseded_at`, new version inserted
  - dropped from the corpus -> stamped `superseded_at` (retired), never deleted, so
    citations keep pointing at what they quoted;
* each passage becomes one or more `governance_chunks`, embedded by the configured
  embedder. Chunks embedded by a different embedder are re-embedded, because vectors
  from different models cannot be compared.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings import Embedder
from app.core.errors import UpstreamError
from app.db.models.governance import GovernanceChunk, GovernanceDocument, GovernanceSource
from app.domain.provenance import is_official_source
from app.knowledge.corpus import Corpus, SourceRecord, chunk_text
from app.knowledge.evidence import PassageView
from app.knowledge.graph_seed import ResolvedPassage
from app.knowledge.sources import PUBLISHERS

logger = logging.getLogger("adapt.knowledge.ingest")
CORPUS_ORIGIN = "curated_corpus"


@dataclass
class IngestReport:
    sites: int = 0
    inserted: int = 0
    unchanged: int = 0
    refreshed: int = 0
    superseded: int = 0
    retired: int = 0
    chunks_embedded: int = 0
    embedding_model: str | None = None
    embedding_fallback: bool = False
    notes: list[str] = field(default_factory=list)


def chunk_context(record: SourceRecord, section: str | None) -> str:
    return f"{record.title} — {section}" if section else record.title


def _chunk_rows(record: SourceRecord) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for passage in record.passages:
        parts = chunk_text(passage.text)
        for part_index, content in enumerate(parts):
            rows.append(
                {
                    "chunk_index": len(rows),
                    "content": content,
                    "context": chunk_context(record, passage.section),
                    "section": passage.section,
                    "token_count": math.ceil(len(content) / 4),
                    "metadata_": {
                        "passage_key": passage.key,
                        "part": part_index,
                        "parts": len(parts),
                        "source_key": record.key,
                        "excerpt": passage.excerpt,
                        "states_requirement": passage.states_requirement,
                        "verification": record.verification,
                        "topics": [t.value for t in record.passage_topics(passage)],
                    },
                }
            )
    return rows


async def _upsert_sites(session: AsyncSession, corpus: Corpus) -> dict[str, UUID]:
    """One `governance_sources` row per publisher. Returns publisher key -> row id."""
    site_ids: dict[str, UUID] = {}
    for publisher in sorted({PUBLISHERS[s.authority] for s in corpus.sources}, key=lambda p: p.key):
        values = {
            "key": publisher.site_key,
            "name": publisher.name,
            "authority": publisher.key,
            "base_url": publisher.base_url,
            "source_type": "portal",
            "is_official": is_official_source(publisher.base_url),
            "priority": publisher.priority,
            "metadata_": {"family": publisher.family.value, "domains": list(publisher.domains)},
        }
        site_insert = insert(GovernanceSource).values(**values)
        upsert = site_insert.on_conflict_do_update(
            constraint="uq_governance_sources_key",
            set_={
                "name": site_insert.excluded.name,
                "authority": site_insert.excluded.authority,
                "base_url": site_insert.excluded.base_url,
                "is_official": site_insert.excluded.is_official,
                "priority": site_insert.excluded.priority,
                "metadata": site_insert.excluded.metadata,
            },
        ).returning(GovernanceSource.id)
        site_ids[publisher.key] = (await session.execute(upsert)).scalar_one()
    return site_ids


async def _embed(
    embedder: Embedder, fallback: Embedder | None, texts: Sequence[str], report: IngestReport
) -> tuple[list[list[float]], str]:
    """Embed with the configured embedder, falling back (e.g. offline) to `fallback`.
    Chunks record which embedder produced them, so a later run re-embeds them."""
    try:
        return await embedder.embed(list(texts)), embedder.model_id
    except UpstreamError:
        if fallback is None:
            raise
        report.embedding_fallback = True
        report.notes.append(f"{embedder.model_id} unavailable; embedded with {fallback.model_id}")
        logger.warning("embedding provider unavailable during ingestion; using fallback")
        return await fallback.embed(list(texts)), fallback.model_id


async def ingest_corpus(
    session: AsyncSession,
    corpus: Corpus,
    embedder: Embedder,
    *,
    fallback_embedder: Embedder | None = None,
    now: datetime | None = None,
) -> tuple[IngestReport, dict[str, UUID], dict[str, ResolvedPassage]]:
    """Returns (report, publisher key -> governance_sources id, passage ref -> stored passage)."""
    now = now or datetime.now(UTC)
    report = IngestReport(embedding_model=embedder.model_id)
    site_ids = await _upsert_sites(session, corpus)
    report.sites = len(site_ids)

    live_rows = (
        await session.execute(
            select(GovernanceDocument).where(GovernanceDocument.superseded_at.is_(None))
        )
    ).scalars()
    live = {doc.source_url: doc for doc in live_rows}
    to_embed: list[GovernanceChunk] = []
    documents: dict[str, GovernanceDocument] = {}

    for record in corpus.sources:
        content_hash = record.content_hash
        current = live.get(record.url)
        metadata = {
            "origin": CORPUS_ORIGIN,
            "key": record.key,
            "topics": [t.value for t in record.topics],
            "verification": record.verification,
            "last_updated": record.last_updated.isoformat() if record.last_updated else None,
            "notes": record.notes,
        }
        if current is not None and current.content_hash == content_hash:
            if record.retrieved_at > current.retrieved_at:
                current.retrieved_at = record.retrieved_at
                report.refreshed += 1
            else:
                report.unchanged += 1
            current.metadata_ = metadata
            current.governance_source_id = site_ids[record.authority]
            documents[record.key] = current
            continue
        if current is not None:
            current.superseded_at = now
            report.superseded += 1
            await session.flush()  # free the live-URL slot before inserting the new version
        document = GovernanceDocument(
            governance_source_id=site_ids[record.authority],
            source_url=record.url,
            title=record.title,
            authority=record.authority,
            document_type=record.source_type.value,
            language=record.language,
            effective_date=record.effective_date,
            retrieved_at=record.retrieved_at,
            content_hash=content_hash,
            is_official=is_official_source(record.url),
            metadata_=metadata,
        )
        session.add(document)
        await session.flush()
        for row in _chunk_rows(record):
            chunk = GovernanceChunk(document_id=document.id, **row)
            session.add(chunk)
            to_embed.append(chunk)
        documents[record.key] = document
        report.inserted += 1

    corpus_urls = {record.url for record in corpus.sources}
    retired = [
        doc.id
        for url, doc in live.items()
        if url not in corpus_urls and (doc.metadata_ or {}).get("origin") == CORPUS_ORIGIN
    ]
    if retired:
        await session.execute(
            update(GovernanceDocument)
            .where(GovernanceDocument.id.in_(retired))
            .values(superseded_at=now)
        )
        report.retired = len(retired)
    await session.flush()

    # Re-embed live corpus chunks from another vector space (e.g. demo -> OpenAI).
    doc_ids = [doc.id for doc in documents.values()]
    stale_vectors = (
        await session.execute(
            select(GovernanceChunk).where(
                GovernanceChunk.document_id.in_(doc_ids),
                (GovernanceChunk.embedding_model.is_(None))
                | (GovernanceChunk.embedding_model != embedder.model_id),
            )
        )
    ).scalars()
    pending = {id(c): c for c in [*to_embed, *stale_vectors]}.values()
    chunks = list(pending)
    if chunks:
        vectors, model_id = await _embed(
            embedder,
            fallback_embedder,
            [f"{c.context}\n{c.content}" if c.context else c.content for c in chunks],
            report,
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = model_id
        report.chunks_embedded = len(chunks)
    await session.flush()

    passages = await resolve_passages(session, corpus, documents)
    logger.info(
        "knowledge corpus ingested",
        extra={
            "inserted": report.inserted,
            "unchanged": report.unchanged,
            "superseded": report.superseded,
            "retired": report.retired,
            "chunks_embedded": report.chunks_embedded,
        },
    )
    return report, site_ids, passages


async def resolve_passages(
    session: AsyncSession, corpus: Corpus, documents: dict[str, GovernanceDocument]
) -> dict[str, ResolvedPassage]:
    """Map every `<source_key>#<passage_key>` reference to its stored chunks."""
    by_id = {doc.id: doc for doc in documents.values()}
    rows = (
        await session.execute(
            select(GovernanceChunk)
            .where(GovernanceChunk.document_id.in_(list(by_id)))
            .order_by(GovernanceChunk.document_id, GovernanceChunk.chunk_index)
        )
    ).scalars()
    grouped: dict[tuple[UUID, str], list[GovernanceChunk]] = {}
    for chunk in rows:
        grouped.setdefault((chunk.document_id, chunk.metadata_["passage_key"]), []).append(chunk)

    resolved: dict[str, ResolvedPassage] = {}
    for record in corpus.sources:
        document = documents[record.key]
        for passage in record.passages:
            chunks = grouped.get((document.id, passage.key), [])
            if not chunks:
                continue
            first = chunks[0]
            resolved[f"{record.key}#{passage.key}"] = ResolvedPassage(
                document_id=document.id,
                chunk_ids=tuple(c.id for c in chunks),
                view=PassageView(
                    document_id=document.id,
                    chunk_id=first.id,
                    content=passage.text,
                    source_url=document.source_url,
                    title=document.title,
                    authority=document.authority,
                    retrieved_at=document.retrieved_at,
                    effective_date=document.effective_date,
                    section_or_page=passage.section,
                    excerpt=passage.excerpt,
                    states_requirement=passage.states_requirement,
                    verification=record.verification,
                    topics=tuple(t.value for t in record.passage_topics(passage)),
                ),
            )
    return resolved
