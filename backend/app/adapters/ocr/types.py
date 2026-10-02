"""Provider-neutral types for reading documents (OCR / vision-language models).

This is the port between ADAPT's document pipeline and any reading technology. Providers
receive a generic *schema* (document types with the fields to transcribe) and return raw
transcriptions with confidences. They know nothing about passports, twins or users:
classification rules, validation and mapping to personal facts live in `app.documents`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

SUPPORTED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
)


def sniff_content_type(data: bytes) -> str | None:
    """Content type from magic bytes. Never trust the client-declared type."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"heim"}:
        return "image/heic"
    return None


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    description: str
    # Printed labels a text-based reader can look for, e.g. ("Date of birth", "DOB").
    labels: tuple[str, ...] = ()
    kind: str = "text"  # hint only: text | date | country | boolean | money | list


@dataclass(frozen=True, slots=True)
class DocumentTypeSpec:
    name: str
    description: str
    fields: tuple[FieldSpec, ...]
    # Case-insensitive text markers that identify the type in a text layer.
    markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadRequest:
    content: bytes = field(repr=False)
    content_type: str
    types: tuple[DocumentTypeSpec, ...]
    type_hint: str | None = None  # what the user said the document is

    def spec(self, name: str | None) -> DocumentTypeSpec | None:
        return next((t for t in self.types if t.name == name), None)


@dataclass(slots=True)
class ReadField:
    name: str
    value: str | None = field(repr=False)  # never printed: may be personal data
    confidence: float


@dataclass(slots=True)
class ReadResult:
    method: str  # e.g. "local:pdf-text", "openai:gpt-5.4-mini"
    detected_type: str | None
    type_confidence: float
    fields: list[ReadField]
    machine_readable_zone: list[str] = field(default_factory=list, repr=False)
    warnings: list[str] = field(default_factory=list)

    def filled(self) -> int:
        return sum(1 for f in self.fields if f.value)


class DocumentUnreadable(Exception):
    """This reader cannot handle this input (e.g. an image offline). Try another reader."""


class ReaderFailed(Exception):
    """The reader tried and failed (provider error, timeout, malformed response)."""


class DocumentReader(Protocol):
    provider: str
    mode: Literal["live", "demo"]

    async def read(self, request: ReadRequest) -> ReadResult: ...
