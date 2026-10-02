"""Deterministic journey planning over the governance graph (pure: no DB, no LLM).

This is where "never hallucinate a government obligation" is enforced by construction:
every task, requirement and dependency is derived from a governance node or edge, which
cites an official source. The planner selects root services from the user's goals, then
walks the graph:

* `depends_on` a service       -> that service is a prerequisite task (AND);
* `depends_on` a dependency    -> exactly one `satisfied_by` alternative (OR), selected
                                  by its `when` condition over the user's facts;
* `requires` a document        -> satisfied when the user holds it, otherwise produced
                                  by the service that `produces` it, otherwise missing;
* `requires` a requirement     -> met when `meets.<requirement>` is true, otherwise an
                                  off-platform requirement task;
* `may_require` an appointment -> an appointment task.

Goals ADAPT has no governance coverage for produce a note, never an invented task.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.agents.journey import eligibility
from app.agents.journey.facts import (
    GOAL_ESTABLISH_COMPANY,
    GOAL_FIND_HOUSING,
    GOAL_RESIDENCY,
    GOAL_SPONSOR_FAMILY,
    K_JURISDICTION,
    K_MOVE_WITH_SPOUSE,
    completed_fact_key,
    document_fact_key,
    fact_ids_for,
    goals_of,
    subject_key,
    suffix,
    value_of,
)
from app.agents.journey.governance import (
    DEPENDS_ON,
    MAY_REQUIRE,
    PRODUCES,
    REQUIRES,
    SATISFIED_BY,
    GovernanceSnapshot,
)
from app.agents.journey.state import (
    Dependency,
    GovEdge,
    GovNode,
    Requirement,
    Task,
    TaskLink,
    UserFact,
)
from app.agents.journey.vocab import DependencyKind, Subject, TaskKind, TaskStatus
from app.domain.provenance import is_official_source

# Goal -> root services. Keys are validated against the seed by tests; a key missing
# from the governance graph is reported as uncovered rather than planned.
# Subjects are stored as plain strings: checkpointed state holds JSON types only.
SELF, SPOUSE = Subject.SELF.value, Subject.SPOUSE.value
GOAL_ROOTS: dict[str, list[tuple[str, str]]] = {
    GOAL_ESTABLISH_COMPANY: [("service.corporate_tax_registration", SELF)],
    GOAL_RESIDENCY: [("service.residence_visa_investor", SELF)],
    GOAL_SPONSOR_FAMILY: [("service.family_residence_visa", SPOUSE)],
    GOAL_FIND_HOUSING: [("service.tawtheeq", SELF)],
}
# Fallback roots for a company when corporate tax registration is not in the graph.
LICENCE_BY_JURISDICTION = {
    "mainland": "service.commercial_license_mainland",
    "adgm": "service.company_registration_adgm",
}
GOAL_LABELS = {
    GOAL_ESTABLISH_COMPANY: "set up your company",
    GOAL_RESIDENCY: "get your residence visa",
    GOAL_SPONSOR_FAMILY: "sponsor your spouse's residence visa",
    GOAL_FIND_HOUSING: "register your home lease",
}
GOAL_FACTS = {
    GOAL_ESTABLISH_COMPANY: ["goals", "profile.is_founder"],
    GOAL_RESIDENCY: ["goals"],
    GOAL_SPONSOR_FAMILY: ["goals", K_MOVE_WITH_SPOUSE],
    GOAL_FIND_HOUSING: ["goals"],
}

# Life areas by governance key fragment, when a node does not declare `properties.area`.
_AREA_HINTS: tuple[tuple[str, str], ...] = (
    ("family", "family"),
    ("sponsor", "family"),
    ("mission", "family"),
    ("marriage", "family"),
    ("attestation", "family"),
    ("tawtheeq", "housing"),
    ("tenancy", "housing"),
    ("medical", "health"),
    ("insurance", "health"),
    ("tax", "finance"),
    ("bank", "finance"),
    ("licen", "business"),
    ("trade_name", "business"),
    ("company", "business"),
    ("adgm", "business"),
    ("initial_approval", "business"),
    ("establishment", "business"),
    ("premises", "business"),
    ("visa", "residency"),
    ("permit", "residency"),
    ("emirates_id", "residency"),
    ("biometric", "residency"),
)
# Documents that belong to the household rather than to the person a service is for, used
# only when the governance edge carries no explicit `party`.
_HOUSEHOLD_DOCUMENT_HINTS = ("tenancy", "marriage")


def task_key(node_key: str, subject: str) -> str:
    return node_key if subject == Subject.SELF else f"{node_key}@{subject}"


def reference_evidence_id(governance_key: str) -> str:
    return f"ref:{governance_key}"


def area_of(node: GovNode) -> str:
    declared = node["properties"].get("area") or node["properties"].get("category")
    if isinstance(declared, str):
        return declared
    for fragment, area in _AREA_HINTS:
        if fragment in node["key"]:
            return area
    return "daily_life"


def action_type_of(snapshot: GovernanceSnapshot, node: GovNode, kind: TaskKind) -> str | None:
    """How ADAPT can help with a task. Declared by the node, else derived conservatively."""
    declared = node["properties"].get("action_type")
    if isinstance(declared, str):
        return declared
    if kind is TaskKind.APPOINTMENT:
        return "appointment"
    if kind is TaskKind.REQUIREMENT:
        return "official_handoff"
    if "attest" in node["key"] or node["properties"].get("submission") is True:
        return "document_submission"
    if snapshot.requires_login(node["key"]):
        return "government_portal"
    return "official_handoff" if node["official_url"] else None


def _target_subject(edge: GovEdge, subject: str, target: GovNode | None) -> str:
    """Whose step or document an edge's target is (see governance.py on `party`)."""
    party = edge["properties"].get("party")
    if party in ("sponsor", "household"):
        return SELF
    if party == "beneficiary":
        return subject
    if subject == Subject.SELF:
        return subject
    # No explicit party on a household member's service: prerequisite services belong to
    # the sponsor; household documents (lease, marriage certificate) too.
    if edge["relation"] == DEPENDS_ON:
        return SELF
    if target and any(hint in target["key"] for hint in _HOUSEHOLD_DOCUMENT_HINTS):
        return SELF
    return subject


@dataclass
class RootSelection:
    roots: list[tuple[str, str, str, list[str]]]  # (service key, subject, why, fact keys)
    notes: list[str] = field(default_factory=list)
    uncovered_goals: list[str] = field(default_factory=list)


def select_roots(snapshot: GovernanceSnapshot, facts: dict[str, UserFact]) -> RootSelection:
    goals = goals_of(facts)
    selection = RootSelection(roots=[])
    for goal in goals:
        if goal not in GOAL_ROOTS:
            selection.uncovered_goals.append(goal)
            selection.notes.append(f"ADAPT has no verified official guidance for '{goal}' yet.")
            continue
        if goal == GOAL_RESIDENCY and GOAL_ESTABLISH_COMPANY not in goals:
            selection.uncovered_goals.append(goal)
            selection.notes.append(
                "Residency is planned through your own company; ADAPT's official guidance "
                "does not yet cover other routes (for example, an employer's sponsorship)."
            )
            continue
        candidates = list(GOAL_ROOTS[goal])
        if goal == GOAL_ESTABLISH_COMPANY and candidates[0][0] not in snapshot.nodes:
            jurisdiction = value_of(facts, K_JURISDICTION)
            licence = LICENCE_BY_JURISDICTION.get(str(jurisdiction))
            candidates = [(licence, SELF)] if licence else []
        present = [(k, s) for k, s in candidates if k in snapshot.nodes]
        if not present:
            selection.uncovered_goals.append(goal)
            selection.notes.append(
                f"The official services to {GOAL_LABELS.get(goal, goal)} are not in ADAPT's "
                "governance graph yet."
            )
            continue
        for key, subject in present:
            why = f"You want to {GOAL_LABELS.get(goal, goal)}."
            if all(r[0] != key or r[1] != subject for r in selection.roots):
                selection.roots.append((key, subject, why, GOAL_FACTS.get(goal, ["goals"])))
    return selection


@dataclass
class PlanResult:
    tasks: list[Task]
    requirements: list[Requirement]
    notes: list[str]
    uncovered_goals: list[str]
    alternatives: list[dict[str, Any]]  # OR-groups: {group, chosen, options, decided_by}
    root_services: list[str]


class _Planner:
    def __init__(
        self,
        snapshot: GovernanceSnapshot,
        facts: dict[str, UserFact],
        evidence_index: dict[str, list[str]],
    ) -> None:
        self.g = snapshot
        self.facts = facts
        self.evidence_index = evidence_index
        self.tasks: dict[str, Task] = {}
        self.requirements: dict[str, Requirement] = {}
        self.alternatives: dict[str, dict[str, Any]] = {}
        self.queue: deque[str] = deque()

    # --- helpers -------------------------------------------------------------------------
    def _evidence(self, governance_key: str) -> list[str]:
        return [reference_evidence_id(governance_key), *self.evidence_index.get(governance_key, [])]

    def _is_done(self, node_key: str, subject: str) -> tuple[bool, list[str]]:
        key = completed_fact_key(node_key, subject)
        if value_of(self.facts, key) is True:
            return True, [key]
        for edge in self.g.out(node_key, PRODUCES):
            held = document_fact_key(edge["target"], subject)
            if value_of(self.facts, held) is True:
                return True, [held]
        return False, []

    def _official_url(self, node_key: str, fallback: str | None = None) -> str | None:
        """The node's own page, its portal, the first official page it cites, else the
        page of the step it belongs to."""
        node = self.g.nodes[node_key]
        if node["official_url"]:
            return node["official_url"]
        portal = self.g.portal_of(node_key)
        if portal and portal["official_url"]:
            return portal["official_url"]
        for citation in (node.get("provenance") or {}).get("citations") or []:
            url = citation.get("source_url")
            if isinstance(url, str) and is_official_source(url):
                return url
        return fallback

    def _ensure_task(
        self,
        node_key: str,
        subject: str,
        kind: TaskKind,
        why: str,
        fact_keys: list[str],
        fallback_url: str | None = None,
    ) -> str:
        key = task_key(node_key, subject)
        if key in self.tasks:
            return key
        node = self.g.nodes[node_key]
        done, done_facts = self._is_done(node_key, subject)
        authority = self.g.authority_of(node_key)
        portal = self.g.portal_of(node_key)
        title = node["label"]
        if subject == Subject.SPOUSE:
            if not any(word in title.lower() for word in ("spouse", "family")):
                title = f"{title} for your spouse"
        elif subject != Subject.SELF and subject not in title.lower():
            title = f"{title} ({subject})"
        used = sorted({*fact_keys, *done_facts})
        self.tasks[key] = Task(
            key=key,
            node_key=node_key,
            subject=subject,
            kind=kind.value,
            title=title,
            summary=node["summary"] or "",
            area=area_of(node),
            authority=authority["label"] if authority else None,
            official_url=self._official_url(node_key, fallback_url),
            portal=portal["label"] if portal else None,
            requires_login=self.g.requires_login(node_key),
            action_type=action_type_of(self.g, node, kind),
            status=(TaskStatus.DONE if done else TaskStatus.READY).value,
            order=0,
            level=0,
            links=[],
            depends_on=[],
            requirement_ids=[],
            evidence_ids=self._evidence(node_key),
            fact_keys=used,
            fact_ids=fact_ids_for(self.facts, used),
            why=why,
        )
        if not done:  # a finished step's own prerequisites are moot
            self.queue.append(key)
        return key

    def _link(
        self,
        task: str,
        prerequisite: str,
        kind: DependencyKind,
        via: str,
        any_of: str | None = None,
    ) -> None:
        current = self.tasks[task]
        if prerequisite == task or prerequisite in current["depends_on"]:
            return
        current["links"].append(
            TaskLink(depends_on=prerequisite, kind=kind.value, via=via, any_of=any_of)
        )
        current["depends_on"].append(prerequisite)

    def _why_for(self, dependent: str) -> str:
        return f"Needed before: {self.tasks[dependent]['title']}."

    # --- expansion -----------------------------------------------------------------------
    def expand(self, key: str) -> None:
        task = self.tasks[key]
        node_key, subject = task["node_key"], task["subject"]
        legacy_groups: dict[str, list[GovEdge]] = {}
        appointments: list[str] = []
        for edge in sorted(self.g.out(node_key), key=lambda e: (e["relation"], e["target"])):
            target = self.g.node(edge["target"])
            if target is None:
                continue
            relation, ttype = edge["relation"], target["type"]
            t_subject = _target_subject(edge, subject, target)
            if not self._applies(key, edge, target, subject, t_subject):
                continue
            if relation == DEPENDS_ON and ttype == "dependency":
                self._alternative(key, target, t_subject)
            elif relation == DEPENDS_ON and edge["properties"].get("any_of"):
                legacy_groups.setdefault(str(edge["properties"]["any_of"]), []).append(edge)
            elif relation == DEPENDS_ON and ttype in ("service", "appointment"):
                kind = TaskKind.APPOINTMENT if ttype == "appointment" else TaskKind.SERVICE
                pre = self._ensure_task(target["key"], t_subject, kind, self._why_for(key), [])
                self._link(key, pre, DependencyKind.SERVICE, edge["target"])
            elif relation in (REQUIRES, DEPENDS_ON) and ttype == "document":
                self._document(key, target, t_subject)
            elif relation in (REQUIRES, DEPENDS_ON) and ttype == "requirement":
                self._requirement(key, target, t_subject)
            elif relation == MAY_REQUIRE and ttype == "appointment":
                pre = self._ensure_task(
                    target["key"],
                    t_subject,
                    TaskKind.APPOINTMENT,
                    self._why_for(key),
                    [],
                    fallback_url=task["official_url"],
                )
                self._link(key, pre, DependencyKind.APPOINTMENT, target["key"])
                appointments.append(pre)
        for group, edges in sorted(legacy_groups.items()):
            self._legacy_alternative(key, group, edges, subject)
        # An appointment is part of its service: it can't be booked before the service's
        # own prerequisites are done (e.g. biometrics only once the application exists).
        for appointment in appointments:
            for link in list(task["links"]):
                if link["depends_on"] not in appointments:
                    self._link(
                        appointment,
                        link["depends_on"],
                        DependencyKind(link["kind"]),
                        link["via"],
                        link["any_of"],
                    )

    def _applies(
        self, key: str, edge: GovEdge, target: GovNode, subject: str, t_subject: str
    ) -> bool:
        """Honour an edge's `when` condition. It is read from the facts of `when_party`
        (default: the edge's own party). An unmet condition drops the requirement. So does
        an undecidable one, recorded as an `unknown` requirement naming the missing facts,
        so ADAPT asks rather than inventing or hiding an obligation."""
        condition = edge["properties"].get("when")
        if not isinstance(condition, dict):
            return True
        party = edge["properties"].get("when_party") or edge["properties"].get("party")
        whose = (
            subject
            if party == "beneficiary"
            else (SELF if party in ("sponsor", "household") else t_subject)
        )
        scoped = eligibility.scope_condition(condition, whose)
        result = eligibility.evaluate(scoped, {**self.facts, **eligibility.implicit_facts(whose)})
        if result.status == "met":
            return True
        if result.status == "unknown" and edge["relation"] in (REQUIRES, DEPENDS_ON):
            self._add_requirement(
                f"{key}->{target['key']}", key, target, t_subject, "unknown", None, result.missing
            )
        return False

    def _choose(
        self, options: list[tuple[str, dict[str, Any] | None]], subject: str
    ) -> tuple[str | None, str]:
        """Pick one OR-alternative: an option already done wins, then a met `when`."""
        for option, _ in options:
            if self._is_done(option, subject)[0]:
                return option, "already done"
        for option, condition in options:
            if (
                condition
                and eligibility.evaluate(condition, self.facts, allow_assumed=True).status == "met"
            ):
                return option, eligibility.describe(condition)
        unconditional = [o for o, c in options if not c]
        if len(unconditional) == 1:
            return unconditional[0], "only option"
        return None, "undecided"

    def _alternative(self, key: str, group: GovNode, subject: str) -> None:
        options = [
            (e["target"], e["properties"].get("when"))
            for e in sorted(self.g.out(group["key"], SATISFIED_BY), key=lambda e: e["target"])
            if e["target"] in self.g.nodes
        ]
        chosen, reason = self._choose(options, subject)
        self._record_alternative(group["key"], chosen, [o for o, _ in options], reason)
        if chosen:
            used = sorted(
                {k for _, c in options if c for k in eligibility.evaluate(c, self.facts).used}
            )
            pre = self._ensure_task(chosen, subject, TaskKind.SERVICE, self._why_for(key), used)
            self._link(key, pre, DependencyKind.ALTERNATIVE, group["key"], any_of=group["key"])

    def _legacy_alternative(self, key: str, group: str, edges: list[GovEdge], subject: str) -> None:
        jurisdiction = value_of(self.facts, K_JURISDICTION)
        options: list[tuple[str, dict[str, Any] | None]] = []
        for edge in edges:
            node_jurisdiction = self.g.nodes[edge["target"]]["properties"].get("jurisdiction")
            condition = (
                {"fact": K_JURISDICTION, "op": "eq", "value": node_jurisdiction}
                if node_jurisdiction
                else None
            )
            options.append((edge["target"], condition))
        chosen, reason = self._choose(options, subject)
        self._record_alternative(group, chosen, [o for o, _ in options], reason)
        if chosen:
            used = [K_JURISDICTION] if jurisdiction is not None else []
            pre = self._ensure_task(chosen, subject, TaskKind.SERVICE, self._why_for(key), used)
            self._link(key, pre, DependencyKind.ALTERNATIVE, chosen, any_of=group)

    def _record_alternative(
        self, group: str, chosen: str | None, options: list[str], reason: str
    ) -> None:
        self.alternatives.setdefault(
            group, {"group": group, "chosen": chosen, "options": options, "decided_by": reason}
        )

    def _document(self, key: str, document: GovNode, subject: str) -> None:
        fact_key = document_fact_key(document["key"], subject)
        held = value_of(self.facts, fact_key)
        requirement_id = f"{key}->{document['key']}"
        producers = [p for p in self.g.producers_of(document["key"]) if p in self.g.nodes]
        if held is True:
            status, satisfied_by = "satisfied", fact_key
        elif producers:
            # Prefer a producer already in the plan (e.g. the chosen licence alternative).
            chosen = next(
                (p for p in producers if task_key(p, subject) in self.tasks), producers[0]
            )
            satisfied_by = self._ensure_task(
                chosen, subject, TaskKind.SERVICE, self._why_for(key), []
            )
            self._link(key, satisfied_by, DependencyKind.DOCUMENT, document["key"])
            status = "produced_by_task"
        else:
            status, satisfied_by = "missing", None
        self._add_requirement(
            requirement_id, key, document, subject, status, satisfied_by, [fact_key]
        )

    def _requirement(self, key: str, requirement: GovNode, subject: str) -> None:
        fact_key = subject_key(subject, f"meets.{suffix(requirement['key'])}")
        requirement_id = f"{key}->{requirement['key']}"
        if requirement["properties"].get("informational"):
            # The authority checks it while processing: shown to the user, never a step.
            self._add_requirement(
                requirement_id, key, requirement, subject, "checked_by_authority", None, []
            )
            return
        if value_of(self.facts, fact_key) is True:
            self._add_requirement(
                requirement_id, key, requirement, subject, "satisfied", fact_key, [fact_key]
            )
            return
        pre = self._ensure_task(
            requirement["key"], subject, TaskKind.REQUIREMENT, self._why_for(key), []
        )
        self._link(key, pre, DependencyKind.REQUIREMENT, requirement["key"])
        self._add_requirement(
            requirement_id, key, requirement, subject, "produced_by_task", pre, [fact_key]
        )

    def _add_requirement(
        self,
        requirement_id: str,
        key: str,
        node: GovNode,
        subject: str,
        status: str,
        satisfied_by: str | None,
        fact_keys: list[str],
    ) -> None:
        self.requirements[requirement_id] = Requirement(
            id=requirement_id,
            task_key=key,
            node_key=node["key"],
            node_type=node["type"],
            label=node["label"],
            subject=subject,
            status=status,  # type: ignore[typeddict-item]
            satisfied_by=satisfied_by,
            fact_keys=fact_keys,
            evidence_ids=self._evidence(node["key"]),
        )
        if requirement_id not in self.tasks[key]["requirement_ids"]:
            self.tasks[key]["requirement_ids"].append(requirement_id)

    def _link_done_tasks(self) -> None:
        """A finished step isn't expanded, but if one of its prerequisites is in the plan
        anyway (and not done), keep that edge so the ordering conflict stays visible."""
        for key, task in list(self.tasks.items()):
            if task["status"] != TaskStatus.DONE:
                continue
            for edge in self.g.out(task["node_key"], DEPENDS_ON):
                subject = _target_subject(edge, task["subject"], self.g.node(edge["target"]))
                if self.g.type_of(edge["target"]) == "dependency":
                    options = [e["target"] for e in self.g.out(edge["target"], SATISFIED_BY)]
                    kind, any_of = DependencyKind.ALTERNATIVE, edge["target"]
                else:
                    options, kind, any_of = [edge["target"]], DependencyKind.SERVICE, None
                for option in options:
                    if task_key(option, subject) in self.tasks:
                        self._link(key, task_key(option, subject), kind, edge["target"], any_of)

    def run(self, selection: RootSelection) -> PlanResult:
        for service_key, subject, why, fact_keys in selection.roots:
            self._ensure_task(service_key, subject, TaskKind.SERVICE, why, fact_keys)
        while self.queue:
            self.expand(self.queue.popleft())
        self._link_done_tasks()
        return PlanResult(
            tasks=[self.tasks[k] for k in sorted(self.tasks)],
            requirements=[self.requirements[k] for k in sorted(self.requirements)],
            notes=list(selection.notes),
            uncovered_goals=list(selection.uncovered_goals),
            alternatives=[self.alternatives[k] for k in sorted(self.alternatives)],
            root_services=[r[0] for r in selection.roots],
        )


def plan(
    snapshot: GovernanceSnapshot,
    facts: dict[str, UserFact],
    evidence_index: dict[str, list[str]] | None = None,
) -> PlanResult:
    return _Planner(snapshot, facts, evidence_index or {}).run(select_roots(snapshot, facts))


# --- dependency analysis ------------------------------------------------------------------

_AREA_ORDER = (
    "business",
    "residency",
    "health",
    "housing",
    "family",
    "finance",
    "daily_life",
    "community",
)


@dataclass
class DependencyAnalysis:
    tasks: list[Task]
    dependencies: list[Dependency]
    cycles: list[list[str]]
    critical_path: list[str]


def analyse_dependencies(tasks: list[Task]) -> DependencyAnalysis:
    """Typed edges, a deterministic topological order, levels, readiness and cycles."""
    by_key: dict[str, Task] = {t["key"]: Task(**t) for t in tasks}  # copies
    dependencies: list[Dependency] = []
    for task in tasks:
        for link in task["links"]:
            if link["depends_on"] not in by_key:
                continue
            dependencies.append(
                Dependency(
                    id=f"{task['key']}<-{link['depends_on']}",
                    task=task["key"],
                    depends_on=link["depends_on"],
                    kind=link["kind"],
                    via=link["via"],
                    any_of=link["any_of"],
                    evidence_ids=[reference_evidence_id(link["via"])],
                )
            )
    prerequisites: dict[str, set[str]] = {k: set() for k in by_key}
    dependents: dict[str, set[str]] = {k: set() for k in by_key}
    for dep in dependencies:
        prerequisites[dep["task"]].add(dep["depends_on"])
        dependents[dep["depends_on"]].add(dep["task"])

    def rank(key: str) -> tuple[int, str]:
        area = str(by_key[key]["area"])
        return (_AREA_ORDER.index(area) if area in _AREA_ORDER else len(_AREA_ORDER), key)

    remaining = {k: len(v) for k, v in prerequisites.items()}
    level: dict[str, int] = {}

    def position(key: str) -> tuple[int, int, str]:
        # Kahn's algorithm, always taking the shallowest ready task (then by area, key),
        # so the order reads stage by stage.
        depth = max((level[p] + 1 for p in prerequisites[key]), default=0)
        return (depth, *rank(key))

    frontier = sorted((k for k, n in remaining.items() if n == 0), key=position)
    order: list[str] = []
    while frontier:
        key = frontier.pop(0)
        order.append(key)
        level[key] = max((level[p] + 1 for p in prerequisites[key]), default=0)
        for dependent in dependents[key]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                frontier.append(dependent)
        frontier.sort(key=position)

    cyclic = sorted(k for k in by_key if k not in level)
    cycles = _cycles(cyclic, prerequisites)
    for key in cyclic:  # still shown, after everything that can be ordered
        order.append(key)
        level[key] = -1

    done = {k for k, t in by_key.items() if t["status"] == TaskStatus.DONE}
    result: list[Task] = []
    for index, key in enumerate(order):
        task = by_key[key]
        if task["status"] not in (TaskStatus.DONE, TaskStatus.NOT_APPLICABLE):
            ready = key not in cyclic and prerequisites[key] <= done
            task["status"] = (TaskStatus.READY if ready else TaskStatus.BLOCKED).value
        task["order"] = index + 1
        task["level"] = level[key]
        task["depends_on"] = sorted(prerequisites[key])
        result.append(task)

    return DependencyAnalysis(
        tasks=result,
        dependencies=sorted(dependencies, key=lambda d: d["id"]),
        cycles=cycles,
        critical_path=_critical_path(level, prerequisites),
    )


def _cycles(keys: list[str], prerequisites: dict[str, set[str]]) -> list[list[str]]:
    remaining, cycles = set(keys), []
    for start in keys:
        if start not in remaining:
            continue
        path, seen, node = [], set(), start
        while node in remaining and node not in seen:
            seen.add(node)
            path.append(node)
            node = min((p for p in prerequisites[node] if p in remaining), default=None)  # type: ignore[assignment]
            if node is None:
                break
        if node in seen:
            cycle = path[path.index(node) :]
            cycles.append(cycle)
            remaining -= set(cycle)
    return cycles


def _critical_path(level: dict[str, int], prerequisites: dict[str, set[str]]) -> list[str]:
    if not level:
        return []
    end = max(sorted(level), key=lambda k: level[k])
    path = [end]
    while prerequisites.get(path[-1]):
        candidates = [p for p in prerequisites[path[-1]] if level.get(p, -1) == level[path[-1]] - 1]
        if not candidates:
            break
        path.append(sorted(candidates)[0])
    return list(reversed(path))


def prerequisite_chain(task: str, dependencies: list[Dependency]) -> list[str]:
    """Every task that must finish before `task` (transitively), nearest first."""
    direct: dict[str, list[str]] = {}
    for dep in dependencies:
        direct.setdefault(dep["task"], []).append(dep["depends_on"])
    seen: list[str] = []
    queue = deque(sorted(direct.get(task, [])))
    while queue:
        key = queue.popleft()
        if key in seen:
            continue
        seen.append(key)
        queue.extend(sorted(direct.get(key, [])))
    return seen
