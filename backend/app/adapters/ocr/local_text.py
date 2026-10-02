"""Local, offline reader for digital documents: the PDF text layer.

Many official documents are issued as digital PDFs (e-visas, salary certificates, trade
licences, tenancy contracts) whose text can be read exactly, without OCR and without
sending the document to a third party. This reader:

* extracts the text layer with pypdf (scanned PDFs and images have none, so it reports
  `DocumentUnreadable` and a vision provider, or the user, takes over);
* identifies the document type from the schema's markers;
* transcribes `Label: value` lines for the schema's fields;
* collects machine-readable-zone lines verbatim for downstream check-digit validation.

It never guesses: a field that is not printed with a recognised label is left empty.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.adapters.ocr.types import (
    DocumentUnreadable,
    FieldSpec,
    ReadField,
    ReadRequest,
    ReadResult,
)

logger = logging.getLogger(__name__)

MAX_PAGES = 5
MIN_TEXT_CHARS = 20
LABELLED_CONFIDENCE = 0.9  # the text is exact; the residual doubt is the label match
SPACED_CONFIDENCE = 0.8  # "Label    value" without a separator
_MRZ_LINE = re.compile(r"^[A-Z0-9<]{30,44}$")
_SEPARATOR = r"\s*[:\uff1a\-\u2013]\s*"  # colon, full-width colon, hyphen, en dash


def _text_layer(content: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise DocumentUnreadable("the PDF is password-protected")
        chunks = [(page.extract_text() or "") for page in reader.pages[:MAX_PAGES]]
    except PdfReadError as exc:
        raise DocumentUnreadable("the PDF could not be opened") from exc
    lines = []
    for chunk in chunks:
        for raw in chunk.splitlines():
            line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
            if line:
                lines.append(line)
    if sum(len(line) for line in lines) < MIN_TEXT_CHARS:
        raise DocumentUnreadable("the PDF has no text layer (it is probably a scan)")
    return lines


def _match_field(spec: FieldSpec, lines: list[str]) -> tuple[str, float] | None:
    for label in spec.labels:
        escaped = re.escape(label).replace(r"\ ", r"\s+")
        labelled = re.compile(rf"^{escaped}{_SEPARATOR}(.+)$", re.IGNORECASE)
        spaced = re.compile(rf"^{escaped}\s{{2,}}(.+)$", re.IGNORECASE)
        for line in lines:
            if m := labelled.match(line):
                return m[1].strip(), LABELLED_CONFIDENCE
            if m := spaced.match(line):
                return m[1].strip(), SPACED_CONFIDENCE
    return None


class LocalTextReader:
    """Reads digital PDFs locally. Offline, deterministic, sends nothing anywhere."""

    provider = "local-text"
    mode: Literal["live", "demo"] = "demo"
    method = "local:pdf-text"

    async def read(self, request: ReadRequest) -> ReadResult:
        if request.content_type != "application/pdf":
            raise DocumentUnreadable("images need a vision provider to be read")
        lines = await asyncio.to_thread(_text_layer, request.content)
        lowered = "\n".join(lines).lower()

        detected: str | None = None
        best = 0
        for spec in request.types:
            score = sum(1 for marker in spec.markers if marker.lower() in lowered)
            if score > best:
                detected, best = spec.name, score
        type_confidence = 0.0 if detected is None else (0.95 if best >= 2 else 0.85)

        chosen = request.spec(request.type_hint) or request.spec(detected)
        fields: list[ReadField] = []
        if chosen is not None:
            for field_spec in chosen.fields:
                match = _match_field(field_spec, lines)
                if match is not None:
                    fields.append(ReadField(field_spec.name, match[0], match[1]))
        mrz = [line.replace(" ", "") for line in lines if _MRZ_LINE.match(line.replace(" ", ""))]
        return ReadResult(
            method=self.method,
            detected_type=detected,
            type_confidence=type_confidence,
            fields=fields,
            machine_readable_zone=mrz,
        )
