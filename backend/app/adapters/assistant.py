"""Text assistant model: the fallback when voice is unavailable.

The assistant service runs a tool loop: `step()` either answers or asks for tool calls.
The service executes the calls through the same tools voice uses, appends the outputs,
and calls `step()` again.

* `OpenAIAssistantModel` uses the Responses API with function tools (`store=False`;
  encrypted reasoning items are replayed within a turn, so nothing is kept at OpenAI).
* `DemoAssistantModel` is deterministic. It maps a request to one of ADAPT's tools with
  keyword rules and phrases the tool's real result. It never invents facts: without a
  matching tool it says what it can help with.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, Field

from app.contracts.voice import VoiceToolSpec
from app.core.errors import AdapterUnavailable, UpstreamError

InputItem = dict[str, Any]
ToolChoice = Literal["auto", "none"]


class AssistantToolCall(BaseModel):
    call_id: str
    name: str
    arguments: str = "{}"


class AssistantStep(BaseModel):
    text: str = ""
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)
    # Provider items to append to the input before the next step (reasoning, calls).
    items: list[InputItem] = Field(default_factory=list)


class AssistantModel(Protocol):
    provider: str
    mode: Literal["live", "demo"]

    async def step(
        self,
        *,
        instructions: str,
        input: list[InputItem],
        tools: list[VoiceToolSpec],
        tool_choice: ToolChoice = "auto",
    ) -> AssistantStep: ...


def function_call_output(call_id: str, output: dict[str, Any]) -> InputItem:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(output, ensure_ascii=False, default=str),
    }


class OpenAIAssistantModel:
    provider = "openai"
    mode: Literal["live", "demo"] = "live"

    def __init__(self, client: AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    async def step(
        self,
        *,
        instructions: str,
        input: list[InputItem],
        tools: list[VoiceToolSpec],
        tool_choice: ToolChoice = "auto",
    ) -> AssistantStep:
        function_tools: Any = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "strict": False,
            }
            for tool in tools
        ]
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=input,  # type: ignore[arg-type]
                tools=function_tools,
                tool_choice=tool_choice,
                reasoning={"effort": "low"},
                include=["reasoning.encrypted_content"],
                store=False,
                metadata={"purpose": "assistant.turn"},
            )
        except RateLimitError as exc:
            raise AdapterUnavailable(
                "ADAPT is busy right now. Try again in a moment.", code="assistant_busy"
            ) from exc
        except OpenAIError as exc:
            raise UpstreamError("The assistant could not respond", code="assistant_error") from exc

        items = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
        calls = [
            AssistantToolCall(call_id=item.call_id, name=item.name, arguments=item.arguments)
            for item in response.output
            if item.type == "function_call"
        ]
        return AssistantStep(text=response.output_text, tool_calls=calls, items=items)


# --- demo -----------------------------------------------------------------------------


_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_STOPWORDS = frozenset(
    re.split(
        r"\s+",
        "a an the i im i'm me my we our you your to of for in on at and or is are am be do "
        "does did can could should would will need want wants what which who how when where "
        "why please about with from this that it its there have has get tell show find us",
    )
)

# (tool, trigger words). First match wins, so specific intents come before general ones.
# Building a plan, what-ifs, research and approvals are recognised first (see `_plan`).
_INTENTS: tuple[tuple[str, frozenset[str]], ...] = (
    ("prepare_action", frozenset({"apply", "book", "appointment", "submit", "prepare"})),
    ("retrieve_evidence", frozenset({"evidence", "source", "sources", "official", "proof"})),
    ("upload_document_context", frozenset({"document", "documents", "passport", "upload"})),
    ("get_user_graph", frozenset({"twin", "graph", "connections"})),
    ("get_journey", frozenset({"plan", "journey", "steps", "next", "progress", "todo"})),
    ("get_profile", frozenset({"profile", "preferences", "consent", "household"})),
)
_GREETINGS = frozenset({"hi", "hello", "hey", "salam", "marhaba", "morning", "evening"})

# "Build my plan", "plan my move", "I'm moving to Abu Dhabi with my wife".
_START_VERBS = frozenset({"build", "create", "start", "new", "make", "begin", "redo", "replan"})
_PLAN_NOUNS = frozenset({"plan", "journey", "move"})
_MOVING = frozenset({"moving", "relocating", "relocate", "relocation"})
# "What if I set up in ADGM instead?"
_WHAT_IF = frozenset({"instead", "simulate", "simulation", "scenario", "suppose"})
_SPOUSE = frozenset({"wife", "husband", "spouse", "partner"})
# Research: start it, or ask how it's going.
_RESEARCH_STATUS = frozenset(
    {"ready", "status", "done", "finished", "findings", "progress", "results", "found"}
)
_RESEARCH_START = frozenset({"start", "run", "begin", "new", "again", "redo", "find", "search"})
_RESEARCH_CATEGORIES: tuple[tuple[str, frozenset[str]], ...] = (
    ("community", frozenset({"community", "communities", "people"})),
    ("events", frozenset({"event", "events", "meetup", "meetups"})),
    ("culture", frozenset({"culture", "cultural", "etiquette", "customs"})),
    ("professional_network", frozenset({"network", "networking", "professional", "founders"})),
)
_APPROVE = frozenset({"approve", "approved", "confirm", "yes"})
_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand)?", re.IGNORECASE)

_WHAT_IF_HELP = (
    "Tell me what to change, for example: “What if I set up in ADGM instead?”, "
    "“What if my wife joins later?” or “What if my income is 30,000 AED a month?”"
)
_APPROVE_HELP = (
    "Approvals are a tap, never something said: tap Approve on the card when you're ready. "
    "Nothing is sent or booked until you do."
)


def _is_what_if(words: set[str]) -> bool:
    return bool(words & _WHAT_IF) or {"what", "if"} <= words


def _scenario_changes(text: str) -> list[dict[str, Any]]:
    """The assumptions a plain-English what-if changes (only keys the simulation knows)."""
    words = set(_tokens(text))
    changes: list[dict[str, Any]] = []
    if "adgm" in words:
        changes.append({"key": "company.jurisdiction", "value": "adgm"})
    elif "mainland" in words:
        changes.append({"key": "company.jurisdiction", "value": "mainland"})
    if words & _SPOUSE:
        if words & {"later", "after", "afterwards", "separately"}:
            changes.append({"key": "household.spouse_relocation", "value": "later"})
        elif words & {"without", "stays", "stay", "behind"}:
            changes.append({"key": "household.move_with_spouse", "value": False})
        elif words & {"with", "together", "joins", "comes"}:
            changes.append({"key": "household.move_with_spouse", "value": True})
    elif words & {"alone", "single"}:
        changes.append({"key": "household.move_with_spouse", "value": False})
    income = words & {"income", "salary", "earn", "earning", "earnings"}
    if income and (match := _NUMBER.search(text)):
        amount = float(match.group(1).replace(",", ""))
        if match.group(2):
            amount *= 1000
        changes.append({"key": "finance.monthly_income_aed", "value": int(amount)})
    if words & {"accommodation", "housing"} and words & {"provided", "provides", "employer"}:
        changes.append({"key": "housing.accommodation_provided", "value": True})
    return changes


_HELP = (
    "I can look up government services and their official requirements, check your plan "
    "and profile, bring in your documents, and prepare actions for you to approve. "
    "For example: “What do I need for a family residence visa?” or “What's next in my plan?”"
)


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _search_terms(text: str) -> str:
    terms = [t for t in _tokens(text) if t not in _STOPWORDS and len(t) > 2]
    return " ".join(terms[:8]) or text[:100]


def _last_user_text(items: list[InputItem]) -> str:
    for item in reversed(items):
        if item.get("role") == "user":
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(str(part.get("text", "")) for part in content)
    return ""


def _turn_items(items: list[InputItem]) -> list[InputItem]:
    """Items after the last user message: this turn's calls and outputs."""
    for index in range(len(items) - 1, -1, -1):
        if items[index].get("role") == "user":
            return items[index + 1 :]
    return []


def _labels(value: Any, limit: int = 5) -> list[str]:
    """Human labels from a tool result of any shape (title / label / name fields)."""
    found: list[str] = []

    def visit(node: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for key in ("title", "label", "name", "kind_label", "source_title"):
                text = node.get(key)
                if isinstance(text, str) and text.strip():
                    found.append(text.strip())
                    return
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return list(dict.fromkeys(found))


_NEXT = ("ready", "in_progress", "needs_info", "awaiting_approval", "handoff")


def _next_steps(journey: dict[str, Any], limit: int = 3) -> list[str]:
    """The plan's steps the person can act on now, in plan order."""
    nodes = [n for n in journey.get("nodes") or [] if isinstance(n, dict)]
    ready = [n for n in nodes if n.get("status") in _NEXT and n.get("title")]
    ready.sort(key=lambda n: (_NEXT.index(str(n.get("status"))), n.get("position") or 0))
    return [str(n["title"]) for n in ready[:limit]]


def _first_key(value: Any, prefix: str) -> str | None:
    if isinstance(value, dict):
        key = value.get("key")
        if isinstance(key, str) and key.startswith(prefix):
            return key
        for child in value.values():
            if found := _first_key(child, prefix):
                return found
    elif isinstance(value, list):
        for child in value:
            if found := _first_key(child, prefix):
                return found
    return None


class DemoAssistantModel:
    provider = "adapt-demo"
    mode: Literal["live", "demo"] = "demo"

    async def step(
        self,
        *,
        instructions: str,
        input: list[InputItem],
        tools: list[VoiceToolSpec],
        tool_choice: ToolChoice = "auto",
    ) -> AssistantStep:
        available = {tool.name for tool in tools}
        turn = _turn_items(input)
        outputs = {
            item["call_id"]: json.loads(item["output"])
            for item in turn
            if item.get("type") == "function_call_output"
        }
        calls = [item for item in turn if item.get("type") == "function_call"]
        user_text = _last_user_text(input)

        if not calls:
            if tool_choice == "none":
                return AssistantStep(text=_HELP)
            return self._plan(user_text, available)

        results = [(call["name"], outputs.get(call["call_id"], {})) for call in calls]
        # An action request searches first, then prepares the best-matching service.
        name, first = results[0]
        if (
            tool_choice == "auto"
            and len(results) == 1
            and name == "search_governance"
            and "prepare_action" in available
            and self._intent(user_text) == "prepare_action"
            and (service := _first_key(first.get("data"), "service."))
        ):
            return self._call("prepare_action", {"service_key": service}, index=len(calls))
        return AssistantStep(text="\n\n".join(self._describe(n, r) for n, r in results))

    def _intent(self, text: str) -> str | None:
        words = set(_tokens(text))
        for tool, triggers in _INTENTS:
            if words & triggers:
                return tool
        return None

    def _plan(self, text: str, available: set[str]) -> AssistantStep:
        words = set(_tokens(text))
        if _is_what_if(words) and "simulate_journey" in available:
            changes = _scenario_changes(text)
            if not changes:
                return AssistantStep(text=_WHAT_IF_HELP)
            return self._call("simulate_journey", {"changes": changes})
        if "start_journey" in available and (
            (words & _START_VERBS and words & _PLAN_NOUNS)
            or words & _MOVING
            or {"plan", "move"} <= words
        ):
            return self._call("start_journey", {"request": text[:4000]})
        categories = [c for c, triggers in _RESEARCH_CATEGORIES if words & triggers]
        if "research" in words or categories:
            if words & _RESEARCH_STATUS or not (words & _RESEARCH_START or categories):
                return self._call("get_research_status", {})
            # No categories means every category the person has consented to.
            return self._call("start_research", {"categories": categories} if categories else {})
        if words & _APPROVE and not words & {"what", "how", "which"}:
            return AssistantStep(text=_APPROVE_HELP)
        intent = self._intent(text)
        if intent == "prepare_action" and "search_governance" in available:
            return self._call("search_governance", {"query": _search_terms(text)})
        if intent == "retrieve_evidence":
            return self._call(intent, {"query": _search_terms(text)})
        if intent and intent in available:
            return self._call(intent, {})
        if words and words <= _GREETINGS | _STOPWORDS:
            return AssistantStep(text=f"Hello! {_HELP}")
        terms = _search_terms(text)
        if "search_governance" in available and len(terms) >= 3:
            return self._call("search_governance", {"query": terms})
        return AssistantStep(text=_HELP)

    @staticmethod
    def _call(name: str, arguments: dict[str, Any], *, index: int = 0) -> AssistantStep:
        call = AssistantToolCall(
            call_id=f"demo_{name}_{index}", name=name, arguments=json.dumps(arguments)
        )
        item = {
            "type": "function_call",
            "call_id": call.call_id,
            "name": name,
            "arguments": call.arguments,
        }
        return AssistantStep(tool_calls=[call], items=[item])

    @staticmethod
    def _describe(name: str, result: dict[str, Any]) -> str:
        """Person-facing text from a tool result. `guidance` is written for a language
        model, so the demo never shows it; it phrases the status and the data instead."""
        status = result.get("status")
        summary = str(result.get("summary") or "").rstrip(".")
        if status == "needs_approval":
            return (
                f"{summary}. Nothing has happened yet: review it below and tap Approve or Decline."
            )
        if status == "needs_consent":
            return "That needs your permission first. Choose Allow or Not now below."
        if status == "not_found":
            return f"{summary or 'I could not find that'}. {_HELP}"
        if status == "unavailable":
            return f"{summary or 'That is not available right now'}. You can ask me something else."
        if status != "ok":
            return "I couldn't complete that just now. Please try again in a moment."
        data = result.get("data")
        if name == "get_journey" and isinstance(data, dict) and (steps := _next_steps(data)):
            lead = f"{summary}." if summary else "Here's your plan."
            return f"{lead} What you can do next:\n" + "\n".join(f"• {step}" for step in steps)
        labels = _labels(data)
        lead = f"{summary}." if summary else "Here's what I found."
        if not labels:
            return lead
        listed = "\n".join(f"• {label}" for label in labels)
        return f"{lead}\n{listed}"
