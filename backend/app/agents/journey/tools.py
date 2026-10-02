"""The journey agent's tools: typed inputs/outputs, streamed tool events, evidence refs.

Every call emits `tool_called` then `tool_result` (ok or not) on the run's event stream
and appends `tool_call` / `tool_result` entries to the node's state journal. Tools that
produce support for a claim return `EvidenceRecord`s with deterministic ids, which
tasks, requirements, risks and actions reference.

`TOOL_SPECS` exposes the JSON schemas, so the same tools can be offered to an LLM or
the voice agent via function calling.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agents.journey.context import JourneyContext
from app.agents.journey.emit import emit
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.planning import reference_evidence_id
from app.agents.journey.ports import DocumentAnalysis
from app.agents.journey.spec import journal
from app.agents.journey.state import (
    ActionRecord,
    EvidenceRecord,
    GovEdge,
    GovernanceContext,
    GovNode,
    UserFact,
)
from app.domain.actions import ActionRequest, PreparedAction
from app.domain.enums import ActionKind, ActionStatus, EvidenceKind

logger = logging.getLogger(__name__)

# --- inputs & outputs ------------------------------------------------------------------


class GetUserGraphInput(BaseModel):
    keys: list[str] | None = Field(default=None, description="Fact keys to read; all when omitted")


class UserGraphOutput(BaseModel):
    facts: list[dict[str, Any]]  # UserFact


class GetGovernanceGraphInput(BaseModel):
    root_keys: list[str] = Field(description="Service keys to start from")


class GovernanceGraphOutput(BaseModel):
    nodes: list[dict[str, Any]]  # GovNode
    edges: list[dict[str, Any]]  # GovEdge
    missing_keys: list[str]


class RetrieveEvidenceInput(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    governance_keys: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceOutput(BaseModel):
    records: list[dict[str, Any]]  # EvidenceRecord
    passages: int
    references: int


class AnalyzeDocumentInput(BaseModel):
    document_id: str


class DocumentAnalysisOutput(BaseModel):
    document_id: str
    kind: str
    holder: str
    status: str
    needs_review: bool
    cached: bool
    fields: list[dict[str, Any]]
    facts: list[dict[str, Any]]  # UserFact
    review_task_ids: list[str]


class GenerateDocumentInput(BaseModel):
    kind: Literal["checklist", "cover_letter", "email", "appointment_brief", "business_summary"]
    title: str = Field(max_length=300)
    journey_id: str
    task_key: str | None = None
    context: dict[str, Any] = Field(
        default_factory=dict, description="Facts and requirements the document may use"
    )
    persist: bool = True


class GeneratedDocumentOutput(BaseModel):
    id: str
    kind: str
    title: str
    body_markdown: str
    persisted: bool
    provenance: dict[str, Any]


class PrepareActionInput(BaseModel):
    action_type: ActionKind
    task_key: str
    service_key: str
    title: str
    official_url: str | None = None
    channel_name: str | None = None
    requires_login: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    action_id: str | None = None


class PrepareAppointmentInput(BaseModel):
    task_key: str
    service_key: str
    title: str
    official_url: str | None = None
    channel_name: str | None = None
    requires_login: bool = False
    preferred_after: str | None = Field(default=None, description="ISO date")
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    action_id: str | None = None


class PreparedActionOutput(BaseModel):
    action: dict[str, Any]  # ActionRecord


class StartResearchInput(BaseModel):
    journey_id: str


class ResearchStartOutput(BaseModel):
    started: bool
    job_id: str | None = None
    run_id: str | None = None
    status: str
    reason: str | None = None


class SimulateJourneyInput(BaseModel):
    journey_id: str
    changes: list[dict[str, Any]] = Field(min_length=1, max_length=10)


class SimulationOutput(BaseModel):
    result: dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input: type[BaseModel]
    output: type[BaseModel]


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "get_user_graph",
            "Read the user's private facts (their digital twin).",
            GetUserGraphInput,
            UserGraphOutput,
        ),
        ToolSpec(
            "get_governance_graph",
            "Read the official services, requirements and dependencies reachable from services.",
            GetGovernanceGraphInput,
            GovernanceGraphOutput,
        ),
        ToolSpec(
            "retrieve_evidence",
            "Retrieve official-source passages and citations supporting requirements.",
            RetrieveEvidenceInput,
            EvidenceOutput,
        ),
        ToolSpec(
            "analyze_document",
            "Read fields from an uploaded document (idempotent).",
            AnalyzeDocumentInput,
            DocumentAnalysisOutput,
        ),
        ToolSpec(
            "generate_document",
            "Draft a checklist, cover letter or email for the user's review.",
            GenerateDocumentInput,
            GeneratedDocumentOutput,
        ),
        ToolSpec(
            "prepare_action",
            "Prepare an official-service action without side effects.",
            PrepareActionInput,
            PreparedActionOutput,
        ),
        ToolSpec(
            "prepare_appointment",
            "Prepare an appointment booking handoff without side effects.",
            PrepareAppointmentInput,
            PreparedActionOutput,
        ),
        ToolSpec(
            "start_research",
            "Start background community research; does not wait.",
            StartResearchInput,
            ResearchStartOutput,
        ),
        ToolSpec(
            "simulate_journey",
            "Run a what-if on a copy of the journey; never changes it.",
            SimulateJourneyInput,
            SimulationOutput,
        ),
    )
}


def tool_schemas() -> list[dict[str, Any]]:
    """Function-calling definitions for LLM or voice agents."""
    return [
        {"name": s.name, "description": s.description, "parameters": s.input.model_json_schema()}
        for s in TOOL_SPECS.values()
    ]


# --- evidence helpers ----------------------------------------------------------------------


def reference_record(node: GovNode, tool_call_id: str | None) -> EvidenceRecord | None:
    """A governance node's own citation of an official page (no quoted passage)."""
    provenance = node.get("provenance") or {}
    citations = provenance.get("citations") or []
    url = (citations[0].get("source_url") if citations else None) or node.get("official_url")
    if not url:
        return None
    return EvidenceRecord(
        id=reference_evidence_id(node["key"]),
        kind="official_reference",
        trust=str(provenance.get("kind") or EvidenceKind.OFFICIAL_GUIDANCE.value),
        title=(citations[0].get("source_title") if citations else None) or node["label"],
        source_url=url,
        authority=citations[0].get("authority") if citations else None,
        quote=None,
        governance_key=node["key"],
        document_id=None,
        tool_call_id=tool_call_id,
        retrieved_at=None,
    )


def document_record(analysis: DocumentAnalysis, tool_call_id: str | None) -> EvidenceRecord:
    return EvidenceRecord(
        id=f"doc:{analysis.document_id}",
        kind="user_document",
        trust=EvidenceKind.AI_RECOMMENDATION.value,
        title=f"Your {analysis.kind.replace('_', ' ')}",
        source_url=None,
        authority=None,
        quote=None,
        governance_key=None,
        document_id=analysis.document_id,
        tool_call_id=tool_call_id,
        retrieved_at=None,
    )


def _summarize(name: str, out: BaseModel) -> str:
    match out:
        case UserGraphOutput():
            return f"{len(out.facts)} facts"
        case GovernanceGraphOutput():
            return f"{len(out.nodes)} nodes, {len(out.edges)} relationships"
        case EvidenceOutput():
            return f"{out.passages} official passages, {out.references} official references"
        case DocumentAnalysisOutput():
            review = sum(1 for f in out.fields if f.get("needs_review"))
            return f"{out.kind}: {len(out.fields)} fields, {review} to review" + (
                " (stored)" if out.cached else ""
            )
        case GeneratedDocumentOutput():
            return f"{out.kind} '{out.title}'" + ("" if out.persisted else " (preview)")
        case PreparedActionOutput():
            label = out.action.get("simulation_label")
            return f"{out.action['type']}: {out.action['status']}" + (
                f" [{label}]" if label else ""
            )
        case ResearchStartOutput():
            return out.status if out.started else f"not started: {out.reason}"
        case SimulationOutput():
            return str(out.result.get("summary", "simulated"))
    return name


# --- the toolbox ----------------------------------------------------------------------------


class JourneyTools:
    """Tools bound to one run's context (principal, services, event sink)."""

    def __init__(self, context: JourneyContext) -> None:
        self.context = context
        self.services = context.svc
        self._governance: GovernanceSnapshot | None = None

    async def _run[O: BaseModel](
        self, name: str, args: BaseModel, label: str, impl: Callable[[str], Awaitable[O]]
    ) -> tuple[O, str]:
        call_id = f"{name}:{uuid4().hex[:12]}"
        journal("tool_call", label, call_id)
        await emit(self.context, "tool_called", name, call_id=call_id, summary=label)
        started = time.perf_counter()
        try:
            out = await impl(call_id)
        except Exception as exc:
            journal("tool_result", f"{name} failed", call_id)
            await emit(
                self.context,
                "tool_result",
                name,
                call_id=call_id,
                ok=False,
                summary=f"{name} failed",
            )
            logger.info("tool_failed", extra={"tool": name, "error": type(exc).__name__})
            raise
        summary = _summarize(name, out)
        journal("tool_result", summary, call_id)
        await emit(self.context, "tool_result", name, call_id=call_id, ok=True, summary=summary)
        logger.debug(
            "tool_ok", extra={"tool": name, "ms": int((time.perf_counter() - started) * 1000)}
        )
        return out, call_id

    async def snapshot(self) -> GovernanceSnapshot:
        if self._governance is None:
            self._governance = await self.services.store.governance()
        return self._governance

    # --- reads -------------------------------------------------------------------------
    async def get_user_graph(self, args: GetUserGraphInput) -> UserGraphOutput:
        async def impl(call_id: str) -> UserGraphOutput:
            facts = await self.services.store.user_facts()
            if args.keys is not None:
                facts = [f for f in facts if f["key"] in args.keys]
            return UserGraphOutput(facts=[dict(f) for f in facts])

        out, _ = await self._run("get_user_graph", args, "Reading your private profile", impl)
        return out

    async def get_governance_graph(self, args: GetGovernanceGraphInput) -> GovernanceGraphOutput:
        async def impl(call_id: str) -> GovernanceGraphOutput:
            snapshot = await self.snapshot()
            present = [k for k in args.root_keys if k in snapshot.nodes]
            context = snapshot.context(present, [])
            return GovernanceGraphOutput(
                nodes=[dict(n) for n in context["nodes"].values()],
                edges=[dict(e) for e in context["edges"]],
                missing_keys=[k for k in args.root_keys if k not in snapshot.nodes],
            )

        out, _ = await self._run(
            "get_governance_graph", args, "Finding the official services that apply", impl
        )
        return out

    async def retrieve_evidence(self, args: RetrieveEvidenceInput) -> EvidenceOutput:
        async def impl(call_id: str) -> EvidenceOutput:
            records: dict[str, EvidenceRecord] = {}
            hits = await self.services.evidence.retrieve(
                args.query, governance_keys=args.governance_keys, top_k=args.top_k
            )
            for hit in hits:
                record = EvidenceRecord(
                    id=f"passage:{hit.id}",
                    kind="official_passage",
                    trust=hit.trust,
                    title=hit.title,
                    source_url=hit.source_url,
                    authority=hit.authority,
                    quote=hit.quote,
                    governance_key=hit.governance_key,
                    document_id=None,
                    tool_call_id=call_id,
                    retrieved_at=hit.retrieved_at,
                    claim=hit.claim,
                    section_or_page=hit.section_or_page,
                    effective_date=hit.effective_date,
                    excerpt=hit.excerpt,
                    source_family=hit.source_family,
                    freshness=hit.freshness,
                    chunk_id=hit.chunk_id,
                )
                records[record["id"]] = record
                await emit(
                    self.context,
                    "evidence_found",
                    title=hit.title,
                    source_url=hit.source_url,
                    authority=hit.authority,
                    evidence_kind=hit.trust,
                    quote=hit.quote,
                    score=hit.score,
                )
            passages = len(records)
            snapshot = await self.snapshot()
            for key in args.governance_keys:
                node = snapshot.node(key)
                ref = reference_record(node, call_id) if node else None
                if ref:
                    records.setdefault(ref["id"], ref)
            return EvidenceOutput(
                records=[dict(r) for r in records.values()],
                passages=passages,
                references=len(records) - passages,
            )

        out, _ = await self._run("retrieve_evidence", args, "Checking official sources", impl)
        return out

    async def analyze_document(
        self, args: AnalyzeDocumentInput
    ) -> tuple[DocumentAnalysisOutput, EvidenceRecord]:
        record: list[EvidenceRecord] = []

        async def impl(call_id: str) -> DocumentAnalysisOutput:
            analysis = await self.services.documents.analyze(args.document_id)
            record.append(document_record(analysis, call_id))
            return DocumentAnalysisOutput(
                document_id=analysis.document_id,
                kind=analysis.kind,
                holder=analysis.holder,
                status=analysis.status,
                needs_review=analysis.needs_review,
                cached=analysis.cached,
                fields=[f.__dict__ for f in analysis.fields],
                facts=[dict(f) for f in analysis.facts],
                review_task_ids=list(analysis.review_task_ids),
            )

        out, _ = await self._run("analyze_document", args, "Reading your document", impl)
        return out, record[0]

    # --- writes / preparations ----------------------------------------------------------
    async def generate_document(self, args: GenerateDocumentInput) -> GeneratedDocumentOutput:
        from app.agents.journey.drafting import draft  # local: drafting imports tools types

        async def impl(call_id: str) -> GeneratedDocumentOutput:
            body, provenance = await draft(self.services.llm, args)
            persist = args.persist and not self.context.simulation
            doc_id = f"preview:{args.kind}:{args.task_key or 'journey'}"
            if persist:
                doc_id = await self.services.store.save_generated_document(
                    journey_id=args.journey_id,
                    run_id=str(self.context.run_id),
                    kind=args.kind,
                    title=args.title,
                    body_markdown=body,
                    task_key=args.task_key,
                    provenance=provenance,
                )
                await emit(
                    self.context,
                    "document_generated",
                    document_id=doc_id,
                    kind=args.kind,
                    title=args.title,
                )
            return GeneratedDocumentOutput(
                id=doc_id,
                kind=args.kind,
                title=args.title,
                body_markdown=body,
                persisted=persist,
                provenance=provenance,
            )

        out, _ = await self._run("generate_document", args, f"Drafting {args.title}", impl)
        return out

    async def _prepare(
        self,
        kind: ActionKind,
        args: PrepareActionInput | PrepareAppointmentInput,
        parameters: dict[str, Any],
    ) -> ActionRecord:
        action_id = args.action_id or (
            f"preview:{kind.value}:{args.task_key}" if self.context.simulation else str(uuid4())
        )
        request = ActionRequest(
            kind=kind,
            service_key=args.service_key,
            title=args.title,
            action_id=action_id,
            task_key=args.task_key,
            parameters={
                "official_url": args.official_url,
                "channel_name": args.channel_name,
                "requires_uae_pass": args.requires_login,
                **parameters,
            },
            payload=args.payload,
        )
        adapter = self.services.actions.resolve(kind)
        prepared = await adapter.prepare(request)
        return action_record(action_id, prepared, list(args.evidence))

    async def prepare_action(self, args: PrepareActionInput) -> PreparedActionOutput:
        async def impl(call_id: str) -> PreparedActionOutput:
            record = await self._prepare(args.action_type, args, {})
            return PreparedActionOutput(action=dict(record))

        out, _ = await self._run("prepare_action", args, f"Preparing '{args.title}'", impl)
        return out

    async def prepare_appointment(self, args: PrepareAppointmentInput) -> PreparedActionOutput:
        async def impl(call_id: str) -> PreparedActionOutput:
            preferred = args.preferred_after or self.services.today().isoformat()
            record = await self._prepare(
                ActionKind.APPOINTMENT, args, {"preferred_after": preferred}
            )
            return PreparedActionOutput(action=dict(record))

        out, _ = await self._run(
            "prepare_appointment", args, f"Preparing a booking for '{args.title}'", impl
        )
        return out

    async def start_research(self, args: StartResearchInput) -> ResearchStartOutput:
        async def impl(call_id: str) -> ResearchStartOutput:
            if self.context.simulation:
                return ResearchStartOutput(
                    started=False, status="skipped", reason="what-if preview"
                )
            started = await self.services.research.start(journey_id=args.journey_id)
            if started is None:
                return ResearchStartOutput(
                    started=False, status="unavailable", reason="web research is not available"
                )
            return ResearchStartOutput(
                started=True, job_id=started.job_id, run_id=started.run_id, status=started.status
            )

        out, _ = await self._run("start_research", args, "Starting community research", impl)
        return out

    async def simulate_journey(
        self,
        args: SimulateJourneyInput,
        simulate: Callable[[str, list[dict[str, Any]]], Awaitable[dict[str, Any]]],
    ) -> SimulationOutput:
        async def impl(call_id: str) -> SimulationOutput:
            return SimulationOutput(result=await simulate(args.journey_id, args.changes))

        out, _ = await self._run("simulate_journey", args, "Simulating a what-if", impl)
        return out


def action_record(action_id: str, prepared: PreparedAction, evidence: list[str]) -> ActionRecord:
    request = prepared.request
    return ActionRecord(
        id=action_id,
        type=request.kind.value,
        status=ActionStatus.PREPARED.value,
        reversible=prepared.reversible,
        requires_human_approval=prepared.requires_approval,
        requires_user_authentication=prepared.requires_user_authentication,
        official_url=prepared.official_url,
        payload=dict(request.payload),
        evidence=evidence,
        title=request.title,
        summary=prepared.summary,
        consequences=list(prepared.consequences),
        task_key=request.task_key or "",
        service_key=request.service_key,
        adapter=prepared.adapter,
        is_simulated=prepared.is_simulated,
        simulation_label=prepared.simulation_label,
        approval_id=None,
        external_reference=None,
        confirmation_source=None,
        response_metadata={
            "demo_response": prepared.demo_response,
            "parameters": {k: v for k, v in request.parameters.items() if k != "official_url"},
        }
        if prepared.demo_response or request.parameters
        else {},
    )


def governance_context_from(
    out: GovernanceGraphOutput, roots: list[str], notes: list[str]
) -> GovernanceContext:
    return GovernanceContext(
        root_services=list(roots),
        nodes={n["key"]: GovNode(**n) for n in out.nodes},  # type: ignore[typeddict-item]
        edges=[GovEdge(**e) for e in out.edges],  # type: ignore[typeddict-item]
        notes=list(notes),
    )


def facts_from(out: UserGraphOutput | DocumentAnalysisOutput) -> dict[str, UserFact]:
    return {f["key"]: UserFact(**f) for f in out.facts}  # type: ignore[typeddict-item]


def json_preview(value: Any, limit: int = 400) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"
