"""Knowledge layer against real Postgres + pgvector: ingestion, retrieval, ranking,
filters, graph relationships and the HTTP endpoints."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.embeddings import HashingEmbedder
from app.core.config import Settings
from app.db.models.governance import GovernanceChunk, GovernanceDocument
from app.db.models.graph import GraphEdge, GraphEdgeEvidence, GraphNode, GraphNodeEvidence
from app.db.session import Database
from app.domain.enums import EvidenceKind, GraphType
from app.knowledge.corpus import Corpus, load_corpus, parse_sources
from app.knowledge.ingest import ingest_corpus
from app.knowledge.retrieval import retrieve
from app.knowledge.schemas import EvidenceCaveat, RetrievalFilters
from app.knowledge.seed import seed_knowledge
from app.knowledge.sources import SourceFamily
from app.main import create_app
from tests.integration.conftest import APP_URL

EMBEDDER = HashingEmbedder()


@pytest.fixture(scope="session", autouse=True)
async def knowledge_seeded(owner_db: Database) -> None:
    """Seed the knowledge layer (idempotent: harmless if the platform seed already did)."""
    async with owner_db.public_session() as session:
        await seed_knowledge(session, EMBEDDER)
        await session.commit()


def _record(key: str, url: str, authority: str, text: str, **kw: Any) -> dict[str, Any]:
    return {
        "key": key,
        "title": f"Test page {key}",
        "url": url,
        "authority": authority,
        "source_type": "service_page",
        "retrieved_at": kw.pop("retrieved_at", "2026-09-28"),
        "topics": ["residency"],
        "verification": "fetched",
        "passages": [{"key": "p", "excerpt": "quote", "states_requirement": True, "text": text}],
        **kw,
    }


def _corpus(*records: dict[str, Any]) -> Corpus:
    parsed, problems = parse_sources(records, origin="test", now=datetime.now(UTC))
    assert problems == []
    return Corpus(sources=parsed)


# --- retrieval -------------------------------------------------------------------------------


async def test_semantic_retrieval_returns_official_evidence(app_db: Database) -> None:
    async with app_db.public_session() as session:
        found = await retrieve(
            session, EMBEDDER, "how do I sponsor my wife's residence visa", top_k=5
        )
    assert found.evidence, found.retrieval
    assert found.retrieval.mode in {"hybrid", "vector", "lexical"}
    for evidence in found.evidence:
        assert evidence.source_url.startswith("https://")
        assert evidence.evidence_kind is not EvidenceKind.COMMUNITY_WEB
        assert evidence.source_title and evidence.retrieved_at and evidence.claim
    assert [e.rank for e in found.evidence] == list(range(1, len(found.evidence) + 1))
    top = " ".join(e.claim.lower() for e in found.evidence[:3])
    assert "spouse" in top or "family" in top


async def test_top_k_is_respected(app_db: Database) -> None:
    async with app_db.public_session() as session:
        for k in (1, 3, 7):
            found = await retrieve(session, EMBEDDER, "residence visa documents", top_k=k)
            assert len(found.evidence) <= k


async def test_authority_filter(app_db: Database) -> None:
    async with app_db.public_session() as session:
        found = await retrieve(
            session,
            EMBEDDER,
            "residence visa",
            filters=RetrievalFilters(authorities=["authority.icp"]),
            top_k=10,
        )
    assert found.evidence
    assert {e.authority_key for e in found.evidence} == {"authority.icp"}


async def test_source_family_and_topic_filters(app_db: Database) -> None:
    async with app_db.public_session() as session:
        by_family = await retrieve(
            session,
            EMBEDDER,
            "company registration licence",
            filters=RetrievalFilters(source_families=[SourceFamily.ADGM]),
            top_k=10,
        )
        by_topic = await retrieve(
            session,
            EMBEDDER,
            "licence",
            filters=RetrievalFilters(topics=["driving"]),  # type: ignore[list-item]
            top_k=10,
        )
    assert by_family.evidence
    assert {e.source_family for e in by_family.evidence} == {SourceFamily.ADGM}
    assert by_topic.evidence
    assert all("driving" in {t.value for t in e.topics} for e in by_topic.evidence)


async def test_governance_scope(app_db: Database) -> None:
    async with app_db.public_session() as session:
        found = await retrieve(
            session,
            EMBEDDER,
            "documents",
            filters=RetrievalFilters(governance_keys=["service.family_residence_visa"]),
            top_k=10,
        )
    assert found.evidence
    assert all("service.family_residence_visa" in e.governance_keys for e in found.evidence)


async def test_source_ranking_prefers_higher_priority_publishers(owner_db: Database) -> None:
    phrase = "zqvx ranking probe residence permit sponsorship rule"
    corpus = _corpus(
        _record("icp.rank_probe", "https://icp.gov.ae/en/rank-probe", "authority.icp", phrase),
        _record(
            "tamm.rank_probe",
            "https://www.tamm.abudhabi/en/rank-probe",
            "authority.abu_dhabi_government",
            phrase,
        ),
        _record(
            "u_ae.rank_probe", "https://u.ae/en/rank-probe", "authority.uae_government", phrase
        ),
    )
    async with owner_db.public_session() as session:
        await ingest_corpus(session, corpus, EMBEDDER)
        found = await retrieve(
            session,
            EMBEDDER,
            phrase,
            filters=RetrievalFilters(topics=["residency"]),  # type: ignore[list-item]
            top_k=20,
        )
        await session.rollback()
    probes = [e for e in found.evidence if "rank-probe" in e.source_url]
    assert [e.source_priority for e in probes] == [1, 2, 5]
    assert probes[0].score is not None and probes[0].score > probes[-1].score  # type: ignore[operator]


async def test_stale_sources_are_flagged_ranked_lower_and_filterable(owner_db: Database) -> None:
    phrase = "zqvx staleness probe tenancy registration notice"
    stale_date = (datetime.now(UTC) - timedelta(days=400)).date().isoformat()
    corpus = _corpus(
        _record(
            "tamm.stale_probe",
            "https://www.tamm.abudhabi/en/stale-probe",
            "authority.abu_dhabi_government",
            phrase,
            retrieved_at=stale_date,
        ),
        _record(
            "u_ae.fresh_probe", "https://u.ae/en/fresh-probe", "authority.uae_government", phrase
        ),
    )
    async with owner_db.public_session() as session:
        await ingest_corpus(session, corpus, EMBEDDER)
        default = await retrieve(session, EMBEDDER, phrase, top_k=20)
        current_only = await retrieve(
            session, EMBEDDER, phrase, filters=RetrievalFilters(include_stale=False), top_k=20
        )
        await session.rollback()
    probes = [e for e in default.evidence if "probe" in e.source_url]
    assert [p.source_url.rsplit("/", 1)[1] for p in probes] == ["fresh-probe", "stale-probe"]
    stale = probes[1]
    assert EvidenceCaveat.STALE_SOURCE in stale.caveats
    assert stale.evidence_kind is EvidenceKind.OFFICIAL_GUIDANCE
    assert not any("stale-probe" in e.source_url for e in current_only.evidence)
    assert current_only.retrieval.filtered_stale >= 1


async def test_changed_pages_are_versioned_not_overwritten(owner_db: Database) -> None:
    url = "https://u.ae/en/version-probe"
    v1 = _corpus(
        _record("u_ae.version_probe", url, "authority.uae_government", "zqvx version one text.")
    )
    v2 = _corpus(
        _record("u_ae.version_probe", url, "authority.uae_government", "zqvx version two text.")
    )
    async with owner_db.public_session() as session:
        first, _, _ = await ingest_corpus(session, v1, EMBEDDER)
        again, _, _ = await ingest_corpus(session, v1, EMBEDDER)
        changed, _, passages = await ingest_corpus(session, v2, EMBEDDER)
        versions = [
            (v.superseded_at is None)
            for v in (
                await session.execute(
                    select(GovernanceDocument).where(GovernanceDocument.source_url == url)
                )
            ).scalars()
        ]
        found = await retrieve(session, EMBEDDER, "zqvx version text", top_k=10)
        await session.rollback()
    assert (first.inserted, again.unchanged, changed.superseded) == (1, 1, 1)
    assert len(versions) == 2 and sum(versions) == 1
    texts = {e.claim for e in found.evidence if e.source_url == url}
    assert texts == {"zqvx version two text."}
    assert passages["u_ae.version_probe#p"].view.content == "zqvx version two text."


async def test_chunks_record_their_embedder(owner_db: Database) -> None:
    async with owner_db.public_session() as session:
        models = set(
            (await session.execute(select(GovernanceChunk.embedding_model).distinct())).scalars()
        )
    assert EMBEDDER.model_id in models


# --- graph -----------------------------------------------------------------------------------


async def test_every_governance_relationship_cites_official_evidence(app_db: Database) -> None:
    async with app_db.public_session() as session:
        live = (GraphNode.graph_type == GraphType.GOVERNANCE) & GraphNode.valid_to.is_(None)
        nodes = (await session.execute(select(GraphNode.id).where(live))).scalars().all()
        edges = (
            (
                await session.execute(
                    select(GraphEdge.id).where(GraphEdge.graph_type == GraphType.GOVERNANCE)
                )
            )
            .scalars()
            .all()
        )
        cited_nodes = set(
            (await session.execute(select(GraphNodeEvidence.node_id).distinct())).scalars()
        )
        cited_edges = set(
            (await session.execute(select(GraphEdgeEvidence.edge_id).distinct())).scalars()
        )
        unofficial = (
            await session.execute(
                select(func.count())
                .select_from(GraphEdgeEvidence)
                .join(GovernanceDocument, GovernanceDocument.id == GraphEdgeEvidence.document_id)
                .where(GovernanceDocument.is_official.is_(False))
            )
        ).scalar_one()
    assert len(nodes) >= 40 and len(edges) >= 60
    assert set(nodes) <= cited_nodes, "uncited governance node"
    assert set(edges) <= cited_edges, "uncited governance relationship"
    assert unofficial == 0


async def test_requested_relationship_shapes_exist(app_db: Database) -> None:
    async with app_db.public_session() as session:
        src = GraphNode.__table__.alias("src")
        dst = GraphNode.__table__.alias("dst")
        rows = await session.execute(
            select(src.c.entity_type, GraphEdge.relation, dst.c.entity_type)
            .join(src, src.c.id == GraphEdge.source_node_id)
            .join(dst, dst.c.id == GraphEdge.target_node_id)
            .where(GraphEdge.graph_type == GraphType.GOVERNANCE)
            .distinct()
        )
        shapes = {(s, str(getattr(r, "value", r)), t) for s, r, t in rows}
    for shape in (
        ("authority", "provides", "service"),
        ("service", "requires", "requirement"),
        ("service", "requires", "document"),
        ("service", "depends_on", "service"),
        ("service", "available_at", "portal"),
        ("service", "may_require", "appointment"),
        ("eligibility_rule", "applies_to", "service"),
        ("dependency", "satisfied_by", "service"),
    ):
        assert shape in shapes, shape


# --- HTTP ------------------------------------------------------------------------------------


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    assert APP_URL
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=APP_URL,
        document_storage_dir=tmp_path,
        openai_api_key=None,
        adapter_embeddings="demo",
    )
    app = create_app(settings)
    base = f"http://t{settings.api_prefix}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=base) as c:
        yield c
    await app.state.container.aclose()


async def test_search_endpoint(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/knowledge/search",
        params={"q": "medical fitness test", "k": 3, "topic": "medical_fitness"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 < len(body["results"]) <= 3
    first = body["results"][0]
    for field in (
        "id",
        "claim",
        "source_title",
        "source_url",
        "authority",
        "retrieved_at",
        "confidence",
    ):
        assert field in first
    assert body["nodes"], "a matching governance node"


async def test_retrieve_endpoint_validates(client: httpx.AsyncClient) -> None:
    r = await client.post("/knowledge/retrieve", json={"query": "x", "top_k": 500})
    assert r.status_code == 422
    r = await client.post(
        "/knowledge/retrieve",
        json={
            "query": "Emirates ID biometrics",
            "top_k": 4,
            "filters": {"authorities": ["authority.icp"]},
        },
    )
    assert r.status_code == 200, r.text
    assert all(e["authority_key"] == "authority.icp" for e in r.json()["evidence"])


async def test_governance_graph_search(client: httpx.AsyncClient) -> None:
    for q in ("family", "ambulance", "Priya"):
        r = await client.get("/graph/governance", params={"q": q})
        assert r.status_code == 200, (q, r.text)
    keys = {
        n["key"]
        for n in (await client.get("/graph/governance", params={"q": "ambulance"})).json()["nodes"]
    }
    assert "service.emergency_ambulance" in keys


async def test_governance_graph_endpoint(client: httpx.AsyncClient) -> None:
    r = await client.get("/graph/governance")
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {n["entity_type"] for n in body["nodes"]}
    assert {"authority", "service", "document", "portal", "source"} <= kinds
    evidence_ids = {e["id"] for e in body["evidence"]}
    assert any(e["relation"] == "evidenced_by" for e in body["edges"])
    for edge in body["edges"]:
        assert edge["evidence_ids"], edge
        assert set(edge["evidence_ids"]) <= evidence_ids
    focused = (
        await client.get("/graph/governance", params={"focus": "service.family_residence_visa"})
    ).json()
    assert 1 < len(focused["nodes"]) < len(body["nodes"])


async def test_explain_endpoint_traces_fact_to_task(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/knowledge/explain",
        json={
            "requirement": "sponsor my wife",
            "subject": "spouse",
            "facts": [
                {"key": "finance.monthly_income_aed", "value": 25000, "label": "Monthly salary"},
                {"key": "company.jurisdiction", "value": "adgm"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requirement"]["key"] == "service.family_residence_visa"
    checks = {c["id"]: c for c in body["reasoning_inputs"]}
    income = next(
        c for c in checks.values() if c["kind"] == "eligibility" and "income" in c["node_key"]
    )
    assert income["status"] == "met" and income["evidence_ids"]
    links = body["links"]
    chain = [link for link in links if link["check_id"] == income["id"]]
    assert {link["relation"] for link in chain} == {"checked_against", "evidenced_by", "supports"}
    assert any(link["source"] == "fact:finance.monthly_income_aed" for link in chain)
    node_ids = {n["id"] for n in body["nodes"]}
    assert all(c["node_id"] in node_ids for c in checks.values())
    evidence_ids = {e["id"] for e in body["evidence"]}
    assert all(set(c["evidence_ids"]) <= evidence_ids for c in checks.values())
    assert body["next_step"]["action"] in {
        "complete_prerequisite",
        "provide_information",
        "obtain_document",
        "book_appointment",
        "apply",
    }
    assert body["next_step"]["handoff"] is True


async def test_explain_rejects_sensitive_facts(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/knowledge/explain",
        json={
            "requirement": "service.family_residence_visa",
            "facts": [{"key": "person.religion", "value": "x"}],
        },
    )
    assert r.status_code == 422


async def test_gibberish_finds_nothing(client: httpx.AsyncClient) -> None:
    r = await client.get("/knowledge/search", params={"q": "zzqx qqzv"})
    assert r.status_code == 200
    assert r.json()["results"] == [] and r.json()["nodes"] == []


async def test_unknown_requirement_is_a_clean_404(client: httpx.AsyncClient) -> None:
    r = await client.post("/knowledge/explain", json={"requirement": "zzqx qqzv"})
    assert r.status_code == 404
    assert r.json()["code"] == "requirement_not_found"


def test_corpus_hash_is_deterministic() -> None:
    corpus = load_corpus()
    digest = hashlib.sha256("".join(s.content_hash for s in corpus.sources).encode()).hexdigest()
    assert (
        digest
        == hashlib.sha256(
            "".join(s.content_hash for s in load_corpus().sources).encode()
        ).hexdigest()
    )
