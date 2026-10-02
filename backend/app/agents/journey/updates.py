"""Updating an existing plan without a new agent run: "I did this step" / "here's the answer".

Uses the same pure functions as the graph (planner, dependency analysis, eligibility,
risks), so a journey edited this way is exactly what a new run would plan from the same
facts. No language model is involved and nothing is executed.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.journey import eligibility
from app.agents.journey.facts import completed_fact_key, fact, subject_key, suffix
from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.nodes.human import compose_summary
from app.agents.journey.planning import analyse_dependencies, plan
from app.agents.journey.risks import RiskInputs, detect_risks
from app.agents.journey.simulation import ScenarioError, variable_for
from app.agents.journey.state import ActionRecord, UserFact
from app.agents.journey.vocab import TaskKind


class NothingToAnswer(ValueError):
    """The step isn't waiting for any fact ADAPT can record."""


def replan(
    snapshot: GovernanceSnapshot,
    previous: dict[str, Any],
    facts: dict[str, UserFact],
    actions: list[ActionRecord],
) -> dict[str, Any]:
    evidence = previous.get("evidence", [])
    passages: dict[str, list[str]] = {}
    for record in evidence:
        if record.get("kind") == "official_passage" and record.get("governance_key"):
            passages.setdefault(record["governance_key"], []).append(record["id"])
    result = plan(snapshot, facts, passages)
    analysis = analyse_dependencies(result.tasks)
    context = snapshot.context(result.root_services, result.notes)
    subjects = {
        t["node_key"]: t["subject"] for t in analysis.tasks if t["node_key"] in result.root_services
    }
    rules = eligibility.assess(context, facts, subjects)
    risks = detect_risks(
        RiskInputs(
            tasks=analysis.tasks,
            requirements=result.requirements,
            dependencies=analysis.dependencies,
            eligibility=rules,
            facts=facts,
            evidence=evidence,
            governance=context,
        )
    )
    updated = {
        **previous,
        "facts": list(facts.values()),
        "root_services": result.root_services,
        "coverage_notes": result.notes,
        "tasks": analysis.tasks,
        "dependencies": analysis.dependencies,
        "requirements": result.requirements,
        "eligibility": rules,
        "risks": risks,
        "actions": actions,
    }
    updated["summary"] = compose_summary({**updated, "goals": previous.get("goals", [])})
    return updated


def done_fact(task: dict[str, Any], journey_id: str) -> UserFact:
    """`completed.<step>` for the step's subject, as the user stated it."""
    key = completed_fact_key(task["node_key"], task["subject"])
    return fact(key, True, "user_stated", source_ref=f"journey:{journey_id}", confirmed=True)


def open_questions(task_key: str, plan_snapshot: dict[str, Any]) -> list[str]:
    """Facts a step is waiting on, most decisive first: eligibility rules, then conditional
    requirements and other missing information, then an off-platform requirement itself."""
    task = next((t for t in plan_snapshot.get("tasks", []) if t["key"] == task_key), None)
    keys: list[str] = []
    if task is not None:
        for result in plan_snapshot.get("eligibility", []):
            if result["service_key"] == task["node_key"]:
                keys += result["missing_facts"]
    for risk in plan_snapshot.get("risks", []):
        if task_key in risk["task_keys"] and risk["kind"] == "missing_information":
            keys += risk["fact_keys"]
    if task is not None and task["kind"] == TaskKind.REQUIREMENT and task["status"] != "done":
        keys.append(subject_key(task["subject"], f"meets.{suffix(task['node_key'])}"))
    return list(dict.fromkeys(keys))


def open_question(task_key: str, plan_snapshot: dict[str, Any], key: str | None = None) -> str:
    questions = open_questions(task_key, plan_snapshot)
    if key is not None:
        if key not in questions:
            raise NothingToAnswer(f"'{task_key}' isn't waiting for '{key}'")
        return key
    if not questions:
        raise NothingToAnswer(f"'{task_key}' isn't waiting for an answer")
    return questions[0]


def parse_answer(key: str, answer: str) -> Any:
    """Plain text -> a typed value, checked against the what-if variable catalogue."""
    text = answer.strip()
    lowered = text.lower()
    value: Any = text
    if lowered in ("yes", "true", "y", "done"):
        value = True
    elif lowered in ("no", "false", "n"):
        value = False
    else:
        number = re.fullmatch(r"(?:aed\s*)?([\d,]+(?:\.\d+)?)\s*(k)?", lowered)
        if number:
            parsed = float(number.group(1).replace(",", "")) * (1000 if number.group(2) else 1)
            value = int(parsed) if parsed.is_integer() else parsed
    try:
        variable = variable_for(key)
    except ScenarioError:
        return value  # a fact outside the catalogue (e.g. a spouse's age): keep as typed
    if variable.type == "number" and isinstance(value, int):
        value = float(value)
    return variable.coerce(value)
