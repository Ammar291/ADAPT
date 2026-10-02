from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.deps import get_principal
from app.core.config import Settings
from app.core.errors import (
    AdapterUnavailable,
    BadRequest,
    Forbidden,
    UpstreamError,
    install_error_handlers,
)
from app.core.middleware import RequestContextMiddleware
from app.domain.principal import Principal
from app.interpreter.contracts import SessionRequest
from app.interpreter.provider import MODEL, OpenAITranslationProvider
from app.interpreter.router import router
from app.interpreter.service import InterpreterSessionService, RateLimited


class Store:
    def __init__(self):
        self.data = {}

    async def eval(self, _script, _n, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, **_kwargs):
        self.data[key] = value


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, document_storage_dir=tmp_path, interpreter_mode="demo")


@pytest.fixture
def principal():
    return Principal(user_id=uuid4(), tenant_id=uuid4())


def sessions(settings, principal, store=None, provider=None):
    return InterpreterSessionService(
        provider or OpenAITranslationProvider(settings), store or Store(), settings, principal
    )


def test_capabilities_do_not_claim_arabic_output(settings):
    cap = OpenAITranslationProvider(settings).capabilities()
    ar = next(lang for lang in cap.languages if lang.code == "ar")
    hi = next(lang for lang in cap.languages if lang.code == "hi")
    assert ar.input and not ar.output and ar.rtl
    assert hi.input and hi.output
    assert cap.model == MODEL and cap.mode == "demo"


@pytest.mark.parametrize("source,target", [("en", "en"), ("en", "xx"), ("xx", "hi")])
async def test_unsupported_pair_rejected_before_mint(settings, principal, source, target):
    with pytest.raises(BadRequest):
        await sessions(settings, principal).create(SessionRequest(source=source, target=target))


async def test_arabic_requires_enabled_fallback(settings, principal):
    settings.interpreter_fallback_enabled = False
    with pytest.raises(BadRequest):
        await sessions(settings, principal).create(SessionRequest(source="en", target="ar"))


async def test_demo_session_and_swap_have_separate_streams_without_credentials(settings, principal):
    service = sessions(settings, principal)
    for source, target in [("en", "ar"), ("ar", "en"), ("en", "hi")]:
        result = await service.create(SessionRequest(source=source, target=target))
        assert [(s.speaker, s.source, s.target) for s in result.streams] == [
            ("a", source, target),
            ("b", target, source),
        ]
        assert all(s.client_secret is None and s.transport == "demo" for s in result.streams)


async def test_session_reconnect_binding_expiration_and_end(settings, principal):
    store = Store()
    service = sessions(settings, principal, store)
    pair = SessionRequest(source="en", target="hi")
    original = await service.create(pair)
    renewed = await service.create(pair, original.session_id)
    assert renewed.session_id == original.session_id and renewed.expires_at == original.expires_at
    other = sessions(settings, Principal(uuid4(), principal.tenant_id), store)
    with pytest.raises(Forbidden):
        await other.verify(original.session_id)
    claims = await service.verify(original.session_id)
    expired = jwt.encode({**claims, "exp": int(time.time()) - 1}, service.key, algorithm="HS256")
    with pytest.raises(Forbidden):
        await service.verify(expired)
    with pytest.raises(Forbidden):
        await service.verify(original.session_id + "tamper")
    await service.end(original.session_id)
    with pytest.raises(Forbidden):
        await service.create(pair, original.session_id)


async def test_rate_limits_fail_closed(settings, principal):
    store = Store()
    service = sessions(settings, principal, store)
    for _ in range(10):
        await service.create(SessionRequest(source="en", target="hi"))
    with pytest.raises(RateLimited):
        await service.create(SessionRequest(source="en", target="hi"))
    store.eval = AsyncMock(side_effect=RedisConnectionError("offline"))
    with pytest.raises(AdapterUnavailable):
        await service.create(SessionRequest(source="en", target="hi"))


async def test_official_sdk_post_schema_primary_key_never_in_result(settings, principal):
    settings.interpreter_mode = "live"
    settings.openai_api_key = SecretStr("sk-server-secret-never-send")
    calls = []

    def upstream(request):
        calls.append(request)
        config = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "value": f"ek-{len(calls)}",
                "expires_at": int(time.time()) + 120,
                "session": {
                    "expires_at": int(time.time()) + 3600,
                    "audio": config["session"]["audio"],
                },
            },
        )

    async with AsyncOpenAI(
        api_key=settings.openai.api_key,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    ) as client:
        service = sessions(
            settings, principal, provider=OpenAITranslationProvider(settings, client)
        )
        result = await service.create(SessionRequest(source="en", target="hi"))
        assert [s.client_secret for s in result.streams] == ["ek-1", "ek-2"]
        renewed = await service.create(SessionRequest(source="en", target="hi"), result.session_id)
        assert renewed.streams[0].client_secret == "ek-3"
        assert settings.openai.api_key not in result.model_dump_json()
        config = json.loads(calls[0].content)
        assert calls[0].url.path == "/v1/realtime/translations/client_secrets"
        assert config["session"]["model"] == "gpt-realtime-translate"
        assert (
            config["session"]["audio"]["input"]["transcription"]["model"] == "gpt-realtime-whisper"
        )
        assert config["expires_after"]["seconds"] == 120
        assert not {"tools", "instructions", "voice", "turn_detection"} & config["session"].keys()
        assert [
            json.loads(c.content)["session"]["audio"]["output"]["language"] for c in calls[:2]
        ] == ["hi", "en"]
        hybrid = await service.create(SessionRequest(source="en", target="ar"))
        assert [s.transport for s in hybrid.streams] == ["recorded", "webrtc"]
        before = len(calls)
        recorded = await service.create(SessionRequest(source="en", target="hi", recorded=True))
        assert len(calls) == before and all(s.transport == "recorded" for s in recorded.streams)


async def test_tts_failure_preserves_translated_text(settings):
    from openai import APIConnectionError

    client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(text="Help"))
            ),
            speech=SimpleNamespace(
                create=AsyncMock(
                    side_effect=APIConnectionError(
                        request=httpx.Request("POST", "https://api.openai.com")
                    )
                )
            ),
        ),
        responses=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(output_text="مساعدة"))
        ),
    )
    result = await OpenAITranslationProvider(settings, client).translate_recording(
        "a", "en", "ar", b"synthetic audio", "audio/webm"
    )
    assert result.original == "Help" and result.translation == "مساعدة"
    assert result.audio_error and result.audio_base64 is None
    assert client.responses.create.call_args.kwargs["store"] is False


@pytest.mark.parametrize("dedicated", [False, True])
async def test_sdk_paths_refuse_primary_key_as_session_credential(settings, dedicated):
    payload = {"value": "sk-server-secret", "expires_at": int(time.time()) + 120, "session": {}}
    client = SimpleNamespace(
        realtime=SimpleNamespace(), post=AsyncMock(return_value=payload)
    )
    if dedicated:
        client.realtime.translations = SimpleNamespace(
            client_secrets=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(model_dump=lambda: payload))
            )
        )
    with pytest.raises(UpstreamError) as error:
        await OpenAITranslationProvider(settings, client).credential("a", "en", "hi")
    assert "sk-server-secret" not in str(error.value)


async def test_dedicated_sdk_resource_returns_only_ephemeral_credential(settings):
    payload = {"value": "ek-ephemeral", "expires_at": int(time.time()) + 120, "session": {}}
    create = AsyncMock(return_value=SimpleNamespace(model_dump=lambda: payload))
    client = SimpleNamespace(
        realtime=SimpleNamespace(
            translations=SimpleNamespace(client_secrets=SimpleNamespace(create=create))
        )
    )
    result = await OpenAITranslationProvider(settings, client).credential("b", "hi", "en")
    assert result.client_secret == "ek-ephemeral"
    assert create.call_args.kwargs["session"]["model"] == MODEL


async def test_unstarted_session_expiry_is_unknown_not_expired(settings):
    # The provider answers expires_at 0 until the WebRTC call starts. Reporting 0 made the
    # browser treat every new session as already expired and reconnect in a loop.
    expires = int(time.time()) + 120
    payload = {"value": "ek-new", "expires_at": expires, "session": {"expires_at": 0}}
    client = SimpleNamespace(realtime=SimpleNamespace(), post=AsyncMock(return_value=payload))
    result = await OpenAITranslationProvider(settings, client).credential("a", "en", "hi")
    assert result.session_expires_at is None


async def test_router_auth_no_store_lifecycle_and_upload_validation(settings, principal):
    app = FastAPI()
    app.state.container = SimpleNamespace(settings=settings, redis=Store())
    app.include_router(router, prefix="/api")
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/interpreter/capabilities")).status_code == 200
        assert (await client.post("/api/interpreter/session", json={})).status_code == 401
        assert (await client.post("/api/interpreter/text", json={"text": "Hello"})).status_code == 401
        app.dependency_overrides[get_principal] = lambda: principal
        assert (await client.post("/api/interpreter/text", json={"text": "Hello", "source": "en", "target": "en"})).status_code == 400
        assert (await client.post("/api/interpreter/text", json={"text": "x" * 6001})).status_code == 422
        assert (await client.post("/api/interpreter/text", json={"text": "Hello"})).status_code == 503
        response = await client.post(
            "/api/interpreter/session", json={"source": "en", "target": "hi"}
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        ref = {"session_id": response.json()["session_id"]}
        assert (await client.post("/api/interpreter/reconnect", json=ref)).status_code == 200
        assert (
            await client.post(
                "/api/interpreter/recording",
                data={**ref, "speaker": "c"},
                files={"audio": ("a.webm", b"x", "audio/webm")},
            )
        ).status_code == 422
        assert (await client.post("/api/interpreter/end", json=ref)).status_code == 204
        assert (await client.post("/api/interpreter/reconnect", json=ref)).status_code == 403


async def test_text_fallback_translates_without_microphone_audio_or_tools(settings):
    create = AsyncMock(return_value=SimpleNamespace(output_text="مرحبا"))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = await OpenAITranslationProvider(settings, client).translate_text(
        "a", "en", "ar", "Hello"
    )
    assert result.original == "Hello" and result.translation == "مرحبا"
    assert result.audio_base64 is None
    arguments = create.call_args.kwargs
    assert arguments["store"] is False and "tools" not in arguments
    assert "Do not answer questions, perform actions" in arguments["instructions"]
