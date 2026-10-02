"""OCR/VLM provider abstraction: local text-layer reader, OpenAI vision reader, chain."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

import pytest
from openai import APIConnectionError

from app.adapters.ocr import (
    ChainedReader,
    DocumentUnreadable,
    LocalTextReader,
    OpenAIVisionReader,
    ReaderFailed,
    ReadField,
    ReadRequest,
    ReadResult,
    sniff_content_type,
)
from app.documents.catalogue import READ_SCHEMA
from app.documents.specimens import Line, build_pdf, marriage_certificate, passport

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def request(content: bytes, content_type: str = "application/pdf", hint: str | None = None):  # type: ignore[no-untyped-def]
    return ReadRequest(content, content_type, READ_SCHEMA, hint)


class TestSniffing:
    def test_magic_bytes(self) -> None:
        assert sniff_content_type(passport()) == "application/pdf"
        assert sniff_content_type(PNG) == "image/png"
        assert sniff_content_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
        assert sniff_content_type(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
        assert sniff_content_type(b"<html>not a document") is None


class TestLocalTextReader:
    async def test_reads_a_digital_passport_and_its_mrz(self) -> None:
        result = await LocalTextReader().read(request(passport()))
        assert result.detected_type == "passport"
        assert result.method == "local:pdf-text"
        values = {f.name: f.value for f in result.fields}
        assert values["surname"] == "MEHTA"
        assert values["date_of_birth"] == "12/04/1990"
        assert len(result.machine_readable_zone) == 2

    async def test_classifies_from_markers_and_respects_the_hint(self) -> None:
        detected = await LocalTextReader().read(request(marriage_certificate()))
        assert detected.detected_type == "marriage_certificate"
        assert detected.type_confidence >= 0.85
        # The user says it's a passport: fields are read for the hinted type, and the
        # disagreement stays visible for the pipeline to flag.
        hinted = await LocalTextReader().read(request(marriage_certificate(), hint="passport"))
        assert hinted.detected_type == "marriage_certificate"
        passport_fields = {"surname", "given_names", "full_name", "nationality",
                           "date_of_birth", "date_of_expiry", "issuing_country"}  # fmt: skip
        assert {f.name for f in hinted.fields} <= passport_fields

    async def test_never_guesses_unlabelled_values(self) -> None:
        pdf = build_pdf([Line("MARRIAGE CERTIFICATE"), Line("Arjun and Priya were married.")])
        result = await LocalTextReader().read(request(pdf))
        assert result.detected_type == "marriage_certificate"
        assert result.fields == []

    async def test_images_and_scans_are_unreadable_offline(self) -> None:
        with pytest.raises(DocumentUnreadable, match="vision"):
            await LocalTextReader().read(request(PNG, "image/png"))
        with pytest.raises(DocumentUnreadable, match="text layer"):
            await LocalTextReader().read(request(build_pdf([], banner=False)))
        with pytest.raises(DocumentUnreadable):
            await LocalTextReader().read(request(b"%PDF-1.4 garbage"))


class _FakeResponses:
    def __init__(self, parsed: Any = None, error: Exception | None = None) -> None:
        self.parsed, self.error, self.calls = parsed, error, []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.parsed)


def _vision(parsed: Any = None, error: Exception | None = None):  # type: ignore[no-untyped-def]
    responses = _FakeResponses(parsed, error)
    return OpenAIVisionReader(SimpleNamespace(responses=responses), model="vision-test"), responses  # type: ignore[arg-type]


class TestOpenAIVisionReader:
    async def test_transcribes_and_filters_to_the_schema(self) -> None:
        parsed = SimpleNamespace(
            detected_type="passport",
            type_confidence=1.3,  # out-of-range model output is clamped
            fields=[
                SimpleNamespace(name="surname", value=" MEHTA ", confidence=0.97),
                SimpleNamespace(name="passport_number", value="Z1234567", confidence=0.99),
                SimpleNamespace(name="nationality", value="", confidence=0.2),
            ],
            machine_readable_zone=["P<IND MEHTA<<ARJUN"],
            warnings=["glare on photo"],
        )
        reader, responses = _vision(parsed)
        result = await reader.read(request(PNG, "image/png"))
        assert result.method == "openai:vision-test"
        assert result.type_confidence == 1.0
        assert [(f.name, f.value) for f in result.fields] == [
            ("surname", "MEHTA"),
            ("nationality", None),
        ]  # a passport number is never accepted, even if the model returns one
        call = responses.calls[0]
        assert call["store"] is False
        assert call["input"][0]["content"][1]["type"] == "input_image"
        assert "Never guess" in call["instructions"]

    async def test_unknown_type_is_not_trusted(self) -> None:
        parsed = SimpleNamespace(
            detected_type="bank_statement", type_confidence=0.9, fields=[],
            machine_readable_zone=[], warnings=[],
        )  # fmt: skip
        result = await _vision(parsed)[0].read(request(PNG, "image/png"))
        assert result.detected_type is None and result.type_confidence == 0.0

    async def test_provider_errors_become_reader_failures(self) -> None:
        error = APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]
        with pytest.raises(ReaderFailed):
            await _vision(error=error)[0].read(request(PNG, "image/png"))

    async def test_pdfs_are_sent_as_files(self) -> None:
        parsed = SimpleNamespace(
            detected_type="miscellaneous", type_confidence=0.5, fields=[],
            machine_readable_zone=[], warnings=[],
        )  # fmt: skip
        reader, responses = _vision(parsed)
        await reader.read(request(passport()))
        assert responses.calls[0]["input"][0]["content"][1]["type"] == "input_file"


class _Stub:
    def __init__(
        self, provider: str, outcome: ReadResult | Exception, mode: Literal["live", "demo"] = "demo"
    ) -> None:
        self.provider, self.mode, self.outcome, self.called = provider, mode, outcome, False

    async def read(self, request: ReadRequest) -> ReadResult:
        self.called = True
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _result(filled: int, method: str) -> ReadResult:
    names = ["surname", "given_names", "nationality", "date_of_birth", "date_of_expiry"]
    return ReadResult(method, "passport", 0.9, [ReadField(n, "x", 0.9) for n in names[:filled]])


class TestChain:
    async def test_prefers_the_first_sufficient_reader(self) -> None:
        local, vision = _Stub("local", _result(5, "local")), _Stub("vision", _result(5, "vision"))
        chain = ChainedReader([local, vision])
        assert (await chain.read(request(passport()))).method == "local"
        assert not vision.called

    async def test_falls_through_unreadable_and_failed_readers(self) -> None:
        chain = ChainedReader(
            [
                _Stub("local", DocumentUnreadable("image")),
                _Stub("vision", _result(5, "vision"), "live"),
            ]
        )
        assert chain.mode == "live" and chain.provider == "local+vision"
        assert (await chain.read(request(PNG, "image/png"))).method == "vision"

    async def test_keeps_the_best_partial_reading(self) -> None:
        chain = ChainedReader(
            [_Stub("local", _result(2, "local")), _Stub("vision", ReaderFailed("timeout"))]
        )
        assert (await chain.read(request(passport()))).method == "local"

    async def test_raises_when_nobody_can_read(self) -> None:
        chain = ChainedReader([_Stub("a", DocumentUnreadable("x")), _Stub("b", ReaderFailed("y"))])
        with pytest.raises(ReaderFailed):
            await chain.read(request(PNG, "image/png"))
