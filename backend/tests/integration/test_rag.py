"""pgvector similarity search over the governance corpus (`similarity_search`)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import update

from app.adapters.embeddings import HashingEmbedder
from app.db.models import GovernanceChunk, GovernanceDocument
from app.db.session import Database
from app.repositories.governance_corpus import lexical_search, similarity_search

EMBEDDER = HashingEmbedder()
MODEL = "test-hashing"  # isolates these rows from the seeded corpus

PASSAGES = {
    "family": (
        "authority.icp",
        "Family residence visa",
        "A resident can sponsor a spouse's family residence visa when their monthly income "
        "meets the minimum threshold and they hold a registered tenancy contract.",
    ),
    "tawtheeq": (
        "authority.dmt",
        "Tawtheeq tenancy registration",
        "Tenancy contracts in Abu Dhabi are registered through Tawtheeq on the TAMM platform.",
    ),
    "adgm": (
        "authority.adgm_ra",
        "ADGM incorporation",
        "Companies incorporate in the Abu Dhabi Global Market through the ADGM online registry.",
    ),
}


async def _ingest(owner_db: Database, marker: str) -> dict[str, GovernanceDocument]:
    docs: dict[str, GovernanceDocument] = {}
    async with owner_db.public_session() as session:
        for key, (authority, title, content) in PASSAGES.items():
            doc = GovernanceDocument(
                source_url=f"https://example.gov.ae/{marker}/{key}",
                title=title,
                authority=authority,
                document_type="guidance",
                retrieved_at=datetime.now(UTC),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                is_official=True,
            )
            session.add(doc)
            await session.flush()
            [vector] = await EMBEDDER.embed([f"{title}\n{content}"])
            session.add(
                GovernanceChunk(
                    document_id=doc.id,
                    chunk_index=0,
                    content=content,
                    context=title,
                    section="Overview",
                    embedding=vector,
                    embedding_model=MODEL,
                )
            )
            docs[key] = doc
        await session.commit()
    return docs


async def _query(db: Database, text: str, **filters: object) -> list[str]:
    [vector] = await EMBEDDER.embed([text])
    async with db.public_session() as session:
        hits = await similarity_search(session, vector, k=3, embedding_model=MODEL, **filters)  # type: ignore[arg-type]
    return [doc.title for _, doc, _ in hits]


async def test_nearest_passage_first(owner_db: Database, app_db: Database) -> None:
    await _ingest(owner_db, uuid4().hex)
    titles = await _query(app_db, "how do I sponsor my spouse's residence visa")
    assert titles[0] == "Family residence visa"
    titles = await _query(app_db, "register my tenancy contract on TAMM")
    assert titles[0] == "Tawtheeq tenancy registration"


async def test_hits_carry_citation_fields_and_distance(
    owner_db: Database, app_db: Database
) -> None:
    await _ingest(owner_db, uuid4().hex)
    [vector] = await EMBEDDER.embed(["ADGM online registry incorporation"])
    async with app_db.public_session() as session:
        hits = await similarity_search(session, vector, k=5, embedding_model=MODEL)
    chunk, doc, distance = hits[0]
    assert doc.title == "ADGM incorporation" and doc.source_url.startswith("https://")
    assert chunk.page_or_section == "Overview"  # generated column
    assert 0.0 <= distance < 1.0
    assert [d for _, _, d in hits] == sorted(d for _, _, d in hits)


async def test_filters_by_authority(owner_db: Database, app_db: Database) -> None:
    await _ingest(owner_db, uuid4().hex)
    titles = await _query(app_db, "sponsor my spouse residence visa", authorities=["authority.dmt"])
    assert set(titles) == {"Tawtheeq tenancy registration"}


async def test_only_compares_vectors_from_the_same_embedder(app_db: Database) -> None:
    [vector] = await EMBEDDER.embed(["family residence visa"])
    async with app_db.public_session() as session:
        assert await similarity_search(session, vector, k=3, embedding_model="other-model") == []


async def test_superseded_versions_are_not_retrieved(owner_db: Database, app_db: Database) -> None:
    docs = await _ingest(owner_db, uuid4().hex)
    async with owner_db.public_session() as session:
        await session.execute(
            update(GovernanceDocument)
            .where(GovernanceDocument.id == docs["family"].id)
            .values(superseded_at=datetime.now(UTC))
        )
        await session.commit()
    [vector] = await EMBEDDER.embed(["sponsor spouse family residence visa"])
    async with app_db.public_session() as session:
        hits = await similarity_search(session, vector, k=20, embedding_model=MODEL)
    assert docs["family"].id not in {doc.id for _, doc, _ in hits}


async def test_lexical_search(owner_db: Database, app_db: Database) -> None:
    await _ingest(owner_db, uuid4().hex)
    async with app_db.public_session() as session:
        hits = await lexical_search(session, "Tawtheeq", k=50)
    assert any(doc.title == "Tawtheeq tenancy registration" for _, doc, _ in hits)


async def test_runtime_role_cannot_write_the_corpus(app_db: Database) -> None:
    import pytest
    from sqlalchemy.exc import DBAPIError

    async with app_db.public_session() as session:
        session.add(
            GovernanceDocument(
                source_url="https://example.gov.ae/injected",
                title="Injected",
                document_type="guidance",
                retrieved_at=datetime.now(UTC),
                content_hash="0" * 64,
                is_official=True,
            )
        )
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.commit()
