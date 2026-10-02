"""Research engines, source processing and adapters, with fake third parties (no services)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.web_fetch import FetchedPage, UnsafeUrl, assert_public_url, html_to_text
from app.adapters.web_search import OpenAIWebResearcher, WebCitation, WebResearchResult
from app.core.errors import UpstreamError
from app.domain.enums import ConsentStatus, EvidenceKind
from app.research.engines import LiveResearchEngine, SnapshotResearchEngine, to_candidates
from app.research.processing import (
    ContactVerifier,
    SourceProcessor,
    address_on_page,
    email_on_page,
    phone_on_page,
)
from app.research.profile import ProfileFacts, ResearchProfile, build_research_profile
from app.research.prompts import ExtractedContact, ExtractedItem, Extraction
from app.research.sources import canonicalize_url
from app.research.types import (
    Candidate,
    CategoryFindings,
    ClaimedSourceType,
    ContactCandidate,
    ContactKind,
    ResearchCategory,
    ResearchMode,
    SourceLabel,
    SourceRef,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
TODAY = NOW.date()


def plain_profile(**overrides: Any) -> ResearchProfile:
    facts = ProfileFacts()
    for key, value in overrides.items():
        setattr(facts, key, value)
    return build_research_profile(facts)


class FakeFetcher:
    mode = "live"

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch_text(self, url: str) -> FetchedPage | None:
        self.calls.append(url)
        text = self.pages.get(url)
        return FetchedPage(url=url, final_url=url, text=text, fetched_at=NOW) if text else None


def findings(
    candidates: list[Candidate],
    urls: list[str],
    category: ResearchCategory = ResearchCategory.COMMUNITY,
) -> CategoryFindings:
    return CategoryFindings(
        category=category,
        mode=ResearchMode.LIVE,
        candidates=candidates,
        sources={
            canonicalize_url(u) or u: SourceRef(url=u, title=f"Page {i}", retrieved_at=NOW)
            for i, u in enumerate(urls)
        },
    )


def candidate(**overrides: Any) -> Candidate:
    base: dict[str, Any] = {
        "category": ResearchCategory.COMMUNITY,
        "title": "Abu Dhabi Striders",
        "summary": "A running club for all levels.",
        "relevance": "Matches your interest in running.",
        "claim_kind": EvidenceKind.COMMUNITY_WEB,
        "primary_url": "https://striders.example.org/",
        "claimed_source_type": ClaimedSourceType.ORGANIZATION_SITE,
    }
    base.update(overrides)
    return Candidate(**base)


async def process(
    items: list[Candidate],
    urls: list[str],
    *,
    pages: dict[str, str] | None = None,
    profile: ResearchProfile | None = None,
    category: ResearchCategory = ResearchCategory.COMMUNITY,
) -> list[Any]:
    processor = SourceProcessor(ContactVerifier(FakeFetcher(pages or {})))
    return await processor.process(findings(items, urls, category), profile or plain_profile(), NOW)


class TestProcessing:
    async def test_future_last_checked_is_never_published(self) -> None:
        raw = findings([candidate()], ["https://striders.example.org/"])
        raw.sources = {
            key: replace(source, retrieved_at=NOW + timedelta(days=1))
            for key, source in raw.sources.items()
        }
        processor = SourceProcessor(ContactVerifier(FakeFetcher({})))
        assert await processor.process(raw, plain_profile(), NOW) == []

    async def test_ungrounded_urls_are_dropped(self) -> None:
        results = await process([candidate(primary_url="https://invented.example/")], [])
        assert results == []

    async def test_a_grounded_supporting_url_can_stand_in(self) -> None:
        item = candidate(
            primary_url="https://invented.example/",
            source_urls=["https://striders.example.org/?utm_source=x"],
        )
        [result] = await process([item], ["https://striders.example.org/"])
        assert result.primary.url == "https://striders.example.org/"
        assert "primary source replaced" in result.notes[0]

    async def test_web_pages_never_become_law(self) -> None:
        item = candidate(
            category=ResearchCategory.CULTURE,
            title="Public decency rules",
            claim_kind=EvidenceKind.AUTHORITATIVE_REQUIREMENT,
            primary_url="https://someblog.example.com/uae-rules",
            claimed_source_type=ClaimedSourceType.GOVERNMENT,
        )
        results = await process(
            [item], ["https://someblog.example.com/uae-rules"], category=ResearchCategory.CULTURE
        )
        assert results == []

    async def test_official_citation_is_promoted_for_official_claims(self) -> None:
        item = candidate(
            category=ResearchCategory.LIFESTYLE,
            title="Midday break",
            claim_kind=EvidenceKind.AUTHORITATIVE_REQUIREMENT,
            primary_url="https://news.example.com/midday",
            source_urls=["https://u.ae/en/information-and-services/jobs/midday"],
        )
        urls = [
            "https://news.example.com/midday",
            "https://u.ae/en/information-and-services/jobs/midday",
        ]
        [result] = await process([item], urls, category=ResearchCategory.LIFESTYLE)
        assert result.claim_kind is EvidenceKind.OFFICIAL_GUIDANCE
        assert result.source_label is SourceLabel.OFFICIAL
        assert result.primary.url.startswith("https://u.ae/")
        assert [c.is_primary for c in result.citations] == [True, False]

    async def test_faith_results_are_filtered_without_opt_in(self) -> None:
        church = candidate(
            title="St Andrew's Church community", primary_url="https://church.example/"
        )
        flagged = candidate(
            title="Friday gathering", primary_url="https://g.example/", involves_faith=True
        )
        urls = ["https://church.example/", "https://g.example/", "https://striders.example.org/"]
        results = await process([church, flagged, candidate()], urls)
        assert [r.title for r in results] == ["Abu Dhabi Striders"]
        opted_in = plain_profile(faith_consent=ConsentStatus.GRANTED)
        assert len(await process([church, flagged, candidate()], urls, profile=opted_in)) == 3

    async def test_culture_keeps_civic_ramadan_guidance(self) -> None:
        item = candidate(
            category=ResearchCategory.CULTURE,
            title="Ramadan etiquette for everyone",
            claim_kind=EvidenceKind.OFFICIAL_GUIDANCE,
            primary_url="https://u.ae/en/ramadan",
        )
        results = await process(
            [item], ["https://u.ae/en/ramadan"], category=ResearchCategory.CULTURE
        )
        assert results and results[0].claim_kind is EvidenceKind.OFFICIAL_GUIDANCE

    async def test_past_events_are_dropped(self) -> None:
        past = candidate(
            category=ResearchCategory.EVENTS,
            title="Old festival",
            primary_url="https://e.example/old",
            event_starts_on=TODAY - timedelta(days=10),
        )
        upcoming = candidate(
            category=ResearchCategory.EVENTS,
            title="New festival",
            primary_url="https://e.example/new",
            event_starts_on=TODAY + timedelta(days=10),
        )
        results = await process(
            [past, upcoming],
            ["https://e.example/old", "https://e.example/new"],
            category=ResearchCategory.EVENTS,
        )
        assert [r.title for r in results] == ["New festival"]

    async def test_only_contacts_found_on_the_cited_page_survive(self) -> None:
        url = "https://striders.example.org/"
        item = candidate(
            contacts=[
                ContactCandidate(ContactKind.PHONE, "+971 2 123 4567", url),
                ContactCandidate(ContactKind.PHONE, "+971 2 999 0000", url),  # invented
                ContactCandidate(ContactKind.EMAIL, "hello@striders.example.org", url),
                ContactCandidate(ContactKind.EMAIL, "fake@striders.example.org", url),  # invented
                ContactCandidate(ContactKind.WEBSITE, "https://striders.example.org/join", url),
                ContactCandidate(ContactKind.WEBSITE, "https://phishy.example.net", url),
                ContactCandidate(ContactKind.PHONE, "02 123 4567", "https://unread.example/"),
            ]
        )
        page = "Call us on 02-123-4567 or write to <a>Hello@Striders.example.org</a>."
        [result] = await process([item], [url], pages={url: page})
        kept = {(c.kind, c.value) for c in result.contacts}
        assert kept == {
            (ContactKind.PHONE, "+971 2 123 4567"),
            (ContactKind.EMAIL, "hello@striders.example.org"),
            (ContactKind.WEBSITE, "https://striders.example.org/join"),
        }
        assert any("unverified contact" in n for n in result.notes)

    async def test_unfetchable_pages_mean_no_contacts(self) -> None:
        url = "https://striders.example.org/"
        item = candidate(contacts=[ContactCandidate(ContactKind.PHONE, "+971 2 123 4567", url)])
        [result] = await process([item], [url], pages={})
        assert result.contacts == []

    async def test_duplicates_merge_and_results_rank(self) -> None:
        a = candidate(
            title="Hub71",
            primary_url="https://hub71.com/",
            category=ResearchCategory.PROFESSIONAL_NETWORK,
        )
        b = candidate(
            title="Hub71 Abu Dhabi",
            primary_url="https://hub71.com/?utm_medium=x",
            source_urls=["https://www.thenationalnews.com/hub71"],
            category=ResearchCategory.PROFESSIONAL_NETWORK,
        )
        c = candidate(
            title="A forum thread",
            primary_url="https://www.reddit.com/r/abudhabi/x",
            claimed_source_type=ClaimedSourceType.COMMUNITY_PLATFORM,
            category=ResearchCategory.PROFESSIONAL_NETWORK,
        )
        urls = [
            "https://hub71.com/",
            "https://www.thenationalnews.com/hub71",
            "https://www.reddit.com/r/abudhabi/x",
        ]
        results = await process([c, a, b], urls, category=ResearchCategory.PROFESSIONAL_NETWORK)
        assert results[0].title.startswith("Hub71")
        assert len(results) == 2
        hub = results[0]
        assert {x.canonical_url for x in hub.citations} == {
            "https://hub71.com",
            "https://thenationalnews.com/hub71",
        }
        assert sum(x.is_primary for x in hub.citations) == 1

    async def test_results_are_capped(self) -> None:
        items = [
            candidate(title=f"Club {n}", primary_url=f"https://c{n}.example/") for n in range(12)
        ]
        results = await process(items, [f"https://c{n}.example/" for n in range(12)])
        assert len(results) == 6

    @pytest.mark.parametrize(
        ("check", "value", "text", "expected"),
        [
            (phone_on_page, "+971 2 123 4567", "tel 00971-2-1234567", True),
            (phone_on_page, "123", "123", False),
            (email_on_page, "a@b.ae", "Contact A@B.AE", True),
            (email_on_page, "not-an-email", "not-an-email", False),
            (address_on_page, "Al Mushrif, Abu Dhabi", "located in Al-Mushrif Abu Dhabi.", True),
        ],
    )
    def test_contact_matchers(self, check: Any, value: str, text: str, expected: bool) -> None:
        assert check(value, text) is expected


# --- live engine ------------------------------------------------------------------------


class FakeWeb:
    provider = "fake"
    mode = "live"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, list[str] | None]] = []
        self.fail = fail

    async def research(
        self,
        *,
        query: str,
        instructions: str,
        allowed_domains: list[str] | None = None,
        depth: str = "quick",
    ) -> WebResearchResult:
        self.calls.append((query, depth, allowed_domains))
        if self.fail:
            raise UpstreamError("down")
        n = len(self.calls)
        return WebResearchResult(
            query=query,
            answer=f"Notes {n}: Abu Dhabi Striders is a running club [source].",
            citations=[
                WebCitation(url=f"https://site{n}.example/", title=f"Site {n}", snippet="club")
            ],
            retrieved_at=NOW,
            provider="fake",
        )


class FakeLLM:
    provider = "fake"
    mode = "live"

    def __init__(self, extractions: list[Extraction]) -> None:
        self.extractions = extractions
        self.inputs: list[str] = []

    async def structured(
        self, *, purpose: str, instructions: str, input: Any, schema: type, tier: str = "reasoning"
    ) -> Any:
        assert purpose == "research.extract"
        assert "Do not guess or assume any religion" in instructions
        self.inputs.append(input)
        return self.extractions[min(len(self.inputs) - 1, len(self.extractions) - 1)]

    async def text(self, **_: Any) -> str:  # pragma: no cover
        raise NotImplementedError


def item(url: str, **overrides: Any) -> ExtractedItem:
    base: dict[str, Any] = {
        "title": "Abu Dhabi Striders",
        "summary": "Running club.",
        "relevance": "Good for newcomers.",
        "claim_kind": "community_information",
        "source_url": url,
        "supporting_urls": [],
        "source_type": "organization_site",
        "fact_keys": ["interests", "made_up"],
        "involves_faith": False,
        "contacts": [],
        "event_start": None,
        "event_end": None,
        "event_timing": None,
    }
    base.update(overrides)
    return ExtractedItem(**base)


async def no_progress(message: str, fraction: float | None) -> None:
    return None


class TestLiveEngine:
    async def test_agentic_search_runs_a_follow_up_round_when_coverage_is_thin(self) -> None:
        web = FakeWeb()
        llm = FakeLLM(
            [
                Extraction(
                    items=[item("https://site1.example/")],
                    follow_up_queries=["Striders official website"],
                ),
                Extraction(
                    items=[
                        item("https://site1.example/"),
                        item("https://site4.example/", title="Club B"),
                        item("https://site5.example/", title="Club C"),
                    ],
                    follow_up_queries=[],
                ),
            ]
        )
        engine = LiveResearchEngine(web, llm, fetcher=FakeFetcher({}))  # type: ignore[arg-type]
        found = await engine.research(
            ResearchCategory.COMMUNITY, plain_profile(), today=TODAY, progress=no_progress
        )
        assert len(llm.inputs) == 2  # extraction re-run over all notes after the follow-up
        assert web.calls[-1][0] == "Striders official website Abu Dhabi"
        assert {depth for _, depth, _ in web.calls} == {"agentic"}
        assert len(found.candidates) == 3
        assert found.candidates[0].fact_keys == ["interests"]
        assert "SOURCES (cite these URLs exactly)" in llm.inputs[-1]

    async def test_quick_categories_do_one_round(self) -> None:
        web = FakeWeb()
        llm = FakeLLM([Extraction(items=[], follow_up_queries=["more"])])
        engine = LiveResearchEngine(web, llm, fetcher=FakeFetcher({}))  # type: ignore[arg-type]
        await engine.research(
            ResearchCategory.STARTER_KIT, plain_profile(), today=TODAY, progress=no_progress
        )
        assert len(llm.inputs) == 1
        assert all(depth == "quick" for _, depth, _ in web.calls)

    async def test_search_outage_fails_the_category(self) -> None:
        engine = LiveResearchEngine(FakeWeb(fail=True), FakeLLM([]), fetcher=FakeFetcher({}))  # type: ignore[arg-type]
        with pytest.raises(UpstreamError):
            await engine.research(
                ResearchCategory.CULTURE, plain_profile(), today=TODAY, progress=no_progress
            )

    async def test_faith_is_not_researched_without_opt_in(self) -> None:
        web = FakeWeb()
        engine = LiveResearchEngine(web, FakeLLM([]), fetcher=FakeFetcher({}))  # type: ignore[arg-type]
        found = await engine.research(
            ResearchCategory.FAITH_AND_WORSHIP, plain_profile(), today=TODAY, progress=no_progress
        )
        assert web.calls == [] and found.candidates == []

    def test_extraction_mapping(self) -> None:
        extraction = Extraction(
            items=[
                item(
                    "https://u.ae/x",
                    claim_kind="law",
                    source_type="government",
                    event_start="2026-11-20",
                    event_end="not a date",
                    contacts=[
                        ExtractedContact(kind="phone", value="800", source_url="https://u.ae/x")
                    ],
                ),
                item("", title="no url"),
            ],
            follow_up_queries=[],
        )
        [c] = to_candidates(extraction, ResearchCategory.FAITH_AND_WORSHIP)
        assert c.claim_kind is EvidenceKind.AUTHORITATIVE_REQUIREMENT
        assert c.claimed_source_type is ClaimedSourceType.GOVERNMENT
        assert c.event_starts_on == date(2026, 11, 20) and c.event_ends_on is None
        assert c.involves_faith  # everything in the faith category is faith content
        assert c.contacts[0].kind is ContactKind.PHONE


class TestSnapshotEngine:
    async def test_offline_research_is_deterministic_and_grounded(self) -> None:
        engine = SnapshotResearchEngine()
        p = plain_profile(profession="founder", relocation_type=None)
        first = await engine.research(
            ResearchCategory.PROFESSIONAL_NETWORK, p, today=TODAY, progress=no_progress
        )
        second = await engine.research(
            ResearchCategory.PROFESSIONAL_NETWORK, p, today=TODAY, progress=no_progress
        )
        assert [c.title for c in first.candidates] == [c.title for c in second.candidates]
        assert first.candidates
        assert all(canonicalize_url(c.primary_url) in first.sources for c in first.candidates)
        processed = await SourceProcessor(ContactVerifier(engine.fetcher)).process(first, p, NOW)
        assert processed and all(r.contacts == [] for r in processed)

    async def test_law_tier_survives_processing_offline(self) -> None:
        engine = SnapshotResearchEngine()
        p = plain_profile()
        found = await engine.research(
            ResearchCategory.STARTER_KIT, p, today=TODAY, progress=no_progress
        )
        processed = await SourceProcessor(ContactVerifier(engine.fetcher)).process(found, p, NOW)
        kinds = {r.claim_kind for r in processed}
        assert EvidenceKind.AUTHORITATIVE_REQUIREMENT in kinds
        for r in processed:
            if r.claim_kind in (
                EvidenceKind.AUTHORITATIVE_REQUIREMENT,
                EvidenceKind.OFFICIAL_GUIDANCE,
            ):
                assert r.source_label is SourceLabel.OFFICIAL


# --- adapters -------------------------------------------------------------------------------


class _Responses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


class TestWebSearchAdapter:
    async def test_citations_snippets_and_agentic_options(self) -> None:
        text = "Intro. Hub71 supports founders in Abu Dhabi. Other text."
        start = text.index("Hub71")
        response = SimpleNamespace(
            output_text=text,
            output=[
                SimpleNamespace(
                    type="web_search_call",
                    action=SimpleNamespace(
                        query="founder programmes Abu Dhabi",
                        queries=None,
                        sources=[SimpleNamespace(url="https://hub71.com/")],
                    ),
                ),
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            text=text,
                            annotations=[
                                SimpleNamespace(
                                    type="url_citation",
                                    url="https://hub71.com/",
                                    title="Hub71",
                                    start_index=start,
                                    end_index=start + 40,
                                )
                            ],
                        )
                    ],
                ),
            ],
        )
        responses = _Responses(response)
        client = SimpleNamespace(responses=responses)
        researcher = OpenAIWebResearcher(client, model="m")  # type: ignore[arg-type]
        result = await researcher.research(
            query="q", instructions="i", allowed_domains=["u.ae"], depth="agentic"
        )
        assert result.citations[0].url == "https://hub71.com/"
        assert (
            result.citations[0].snippet and "Hub71 supports founders" in result.citations[0].snippet
        )
        assert result.searches == ["founder programmes Abu Dhabi"]
        assert result.sources_consulted == ["https://hub71.com/"]
        sent = responses.kwargs
        assert sent["reasoning"] == {"effort": "medium"} and sent["max_tool_calls"] == 10
        tool = sent["tools"][0]
        assert tool["filters"] == {"allowed_domains": ["u.ae"]}
        assert tool["user_location"]["city"] == "Abu Dhabi"
        assert sent["store"] is False


class TestPageFetcherSafety:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://localhost/admin",
            "http://10.0.0.5/",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/",
            "file:///etc/passwd",
            "https://example.com:8443/",
            "http://192.168.1.1/",
        ],
    )
    async def test_refuses_non_public_urls(self, url: str) -> None:
        with pytest.raises(UnsafeUrl):
            await assert_public_url(url)

    def test_html_to_text_keeps_contact_links_and_drops_scripts(self) -> None:
        html = (
            "<html><script>var phone='000'</script><p>Visit us</p>"
            "<a href='mailto:hi@club.ae?subject=x'>Email</a>"
            "<a href='tel:+97121234567'>Call</a></html>"
        )
        text = html_to_text(html)
        assert "Visit us" in text and "hi@club.ae" in text and "+97121234567" in text
        assert "000" not in text


async def test_personal_matches_outrank_equally_good_generic_results() -> None:
    generic = candidate(title="Newcomers club", primary_url="https://a.example/")
    personal = candidate(
        title="Home-country centre", primary_url="https://b.example/", fact_keys=["background"]
    )
    results = await process([generic, personal], ["https://a.example/", "https://b.example/"])
    assert [r.title for r in results] == ["Home-country centre", "Newcomers club"]
    assert results[0].quality_score == results[1].quality_score  # the score stays source-only


async def test_results_record_the_user_facts_behind_their_relevance() -> None:
    facts = ProfileFacts(
        interests=["running"],
        community_consent=ConsentStatus.GRANTED,
        fact_ids={"interests": ["fact-running"]},
    )
    personal = candidate(fact_keys=["interests"])
    [result] = await process(
        [personal], ["https://striders.example.org/"], profile=build_research_profile(facts)
    )
    assert result.fact_ids == ["fact-running"]
