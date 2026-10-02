"""Configuration, session tokens, adapters, OpenAPI contract and basic API behaviour."""

from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.embeddings import HashingEmbedder
from app.adapters.llm import DemoLLM
from app.adapters.ocr import DocumentUnreadable, LocalTextReader, ReadRequest
from app.adapters.registry import build_adapters
from app.contracts.agents import AgentTopology
from app.core.config import Settings
from app.core.errors import AdapterUnavailable, Unauthorized
from app.core.security import issue_session_token, verify_session_token
from app.domain.principal import Principal
from app.main import create_app

CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.json"


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adapter_llm": "auto",
        "adapter_embeddings": "auto",
        "adapter_ocr": "auto",
        "adapter_voice": "auto",
        "adapter_web_search": "auto",
        "openai_api_key": None,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]


class TestSettings:
    def test_auto_without_key_is_demo(self) -> None:
        assert settings().resolve_adapter("llm") == "demo"

    def test_auto_with_key_is_live(self) -> None:
        s = settings(openai_api_key="sk-test")
        assert s.resolve_adapter("voice") == "live"

    def test_forced_demo_wins_over_key(self) -> None:
        assert (
            settings(openai_api_key="sk-test", adapter_ocr="demo").resolve_adapter("ocr") == "demo"
        )

    def test_live_without_key_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="requires OPENAI_API_KEY"):
            settings(adapter_llm="live").resolve_adapter("llm")

    def test_blank_key_is_no_key(self) -> None:
        assert not settings(openai_api_key="  ").openai.configured

    def test_cors_origins_from_csv(self) -> None:
        s = settings(cors_origins="http://a.test, http://b.test")
        assert s.cors_origins == ["http://a.test", "http://b.test"]

    def test_production_rejects_dev_secrets(self) -> None:
        with pytest.raises(ValidationError, match="SESSION_SECRET"):
            settings(adapt_env="production")

    def test_production_rejects_demo_auth(self) -> None:
        with pytest.raises(ValidationError, match="DEMO_AUTH_ENABLED"):
            settings(
                adapt_env="production",
                session_secret="x" * 48,
                document_encryption_key="k" * 44,
            )


class TestSessionTokens:
    def test_round_trip(self) -> None:
        principal = Principal(user_id=uuid4(), tenant_id=uuid4(), is_demo=True)
        issued = issue_session_token(principal, secret="s" * 40, ttl_hours=1)
        assert verify_session_token(issued.token, secret="s" * 40) == principal

    def test_wrong_secret(self) -> None:
        issued = issue_session_token(
            Principal(user_id=uuid4(), tenant_id=uuid4()), secret="s" * 40, ttl_hours=1
        )
        with pytest.raises(Unauthorized):
            verify_session_token(issued.token, secret="t" * 40)

    def test_expired(self) -> None:
        issued = issue_session_token(
            Principal(user_id=uuid4(), tenant_id=uuid4()), secret="s" * 40, ttl_hours=-1
        )
        with pytest.raises(Unauthorized) as exc:
            verify_session_token(issued.token, secret="s" * 40)
        assert exc.value.code == "session_expired"


class TestAdapters:
    def test_registry_reports_demo_capabilities(self, tmp_path: Path) -> None:
        adapters = build_adapters(settings(document_storage_dir=tmp_path))
        assert set(adapters.demo_capabilities) == {
            "llm",
            "embeddings",
            "ocr",
            "voice",
            "web_search",
            "actions",  # demo previews of government actions outside production
        }

    async def test_hashing_embeddings_are_deterministic_and_normalised(self) -> None:
        embedder = HashingEmbedder()
        a1, a2, b = await embedder.embed(
            [
                "family residence visa sponsorship",
                "family residence visa sponsorship",
                "trade licence",
            ]
        )
        assert a1 == a2
        assert len(a1) == embedder.dimensions
        assert math.isclose(sum(v * v for v in a1), 1.0, rel_tol=1e-9)
        similar = sum(
            x * y
            for x, y in zip(a1, (await embedder.embed(["spouse residence visa"]))[0], strict=True)
        )
        different = sum(x * y for x, y in zip(a1, b, strict=True))
        assert similar > different

    async def test_demo_llm_refuses_to_invent(self) -> None:
        with pytest.raises(AdapterUnavailable):
            await DemoLLM().text(purpose="journey.plan", instructions="", input="hi")

    async def test_offline_reader_never_invents_values(self) -> None:
        """Without a vision provider an image is unreadable (no specimen values)."""
        with pytest.raises(DocumentUnreadable):
            await LocalTextReader().read(ReadRequest(bytes([0xFF, 0xD8, 0xFF]), "image/jpeg", ()))

    async def test_encrypted_storage_round_trip(self, tmp_path: Path) -> None:
        storage = build_adapters(settings(document_storage_dir=tmp_path)).storage
        key = f"{uuid4()}/{uuid4()}"
        await storage.put(key, b"passport bytes")
        on_disk = next(tmp_path.rglob("*.bin")).read_bytes()  # noqa: ASYNC240
        assert b"passport bytes" not in on_disk
        assert await storage.get(key) == b"passport bytes"
        await storage.delete(key)
        with pytest.raises(ValueError):
            await storage.put("../../etc/passwd", b"x")


class TestApi:
    @pytest.fixture
    def app(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        return create_app(settings(document_storage_dir=tmp_path))

    async def test_health_and_headers(self, app) -> None:  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            r = await c.get("/api/health")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-request-id"]
        assert "llm" in r.headers["x-adapt-demo-adapters"]

    async def test_private_endpoints_require_session(self, app) -> None:  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            for path in ("/api/me", "/api/profile", "/api/graph/user", f"/api/agents/{uuid4()}"):
                r = await c.get(path)
                assert r.status_code == 401, path
                assert r.headers["content-type"] == "application/problem+json"
                assert r.json()["code"] == "session_missing"

    async def test_validation_errors_are_problem_details(self, app) -> None:  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            r = await c.post("/api/auth/demo-session", json={"display_name": "x" * 500})
        assert r.status_code == 422
        assert r.json()["code"] == "validation_failed"
        assert "display_name" in r.json()["errors"][0]["loc"]

    async def test_topology_endpoint(self, app) -> None:  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
            r = await c.get("/api/agents/journey/topology")
        AgentTopology.model_validate(r.json())


class TestContracts:
    def test_generated_contract_is_up_to_date(self, tmp_path: Path) -> None:
        """Fails when API models change without regenerating packages/contracts."""
        app = create_app(settings(document_storage_dir=tmp_path))
        current = json.loads(json.dumps(app.openapi()))
        committed = json.loads(CONTRACTS.read_text(encoding="utf-8"))
        assert current == committed, "run `npm run contracts:generate` and commit the result"

    def test_event_union_is_exported(self, tmp_path: Path) -> None:
        schemas = create_app(settings(document_storage_dir=tmp_path)).openapi()["components"][
            "schemas"
        ]
        assert "discriminator" in schemas["AgentEvent"]
        assert schemas["AgentEvent"]["discriminator"]["propertyName"] == "event"
        for name in (
            "JourneyOut",
            "ActionOut",
            "ActionApprovalOut",
            "FullProfileOut",
            "GeneratedDocumentOut",
            "VoiceSessionOut",
        ):
            assert name in schemas
