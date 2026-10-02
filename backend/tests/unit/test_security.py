"""Security primitives: log redaction, signed document links, API key never exposed."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import Forbidden
from app.core.logging import JsonFormatter
from app.core.redaction import REDACTED, RedactingFilter, redact_query, redact_text, redact_value
from app.core.signing import sign_document_url, verify_document_signature
from app.domain.principal import Principal
from app.main import create_app

FAKE_KEY = "sk-test-DO-NOT-LEAK-0123456789abcdef"


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adapter_llm": "demo",
        "adapter_embeddings": "demo",
        "adapter_ocr": "demo",
        "adapter_voice": "demo",
        "adapter_web_search": "demo",
        "openai_api_key": FAKE_KEY,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]


class TestRedaction:
    def test_api_keys_and_tokens(self) -> None:
        text = f"calling with {FAKE_KEY} and Bearer abc.def.ghi"
        out = redact_text(text)
        assert FAKE_KEY not in out and "abc.def.ghi" not in out

    def test_passport_mrz_and_emirates_id(self) -> None:
        mrz = "P<INDMEHTA<<ARJUN<<<<<<<<<<<<<<<<<<<<<<<<<<<"
        out = redact_text(f"line {mrz} id 784-1990-1234567-1")
        assert "MEHTA" not in out and "784-1990" not in out

    def test_sensitive_keys_are_masked_recursively(self) -> None:
        value = {
            "document_id": "d1",
            "fields": [{"passport_number": "Z1234567", "date_of_birth": "1990-04-12"}],
            "content": "full passport text",
        }
        out = redact_value(value)
        assert out["document_id"] == "d1"
        assert out["fields"] == REDACTED
        assert out["content"] == REDACTED

    def test_query_signatures(self) -> None:
        assert "deadbeef" not in redact_query("expires=1&sig=deadbeef")
        assert "expires=1" in redact_query("expires=1&sig=deadbeef")

    def test_log_records_are_redacted(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        handler.setFormatter(JsonFormatter())
        log = logging.getLogger("test.redaction")
        log.addHandler(handler)
        log.propagate = False
        try:
            log.warning(
                "extraction failed for %s",
                "P<INDMEHTA<<ARJUN<<<<<<<<<<<<<<<<<<<<<<<<<<<",
                extra={"passport_number": "Z1234567", "document_id": "doc-1", "body": b"%PDF..."},
            )
        finally:
            log.removeHandler(handler)
        record = json.loads(stream.getvalue())
        dumped = json.dumps(record)
        assert "Z1234567" not in dumped and "MEHTA" not in dumped and "%PDF" not in dumped
        assert record["document_id"] == "doc-1"


class TestSignedDocumentLinks:
    def test_round_trip(self) -> None:
        s = settings()
        principal = Principal(user_id=uuid4(), tenant_id=uuid4())
        doc = uuid4()
        url = sign_document_url(s, principal, doc, now=1_000)
        query = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
        verify_document_signature(
            s, principal, doc, expires=int(query["expires"]), sig=query["sig"], now=1_000
        )

    def test_other_user_or_document_or_expiry_fails(self) -> None:
        s = settings()
        owner = Principal(user_id=uuid4(), tenant_id=uuid4())
        doc = uuid4()
        url = sign_document_url(s, owner, doc, ttl_seconds=60, now=1_000)
        query = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
        expires, sig = int(query["expires"]), query["sig"]
        stranger = Principal(user_id=uuid4(), tenant_id=owner.tenant_id)
        with pytest.raises(Forbidden):
            verify_document_signature(s, stranger, doc, expires=expires, sig=sig, now=1_000)
        with pytest.raises(Forbidden):
            verify_document_signature(s, owner, uuid4(), expires=expires, sig=sig, now=1_000)
        with pytest.raises(Forbidden) as exc:
            verify_document_signature(s, owner, doc, expires=expires, sig=sig, now=2_000)
        assert exc.value.code == "document_link_expired"


class TestSecretsNeverExposed:
    async def test_public_endpoints_never_return_the_openai_key(self, tmp_path: Path) -> None:
        app = create_app(settings(document_storage_dir=tmp_path))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            bodies = [
                (await c.get(path)).text
                for path in ("/api/health", "/api/system/info", "/api/openapi.json", "/api/agents")
            ]
        assert all(FAKE_KEY not in body for body in bodies)
        assert all("sk-test" not in body for body in bodies)
