"""Typed configuration for every ADAPT process (API, worker, migrations, scripts).

All configuration comes from environment variables or a `.env` file. Field names map
one-to-one to upper-case env vars (`openai_api_key` -> `OPENAI_API_KEY`), which keeps
`.env.example` flat and greppable. Grouped, read-only views (`settings.openai`,
`settings.adapters`) are derived from the flat fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Dimensionality of the `rag_chunks.embedding` column. Changing it requires a migration.
EMBEDDING_DIMENSIONS = 1536

AdapterCapability = Literal["llm", "embeddings", "ocr", "voice", "web_search"]
ADAPTER_CAPABILITIES: tuple[AdapterCapability, ...] = (
    "llm",
    "embeddings",
    "ocr",
    "voice",
    "web_search",
)


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AdapterSetting(StrEnum):
    """How a third-party integration is resolved at startup."""

    AUTO = "auto"  # live when credentials exist, otherwise the deterministic demo adapter
    LIVE = "live"  # always live; startup fails if credentials are missing
    DEMO = "demo"  # always the deterministic demo adapter


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    api_key: str | None
    base_url: str | None
    organization: str | None
    reasoning_model: str
    fast_model: str
    vision_model: str
    research_model: str
    realtime_model: str
    realtime_voice: str
    realtime_transcription_model: str
    realtime_reasoning_effort: str
    embedding_model: str
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application -------------------------------------------------------------
    adapt_env: Environment = Environment.DEVELOPMENT
    app_name: str = "ADAPT"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_json: bool | None = None  # defaults to True in production
    api_prefix: str = "/api"
    public_base_url: str = "http://localhost:8080"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5180", "http://localhost:8080"]
    )

    # --- security ----------------------------------------------------------------
    session_secret: SecretStr = SecretStr("dev-only-insecure-session-secret-change-me-0000")
    session_cookie_name: str = "adapt_session"
    session_ttl_hours: int = 24 * 7
    session_cookie_secure: bool | None = None  # defaults to True in production
    demo_auth_enabled: bool = True
    document_encryption_key: SecretStr | None = None
    # Lifetime of signed document-content links (the session is required as well).
    document_url_ttl_seconds: int = 300

    # --- infrastructure ----------------------------------------------------------
    # Runtime role: NOT a superuser and NOT the table owner, so row-level security applies.
    database_url: str = "postgresql+psycopg://adapt_app:adapt_app@localhost:5432/adapt"
    # Owner role, used only for migrations and governance seeding.
    migration_database_url: str | None = None
    database_pool_size: int = 10
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    worker_queue_name: str = "adapt:queue"
    worker_max_jobs: int = 8
    worker_job_timeout_seconds: int = 15 * 60
    document_storage_dir: Path = Path("./var/documents")
    max_upload_bytes: int = 15 * 1024 * 1024

    # --- OpenAI ------------------------------------------------------------------
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_organization: str | None = None
    openai_reasoning_model: str = "gpt-5.5"
    openai_fast_model: str = "gpt-5.4-mini"
    openai_vision_model: str = "gpt-5.4-mini"
    openai_research_model: str = "gpt-5.4-mini"
    openai_realtime_model: str = "gpt-realtime-2.1"
    openai_realtime_voice: str = "marin"
    openai_realtime_transcription_model: str = "gpt-transcribe"
    openai_realtime_reasoning_effort: str = "low"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 60.0

    # Independent human-to-human interpreter; never uses the assistant model or graph.
    interpreter_mode: Literal["auto", "live", "demo"] = "auto"
    interpreter_fallback_enabled: bool = True
    interpreter_transcription_model: str = "gpt-4o-mini-transcribe"
    interpreter_translation_model: str = "gpt-5.4-mini"
    interpreter_tts_model: str = "gpt-4o-mini-tts"

    # --- adapter selection (auto | live | demo) ------------------------------------
    adapter_llm: AdapterSetting = AdapterSetting.AUTO
    adapter_embeddings: AdapterSetting = AdapterSetting.AUTO
    adapter_ocr: AdapterSetting = AdapterSetting.AUTO
    adapter_voice: AdapterSetting = AdapterSetting.AUTO
    adapter_web_search: AdapterSetting = AdapterSetting.AUTO
    # Government actions: auto = demo previews outside production, real official handoffs
    # in production; `demo` is refused in production (see adapters.registry).
    adapter_actions: AdapterSetting = AdapterSetting.AUTO

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @field_validator("openai_api_key", "document_encryption_key", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.is_production:
            secret = self.session_secret.get_secret_value()
            if secret.startswith("dev-only") or len(secret) < 32:
                raise ValueError("SESSION_SECRET must be a random value of 32+ chars in production")
            if self.document_encryption_key is None:
                raise ValueError("DOCUMENT_ENCRYPTION_KEY is required in production")
            if self.demo_auth_enabled:
                raise ValueError("DEMO_AUTH_ENABLED must be false in production")
            if self.session_cookie_secure is False:
                raise ValueError("SESSION_COOKIE_SECURE must be true in production")
            if self.database_echo:
                raise ValueError("DATABASE_ECHO must be false in production")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL must use https in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must name trusted origins in production")
        else:
            secret = self.session_secret.get_secret_value()
            if not secret or secret.startswith("dev-only"):
                from app.core.development_security import local_session_secret

                self.session_secret = SecretStr(
                    local_session_secret(
                        self.document_storage_dir,
                        has_document_key=self.document_encryption_key is not None,
                    )
                )
            elif len(secret) < 32:
                raise ValueError("SESSION_SECRET must contain 32+ characters")
        return self

    # --- derived -----------------------------------------------------------------
    @property
    def environment(self) -> Environment:
        return self.adapt_env

    @property
    def is_production(self) -> bool:
        return self.adapt_env is Environment.PRODUCTION

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is None:
            return self.is_production
        return self.session_cookie_secure

    @property
    def json_logs(self) -> bool:
        return self.is_production if self.log_json is None else self.log_json

    @property
    def owner_database_url(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def openai(self) -> OpenAIConfig:
        key = self.openai_api_key.get_secret_value().strip() if self.openai_api_key else None
        return OpenAIConfig(
            api_key=key or None,
            base_url=self.openai_base_url,
            organization=self.openai_organization,
            reasoning_model=self.openai_reasoning_model,
            fast_model=self.openai_fast_model,
            vision_model=self.openai_vision_model,
            research_model=self.openai_research_model,
            realtime_model=self.openai_realtime_model,
            realtime_voice=self.openai_realtime_voice,
            realtime_transcription_model=self.openai_realtime_transcription_model,
            realtime_reasoning_effort=self.openai_realtime_reasoning_effort,
            embedding_model=self.openai_embedding_model,
            timeout_seconds=self.openai_timeout_seconds,
        )

    def adapter_setting(self, capability: AdapterCapability) -> AdapterSetting:
        return AdapterSetting(getattr(self, f"adapter_{capability}"))

    def resolve_adapter(self, capability: AdapterCapability) -> Literal["live", "demo"]:
        """Resolve AUTO/LIVE/DEMO for a capability. LIVE without credentials is a hard error."""
        setting = self.adapter_setting(capability)
        if setting is AdapterSetting.DEMO:
            return "demo"
        if setting is AdapterSetting.LIVE:
            if not self.openai.configured:
                raise ValueError(f"ADAPTER_{capability.upper()}=live requires OPENAI_API_KEY")
            return "live"
        return "live" if self.openai.configured else "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
