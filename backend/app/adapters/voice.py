"""OpenAI Realtime session minting. The browser connects over WebRTC with an ephemeral key.

The server fixes the whole session configuration (model, instructions, tools, turn
detection, transcription) when it mints the client secret, so the browser only ever holds
a short-lived credential that can open a call. The long-lived API key stays here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

from app.contracts.voice import AudioProfile, VoiceSessionOut, VoiceToolSpec
from app.core.errors import AdapterUnavailable, UpstreamError

logger = logging.getLogger(__name__)

REALTIME_WEBRTC_URL = "https://api.openai.com/v1/realtime/calls"
# The secret only has to outlive the WebRTC handshake: a fresh one is minted for every
# connection attempt, including reconnects, so keep the exposure window short.
CLIENT_SECRET_TTL_SECONDS = 120

# Domain vocabulary that generic transcription often mishears. Only sent to transcription
# models that accept keyword hints.
TRANSCRIPTION_KEYWORDS: tuple[str, ...] = (
    "Abu Dhabi",
    "ADGM",
    "ADDED",
    "ICP",
    "TAMM",
    "UAE PASS",
    "Emirates ID",
    "Tawtheeq",
    "MoFA",
    "DoH",
    "establishment card",
    "trade licence",
    "Golden Visa",
)
_KEYWORD_TRANSCRIBERS = frozenset({"gpt-transcribe", "gpt-live-transcribe"})

ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]


class VoiceSessionProvider(Protocol):
    provider: str
    mode: Literal["live", "demo"]

    async def create_session(
        self,
        *,
        instructions: str,
        tools: list[VoiceToolSpec],
        audio_profile: AudioProfile = "near_field",
    ) -> VoiceSessionOut: ...


def _is_reasoning_model(model: str) -> bool:
    # gpt-realtime-2 and later reason; gpt-realtime / -1.5 / -mini do not accept `reasoning`.
    return model.startswith("gpt-realtime-2")


class OpenAIRealtimeProvider:
    provider = "openai"
    mode: Literal["live", "demo"] = "live"

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        voice: str,
        transcription_model: str = "gpt-transcribe",
        reasoning_effort: ReasoningEffort = "low",
    ) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self._transcription_model = transcription_model
        self._reasoning_effort = reasoning_effort

    def session_config(
        self, *, instructions: str, tools: list[VoiceToolSpec], audio_profile: AudioProfile
    ) -> dict[str, Any]:
        transcription: dict[str, Any] = {"model": self._transcription_model}
        if self._transcription_model in _KEYWORD_TRANSCRIBERS:
            transcription["keywords"] = list(TRANSCRIPTION_KEYWORDS)
        # No `language` for transcription: people may speak any language the model
        # supports and switch mid-conversation.
        session: dict[str, Any] = {
            "type": "realtime",
            "model": self._model,
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "noise_reduction": {"type": audio_profile},
                    "transcription": transcription,
                    # Semantic VAD waits through "umm" and mid-sentence pauses. Speaking
                    # over the assistant cancels its response (barge-in); over WebRTC the
                    # server also truncates the unplayed audio from the conversation.
                    "turn_detection": {
                        "type": "semantic_vad",
                        "eagerness": "auto",
                        "create_response": True,
                        "interrupt_response": True,
                    },
                },
                "output": {"voice": self._voice},
            },
            "tools": [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in tools
            ],
            "tool_choice": "auto",
        }
        if _is_reasoning_model(self._model):
            session["reasoning"] = {"effort": self._reasoning_effort}
        return session

    async def create_session(
        self,
        *,
        instructions: str,
        tools: list[VoiceToolSpec],
        audio_profile: AudioProfile = "near_field",
    ) -> VoiceSessionOut:
        try:
            secret = await self._client.realtime.client_secrets.create(
                expires_after={"anchor": "created_at", "seconds": CLIENT_SECRET_TTL_SECONDS},
                session=self.session_config(  # type: ignore[arg-type]
                    instructions=instructions, tools=tools, audio_profile=audio_profile
                ),
            )
        except AuthenticationError as exc:
            logger.error("voice_session_auth_failed")  # misconfigured key: developer action
            raise UpstreamError(
                "Voice could not be started", code="voice_provider_rejected"
            ) from exc
        except RateLimitError as exc:
            raise AdapterUnavailable(
                "Voice is busy right now. Try again in a moment, or type instead.",
                code="voice_busy",
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise UpstreamError(
                "The voice service did not respond", code="voice_provider_unreachable"
            ) from exc
        except OpenAIError as exc:
            logger.warning("voice_session_failed", extra={"error": type(exc).__name__})
            raise UpstreamError("Voice could not be started", code="voice_provider_error") from exc
        return VoiceSessionOut(
            mode="live",
            client_secret=secret.value,
            expires_at=datetime.fromtimestamp(secret.expires_at, UTC),
            model=self._model,
            voice=self._voice,
            webrtc_url=REALTIME_WEBRTC_URL,
            tools=tools,
        )


class UnavailableVoiceProvider:
    """Demo mode: no voice. The UI switches to the text assistant, which uses the same
    tools. Nothing here imitates speech."""

    provider = "adapt-demo"
    mode: Literal["live", "demo"] = "demo"

    async def create_session(
        self,
        *,
        instructions: str,
        tools: list[VoiceToolSpec],
        audio_profile: AudioProfile = "near_field",
    ) -> VoiceSessionOut:
        return VoiceSessionOut(
            mode="unavailable",
            tools=tools,
            unavailable_reason="Voice isn't available right now. You can type instead.",
        )
