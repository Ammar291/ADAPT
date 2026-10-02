"""Adversarial trust-boundary regressions that run without external services."""

from __future__ import annotations

import io
import logging
import re
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocket

from app.adapters.web_fetch import SafeHttpPageFetcher, UnsafeUrl, assert_public_url
from app.adapters.web_search import OpenAIWebResearcher
from app.api.deps import PrincipalDep, get_user_session, websocket_principal
from app.contracts.appointments import AppointmentOut
from app.core.config import Settings
from app.core.errors import AdapterUnavailable, NotFound, Unauthorized, UpstreamError
from app.core.logging import JsonFormatter
from app.core.origins import trusted_origin
from app.core.redaction import RedactingFilter
from app.core.security import issue_session_token, verify_session_token
from app.core.signing import sign_document_url
from app.db.session import Database, _apply_rls_context
from app.documents import service as document_service
from app.domain.enums import ConsentStatus, FactSource
from app.domain.principal import Principal
from app.domain.provenance import Citation, is_official_source
from app.domain.twin import SensitiveAttributeError, TwinFact, validate_twin_facts
from app.main import create_app

SECRET = "security-audit-random-test-key-0123456789abcdef"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        session_secret=SECRET,
        document_storage_dir=tmp_path,
        openai_api_key=None,
        adapter_llm="demo",
        adapter_embeddings="demo",
        adapter_ocr="demo",
        adapter_voice="demo",
        adapter_web_search="demo",
    )


def bearer(principal: Principal) -> dict[str, str]:
    token = issue_session_token(principal, secret=SECRET, ttl_hours=1).token
    return {"Authorization": f"Bearer {token}"}


async def test_every_private_api_operation_requires_authentication(settings: Settings) -> None:
    app = create_app(settings)
    public = {
        "/api/health",
        "/api/health/ready",
        "/api/system/info",
        "/api/agents",
        "/api/agents/journey/topology",
        "/api/agents/what_if/topology",
        "/api/auth/demo-session",
        "/api/auth/logout",
    }
    failures = []
    checked = 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for template, operations in app.openapi()["paths"].items():
            if template in public or template.startswith(
                ("/api/knowledge/", "/api/graph/governance", "/api/demo/scenarios")
            ):
                continue
            path = re.sub(r"\{[^}]+\}", str(uuid4()), template)
            for method in operations:
                if method not in {"get", "post", "patch", "put", "delete"}:
                    continue
                response = await client.request(method, path, json={})
                checked += 1
                if response.status_code != 401:
                    failures.append((method, template, response.status_code))
                assert response.headers["cache-control"] == "no-store"
    assert checked >= 50
    assert failures == []


@pytest.mark.parametrize(
    "origin", [None, "null", "https://evil.test", "https://test", "http://test.evil.test"]
)
async def test_cookie_mutations_reject_missing_or_forged_origins(
    settings: Settings, origin: str | None
) -> None:
    app = create_app(settings)
    calls = []

    @app.post("/api/audit-mutation")
    async def mutate(principal: PrincipalDep) -> dict[str, bool]:
        calls.append(principal)
        return {"ok": True}

    owner = Principal(user_id=uuid4(), tenant_id=uuid4())
    token = issue_session_token(owner, secret=SECRET, ttl_hours=1).token
    headers = {"Origin": origin} if origin else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://test",
        cookies={settings.session_cookie_name: token},
    ) as client:
        response = await client.post("/api/audit-mutation", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "origin_not_allowed"
    assert calls == []


async def test_trusted_browser_and_bearer_mutations_remain_usable(settings: Settings) -> None:
    app = create_app(settings)

    @app.post("/api/audit-mutation")
    async def mutate(principal: PrincipalDep) -> dict[str, str]:
        return {"user": str(principal.user_id)}

    owner = Principal(user_id=uuid4(), tenant_id=uuid4())
    token = issue_session_token(owner, secret=SECRET, ttl_hours=1).token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for origin in ("http://test", "http://localhost:5180"):
            response = await client.post(
                "/api/audit-mutation",
                headers={"Cookie": f"adapt_session={token}", "Origin": origin},
            )
            assert response.status_code == 200
        assert (await client.post("/api/audit-mutation", headers=bearer(owner))).status_code == 200


@pytest.mark.parametrize("value", [None, [], {}, 42, "not-a-uuid"])
def test_malformed_signed_tenant_claim_is_an_auth_error(value: object) -> None:
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "tid": value,
            "aud": "adapt-api",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(Unauthorized) as error:
        verify_session_token(token, secret=SECRET)
    assert error.value.code == "session_invalid"


def test_websocket_cookie_requires_a_trusted_origin(settings: Settings) -> None:
    owner = Principal(user_id=uuid4(), tenant_id=uuid4())
    token = issue_session_token(owner, secret=SECRET, ttl_hours=1).token
    for origin in (None, "http://test", "https://evil.test"):
        headers = [(b"host", b"test"), (b"cookie", f"adapt_session={token}".encode())]
        if origin:
            headers.append((b"origin", origin.encode()))
        websocket = WebSocket(
            {
                "type": "websocket",
                "scheme": "wss",
                "path": "/api/agents/x/stream",
                "headers": headers,
                "app": SimpleNamespace(
                    state=SimpleNamespace(container=SimpleNamespace(settings=settings))
                ),
            },
            receive=AsyncMock(),
            send=AsyncMock(),
        )
        with pytest.raises(Unauthorized):
            websocket_principal(websocket)
    assert trusted_origin("https://test", scheme="wss", host="test", settings=settings)


async def test_document_bytes_require_owner_signature_and_owner_lookup(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(settings)
    owner = Principal(user_id=uuid4(), tenant_id=uuid4())
    stranger = Principal(user_id=uuid4(), tenant_id=owner.tenant_id)
    wrong_tenant = Principal(user_id=owner.user_id, tenant_id=uuid4())
    document_id = uuid4()
    storage = AsyncMock()
    storage.get.return_value = b"private document bytes"
    app.state.container.adapters.storage = storage

    async def fake_session():
        yield object()

    async def lookup(session, principal, ref):
        if principal != owner or ref != document_id:
            raise NotFound("Document not found")
        return SimpleNamespace(storage_key="private-key", content_type="application/pdf")

    app.dependency_overrides[get_user_session] = fake_session
    monkeypatch.setattr(document_service, "get_document", lookup)
    signed = sign_document_url(settings, owner, document_id)
    parts = urlsplit(signed)
    path = parts.path + "?" + parts.query
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 401
        for principal in (stranger, wrong_tenant):
            assert (await client.get(path, headers=bearer(principal))).status_code == 403
        # Even a valid link issued to the attacker for a guessed document cannot bypass lookup.
        attacker_link = urlsplit(sign_document_url(settings, stranger, document_id))
        response = await client.get(
            attacker_link.path + "?" + attacker_link.query, headers=bearer(stranger)
        )
        assert response.status_code == 404
        storage.get.assert_not_called()
        response = await client.get(path, headers=bearer(owner))
        assert response.status_code == 200 and response.content == b"private document bytes"
        assert response.headers["cache-control"] == "no-store"
        storage.get.assert_awaited_once_with("private-key")


@pytest.mark.parametrize("formatter", [logging.Formatter("%(message)s"), JsonFormatter()])
def test_exception_logs_never_include_document_content(formatter: logging.Formatter) -> None:
    sensitive = "passport Z1234567 and marriage certificate for Layla and Omar"
    try:
        raise ValueError(sensitive)
    except ValueError:
        try:
            raise RuntimeError("upstream body=" + sensitive)
        except RuntimeError:
            record = logging.LogRecord(
                "audit", logging.ERROR, __file__, 1, "document_failed", (), sys.exc_info()
            )
    record.fields = {"freeform": sensitive}
    record.raw_text = sensitive
    assert RedactingFilter().filter(record)
    output = formatter.format(record)
    assert sensitive not in output and "Z1234567" not in output and "Layla" not in output
    assert "RuntimeError" in output


async def test_access_logs_omit_queries_bodies_and_raw_paths(settings: Settings) -> None:
    app = create_app(settings)
    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    log = logging.getLogger("adapt.access")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/unknown/Layla-marriage-document",
                params={"q": "Z1234567"},
                json={"text": "Layla certificate"},
            )
    finally:
        log.removeHandler(handler)
    output = capture.getvalue()
    assert output and "Z1234567" not in output and "Layla" not in output


async def test_rls_runtime_role_misconfiguration_fails_closed() -> None:
    db = Database("postgresql+psycopg://test:test@localhost/test", require_rls=True)
    connection = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one=lambda: False))
    )

    @asynccontextmanager
    async def connect():
        yield connection

    original_engine = db.engine
    db.engine = SimpleNamespace(connect=connect)
    try:
        with pytest.raises(AdapterUnavailable) as error:
            async with db.public_session():
                pytest.fail("unsafe runtime connection was allowed")
        assert error.value.code == "unsafe_database_role"
        assert not db._role_checked
    finally:
        await original_engine.dispose()


def test_public_transactions_explicitly_clear_previous_private_context() -> None:
    calls = []
    connection = SimpleNamespace(execute=lambda query, args: calls.append(args))
    owner = Principal(user_id=uuid4(), tenant_id=uuid4())
    _apply_rls_context(SimpleNamespace(info={"adapt.principal": owner}), None, connection)
    _apply_rls_context(SimpleNamespace(info={}), None, connection)
    assert calls == [
        {"user_id": str(owner.user_id), "tenant_id": str(owner.tenant_id)},
        {"user_id": "", "tenant_id": ""},
    ]


def test_development_credentials_are_private_persistent_and_not_shared(tmp_path: Path) -> None:
    def load(directory):
        return Settings(
            _env_file=None, session_secret="dev-only-placeholder", document_storage_dir=directory
        )

    a = load(tmp_path / "a").session_secret.get_secret_value()
    assert len(a) >= 32 and not a.startswith("dev-only")
    assert load(tmp_path / "a").session_secret.get_secret_value() == a
    assert load(tmp_path / "b").session_secret.get_secret_value() != a


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"session_cookie_secure": False}, "SESSION_COOKIE_SECURE"),
        ({"database_echo": True}, "DATABASE_ECHO"),
        ({"public_base_url": "http://adapt.test"}, "PUBLIC_BASE_URL"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
    ],
)
def test_production_rejects_unsafe_security_settings(changes: dict, field: str) -> None:
    base = dict(
        adapt_env="production",
        session_secret=SECRET,
        document_encryption_key="k" * 44,
        demo_auth_enabled=False,
        public_base_url="https://adapt.test",
    )
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **{**base, **changes})


@pytest.mark.parametrize("status", ["confirmed", "completed"])
@pytest.mark.parametrize(
    "receipt",
    [None, {"provider": "Provider", "reference": "WRONG", "confirmed_at": "2026-10-01T00:00:00Z"}],
)
def test_a_reference_alone_never_books_an_appointment(status: str, receipt: dict | None) -> None:
    with pytest.raises(ValidationError, match=r"confirmation|reference"):
        AppointmentOut(
            id=uuid4(),
            title="Biometrics",
            status=status,
            external_reference="USER-TYPED",
            booking_confirmation=receipt,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_actual_provider_receipt_can_be_displayed() -> None:
    appointment = AppointmentOut(
        id=uuid4(),
        title="Biometrics",
        status="confirmed",
        external_reference="PROVIDER-1",
        booking_confirmation={
            "provider": "Provider",
            "reference": "PROVIDER-1",
            "confirmed_at": "2026-10-01T00:00:00Z",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert appointment.booking_confirmation.reference == "PROVIDER-1"


@pytest.mark.parametrize(
    "attribute", ["Religion", " faith ", "sexual-orientation", "Health Condition"]
)
def test_sensitive_attribute_aliases_cannot_be_inferred(attribute: str) -> None:
    with pytest.raises(SensitiveAttributeError, match="never infers"):
        validate_twin_facts(
            {attribute: TwinFact(value="guess", source=FactSource.INFERRED)},
            faith_consent=ConsentStatus.GRANTED,
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://u.ae.evil.test/",
        "https://user@u.ae/",
        "https://u.ae:8443/",
        "http://u.ae/",
        "https://u.ae:bad/",
    ],
)
def test_spoofed_official_urls_never_become_government_evidence(url: str) -> None:
    assert not is_official_source(url)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///passport.txt", "https://user:password@example.org/"]
)
def test_citation_links_reject_active_schemes_and_credentials(url: str) -> None:
    with pytest.raises(ValidationError):
        Citation(source_url=url, source_title="Source")


@pytest.mark.parametrize(
    "status,annotations",
    [
        ("incomplete", []),
        ("completed", []),
        (
            "completed",
            [
                SimpleNamespace(
                    type="url_citation",
                    url="javascript:alert(1)",
                    title="Bad",
                    start_index=0,
                    end_index=5,
                )
            ],
        ),
        (
            "completed",
            [
                SimpleNamespace(
                    type="url_citation",
                    url="https://u.ae/",
                    title="Bad span",
                    start_index=0,
                    end_index=9999,
                )
            ],
        ),
    ],
)
async def test_incomplete_uncited_and_invalid_search_answers_are_rejected(
    status: str, annotations: list
) -> None:
    response = SimpleNamespace(
        status=status,
        output_text="Unverified claim",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(text="Unverified claim", annotations=annotations)],
            )
        ],
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=response)))
    researcher = OpenAIWebResearcher(client, model="test")
    with pytest.raises(UpstreamError):
        await researcher.research(query="q", instructions="i")


async def test_page_fetch_connects_to_validated_ip_and_preserves_tls_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    resolved = AsyncMock(return_value=["93.184.216.34"])
    monkeypatch.setattr("app.adapters.web_fetch.assert_public_url", resolved)

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="Verified page")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        page = await SafeHttpPageFetcher(client=client).fetch_text(
            "https://club.example.org/contact"
        )
    assert page and page.final_url == "https://club.example.org/contact"
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "club.example.org"
    assert requests[0].extensions["sni_hostname"] == "club.example.org"
    resolved.assert_awaited_once()


async def test_page_redirect_to_private_service_is_blocked() -> None:
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secrets"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        page = await SafeHttpPageFetcher(client=client).fetch_text("https://93.184.216.34/")
    assert page is None and len(requests) == 1
    with pytest.raises(UnsafeUrl):
        await assert_public_url("https://user:password@93.184.216.34/")
