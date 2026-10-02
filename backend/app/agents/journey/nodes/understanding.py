"""INTAKE -> PROFILE_ANALYSIS -> DOCUMENT_ANALYSIS: what does ADAPT know about the user?"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.instrumentation import report
from app.agents.journey.context import ctx
from app.agents.journey.facts import (
    GOAL_ESTABLISH_COMPANY,
    K_JURISDICTION,
    fact,
    goals_of,
    known,
)
from app.agents.journey.intake import (
    INTAKE_INSTRUCTIONS,
    INTAKE_PURPOSE,
    IntakeExtraction,
    facts_from_intake,
)
from app.agents.journey.review import (
    REVIEW_RESPONSE,
    DocumentCorrectionResponse,
    DocumentCorrectionReview,
    DocumentReviewItem,
    FieldReview,
    review_id_for,
    validate_response,
)
from app.agents.journey.spec import NodeSpec, journal, journey_node
from app.agents.journey.state import (
    ApprovalRequest,
    EvidenceRecord,
    UserFact,
    UserRequest,
)
from app.agents.journey.tools import (
    AnalyzeDocumentInput,
    GetUserGraphInput,
    JourneyTools,
    facts_from,
)
from app.agents.journey.vocab import NodeId, ReviewGate
from app.domain.enums import EvidenceKind

# --- INTAKE --------------------------------------------------------------------------------


class IntakeIn(TypedDict):
    request: UserRequest


class IntakeOut(TypedDict, total=False):
    user_facts: dict[str, UserFact]
    evidence: list[EvidenceRecord]


INTAKE = NodeSpec(
    id=NodeId.INTAKE,
    label="Understand your request",
    description="Reads what you said: goals, household, timing. Nothing is inferred.",
    kind="agent",
    input=IntakeIn,
    output=IntakeOut,
)


@journey_node(INTAKE)
async def intake(state: IntakeIn, runtime: Runtime[Any]) -> dict[str, Any]:
    request = state["request"]
    await report(runtime, "Reading your request", 0.2)
    extraction = await ctx(runtime).svc.llm.structured(
        purpose=INTAKE_PURPOSE,
        instructions=INTAKE_INSTRUCTIONS,
        input=request["text"],
        schema=IntakeExtraction,
        tier="fast",
    )
    facts = facts_from_intake(extraction)
    statement = EvidenceRecord(
        id="stmt:request",
        kind="user_statement",
        trust=EvidenceKind.AI_RECOMMENDATION.value,
        title="What you told ADAPT",
        source_url=None,
        authority=None,
        quote=request["text"][:1200],
        governance_key=None,
        document_id=None,
        tool_call_id=None,
        retrieved_at=None,
    )
    goals = ", ".join(goals_of(facts)) or "none yet"
    return {"user_facts": facts, "evidence": [statement], "_summary": f"Goals: {goals}"}


# --- PROFILE_ANALYSIS ------------------------------------------------------------------------


class ProfileIn(TypedDict):
    user_facts: dict[str, UserFact]


class ProfileOut(TypedDict, total=False):
    user_facts: dict[str, UserFact]


PROFILE_ANALYSIS = NodeSpec(
    id=NodeId.PROFILE_ANALYSIS,
    label="Understand your situation",
    description="Combines what you said with your saved profile, and notes what's assumed.",
    kind="tool",
    input=ProfileIn,
    output=ProfileOut,
)


@journey_node(PROFILE_ANALYSIS)
async def profile_analysis(state: ProfileIn, runtime: Runtime[Any]) -> dict[str, Any]:
    stated = state["user_facts"]
    graph = await JourneyTools(ctx(runtime)).get_user_graph(GetUserGraphInput())
    saved = facts_from(graph)
    # What the user just said wins over what was saved earlier; saved facts fill gaps.
    added: dict[str, UserFact] = {
        k: UserFact(**{**f, "source": f["source"] if f["source"] == "assumed" else "user_graph"})  # type: ignore[typeddict-item]
        for k, f in saved.items()
        if k not in stated
    }
    merged = {**stated, **added}
    assumptions: dict[str, UserFact] = {}
    if GOAL_ESTABLISH_COMPANY in goals_of(merged) and not known(merged, K_JURISDICTION):
        # Planning needs one licensing route; the assumption is surfaced as a risk.
        assumptions[K_JURISDICTION] = fact(
            K_JURISDICTION, "mainland", "assumed", source_ref="default", confidence=0.3
        )
    await report(runtime, f"{len(merged)} facts, {len(assumptions)} assumptions", 1.0)
    return {
        "user_facts": {**added, **assumptions},
        "_summary": f"{len(added)} saved facts used, {len(assumptions)} assumptions",
    }


# --- DOCUMENT_ANALYSIS (gate: document_correction) ---------------------------------------------


class DocumentsIn(TypedDict):
    run_id: str
    journey_id: str
    user_facts: dict[str, UserFact]
    document_ids: NotRequired[list[str]]


class DocumentsOut(TypedDict, total=False):
    user_facts: dict[str, UserFact]
    evidence: list[EvidenceRecord]
    approval_requests: list[ApprovalRequest]


DOCUMENT_ANALYSIS = NodeSpec(
    id=NodeId.DOCUMENT_ANALYSIS,
    label="Read your documents",
    description="Extracts fields from your documents; asks you to check uncertain values.",
    kind="agent",
    input=DocumentsIn,
    output=DocumentsOut,
)


@journey_node(DOCUMENT_ANALYSIS)
async def document_analysis(state: DocumentsIn, runtime: Runtime[Any]) -> dict[str, Any]:
    context = ctx(runtime)
    tools = JourneyTools(context)
    document_ids = state.get("document_ids") or []
    if not document_ids:
        return {"_summary": "No documents uploaded yet"}

    facts: dict[str, UserFact] = {}
    evidence: list[EvidenceRecord] = []
    analyses = []
    for index, document_id in enumerate(document_ids, start=1):
        # Idempotent: when this node re-runs after the correction gate, stored results
        # are returned without calling OCR again.
        analysis, record = await tools.analyze_document(
            AnalyzeDocumentInput(document_id=document_id)
        )
        analyses.append(analysis)
        evidence.append(record)
        facts.update(facts_from(analysis))
        await report(runtime, f"Read {analysis.kind.replace('_', ' ')}", index / len(document_ids))

    to_review = [a for a in analyses if a.needs_review]
    if not to_review or context.simulation:
        return {
            "user_facts": facts,
            "evidence": evidence,
            "_summary": f"{len(analyses)} documents read, none need checking",
        }

    review = DocumentCorrectionReview(
        review_id=review_id_for(state["run_id"], ReviewGate.DOCUMENT_CORRECTION),
        run_id=state["run_id"],
        journey_id=state["journey_id"],
        title="Check what ADAPT read from your documents",
        summary=f"{len(to_review)} document(s) have values ADAPT isn't sure about.",
        items=[
            DocumentReviewItem(
                document_id=a.document_id,
                kind=a.kind,
                holder=a.holder,
                review_task_ids=a.review_task_ids,
                fields=[FieldReview.model_validate(f) for f in a.fields],
            )
            for a in to_review
        ],
    )
    journal("approval_required", review.title, review.review_id)
    answer = interrupt(review.model_dump(mode="json"))

    response = REVIEW_RESPONSE.validate_python(answer)
    validate_response(review, response)
    assert isinstance(response, DocumentCorrectionResponse)
    outcome: dict[str, str] = {}
    for doc in response.documents:
        updated = await context.svc.documents.apply_corrections(
            doc.document_id, [c.model_dump() for c in doc.corrections], confirm=doc.confirm
        )
        if doc.confirm:
            facts.update({f["key"]: f for f in updated})
            outcome[doc.document_id] = f"confirmed ({len(doc.corrections)} corrected)"
        else:
            # Values the user rejected are not used for planning.
            reviewed = next(a for a in to_review if a.document_id == doc.document_id)
            for rejected in reviewed.facts:
                facts.pop(rejected["key"], None)
            outcome[doc.document_id] = "not used"
    journal("approval_resolved", f"{len(response.documents)} documents checked", review.review_id)
    return {
        "user_facts": facts,
        "evidence": evidence,
        "approval_requests": [
            ApprovalRequest(
                review_id=review.review_id,
                gate=ReviewGate.DOCUMENT_CORRECTION.value,
                status="resolved",
                item_ids=[i.document_id for i in review.items],
                outcome=outcome,
            )
        ],
        "_summary": f"{len(analyses)} documents read, {len(to_review)} checked by you",
    }
