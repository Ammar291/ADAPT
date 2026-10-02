"""Assistant use cases: mint a voice session, run a tool call, answer a text turn."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta, timezone

from app.adapters.assistant import AssistantModel, InputItem, function_call_output
from app.adapters.voice import VoiceSessionProvider
from app.contracts.voice import (
    AssistantMessageOut,
    AssistantMessageRequest,
    VoiceSessionOut,
    VoiceSessionRequest,
    VoiceToolCallRequest,
    VoiceToolCallResult,
)
from app.core.errors import BadRequest
from app.domain.principal import Principal
from app.voice.gateway import ApiGateway
from app.voice.guard import AssistantGuard, TooManyRequests
from app.voice.outcomes import ToolOutcome, rate_limited
from app.voice.prompt import Channel, build_instructions
from app.voice.tools import Routes, ToolContext, execute_tool, tool_result, tool_specs

logger = logging.getLogger(__name__)

GULF_STANDARD_TIME = timezone(timedelta(hours=4))  # Abu Dhabi; no daylight saving
MAX_TOOL_ROUNDS = 4
MAX_CALLS_PER_ROUND = 4
MAX_HISTORY_MESSAGES = 24
LOOP_LIMIT_REPLY = (
    "I've gathered what I could, and the details are on screen. "
    "What would you like to look at next?"
)


def abu_dhabi_today() -> date:
    return datetime.now(UTC).astimezone(GULF_STANDARD_TIME).date()


class AssistantService:
    def __init__(
        self,
        *,
        principal: Principal,
        gateway: ApiGateway,
        guard: AssistantGuard,
        voice: VoiceSessionProvider,
        model: AssistantModel,
    ) -> None:
        self._principal = principal
        self._gateway = gateway
        self._guard = guard
        self._voice = voice
        self._model = model

    @property
    def _user_id(self) -> str:
        return f"{self._principal.tenant_id}:{self._principal.user_id}"

    async def _instructions(
        self,
        channel: Channel,
        *,
        language: str | None,
        journey_id: str | None,
        resumed: bool = False,
    ) -> str:
        display_name: str | None = None
        preferred = language
        if self._gateway.serves("GET", Routes.ME[0]):
            me = await self._gateway.get(Routes.ME[0])
            if me.ok and isinstance(me.body, dict):
                display_name = me.body.get("display_name")
                prefs = me.body.get("preferences") or {}
                preferred = language or prefs.get("preferred_language")
        return build_instructions(
            channel=channel,
            today=abu_dhabi_today(),
            preferred_language=preferred,
            display_name=display_name,
            journey_id=journey_id,
            resumed=resumed,
        )

    async def create_session(self, body: VoiceSessionRequest) -> VoiceSessionOut:
        await self._guard.check_mint(self._user_id)
        instructions = await self._instructions(
            "voice", language=body.language, journey_id=body.journey_id, resumed=body.resumed
        )
        session = await self._voice.create_session(
            instructions=instructions, tools=tool_specs(), audio_profile=body.audio_profile
        )
        if session.mode != "live":
            return session
        session_id = self._guard.new_session_id(self._user_id)
        logger.info(
            "voice_session_minted",
            extra={"voice_session": session_id, "model": session.model, "resumed": body.resumed},
        )
        return session.model_copy(update={"session_id": session_id})

    async def tool_call(self, body: VoiceToolCallRequest) -> VoiceToolCallResult:
        await self._guard.check_tool_call(body.session_id, self._user_id)
        await self._guard.claim_tool_call(body.session_id, body.call_id)
        result = await execute_tool(
            ToolContext(self._gateway),
            call_id=body.call_id,
            name=body.name,
            arguments=body.arguments,
        )
        logger.info(
            "voice_tool_call",
            extra={"voice_session": body.session_id, "tool": body.name, "status": result.status},
        )
        return result

    async def _run_text_tool(
        self, context: ToolContext, index: int, call_id: str, name: str, arguments: str
    ) -> VoiceToolCallResult:
        if index >= MAX_CALLS_PER_ROUND:
            outcome = ToolOutcome(
                "invalid_arguments",
                summary="Too many requests at once",
                guidance=f"At most {MAX_CALLS_PER_ROUND} tools per step. Call this one again "
                "later if it's still needed.",
            )
            return tool_result(call_id, name, "Working on it", outcome)
        try:
            await self._guard.check_tool_rate(self._user_id)
        except TooManyRequests:
            return tool_result(call_id, name, "Working on it", rate_limited())
        return await execute_tool(context, call_id=call_id, name=name, arguments=arguments)

    async def text_turn(self, body: AssistantMessageRequest) -> AssistantMessageOut:
        await self._guard.check_text_turn(self._user_id)
        history = body.messages[-MAX_HISTORY_MESSAGES:]
        if history[-1].role != "user":
            raise BadRequest("The last message must be from the person", code="no_user_message")

        instructions = await self._instructions(
            "text", language=body.language, journey_id=body.journey_id
        )
        specs = tool_specs()
        context = ToolContext(self._gateway, journey_id=body.journey_id)
        items: list[InputItem] = [{"role": m.role, "content": m.text} for m in history]
        results: list[VoiceToolCallResult] = []

        for round_number in range(MAX_TOOL_ROUNDS + 1):
            # The last round must answer in words: no more tools, so nothing is started
            # and then thrown away.
            final = round_number == MAX_TOOL_ROUNDS
            step = await self._model.step(
                instructions=instructions,
                input=items,
                tools=specs,
                tool_choice="none" if final else "auto",
            )
            items.extend(step.items)
            if not step.tool_calls or final:
                reply = step.text.strip() or LOOP_LIMIT_REPLY
                return AssistantMessageOut(mode=self._model.mode, reply=reply, tool_results=results)
            round_results = await asyncio.gather(
                *(
                    self._run_text_tool(context, index, call.call_id, call.name, call.arguments)
                    for index, call in enumerate(step.tool_calls)
                )
            )
            for call, result in zip(step.tool_calls, round_results, strict=True):
                items.append(function_call_output(call.call_id, result.output))
            results.extend(round_results)

        logger.warning("assistant_tool_loop_limit", extra={"tool_calls": len(results)})
        return AssistantMessageOut(
            mode=self._model.mode, reply=LOOP_LIMIT_REPLY, tool_results=results
        )
