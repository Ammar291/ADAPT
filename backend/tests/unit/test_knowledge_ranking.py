"""Source ranking, authority classification and evidence trust (pure, no database)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.enums import EvidenceKind
from app.knowledge.evidence import PassageView, build_evidence, strongest_kind
from app.knowledge.ranking import (
    RankItem,
    embedding_text,
    fuse,
    lexical_query,
    query_terms,
    rank,
)
from app.knowledge.schemas import EvidenceCaveat, Freshness
from app.knowledge.sources import PUBLISHERS, SourceFamily, classify_source

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def item(key: str, relevance: float, priority: int, **kw: object) -> RankItem:
    base: dict[str, object] = {
        "group": key,
        "freshness": Freshness.CURRENT,
        "retrieved_at": NOW - timedelta(days=1),
    }
    base.update(kw)
    return RankItem(key=key, relevance=relevance, priority=priority, **base)  # type: ignore[arg-type]


def view(url: str, authority: str | None, **kw: object) -> PassageView:
    base: dict[str, object] = {
        "document_id": uuid4(),
        "chunk_id": uuid4(),
        "content": "Residents may sponsor their spouse subject to the income requirement.",
        "source_url": url,
        "title": "Sponsoring your family",
        "authority": authority,
        "retrieved_at": NOW - timedelta(days=3),
        "excerpt": "quote",
        "states_requirement": True,
        "verification": "fetched",
    }
    base.update(kw)
    return PassageView(**base)  # type: ignore[arg-type]


class TestSourceClassification:
    def test_priority_order_matches_the_brief(self) -> None:
        cases = {
            ("https://www.tamm.abudhabi/x", "authority.abu_dhabi_government"): 1,
            ("https://u.ae/en/x", "authority.uae_government"): 2,
            ("https://www.adgm.com/x", "authority.adgm"): 3,
            ("https://www.doh.gov.ae/x", "authority.doh"): 4,
            ("https://icp.gov.ae/x", "authority.icp"): 5,
        }
        for (url, authority), expected in cases.items():
            assert classify_source(url, authority).priority == expected, url

    def test_unlisted_official_domain_is_rank_six(self) -> None:
        source = classify_source("https://www.moe.gov.ae/page", None)
        assert source.is_official and source.family is SourceFamily.OFFICIAL_AUTHORITY

    def test_ordinary_web_content_is_never_official(self) -> None:
        for url in (
            "https://visa-help-uae.com/family-visa",
            "http://icp.gov.ae/insecure",
            "https://icp.gov.ae.evil.example/x",
            "https://notu.ae/x",
        ):
            source = classify_source(url, "authority.icp")
            assert not source.is_official, url
            assert source.family is SourceFamily.UNOFFICIAL, url

    def test_mislabelled_publisher_cannot_borrow_a_higher_rank(self) -> None:
        # An ICP page that claims to be published by TAMM ranks as "other official".
        source = classify_source("https://icp.gov.ae/x", "authority.abu_dhabi_government")
        assert source.family is SourceFamily.OFFICIAL_AUTHORITY
        assert source.priority == 6

    def test_every_publisher_is_on_the_allowlist_or_flagged(self) -> None:
        for publisher in PUBLISHERS.values():
            if publisher.key in {"authority.seha"}:
                continue  # official health channel pending allowlist review
            assert classify_source(publisher.base_url, publisher.key).is_official, publisher.key


class TestQueryAnalysis:
    def test_stopwords_and_duplicates_are_dropped(self) -> None:
        assert query_terms("How do I sponsor my wife and my WIFE?") == ["sponsor", "wife"]

    def test_everyday_words_expand_to_official_terms(self) -> None:
        expression = lexical_query("sponsor my wife")
        assert expression is not None
        assert "spouse:*" in expression and "sponsor:*" in expression
        assert "spouse" in embedding_text("visa for my wife")

    def test_tsquery_is_always_safe(self) -> None:
        expression = lexical_query("visa'); DROP TABLE x; -- & | ! :* (")
        assert expression is not None
        assert all(ch.isalnum() or ch in " |:*_" for ch in expression)
        assert lexical_query("?? !!") is None

    def test_short_terms_are_not_prefix_matched(self) -> None:
        expression = lexical_query("visa pass")
        assert expression is not None
        assert "visa:*" not in expression and "pass:*" not in expression


class TestFusion:
    def test_items_in_both_lists_win(self) -> None:
        scores = fuse([("a", 0.9), ("b", 0.8)], [("b", 3.0), ("c", 1.0)])
        assert max(scores, key=scores.__getitem__) == "b"
        assert all(0 < s <= 1 for s in scores.values())

    def test_weak_vector_neighbours_are_dropped(self) -> None:
        scores = fuse([("a", 0.8), ("noise", 0.1)], [])
        assert "noise" not in scores

    def test_empty(self) -> None:
        assert fuse([], []) == {}


class TestSourceRanking:
    def test_equal_relevance_follows_source_priority(self) -> None:
        ranked = rank(
            [item("icp", 0.8, 5), item("tamm", 0.8, 1), item("uae", 0.8, 2), item("adgm", 0.8, 3)],
            top_k=4,
        )
        assert [i.key for i, _ in ranked] == ["tamm", "uae", "adgm", "icp"]

    def test_relevance_still_dominates(self) -> None:
        ranked = rank([item("tamm_weak", 0.3, 1), item("icp_strong", 0.9, 5)], top_k=2)
        assert ranked[0][0].key == "icp_strong"

    def test_stale_source_yields_to_current_one(self) -> None:
        ranked = rank(
            [
                item("tamm_stale", 0.8, 1, freshness=Freshness.STALE),
                item("uae_current", 0.8, 2),
            ],
            top_k=2,
        )
        assert ranked[0][0].key == "uae_current"

    def test_superseded_versions_rank_last(self) -> None:
        ranked = rank([item("old", 0.9, 1, superseded=True), item("new", 0.6, 1)], top_k=2)
        assert ranked[0][0].key == "new"

    def test_ties_prefer_recently_checked(self) -> None:
        ranked = rank(
            [
                item("older", 0.8, 1, retrieved_at=NOW - timedelta(days=30)),
                item("newer", 0.8, 1, retrieved_at=NOW - timedelta(days=2)),
            ],
            top_k=2,
        )
        assert ranked[0][0].key == "newer"

    def test_top_k_min_score_and_per_page_cap(self) -> None:
        items = [item(f"p{i}", 0.9 - i * 0.01, 1, group="same_page") for i in range(5)]
        items.append(item("other", 0.5, 1))
        ranked = rank(items, top_k=10, max_per_group=3)
        assert [i.key for i, _ in ranked] == ["p0", "p1", "p2", "other"]
        assert len(rank(items, top_k=2)) == 2
        assert all(score >= 0.6 for _, score in rank(items, top_k=10, min_score=0.6))


class TestEvidence:
    def test_evidence_object_carries_the_required_fields(self) -> None:
        passage = view(
            "https://u.ae/en/family", "authority.uae_government", section_or_page="Eligibility"
        )
        evidence = build_evidence(passage, now=NOW, score=0.5, rank=1, governance_keys=["b", "a"])
        dumped = evidence.model_dump()
        for name in (
            "id",
            "claim",
            "source_title",
            "source_url",
            "authority",
            "section_or_page",
            "retrieved_at",
            "confidence",
        ):
            assert dumped[name] is not None, name
        assert evidence.id == f"ev_{passage.chunk_id.hex}"
        assert evidence.authority == "UAE Government portal (u.ae)"
        assert evidence.governance_keys == ["a", "b"]

    def test_current_verbatim_requirement_is_authoritative(self) -> None:
        evidence = build_evidence(view("https://u.ae/x", "authority.uae_government"), now=NOW)
        assert evidence.evidence_kind is EvidenceKind.AUTHORITATIVE_REQUIREMENT
        assert evidence.caveats == []

    @pytest.mark.parametrize(
        "change,caveat",
        [
            ({"retrieved_at": NOW - timedelta(days=400)}, EvidenceCaveat.STALE_SOURCE),
            ({"excerpt": "paraphrase"}, EvidenceCaveat.PARAPHRASED),
            (
                {"verification": "search_snippet", "excerpt": "paraphrase"},
                EvidenceCaveat.SNIPPET_ONLY,
            ),
            ({"superseded_at": NOW - timedelta(days=1)}, EvidenceCaveat.SUPERSEDED_SOURCE),
            ({"effective_date": date(2027, 1, 1)}, EvidenceCaveat.NOT_YET_EFFECTIVE),
        ],
    )
    def test_weaker_provenance_is_never_authoritative(
        self, change: dict[str, object], caveat: EvidenceCaveat
    ) -> None:
        strong = build_evidence(view("https://u.ae/x", "authority.uae_government"), now=NOW)
        weak = build_evidence(view("https://u.ae/x", "authority.uae_government", **change), now=NOW)
        assert caveat in weak.caveats
        assert weak.evidence_kind is EvidenceKind.OFFICIAL_GUIDANCE
        assert weak.confidence < strong.confidence

    def test_stale_metadata_is_flagged_not_hidden(self) -> None:
        evidence = build_evidence(
            view(
                "https://u.ae/x", "authority.uae_government", retrieved_at=NOW - timedelta(days=200)
            ),
            now=NOW,
            stale_after_days=180,
        )
        assert evidence.freshness is Freshness.STALE
        assert evidence.retrieved_at == NOW - timedelta(days=200)

    def test_missing_effective_date_is_allowed(self) -> None:
        evidence = build_evidence(view("https://u.ae/x", "authority.uae_government"), now=NOW)
        assert evidence.effective_date is None
        assert EvidenceCaveat.NOT_YET_EFFECTIVE not in evidence.caveats

    def test_unofficial_content_is_community_web(self) -> None:
        evidence = build_evidence(
            view("https://expat-forum.example/visa", "authority.icp"), now=NOW
        )
        assert evidence.evidence_kind is EvidenceKind.COMMUNITY_WEB
        assert EvidenceCaveat.UNOFFICIAL_SOURCE in evidence.caveats
        assert evidence.source_family is SourceFamily.UNOFFICIAL
        assert evidence.confidence < 0.5

    def test_source_priority_shapes_confidence(self) -> None:
        tamm = build_evidence(
            view("https://www.tamm.abudhabi/x", "authority.abu_dhabi_government"), now=NOW
        )
        icp = build_evidence(view("https://icp.gov.ae/x", "authority.icp"), now=NOW)
        assert tamm.source_priority < icp.source_priority
        assert tamm.confidence > icp.confidence

    def test_strongest_kind(self) -> None:
        strong = build_evidence(view("https://u.ae/x", "authority.uae_government"), now=NOW)
        weak = build_evidence(
            view("https://u.ae/y", "authority.uae_government", excerpt="paraphrase"), now=NOW
        )
        assert strongest_kind([weak, strong]) is EvidenceKind.AUTHORITATIVE_REQUIREMENT
        assert strongest_kind([]) is None
