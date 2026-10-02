"""Tries readers in order, preferring the most private one that reads enough.

Typical chain: the local text-layer reader first (exact, offline, nothing leaves the
server), then a vision provider for images, scans, or digital PDFs the local reader could
only partly read.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from app.adapters.ocr.types import (
    DocumentReader,
    DocumentUnreadable,
    ReaderFailed,
    ReadRequest,
    ReadResult,
)

logger = logging.getLogger(__name__)

# A reading is good enough to stop when it filled this share of the type's fields.
SUFFICIENT_COVERAGE = 0.6


def coverage(request: ReadRequest, result: ReadResult) -> float:
    spec = request.spec(request.type_hint) or request.spec(result.detected_type)
    if spec is None or not spec.fields:
        return 0.0
    return result.filled() / len(spec.fields)


class ChainedReader:
    def __init__(self, readers: Sequence[DocumentReader]) -> None:
        if not readers:
            raise ValueError("ChainedReader needs at least one reader")
        self._readers = list(readers)
        self.provider = "+".join(r.provider for r in self._readers)
        self.mode: Literal["live", "demo"] = (
            "live" if any(r.mode == "live" for r in self._readers) else "demo"
        )

    async def read(self, request: ReadRequest) -> ReadResult:
        best: ReadResult | None = None
        failure: Exception | None = None
        for reader in self._readers:
            try:
                result = await reader.read(request)
            except DocumentUnreadable as exc:
                failure = failure or exc
                continue
            except ReaderFailed as exc:
                failure = exc
                logger.warning("reader_failed", extra={"provider": reader.provider})
                continue
            if coverage(request, result) >= SUFFICIENT_COVERAGE:
                return result
            if best is None or result.filled() > best.filled():
                best = result
        if best is not None:
            return best
        raise failure or DocumentUnreadable("no reader could read this document")
