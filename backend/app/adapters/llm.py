"""Language-model adapter.

Callers name a `purpose` (e.g. "journey.understand_request") and a Pydantic output
schema. In demo mode, deterministic responders registered per purpose produce the
output; a purpose without a responder raises `AdapterUnavailable` instead of inventing
content.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from app.core.errors import AdapterUnavailable, UpstreamError

ModelTier = Literal["reasoning", "fast"]
LLMInput = str | list[dict[str, Any]]


class LLMClient(Protocol):
    provider: str
    mode: Literal["live", "demo"]

    async def structured[T: BaseModel](
        self,
        *,
        purpose: str,
        instructions: str,
        input: LLMInput,
        schema: type[T],
        tier: ModelTier = "reasoning",
    ) -> T: ...

    async def text(
        self, *, purpose: str, instructions: str, input: LLMInput, tier: ModelTier = "fast"
    ) -> str: ...


class OpenAILLM:
    provider = "openai"
    mode: Literal["live", "demo"] = "live"

    def __init__(self, client: AsyncOpenAI, *, reasoning_model: str, fast_model: str) -> None:
        self._client = client
        self._models: dict[ModelTier, str] = {"reasoning": reasoning_model, "fast": fast_model}

    async def structured[T: BaseModel](
        self,
        *,
        purpose: str,
        instructions: str,
        input: LLMInput,
        schema: type[T],
        tier: ModelTier = "reasoning",
    ) -> T:
        try:
            response = await self._client.responses.parse(
                model=self._models[tier],
                instructions=instructions,
                input=input,  # type: ignore[arg-type]
                text_format=schema,
                metadata={"purpose": purpose},
                store=False,
            )
        except OpenAIError as exc:
            raise UpstreamError(f"Language model call failed ({purpose})") from exc
        if response.output_parsed is None:
            raise UpstreamError(f"Language model returned no structured output ({purpose})")
        return response.output_parsed

    async def text(
        self, *, purpose: str, instructions: str, input: LLMInput, tier: ModelTier = "fast"
    ) -> str:
        try:
            response = await self._client.responses.create(
                model=self._models[tier],
                instructions=instructions,
                input=input,  # type: ignore[arg-type]
                metadata={"purpose": purpose},
                store=False,
            )
        except OpenAIError as exc:
            raise UpstreamError(f"Language model call failed ({purpose})") from exc
        return response.output_text


DemoResponder = Callable[[LLMInput, type[BaseModel] | None], BaseModel | str]


class DemoLLM:
    """Deterministic stand-in. Feature workstreams register responders per purpose."""

    provider = "adapt-demo"
    mode: Literal["live", "demo"] = "demo"

    def __init__(self) -> None:
        self._responders: dict[str, DemoResponder] = {}

    def register(self, purpose: str, responder: DemoResponder) -> None:
        self._responders[purpose] = responder

    def _responder(self, purpose: str) -> DemoResponder:
        try:
            return self._responders[purpose]
        except KeyError:
            raise AdapterUnavailable(
                f"No demo response is available for '{purpose}'. Set OPENAI_API_KEY to use "
                "the live model.",
                code="demo_capability_missing",
            ) from None

    async def structured[T: BaseModel](
        self,
        *,
        purpose: str,
        instructions: str,
        input: LLMInput,
        schema: type[T],
        tier: ModelTier = "reasoning",
    ) -> T:
        result = self._responder(purpose)(input, schema)
        return schema.model_validate(
            result.model_dump() if isinstance(result, BaseModel) else result
        )

    async def text(
        self, *, purpose: str, instructions: str, input: LLMInput, tier: ModelTier = "fast"
    ) -> str:
        result = self._responder(purpose)(input, None)
        return result if isinstance(result, str) else result.model_dump_json()
