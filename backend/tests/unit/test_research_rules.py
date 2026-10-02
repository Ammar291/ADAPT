"""Research privacy, source and catalogue rules (pure, no services)."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.enums import ConsentStatus, EvidenceKind
from app.domain.provenance import is_official_source
from app.research.profile import (
    ProfileFacts,
    ResearchProfile,
    StatedValue,
    build_research_profile,
    mentions_faith,
)
from app.research.queries import build_query_plan, ramadan_is_relevant, sanitize_follow_ups
from app.research.snapshot import load_catalogue, match_entry, select_entries
from app.research.sources import (
    canonicalize_url,
    classify_source,
    freshness_factor,
    needs_recheck,
    quality_score,
    registrable_domain,
    same_result,
)
from app.research.types import (
    ALL_CATEGORIES,
    ClaimedSourceType,
    RelocationType,
    ResearchCategory,
    SourceLabel,
)

GRANTED = ConsentStatus.GRANTED
TODAY = date(2026, 9, 29)
NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def profile(**overrides: object) -> ResearchProfile:
    facts = ProfileFacts(
        relocation_type=RelocationType.BUSINESS,
        profession="software founder",
        interests=["running", "museums"],
        background=StatedValue("IND", user_stated=True),
        faith=StatedValue("Christian", user_stated=True),
    )
    for key, value in overrides.items():
        setattr(facts, key, value)
    return build_research_profile(facts)


class TestConsentAndSensitivity:
    def test_faith_needs_opt_in(self) -> None:
        p = profile()
        assert p.faith is None and not p.faith_opted_in
        assert any("faith" in w for w in p.withheld)

    def test_faith_used_when_stated_and_opted_in(self) -> None:
        p = profile(faith_consent=GRANTED)
        assert p.faith == "Christian" and p.faith_opted_in

    def test_faith_never_taken_unless_user_stated(self) -> None:
        p = profile(faith_consent=GRANTED, faith=StatedValue("Christian", user_stated=False))
        assert p.faith is None

    def test_background_and_interests_need_community_consent(self) -> None:
        p = profile()
        assert p.background is None and p.interests == ()
        p = profile(community_consent=GRANTED)
        assert p.background == "India" and p.interests == ("running", "museums")

    def test_profession_and_relocation_need_no_consent(self) -> None:
        p = profile()
        assert p.profession == "software founder"
        assert p.relocation_type is RelocationType.BUSINESS

    def test_focus_mentioning_faith_is_dropped_without_opt_in(self) -> None:
        assert profile(focus="a church choir").focus is None
        assert profile(focus="a church choir", faith_consent=GRANTED).focus == "a church choir"
        assert profile(focus="running clubs").focus == "running clubs"

    def test_profile_has_no_name_and_prompt_never_guesses_faith(self) -> None:
        assert "name" not in ResearchProfile.model_fields
        facts = profile(community_consent=GRANTED).prompt_facts()
        assert "Do not guess or assume any religion" in facts
        assert "India" in facts

    def test_free_text_is_bounded(self) -> None:
        p = profile(profession="x" * 500, interests=[f"i{n}" for n in range(30)])
        assert len(p.profession or "") <= 80
        assert p.interests == ()  # no community consent
        p = profile(community_consent=GRANTED, interests=[f"i{n}" for n in range(30)])
        assert len(p.interests) == 8

    @pytest.mark.parametrize(
        "text",
        ["St Mary's Church", "Hindu temple", "Eid celebrations", "a prayer group", "Diwali mela"],
    )
    def test_mentions_faith(self, text: str) -> None:
        assert mentions_faith(text)

    @pytest.mark.parametrize(
        "text", ["Churchill Society", "holiday camps", "Abu Dhabi Striders", "Faithfull Road run"]
    )
    def test_does_not_mention_faith(self, text: str) -> None:
        assert not mentions_faith(text)


class TestQueries:
    def _profiles(self) -> list[ResearchProfile]:
        combos = itertools.product(
            [ConsentStatus.NOT_ASKED, ConsentStatus.DECLINED],
            [ConsentStatus.NOT_ASKED, GRANTED],
            list(RelocationType),
        )
        return [
            profile(
                faith_consent=faith,
                community_consent=community,
                relocation_type=relocation,
                background=StatedValue("PAK", user_stated=True),
            )
            for faith, community, relocation in combos
        ]

    def test_no_faith_terms_in_queries_without_opt_in(self) -> None:
        for p in self._profiles():
            for category in ALL_CATEGORIES:
                if category is ResearchCategory.CULTURE:
                    continue  # Ramadan etiquette applies to everyone living in Abu Dhabi
                for planned in build_query_plan(category, p, TODAY):
                    assert not mentions_faith(planned.query), (category, planned.query)

    def test_faith_category_is_never_searched_without_opt_in(self) -> None:
        assert build_query_plan(ResearchCategory.FAITH_AND_WORSHIP, profile(), TODAY) == []

    def test_faith_search_follows_the_stated_faith_only(self) -> None:
        plan = build_query_plan(
            ResearchCategory.FAITH_AND_WORSHIP, profile(faith_consent=GRANTED), TODAY
        )
        assert plan and all("Christian" in q.query for q in plan)
        neutral = build_query_plan(
            ResearchCategory.FAITH_AND_WORSHIP,
            profile(faith_consent=GRANTED, faith=None),
            TODAY,
        )
        assert neutral and "different faiths" in neutral[0].query

    def test_background_query_only_with_community_consent(self) -> None:
        without = build_query_plan(ResearchCategory.COMMUNITY, profile(), TODAY)
        with_ = build_query_plan(
            ResearchCategory.COMMUNITY, profile(community_consent=GRANTED), TODAY
        )
        assert not any("India" in q.query for q in without)
        assert any("India" in q.query for q in with_)

    def test_complex_categories_use_agentic_search(self) -> None:
        community = build_query_plan(ResearchCategory.COMMUNITY, profile(), TODAY)
        starter = build_query_plan(ResearchCategory.STARTER_KIT, profile(), TODAY)
        assert {q.depth for q in community} == {"agentic"}
        assert {q.depth for q in starter} == {"quick"}

    def test_rules_and_guidance_search_official_domains(self) -> None:
        culture = build_query_plan(ResearchCategory.CULTURE, profile(), TODAY)
        assert all(q.allowed_domains and "u.ae" in q.allowed_domains for q in culture)
        assert all("visitabudhabi.ae" not in (q.allowed_domains or ()) for q in culture)

    def test_ramadan_relevance(self) -> None:
        assert ramadan_is_relevant(date(2026, 11, 1))
        assert ramadan_is_relevant(date(2027, 3, 1))
        assert not ramadan_is_relevant(date(2027, 6, 1))
        plan = build_query_plan(ResearchCategory.CULTURE, profile(), date(2026, 11, 1))
        assert any("Ramadan" in q.query for q in plan)

    def test_follow_ups_pass_the_privacy_guard(self) -> None:
        cleaned = sanitize_follow_ups(
            ["Indian mosque near Khalifa City", "official website of ISC", "", "x" * 400],
            ResearchCategory.COMMUNITY,
            profile(),
        )
        assert cleaned[0].query == "official website of ISC Abu Dhabi"
        assert all(not mentions_faith(q.query) for q in cleaned)
        assert len(cleaned) <= 2


class TestSources:
    def test_canonical_urls(self) -> None:
        assert (
            canonicalize_url("http://WWW.Hub71.com/programs/?utm_source=x&b=2&a=1#top")
            == "https://hub71.com/programs?a=1&b=2"
        )
        assert canonicalize_url("https://u.ae/") == canonicalize_url("https://u.ae")
        assert canonicalize_url("javascript:alert(1)") is None
        assert canonicalize_url("ftp://example.com/file") is None

    def test_registrable_domain(self) -> None:
        assert registrable_domain("events.hub71.com") == "hub71.com"
        assert registrable_domain("icp.gov.ae") == "icp.gov.ae"
        assert registrable_domain("https://www.bbc.co.uk/news") == "bbc.co.uk"

    @pytest.mark.parametrize(
        ("url", "claimed", "label"),
        [
            ("https://u.ae/en/about", None, SourceLabel.OFFICIAL),
            ("https://www.tamm.abudhabi/", ClaimedSourceType.OTHER, SourceLabel.OFFICIAL),
            ("https://www.meetup.com/abu-dhabi-runners", None, SourceLabel.COMMUNITY),
            (
                "https://www.thenationalnews.com/x",
                ClaimedSourceType.ORGANIZATION_SITE,
                SourceLabel.GENERAL_WEB,
            ),
            (
                "https://standrewauh.org/",
                ClaimedSourceType.ORGANIZATION_SITE,
                SourceLabel.ORGANIZATION,
            ),
            ("https://standrewauh.org/", None, SourceLabel.GENERAL_WEB),
            # "government" on the model's word is never Official
            ("https://gov-ae.example.com/", ClaimedSourceType.GOVERNMENT, SourceLabel.ORGANIZATION),
            ("http://u.ae/en/about", None, SourceLabel.GENERAL_WEB),  # not https
            ("https://visitabudhabi.ae/en/faqs", None, SourceLabel.GENERAL_WEB),
        ],
    )
    def test_labels(self, url: str, claimed: ClaimedSourceType | None, label: SourceLabel) -> None:
        assert classify_source(url, claimed) is label

    def test_score_prefers_official_and_organisation_sources(self) -> None:
        def score(label: SourceLabel, category: ResearchCategory) -> float:
            return quality_score(label, category, NOW, NOW)

        culture = ResearchCategory.CULTURE
        assert score(SourceLabel.OFFICIAL, culture) > score(SourceLabel.ORGANIZATION, culture)
        assert score(SourceLabel.ORGANIZATION, culture) > score(SourceLabel.COMMUNITY, culture)
        assert score(SourceLabel.COMMUNITY, culture) > score(SourceLabel.GENERAL_WEB, culture)
        community = ResearchCategory.COMMUNITY
        assert score(SourceLabel.ORGANIZATION, community) > score(SourceLabel.ORGANIZATION, culture)

    def test_freshness(self) -> None:
        assert freshness_factor(NOW - timedelta(days=3), NOW) == 1.0
        assert freshness_factor(NOW - timedelta(days=200), NOW) == 0.6
        fresh = quality_score(SourceLabel.OFFICIAL, ResearchCategory.CULTURE, NOW, NOW)
        old = quality_score(
            SourceLabel.OFFICIAL, ResearchCategory.CULTURE, NOW - timedelta(days=60), NOW
        )
        assert 0 < old < fresh <= 1
        assert needs_recheck(NOW - timedelta(days=31), NOW)
        assert not needs_recheck(NOW - timedelta(days=5), NOW)

    def test_duplicates(self) -> None:
        url = "https://hub71.com"
        assert same_result(url, "Hub71", url, "Hub71 Abu Dhabi")
        assert same_result(url, "The Hub71", "https://x.com", "hub71")
        listing = "https://visitabudhabi.ae/en/events"
        assert not same_result(listing, "Frieze Abu Dhabi", listing, "Abu Dhabi Festival")


class TestCatalogue:
    def test_catalogue_loads_real_checked_pages(self) -> None:
        entries = load_catalogue()
        assert len(entries) >= 40
        assert {e.category for e in entries} == set(ALL_CATEGORIES)
        for entry in entries:
            assert entry.url.startswith("https://"), entry.key
            assert entry.retrieved_at.date() <= date.today()
            text = f"{entry.title} {entry.summary}"
            assert not re.search(r"\+?971[\s\d-]{6,}|\b0\d[\s-]?\d{3}[\s-]?\d{4}\b", text), (
                entry.key
            )
            assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), entry.key

    def test_law_only_on_official_pages(self) -> None:
        laws = [
            e for e in load_catalogue() if e.evidence_kind is EvidenceKind.AUTHORITATIVE_REQUIREMENT
        ]
        assert laws
        assert all(is_official_source(e.url) for e in laws)
        official = [
            e for e in load_catalogue() if e.evidence_kind is EvidenceKind.OFFICIAL_GUIDANCE
        ]
        assert all(is_official_source(e.url) for e in official)

    def test_background_entries_need_a_matching_stated_background(self) -> None:
        entries = load_catalogue()
        isc = next(e for e in entries if e.key == "community.india_social_and_cultural_centre")
        assert match_entry(isc, profile()) is None  # no community consent
        assert match_entry(isc, profile(community_consent=GRANTED)) is not None
        other = profile(community_consent=GRANTED, background=StatedValue("FRA", user_stated=True))
        assert match_entry(isc, other) is None

    def test_faith_entries_only_after_opt_in(self) -> None:
        entries = load_catalogue()
        assert (
            select_entries(entries, ResearchCategory.FAITH_AND_WORSHIP, profile(), limit=10) == []
        )
        christian = select_entries(
            entries, ResearchCategory.FAITH_AND_WORSHIP, profile(faith_consent=GRANTED), limit=10
        )
        faiths = {tag for m in christian for tag in m.entry.tags.get("faith", ())}
        assert faiths <= {"christian", "multi"} and "christian" in faiths
        neutral = select_entries(
            entries,
            ResearchCategory.FAITH_AND_WORSHIP,
            profile(faith_consent=GRANTED, faith=None),
            limit=10,
        )
        assert len({t for m in neutral for t in m.entry.tags.get("faith", ())}) > 2

    def test_relevance_explains_the_match(self) -> None:
        entries = load_catalogue()
        founder = select_entries(entries, ResearchCategory.PROFESSIONAL_NETWORK, profile(), limit=6)
        hub71 = next(m for m in founder if m.entry.key == "professional_network.hub71")
        assert "profession" in hub71.fact_keys and "software founder" in hub71.relevance
        worker = select_entries(
            entries,
            ResearchCategory.PROFESSIONAL_NETWORK,
            profile(relocation_type=RelocationType.STUDY, profession=None),
            limit=6,
        )
        assert all("relocation:" not in str(m.entry.tags) for m in worker)

    def test_selection_is_deterministic(self) -> None:
        p = profile(community_consent=GRANTED)
        runs = [
            [m.entry.key for m in select_entries(load_catalogue(), c, p, limit=6)]
            for c in ALL_CATEGORIES
            for _ in range(2)
        ]
        assert runs[0::2] == runs[1::2]

    def test_interests_rank_but_never_hide_city_highlights(self) -> None:
        runner = profile(community_consent=GRANTED, interests=["running"])
        events = select_entries(load_catalogue(), ResearchCategory.EVENTS, runner, limit=6)
        assert len(events) >= 5
        art_lover = profile(community_consent=GRANTED, interests=["art"])
        ranked = select_entries(load_catalogue(), ResearchCategory.EVENTS, art_lover, limit=6)
        assert "interests" in ranked[0].fact_keys

    def test_curated_organisation_sites_are_labelled_organization(self) -> None:
        from app.research.snapshot import to_candidate

        culture = select_entries(load_catalogue(), ResearchCategory.CULTURE, profile(), limit=10)
        louvre = next(m for m in culture if m.entry.key == "culture.louvre_abu_dhabi")
        claimed = to_candidate(louvre).claimed_source_type
        assert classify_source(louvre.entry.url, claimed) is SourceLabel.ORGANIZATION
        meetup = next(e for e in load_catalogue() if e.key == "community.meetup_abu_dhabi")
        assert classify_source(meetup.url, claimed) is SourceLabel.COMMUNITY


class TestFactIds:
    def test_only_used_dimensions_keep_their_fact_ids(self) -> None:
        ids = {
            "profession": ["f-occ"],
            "interests": ["f-int"],
            "background": ["f-nat"],
            "faith": ["f-faith"],
            "relocation_type": ["f-goal"],
        }
        without_consent = profile(fact_ids=ids)
        assert set(without_consent.fact_ids) == {"profession", "relocation_type"}
        full = profile(fact_ids=ids, community_consent=GRANTED, faith_consent=GRANTED)
        assert set(full.fact_ids) == set(ids)
        assert full.fact_ids_for(["interests", "background", "interests"]) == ["f-int", "f-nat"]
        assert full.fact_ids_for(["focus", "journey_goals"]) == []

    def test_unstated_faith_leaves_no_fact_ids(self) -> None:
        p = profile(
            faith_consent=GRANTED,
            faith=StatedValue("Christian", user_stated=False),
            fact_ids={"faith": ["f-faith"]},
        )
        assert "faith" not in p.fact_ids
