"""ELIGIBILITY_ANALYSIS -> REQUIREMENT_PLANNER -> DEPENDENCY_ANALYSIS -> RISK_DETECTION.

All four are deterministic reasoning over the governance graph (see planning.py,
eligibility.py and risks.py). Language models are not used to decide what the rules are.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.runtime import Runtime

from app.agents.instrumentation import report
from app.agents.journey import eligibility as rules
from app.agents.journey.context import ctx
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.planning import (
    GOAL_ROOTS,
    LICENCE_BY_JURISDICTION,
    analyse_dependencies,
    plan,
    select_roots,
)
from app.agents.journey.risks import RiskInputs, detect_risks
from app.agents.journey.spec import NodeSpec, journey_node
from app.agents.journey.state import (
    Dependency,
    EligibilityResult,
    EvidenceRecord,
    GovernanceContext,
    Requirement,
    Risk,
    Task,
    UserFact,
)
from app.agents.journey.tools import (
    EvidenceOutput,
    GetGovernanceGraphInput,
    JourneyTools,
    RetrieveEvidenceInput,
)
from app.agents.journey.vocab import NodeId, RiskSeverity, TaskStatus

# Facts that decide which services apply and whose rules are checked (eligibility).
PLANNING_FACTS = frozenset(
    {"goals", "profile.*", "household.*", "company.*", "finance.*", "housing.*"}
)
# Facts that decide which steps exist and how they're satisfied (requirement planning).
# Income and accommodation only feed eligibility rules, so they're deliberately absent.
STEP_FACTS = frozenset(
    {
        "goals",
        "profile.*",
        "household.move_with_spouse",
        "household.has_spouse",
        "company.*",
        "documents.*",
        "*.documents.*",
        "completed.*",
        "*.completed.*",
        "meets.*",
        "*.meets.*",
    }
)


def _records(out: EvidenceOutput) -> list[EvidenceRecord]:
    return [EvidenceRecord(**r) for r in out.records]  # type: ignore[typeddict-item]


# --- ELIGIBILITY_ANALYSIS ----------------------------------------------------------------


class EligibilityIn(TypedDict):
    user_facts: dict[str, UserFact]


class EligibilityOut(TypedDict, total=False):
    governance_context: GovernanceContext
    eligibility: list[EligibilityResult]
    evidence: list[EvidenceRecord]


ELIGIBILITY_ANALYSIS = NodeSpec(
    id=NodeId.ELIGIBILITY_ANALYSIS,
    label="Check what applies to you",
    description="Finds the official services for your goals and checks eligibility rules.",
    kind="tool",
    input=EligibilityIn,
    output=EligibilityOut,
    fact_keys=PLANNING_FACTS,
)


@journey_node(ELIGIBILITY_ANALYSIS)
async def eligibility_analysis(state: EligibilityIn, runtime: Runtime[Any]) -> dict[str, Any]:
    facts = state["user_facts"]
    tools = JourneyTools(ctx(runtime))
    # Every root any goal could need (plus licence fallbacks); root selection then keeps
    # the ones the graph actually contains.
    candidates = sorted(
        {key for roots in GOAL_ROOTS.values() for key, _ in roots}
        | set(LICENCE_BY_JURISDICTION.values())
    )
    graph = await tools.get_governance_graph(GetGovernanceGraphInput(root_keys=candidates))
    snapshot = GovernanceSnapshot.of(graph.nodes, graph.edges)  # type: ignore[arg-type]
    selection = select_roots(snapshot, facts)
    roots = [r[0] for r in selection.roots]
    context = snapshot.context(roots, selection.notes)
    await report(runtime, f"{len(roots)} services match your goals", 0.4)

    subjects = {key: subject for key, subject, _, _ in selection.roots}
    results = rules.assess(context, facts, subjects)
    evidence: list[EvidenceRecord] = []
    if results:
        found = await tools.retrieve_evidence(
            RetrieveEvidenceInput(
                query=" ".join(sorted({r["explanation"].split(":")[0] for r in results})),
                governance_keys=sorted({r["rule_key"] for r in results}),
            )
        )
        evidence = _records(found)
        passages = {
            e["governance_key"]: e["id"] for e in evidence if e["kind"] == "official_passage"
        }
        for result in results:
            if result["rule_key"] in passages:
                result["evidence_ids"].append(passages[result["rule_key"]])
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("met", "unmet", "unknown")}
    return {
        "governance_context": context,
        "eligibility": results,
        "evidence": evidence,
        "_summary": f"{len(roots)} services; rules: {counts['met']} met, "
        f"{counts['unmet']} not met, {counts['unknown']} to check",
    }


# --- REQUIREMENT_PLANNER -----------------------------------------------------------------------


class PlannerIn(TypedDict):
    user_facts: dict[str, UserFact]
    governance_context: GovernanceContext


class PlannerOut(TypedDict, total=False):
    tasks: list[Task]
    requirements: list[Requirement]
    evidence: list[EvidenceRecord]


REQUIREMENT_PLANNER = NodeSpec(
    id=NodeId.REQUIREMENT_PLANNER,
    label="Plan the steps",
    description="Turns the official requirements into your steps. Every step cites its source.",
    kind="agent",
    input=PlannerIn,
    output=PlannerOut,
    fact_keys=STEP_FACTS,
)


@journey_node(REQUIREMENT_PLANNER)
async def requirement_planner(state: PlannerIn, runtime: Runtime[Any]) -> dict[str, Any]:
    facts, context = state["user_facts"], state["governance_context"]
    snapshot = GovernanceSnapshot.from_context(context)
    draft = plan(snapshot, facts)
    await report(runtime, f"{len(draft.tasks)} steps from {len(draft.root_services)} goals", 0.5)
    keys = sorted(
        {t["node_key"] for t in draft.tasks} | {r["node_key"] for r in draft.requirements}
    )
    found = await JourneyTools(ctx(runtime)).retrieve_evidence(
        RetrieveEvidenceInput(
            query=" ".join(t["title"] for t in draft.tasks)[:480] or "requirements",
            governance_keys=keys,
        )
    )
    evidence = _records(found)
    index: dict[str, list[str]] = {}
    for record in evidence:
        if record["kind"] == "official_passage" and record["governance_key"]:
            index.setdefault(record["governance_key"], []).append(record["id"])
    final = plan(snapshot, facts, index) if index else draft
    missing = sum(1 for r in final.requirements if r["status"] == "missing")
    return {
        "tasks": final.tasks,
        "requirements": final.requirements,
        "evidence": evidence,
        "_summary": f"{len(final.tasks)} steps, {len(final.requirements)} requirements "
        f"({missing} missing)",
    }


# --- DEPENDENCY_ANALYSIS -----------------------------------------------------------------------


class DependencyIn(TypedDict):
    tasks: list[Task]


class DependencyOut(TypedDict, total=False):
    tasks: list[Task]
    dependencies: list[Dependency]


DEPENDENCY_ANALYSIS = NodeSpec(
    id=NodeId.DEPENDENCY_ANALYSIS,
    label="Order the steps",
    description="Works out what must happen first and what you can start today.",
    kind="tool",
    input=DependencyIn,
    output=DependencyOut,
    fact_keys=frozenset(),
)


@journey_node(DEPENDENCY_ANALYSIS)
async def dependency_analysis(state: DependencyIn, runtime: Runtime[Any]) -> dict[str, Any]:
    analysis = analyse_dependencies(state["tasks"])
    ready = sum(1 for t in analysis.tasks if t["status"] == TaskStatus.READY)
    stages = max((t["level"] for t in analysis.tasks), default=-1) + 1
    await report(runtime, f"{ready} steps can start now", 1.0)
    summary = f"{stages} stages, {ready} ready now"
    if analysis.cycles:
        summary += f", {len(analysis.cycles)} ordering conflict(s)"
    return {"tasks": analysis.tasks, "dependencies": analysis.dependencies, "_summary": summary}


# --- RISK_DETECTION --------------------------------------------------------------------------


class RiskIn(TypedDict):
    tasks: list[Task]
    requirements: list[Requirement]
    dependencies: list[Dependency]
    eligibility: list[EligibilityResult]
    user_facts: dict[str, UserFact]
    evidence: list[EvidenceRecord]
    governance_context: GovernanceContext


class RiskOut(TypedDict, total=False):
    risks: list[Risk]


RISK_DETECTION = NodeSpec(
    id=NodeId.RISK_DETECTION,
    label="Spot risks",
    description="Finds missing documents and information, timing and ordering problems.",
    kind="agent",
    input=RiskIn,
    output=RiskOut,
)


@journey_node(RISK_DETECTION)
async def risk_detection(state: RiskIn, runtime: Runtime[Any]) -> dict[str, Any]:
    risks = detect_risks(
        RiskInputs(
            tasks=state["tasks"],
            requirements=state["requirements"],
            dependencies=state["dependencies"],
            eligibility=state["eligibility"],
            facts=state["user_facts"],
            evidence=state["evidence"],
            governance=state["governance_context"],
        )
    )
    blocking = sum(1 for r in risks if r["severity"] == RiskSeverity.BLOCKING)
    await report(runtime, f"{len(risks)} risks found", 1.0)
    return {"risks": risks, "_summary": f"{len(risks)} risks ({blocking} blocking)"}
