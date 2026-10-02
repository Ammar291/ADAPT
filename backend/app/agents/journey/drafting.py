"""Drafting documents for the user's review (checklists, cover letters, emails, briefs).

Rules for every draft:
* only the facts and requirements passed in `context` are used, and nothing is added. A
  missing detail becomes a visible [placeholder];
* no requirement, fee or processing time appears unless it was passed in (they come
  from the governance graph);
* provenance is always an ADAPT suggestion that cites the official pages it drew on,
  and the user reviews the draft before using it.

Checklists are rendered deterministically. Letters and emails use the language model
(live) or deterministic templates registered as demo responders (demo).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.adapters.llm import LLMClient
from app.domain.provenance import Citation, Provenance, is_official_source

if TYPE_CHECKING:
    from app.agents.journey.tools import GenerateDocumentInput

DRAFT_NOTE = (
    "Drafted by ADAPT from your details and the official requirements listed. Review before use."
)
DRAFT_INSTRUCTIONS = (
    "You draft documents for a person relocating to Abu Dhabi. Use ONLY the facts and "
    "requirements in the JSON input. Never add requirements, fees, deadlines or processing "
    "times that are not in the input. Write [placeholders] for any detail that is missing. "
    "Plain, polite English; markdown; no preamble."
)


def purpose_for(kind: str) -> str:
    return f"journey.document.{kind}"


def _provenance(context: dict[str, Any]) -> dict[str, Any]:
    citations = []
    for source in context.get("sources", [])[:5]:
        url = source.get("url")
        if url and is_official_source(url):
            citations.append(Citation(source_url=url, source_title=source.get("title") or url))
    return Provenance.ai(DRAFT_NOTE, citations=citations).model_dump(mode="json")


def checklist(context: dict[str, Any]) -> str:
    lines = [f"# {context.get('title', 'Checklist')}", ""]
    if context.get("authority"):
        lines += [f"Handled by: {context['authority']}", ""]
    ready = [r for r in context.get("requirements", []) if r.get("status") in ("satisfied",)]
    todo = [r for r in context.get("requirements", []) if r.get("status") not in ("satisfied",)]
    if todo:
        lines.append("## Still to get")
        for req in todo:
            via = f" (from: {req['provided_by']})" if req.get("provided_by") else ""
            lines.append(f"- [ ] {req['label']}{via}")
        lines.append("")
    if ready:
        lines.append("## Already have")
        lines += [f"- [x] {req['label']}" for req in ready]
        lines.append("")
    if context.get("official_url"):
        lines.append(f"Confirm the current list on the official page: {context['official_url']}")
    return "\n".join(lines).strip() + "\n"


async def draft(llm: LLMClient, args: GenerateDocumentInput) -> tuple[str, dict[str, Any]]:
    context = {"title": args.title, **args.context}
    if args.kind == "checklist":
        body = checklist(context)
    else:
        body = await llm.text(
            purpose=purpose_for(args.kind),
            instructions=DRAFT_INSTRUCTIONS,
            input=json.dumps({"kind": args.kind, **context}, default=str, ensure_ascii=False),
            tier="fast",
        )
    return body, _provenance(context)
