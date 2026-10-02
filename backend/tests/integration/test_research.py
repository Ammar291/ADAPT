"""Research end to end against real Postgres: service -> ARQ task -> graph -> results/events.

The worker task runs in-process with an in-memory checkpointer; third parties are fakes
(the offline snapshot, or scripted web search + extraction for the live path).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.adapters.web_fetch import FetchedPage
from app.adapters.web_search import WebCitation, WebResearchResult
from app.core.errors import Conflict, NotFound
from app.db.models import AgentEvent, AgentRun, Journey, User
from app.db.session import Database
from app.domain.enums import JourneyStatus, RunStatus
from app.domain.principal import Principal
from app.events.notifier import NullNotifier
from app.research import service, tasks
from app.research.contracts import (
    BRIEF_READY_MESSAGE,
    ResearchProfileInput,
    StartResearchRequest,
)
from app.research.engines import LiveResearchEngine, SnapshotResearchEngine
from app.research.models import ResearchCitation, ResearchResult
from app.research.prompts import ExtractedContact, ExtractedItem, Extraction
from app.research.service import ConsentRequired
from app.research.types import ResearchCategory


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, function: str, *, job_id: str, **kwargs: Any) -> str:
        self.calls.append((function, {"job_id": job_id, **kwargs}))
        return f"arq-{job_id}"


async def consent(db: Database, who: Principal, **prefs: str) -> None:
    async with db.user_session(who) as session:
        user = (await session.execute(select(User).where(User.id == who.user_id))).scalar_one()
        await session.execute(
            update(User)
            .where(User.id == who.user_id)
            .values(preferences={**(user.preferences or {}), **prefs})
        )
        await session.commit()


def worker_ctx(db: Database) -> dict[str, Any]:
    adapters = SimpleNamespace(
        web_search=SimpleNamespace(mode="demo"), llm=SimpleNamespace(mode="demo")
    )
    deps = SimpleNamespace(
        db=db, notifier=NullNotifier(), adapters=adapters, checkpointer=InMemorySaver()
    )
    return {"deps": deps}


async def run_worker(db: Database, queue: FakeQueue) -> str:
    function, kwargs = queue.calls[-1]
    assert function == "run_research"
    kwargs = dict(kwargs)
    kwargs.pop("job_id")
    return await tasks.run_research(worker_ctx(db), **kwargs)


async def events(db: Database, who: Principal, run_id: UUID) -> list[dict[str, Any]]:
    async with db.user_session(who) as session:
        rows = await session.execute(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
        )
        return [row.payload for row in rows.scalars()]


@pytest.fixture(autouse=True)
def fast_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks,
        "build_research_engine",
        lambda adapters, **_: SnapshotResearchEngine(pace_seconds=0),
    )


FOUNDER = StartResearchRequest(
    profile=ResearchProfileInput(profession="software founder", relocation_type="business")
)


async def test_start_returns_immediately_and_is_idempotent(
    app_db: Database, alice: Principal
) -> None:
    queue = FakeQueue()
    job = await service.start_research(app_db, queue, alice, FOUNDER)  # type: ignore[arg-type]
    assert job.status is RunStatus.QUEUED
    assert job.events_url == f"/api/agents/{job.run_id}/events"
    states = {s.category: s for s in job.categories}
    assert states[ResearchCategory.FAITH_AND_WORSHIP].status == "skipped"
    assert states[ResearchCategory.FAITH_AND_WORSHIP].reason == "faith_not_opted_in"
    assert queue.calls[0][1]["research_job_id"] == str(job.id)
    assert "Work: software founder" in job.personalised_with

    again = await service.start_research(app_db, queue, alice, FOUNDER)  # type: ignore[arg-type]
    assert again.id == job.id and len(queue.calls) == 1
    forced = await service.start_research(  # type: ignore[arg-type]
        app_db, queue, alice, FOUNDER.model_copy(update={"force": True})
    )
    assert forced.id != job.id


async def test_explicit_sensitive_requests_need_consent(app_db: Database, alice: Principal) -> None:
    queue = FakeQueue()
    cases = [
        StartResearchRequest(profile=ResearchProfileInput(faith="Hindu")),
        StartResearchRequest(categories=[ResearchCategory.FAITH_AND_WORSHIP]),
        StartResearchRequest(focus="a mosque near Khalifa City"),
        StartResearchRequest(profile=ResearchProfileInput(background="India")),
        StartResearchRequest(profile=ResearchProfileInput(interests=["cricket"])),
    ]
    for request in cases:
        with pytest.raises(ConsentRequired) as exc:
            await service.start_research(app_db, queue, alice, request)  # type: ignore[arg-type]
        assert exc.value.extra["consent"] in {"faith_personalization", "community_personalization"}
    assert queue.calls == []


async def test_offline_brief_end_to_end(app_db: Database, alice: Principal) -> None:
    await consent(app_db, alice, community_personalization="granted")
    queue = FakeQueue()
    request = StartResearchRequest(
        profile=ResearchProfileInput(
            profession="software founder",
            relocation_type="business",
            interests=["running", "art"],
            background="India",
        ),
        force=True,
    )
    job = await service.start_research(app_db, queue, alice, request)  # type: ignore[arg-type]
    assert await run_worker(app_db, queue) == "completed"

    detail = await service.get_job_detail(app_db, alice, job.id)
    assert detail.job.status is RunStatus.SUCCEEDED and detail.job.brief_ready
    assert detail.job.mode == "snapshot"
    categories = {r.category for r in detail.results}
    assert ResearchCategory.FAITH_AND_WORSHIP not in categories
    assert {ResearchCategory.COMMUNITY, ResearchCategory.STARTER_KIT} <= categories
    for result in detail.results:
        assert result.citations and result.citations[0].is_primary
        assert result.source_url.startswith("https://")
        assert result.relevance
        assert result.contacts == []  # nothing verifiable offline, so nothing shown
    titles = {r.title for r in detail.results}
    assert "India Social and Cultural Centre (ISC) Abu Dhabi" in titles  # background consented
    assert "Hub71" in titles

    log = await events(app_db, alice, job.run_id)
    kinds = [e["event"] for e in log]
    assert kinds[0] == "run_started" and kinds[-1] == "run_completed"
    assert kinds.index("research_started") < kinds.index("research_completed") < len(kinds) - 1
    completed = [e for e in log if e["event"] == "research_category_completed"]
    assert {e["category"]: e["status"] for e in completed}["faith_and_worship"] == "skipped"
    assert sum(e["status"] == "completed" for e in completed) == 6
    found = [e for e in log if e["event"] == "research_source_found"]
    assert len({e["url"] for e in found}) == len(found)  # each source announced once
    final = next(e for e in log if e["event"] == "research_completed")
    assert final["message"] == BRIEF_READY_MESSAGE == "Your Abu Dhabi Life Brief is ready."
    assert final["result_count"] == len(detail.results)

    page = await service.discover(app_db, alice)
    assert [s.title for s in page.sections] == [
        "Your Communities",
        "Your Faith & Places",
        "Your Professional Network",
        "Local Events",
        "Cultural Guide",
        "Things That May Surprise You",
        "Starter Kit",
    ]
    assert page.message == BRIEF_READY_MESSAGE
    faith = next(s for s in page.sections if s.section == "faith")
    assert faith.status == "skipped" and faith.results == []

    seen = await service.mark_seen(app_db, alice, job.id)
    assert seen.seen_at is not None
    assert (await service.discover(app_db, alice)).message is None

    first = detail.results[0]
    saved = await service.set_saved(app_db, alice, first.id, True)
    assert saved.saved
    later = await service.start_research(app_db, queue, alice, request)  # type: ignore[arg-type]
    assert later.id != job.id
    page = await service.discover(app_db, alice)
    assert [r.id for r in page.saved] == [first.id]  # saves outlive the brief they came from


async def test_live_path_enforces_honesty(
    app_db: Database, alice: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    shared = "https://www.adgm.com/"

    class Web:
        provider, mode = "fake", "live"

        async def research(self, *, query: str, **_: Any) -> WebResearchResult:
            return WebResearchResult(
                query=query,
                answer="notes",
                citations=[
                    WebCitation(url="https://u.ae/en/rules", title="UAE rules"),
                    WebCitation(url="https://blog.example.com/rules", title="A blog"),
                    WebCitation(url="https://club.example.org/", title="Club"),
                    WebCitation(url=shared, title="ADGM"),
                ],
                retrieved_at=now,
                provider="fake",
            )

    def extracted(url: str, **overrides: Any) -> ExtractedItem:
        base: dict[str, Any] = {
            "title": f"Item {url}",
            "summary": "s",
            "relevance": "r",
            "claim_kind": "community_information",
            "source_url": url,
            "supporting_urls": [],
            "source_type": "organization_site",
            "fact_keys": [],
            "involves_faith": False,
            "contacts": [],
            "event_start": None,
            "event_end": None,
            "event_timing": None,
        }
        return ExtractedItem(**{**base, **overrides})

    class LLM:
        provider, mode = "fake", "live"

        async def structured(self, **_: Any) -> Extraction:
            return Extraction(
                items=[
                    extracted(
                        "https://blog.example.com/rules", title="Blog rule", claim_kind="law"
                    ),
                    extracted("https://u.ae/en/rules", title="Official rule", claim_kind="law"),
                    extracted(
                        "https://club.example.org/",
                        title="Club",
                        contacts=[
                            ExtractedContact(
                                kind="email",
                                value="hi@club.example.org",
                                source_url="https://club.example.org/",
                            ),
                            ExtractedContact(
                                kind="phone",
                                value="+971 2 555 0000",
                                source_url="https://club.example.org/",
                            ),
                        ],
                    ),
                    extracted(shared, title="ADGM"),
                    extracted("https://invented.example/", title="Invented"),
                ],
                follow_up_queries=[],
            )

    class Fetcher:
        mode = "live"

        async def fetch_text(self, url: str) -> FetchedPage | None:
            if url == "https://club.example.org/":
                return FetchedPage(
                    url=url, final_url=url, text="Email hi@club.example.org", fetched_at=now
                )
            return None

    monkeypatch.setattr(
        tasks,
        "build_research_engine",
        lambda adapters, **_: LiveResearchEngine(Web(), LLM(), fetcher=Fetcher()),  # type: ignore[arg-type]
    )
    queue = FakeQueue()
    job = await service.start_research(  # type: ignore[arg-type]
        app_db,
        queue,
        alice,
        StartResearchRequest(
            categories=[ResearchCategory.CULTURE, ResearchCategory.PROFESSIONAL_NETWORK],
            force=True,
        ),
    )
    assert await run_worker(app_db, queue) == "completed"
    detail = await service.get_job_detail(app_db, alice, job.id)
    assert detail.job.mode == "live"
    by_title = {(r.category, r.title): r for r in detail.results}
    culture = ResearchCategory.CULTURE
    assert by_title[(culture, "Blog rule")].evidence_kind == "community_web"
    assert by_title[(culture, "Official rule")].evidence_kind == "authoritative_requirement"
    assert by_title[(culture, "Official rule")].source_label == "official"
    club = by_title[(culture, "Club")]
    assert [(c.kind, c.value) for c in club.contacts] == [("email", "hi@club.example.org")]
    assert not any(r.title == "Invented" for r in detail.results)
    log = await events(app_db, alice, job.run_id)
    announced = [e["url"] for e in log if e["event"] == "research_source_found"]
    assert announced.count(shared) == 1  # cited in both categories, announced once


async def test_run_fails_only_when_every_category_fails(
    app_db: Database, alice: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(SnapshotResearchEngine):
        async def research(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "build_research_engine", lambda adapters, **_: Broken())
    queue = FakeQueue()
    job = await service.start_research(  # type: ignore[arg-type]
        app_db,
        queue,
        alice,
        StartResearchRequest(categories=[ResearchCategory.CULTURE], force=True),
    )
    assert await run_worker(app_db, queue) == "failed"
    kinds = [e["event"] for e in await events(app_db, alice, job.run_id)]
    assert kinds.index("research_failed") < kinds.index("run_failed")
    assert kinds[-1] == "run_failed"
    detail = await service.get_job_detail(app_db, alice, job.id)
    assert detail.job.status is RunStatus.FAILED
    assert detail.job.categories[0].status == "failed"


async def test_research_is_private(app_db: Database, alice: Principal, bob: Principal) -> None:
    queue = FakeQueue()
    job = await service.start_research(
        app_db, queue, alice, FOUNDER.model_copy(update={"force": True})
    )  # type: ignore[arg-type]
    await run_worker(app_db, queue)
    with pytest.raises(NotFound):
        await service.get_job_detail(app_db, bob, job.id)
    async with app_db.user_session(bob) as session:
        rows = (await session.execute(select(ResearchResult))).scalars().all()
        citations = (await session.execute(select(ResearchCitation))).scalars().all()
    assert rows == [] and citations == []
    assert (await service.discover(app_db, bob)).job is None


async def test_database_rejects_official_claims_without_official_source(
    app_db: Database, alice: Principal
) -> None:
    queue = FakeQueue()
    job = await service.start_research(
        app_db, queue, alice, FOUNDER.model_copy(update={"force": True})
    )  # type: ignore[arg-type]
    base = {
        "tenant_id": alice.tenant_id,
        "user_id": alice.user_id,
        "job_id": job.id,
        "category": ResearchCategory.CULTURE,
        "title": "t",
        "summary": "s",
        "relevance": "r",
        "source_url": "https://blog.example.com/x",
        "canonical_url": "https://blog.example.com/x",
        "source_title": "Blog",
        "source_domain": "blog.example.com",
        "retrieved_at": datetime.now(UTC),
        "quality_score": 0.5,
    }
    bad = [
        {"evidence_kind": "authoritative_requirement", "source_label": "general_web"},
        {"evidence_kind": "official_guidance", "source_label": "organization"},
        {
            "evidence_kind": "community_web",
            "source_label": "official",
            "source_url": "http://u.ae/x",
        },
        {
            "evidence_kind": "community_web",
            "source_label": "community",
            "source_url": "javascript:alert(1)",
        },
    ]
    for case in bad:
        async with app_db.user_session(alice) as session:
            session.add(ResearchResult(**{**base, **case, "dedupe_key": uuid4().hex}))
            with pytest.raises(IntegrityError):
                await session.commit()


async def test_add_to_journey(app_db: Database, alice: Principal) -> None:
    queue = FakeQueue()
    job = await service.start_research(
        app_db, queue, alice, FOUNDER.model_copy(update={"force": True})
    )  # type: ignore[arg-type]
    await run_worker(app_db, queue)
    result = (await service.get_job_detail(app_db, alice, job.id)).results[0]

    other = await _principal(app_db)
    with pytest.raises(NotFound):
        await service.add_to_journey(app_db, other, result.id, None)

    fresh = await _principal(app_db)
    fresh_queue = FakeQueue()
    fresh_job = await service.start_research(app_db, fresh_queue, fresh, FOUNDER)  # type: ignore[arg-type]
    await run_worker(app_db, fresh_queue)
    fresh_result = (await service.get_job_detail(app_db, fresh, fresh_job.id)).results[0]
    with pytest.raises(Conflict) as exc:
        await service.add_to_journey(app_db, fresh, fresh_result.id, None)
    assert exc.value.code == "journey_required"

    async with app_db.user_session(alice) as session:
        session.add(
            Journey(
                tenant_id=alice.tenant_id,
                user_id=alice.user_id,
                title="My move",
                status=JourneyStatus.ACTIVE,
            )
        )
        await session.commit()
    added = await service.add_to_journey(app_db, alice, result.id, None)
    assert added.journey_node_id is not None
    again = await service.add_to_journey(app_db, alice, result.id, None)
    assert again.journey_node_id == added.journey_node_id
    async with app_db.user_session(alice) as session:
        run = (
            await session.execute(select(AgentRun).where(AgentRun.id == job.run_id))
        ).scalar_one()
    assert run.agent == "research"


async def _principal(db: Database) -> Principal:
    from tests.integration.conftest import make_principal

    return await make_principal(db)


async def test_stored_user_facts_personalise_and_explain_results(
    app_db: Database, alice: Principal
) -> None:
    from app.domain.enums import FactSource
    from app.domain.twin import TwinFact
    from app.personalization import facts as personal

    async with app_db.user_session(alice) as session:
        person = await personal.ensure_node(session, alice, "person")
        [occupation] = await personal.upsert_user_stated(
            session,
            alice,
            node_id=person.id,
            source_ref="test:profile",
            facts={"occupation": TwinFact(value="software founder", source=FactSource.USER_STATED)},
        )
        await session.commit()

    queue = FakeQueue()
    job = await service.start_research(  # type: ignore[arg-type]
        app_db,
        queue,
        alice,
        StartResearchRequest(categories=[ResearchCategory.PROFESSIONAL_NETWORK], force=True),
    )
    assert job.profile.profession == "software founder"  # read from the fact store
    assert await run_worker(app_db, queue) == "completed"
    results = (await service.get_job_detail(app_db, alice, job.id)).results
    matched = [r for r in results if "software founder" in r.relevance]
    assert matched and all(r.fact_ids == [str(occupation.id)] for r in matched)
    generic = [r for r in results if "software founder" not in r.relevance]
    assert all(r.fact_ids == [] for r in generic)

    async with app_db.user_session(alice) as session:
        evidence = await personal.explain(session, matched[0].fact_ids)
    assert [e.fact_id for e in evidence] == [occupation.id]
