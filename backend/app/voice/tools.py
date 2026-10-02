"""Application tools the assistant may call (voice and text).

Each tool validates its arguments, calls ADAPT's public API through `ApiGateway` as the
signed-in user, and returns a `ToolOutcome`: a status, compact data for the model,
guidance on how to convey it, and optional UI payloads (approval card, consent card, link).

Route candidates list the current path first and older foundation paths after, so tools
keep working while feature workstreams move routes. A tool whose route isn't in this build
reports "unavailable", and the assistant says so honestly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.contracts.voice import (
    ApprovalRequest,
    ToolActivity,
    ToolCitation,
    VoiceToolCallResult,
    VoiceToolSpec,
)
from app.voice.gateway import ApiGateway
from app.voice.outcomes import ToolOutcome, failure, unavailable
from app.voice.shaping import shape

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 25.0


class Routes:
    ME = ("/me",)
    PROFILE = ("/profile", "/me")
    JOURNEYS = ("/journey", "/journeys")
    JOURNEY = ("/journey/{journey_id}", "/journeys/{journey_id}")
    JOURNEY_SIMULATE = ("/journey/{journey_id}/simulate", "/journeys/{journey_id}/what-if")
    JOURNEY_VARIABLES = ("/journey/{journey_id}/what-if/variables",)
    GOVERNANCE_SEARCH = ("/graph/governance", "/governance/graph")
    EVIDENCE_SEARCH = ("/knowledge/search",)
    # The compact "what ADAPT takes into account" view first; the raw graph as fallback.
    USER_GRAPH = ("/graph/user/personalisation", "/graph/user", "/twin/graph")
    DOCUMENTS = ("/documents",)
    DOCUMENT = ("/documents/{document_id}",)
    DOCUMENT_UPLOAD = ("/documents/upload",)
    ACTION_PREPARE = ("/actions/prepare",)
    RESEARCH = ("/research",)
    RESEARCH_JOB = ("/research/{job_id}",)


# --- arguments ---------------------------------------------------------------------------


# Ids go into URL paths: letters, digits, "-" and "_" only, so an argument can never add
# path segments (e.g. "x/../approve").
IdArg = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class ToolArgs(BaseModel):
    # Models occasionally add stray keys; ignore them rather than fail the whole call.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class NoArgs(ToolArgs):
    pass


class GetJourneyArgs(ToolArgs):
    journey_id: IdArg | None = Field(
        default=None, max_length=64, description="Omit for the person's current plan"
    )


class SearchGovernanceArgs(ToolArgs):
    query: str = Field(
        min_length=2,
        max_length=100,
        description="Short English keywords, e.g. 'family residence visa' or 'trade licence'",
    )
    limit: int = Field(default=6, ge=1, le=10)


class RetrieveEvidenceArgs(ToolArgs):
    query: str = Field(
        min_length=2, max_length=300, description="What the evidence should cover, in English"
    )
    service_key: str | None = Field(
        default=None,
        max_length=200,
        description="Governance key to scope the search, e.g. 'service.family_residence_visa'",
    )
    limit: int = Field(default=4, ge=1, le=8)


class StartJourneyArgs(ToolArgs):
    request: str = Field(
        min_length=3,
        max_length=4000,
        description="What the person wants to achieve, in their own words: who is moving, "
        "goals (company, visas, housing, school), and timing",
    )
    language: str = Field(
        default="en", max_length=35, description="BCP-47 code of the conversation language"
    )


class UploadDocumentContextArgs(ToolArgs):
    document_id: IdArg | None = Field(
        default=None, max_length=64, description="A document to bring into the conversation"
    )
    kind: str | None = Field(
        default=None,
        max_length=40,
        description="Document you need the person to upload, e.g. passport, "
        "marriage_certificate, emirates_id, degree_certificate, tenancy_contract",
    )
    reason: str | None = Field(
        default=None, max_length=200, description="Why it's needed, shown to the person"
    )


ActionKindArg = Literal[
    "official_handoff", "government_portal", "appointment", "document_submission"
]


class PrepareActionArgs(ToolArgs):
    task_key: str | None = Field(
        default=None, max_length=200, description="Key of the plan step, from get_journey"
    )
    service_key: str | None = Field(
        default=None,
        max_length=200,
        description="Governance service key, e.g. 'service.emirates_id_application'",
    )
    journey_node_id: IdArg | None = Field(default=None, max_length=64)
    journey_id: IdArg | None = Field(
        default=None, max_length=64, description="Omit for the person's current plan"
    )
    kind: ActionKindArg | None = Field(
        default=None,
        description="Omit to use the step's own action type. Only to override it: "
        "official_handoff opens the official service for the person to complete; "
        "appointment books a slot; document_submission sends documents",
    )


ResearchCategoryArg = Literal[
    "community",
    "faith_and_worship",
    "professional_network",
    "events",
    "culture",
    "lifestyle",
    "starter_kit",
]


class StartResearchArgs(ToolArgs):
    categories: list[ResearchCategoryArg] | None = Field(
        default=None,
        max_length=7,
        description="Omit for all categories. faith_and_worship needs the person's opt-in.",
    )
    focus: str | None = Field(
        default=None, max_length=200, description="Optional focus, e.g. 'running clubs'"
    )


class ScenarioChange(ToolArgs):
    key: str = Field(
        max_length=120,
        description="Assumption to change, e.g. 'company.jurisdiction' or 'move.date'",
    )
    value: str | int | float | bool = Field(description="The new value")


class SimulateJourneyArgs(ToolArgs):
    changes: list[ScenarioChange] = Field(
        min_length=1,
        max_length=10,
        description="e.g. company.jurisdiction = 'adgm', household.move_with_spouse = true, "
        "household.planned_arrival_date = '2026-12-01', finance.monthly_income_aed = 30000",
    )
    journey_id: IdArg | None = Field(default=None, max_length=64, description="Omit for current")


class ResearchStatusArgs(ToolArgs):
    job_id: IdArg | None = Field(default=None, max_length=64, description="Omit for the latest")


# --- helpers --------------------------------------------------------------------------------


def _first(body: Any, *keys: str) -> Any:
    if isinstance(body, dict):
        for key in keys:
            if body.get(key) not in (None, "", [], {}):
                return body[key]
    return None


def _items(body: Any, *keys: str) -> list[Any]:
    """A list payload, whether returned bare or wrapped (e.g. {"items": [...]})."""
    if isinstance(body, list):
        return body
    found = _first(body, *keys)
    return found if isinstance(found, list) else []


def _id_of(value: Any) -> str | None:
    found = _first(value, "id", "job_id", "run_id")
    return str(found) if found is not None else None


_TRUST_TIERS = frozenset(
    {"authoritative_requirement", "official_guidance", "community_web", "ai_recommendation"}
)


def _citation(
    *, title: Any, url: Any, kind: Any, authority: Any = None, retrieved_at: Any = None
) -> ToolCitation | None:
    """A citation for the UI's sources list, only for http(s) links with a known tier."""
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return None
    if kind not in _TRUST_TIERS:
        return None
    try:
        return ToolCitation(
            title=str(title or url)[:300],
            url=url,
            authority=str(authority)[:200] if authority else None,
            retrieved_at=retrieved_at or None,
            kind=kind,
        )
    except ValueError:
        return None


def _citations(candidates: list[ToolCitation | None], limit: int = 8) -> list[ToolCitation]:
    unique: dict[str, ToolCitation] = {}
    for citation in candidates:
        if citation is not None:
            unique.setdefault(citation.url, citation)
    return list(unique.values())[:limit]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


async def _latest_journey_id(gw: ApiGateway) -> str | ToolOutcome | None:
    route = gw.first_served("GET", Routes.JOURNEYS)
    if route is None:
        return unavailable("Your plan")
    response = await gw.get(route)
    if not response.ok:
        return failure(response, what="Your plan")
    # Newest first, and what-if scenarios are journeys too: the plan is the newest one that
    # isn't a scenario (or archived).
    plans = [
        j
        for j in _items(response.body, "items", "journeys")
        if isinstance(j, dict)
        and j.get("status") not in ("scenario", "archived")
        and not j.get("parent_journey_id")
    ]
    return _id_of(plans[0]) if plans else None


# --- tools ------------------------------------------------------------------------------------


@dataclass
class ToolContext:
    gateway: ApiGateway
    journey_id: str | None = None


async def get_profile(ctx: ToolContext, _: NoArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("GET", Routes.PROFILE)
    if route is None:
        return unavailable("Your profile")
    profile = await gw.get(route)
    if not profile.ok:
        return failure(profile, what="Your profile")
    data: dict[str, Any] = {"profile": shape(profile.body)}
    guidance = "Use this to personalise advice. Facts marked unconfirmed may need checking."
    me = await gw.get(Routes.ME[0]) if gw.serves("GET", Routes.ME[0]) else None
    prefs = _first(me.body if me and me.ok else None, "preferences") or {}
    consents = {
        name: prefs.get(name, "not_asked")
        for name in ("faith_personalization", "community_personalization")
    }
    data["personalisation_consent"] = consents
    if "not_asked" in consents.values():
        guidance += (
            " Faith or community personalisation hasn't been discussed: don't assume anything "
            "about either; ask only if it becomes relevant."
        )
    return ToolOutcome("ok", data=data, summary="Read your profile", guidance=guidance)


async def get_journey(ctx: ToolContext, args: GetJourneyArgs) -> ToolOutcome:
    gw = ctx.gateway
    journey_id = args.journey_id or ctx.journey_id
    if journey_id is None:
        latest = await _latest_journey_id(gw)
        if isinstance(latest, ToolOutcome):
            return latest
        if latest is None:
            return ToolOutcome(
                "not_found",
                summary="No plan yet",
                guidance="The person has no plan yet. Understand their goals, then offer to "
                "build one (start_journey).",
            )
        journey_id = latest
    route = gw.first_served("GET", Routes.JOURNEY)
    if route is None:
        return unavailable("Your plan")
    response = await gw.get(route, path_params=[journey_id])
    if not response.ok:
        return failure(response, what="That plan")
    steps = _items(response.body, "steps", "nodes", "tasks")
    title = _first(response.body, "title", "name") or "Your plan"
    return ToolOutcome(
        "ok",
        data=shape(response.body),
        summary=f"{title}: {_count(len(steps), 'step')}" if steps else str(title),
        guidance="Lead with what's next and what's blocking it. Explain dependencies (why a "
        "step must wait) and cite the authority for requirements.",
        ui_hint="/journey",
    )


def _node_brief(node: dict[str, Any]) -> dict[str, Any]:
    provenance = node.get("provenance") if isinstance(node.get("provenance"), dict) else {}
    citations = provenance.get("citations") or []
    first_citation = citations[0] if citations and isinstance(citations[0], dict) else {}
    return {
        "key": node.get("key"),
        "type": _first(node, "entity_type", "type", "node_type"),
        "label": node.get("label"),
        "summary": node.get("summary"),
        "official_url": node.get("official_url"),
        "trust_tier": node.get("evidence_kind") or provenance.get("kind"),
        "authority": first_citation.get("authority"),
    }


def _terms(text: str) -> set[str]:
    """Lower-cased words of 3+ letters, lightly stemmed (visas -> visa)."""
    words = re.findall(r"[^\W\d_]{3,}", text.lower())
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words}


# Services answer "what do I need"; their requirements follow; authorities last.
_TYPE_WEIGHT = {"service": 3.0, "requirement": 1.5, "eligibility_rule": 1.5, "document": 1.0}


def _rank(nodes: list[dict[str, Any]], edges: list[Any], query: str) -> list[dict[str, Any]]:
    """Order a search result by relevance: nodes matching the query first (services before
    their requirements), then nodes directly connected to a match (what they require,
    who provides them). Unrelated neighbourhood is dropped."""
    terms = _terms(query)

    def score(node: dict[str, Any]) -> float:
        label = _terms(str(node.get("label") or ""))
        key = _terms(str(node.get("key") or "").replace(".", " ").replace("_", " "))
        summary = _terms(str(node.get("summary") or ""))
        hits = 3 * len(terms & label) + 2 * len(terms & key) + len(terms & summary)
        if not hits:
            return 0.0
        kind = str(_first(node, "entity_type", "type", "node_type") or "")
        return hits + _TYPE_WEIGHT.get(kind, 0.0)

    scored = sorted(((score(n), i, n) for i, n in enumerate(nodes)), key=lambda t: (-t[0], t[1]))
    matched = [n for s, _, n in scored if s > 0]
    if not matched:
        return nodes
    matched_ids = {str(n.get("id")) for n in matched}
    linked: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        ends = {
            str(_first(edge, "source_node_id", "source")),
            str(_first(edge, "target_node_id", "target")),
        }
        if ends & matched_ids:
            linked |= ends - matched_ids
    return matched + [n for n in nodes if str(n.get("id")) in linked]


def _relations(nodes: list[dict[str, Any]], edges: list[Any]) -> list[str]:
    labels = {str(n.get("id")): str(n.get("label")) for n in nodes if n.get("id")}
    out: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = labels.get(str(_first(edge, "source_node_id", "source")))
        target = labels.get(str(_first(edge, "target_node_id", "target")))
        relation = _first(edge, "relation", "type", "edge_type")
        if source and target and relation:
            out.append(f"{source} —{str(relation).replace('_', ' ')}→ {target}")
    return out


def _node_citations(nodes: list[dict[str, Any]], evidence: list[Any]) -> list[ToolCitation]:
    """Cite the evidence passages behind the results; fall back to their official pages."""
    by_id = {e.get("id"): e for e in evidence if isinstance(e, dict)}
    candidates: list[ToolCitation | None] = []
    for node in nodes:
        for evidence_id in node.get("evidence_ids") or []:
            item = by_id.get(evidence_id)
            if item:
                candidates.append(
                    _citation(
                        title=item.get("source_title"),
                        url=item.get("source_url"),
                        kind=item.get("evidence_kind"),
                        authority=item.get("authority"),
                        retrieved_at=item.get("retrieved_at"),
                    )
                )
        brief = _node_brief(node)
        candidates.append(
            _citation(
                title=brief["label"],
                url=brief["official_url"],
                kind=brief["trust_tier"],
                authority=brief["authority"],
            )
        )
    return _citations(candidates)


async def search_governance(ctx: ToolContext, args: SearchGovernanceArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("GET", Routes.GOVERNANCE_SEARCH)
    if route is None:
        return unavailable("Government service search")

    async def search(q: str) -> tuple[list[dict[str, Any]], list[Any], list[Any]] | ToolOutcome:
        response = await gw.get(route, params={"q": q})
        if not response.ok:
            return failure(response, what="Government service search")
        nodes = [n for n in _items(response.body, "nodes") if isinstance(n, dict)]
        return nodes, _items(response.body, "edges"), _items(response.body, "evidence")

    found = await search(args.query)
    if isinstance(found, ToolOutcome):
        return found
    nodes, edges, evidence = found
    if not nodes:
        # Some graph filters match a phrase; retry with the most specific single words.
        seen: dict[str, dict[str, Any]] = {}
        for word in sorted(_terms(args.query), key=len, reverse=True)[:3]:
            partial = await search(word)
            if isinstance(partial, ToolOutcome):
                return partial
            for node in partial[0]:
                seen.setdefault(str(node.get("id") or node.get("key")), node)
            edges.extend(partial[1])
            evidence.extend(partial[2])
        nodes = list(seen.values())
    nodes = _rank(nodes, edges, args.query)[: args.limit]
    if not nodes:
        return ToolOutcome(
            "not_found",
            summary="No matching services",
            guidance="Nothing matched in ADAPT's governance graph. Try other keywords, or say "
            "you couldn't find it and suggest the official TAMM portal.",
        )
    return ToolOutcome(
        "ok",
        citations=_node_citations(nodes, evidence),
        data=shape(
            {"results": [_node_brief(n) for n in nodes], "relations": _relations(nodes, edges)}
        ),
        summary=f"Found {_count(len(nodes), 'matching service or requirement')}"
        if len(nodes) == 1
        else f"Found {len(nodes)} matching services and requirements",
        guidance="These come from ADAPT's governance graph, most relevant first; each has a "
        "trust tier. Before stating a specific requirement, fee or threshold as binding, check "
        "it with retrieve_evidence. Put official links on screen, don't read them aloud.",
        ui_hint="/services",
    )


def _evidence_brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim": item.get("claim") or item.get("content") or item.get("quote"),
        "trust_tier": item.get("evidence_kind"),
        "source_title": item.get("source_title"),
        "source_url": item.get("source_url"),
        "authority": item.get("authority"),
        "section": item.get("section_or_page"),
        "effective_date": item.get("effective_date"),
        "retrieved_at": item.get("retrieved_at"),
        "freshness": item.get("freshness"),
        "caveats": item.get("caveats"),
    }


async def retrieve_evidence(ctx: ToolContext, args: RetrieveEvidenceArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("GET", Routes.EVIDENCE_SEARCH)
    if route is None:
        return unavailable("Official evidence search")
    params: dict[str, Any] = {"q": args.query, "k": args.limit}
    if args.service_key:
        params["node"] = args.service_key
    response = await gw.get(route, params=params)
    if not response.ok:
        return failure(response, what="Official evidence search")
    results = [r for r in _items(response.body, "results", "evidence") if isinstance(r, dict)]
    if not results:
        return ToolOutcome(
            "not_found",
            summary="No current official source found",
            guidance="No current official passage covers this. Say you couldn't find a current "
            "official source, don't state the requirement, and point to the official channel.",
        )
    stale = any((r.get("freshness") == "stale") for r in results)
    guidance = (
        "Attribute each point to its source, e.g. 'According to official guidance on u.ae…'. "
        "authoritative_requirement is binding; official_guidance is advisory."
    )
    if stale:
        guidance += " Some sources are marked stale: suggest confirming on the official page."
    briefs = [_evidence_brief(r) for r in results[: args.limit]]
    return ToolOutcome(
        "ok",
        citations=_citations(
            [
                _citation(
                    title=b["source_title"],
                    url=b["source_url"],
                    kind=b["trust_tier"],
                    authority=b["authority"],
                    retrieved_at=b["retrieved_at"],
                )
                for b in briefs
            ]
        ),
        data=shape({"evidence": briefs}),
        summary=f"Found {_count(min(len(results), args.limit), 'official source')}",
        guidance=guidance,
    )


async def get_user_graph(ctx: ToolContext, _: NoArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("GET", Routes.USER_GRAPH)
    if route is None:
        return unavailable("Your personal graph")
    response = await gw.get(route)
    if not response.ok:
        return failure(response, what="Your personal graph")
    nodes = _items(response.body, "nodes")
    return ToolOutcome(
        "ok",
        data=shape(response.body),
        summary=f"Read {_count(len(nodes), 'item')} about you" if nodes else "Read your graph",
        guidance="This is private information the person shared or confirmed. Use it to "
        "explain what applies to them; don't read it back wholesale.",
        ui_hint="/twin",
    )


async def start_journey(ctx: ToolContext, args: StartJourneyArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("POST", Routes.JOURNEYS)
    if route is None:
        return unavailable("Plan building")
    response = await gw.post(
        route, json={"prompt": args.request, "language": args.language, "channel": "voice"}
    )
    if not response.ok:
        return failure(response, what="Plan building")
    run = _first(response.body, "run") or response.body
    return ToolOutcome(
        "ok",
        data=shape(
            {
                "journey_id": _first(response.body, "journey_id"),
                "run_id": _id_of(run),
                "status": _first(run, "status"),
            }
        ),
        summary="Started building your plan",
        guidance="Planning has started in the background and hasn't finished. Tell the person "
        "it's underway, that progress shows in Activity, and that you can keep talking.",
        ui_hint="/activity",
    )


async def upload_document_context(ctx: ToolContext, args: UploadDocumentContextArgs) -> ToolOutcome:
    gw = ctx.gateway
    if args.document_id:
        route = gw.first_served("GET", Routes.DOCUMENT)
        if route is None:
            return unavailable("Documents")
        response = await gw.get(route, path_params=[args.document_id])
        if not response.ok:
            return failure(response, what="That document")
        return ToolOutcome(
            "ok",
            data=shape(response.body),
            summary="Read your document",
            guidance="Summarise what was read and anything that still needs their review. "
            "Identifiers are masked: never read numbers aloud.",
            ui_hint="/documents",
        )

    route = gw.first_served("GET", Routes.DOCUMENTS)
    if route is None:
        return unavailable("Documents")
    response = await gw.get(route)
    if not response.ok:
        return failure(response, what="Your documents")
    documents = _items(response.body, "items", "documents")
    data: dict[str, Any] = {"documents": shape(documents)}
    uploads = gw.first_served("POST", Routes.DOCUMENT_UPLOAD) is not None
    if args.kind:
        data["upload_request"] = {"kind": args.kind, "reason": args.reason}
        guidance = (
            "Ask the person to add it with the Documents button on screen (camera or file). "
            "It's read privately and they review what was extracted."
            if uploads
            else "Uploading documents isn't available right now. Say so, and carry on without it."
        )
        summary = f"Asked for your {args.kind.replace('_', ' ')}"
    else:
        guidance = "These are the person's documents. Refer to them by type, never by number."
        summary = f"Found {_count(len(documents), 'document')}"
    return ToolOutcome("ok", data=data, summary=summary, guidance=guidance, ui_hint="/documents")


def _https(url: Any) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") else None


def _approval_from(body: Any) -> ApprovalRequest | None:
    action = _first(body, "action") or {}
    approval = _first(body, "approval") or {}
    if not isinstance(action, dict) or not isinstance(approval, dict):
        return None
    action_id = _id_of(action) or _first(approval, "action_id")
    if not action_id:
        return None
    preview = approval.get("payload_preview")
    preview = preview if isinstance(preview, dict) else {}
    consequences = _first(approval, "consequences") or _first(action, "consequences") or []
    return ApprovalRequest(
        action_id=str(action_id),
        title=str(_first(approval, "title") or _first(action, "title") or "Review this action"),
        summary=str(
            _first(approval, "summary") or _first(action, "summary", "message", "description") or ""
        ),
        consequences=[str(c) for c in consequences if c][:6],
        requires_user_authentication=bool(
            _first(approval, "requires_user_authentication")
            or _first(action, "requires_user_authentication")
        ),
        handoff_url=_https(
            _first(action, "official_url", "handoff_url") or _first(preview, "handoff_url")
        ),
        kind=_first(action, "type", "kind"),
        simulation_label=(_first(action, "simulation_label") or "DEMO / SIMULATED")
        if action.get("is_simulated")
        else None,
    )


async def prepare_action(ctx: ToolContext, args: PrepareActionArgs) -> ToolOutcome:
    if not (args.task_key or args.service_key or args.journey_node_id):
        return ToolOutcome(
            "invalid_arguments",
            summary="Needs a step or service",
            guidance="Say what to prepare: pass task_key (a plan step from get_journey) or "
            "service_key (from search_governance).",
        )
    gw = ctx.gateway
    route = gw.first_served("POST", Routes.ACTION_PREPARE)
    if route is None:
        return unavailable("Preparing actions")
    journey_id = args.journey_id or ctx.journey_id
    if journey_id is None:
        latest = await _latest_journey_id(gw)
        if isinstance(latest, ToolOutcome):
            return latest
        if latest is None:
            return ToolOutcome(
                "not_found",
                summary="No plan yet",
                guidance="Actions are prepared as part of the person's plan, and they don't "
                "have one yet. Offer to build it first (start_journey).",
            )
        journey_id = latest
    body = {
        "journey_id": journey_id,
        "task_key": args.task_key,
        "service_key": args.service_key,
        "journey_node_id": args.journey_node_id,
        "type": args.kind,
    }
    response = await gw.post(route, json={k: v for k, v in body.items() if v is not None})
    if not response.ok:
        if response.code == "journey_step_not_found":
            return ToolOutcome(
                "not_found",
                summary="That isn't a step in your plan yet",
                guidance="That service isn't a step in the person's plan (it may still be being "
                "built). Say so; offer the official link from search_governance instead, or to "
                "prepare it once the plan includes it.",
            )
        return failure(response, what="Preparing that action")
    approval = _approval_from(response.body)
    if approval is None:
        logger.warning("prepare_action_unrecognised_response")
        return ToolOutcome(
            "error",
            summary="Couldn't prepare that",
            guidance="The action "
            "couldn't be prepared. Apologise and offer the official link instead.",
        )
    return ToolOutcome(
        "needs_approval",
        data=shape(
            {
                "title": approval.title,
                "summary": approval.summary,
                "consequences": approval.consequences,
                "requires_user_authentication": approval.requires_user_authentication,
            }
        ),
        summary=f"Prepared: {approval.title}",
        guidance="Nothing has happened yet. In one or two sentences say what approving will "
        "do, then ask the person to review the card on screen and tap Approve or Decline. A "
        "spoken yes is not an approval. If they must sign in on the official site, say so."
        + (
            " This runs on a demonstration adapter: say clearly that nothing real will be "
            "booked or submitted."
            if approval.simulation_label
            else ""
        ),
        approval=approval,
    )


async def start_research(ctx: ToolContext, args: StartResearchArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("POST", Routes.RESEARCH)
    if route is None:
        return unavailable("Community and lifestyle research")
    body: dict[str, Any] = {}
    if args.categories:
        body["categories"] = list(dict.fromkeys(args.categories))
    if args.focus:
        body["focus"] = args.focus
    if ctx.journey_id:
        body["journey_id"] = ctx.journey_id
    response = await gw.post(route, json=body)
    if not response.ok:
        return failure(response, what="Research")
    job = _first(response.body, "job") or response.body
    return ToolOutcome(
        "ok",
        data=shape(
            {
                "job_id": _id_of(job),
                "status": _first(job, "status"),
                "categories": _first(job, "categories"),
            }
        ),
        summary="Started researching for you",
        guidance="Research runs in the background and hasn't finished. Say it's underway and "
        "that results appear in Discover. Results mix official and community sources, each "
        "labelled; community results are never requirements.",
        ui_hint="/discover",
    )


async def simulate_journey(ctx: ToolContext, args: SimulateJourneyArgs) -> ToolOutcome:
    gw = ctx.gateway
    route = gw.first_served("POST", Routes.JOURNEY_SIMULATE)
    if route is None:
        return unavailable("What-if simulation")
    journey_id = args.journey_id or ctx.journey_id
    if journey_id is None:
        latest = await _latest_journey_id(gw)
        if isinstance(latest, ToolOutcome):
            return latest
        if latest is None:
            return ToolOutcome(
                "not_found",
                summary="No plan to compare",
                guidance="There's no plan to simulate yet. Offer to build one first.",
            )
        journey_id = latest
    changes = [change.model_dump() for change in args.changes]
    response = await gw.post(route, path_params=[journey_id], json={"changes": changes})
    if response.status == 409 and response.code == "journey_not_ready":
        return ToolOutcome(
            "not_found",
            summary="Your plan isn't ready yet",
            guidance="The plan is still being built, so it can't be compared yet. Offer to try "
            "the what-if once the plan is ready.",
        )
    if response.status in (400, 422):
        outcome = failure(response, what="What-if simulation")
        variables = gw.first_served("GET", Routes.JOURNEY_VARIABLES)
        if variables:
            known = await gw.get(variables, path_params=[journey_id])
            if known.ok:
                outcome.data = shape({"valid_changes": known.body})
                outcome.guidance = (
                    "That change isn't one the simulation understands. Pick a key and value "
                    "from valid_changes (current values are shown) and call it again."
                )
        return outcome
    if not response.ok:
        return failure(response, what="What-if simulation")
    result = await _simulation_result(gw, _first(response.body, "scenario_journey_id"))
    if result is not None:
        return ToolOutcome(
            "ok",
            data=shape(result),
            summary=str(result.get("summary") or "Your what-if is ready"),
            guidance="Explain what changes compared with the plan: added, removed or reordered "
            "steps and changed risks. A scenario is never acted upon; the plan is unchanged.",
            ui_hint="/simulate",
        )
    return ToolOutcome(
        "ok",
        data=shape(response.body),
        summary="Simulating a what-if scenario",
        guidance="If the result is already here, explain what changes: added, removed or "
        "delayed steps. If it's still running, say the comparison will appear in What if. "
        "A scenario is never acted upon.",
        ui_hint="/simulate",
    )


# Under the browser's 20 s request timeout; a demo what-if takes a few seconds.
SIMULATION_WAIT_SECONDS = 12.0
SIMULATION_POLL_SECONDS = 1.0


async def _simulation_result(gw: ApiGateway, scenario_id: Any) -> dict[str, Any] | None:
    """The comparison, if the what-if finishes within a short wait (it usually takes seconds)."""
    route = gw.first_served("GET", Routes.JOURNEY)
    if route is None or not scenario_id:
        return None
    deadline = time.monotonic() + SIMULATION_WAIT_SECONDS
    while time.monotonic() < deadline:
        scenario = await gw.get(route, path_params=[str(scenario_id)])
        if not scenario.ok:
            return None
        result = _first(scenario.body, "simulation_result")
        if isinstance(result, dict):
            return result
        await asyncio.sleep(SIMULATION_POLL_SECONDS)
    return None


async def get_research_status(ctx: ToolContext, args: ResearchStatusArgs) -> ToolOutcome:
    gw = ctx.gateway
    job_id = args.job_id
    if job_id is None:
        if not gw.serves("GET", Routes.RESEARCH[0]):
            return unavailable("Research")
        latest = await gw.get(Routes.RESEARCH[0], params={"limit": 1})
        if not latest.ok:
            return failure(latest, what="Research")
        jobs = _items(latest.body, "items", "jobs")
        if not jobs:
            return ToolOutcome(
                "not_found",
                summary="No research yet",
                guidance="No research has been run yet. Offer to start some (start_research).",
            )
        job_id = _id_of(jobs[0])
    route = gw.first_served("GET", Routes.RESEARCH_JOB)
    if route is None or job_id is None:
        return unavailable("Research")
    response = await gw.get(route, path_params=[job_id])
    if not response.ok:
        return failure(response, what="That research")
    job = _first(response.body, "job") or {}
    results = _items(response.body, "results")
    citations = _citations(
        [
            _citation(
                title=r.get("source_title") or r.get("title"),
                url=r.get("source_url"),
                kind=r.get("evidence_kind"),
                retrieved_at=r.get("retrieved_at"),
            )
            for r in results
            if isinstance(r, dict)
        ]
    )
    return ToolOutcome(
        "ok",
        citations=citations,
        data=shape(
            {
                "status": _first(job, "status"),
                "results": [
                    {
                        k: r.get(k)
                        for k in (
                            "category",
                            "title",
                            "summary",
                            "relevance",
                            "evidence_kind",
                            "source_title",
                            "retrieved_at",
                            "contacts",
                            "event",
                        )
                    }
                    for r in results
                    if isinstance(r, dict)
                ],
            }
        ),
        summary=_research_summary(job, len(results)),
        guidance="Voice each result by its evidence_kind: official guidance vs community "
        "information. Community results are never requirements. If contacts are empty, say "
        "you don't have verified contact details.",
        ui_hint="/discover",
    )


def _research_summary(job: Any, found: int) -> str:
    status = _first(job, "status")
    if status in ("queued", "running"):
        return f"Still researching: {_count(found, 'finding')} so far"
    if status == "succeeded":
        ready = "Your Abu Dhabi Life Brief is ready" if _first(job, "brief_ready") else "Done"
        return f"{ready}: {_count(found, 'finding')}"
    if status == "failed":
        return "The research stopped before it finished"
    return f"{_count(found, 'finding')} so far" if found else "Research status"


# --- registry ---------------------------------------------------------------------------------


Handler = Callable[[ToolContext, Any], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class ToolDef:
    name: str
    label: str
    description: str
    args: type[ToolArgs]
    handler: Handler = field(repr=False)

    def spec(self) -> VoiceToolSpec:
        return VoiceToolSpec(
            name=self.name,
            label=self.label,
            description=self.description,
            parameters=json_schema(self.args),
        )


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Self-contained JSON schema (refs inlined, titles dropped) for function calling."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: inline(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    result: dict[str, Any] = inline(schema)
    result.setdefault("properties", {})
    result["additionalProperties"] = False
    return result


TOOLS: tuple[ToolDef, ...] = (
    ToolDef(
        "get_profile",
        "Checking your profile",
        "Get the person's profile: name, household, goals, preferences and whether they've "
        "opted in to faith or community personalisation. Call before personalising advice.",
        NoArgs,
        get_profile,
    ),
    ToolDef(
        "get_journey",
        "Checking your plan",
        "Get the person's relocation plan: ordered steps with status, dependencies, blockers, "
        "responsible authorities and official links. Omit journey_id for their current plan.",
        GetJourneyArgs,
        get_journey,
    ),
    ToolDef(
        "search_governance",
        "Searching official services",
        "Search Abu Dhabi's governance knowledge graph: government services, requirements, "
        "documents, eligibility rules, authorities and official channels, with trust tiers "
        "and how they depend on each other.",
        SearchGovernanceArgs,
        search_governance,
    ),
    ToolDef(
        "retrieve_evidence",
        "Checking official sources",
        "Retrieve passages from current official government sources. Use before stating any "
        "requirement, fee, eligibility rule or deadline, and cite the source.",
        RetrieveEvidenceArgs,
        retrieve_evidence,
    ),
    ToolDef(
        "get_user_graph",
        "Reviewing what you've shared",
        "Get the person's private digital twin: people, organisations, documents and goals, "
        "and how they connect to government services. Use it to explain what applies to them.",
        NoArgs,
        get_user_graph,
    ),
    ToolDef(
        "start_journey",
        "Starting your plan",
        "Start building (or rebuilding) the person's personalised relocation plan from what "
        "they've described. Runs in the background; progress appears in Activity.",
        StartJourneyArgs,
        start_journey,
    ),
    ToolDef(
        "upload_document_context",
        "Looking at your documents",
        "Bring the person's documents into the conversation. With document_id: what was read "
        "from it and what still needs their review. Without: lists their documents; pass kind "
        "to ask them to upload a document you need.",
        UploadDocumentContextArgs,
        upload_document_context,
    ),
    ToolDef(
        "prepare_action",
        "Preparing an action",
        "Prepare an action, such as continuing an application on the official portal or "
        "booking an appointment, for the person to approve on screen. Nothing is submitted.",
        PrepareActionArgs,
        prepare_action,
    ),
    ToolDef(
        "start_research",
        "Starting research",
        "Start background research on communities, events, culture, lifestyle and practical "
        "life in Abu Dhabi, matched to the person. Faith-related research needs their opt-in.",
        StartResearchArgs,
        start_research,
    ),
    ToolDef(
        "simulate_journey",
        "Simulating a what-if",
        "Run a what-if simulation on the person's plan, e.g. a different company jurisdiction "
        "or move date, and compare it with the current plan. Never acted upon.",
        SimulateJourneyArgs,
        simulate_journey,
    ),
    ToolDef(
        "get_research_status",
        "Checking research",
        "Check background research: its status and the latest findings, each labelled "
        "official or community information.",
        ResearchStatusArgs,
        get_research_status,
    ),
)
TOOLS_BY_NAME: dict[str, ToolDef] = {tool.name: tool for tool in TOOLS}


def tool_specs() -> list[VoiceToolSpec]:
    return [tool.spec() for tool in TOOLS]


def tool_result(
    call_id: str, tool_name: str, label: str, outcome: ToolOutcome
) -> VoiceToolCallResult:
    return VoiceToolCallResult(
        call_id=call_id,
        name=tool_name,
        status=outcome.status,
        output=outcome.model_output(),
        activity=ToolActivity(
            call_id=call_id,
            name=tool_name,
            label=label,
            status=outcome.status,
            summary=outcome.summary,
        ),
        approval=outcome.approval,
        consent=outcome.consent,
        citations=outcome.citations,
        ui_hint=outcome.ui_hint,
    )


async def execute_tool(
    ctx: ToolContext, *, call_id: str, name: str, arguments: str
) -> VoiceToolCallResult:
    """Validate and run one tool call. Never raises: failures become outcomes the model
    can explain, so a call is never left without an output."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        outcome = ToolOutcome(
            "invalid_arguments",
            guidance=f"There is no tool called {name!r}. Use one of: " + ", ".join(TOOLS_BY_NAME),
        )
        return tool_result(call_id, name, "Working on it", outcome)
    try:
        raw = json.loads(arguments or "{}")
        if not isinstance(raw, dict):
            raise ValueError("arguments must be a JSON object")
        args = tool.args.model_validate(raw)
    except (ValueError, ValidationError, RecursionError) as exc:
        detail = (
            [{"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()]
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        outcome = ToolOutcome(
            "invalid_arguments",
            data={"errors": detail},
            summary="Needs different details",
            guidance="Fix the arguments and call the tool again.",
        )
        return tool_result(call_id, name, tool.label, outcome)
    try:
        async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
            outcome = await tool.handler(ctx, args)
    except TimeoutError:
        outcome = ToolOutcome(
            "error",
            summary="Took too long",
            guidance="This took too long. Apologise briefly and offer to try again.",
        )
    except Exception:
        logger.exception("tool_failed", extra={"tool": name})
        outcome = ToolOutcome(
            "error",
            summary="Something went wrong",
            guidance="Something went "
            "wrong on ADAPT's side. Apologise briefly and offer to try again.",
        )
    return tool_result(call_id, name, tool.label, outcome)


def tool_names() -> Sequence[str]:
    return tuple(TOOLS_BY_NAME)
