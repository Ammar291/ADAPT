"""Risk detection over a planned journey (pure: no DB, no LLM).

A risk never asserts a new government obligation. Each one points at something concrete:
a governance node, a planned task derived from one, or a fact ADAPT doesn't know.

* missing_user_document      a required document the user hasn't provided and no planned
                             task produces
* missing_information        an assumption ADAPT had to make, or a fact a rule needs
* missing_source_evidence    a requirement backed only by a curated summary / no citation
* timeline_dependency        a goal that can't start until a chain of earlier steps is done
* incompatible_task_ordering a dependency cycle, or a step reported done before its
                             prerequisites
* external_login_required    steps the user must complete with their own login (UAE PASS)
* eligibility_gap            a machine-checkable eligibility rule the stated facts don't meet
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.journey.facts import (
    K_ARRIVAL,
    K_ARRIVAL_TEXT,
    K_MOVE_WITH_SPOUSE,
    K_SPOUSE_RELOCATION,
    fact_ids_for,
    value_of,
)
from app.agents.journey.planning import prerequisite_chain, reference_evidence_id
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
from app.agents.journey.vocab import RiskKind, RiskSeverity, Subject, TaskStatus

ASSUMPTION_LABELS: dict[str, tuple[str, str]] = {
    "household.move_with_spouse": (
        "We assumed your spouse is moving to Abu Dhabi with you",
        "Tell ADAPT whether your spouse is moving, and when. Sponsorship steps depend on it.",
    ),
    "company.jurisdiction": (
        "We assumed your company will be licensed on the Abu Dhabi mainland",
        "Tell ADAPT if you prefer the ADGM free zone. The licensing steps are different.",
    ),
}
_SEVERITY_ORDER = {RiskSeverity.BLOCKING: 0, RiskSeverity.WARNING: 1, RiskSeverity.INFO: 2}
LONG_CHAIN = 4  # steps in sequence before a timeline is worth flagging


@dataclass
class RiskInputs:
    tasks: list[Task]
    requirements: list[Requirement]
    dependencies: list[Dependency]
    eligibility: list[EligibilityResult]
    facts: dict[str, UserFact]
    evidence: list[EvidenceRecord]
    governance: GovernanceContext


def _risk(
    kind: RiskKind,
    severity: RiskSeverity,
    ident: str,
    title: str,
    detail: str,
    *,
    resolution: str | None = None,
    task_keys: list[str] | None = None,
    fact_keys: list[str] | None = None,
    governance_keys: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> Risk:
    return Risk(
        id=f"risk:{kind.value}:{ident}",
        kind=kind.value,
        severity=severity.value,
        title=title,
        detail=detail,
        resolution=resolution,
        task_keys=sorted(set(task_keys or [])),
        fact_keys=sorted(set(fact_keys or [])),
        governance_keys=sorted(set(governance_keys or [])),
        evidence_ids=list(dict.fromkeys(evidence_ids or [])),
        fact_ids=[],
    )


def _whose(subject: str) -> str:
    return "Your" if subject == Subject.SELF else f"Your {subject}'s"


def missing_documents(inputs: RiskInputs) -> list[Risk]:
    tasks = {t["key"]: t for t in inputs.tasks}
    grouped: dict[tuple[str, str], list[Requirement]] = {}
    for req in inputs.requirements:
        task = tasks.get(req["task_key"])
        open_task = task is None or task["status"] != TaskStatus.DONE
        if req["status"] == "missing" and req["node_type"] == "document" and open_task:
            grouped.setdefault((req["subject"], req["node_key"]), []).append(req)
    risks = []
    for (subject, node_key), reqs in sorted(grouped.items()):
        label = reqs[0]["label"]
        needed_by = [r["task_key"] for r in reqs]
        # A ready submission can't go ahead without it; elsewhere the user can bring it.
        blocking = any(
            tasks[k]["status"] == TaskStatus.READY
            and tasks[k]["action_type"] == "document_submission"
            for k in needed_by
            if k in tasks
        )
        titles = ", ".join(tasks[k]["title"] for k in needed_by if k in tasks)
        risks.append(
            _risk(
                RiskKind.MISSING_USER_DOCUMENT,
                RiskSeverity.BLOCKING if blocking else RiskSeverity.WARNING,
                f"{subject}:{node_key}",
                f"{_whose(subject)} {label.lower()} is needed",
                f"Needed for: {titles}. ADAPT hasn't seen it yet.",
                resolution="Upload or photograph it in Documents so ADAPT can check it.",
                task_keys=needed_by,
                fact_keys=[k for r in reqs for k in r["fact_keys"]],
                governance_keys=[node_key],
                evidence_ids=[reference_evidence_id(node_key)],
            )
        )
    return risks


def missing_information(inputs: RiskInputs) -> list[Risk]:
    risks = []
    for key, item in sorted(inputs.facts.items()):
        if item["source"] != "assumed":
            continue
        title, resolution = ASSUMPTION_LABELS.get(
            key, (f"ADAPT assumed '{key}' = {item['value']!r}", "Tell ADAPT the actual value.")
        )
        affected = [t["key"] for t in inputs.tasks if key in t["fact_keys"]]
        risks.append(
            _risk(
                RiskKind.MISSING_INFORMATION,
                RiskSeverity.WARNING,
                key,
                title,
                "This choice changes which official steps apply to you.",
                resolution=resolution,
                task_keys=affected,
                fact_keys=[key],
            )
        )
    for result in inputs.eligibility:
        if result["status"] == "unknown" and result["missing_facts"]:
            rule = inputs.governance["nodes"].get(result["rule_key"])
            risks.append(
                _risk(
                    RiskKind.MISSING_INFORMATION,
                    RiskSeverity.WARNING,
                    f"{result['rule_key']}:{result['subject']}",
                    f"Missing information: {rule['label']}"
                    if rule
                    else "ADAPT needs more information to check an eligibility rule",
                    result["explanation"],
                    resolution="Answer the missing details so ADAPT can check the rule.",
                    task_keys=[
                        t["key"] for t in inputs.tasks if t["node_key"] == result["service_key"]
                    ],
                    fact_keys=result["missing_facts"],
                    governance_keys=[result["rule_key"], result["service_key"]],
                    evidence_ids=result["evidence_ids"],
                )
            )
    for req in inputs.requirements:
        if req["status"] == "unknown" and req["fact_keys"]:
            whose = "your spouse's" if req["subject"] == Subject.SPOUSE else "your"
            missing = ", ".join(
                k.split(".", 1)[-1].replace("_", " ").replace(".", " ") for k in req["fact_keys"]
            )
            risks.append(
                _risk(
                    RiskKind.MISSING_INFORMATION,
                    RiskSeverity.WARNING,
                    f"condition:{req['id']}",
                    f"ADAPT can't tell yet whether '{req['label']}' applies",
                    f"It's required only in some cases. ADAPT needs {whose} {missing} to know.",
                    resolution="Add the missing detail to your profile.",
                    task_keys=[req["task_key"]],
                    fact_keys=req["fact_keys"],
                    governance_keys=[req["node_key"]],
                    evidence_ids=req["evidence_ids"],
                )
            )
    for note in inputs.governance["notes"]:
        risks.append(
            _risk(
                RiskKind.MISSING_INFORMATION,
                RiskSeverity.INFO,
                f"coverage:{_slug(note)}",
                "Part of your move isn't covered yet",
                note,
                resolution="Check the official portal for this part of your move.",
            )
        )
    return risks


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())[:60].strip("_")


def missing_source_evidence(inputs: RiskInputs) -> list[Risk]:
    passages = {e["governance_key"] for e in inputs.evidence if e["kind"] == "official_passage"}
    nodes = inputs.governance["nodes"]
    risks = []
    uncited = []
    for task in inputs.tasks:
        node = nodes.get(task["node_key"])
        provenance = (node["provenance"] if node else None) or {}
        citations = provenance.get("citations") or []
        if node is None or not (citations or node["official_url"]):
            uncited.append(task["key"])
    if uncited:
        risks.append(
            _risk(
                RiskKind.MISSING_SOURCE_EVIDENCE,
                RiskSeverity.WARNING,
                "uncited_tasks",
                "Some steps have no official source attached",
                "ADAPT couldn't attach an official source to these steps. Treat them as "
                "unverified until you check the official portal.",
                resolution="Confirm these steps with the responsible authority.",
                task_keys=uncited,
            )
        )
    for result in inputs.eligibility:
        if result["verify_on_official_page"] and result["rule_key"] not in passages:
            risks.append(
                _risk(
                    RiskKind.MISSING_SOURCE_EVIDENCE,
                    RiskSeverity.WARNING,
                    result["rule_key"],
                    "Confirm this eligibility rule on the official page",
                    "The values ADAPT used come from a curated summary, not a quoted official "
                    f"passage. {result['explanation']}",
                    resolution="Check the current rule on the official page before you apply.",
                    task_keys=[
                        t["key"] for t in inputs.tasks if t["node_key"] == result["service_key"]
                    ],
                    governance_keys=[result["rule_key"]],
                    evidence_ids=result["evidence_ids"],
                )
            )
    return risks


def timeline(inputs: RiskInputs) -> list[Risk]:
    risks = []
    tasks = {t["key"]: t for t in inputs.tasks}
    relocation = value_of(inputs.facts, K_SPOUSE_RELOCATION)
    together = value_of(inputs.facts, K_MOVE_WITH_SPOUSE) is True and relocation in (
        None,
        "with_user",
    )
    for task in inputs.tasks:
        if (
            task["subject"] == Subject.SPOUSE
            and task["node_key"] == "service.family_residence_visa"
        ):
            if task["status"] == TaskStatus.DONE or not together:
                continue
            chain = [
                k
                for k in prerequisite_chain(task["key"], inputs.dependencies)
                if tasks[k]["status"] != TaskStatus.DONE
            ]
            direct = [
                tasks[k]["title"]
                for k in task["depends_on"]
                if tasks[k]["status"] != TaskStatus.DONE
            ]
            if len(chain) >= 2:
                keys = [K_MOVE_WITH_SPOUSE, K_SPOUSE_RELOCATION]
                risks.append(
                    _risk(
                        RiskKind.TIMELINE_DEPENDENCY,
                        RiskSeverity.WARNING,
                        task["key"],
                        "Your spouse's residence visa can't start when you arrive",
                        f"It can only begin after {len(chain)} earlier steps are done, "
                        f"including: {', '.join(direct)}. Plan your spouse's travel around this.",
                        resolution="Check the official ICP guidance on how your spouse can enter "
                        "while the sponsorship is being prepared.",
                        task_keys=[task["key"], *chain],
                        fact_keys=[k for k in keys if k in inputs.facts],
                        governance_keys=[task["node_key"]],
                        evidence_ids=task["evidence_ids"][:1],
                    )
                )
    arrival = value_of(inputs.facts, K_ARRIVAL) or value_of(inputs.facts, K_ARRIVAL_TEXT)
    open_tasks = [t for t in inputs.tasks if t["status"] != TaskStatus.DONE and t["level"] >= 0]
    deepest = max((t["level"] for t in open_tasks), default=0)
    if arrival and deepest + 1 >= LONG_CHAIN:
        last = [t for t in open_tasks if t["level"] == deepest]
        risks.append(
            _risk(
                RiskKind.TIMELINE_DEPENDENCY,
                RiskSeverity.INFO,
                "long_chain",
                f"{deepest + 1} stages have to happen one after another",
                f"You plan to arrive {arrival}. {last[0]['title']} is at the end of a chain of "
                f"{deepest + 1} dependent stages, so start the first ones early.",
                task_keys=[t["key"] for t in last],
                fact_keys=[k for k in (K_ARRIVAL, K_ARRIVAL_TEXT) if k in inputs.facts],
            )
        )
    return risks


def ordering(inputs: RiskInputs) -> list[Risk]:
    risks = []
    tasks = {t["key"]: t for t in inputs.tasks}
    cyclic = [t["key"] for t in inputs.tasks if t["level"] < 0]
    if cyclic:
        risks.append(
            _risk(
                RiskKind.INCOMPATIBLE_TASK_ORDERING,
                RiskSeverity.BLOCKING,
                "cycle",
                "Some steps depend on each other in a loop",
                "These steps can't be ordered because each one waits for another. ADAPT has "
                "flagged this for review instead of guessing an order.",
                resolution="Check the order with the responsible authority.",
                task_keys=cyclic,
            )
        )
    for dep in inputs.dependencies:
        task, prereq = tasks.get(dep["task"]), tasks.get(dep["depends_on"])
        if not task or not prereq:
            continue
        if task["status"] == TaskStatus.DONE and prereq["status"] != TaskStatus.DONE:
            risks.append(
                _risk(
                    RiskKind.INCOMPATIBLE_TASK_ORDERING,
                    RiskSeverity.WARNING,
                    dep["id"],
                    f"'{task['title']}' is marked done before '{prereq['title']}'",
                    f"'{task['title']}' normally comes after '{prereq['title']}'. One of them "
                    "may be recorded incorrectly.",
                    resolution=f"Check whether '{prereq['title']}' is already done.",
                    task_keys=[task["key"], prereq["key"]],
                    fact_keys=task["fact_keys"],
                    governance_keys=[dep["via"]],
                )
            )
    return risks


def external_login(inputs: RiskInputs) -> list[Risk]:
    keys = [
        t["key"] for t in inputs.tasks if t["requires_login"] and t["status"] != TaskStatus.DONE
    ]
    if not keys:
        return []
    return [
        _risk(
            RiskKind.EXTERNAL_LOGIN_REQUIRED,
            RiskSeverity.INFO,
            "uae_pass",
            f"{len(keys)} steps need your own UAE PASS login",
            "You complete these on the official portal yourself. ADAPT prepares everything and "
            "hands you over. It never asks for or stores your credentials.",
            resolution="Set up UAE PASS before you start these steps.",
            task_keys=keys,
        )
    ]


def eligibility_gaps(inputs: RiskInputs) -> list[Risk]:
    passages = {e["governance_key"] for e in inputs.evidence if e["kind"] == "official_passage"}
    risks = []
    for result in inputs.eligibility:
        if result["status"] != "unmet":
            continue
        verified = result["rule_key"] in passages and not result["verify_on_official_page"]
        risks.append(
            _risk(
                RiskKind.ELIGIBILITY_GAP,
                RiskSeverity.BLOCKING if verified else RiskSeverity.WARNING,
                f"{result['rule_key']}:{result['subject']}",
                "Your stated details don't meet an eligibility rule",
                result["explanation"],
                resolution="Check the rule on the official page. Different routes or thresholds "
                "may apply to your situation.",
                task_keys=[
                    t["key"] for t in inputs.tasks if t["node_key"] == result["service_key"]
                ],
                fact_keys=result["fact_keys"],
                governance_keys=[result["rule_key"], result["service_key"]],
                evidence_ids=result["evidence_ids"],
            )
        )
    return risks


def _relevant(inputs: RiskInputs) -> RiskInputs:
    """Only rules of steps actually planned (and not done) can raise risks: the graph
    also holds rules of alternatives the plan didn't choose (e.g. ADGM vs mainland)."""
    open_services = {t["node_key"] for t in inputs.tasks if t["status"] != TaskStatus.DONE}
    return RiskInputs(
        tasks=inputs.tasks,
        requirements=inputs.requirements,
        dependencies=inputs.dependencies,
        eligibility=[e for e in inputs.eligibility if e["service_key"] in open_services],
        facts=inputs.facts,
        evidence=inputs.evidence,
        governance=inputs.governance,
    )


def detect_risks(inputs: RiskInputs) -> list[Risk]:
    inputs = _relevant(inputs)
    risks = [
        *missing_documents(inputs),
        *missing_information(inputs),
        *missing_source_evidence(inputs),
        *timeline(inputs),
        *ordering(inputs),
        *external_login(inputs),
        *eligibility_gaps(inputs),
    ]
    unique = {r["id"]: r for r in risks}
    for risk in unique.values():
        risk["fact_ids"] = fact_ids_for(inputs.facts, risk["fact_keys"])
    return sorted(
        unique.values(),
        key=lambda r: (_SEVERITY_ORDER[RiskSeverity(r["severity"])], r["kind"], r["id"]),
    )
