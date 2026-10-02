"""Load and validate the curated corpus (`corpus/*.yaml`). Pure: no database, no network.

Validation is strict because this corpus is what ADAPT cites as official:

* required metadata (title, url, publisher, source type, retrieved_at, topics, passages)
  must be present; unknown fields are rejected so typos cannot silently drop data;
* every URL must be https, on the official-domain allowlist, and owned by the publisher
  the record claims (a TAMM page cannot claim to be published by ICP, and vice versa);
* a page only readable through a search snippet cannot claim verbatim quotes;
* `retrieved_at` cannot be in the future.

Staleness is *not* a validation error: an old record stays usable, but retrieval marks it
stale, lowers its confidence and never presents it as a binding requirement.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.domain.provenance import is_official_source
from app.knowledge.schemas import Freshness, KnowledgeTopic, SourceType
from app.knowledge.sources import PUBLISHERS

CORPUS_DIR = Path(__file__).with_name("corpus")
DEFAULT_STALE_AFTER_DAYS = 180
MAX_CHUNK_CHARS = 1200


class CorpusError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid knowledge corpus:\n  - " + "\n  - ".join(problems))


class PassageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z0-9_]+$", max_length=80)
    section: str | None = Field(default=None, max_length=500)
    excerpt: Literal["quote", "paraphrase"]
    states_requirement: bool = False
    text: str = Field(min_length=20, max_length=4000)
    topics: list[KnowledgeTopic] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _normalise_space(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()


class SourceRecord(BaseModel):
    """One official page, as curated: the unit that becomes a `governance_documents` row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$", max_length=120)
    title: str = Field(min_length=3, max_length=500)
    url: str = Field(min_length=12, max_length=2048)
    authority: str = Field(pattern=r"^authority\.[a-z0-9_]+$")
    source_type: SourceType
    language: str = Field(default="en", max_length=35)
    retrieved_at: datetime
    effective_date: date | None = None
    last_updated: date | None = None
    topics: list[KnowledgeTopic] = Field(min_length=1)
    verification: Literal["fetched", "search_snippet"]
    notes: str | None = None
    passages: list[PassageRecord] = Field(min_length=1)

    @field_validator("retrieved_at", mode="before")
    @classmethod
    def _date_is_midnight_utc(cls, value: Any) -> Any:
        if isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, time.min, tzinfo=UTC)
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def _rules(self) -> SourceRecord:
        if not self.url.startswith("https://"):
            raise ValueError("url must be https")
        keys = [p.key for p in self.passages]
        if len(keys) != len(set(keys)):
            raise ValueError("passage keys must be unique within a source")
        if self.verification == "search_snippet" and any(
            p.excerpt == "quote" for p in self.passages
        ):
            raise ValueError("a search_snippet source cannot claim verbatim quotes")
        return self

    def passage(self, key: str) -> PassageRecord | None:
        return next((p for p in self.passages if p.key == key), None)

    def passage_topics(self, passage: PassageRecord) -> list[KnowledgeTopic]:
        return list(passage.topics or self.topics)

    @property
    def content_hash(self) -> str:
        """Hash of what the page SAYS. `retrieved_at` is excluded: re-checking an unchanged
        page refreshes the live version instead of creating a new one."""
        payload = {
            "title": self.title,
            "url": self.url,
            "authority": self.authority,
            "source_type": self.source_type.value,
            "language": self.language,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "passages": [
                {
                    "key": p.key,
                    "section": p.section,
                    "excerpt": p.excerpt,
                    "states_requirement": p.states_requirement,
                    "text": p.text,
                    "topics": [t.value for t in self.passage_topics(p)],
                }
                for p in self.passages
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Corpus:
    sources: list[SourceRecord]
    by_key: dict[str, SourceRecord] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_key", {s.key: s for s in self.sources})

    def resolve(self, ref: str) -> tuple[SourceRecord, PassageRecord]:
        """Resolve an evidence reference `<source_key>#<passage_key>`."""
        source_key, _, passage_key = ref.partition("#")
        source = self.by_key.get(source_key)
        passage = source.passage(passage_key) if source and passage_key else None
        if source is None or passage is None:
            raise KeyError(ref)
        return source, passage

    @property
    def passage_count(self) -> int:
        return sum(len(s.passages) for s in self.sources)


def _format_validation_error(origin: str, exc: ValidationError) -> list[str]:
    problems = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        problems.append(f"{origin}: {loc}: {error['msg']}")
    return problems


def parse_sources(
    raw_sources: Iterable[dict[str, Any]], *, origin: str, now: datetime | None = None
) -> tuple[list[SourceRecord], list[str]]:
    """Validate raw source dicts. Returns the valid records and a list of problems."""
    now = now or datetime.now(UTC)
    records: list[SourceRecord] = []
    problems: list[str] = []
    for index, raw in enumerate(raw_sources):
        label = f"{origin}[{index}] {raw.get('key', '?') if isinstance(raw, dict) else '?'}"
        try:
            record = SourceRecord.model_validate(raw)
        except ValidationError as exc:
            problems += _format_validation_error(label, exc)
            continue
        publisher = PUBLISHERS.get(record.authority)
        if publisher is None:
            problems.append(f"{label}: unknown publisher '{record.authority}'")
            continue
        if not is_official_source(record.url):
            problems.append(f"{label}: {record.url} is not on the official-domain allowlist")
            continue
        if not publisher.owns(record.url):
            problems.append(
                f"{label}: {record.url} is not a {publisher.name} domain "
                f"({', '.join(publisher.domains)})"
            )
            continue
        if record.retrieved_at > now + timedelta(days=1):
            problems.append(f"{label}: retrieved_at is in the future")
            continue
        records.append(record)
    return records, problems


def load_corpus(directory: Path = CORPUS_DIR, *, now: datetime | None = None) -> Corpus:
    """Load every `*.yaml` file in `directory`. Raises `CorpusError` listing ALL problems."""
    records: list[SourceRecord] = []
    problems: list[str] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        found, issues = parse_sources(data.get("sources") or [], origin=path.name, now=now)
        records += found
        problems += issues
    seen_keys: set[str] = set()
    seen_urls: dict[str, str] = {}
    for record in records:
        if record.key in seen_keys:
            problems.append(f"duplicate source key '{record.key}'")
        seen_keys.add(record.key)
        if record.url in seen_urls:
            problems.append(f"'{record.key}' and '{seen_urls[record.url]}' share {record.url}")
        seen_urls[record.url] = record.key
    if problems:
        raise CorpusError(problems)
    return Corpus(sources=records)


def assess_freshness(
    retrieved_at: datetime, *, now: datetime, stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
) -> Freshness:
    return (
        Freshness.STALE
        if retrieved_at > now or now - retrieved_at > timedelta(days=stale_after_days)
        else Freshness.CURRENT
    )


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split a passage into chunks of whole sentences. Most passages are one chunk."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?؟])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # a single overlong sentence: hard split
            chunks.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks
