"""Mapping the agent's plan onto stored journey nodes and edges (pure; no DB).

One journey node per task. Its status merges the planner's view (ready / blocked / done)
with what happened to its action (awaiting approval, handed off, submitted...). Blockers,
the facts it relied on (`basis`, fact ids only) and its official provenance come along.
"""

from __future__ import annotations

from typing import Any

from app.agents.journey.eligibility import FACT_LABELS, fact_question
from app.agents.journey.state import ActionRecord, Requirement, Risk, Task
from app.agents.journey.vocab import TaskStatus
from app.domain.enums import ActionStatus, StepCategory, StepStatus
from app.domain.provenance import Provenance

KIND_BY_TASK = {"service": "task", "requirement": "requirement", "appointment": "appointment"}
_ACTION_STEP = {
    ActionStatus.AWAITING_APPROVAL: StepStatus.AWAITING_APPROVAL,
    ActionStatus.APPROVED: StepStatus.IN_PROGRESS,
    ActionStatus.HANDOFF_REQUIRED: StepStatus.HANDOFF,
    ActionStatus.SUBMITTED: StepStatus.IN_PROGRESS,
    ActionStatus.COMPLETED: StepStatus.DONE,
}
_RISK_BLOCKER = {
    "missing_information": "missing_info",
    "eligibility_gap": "eligibility",
    "missing_user_document": "missing_document",
}


def step_status(
    task: Task, requirements: list[Requirement], action: ActionRecord | None
) -> StepStatus:
    if (
        action is not None
        and action["status"] == ActionStatus.COMPLETED
        and (
            action.get("is_simulated")
            or action.get("confirmation_source") != "adapter"
            or not str(action.get("external_reference") or "").strip()
        )
    ):
        return StepStatus.HANDOFF if action.get("official_url") else StepStatus.READY
    if task["status"] == TaskStatus.DONE:
        if action is not None:
            return _ACTION_STEP.get(ActionStatus(action["status"]), StepStatus.READY)
        return StepStatus.DONE
    if task["status"] == TaskStatus.NOT_APPLICABLE:
        return StepStatus.NOT_APPLICABLE
    if task["status"] == TaskStatus.BLOCKED:
        return StepStatus.BLOCKED
    if action is not None and ActionStatus(action["status"]) in _ACTION_STEP:
        return _ACTION_STEP[ActionStatus(action["status"])]
    if any(r["status"] == "missing" for r in requirements):
        return StepStatus.NEEDS_INFO
    return StepStatus.READY


def blockers(
    task: Task, tasks: dict[str, Task], requirements: list[Requirement], risks: list[Risk]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for prerequisite in task["depends_on"]:
        other = tasks.get(prerequisite)
        if other and other["status"] != TaskStatus.DONE:
            out.append(
                {
                    "kind": "dependency",
                    "message": f"Waits for: {other['title']}",
                    "resolution": None,
                    "related_node_key": prerequisite,
                    "related_document": None,
                }
            )
    for req in requirements:
        if req["status"] == "missing":
            out.append(
                {
                    "kind": "missing_document",
                    "message": f"{req['label']} is needed",
                    "resolution": "Upload or photograph it in Documents.",
                    "related_node_key": None,
                    "related_document": req["node_key"],
                }
            )
    for risk in risks:
        kind = _RISK_BLOCKER.get(risk["kind"])
        if kind and task["key"] in risk["task_keys"] and kind != "missing_document":
            out.append(
                {
                    "kind": kind,
                    "message": risk["title"],
                    "resolution": risk["resolution"],
                    "related_node_key": None,
                    "related_document": None,
                }
            )
    return out


def basis(task: Task, facts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Which user facts the step relied on: keys and fact ids only, never values."""
    return [
        {
            "key": key,
            "label": FACT_LABELS.get(key, key.replace(".", " ").replace("_", " ")),
            "fact_refs": list((facts.get(key) or {}).get("fact_ids", [])),
        }
        for key in task["fact_keys"]
    ]


def provenance(node: dict[str, Any] | None) -> dict[str, Any]:
    raw = (node or {}).get("provenance")
    if raw:
        try:
            return Provenance.model_validate(raw).model_dump(mode="json")
        except ValueError:
            pass
    return Provenance.ai("Derived by ADAPT; no official citation attached.").model_dump(mode="json")


def category(area: str) -> StepCategory:
    try:
        return StepCategory(area)
    except ValueError:
        return StepCategory.DAILY_LIFE


def open_questions(task_key: str, plan: dict[str, Any]) -> list[str]:
    from app.agents.journey.updates import open_questions as questions  # avoid an import cycle

    return questions(task_key, plan)


def node_rows(
    plan: dict[str, Any], governance_nodes: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Journey-node rows (without ids/ownership) for every task in a plan snapshot."""
    tasks: dict[str, Task] = {t["key"]: t for t in plan.get("tasks", [])}
    requirements = plan.get("requirements", [])
    risks: list[Risk] = plan.get("risks", [])
    actions = {a["task_key"]: a for a in plan.get("actions", [])}
    facts = {f["key"]: f for f in plan.get("facts", [])}
    rows = []
    for task in tasks.values():
        reqs = [r for r in requirements if r["task_key"] == task["key"]]
        action = actions.get(task["key"])
        rows.append(
            {
                "key": task["key"],
                "kind": KIND_BY_TASK.get(task["kind"], "task"),
                "title": task["title"][:300],
                "summary": task["summary"],
                "category": category(task["area"]),
                "status": step_status(task, reqs, action),
                "position": task["order"],
                "governance_key": task["node_key"],
                "authority": task["authority"],
                "official_url": task["official_url"],
                "blockers": blockers(task, tasks, reqs, risks),
                "provenance": provenance(governance_nodes.get(task["node_key"])),
                "basis": basis(task, facts),
                "details": {
                    "subject": task["subject"],
                    "task_kind": task["kind"],
                    "level": task["level"],
                    "why_it_matters": task["why"],
                    "action_type": task["action_type"],
                    "action_id": action["id"] if action else None,
                    "requires_login": task["requires_login"],
                    "portal": task["portal"],
                    "requirements": [
                        {
                            "label": r["label"],
                            "status": r["status"],
                            "satisfied_by": r["satisfied_by"],
                        }
                        for r in reqs
                    ],
                    "evidence_ids": task["evidence_ids"],
                    "risk_ids": [r["id"] for r in risks if task["key"] in r["task_keys"]],
                    "fact_ids": task["fact_ids"],
                    "open_questions": [
                        {
                            "key": k,
                            "label": FACT_LABELS.get(k, k.replace(".", " ").replace("_", " ")),
                            "question": fact_question(k),
                        }
                        for k in open_questions(task["key"], plan)
                    ],
                },
            }
        )
    return rows


def edge_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source": dep["task"],  # the dependent step
            "target": dep["depends_on"],  # what it waits for
            "properties": {"kind": dep["kind"], "via": dep["via"], "any_of": dep["any_of"]},
        }
        for dep in plan.get("dependencies", [])
    ]


def assumptions(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        f["key"]: {
            "value": f["value"],
            "source": f["source"],
            "confidence": f["confidence"],
            "confirmed": f["confirmed"],
            "label": FACT_LABELS.get(f["key"], f["key"]),
        }
        for f in plan.get("facts", [])
    }
