"""Voice assistant contracts (OpenAI Realtime over WebRTC, with a text fallback).

The backend mints a short-lived Realtime client secret. The browser uses it to open a
WebRTC call, so the long-lived OpenAI API key never leaves the server. When the model
calls a tool, the browser forwards the call to `POST /voice/tool-calls`. The server
validates the arguments and runs the tool against ADAPT's own API as the signed-in user,
then returns the output the browser hands back to the model. When voice is unavailable,
`POST /voice/assistant` offers the same tools over text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.contracts.common import ApiModel

AudioProfile = Literal["near_field", "far_field"]
"""Microphone situation, for noise reduction: `near_field` for headsets and phones held
close, `far_field` for laptop or speakerphone microphones."""

ToolStatus = Literal[
    "ok",
    "not_found",
    "unavailable",
    "needs_consent",
    "needs_approval",
    "invalid_arguments",
    "error",
]


class VoiceToolSpec(ApiModel):
    name: str
    label: str = Field(description="Short progress label for the UI, e.g. 'Checking your plan'")
    description: str
    parameters: dict[str, Any] = Field(description="JSON schema of the tool arguments")


class VoiceSessionRequest(ApiModel):
    language: str | None = Field(
        default=None,
        max_length=35,
        description="BCP-47 hint only. The assistant follows the language the user speaks.",
    )
    journey_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    audio_profile: AudioProfile = "near_field"
    resumed: bool = Field(
        default=False, description="True when reconnecting after a dropped connection"
    )


class VoiceSessionOut(ApiModel):
    mode: Literal["live", "unavailable"]
    session_id: str | None = Field(
        default=None, description="ADAPT voice session; tool calls must reference it"
    )
    client_secret: str | None = Field(
        default=None, description="Ephemeral Realtime secret, valid only for connecting"
    )
    expires_at: datetime | None = None
    model: str | None = None
    voice: str | None = None
    webrtc_url: str | None = None
    tools: list[VoiceToolSpec] = Field(default_factory=list)
    unavailable_reason: str | None = None


class ToolActivity(ApiModel):
    """What the UI shows while and after a tool runs."""

    call_id: str
    name: str
    label: str
    status: ToolStatus
    summary: str | None = None


class ApprovalRequest(ApiModel):
    """A prepared action awaiting the user's decision. The model can never approve it."""

    action_id: str
    title: str
    summary: str
    consequences: list[str] = Field(default_factory=list)
    requires_user_authentication: bool = Field(
        default=False, description="The user signs in on the official site (e.g. UAE PASS)"
    )
    handoff_url: str | None = None
    kind: str | None = None
    simulation_label: str | None = Field(
        default=None,
        description="Shown prominently when a demonstration adapter would carry it out "
        "(e.g. 'DEMO / SIMULATED'): nothing real is booked or submitted",
    )


class ToolCitation(ApiModel):
    """A source behind a tool result, for the UI's sources list. `kind` is the trust tier."""

    title: str
    url: str
    authority: str | None = None
    retrieved_at: datetime | None = None
    kind: Literal[
        "authoritative_requirement", "official_guidance", "community_web", "ai_recommendation"
    ]


class ConsentRequest(ApiModel):
    """Personalisation the user must explicitly allow in the UI before it is used."""

    preference: Literal["faith_personalization", "community_personalization"]
    title: str
    detail: str


class VoiceToolCallRequest(ApiModel):
    session_id: str = Field(max_length=64)
    call_id: str = Field(max_length=128)
    name: str = Field(max_length=64)
    arguments: str = Field(
        max_length=8000, description="JSON-encoded arguments exactly as sent by the model"
    )


class VoiceToolCallResult(ApiModel):
    call_id: str
    name: str
    status: ToolStatus
    output: dict[str, Any] = Field(description="Returned to the model as the function output")
    activity: ToolActivity
    approval: ApprovalRequest | None = None
    consent: ConsentRequest | None = None
    citations: list[ToolCitation] = Field(default_factory=list)
    ui_hint: str | None = Field(
        default=None, description="Optional route the UI may offer, e.g. '/journey'"
    )


class ConversationMessage(ApiModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AssistantMessageRequest(ApiModel):
    """Text turn. The client sends recent history (including voice transcript) so context
    carries across voice and text without the server storing transcripts."""

    messages: list[ConversationMessage] = Field(min_length=1, max_length=40)
    language: str | None = Field(default=None, max_length=35)
    journey_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class AssistantMessageOut(ApiModel):
    mode: Literal["live", "demo"]
    reply: str
    tool_results: list[VoiceToolCallResult] = Field(default_factory=list)
