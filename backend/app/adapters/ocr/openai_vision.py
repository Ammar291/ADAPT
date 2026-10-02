"""OpenAI vision-language reader (Responses API with structured output).

Transcription only: the model is told to copy what is printed, never to infer, and to
return null with low confidence for anything illegible. Confidence is model-reported, so
the pipeline calibrates it with deterministic checks (formats, check digits, cross-field
consistency) before anything reaches the user's twin. Calls use `store=False`.
"""

from __future__ import annotations

import base64
import logging
from typing import Literal

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from app.adapters.ocr.types import (
    SUPPORTED_CONTENT_TYPES,
    DocumentUnreadable,
    ReaderFailed,
    ReadField,
    ReadRequest,
    ReadResult,
)

logger = logging.getLogger(__name__)


class _Field(BaseModel):
    name: str
    value: str | None
    confidence: float


class _Reading(BaseModel):
    detected_type: str
    type_confidence: float
    fields: list[_Field]
    machine_readable_zone: list[str]
    warnings: list[str]


def _instructions(request: ReadRequest) -> str:
    lines = []
    for spec in request.types:
        fields = "; ".join(f"{f.name} ({f.description})" for f in spec.fields) or "none"
        lines.append(f"- {spec.name}: {spec.description}. Fields: {fields}")
    catalogue = "\n".join(lines)
    return (
        "You transcribe fields from a personal document for a relocation assistant.\n"
        "Rules: copy only what is printed. Never guess, infer or complete a value. If a "
        "field is absent, illegible or cut off, return value null and a low confidence. "
        "Confidence (0-1) is how sure you are that the transcription is exactly right. "
        "Dates as YYYY-MM-DD when unambiguous, otherwise as printed. Return only fields "
        "listed for the detected type. Copy any machine-readable zone (MRZ) lines "
        "verbatim, including '<' characters. Do not transcribe document or card numbers "
        "anywhere else.\n"
        f"Document types:\n{catalogue}\n"
        "detected_type must be one of the type names above, or 'miscellaneous'."
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class OpenAIVisionReader:
    provider = "openai"
    mode: Literal["live", "demo"] = "live"

    def __init__(self, client: AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def method(self) -> str:
        return f"openai:{self._model}"

    async def read(self, request: ReadRequest) -> ReadResult:
        if request.content_type not in SUPPORTED_CONTENT_TYPES:
            raise DocumentUnreadable(f"{request.content_type} is not a supported document type")
        data_url = (
            f"data:{request.content_type};base64,{base64.b64encode(request.content).decode()}"
        )
        part = (
            {"type": "input_file", "filename": "document.pdf", "file_data": data_url}
            if request.content_type == "application/pdf"
            else {"type": "input_image", "image_url": data_url, "detail": "high"}
        )
        hint = (
            f"The person says this is a {request.type_hint}."
            if request.type_hint
            else "The person did not say what this document is."
        )
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=_instructions(request),
                input=[{"role": "user", "content": [{"type": "input_text", "text": hint}, part]}],  # type: ignore[list-item, misc]
                text_format=_Reading,
                store=False,
            )
        except OpenAIError as exc:
            # Log the error class only: provider messages can echo request content.
            logger.warning("vision_read_failed", extra={"error": type(exc).__name__})
            raise ReaderFailed("the vision provider did not return a reading") from exc
        reading = response.output_parsed
        if reading is None:
            raise ReaderFailed("the vision provider returned no structured reading")

        detected = reading.detected_type if request.spec(reading.detected_type) else None
        chosen = request.spec(request.type_hint) or request.spec(detected)
        allowed = {f.name for f in chosen.fields} if chosen else set()
        fields = [
            ReadField(f.name, (f.value or "").strip() or None, _clamp(f.confidence))
            for f in reading.fields
            if f.name in allowed
        ]
        return ReadResult(
            method=self.method,
            detected_type=detected,
            type_confidence=_clamp(reading.type_confidence) if detected else 0.0,
            fields=fields,
            machine_readable_zone=[line.replace(" ", "") for line in reading.machine_readable_zone],
            warnings=[w[:200] for w in reading.warnings[:5]],
        )
