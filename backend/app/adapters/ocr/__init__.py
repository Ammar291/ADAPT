"""Document reading (OCR / vision-language) behind a provider-neutral port.

`DocumentReader.read(ReadRequest) -> ReadResult`. Implementations:

* `LocalTextReader`: digital PDFs, offline, exact text layer (the no-key fallback)
* `OpenAIVisionReader`: images and scans via the OpenAI Responses API
* `ChainedReader`: local first, then vision

There is deliberately no "demo" reader that returns canned values: a document that no
provider can read is reported as unreadable, and the pipeline asks the user to review it.
"""

from app.adapters.ocr.chain import ChainedReader
from app.adapters.ocr.local_text import LocalTextReader
from app.adapters.ocr.openai_vision import OpenAIVisionReader
from app.adapters.ocr.types import (
    SUPPORTED_CONTENT_TYPES,
    DocumentReader,
    DocumentTypeSpec,
    DocumentUnreadable,
    FieldSpec,
    ReaderFailed,
    ReadField,
    ReadRequest,
    ReadResult,
    sniff_content_type,
)

# Backwards-compatible name used by the adapter registry.
DocumentExtractor = DocumentReader

__all__ = [
    "SUPPORTED_CONTENT_TYPES",
    "ChainedReader",
    "DocumentExtractor",
    "DocumentReader",
    "DocumentTypeSpec",
    "DocumentUnreadable",
    "FieldSpec",
    "LocalTextReader",
    "OpenAIVisionReader",
    "ReadField",
    "ReadRequest",
    "ReadResult",
    "ReaderFailed",
    "sniff_content_type",
]
