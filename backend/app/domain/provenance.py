"""Trust and provenance rules.

Every claim ADAPT shows a user carries a `Provenance`. The invariants here are the
product's trust contract:

* An *authoritative requirement* or *official guidance* must cite at least one source
  on an official government domain.
* A *community/web* finding must cite the web page it came from and when it was read.
* An *AI recommendation* may cite sources, but is never presented as a requirement.

The official-domain allowlist is code, not configuration: widening what counts as
"official" is a trust decision and must go through review.
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import EvidenceKind

# Domain suffixes treated as official Abu Dhabi / UAE government sources.
OFFICIAL_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "gov.ae",  # federal and emirate government domains (icp.gov.ae, mohre.gov.ae, doh.gov.ae ...)
    "abudhabi.ae",  # Abu Dhabi government (e.g. added.gov.ae mirrors, ded.abudhabi.ae)
    "tamm.abudhabi",  # TAMM — Abu Dhabi government services platform
    "u.ae",  # UAE government portal
    "adgm.com",  # Abu Dhabi Global Market (free-zone authority & registration authority)
)


def is_official_source(url: str) -> bool:
    """True when `url` is https and its host is (a subdomain of) an official suffix."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
    ):
        return False
    try:
        if parts.port not in {None, 443}:
            return False
    except ValueError:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_DOMAIN_SUFFIXES)


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_url: str = Field(min_length=8, max_length=2048)
    source_title: str = Field(min_length=1, max_length=500)
    authority: str | None = Field(default=None, max_length=200)
    document_type: str | None = None
    effective_date: date | None = None
    retrieved_at: datetime | None = None
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    rag_chunk_id: UUID | None = None
    quote: str | None = Field(default=None, max_length=1200)

    @field_validator("source_url")
    @classmethod
    def _web_link(cls, value: str) -> str:
        try:
            parts = urlsplit(value)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
            ):
                raise ValueError("Citations require a web URL without credentials")
            _ = parts.port
        except ValueError as exc:
            raise ValueError("Citations require a valid web URL without credentials") from exc
        return value

    @property
    def is_official(self) -> bool:
        return is_official_source(self.source_url)


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind
    citations: list[Citation] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _enforce_trust_rules(self) -> Provenance:
        if self.kind in (EvidenceKind.AUTHORITATIVE_REQUIREMENT, EvidenceKind.OFFICIAL_GUIDANCE):
            if not any(c.is_official for c in self.citations):
                raise ValueError(
                    f"{self.kind.value} must cite at least one official government source"
                )
        elif self.kind is EvidenceKind.COMMUNITY_WEB:
            if not self.citations:
                raise ValueError("community_web findings must cite the page they came from")
            if any(c.retrieved_at is None for c in self.citations):
                raise ValueError("community_web citations must record retrieved_at")
        return self

    @classmethod
    def ai(cls, note: str | None = None, *, citations: list[Citation] | None = None) -> Provenance:
        return cls(kind=EvidenceKind.AI_RECOMMENDATION, note=note, citations=citations or [])
