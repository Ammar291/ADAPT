"""DOCUMENT_PREPARATION -> ACTION_PREPARATION: drafts and prepared (not executed) actions.

In a what-if simulation both run in preview mode: drafts and actions are computed so the
scenarios can be compared, but nothing is stored and no event claims otherwise.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.runtime import Runtime

from app.agents.instrumentation import report
from app.agents.journey.context import ctx
from app.agents.journey.emit import emit
from app.agents.journey.facts import value_of
from app.agents.journey.spec import NodeSpec, journey_node
from app.agents.journey.state import (
    ActionRecord,
    EvidenceRecord,
    GeneratedDocumentRef,
    Requirement,
    Risk,
    Task,
    UserFact,
)
from app.agents.journey.tools import (
    GenerateDocumentInput,
    JourneyTools,
    PrepareActionInput,
    PrepareAppointmentInput,
)
from app.agents.journey.vocab import NodeId, RiskSeverity, TaskKind, TaskStatus
from app.core.errors import BadRequest
from app.domain.enums import ActionKind, ActionStatus

MAX_CHECKLISTS = 3
MAX_ACTIONS = 5
NAME_KEYS = {
    "self": ("profile.full_name", "passport.full_name", "documents.passport.full_name"),
    "spouse": (
        "spouse.full_name",
        "spouse.passport.full_name",
        "marriage_certificate.spouse_2_name",
    ),
}


def _name(facts: dict[str, UserFact], subject: str) -> str | None:
    for key in NAME_KEYS.get(subject, ()):
        value = value_of(facts, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _sources(task: Task, evidence: dict[str, EvidenceRecord]) -> list[dict[str, str]]:
    sources = []
    for evidence_id in task["evidence_ids"]:
        record = evidence.get(evidence_id)
        if record and record["source_url"]:
            sources.append({"url": record["source_url"], "title": record["title"]})
    return sources


def _requirements_of(
    task: Task, requirements: dict[str, Requirement], tasks: dict[str, Task]
) -> list[dict[str, Any]]:
    out = []
    for req_id in task["requirement_ids"]:
        req = requirements.get(req_id)
        if req is None:
            continue
        provider = tasks.get(req["satisfied_by"] or "")
        out.append(
            {
                "label": req["label"] + (" (spouse)" if req["subject"] == "spouse" else ""),
                "status": req["status"],
                "provided_by": provider["title"]
                if provider and req["status"] == "produced_by_task"
                else None,
            }
        )
    return out


# --- DOCUMENT_PREPARATION ------------------------------------------------------------------


class DocPrepIn(TypedDict):
    journey_id: str
    tasks: list[Task]
    requirements: list[Requirement]
    user_facts: dict[str, UserFact]
    evidence: list[EvidenceRecord]


class DocPrepOut(TypedDict, total=False):
    generated_documents: list[GeneratedDocumentRef]


DOCUMENT_PREPARATION = NodeSpec(
    id=NodeId.DOCUMENT_PREPARATION,
    label="Prepare documents",
    description="Drafts checklists and letters for you to review. Nothing is sent.",
    kind="agent",
    input=DocPrepIn,
    output=DocPrepOut,
    fact_keys=frozenset(
        {"household.*", "profile.*", "company.*", "*.full_name", "*.documents.*", "documents.*"}
    ),
    lane=0,
)


@journey_node(DOCUMENT_PREPARATION)
async def document_preparation(state: DocPrepIn, runtime: Runtime[Any]) -> dict[str, Any]:
    tools = JourneyTools(ctx(runtime))
    tasks = {t["key"]: t for t in state["tasks"]}
    requirements = {r["id"]: r for r in state["requirements"]}
    evidence = {e["id"]: e for e in state["evidence"]}
    facts = state["user_facts"]
    jobs: list[GenerateDocumentInput] = []

    ready = [
        t
        for t in state["tasks"]
        if t["status"] == TaskStatus.READY
        and t["kind"] == TaskKind.SERVICE
        and t["requirement_ids"]
    ]
    for task in ready[:MAX_CHECKLISTS]:
        jobs.append(
            GenerateDocumentInput(
                kind="checklist",
                title=f"Checklist: {task['title']}",
                journey_id=state["journey_id"],
                task_key=task["key"],
                context={
                    "authority": task["authority"],
                    "official_url": task["official_url"],
                    "requirements": _requirements_of(task, requirements, tasks),
                    "sources": _sources(task, evidence),
                },
            )
        )
    sponsorship = next(
        (
            t
            for t in state["tasks"]
            if t["node_key"] == "service.family_residence_visa" and t["status"] != TaskStatus.DONE
        ),
        None,
    )
    if sponsorship:
        jobs.append(
            GenerateDocumentInput(
                kind="cover_letter",
                title="Cover letter: sponsoring your spouse",
                journey_id=state["journey_id"],
                task_key=sponsorship["key"],
                context={
                    "service": sponsorship["title"],
                    "authority": sponsorship["authority"],
                    "applicant_name": _name(facts, "self"),
                    "spouse_name": _name(facts, "spouse"),
                    "documents": [
                        r["label"] for r in _requirements_of(sponsorship, requirements, tasks)
                    ],
                    "sources": _sources(sponsorship, evidence),
                },
            )
        )

    generated: list[GeneratedDocumentRef] = []
    for index, job in enumerate(jobs, start=1):
        out = await tools.generate_document(job)
        generated.append(
            GeneratedDocumentRef(
                id=out.id,
                kind=out.kind,
                title=out.title,
                task_key=job.task_key,
                persisted=out.persisted,
                evidence_ids=tasks[job.task_key]["evidence_ids"][:3]
                if job.task_key in tasks
                else [],
            )
        )
        await report(runtime, f"Drafted {out.title}", index / len(jobs))
    return {"generated_documents": generated, "_summary": f"{len(generated)} drafts to review"}


# --- ACTION_PREPARATION -----------------------------------------------------------------------


class ActionPrepIn(TypedDict):
    journey_id: str
    run_id: str
    tasks: list[Task]
    requirements: list[Requirement]
    risks: list[Risk]


class ActionPrepOut(TypedDict, total=False):
    actions: list[ActionRecord]


ACTION_PREPARATION = NodeSpec(
    id=NodeId.ACTION_PREPARATION,
    label="Prepare next actions",
    description="Prepares official-site handoffs and bookings for steps you can start now.",
    kind="tool",
    input=ActionPrepIn,
    output=ActionPrepOut,
    fact_keys=frozenset(),
    lane=1,
)


@journey_node(ACTION_PREPARATION)
async def action_preparation(state: ActionPrepIn, runtime: Runtime[Any]) -> dict[str, Any]:
    context = ctx(runtime)
    tools = JourneyTools(context)
    tasks = {t["key"]: t for t in state["tasks"]}
    requirements = {r["id"]: r for r in state["requirements"]}
    blocking = {
        key: risk
        for risk in state["risks"]
        if risk["severity"] == RiskSeverity.BLOCKING
        for key in risk["task_keys"]
    }
    # Steps the user can act on now; consequential ones (bookings, applications) before
    # informational links, so the handoffs that matter aren't crowded out.
    ready = [
        t
        for t in state["tasks"]
        if t["status"] == TaskStatus.READY and t["action_type"] and t["official_url"]
    ]
    candidates = sorted(
        ready,
        key=lambda t: (
            t["action_type"] == ActionKind.OFFICIAL_HANDOFF,
            t["kind"] == TaskKind.REQUIREMENT,  # real services before off-platform prep
            t["order"],
        ),
    )[:MAX_ACTIONS]

    actions: list[ActionRecord] = []
    for index, task in enumerate(candidates, start=1):
        reqs = _requirements_of(task, requirements, tasks)
        payload = {
            "task": task["title"],
            "documents": [r["label"] for r in reqs if r["status"] == "satisfied"],
            "missing_documents": [r["label"] for r in reqs if r["status"] == "missing"],
        }
        common = {
            "task_key": task["key"],
            "service_key": task["node_key"],
            "title": task["title"],
            "official_url": task["official_url"],
            "channel_name": task["portal"] or task["authority"],
            "requires_login": task["requires_login"],
            "payload": payload,
            "evidence": task["evidence_ids"][:3],
        }
        try:
            if task["action_type"] == ActionKind.APPOINTMENT:
                out = await tools.prepare_appointment(PrepareAppointmentInput(**common))
            else:
                out = await tools.prepare_action(
                    PrepareActionInput(action_type=ActionKind(str(task["action_type"])), **common)
                )
        except BadRequest:
            continue  # no verified official channel: nothing to hand off to
        action = ActionRecord(**out.action)  # type: ignore[typeddict-item]
        reason = None
        if task["key"] in blocking:
            reason = blocking[task["key"]]["title"]
        elif action["type"] == ActionKind.DOCUMENT_SUBMISSION and payload["missing_documents"]:
            reason = f"Missing: {', '.join(payload['missing_documents'])}"
        if reason:
            action["status"] = ActionStatus.BLOCKED.value
            action["response_metadata"] = {**action["response_metadata"], "blocked_reason": reason}
        actions.append(action)
        await report(runtime, f"Prepared: {task['title']}", index / max(len(candidates), 1))

    if actions and not context.simulation:
        await context.svc.store.save_actions(
            journey_id=state["journey_id"], run_id=state["run_id"], actions=actions
        )
        for action in actions:
            await emit(
                context,
                "action_prepared",
                action_id=action["id"],
                action_type=action["type"],
                title=action["title"],
                status=action["status"],
                requires_approval=action["requires_human_approval"],
            )
    need_approval = sum(
        1 for a in actions if a["requires_human_approval"] and a["status"] == ActionStatus.PREPARED
    )
    return {
        "actions": actions,
        "_summary": f"{len(actions)} actions prepared, {need_approval} need your approval",
    }
