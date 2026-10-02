from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from openai import AsyncOpenAI

from app.api.deps import ContainerDep, PrincipalDep
from app.core.errors import AdapterUnavailable, BadRequest, PayloadTooLarge
from app.interpreter.contracts import (
    Capabilities,
    FallbackOut,
    SessionOut,
    SessionReference,
    SessionRequest,
    Speaker,
    TextRequest,
)
from app.interpreter.provider import OpenAITranslationProvider
from app.interpreter.service import InterpreterSessionService

router = APIRouter(prefix="/interpreter", tags=["interpreter"])


@router.get("/capabilities", response_model=Capabilities)
async def capabilities(container: ContainerDep) -> Capabilities:
    return OpenAITranslationProvider(container.settings).capabilities()


@asynccontextmanager
async def service(
    container: ContainerDep, principal: PrincipalDep
) -> AsyncIterator[InterpreterSessionService]:
    settings = container.settings
    if OpenAITranslationProvider(settings).capabilities().mode == "live":
        async with AsyncOpenAI(
            api_key=settings.openai.api_key,
            base_url=settings.openai.base_url,
            organization=settings.openai.organization,
            timeout=30,
            max_retries=0,
            default_headers={
                "OpenAI-Safety-Identifier": hashlib.sha256(
                    f"{principal.tenant_id}:{principal.user_id}".encode()
                ).hexdigest()
            },
        ) as client:
            yield InterpreterSessionService(
                OpenAITranslationProvider(settings, client), container.redis, settings, principal
            )
    else:
        yield InterpreterSessionService(
            OpenAITranslationProvider(settings), container.redis, settings, principal
        )


@router.post("/session", response_model=SessionOut)
async def create_session(
    body: SessionRequest, container: ContainerDep, principal: PrincipalDep
) -> SessionOut:
    async with service(container, principal) as sessions:
        return await sessions.create(body)


@router.post("/reconnect", response_model=SessionOut)
async def reconnect(
    body: SessionReference, container: ContainerDep, principal: PrincipalDep
) -> SessionOut:
    async with service(container, principal) as sessions:
        claims = await sessions.verify(body.session_id)
        return await sessions.create(
            SessionRequest(
                source=claims["source"],
                target=claims["target"],
                recorded=claims.get("recorded", False),
            ),
            body.session_id,
        )


@router.post("/end", status_code=204)
async def end_session(
    body: SessionReference, container: ContainerDep, principal: PrincipalDep
) -> None:
    async with service(container, principal) as sessions:
        await sessions.end(body.session_id)


@router.post("/recording", response_model=FallbackOut)
async def translate_recording(
    container: ContainerDep,
    principal: PrincipalDep,
    session_id: Annotated[str, Form(max_length=2048)],
    speaker: Annotated[Speaker, Form()],
    audio: Annotated[UploadFile, File()],
) -> FallbackOut:
    try:
        async with service(container, principal) as sessions:
            claims = await sessions.verify(session_id)
            if claims["mode"] != "live" or not container.settings.interpreter_fallback_enabled:
                raise AdapterUnavailable("Recorded translation is unavailable in this mode")
            await sessions.limit("recording", 20)
            mime = (audio.content_type or "").split(";")[0]
            if mime not in {"audio/webm", "audio/mp4", "audio/ogg"}:
                raise BadRequest("Use a WebM, MP4 or Ogg microphone recording")
            data = await audio.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise PayloadTooLarge("Record a shorter phrase (maximum 4 MB)")
            if not data:
                raise BadRequest("No microphone audio was recorded")
            source, target = claims["source"], claims["target"]
            if speaker == "b":
                source, target = target, source
            return await sessions.provider.translate_recording(speaker, source, target, data, mime)
    finally:
        await audio.close()


@router.post("/text", response_model=FallbackOut)
async def translate_text(
    body: TextRequest, container: ContainerDep, principal: PrincipalDep
) -> FallbackOut:
    async with service(container, principal) as sessions:
        sessions.validate_pair(body)
        if sessions.provider.capabilities().mode != "live":
            raise AdapterUnavailable("Text translation needs server credentials")
        if not body.text.strip():
            raise BadRequest("Enter a phrase to translate")
        await sessions.limit("text", 20)
        return await sessions.provider.translate_text(
            body.speaker, body.source, body.target, body.text.strip()
        )
