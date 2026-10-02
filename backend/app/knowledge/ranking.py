"""Query analysis, rank fusion and source ranking. Pure functions, no I/O.

Retrieval gathers two candidate lists, semantic (pgvector cosine) and lexical (tsvector),
fuses them (weighted score fusion), then weighs each passage by who published it
(source priority) and how recently it was checked (freshness):

    score = relevance x PRIORITY_WEIGHT[priority] x FRESHNESS_WEIGHT[freshness]

so an equally relevant TAMM passage outranks a u.ae one, which outranks ICP, and a stale
page yields to a current one. Relevance still dominates: a highly relevant rank-5
passage beats a barely relevant rank-1 passage.
"""

from __future__ import annotations

import math
import re
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.knowledge.schemas import Freshness

PRIORITY_WEIGHT: dict[int, float] = {1: 1.0, 2: 0.96, 3: 0.92, 4: 0.88, 5: 0.84, 6: 0.80, 7: 0.40}
FRESHNESS_WEIGHT: dict[Freshness, float] = {Freshness.CURRENT: 1.0, Freshness.STALE: 0.85}
SUPERSEDED_WEIGHT = 0.5
# Vector hits weaker than this fraction of the best hit are noise (every query has
# nearest neighbours, relevant or not). Relative, so it works for any embedder.
RELATIVE_VECTOR_FLOOR = 0.5
ABSOLUTE_VECTOR_FLOOR = 0.05
PREFIX_MIN_LENGTH = 5

_TOKEN = re.compile(r"[0-9a-z؀-ۿ]+")

STOPWORDS = frozenset(
    {
        "a",
        "about",
        "after",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "for",
        "from",
        "get",
        "gets",
        "getting",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "me",
        "might",
        "more",
        "most",
        "must",
        "my",
        "need",
        "needs",
        "of",
        "on",
        "once",
        "only",
        "or",
        "our",
        "out",
        "over",
        "please",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "want",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "abu",
        "dhabi",
        "much",
        "set",
        "many",
        "steps",
    }
)

# Everyday words people use -> the words official pages use (and back). Deterministic, so
# it also helps the demo embedder, which is lexical rather than semantic.
SYNONYM_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(group.split())
    for group in (
        "spouse wife husband",
        "child children son daughter kids",
        "family dependant dependants dependent dependents",
        "visa residency residence",
        "company business startup firm enterprise",
        "licence license licensing",
        "tenancy lease rent rental tawtheeq",
        "home apartment flat housing accommodation villa",
        "medical screening fitness",
        "insurance insured",
        "driving driver drive",
        "attestation attest attested legalisation legalization",
        "salary income wage earn earnings",
        "doctor clinic hospital healthcare",
        "culture customs traditions etiquette",
        "bus buses transport hafilat",
        "toll tolls darb",
        "eid emirates",
        "id identity",
        "uaepass uae",
    )
)
_SYNONYMS: dict[str, frozenset[str]] = {word: group for group in SYNONYM_GROUPS for word in group}

# Broader words official pages use for the same need (weaker than synonyms): pages about
# sponsoring a wife talk about "family" and "dependants", not "wife".
RELATED_GROUPS: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = tuple(
    (frozenset(triggers.split()), tuple(related.split()))
    for triggers, related in (
        ("spouse wife husband child children son daughter kids", "family dependant dependent"),
        ("visa residency residence", "permit"),
        ("home apartment flat housing accommodation villa rent", "tenancy lease"),
        ("medical screening fitness", "health"),
        ("salary income wage earn earnings", "sponsor"),
    )
)

SYNONYM_WEIGHT = 0.8
RELATED_WEIGHT = 0.5


_SUFFIXES = ("ations", "ation", "ships", "ship", "ings", "ing", "ies", "es", "ed", "s", "y")
MIN_STEM_LENGTH = 4


def match_key(term: str) -> str:
    """How a term is matched against page text: a trailing '*' means prefix match.

    The 'simple' text-search config does no stemming, so words are reduced to a prefix
    ("families" -> "famil*", "fingerprints" -> "fingerprint*", "attested" -> "attest*").
    Short words stay exact so 'pass' never matches 'passport'."""
    for suffix in _SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= MIN_STEM_LENGTH:
            return term[: -len(suffix)] + "*"
    return term + "*" if len(term) >= PREFIX_MIN_LENGTH else term


def query_terms(query: str) -> list[str]:
    """Lowercased content words of `query`, in order, without duplicates."""
    seen: dict[str, None] = {}
    for token in _TOKEN.findall(query.lower()):
        if token not in STOPWORDS and (len(token) > 1 or not token.isascii()):
            seen.setdefault(token, None)
    return list(seen)


def _expansions(terms: Sequence[str]) -> dict[str, float]:
    weights: dict[str, float] = dict.fromkeys(terms, 1.0)
    for term in terms:
        for synonym in sorted(_SYNONYMS.get(term, ())):
            weights[synonym] = max(weights.get(synonym, 0.0), SYNONYM_WEIGHT)
        for triggers, related in RELATED_GROUPS:
            if term in triggers:
                for word in related:
                    weights[word] = max(weights.get(word, 0.0), RELATED_WEIGHT)
    return weights


def weighted_terms(terms: Sequence[str]) -> dict[str, float]:
    """Match keys (see `match_key`) for the query terms (1.0), their synonyms (0.8) and
    related official words (0.5)."""
    weights: dict[str, float] = {}
    for word, weight in _expansions(terms).items():
        key = match_key(word)
        weights[key] = max(weights.get(key, 0.0), weight)
    return weights


def expand_terms(terms: Sequence[str]) -> list[str]:
    """Query terms plus synonyms and related words (plain words)."""
    return list(_expansions(terms))


def lexical_query(query: str) -> str | None:
    """A `to_tsquery('simple', ...)` expression matching any expanded term. Tokens are
    restricted to letters and digits, so the result is always valid tsquery syntax."""
    keys = weighted_terms(query_terms(query))
    if not keys:
        return None
    return " | ".join(tsquery_term(key) for key in keys)


def tsquery_term(key: str) -> str:
    return f"{key[:-1]}:*" if key.endswith("*") else key


def embedding_text(query: str) -> str:
    """The text to embed for a query: the query plus its synonyms (not the broader related
    words, which would pull the vector towards generic pages)."""
    terms = query_terms(query)
    extra = [t for t, w in _expansions(terms).items() if t not in terms and w >= SYNONYM_WEIGHT]
    return query if not extra else f"{query} ({' '.join(extra)})"


def token_matches(token: str, key: str) -> bool:
    return token.startswith(key[:-1]) if key.endswith("*") else token == key


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def bm25[K: Hashable](
    docs: Mapping[K, Sequence[str]],
    weights: Mapping[str, float],
    df: Mapping[str, int],
    n_docs: int,
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> list[tuple[K, float]]:
    """Okapi BM25 over tokenised candidates, with corpus document frequencies, so rare,
    discriminating words ("wife", "tawtheeq") outweigh words on every page ("visa")."""
    if not docs or not weights:
        return []
    avgdl = sum(len(tokens) for tokens in docs.values()) / len(docs) or 1.0
    idf = {
        term: math.log(1 + (n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
        for term in weights
    }
    scored: list[tuple[K, float]] = []
    for key, tokens in docs.items():
        norm = k1 * (1 - b + b * len(tokens) / avgdl)
        score = 0.0
        for term, weight in weights.items():
            tf = sum(1 for token in tokens if token_matches(token, term))
            if tf:
                score += weight * idf[term] * tf * (k1 + 1) / (tf + norm)
        if score > 0:
            scored.append((key, score))
    scored.sort(key=lambda pair: -pair[1])
    return scored


def fuse[K: Hashable](
    vector_hits: Sequence[tuple[K, float]],
    lexical_hits: Sequence[tuple[K, float]],
    *,
    vector_weight: float = 0.5,
    lexical_weight: float = 0.5,
) -> dict[K, float]:
    """Weighted score fusion of the two candidate lists, normalised to [0, 1].

    Each list's scores are divided by its best score, so a clear lexical winner keeps its
    margin (rank fusion lets a mediocre passage present in both lists overtake it).
    `vector_hits` are (id, cosine similarity), best first; weak neighbours are dropped
    first. `lexical_hits` are (id, BM25), best first.
    """
    if vector_hits:
        best = max(similarity for _, similarity in vector_hits)
        floor = max(best * RELATIVE_VECTOR_FLOOR, ABSOLUTE_VECTOR_FLOOR)
        vector_hits = [(key, s) for key, s in vector_hits if s >= floor]
    lists = [
        (hits, weight)
        for hits, weight in ((vector_hits, vector_weight), (lexical_hits, lexical_weight))
        if hits
    ]
    if not lists:
        return {}
    total = sum(weight for _, weight in lists)
    scores: dict[K, float] = {}
    for hits, weight in lists:
        best = max(score for _, score in hits) or 1.0
        for key, score in hits:
            scores[key] = scores.get(key, 0.0) + (weight / total) * (score / best)
    return scores


@dataclass(frozen=True, slots=True)
class RankItem:
    key: Hashable
    group: Hashable  # e.g. the document: limits how many passages one page contributes
    relevance: float
    priority: int
    freshness: Freshness
    retrieved_at: datetime
    superseded: bool = False


def ranking_score(item: RankItem) -> float:
    score = item.relevance * PRIORITY_WEIGHT.get(item.priority, PRIORITY_WEIGHT[7])
    score *= FRESHNESS_WEIGHT[item.freshness]
    if item.superseded:
        score *= SUPERSEDED_WEIGHT
    return round(score, 6)


def rank(
    items: Sequence[RankItem],
    *,
    top_k: int,
    max_per_group: int = 3,
    min_score: float | None = None,
) -> list[tuple[RankItem, float]]:
    """Order by ranking score; ties go to the higher-priority, more recently checked source.
    At most `max_per_group` passages per page, so one long page cannot crowd out others."""
    scored = [(item, ranking_score(item)) for item in items]
    scored.sort(key=lambda pair: (-pair[1], pair[0].priority, -pair[0].retrieved_at.timestamp()))
    ranked: list[tuple[RankItem, float]] = []
    per_group: dict[Hashable, int] = {}
    for item, score in scored:
        if min_score is not None and score < min_score:
            continue
        if per_group.get(item.group, 0) >= max_per_group:
            continue
        per_group[item.group] = per_group.get(item.group, 0) + 1
        ranked.append((item, score))
        if len(ranked) == top_k:
            break
    return ranked
