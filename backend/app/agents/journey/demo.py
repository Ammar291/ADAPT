"""Deterministic demo responders for the journey agent's language-model purposes.

`DemoLLM` refuses any purpose without a responder, so these are registered explicitly.
They are deterministic and use only their input: intake is a keyword parser, and drafts
are templates with visible [placeholders] for missing details.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.adapters.llm import DemoLLM, LLMClient, LLMInput
from app.agents.journey.drafting import purpose_for
from app.agents.journey.intake import INTAKE_PURPOSE, parse_request


def _text(value: LLMInput) -> str:
    if isinstance(value, str):
        return value
    parts = []
    for item in value:
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts += [c.get("text", "") for c in content if isinstance(c, dict)]
    return " ".join(parts)


def _context(value: LLMInput) -> dict[str, Any]:
    try:
        data = json.loads(_text(value))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _p(context: dict[str, Any], key: str, placeholder: str) -> str:
    value = context.get(key)
    return str(value) if value not in (None, "", []) else f"[{placeholder}]"


def _bullets(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- [documents to attach]"


def cover_letter(context: dict[str, Any]) -> str:
    return (
        f"# {_p(context, 'title', 'Title')}\n\n"
        f"To: {_p(context, 'authority', 'the responsible authority')}\n\n"
        f"Subject: {_p(context, 'service', 'Application')}\n\n"
        f"Dear Sir or Madam,\n\n"
        f"I, {_p(context, 'applicant_name', 'your full name')}, am applying for "
        f"{_p(context, 'service', 'this service')} for my spouse, "
        f"{_p(context, 'spouse_name', 'spouse full name')}.\n\n"
        f"Please find enclosed:\n{_bullets(context.get('documents', []))}\n\n"
        f"Yours faithfully,\n{_p(context, 'applicant_name', 'your full name')}\n"
    )


def email(context: dict[str, Any]) -> str:
    return (
        f"Subject: {_p(context, 'title', 'Question about my application')}\n\n"
        f"Dear {_p(context, 'authority', 'team')},\n\n"
        f"I am preparing to apply for {_p(context, 'service', 'this service')}. "
        "Could you confirm the current requirements for:\n"
        f"{_bullets(context.get('documents', []))}\n\n"
        f"Kind regards,\n{_p(context, 'applicant_name', 'your name')}\n"
    )


def appointment_brief(context: dict[str, Any]) -> str:
    return (
        f"# {_p(context, 'title', 'Appointment')}\n\n"
        f"Where to book: {_p(context, 'official_url', 'the official booking page')}\n\n"
        f"Bring:\n{_bullets(context.get('documents', []))}\n"
    )


def business_summary(context: dict[str, Any]) -> str:
    return (
        f"# {_p(context, 'title', 'Business summary')}\n\n"
        f"Founder: {_p(context, 'applicant_name', 'your name')}\n\n"
        f"Licensing: {_p(context, 'jurisdiction', 'mainland or ADGM')}\n\n"
        f"Activity: [describe your business activity]\n"
    )


_TEMPLATES = {
    "cover_letter": cover_letter,
    "email": email,
    "appointment_brief": appointment_brief,
    "business_summary": business_summary,
}


def register_demo_responders(llm: LLMClient) -> None:
    """Idempotent. A no-op for live models."""
    if not isinstance(llm, DemoLLM):
        return

    def intake(value: LLMInput, schema: type[BaseModel] | None) -> BaseModel:
        return parse_request(_text(value))

    llm.register(INTAKE_PURPOSE, intake)
    for kind, template in _TEMPLATES.items():
        llm.register(
            purpose_for(kind),
            lambda value, schema, template=template: template(_context(value)),  # type: ignore[misc]
        )
