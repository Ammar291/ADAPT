"""Web research (OpenAI Responses API `web_search` tool), run only from background workers.

Results keep their source URLs, titles, the passage each citation supports and the
retrieval timestamp. Classifying what a source *is* (official, organisation, community)
happens later, in `app.research.sources`, never on the model's word.

Two depths:
* `quick`: one short search, for focused lookups.
* `agentic`: the reasoning model plans and runs several searches, opens pages and checks
  them before answering (bounded by `max_tool_calls`). Used for open-ended research such
  as "find recognised community organisations".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from app.core.errors import UpstreamError
from app.research.sources import canonicalize_url

SearchDepth = Literal["quick", "agentic"]


class WebCitation(BaseModel):
    url: str
    title: str
    snippet: str | None = None  # the answer passage this citation supports


class WebResearchResult(BaseModel):
    query: str
    answer: str
    citations: list[WebCitation]
    retrieved_at: datetime
    provider: str
    available: bool = True
    searches: list[str] = []  # queries the model actually ran
    sources_consulted: list[str] = []  # every URL the search tool returned


class WebResearcher(Protocol):
    provider: str
    mode: Literal["live", "demo"]

    async def research(
        self,
        *,
        query: str,
        instructions: str,
        allowed_domains: list[str] | None = None,
        depth: SearchDepth = "quick",
    ) -> WebResearchResult: ...


ABU_DHABI_LOCATION: dict[str, str] = {
    "type": "approximate",
    "country": "AE",
    "city": "Abu Dhabi",
    "region": "Abu Dhabi",
    "timezone": "Asia/Dubai",
}


def _snippet(text: str, start: int, end: int, limit: int = 400) -> str | None:
    """The sentence(s) a citation annotation covers, trimmed for storage."""
    if not text or start >= end:
        return None
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    passage = text[left:end].strip(" -*\n")
    return passage[-limit:] or None


class OpenAIWebResearcher:
    provider = "openai"
    mode: Literal["live", "demo"] = "live"

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        quick_effort: str | None = "low",
        agentic_effort: str | None = "medium",
        quick_max_tool_calls: int = 3,
        agentic_max_tool_calls: int = 10,
    ) -> None:
        self._client = client
        self._model = model
        self._effort: dict[SearchDepth, str | None] = {
            "quick": quick_effort,
            "agentic": agentic_effort,
        }
        self._max_tool_calls: dict[SearchDepth, int] = {
            "quick": quick_max_tool_calls,
            "agentic": agentic_max_tool_calls,
        }

    async def research(
        self,
        *,
        query: str,
        instructions: str,
        allowed_domains: list[str] | None = None,
        depth: SearchDepth = "quick",
    ) -> WebResearchResult:
        tool: dict[str, Any] = {
            "type": "web_search",
            "user_location": ABU_DHABI_LOCATION,
            "search_context_size": "high" if depth == "agentic" else "medium",
        }
        if allowed_domains:
            tool["filters"] = {"allowed_domains": allowed_domains}
        options: dict[str, Any] = {
            "max_tool_calls": self._max_tool_calls[depth],
            "include": ["web_search_call.action.sources"],
        }
        if effort := self._effort[depth]:
            options["reasoning"] = {"effort": effort}
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=query,
                tools=[tool],  # type: ignore[list-item]
                store=False,
                **options,
            )
        except OpenAIError as exc:
            raise UpstreamError("Web research failed") from exc
        if getattr(response, "status", "completed") != "completed":
            raise UpstreamError("Web research did not finish", code="research_incomplete")

        citations: dict[str, WebCitation] = {}
        searches: list[str] = []
        consulted: list[str] = []
        for item in response.output:
            if item.type == "web_search_call":
                action = getattr(item, "action", None)
                for q in [
                    getattr(action, "query", None),
                    *(getattr(action, "queries", None) or []),
                ]:
                    if q and q not in searches:
                        searches.append(q)
                for source in getattr(action, "sources", None) or []:
                    url = getattr(source, "url", None)
                    if url and url not in consulted:
                        consulted.append(url)
                continue
            if item.type != "message":
                continue
            for content in item.content:
                text = getattr(content, "text", "") or ""
                for annotation in getattr(content, "annotations", None) or []:
                    if getattr(annotation, "type", None) != "url_citation":
                        continue
                    if not canonicalize_url(annotation.url):
                        continue
                    if not 0 <= annotation.start_index < annotation.end_index <= len(text):
                        continue
                    snippet = _snippet(text, annotation.start_index, annotation.end_index)
                    existing = citations.get(annotation.url)
                    if existing is None:
                        citations[annotation.url] = WebCitation(
                            url=annotation.url, title=annotation.title, snippet=snippet
                        )
                    elif snippet and not existing.snippet:
                        citations[annotation.url] = existing.model_copy(update={"snippet": snippet})
        if not citations:
            raise UpstreamError(
                "Web research returned no verifiable citations", code="research_uncited"
            )
        return WebResearchResult(
            query=query,
            answer=response.output_text,
            citations=list(citations.values()),
            retrieved_at=datetime.now(UTC),
            provider=f"openai:{self._model}",
            searches=searches,
            sources_consulted=consulted,
        )


class OfflineWebResearcher:
    """Demo mode: no live web access. Reports unavailability instead of inventing sources.
    (Offline *research* uses the curated snapshot in `app.research.snapshot` instead.)"""

    provider = "adapt-demo"
    mode: Literal["live", "demo"] = "demo"

    async def research(
        self,
        *,
        query: str,
        instructions: str,
        allowed_domains: list[str] | None = None,
        depth: SearchDepth = "quick",
    ) -> WebResearchResult:
        return WebResearchResult(
            query=query,
            answer="",
            citations=[],
            retrieved_at=datetime.now(UTC),
            provider=self.provider,
            available=False,
        )
