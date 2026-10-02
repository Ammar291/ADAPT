"""What-if simulation: copy the journey, change an input, re-run only what it affects.

    base journey (checkpoint, read only)
        |  copy
        v
    apply_scenario --> [eligibility_analysis]? --> [requirement_planner]? --> ...
                       ... [action_preparation]? --> compare_scenarios --> END

* The active journey is never mutated. Its state is read from its checkpoint and deep
  copied into a new thread; the services are read-only (every storage write raises);
  drafts and actions are computed as previews only.
* A node re-runs only when a fact it declares (`NodeSpec.fact_keys`) changed, or when a
  state key it reads was changed by an earlier re-run. Changes are measured against the
  base journey's values, so a re-run that reproduces the base result stops propagation.
* The result lists changed_nodes, added_tasks, removed_tasks, changed_dependencies,
  changed_risks and a summary, and is stored on a separate scenario journey.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Overwrite
from pydantic import BaseModel, Field

from app.agents.journey.context import JourneyContext
from app.agents.journey.facts import fact, value_of
from app.agents.journey.nodes import SIMULATION_SEQUENCE
from app.agents.journey.spec import NodeSpec, journey_node, spec_of
from app.agents.journey.state import (
    STATE_REDUCERS,
    Dependency,
    JourneyState,
    Risk,
    Scenario,
    ScenarioChange,
    SimTrace,
    Task,
    UserFact,
)
from app.agents.journey.vocab import NodeId, TaskStatus
from app.agents.runner import CompleteHook, RunOutcome, execute_run
from app.domain.enums import RunKind

# --- the variables a what-if may change ----------------------------------------------------

VariableType = Literal["boolean", "enum", "number", "integer", "date"]


@dataclass(frozen=True)
class ScenarioVariable:
    key: str  # a fact key, or a pattern with `*` for documents / completed services
    label: str
    type: VariableType
    options: tuple[str, ...] = ()
    description: str = ""
    # How a summary reads a yes/no value: ("when true", "when false").
    phrases: tuple[str, str] | None = None

    def coerce(self, value: Any) -> Any:
        match self.type:
            case "boolean":
                if isinstance(value, bool):
                    return value
                if isinstance(value, str) and value.lower() in ("true", "false", "yes", "no"):
                    return value.lower() in ("true", "yes")
            case "enum":
                if value in self.options:
                    return value
            case "number":
                if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
                    return float(value)
            case "integer":
                if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 20:
                    return value
            case "date":
                try:
                    return date.fromisoformat(str(value)).isoformat()
                except ValueError:
                    pass
        raise ScenarioError(f"{self.label}: {value!r} is not a valid {self.type}")


SCENARIO_VARIABLES: tuple[ScenarioVariable, ...] = (
    ScenarioVariable(
        "household.move_with_spouse",
        "Your spouse moves to Abu Dhabi",
        "boolean",
        phrases=("your spouse moves with you", "you move without your spouse for now"),
    ),
    ScenarioVariable(
        "household.spouse_relocation", "When your spouse moves", "enum", ("with_user", "later")
    ),
    ScenarioVariable(
        "company.jurisdiction", "Where your company is licensed", "enum", ("mainland", "adgm")
    ),
    ScenarioVariable("finance.monthly_income_aed", "Your monthly income (AED)", "number"),
    ScenarioVariable(
        "housing.accommodation_provided",
        "Your employer provides accommodation",
        "boolean",
        phrases=("your employer provides accommodation", "your employer doesn't provide housing"),
    ),
    ScenarioVariable("household.children_count", "Children moving with you", "integer"),
    ScenarioVariable("household.planned_arrival_date", "When you arrive", "date"),
    ScenarioVariable("documents.*", "You already hold this document", "boolean"),
    ScenarioVariable("spouse.documents.*", "Your spouse already holds this document", "boolean"),
    ScenarioVariable("completed.*", "You have already completed this step", "boolean"),
)


class ScenarioError(ValueError):
    pass


class ScenarioChangeIn(BaseModel):
    key: str = Field(max_length=160)
    value: Any


def variable_for(key: str) -> ScenarioVariable:
    for variable in SCENARIO_VARIABLES:
        if variable.key == key:
            return variable
    for variable in SCENARIO_VARIABLES:
        prefix = variable.key[:-1]
        if variable.key.endswith("*") and key.startswith(prefix) and "." not in key[len(prefix) :]:
            return variable
    raise ScenarioError(f"'{key}' can't be changed in a what-if")


def validate_changes(
    changes: list[dict[str, Any]], facts: dict[str, UserFact]
) -> list[ScenarioChange]:
    """Known variables only. New variables are fine: a what-if may add a fact the base
    journey never had (e.g. an income when none was given)."""
    if not changes:
        raise ScenarioError("change at least one thing")
    seen: dict[str, ScenarioChange] = {}
    for raw in changes:
        change = ScenarioChangeIn.model_validate(raw)
        variable = variable_for(change.key)
        seen[change.key] = ScenarioChange(
            key=change.key,
            label=variable.label,
            previous=value_of(facts, change.key),
            value=variable.coerce(change.value),
        )
    return list(seen.values())


# --- building the copy ------------------------------------------------------------------------

COMPARED_KEYS = (
    "governance_context",
    "eligibility",
    "tasks",
    "requirements",
    "dependencies",
    "risks",
    "generated_documents",
    "actions",
)


def build_simulation_state(
    base: dict[str, Any],
    changes: list[dict[str, Any]],
    *,
    base_journey_id: str,
    base_run_id: str | None,
    scenario_journey_id: str,
    run_id: str,
) -> dict[str, Any]:
    """A deep copy of the base state, ready for the what-if graph. The base is untouched."""
    if not base.get("tasks"):
        raise ScenarioError("this journey has no plan to compare against yet")
    state = copy.deepcopy(base)
    validated = validate_changes(changes, state.get("user_facts", {}))
    changed_facts = [c["key"] for c in validated if c["previous"] != c["value"]]
    state.update(
        journey_id=scenario_journey_id,
        run_id=run_id,
        mode="simulation",
        events=[],
        sim_trace=[],
        approval_requests=[],
        research_job_ids=[],
        final_summary="",
        simulation={},
        scenario=Scenario(
            base_journey_id=base_journey_id,
            base_run_id=base_run_id,
            changes=validated,
            changed_facts=changed_facts,
            baseline={key: copy.deepcopy(base.get(key)) for key in COMPARED_KEYS},
        ),
    )
    return state


# --- comparison projections -----------------------------------------------------------------

Projection = Callable[[Any], Any]


def _planned(tasks: list[Task] | None) -> Any:
    return {
        t["key"]: (
            t["node_key"],
            t["subject"],
            t["kind"],
            t["title"],
            tuple(sorted(link["depends_on"] for link in t["links"])),
            t["status"] == TaskStatus.DONE,
        )
        for t in tasks or []
    }


def _scheduled(tasks: list[Task] | None) -> Any:
    return {t["key"]: (t["status"], t["level"]) for t in tasks or []}


def _by_id(records: list[dict[str, Any]] | None, *fields: str) -> Any:
    return {r["id"]: tuple(str(r.get(f)) for f in fields) for r in records or []}


# What each node is responsible for, per key, so an unchanged re-run compares equal.
PROJECTIONS: dict[tuple[NodeId, str], Projection] = {
    (NodeId.REQUIREMENT_PLANNER, "tasks"): _planned,
    (NodeId.DEPENDENCY_ANALYSIS, "tasks"): _scheduled,
}
DEFAULT_PROJECTIONS: dict[str, Projection] = {
    "governance_context": lambda c: (
        tuple((c or {}).get("root_services", [])),
        tuple(sorted((c or {}).get("nodes", {}))),
    ),
    "eligibility": lambda rs: {
        (r["rule_key"], r["subject"]): (r["status"], tuple(r["missing_facts"])) for r in rs or []
    },
    "requirements": lambda rs: _by_id(rs, "status", "satisfied_by"),
    "dependencies": lambda ds: _by_id(ds, "kind", "any_of"),
    "risks": lambda rs: _by_id(rs, "severity", "title", "detail"),
    "generated_documents": lambda ds: {(d["kind"], d["task_key"]) for d in ds or []},
    "actions": lambda acts: {
        (a["type"], a["task_key"], a["status"] == "blocked") for a in acts or []
    },
    "evidence": lambda es: {e["id"] for e in es or []},
}


def project(node: NodeId, key: str, value: Any) -> Any:
    fn = PROJECTIONS.get((node, key)) or DEFAULT_PROJECTIONS.get(key)
    return fn(value) if fn else value


# --- the what-if graph -----------------------------------------------------------------------


class ApplyIn(TypedDict):
    scenario: Scenario
    user_facts: dict[str, UserFact]


class ApplyOut(TypedDict, total=False):
    user_facts: dict[str, UserFact]


APPLY_SCENARIO = NodeSpec(
    id=NodeId.APPLY_SCENARIO,
    label="Apply your what-if",
    description="Copies your plan and changes the assumption you picked. "
    "Your real plan is untouched.",
    kind="tool",
    input=ApplyIn,
    output=ApplyOut,
    lane=1,
)


@journey_node(APPLY_SCENARIO)
async def apply_scenario(state: ApplyIn, runtime: Runtime[Any]) -> dict[str, Any]:
    overrides = {
        c["key"]: fact(
            c["key"], c["value"], "scenario", source_ref="what_if", confidence=1.0, confirmed=True
        )
        for c in state["scenario"]["changes"]
    }
    labels = "; ".join(
        f"{c['label']}: {c['previous']!r} -> {c['value']!r}" for c in state["scenario"]["changes"]
    )
    return {"user_facts": overrides, "_summary": labels}


class CompareIn(TypedDict):
    scenario: Scenario
    tasks: list[Task]
    dependencies: list[Dependency]
    risks: list[Risk]
    sim_trace: list[SimTrace]
    journey_id: str


class CompareOut(TypedDict, total=False):
    simulation: dict[str, Any]
    final_summary: str


COMPARE_SCENARIOS = NodeSpec(
    id=NodeId.COMPARE_SCENARIOS,
    label="Compare with your plan",
    description="Shows what the change adds, removes and puts at risk.",
    kind="agent",
    input=CompareIn,
    output=CompareOut,
    lane=1,
)

_LABELS = {spec_of(n).id.value: spec_of(n).label for n in SIMULATION_SEQUENCE}


def diff(
    scenario: Scenario,
    tasks: list[Task],
    dependencies: list[Dependency],
    risks: list[Risk],
    trace: list[SimTrace],
) -> dict[str, Any]:
    base = scenario["baseline"]
    before_tasks = {t["key"]: t for t in base.get("tasks") or []}
    after_tasks = {t["key"]: t for t in tasks}

    def brief(t: Task) -> dict[str, str]:
        return {"key": t["key"], "title": t["title"], "area": t["area"]}

    added = [brief(after_tasks[k]) for k in sorted(after_tasks.keys() - before_tasks.keys())]
    removed = [brief(before_tasks[k]) for k in sorted(before_tasks.keys() - after_tasks.keys())]

    def edges(deps: list[Dependency] | None) -> dict[tuple[str, str], str]:
        return {(d["task"], d["depends_on"]): d["kind"] for d in deps or []}

    old_edges, new_edges = edges(base.get("dependencies")), edges(dependencies)
    changed_dependencies = [
        {"source": s, "target": t, "relation": new_edges[(s, t)], "change": "added"}
        for s, t in sorted(new_edges.keys() - old_edges.keys())
    ] + [
        {"source": s, "target": t, "relation": old_edges[(s, t)], "change": "removed"}
        for s, t in sorted(old_edges.keys() - new_edges.keys())
    ]

    old_risks = {r["id"]: r for r in base.get("risks") or []}
    new_risks = {r["id"]: r for r in risks}

    def risk_brief(r: Risk, change: str) -> dict[str, str]:
        return {
            "id": r["id"],
            "kind": r["kind"],
            "severity": r["severity"],
            "title": r["title"],
            "change": change,
        }

    changed_risks = (
        [risk_brief(new_risks[k], "added") for k in sorted(new_risks.keys() - old_risks.keys())]
        + [risk_brief(old_risks[k], "removed") for k in sorted(old_risks.keys() - new_risks.keys())]
        + [
            risk_brief(new_risks[k], "changed")
            for k in sorted(new_risks.keys() & old_risks.keys())
            if (new_risks[k]["severity"], new_risks[k]["detail"])
            != (old_risks[k]["severity"], old_risks[k]["detail"])
        ]
    )
    changed_nodes = [
        {
            "node": t["node"],
            "label": _LABELS.get(t["node"], t["node"]),
            "changed_keys": t["changed_keys"],
        }
        for t in trace
        if t["changed_keys"]
    ]
    result = {
        "base_journey_id": scenario["base_journey_id"],
        "changes": [
            {"key": c["key"], "label": c["label"], "from": c["previous"], "to": c["value"]}
            for c in scenario["changes"]
        ],
        "rerun_nodes": [t["node"] for t in trace],
        "changed_nodes": changed_nodes,
        "added_tasks": added,
        "removed_tasks": removed,
        "changed_dependencies": changed_dependencies,
        "changed_risks": changed_risks,
    }
    result["summary"] = summarize(result)
    return result


def _phrase(change: dict[str, Any]) -> str:
    variable = next((v for v in SCENARIO_VARIABLES if v.key == change["key"]), None)
    if variable and variable.phrases and isinstance(change["to"], bool):
        return variable.phrases[0 if change["to"] else 1]
    label = str(change["label"])
    return f"{label[:1].lower()}{label[1:]}: {_show(change['to'])}"


def summarize(result: dict[str, Any]) -> str:
    changes = "; ".join(_phrase(c) for c in result["changes"])
    if not result["rerun_nodes"]:
        return f"If {changes}: nothing in your plan changes."
    parts = [f"If {changes}:"]
    if result["added_tasks"]:
        titles = _list(t["title"] for t in result["added_tasks"])
        parts.append(f"{len(result['added_tasks'])} step(s) added ({titles}).")
    if result["removed_tasks"]:
        titles = _list(t["title"] for t in result["removed_tasks"])
        parts.append(f"{len(result['removed_tasks'])} step(s) no longer needed ({titles}).")
    if result["changed_dependencies"]:
        parts.append(f"{len(result['changed_dependencies'])} dependency change(s).")
    new = [r for r in result["changed_risks"] if r["change"] == "added"]
    gone = [r for r in result["changed_risks"] if r["change"] == "removed"]
    if new or gone:
        parts.append(f"{len(new)} new risk(s), {len(gone)} resolved.")
    if len(parts) == 1:
        parts.append("the same steps and risks as your plan.")
    parts.append(
        f"ADAPT re-checked {len(result['rerun_nodes'])} stage(s); your plan was not changed."
    )
    return " ".join(parts)


def _show(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _list(items: Any, limit: int = 3) -> str:
    items = list(items)
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


@journey_node(COMPARE_SCENARIOS)
async def compare_scenarios(state: CompareIn, runtime: Runtime[Any]) -> dict[str, Any]:
    result = diff(
        state["scenario"], state["tasks"], state["dependencies"], state["risks"], state["sim_trace"]
    )
    result["scenario_journey_id"] = state["journey_id"]
    return {"simulation": result, "final_summary": result["summary"], "_summary": result["summary"]}


def _rerun(node: Any) -> Any:
    """Wrap a journey node for the what-if graph: record what its re-run changed."""
    spec = spec_of(node)

    async def run(state: dict[str, Any], runtime: Runtime[Any]) -> dict[str, Any]:
        update = await node(state, runtime)
        baseline = state["scenario"]["baseline"]
        changed = []
        for key in sorted(spec.writes):
            if key not in update:
                continue
            before = baseline.get(key) if key in baseline else state.get(key)
            after = update[key]
            if key in STATE_REDUCERS and key not in ("actions",):
                after = STATE_REDUCERS[key](state.get(key), after)
            if project(spec.id, key, before) != project(spec.id, key, after):
                changed.append(key)
        if "actions" in update:  # previews replace the copied actions, never merge with them
            update["actions"] = Overwrite(update["actions"])
        return {**update, "sim_trace": [SimTrace(node=spec.id.value, changed_keys=changed)]}

    run.__name__ = spec.id.value
    return run


def needs_rerun(spec: NodeSpec, scenario: Scenario, trace: list[SimTrace]) -> bool:
    if "user_facts" in spec.reads and any(
        spec.depends_on_fact(k) for k in scenario["changed_facts"]
    ):
        return True
    changed = {key for entry in trace for key in entry["changed_keys"]}
    return bool((spec.reads - {"user_facts"}) & changed)


def _router(after: int) -> Callable[[dict[str, Any]], str]:
    def route(state: dict[str, Any]) -> str:
        for node in SIMULATION_SEQUENCE[after + 1 :]:
            spec = spec_of(node)
            if needs_rerun(spec, state["scenario"], state.get("sim_trace", [])):
                return spec.id.value
        return NodeId.COMPARE_SCENARIOS.value

    return route


def build_simulation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(JourneyState, context_schema=JourneyContext)
    graph.add_node(NodeId.APPLY_SCENARIO.value, apply_scenario)
    for node in SIMULATION_SEQUENCE:
        graph.add_node(spec_of(node).id.value, _rerun(node))
    graph.add_node(NodeId.COMPARE_SCENARIOS.value, compare_scenarios)
    graph.add_edge(START, NodeId.APPLY_SCENARIO.value)
    names = [spec_of(n).id.value for n in SIMULATION_SEQUENCE]
    sources = [NodeId.APPLY_SCENARIO.value, *names]
    for position, source in enumerate(sources):
        targets = [*names[position:], NodeId.COMPARE_SCENARIOS.value]
        graph.add_conditional_edges(source, _router(position - 1), targets)
    graph.add_edge(NodeId.COMPARE_SCENARIOS.value, END)
    return graph.compile(checkpointer=checkpointer)


SIMULATION_NODE_SPECS: tuple[NodeSpec, ...] = (
    APPLY_SCENARIO,
    *(spec_of(n) for n in SIMULATION_SEQUENCE),
    COMPARE_SCENARIOS,
)


# --- running a what-if ------------------------------------------------------------------------


def simulation_context(context: JourneyContext) -> JourneyContext:
    """The same principal and event sink, with read-only services and preview mode."""
    return dataclasses.replace(context, services=context.svc.read_only(), simulation=True)


async def run_simulation(
    *,
    journey_graph: CompiledStateGraph[Any, Any, Any, Any],
    simulation_graph: CompiledStateGraph[Any, Any, Any, Any],
    context: JourneyContext,
    base_thread_id: str,
    base_journey_id: str,
    base_run_id: str | None,
    scenario_journey_id: str,
    thread_id: str,
    changes: list[dict[str, Any]],
    on_complete: CompleteHook | None = None,
    base_overrides: dict[str, Any] | None = None,
) -> RunOutcome:
    """Copy the base journey's checkpointed state and run the what-if graph on the copy.

    The base thread is only read (`aget_state`), never updated, so the active journey
    and its checkpoint history are unchanged whatever the scenario does.
    """
    base = await journey_graph.aget_state({"configurable": {"thread_id": base_thread_id}})
    # The persisted plan wins over the checkpoint: it includes edits made since the run
    # (steps marked done, answers), and it is what the user sees as "my plan".
    state = build_simulation_state(
        {**dict(base.values or {}), **(base_overrides or {})},
        changes,
        base_journey_id=base_journey_id,
        base_run_id=base_run_id,
        scenario_journey_id=scenario_journey_id,
        run_id=str(context.run_id),
    )
    return await execute_run(
        graph=simulation_graph,
        ctx=simulation_context(context),
        kind=RunKind.WHAT_IF,
        thread_id=thread_id,
        graph_input=state,
        summary_key="final_summary",
        on_complete=on_complete,
    )
