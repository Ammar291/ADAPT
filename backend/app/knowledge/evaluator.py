"""Requirement evaluation over a governance subgraph and user facts. Pure and deterministic.

For a target service it checks, from the graph alone:

* eligibility  `eligibility_rule -applies_to-> service`, using the rule's machine condition
* requirements `service -requires-> requirement`
* documents    `service -requires-> document`; a document also counts as held once the
               service that `produces` it is completed
* dependencies `service -depends_on-> service` (AND) or `-> dependency` (OR over
               `satisfied_by`, where an edge's `properties.when` picks the relevant path)
* appointments `service -may_require-> appointment`

Each check is three-valued. A missing fact makes a check UNKNOWN, never UNMET: ADAPT asks
rather than assumes. Nothing here invents an obligation. Every check is one edge of the
curated graph, and each edge cites an official passage.

Conditional edges: a `requires` or `depends_on` edge may carry `properties.when`; when it is
known not to apply the check is skipped, and while unknown the check cannot block.

Condition language (`properties.condition` on eligibility rules and requirements):

    {"fact": "finance.monthly_income_aed", "op": "gte", "value": 4000}
    {"all": [<condition>, ...]}     {"any": [<condition>, ...]}

ops: eq, ne, gt, gte, lt, lte, in, not_in, exists, truthy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue

from app.knowledge.facts import completed_fact, document_fact, fact_label
from app.knowledge.schemas import (
    CheckKind,
    CheckStatus,
    FactUse,
    JourneyTaskRef,
    NextAction,
    NextStep,
    PortalRef,
    ReasoningInput,
)

MET, UNMET, UNKNOWN = CheckStatus.MET, CheckStatus.UNMET, CheckStatus.UNKNOWN
Party = Literal["applicant", "beneficiary", "sponsor", "household"]
PARTIES: frozenset[str] = frozenset({"applicant", "beneficiary", "sponsor", "household"})
MAX_DEPTH = 12

# --- graph ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GNode:
    id: UUID
    key: str
    entity_type: str
    label: str
    summary: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    official_url: str | None = None


@dataclass(frozen=True, slots=True)
class GEdge:
    id: UUID
    relation: str
    source: UUID
    target: UUID
    properties: Mapping[str, Any] = field(default_factory=dict)


class GovernanceSubgraph:
    """Read-only adjacency over governance nodes and edges."""

    def __init__(self, nodes: list[GNode], edges: list[GEdge]) -> None:
        self.nodes: dict[UUID, GNode] = {n.id: n for n in nodes}
        self.by_key: dict[str, GNode] = {n.key: n for n in nodes}
        self.edges = [e for e in edges if e.source in self.nodes and e.target in self.nodes]
        self._out: dict[UUID, list[GEdge]] = {}
        self._in: dict[UUID, list[GEdge]] = {}
        for edge in self.edges:
            self._out.setdefault(edge.source, []).append(edge)
            self._in.setdefault(edge.target, []).append(edge)

    def out(self, node: GNode, relation: str) -> list[tuple[GEdge, GNode]]:
        pairs = [
            (e, self.nodes[e.target]) for e in self._out.get(node.id, ()) if e.relation == relation
        ]
        return sorted(pairs, key=lambda pair: (pair[1].label, pair[1].key))

    def inc(self, node: GNode, relation: str) -> list[tuple[GEdge, GNode]]:
        pairs = [
            (e, self.nodes[e.source]) for e in self._in.get(node.id, ()) if e.relation == relation
        ]
        return sorted(pairs, key=lambda pair: (pair[1].label, pair[1].key))

    def portal_of(self, node: GNode) -> GNode | None:
        portals = sorted(self.out(node, "available_at"), key=lambda p: p[1].official_url is None)
        return portals[0][1] if portals else None

    def producers_of(self, document: GNode) -> list[GNode]:
        return [service for _, service in self.inc(document, "produces")]


# --- conditions ----------------------------------------------------------------------------

_COMPARISONS = {"gt", "gte", "lt", "lte"}
_OPS = _COMPARISONS | {"eq", "ne", "in", "not_in", "exists", "truthy"}


def condition_problems(condition: Any, path: str = "condition") -> list[str]:
    """Structural validation of a condition (used by the seed validator)."""
    if not isinstance(condition, Mapping):
        return [f"{path}: must be an object"]
    if "all" in condition or "any" in condition:
        branch = "all" if "all" in condition else "any"
        items = condition[branch]
        if not isinstance(items, list) or not items:
            return [f"{path}.{branch}: must be a non-empty list"]
        problems: list[str] = []
        for i, item in enumerate(items):
            problems += condition_problems(item, f"{path}.{branch}[{i}]")
        return problems
    fact, op = condition.get("fact"), condition.get("op")
    if not isinstance(fact, str) or not fact:
        return [f"{path}: missing 'fact'"]
    if op not in _OPS:
        return [f"{path}: unknown op {op!r}"]
    if op not in {"exists", "truthy"} and "value" not in condition:
        return [f"{path}: op {op!r} needs a 'value'"]
    return []


@dataclass
class ConditionResult:
    status: CheckStatus
    used: dict[str, JsonValue] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_SYMBOL = {"eq": "=", "ne": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤"}


def _leaf(condition: Mapping[str, Any], facts: Mapping[str, Any], prefix: str) -> ConditionResult:
    key = prefix + condition["fact"]
    op = condition["op"]
    expected = condition.get("value")
    if key not in facts or facts[key] is None:
        if op == "exists":
            return ConditionResult(UNMET, missing=[key], reasons=[f"{key} is not known"])
        return ConditionResult(UNKNOWN, missing=[key], reasons=[f"{key} is not known yet"])
    actual = facts[key]
    used = {key: actual}
    if op == "exists":
        ok: bool | None = True
    elif op == "truthy":
        ok = bool(actual)
    elif op in _COMPARISONS:
        a, b = _as_number(actual), _as_number(expected)
        if a is None or b is None:
            return ConditionResult(
                UNKNOWN, used=used, missing=[key], reasons=[f"{key} is not a number"]
            )
        ok = {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    elif op in {"eq", "ne"}:
        same = actual == expected
        if isinstance(actual, str) and isinstance(expected, str):
            same = actual.strip().lower() == expected.strip().lower()
        ok = same if op == "eq" else not same
    else:  # in / not_in
        options = expected if isinstance(expected, list) else [expected]
        normalised = {str(o).lower() for o in options}
        inside = str(actual).lower() in normalised
        ok = inside if op == "in" else not inside
    shown = _SYMBOL.get(op, op.replace("_", " "))
    verdict = "meets" if ok else "does not meet"
    reason = f"{key} = {actual!r} {verdict} {shown} {expected!r}".replace(" None", "")
    return ConditionResult(MET if ok else UNMET, used=used, reasons=[reason])


def evaluate_condition(
    condition: Mapping[str, Any], facts: Mapping[str, Any], *, prefix: str = ""
) -> ConditionResult:
    if "all" in condition or "any" in condition:
        branch = "all" if "all" in condition else "any"
        parts = [evaluate_condition(c, facts, prefix=prefix) for c in condition[branch]]
        statuses = {p.status for p in parts}
        if branch == "all":
            status = UNMET if UNMET in statuses else UNKNOWN if UNKNOWN in statuses else MET
        else:
            status = MET if MET in statuses else UNKNOWN if UNKNOWN in statuses else UNMET
        result = ConditionResult(status)
        for part in parts:
            result.used |= part.used
            result.missing += [m for m in part.missing if m not in result.missing]
            result.reasons += part.reasons
        return result
    return _leaf(condition, facts, prefix)


# --- assessment ----------------------------------------------------------------------------


@dataclass
class Assessment:
    target: GNode
    checks: list[ReasoningInput]
    overall: Literal["ready", "needs_information", "blocked", "not_eligible"]
    next_step: NextStep


class _Facts:
    """Fact lookups that remember which keys were read or found missing."""

    def __init__(self, facts: Mapping[str, Any], labels: Mapping[str, str | None]) -> None:
        self.facts = facts
        self.labels = labels

    def use(self, key: str) -> FactUse:
        provided = key in self.facts and self.facts[key] is not None
        return FactUse(
            key=key,
            label=self.labels.get(key) or fact_label(key.split(".", 1)[-1]) or fact_label(key),
            value=self.facts.get(key) if provided else None,
            provided=provided,
        )

    def flag(self, key: str) -> bool | None:
        value = self.facts.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "held", "done", "completed"}:
                return True
            if lowered in {"false", "no", "missing", "not_done"}:
                return False
            return None
        return bool(value)


class RequirementEvaluator:
    def __init__(
        self,
        graph: GovernanceSubgraph,
        facts: Mapping[str, Any],
        *,
        subject: str | None = None,
        fact_labels: Mapping[str, str | None] | None = None,
    ) -> None:
        self.graph = graph
        self.facts = _Facts(facts, fact_labels or {})
        self.subject = subject

    # -- helpers ----------------------------------------------------------------------------

    def _prefix(self, edge: GEdge | None, key: str = "party") -> str:
        """Fact prefix for an edge: beneficiary facts are read as `<subject>.<fact>`.
        `key="when_party"` lets an edge's condition read a different party's facts (a
        household document that applies only when the beneficiary is a spouse)."""
        properties = edge.properties if edge else {}
        party = properties.get(key) or properties.get("party") or "applicant"
        return f"{self.subject}." if self.subject and party == "beneficiary" else ""

    def _condition_of(
        self, edge: GEdge, prefix: str
    ) -> tuple[CheckStatus | None, list[FactUse], str]:
        """Evaluate an edge's `properties.when`: (None if unconditional, uses, note)."""
        when = edge.properties.get("when")
        if not isinstance(when, Mapping):
            return None, [], ""
        if "when_party" in edge.properties:
            prefix = self._prefix(edge, "when_party")
        result = evaluate_condition(when, self.facts.facts, prefix=prefix)
        keys = list(result.used) + [m for m in result.missing if m not in result.used]
        reasons = "; ".join(result.reasons)
        note = {
            MET: f" This applies to you ({reasons}).",
            UNKNOWN: f" This applies only in some cases ({reasons}).",
            UNMET: "",
        }[result.status]
        return result.status, [self.facts.use(k) for k in keys], note

    @staticmethod
    def _gate(status: CheckStatus, when: CheckStatus | None) -> CheckStatus:
        """A check that may not apply cannot block: UNMET becomes UNKNOWN."""
        return UNKNOWN if when is UNKNOWN and status is UNMET else status

    def _issuer_task(
        self, target: GNode, uses: list[FactUse], prefix: str
    ) -> JourneyTaskRef | None:
        """For an open requirement that holding a document would satisfy, the service that
        issues that document (e.g. adequate housing -> register the lease in Tawtheeq)."""
        for fact in uses:
            doc_prefix = prefix + "documents."
            if fact.provided or not fact.key.startswith(doc_prefix):
                continue
            document = self.graph.by_key.get("document." + fact.key.removeprefix(doc_prefix))
            if document is None:
                continue
            producers = [p for p in self.graph.producers_of(document) if p.id != target.id]
            if producers:
                return self._task(producers[0])
        return None

    def _task(self, service: GNode) -> JourneyTaskRef:
        return JourneyTaskRef(key=service.key, title=service.label, node_id=service.id)

    def service_state(self, service: GNode, prefix: str) -> tuple[CheckStatus, list[FactUse]]:
        """Is `service` done? `completed.<service>`, or holding a document it produces."""
        key = prefix + completed_fact(service.key)
        flag = self.facts.flag(key)
        if flag is not None:
            return (MET if flag else UNMET), [self.facts.use(key)]
        for _, document in self.graph.out(service, "produces"):
            doc_key = prefix + document_fact(document.key)
            if self.facts.flag(doc_key):
                return MET, [self.facts.use(doc_key)]
        return UNKNOWN, [self.facts.use(key)]

    def document_state(self, document: GNode, prefix: str) -> tuple[CheckStatus, list[FactUse]]:
        key = prefix + document_fact(document.key)
        flag = self.facts.flag(key)
        if flag is not None:
            return (MET if flag else UNMET), [self.facts.use(key)]
        for producer in self.graph.producers_of(document):
            done_key = prefix + completed_fact(producer.key)
            if self.facts.flag(done_key):
                return MET, [self.facts.use(done_key)]
        return UNKNOWN, [self.facts.use(key)]

    def _condition_check(
        self, owner: GNode, prefix: str
    ) -> tuple[CheckStatus, list[FactUse], dict[str, Any] | None, str]:
        if owner.properties.get("informational"):
            note = owner.properties.get("note") or "The authority checks this while processing."
            return CheckStatus.INFORMATIONAL, [], None, str(note)
        condition = owner.properties.get("condition")
        if isinstance(condition, Mapping):
            result = evaluate_condition(condition, self.facts.facts, prefix=prefix)
            keys = list(result.used)
            if result.status is UNKNOWN:  # only an undecided rule needs the missing facts
                keys += [m for m in result.missing if m not in result.used]
            explanation = "; ".join(result.reasons) or "Evaluated against your facts."
            return result.status, [self.facts.use(k) for k in keys], dict(condition), explanation
        key = prefix + "meets." + owner.key.split(".", 1)[-1]
        flag = self.facts.flag(key)
        if flag is None:
            return UNKNOWN, [self.facts.use(key)], None, "ADAPT needs you to confirm this."
        explanation = "You confirmed this." if flag else "You told us this is not met."
        return (MET if flag else UNMET), [self.facts.use(key)], None, explanation

    # -- dependencies ------------------------------------------------------------------------

    def _alternative(
        self, dependency: GNode, prefix: str
    ) -> tuple[CheckStatus, GNode | None, list[FactUse], str]:
        """Resolve an OR-group: which alternative satisfies it, or which one applies."""
        options = self.graph.out(dependency, "satisfied_by")
        if not options:
            return UNKNOWN, None, [], "No satisfying service is recorded."
        uses: list[FactUse] = []
        for _, service in options:
            state, used = self.service_state(service, prefix)
            if state is MET:
                return MET, service, used, f"Satisfied by {service.label}."
        selected: list[GNode] = []
        undecided_facts: list[FactUse] = []
        for edge, service in options:
            when = edge.properties.get("when")
            if not isinstance(when, Mapping):
                continue
            result = evaluate_condition(when, self.facts.facts)
            if result.status is MET:
                selected.append(service)
            elif result.status is UNKNOWN:
                undecided_facts += [self.facts.use(k) for k in result.missing]
        if len(selected) == 1:
            state, used = self.service_state(selected[0], prefix)
            reason = f"For your situation this means {selected[0].label}."
            return state, selected[0], used, reason
        uses += undecided_facts
        names = " or ".join(service.label for _, service in options)
        return UNKNOWN, None, _unique(uses), f"Satisfied by any one of: {names}."

    def earliest_prerequisite(
        self, service: GNode, prefix: str, _seen: frozenset[UUID] = frozenset()
    ) -> GNode:
        """The first not-yet-done service on the way to `service` (depth-first, in order)."""
        if service.id in _seen or len(_seen) > MAX_DEPTH:
            return service
        seen = _seen | {service.id}
        for edge, target in self.graph.out(service, "depends_on"):
            edge_prefix = self._prefix(edge) or prefix
            if self._condition_of(edge, edge_prefix)[0] is UNMET:
                continue
            if target.entity_type == "dependency":
                state, chosen, _, _ = self._alternative(target, edge_prefix)
                if state is MET:
                    continue
                if chosen is not None:
                    return self.earliest_prerequisite(chosen, edge_prefix, seen)
                continue  # which path applies is unknown: the caller asks for information
            state, _ = self.service_state(target, edge_prefix)
            if state is not MET:
                return self.earliest_prerequisite(target, edge_prefix, seen)
        return service

    def chain_depth(self, service: GNode, prefix: str, _seen: frozenset[UUID] = frozenset()) -> int:
        """Length of the longest chain of not-yet-done prerequisites below `service`."""
        if service.id in _seen or len(_seen) > MAX_DEPTH:
            return 0
        best = 0
        for edge, target in self.graph.out(service, "depends_on"):
            edge_prefix = self._prefix(edge) or prefix
            if self._condition_of(edge, edge_prefix)[0] is UNMET:
                continue
            if target.entity_type == "dependency":
                state, chosen, _, _ = self._alternative(target, edge_prefix)
                if state is MET or chosen is None:
                    continue
                target = chosen
            elif self.service_state(target, edge_prefix)[0] is MET:
                continue
            best = max(best, 1 + self.chain_depth(target, edge_prefix, _seen | {service.id}))
        return best

    # -- the assessment ----------------------------------------------------------------------

    def assess(self, target: GNode) -> Assessment:
        checks: list[ReasoningInput] = []
        g = self.graph
        target_task = self._task(target)

        for edge, rule in g.inc(target, "applies_to"):
            status, uses, condition, explanation = self._condition_check(rule, self._prefix(edge))
            checks.append(
                ReasoningInput(
                    id=f"chk_eligibility_{rule.key}",
                    kind=CheckKind.ELIGIBILITY,
                    status=status,
                    statement=rule.summary or rule.label,
                    explanation=explanation,
                    node_id=rule.id,
                    node_key=rule.key,
                    edge_id=edge.id,
                    facts=uses,
                    condition=condition,
                    task=target_task,
                )
            )

        task: JourneyTaskRef | None
        for edge, needed in g.out(target, "requires"):
            prefix = self._prefix(edge)
            when, when_uses, when_note = self._condition_of(edge, prefix)
            if when is UNMET:
                continue  # a conditional requirement that does not apply to this person
            whose = " (for the person being sponsored)" if prefix else ""
            if needed.entity_type == "document":
                status, uses = self.document_state(needed, prefix)
                status, uses = self._gate(status, when), uses + when_uses
                producers = [p for p in g.producers_of(needed) if p.id != target.id]
                task = self._task(producers[0]) if producers else target_task
                via = f" It is issued by: {producers[0].label}." if producers else ""
                explanation = {
                    MET: "You have this document.",
                    UNMET: "You told us you don't have this document yet." + via,
                    UNKNOWN: "ADAPT doesn't know yet whether you have this document." + via,
                }[status] + when_note
                checks.append(
                    ReasoningInput(
                        id=f"chk_document_{needed.key}",
                        kind=CheckKind.DOCUMENT,
                        status=status,
                        statement=f"{target.label} requires {needed.label}{whose}",
                        explanation=explanation,
                        node_id=needed.id,
                        node_key=needed.key,
                        edge_id=edge.id,
                        facts=uses,
                        task=task,
                    )
                )
            elif needed.entity_type in {"requirement", "eligibility_rule"}:
                status, uses, condition, explanation = self._condition_check(needed, prefix)
                status, uses = self._gate(status, when), uses + when_uses
                explanation += when_note
                requirement_task = self._issuer_task(target, uses, prefix) or target_task
                checks.append(
                    ReasoningInput(
                        id=f"chk_requirement_{needed.key}",
                        kind=CheckKind.REQUIREMENT,
                        status=status,
                        statement=f"{target.label} requires: {needed.summary or needed.label}",
                        explanation=explanation,
                        node_id=needed.id,
                        node_key=needed.key,
                        edge_id=edge.id,
                        facts=uses,
                        condition=condition,
                        task=requirement_task,
                    )
                )

        for edge, prerequisite in g.out(target, "depends_on"):
            prefix = self._prefix(edge)
            when, when_uses, when_note = self._condition_of(edge, prefix)
            if when is UNMET:
                continue
            if prerequisite.entity_type == "dependency":
                status, chosen, uses, explanation = self._alternative(prerequisite, prefix)
                task = self._task(chosen) if chosen else None
            else:
                status, uses = self.service_state(prerequisite, prefix)
                task = self._task(prerequisite)
                explanation = {
                    MET: "Already completed.",
                    UNMET: "Not completed yet: this comes first.",
                    UNKNOWN: "ADAPT doesn't know yet whether this is done; it comes first.",
                }[status]
            status, uses = self._gate(status, when), uses + when_uses
            explanation += when_note
            checks.append(
                ReasoningInput(
                    id=f"chk_dependency_{prerequisite.key}",
                    kind=CheckKind.DEPENDENCY,
                    status=status,
                    statement=f"{target.label} comes after {prerequisite.label}",
                    explanation=explanation,
                    node_id=prerequisite.id,
                    node_key=prerequisite.key,
                    edge_id=edge.id,
                    facts=uses,
                    task=task,
                )
            )

        done, done_uses = self.service_state(target, "")
        for edge, appointment in g.out(target, "may_require"):
            checks.append(
                ReasoningInput(
                    id=f"chk_appointment_{appointment.key}",
                    kind=CheckKind.APPOINTMENT,
                    status=MET if done is MET else UNKNOWN,
                    statement=f"{target.label} may need an appointment: {appointment.label}",
                    explanation=(
                        "The service is already completed."
                        if done is MET
                        else "Plan this visit. Use the official channel to book."
                    ),
                    node_id=appointment.id,
                    node_key=appointment.key,
                    edge_id=edge.id,
                    facts=done_uses,
                    task=target_task,
                )
            )

        overall = _overall(checks)
        return Assessment(target, checks, overall, self._next_step(target, checks))

    # -- next step ---------------------------------------------------------------------------

    def _step(
        self,
        action: NextAction,
        title: str,
        detail: str,
        node: GNode,
        service: GNode,
        checks: list[ReasoningInput],
        missing: list[str] | None = None,
    ) -> NextStep:
        portal = self.graph.portal_of(service)
        requires_pass = bool(
            service.properties.get("requires_uae_pass")
            or (portal is not None and portal.properties.get("requires_uae_pass"))
        )
        return NextStep(
            action=action,
            title=title,
            detail=detail,
            node_id=node.id,
            task=self._task(service) if service.entity_type == "service" else None,
            portal=(
                PortalRef(node_id=portal.id, label=portal.label, url=portal.official_url)
                if portal
                else None
            ),
            official_url=service.official_url,
            requires_uae_pass=requires_pass,
            missing_facts=missing or [],
            check_ids=[c.id for c in checks],
        )

    def _edge(self, check: ReasoningInput) -> GEdge:
        return next(e for e in self.graph.edges if e.id == check.edge_id)

    def _next_step(self, target: GNode, checks: list[ReasoningInput]) -> NextStep:
        def of(kind: CheckKind, *statuses: CheckStatus) -> list[ReasoningInput]:
            return [c for c in checks if c.kind is kind and c.status in statuses]

        def missing(items: list[ReasoningInput]) -> list[str]:
            return _unique_keys(f.key for c in items for f in c.facts if not f.provided)

        if failed := of(CheckKind.ELIGIBILITY, UNMET):
            return self._step(
                NextAction.REVIEW_ELIGIBILITY,
                f"Check your eligibility for {target.label}",
                "Based on what you told ADAPT, an eligibility rule is not met: "
                + " ".join(c.explanation for c in failed)
                + " Confirm the current rule with the authority before you apply.",
                self.graph.nodes[failed[0].node_id],
                target,
                failed,
            )
        if unknown := of(CheckKind.ELIGIBILITY, UNKNOWN):
            return self._step(
                NextAction.PROVIDE_INFORMATION,
                "Tell ADAPT a few details to check eligibility",
                f"ADAPT needs this information to check the eligibility rules for {target.label}.",
                self.graph.nodes[unknown[0].node_id],
                target,
                unknown,
                missing(unknown),
            )
        issued_elsewhere = [
            c
            for c in of(CheckKind.DOCUMENT, UNMET, UNKNOWN)
            if c.task is not None and c.task.node_id != target.id
        ]
        if pending := of(CheckKind.DEPENDENCY, UNMET, UNKNOWN) + issued_elsewhere:
            # Undecided paths first (ADAPT must ask), then the sponsor's own steps (they gate
            # everything for the people they sponsor), then the longest chain (critical path).
            def urgency(check: ReasoningInput) -> tuple[int, int, int, str]:
                if check.task is None:
                    return (0, 0, 0, check.statement)
                edge = self._edge(check)
                service = self.graph.nodes[check.task.node_id]
                sponsor_first = 0 if edge.properties.get("party") == "sponsor" else 1
                depth = self.chain_depth(service, self._prefix(edge))
                return (1, sponsor_first, -depth, check.statement)

            pending.sort(key=urgency)
            first = pending[0]
            node = self.graph.nodes[first.node_id]
            if first.task is None:  # an OR-group whose relevant path is not known yet
                return self._step(
                    NextAction.PROVIDE_INFORMATION,
                    f"Tell ADAPT which path applies: {node.label}",
                    first.explanation,
                    node,
                    target,
                    [first],
                    missing([first]),
                )
            service = self.graph.nodes[first.task.node_id]
            step_service = self.earliest_prerequisite(service, self._prefix(self._edge(first)))
            path = (
                f" The first step on that path is {step_service.label}."
                if step_service.id != service.id
                else ""
            )
            if first.kind is CheckKind.DOCUMENT:
                return self._step(
                    NextAction.OBTAIN_DOCUMENT
                    if step_service.id == service.id
                    else NextAction.COMPLETE_PREREQUISITE,
                    f"Start with: {step_service.label}",
                    f"{target.label} needs {node.label}, which comes from {service.label}.{path}",
                    step_service,
                    step_service,
                    [first],
                    missing([first]),
                )
            return self._step(
                NextAction.COMPLETE_PREREQUISITE,
                f"Start with: {step_service.label}",
                f"{target.label} comes after {service.label}."
                + (path or " Complete it on the official channel first."),
                step_service,
                step_service,
                [first],
                missing([first]),
            )
        if needs := of(CheckKind.REQUIREMENT, UNMET, UNKNOWN):
            return self._step(
                NextAction.PROVIDE_INFORMATION,
                f"Confirm the requirements for {target.label}",
                " ".join(c.statement + "." for c in needs),
                self.graph.nodes[needs[0].node_id],
                target,
                needs,
                missing(needs),
            )
        if documents := of(CheckKind.DOCUMENT, UNMET, UNKNOWN):
            first = documents[0]
            document = self.graph.nodes[first.node_id]
            producer = self.graph.nodes[first.task.node_id] if first.task else target
            names = ", ".join(self.graph.nodes[c.node_id].label for c in documents)
            return self._step(
                NextAction.OBTAIN_DOCUMENT,
                f"Get your documents ready: {names}",
                (
                    f"{document.label} is issued through {producer.label}."
                    if producer.id != target.id
                    else f"Upload or confirm {document.label} so ADAPT can check it."
                ),
                document,
                producer,
                documents,
                missing(documents),
            )
        appointments = of(CheckKind.APPOINTMENT, UNKNOWN)
        if appointments:
            appointment = self.graph.nodes[appointments[0].node_id]
            portal = self.graph.portal_of(appointment)
            step = self._step(
                NextAction.BOOK_APPOINTMENT,
                f"Book: {appointment.label}",
                f"{target.label} may need this in-person step. Book it on the official channel.",
                appointment,
                target,
                appointments,
            )
            if portal is not None:
                step.portal = PortalRef(
                    node_id=portal.id, label=portal.label, url=portal.official_url
                )
            return step
        return self._step(
            NextAction.APPLY,
            f"Apply for {target.label}",
            "Everything ADAPT knows about is in place. You complete the application on "
            "the official channel.",
            target,
            target,
            [c for c in checks if c.status is MET],
        )


def _overall(
    checks: list[ReasoningInput],
) -> Literal["ready", "needs_information", "blocked", "not_eligible"]:
    blocking = [c for c in checks if c.kind is not CheckKind.APPOINTMENT]
    if any(c.kind is CheckKind.ELIGIBILITY and c.status is UNMET for c in blocking):
        return "not_eligible"
    if any(c.status is UNMET for c in blocking):
        return "blocked"
    if any(c.status is UNKNOWN for c in blocking):
        return "needs_information"
    return "ready"


def _unique(uses: list[FactUse]) -> list[FactUse]:
    seen: dict[str, FactUse] = {}
    for use in uses:
        seen.setdefault(use.key, use)
    return list(seen.values())


def _unique_keys(keys: Any) -> list[str]:
    return list(dict.fromkeys(keys))
