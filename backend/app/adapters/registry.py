"""Builds every third-party adapter from settings, once per process.

Mode resolution per capability (`ADAPTER_<CAPABILITY>` = auto | live | demo):
auto -> live when OPENAI_API_KEY is set, otherwise the deterministic demo adapter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Protocol

from openai import AsyncOpenAI

from app.adapters.actions import (
    ActionAdapterRegistry,
    build_action_registry,
    resolve_actions_mode,
)
from app.adapters.assistant import AssistantModel, DemoAssistantModel, OpenAIAssistantModel
from app.adapters.embeddings import Embedder, HashingEmbedder, OpenAIEmbedder
from app.adapters.llm import DemoLLM, LLMClient, OpenAILLM
from app.adapters.ocr import ChainedReader, DocumentReader, LocalTextReader, OpenAIVisionReader
from app.adapters.storage import DocumentStorage, LocalEncryptedStorage, derive_dev_key
from app.adapters.voice import (
    OpenAIRealtimeProvider,
    UnavailableVoiceProvider,
    VoiceSessionProvider,
)
from app.adapters.web_search import OfflineWebResearcher, OpenAIWebResearcher, WebResearcher
from app.contracts.system import AdapterInfo
from app.core.config import Settings

logger = logging.getLogger(__name__)


class _Described(Protocol):
    """What every capability adapter reports about itself."""

    @property
    def provider(self) -> str: ...

    @property
    def mode(self) -> Literal["live", "demo"]: ...


@dataclass
class Adapters:
    llm: LLMClient
    embeddings: Embedder
    ocr: DocumentReader
    voice: VoiceSessionProvider
    # Text assistant (voice fallback). Part of the `llm` capability: live when the LLM is.
    assistant: AssistantModel
    web_search: WebResearcher
    actions: ActionAdapterRegistry
    storage: DocumentStorage
    _openai: AsyncOpenAI | None = field(default=None, repr=False)

    def infos(self) -> list[AdapterInfo]:
        items: list[tuple[str, _Described]] = [
            ("llm", self.llm),
            ("embeddings", self.embeddings),
            ("ocr", self.ocr),
            ("voice", self.voice),
            ("web_search", self.web_search),
        ]
        infos = [
            AdapterInfo(capability=name, mode=a.mode, provider=a.provider) for name, a in items
        ]
        infos.append(
            AdapterInfo(
                capability="actions", mode=self.actions.mode, provider=",".join(self.actions.names)
            )
        )
        return infos

    @property
    def demo_capabilities(self) -> list[str]:
        return [info.capability for info in self.infos() if info.mode == "demo"]

    async def aclose(self) -> None:
        if self._openai is not None:
            await self._openai.close()


def build_adapters(settings: Settings) -> Adapters:
    cfg = settings.openai
    client: AsyncOpenAI | None = None

    def openai_client() -> AsyncOpenAI:
        nonlocal client
        if client is None:
            client = AsyncOpenAI(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                organization=cfg.organization,
                timeout=cfg.timeout_seconds,
                max_retries=2,
            )
        return client

    llm: LLMClient = (
        OpenAILLM(openai_client(), reasoning_model=cfg.reasoning_model, fast_model=cfg.fast_model)
        if settings.resolve_adapter("llm") == "live"
        else DemoLLM()
    )
    embeddings: Embedder = (
        OpenAIEmbedder(openai_client(), model=cfg.embedding_model)
        if settings.resolve_adapter("embeddings") == "live"
        else HashingEmbedder()
    )
    # Local text-layer reading first (exact, offline, nothing leaves the server); vision
    # only when a key is configured. Without one, unreadable documents go to user review.
    ocr: DocumentReader = (
        ChainedReader(
            [LocalTextReader(), OpenAIVisionReader(openai_client(), model=cfg.vision_model)]
        )
        if settings.resolve_adapter("ocr") == "live"
        else LocalTextReader()
    )
    voice: VoiceSessionProvider = (
        OpenAIRealtimeProvider(
            openai_client(),
            model=cfg.realtime_model,
            voice=cfg.realtime_voice,
            transcription_model=getattr(cfg, "realtime_transcription_model", "gpt-transcribe"),
            reasoning_effort=getattr(cfg, "realtime_reasoning_effort", "low"),
        )
        if settings.resolve_adapter("voice") == "live"
        else UnavailableVoiceProvider()
    )
    assistant: AssistantModel = (
        OpenAIAssistantModel(openai_client(), model=cfg.fast_model)
        if settings.resolve_adapter("llm") == "live"
        else DemoAssistantModel()
    )
    web_search: WebResearcher = (
        OpenAIWebResearcher(openai_client(), model=cfg.research_model)
        if settings.resolve_adapter("web_search") == "live"
        else OfflineWebResearcher()
    )

    actions = build_action_registry(
        resolve_actions_mode(
            getattr(settings, "adapter_actions", None), production=settings.is_production
        )
    )

    if settings.document_encryption_key is not None:
        key = settings.document_encryption_key.get_secret_value().encode()
    else:
        key = derive_dev_key(settings.session_secret.get_secret_value())
    storage = LocalEncryptedStorage(settings.document_storage_dir, key)

    adapters = Adapters(
        llm=llm,
        embeddings=embeddings,
        ocr=ocr,
        voice=voice,
        assistant=assistant,
        web_search=web_search,
        actions=actions,
        storage=storage,
        _openai=client,
    )
    demo = adapters.demo_capabilities
    if demo:
        logger.warning(
            "DEMO ADAPTERS ACTIVE for: %s (set OPENAI_API_KEY for live AI capabilities)",
            ", ".join(demo),
        )
    return adapters
