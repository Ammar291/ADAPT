"""Voice and text assistant endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Request

from app.api.deps import ContainerDep, PrincipalDep
from app.contracts.voice import (
    AssistantMessageOut,
    AssistantMessageRequest,
    VoiceSessionOut,
    VoiceSessionRequest,
    VoiceToolCallRequest,
    VoiceToolCallResult,
)
from app.core.container import Container
from app.core.errors import Unauthorized
from app.core.logging import request_id_var
from app.domain.principal import Principal
from app.voice.gateway import ApiGateway, route_table
from app.voice.guard import AssistantGuard
from app.voice.service import AssistantService

router = APIRouter(tags=["voice"])


def _session_token(request: Request, cookie_name: str) -> str:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    token = token or request.cookies.get(cookie_name)
    if not token:  # unreachable after PrincipalDep, kept as a guard
        raise Unauthorized("Sign in to continue", code="session_missing")
    return token


@asynccontextmanager
async def _service(
    request: Request, container: Container, principal: Principal
) -> AsyncIterator[AssistantService]:
    settings = container.settings
    async with ApiGateway(
        request.app,
        route_table(request.app.routes),
        prefix=settings.api_prefix,
        token=_session_token(request, settings.session_cookie_name),
        request_id=request_id_var.get(),
    ) as gateway:
        yield AssistantService(
            principal=principal,
            gateway=gateway,
            guard=AssistantGuard(
                container.redis, secret=settings.session_secret.get_secret_value()
            ),
            voice=container.adapters.voice,
            model=container.adapters.assistant,
        )


@router.post(
    "/voice/session",
    response_model=VoiceSessionOut,
    summary="Start a voice session",
    description="Mints a short-lived OpenAI Realtime client secret with the session fixed "
    "server-side (instructions, tools, turn detection). The browser uses it to open a WebRTC "
    "call; the OpenAI API key never leaves the server. Returns `mode: unavailable` when "
    "voice can't be offered, and the UI switches to text.",
)
async def create_voice_session(
    body: VoiceSessionRequest, request: Request, principal: PrincipalDep, container: ContainerDep
) -> VoiceSessionOut:
    async with _service(request, container, principal) as service:
        return await service.create_session(body)


@router.post(
    "/voice/tool-calls",
    response_model=VoiceToolCallResult,
    summary="Run a tool the voice model called",
    description="Validates the arguments and runs the tool against ADAPT's API as the "
    "signed-in user. Always returns an output for the model, including when the tool fails.",
)
async def run_voice_tool_call(
    body: VoiceToolCallRequest, request: Request, principal: PrincipalDep, container: ContainerDep
) -> VoiceToolCallResult:
    async with _service(request, container, principal) as service:
        return await service.tool_call(body)


@router.post(
    "/voice/assistant",
    response_model=AssistantMessageOut,
    summary="Text assistant turn (voice fallback)",
    description="Answers a typed message with the same tools voice uses. The client sends "
    "recent history, so context carries over from voice; transcripts aren't stored.",
)
async def assistant_turn(
    body: AssistantMessageRequest,
    request: Request,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AssistantMessageOut:
    async with _service(request, container, principal) as service:
        return await service.text_turn(body)
