"""Eligibility rules: three-valued evaluation of machine conditions over user facts.

Governance eligibility rules carry `properties.condition`, e.g.

    {"any": [{"fact": "finance.monthly_income_aed", "op": "gte", "value": 4000},
             {"all": [{"fact": "finance.monthly_income_aed", "op": "gte", "value": 3000},
                      {"fact": "housing.accommodation_provided", "op": "eq", "value": true}]}]}

A missing fact makes a comparison *unknown* rather than false, so ADAPT asks instead of
guessing. A rule without a machine condition is never evaluated: it stays *unknown* and
the user is pointed to the official page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.journey.facts import value_of
from app.agents.journey.state import EligibilityResult, GovernanceContext, UserFact

Truth = Literal["met", "unmet", "unknown"]

FACT_LABELS: dict[str, str] = {
    "finance.monthly_income_aed": "monthly income (AED)",
    "housing.accommodation_provided": "whether your employer provides accommodation",
    "company.jurisdiction": "where your company is licensed",
    "household.move_with_spouse": "whether your spouse is moving with you",
    "company.has_resident_signatory": "whether your company has a UAE-resident authorised "
    "signatory",
}

FACT_QUESTIONS: dict[str, str] = {
    "finance.monthly_income_aed": "What is your monthly income, in AED?",
    "housing.accommodation_provided": "Does your employer provide your accommodation?",
    "company.jurisdiction": "Will your company be on the Abu Dhabi mainland or in ADGM?",
    "company.legal_form": "What legal form will your company take (for example, an LLC)?",
    "household.move_with_spouse": "Is your spouse moving to Abu Dhabi?",
    "spouse.person.age": "How old is your spouse?",
    "company.has_resident_signatory": "Will your company have an authorised signatory who "
    "lives in the UAE?",
}


def fact_question(key: str) -> str:
    """The question to ask for a missing fact: plain language, never a raw key."""
    if key in FACT_QUESTIONS:
        return FACT_QUESTIONS[key]
    parts = key.split(".")
    name = parts[-1]
    words = name.replace("_", " ")
    if parts[0] == "spouse":
        subject, possessive, do, be, have = "your spouse", "your spouse's", "Does", "Is", "Has"
    elif len(parts) >= 2 and parts[-2] == "company":
        subject, possessive, do, be, have = "your company", "your company's", "Does", "Is", "Has"
    else:
        subject, possessive, do, be, have = "you", "your", "Do", "Are", "Have"
    if "documents" in parts:
        return f"{do} {subject} already have a {words}?"
    if "meets" in parts or "completed" in parts:
        return f"{have} {subject} already done this: {words}?"
    if name.startswith("has_") or name == "special_needs":
        return f"{do} {subject} have {'a ' + words[4:] if name.startswith('has_') else words}?"
    if name.startswith("is_") or name == "married":
        return f"{be} {subject} {words[3:] if name.startswith('is_') else words}?"
    if name.endswith("_aed"):
        return f"What is {possessive} {words[:-4]}, in AED?"
    return f"What is {possessive} {FACT_LABELS.get(key, words)}?"


_OPS: dict[str, str] = {
    "gte": "at least",
    "gt": "more than",
    "lte": "at most",
    "lt": "less than",
    "eq": "equal to",
    "ne": "not",
    "in": "one of",
}


@dataclass
class Evaluation:
    status: Truth
    missing: list[str] = field(default_factory=list)
    used: list[str] = field(default_factory=list)


def _compare(op: str, actual: Any, expected: Any) -> bool:
    try:
        match op:
            case "gte":
                return float(actual) >= float(expected)
            case "gt":
                return float(actual) > float(expected)
            case "lte":
                return float(actual) <= float(expected)
            case "lt":
                return float(actual) < float(expected)
            case "eq":
                return bool(actual == expected)
            case "ne":
                return bool(actual != expected)
            case "in":
                return actual in expected
    except (TypeError, ValueError):
        return False
    raise ValueError(f"unknown condition operator {op!r}")


def evaluate(
    condition: dict[str, Any], facts: dict[str, UserFact], *, allow_assumed: bool = False
) -> Evaluation:
    """`allow_assumed` lets planning follow an assumption (e.g. which OR-alternative to
    plan); eligibility decisions never do."""
    if "any" in condition or "all" in condition:
        is_any = "any" in condition
        parts = [
            evaluate(c, facts, allow_assumed=allow_assumed)
            for c in condition["any" if is_any else "all"]
        ]
        statuses = {p.status for p in parts}
        decisive, neutral = ("met", "unmet") if is_any else ("unmet", "met")
        if decisive in statuses:
            status: Truth = decisive  # type: ignore[assignment]
        elif statuses == {neutral}:
            status = neutral  # type: ignore[assignment]
        else:
            status = "unknown"
        # Once decided, nothing is missing: undecided branches no longer matter.
        missing = sorted({m for p in parts for m in p.missing}) if status == "unknown" else []
        return Evaluation(
            status=status, missing=missing, used=sorted({u for p in parts for u in p.used})
        )
    key = str(condition["fact"])
    actual = value_of(facts, key)
    # An assumed value is not knowledge: eligibility is never decided on a default.
    assumed = key in facts and facts[key]["source"] == "assumed" and not allow_assumed
    if actual is None or assumed:
        return Evaluation(status="unknown", missing=[key], used=[key])
    ok = _compare(str(condition["op"]), actual, condition.get("value"))
    return Evaluation(status="met" if ok else "unmet", used=[key])


def describe(condition: dict[str, Any]) -> str:
    """Plain-language rendering of a condition, for explanations."""
    if "any" in condition:
        return " or ".join(f"({describe(c)})" for c in condition["any"])
    if "all" in condition:
        return " and ".join(describe(c) for c in condition["all"])
    label = FACT_LABELS.get(str(condition["fact"]), str(condition["fact"]))
    value = condition.get("value")
    if isinstance(value, bool):
        return f"{label} is {'yes' if value else 'no'}"
    if isinstance(value, int | float):
        value = f"{value:,.0f}"
    return f"{label} {_OPS.get(str(condition['op']), condition['op'])} {value}"


def legacy_condition(properties: dict[str, Any]) -> dict[str, Any] | None:
    """Rules seeded before machine conditions existed express income thresholds as
    `threshold_aed` / `threshold_with_accommodation_aed`."""
    if "threshold_aed" not in properties:
        return None
    options: list[dict[str, Any]] = [
        {"fact": "finance.monthly_income_aed", "op": "gte", "value": properties["threshold_aed"]}
    ]
    if "threshold_with_accommodation_aed" in properties:
        options.append(
            {
                "all": [
                    {
                        "fact": "finance.monthly_income_aed",
                        "op": "gte",
                        "value": properties["threshold_with_accommodation_aed"],
                    },
                    {"fact": "housing.accommodation_provided", "op": "eq", "value": True},
                ]
            }
        )
    return {"any": options}


def condition_of(properties: dict[str, Any]) -> dict[str, Any] | None:
    condition = properties.get("condition")
    return condition if isinstance(condition, dict) else legacy_condition(properties)


def explain(
    rule: dict[str, Any],
    condition: dict[str, Any] | None,
    result: Evaluation,
    facts: dict[str, UserFact],
) -> str:
    if condition is None:
        return f"{rule['label']}: ADAPT can't check this rule automatically. See the official page."
    described = describe(condition)
    if result.status == "met":
        return f"{rule['label']}: met. The rule asks for {described}."
    if result.status == "unmet":
        stated = ", ".join(
            f"{FACT_LABELS.get(k, k)} = {value_of(facts, k)}" for k in result.used if k in facts
        )
        return f"{rule['label']}: the rule asks for {described}; you told ADAPT {stated}."
    missing = ", ".join(FACT_LABELS.get(k, k) for k in result.missing)
    return f"{rule['label']}: ADAPT needs your {missing} to check this rule ({described})."


def scope_condition(condition: dict[str, Any], subject: str) -> dict[str, Any]:
    """Rewrite a condition's fact keys to a household member (`spouse.person.age`)."""
    if "any" in condition or "all" in condition:
        op = "any" if "any" in condition else "all"
        return {op: [scope_condition(c, subject) for c in condition[op]]}
    key = str(condition["fact"])
    return {**condition, "fact": key if subject == "self" else f"{subject}.{key}"}


def implicit_facts(subject: str) -> dict[str, UserFact]:
    """What the plan's structure itself establishes: a spouse's step is for the spouse."""
    if subject != "spouse":
        return {}
    key = "spouse.person.relationship_to_sponsor"
    return {
        key: UserFact(
            key=key,
            value="spouse",
            source="user_graph",
            source_ref="plan",
            confidence=1.0,
            confirmed=True,
            fact_ids=[],
        )
    }


def assess(
    context: GovernanceContext, facts: dict[str, UserFact], subjects: dict[str, str]
) -> list[EligibilityResult]:
    """Evaluate every eligibility rule attached to a service in the plan's subgraph.

    A rule attached with `party: beneficiary` (e.g. "who a resident can sponsor") reads the
    beneficiary's facts, so it is evaluated for the household member the service is for.
    """
    from app.agents.journey.governance import APPLIES_TO, REQUIRES, GovernanceSnapshot

    snapshot = GovernanceSnapshot.from_context(context)
    results: list[EligibilityResult] = []
    services = sorted(k for k, n in context["nodes"].items() if n["type"] == "service")
    for service_key in services:
        edges = [(e["source"], e) for e in snapshot.into(service_key, APPLIES_TO)] + [
            (e["target"], e)
            for e in snapshot.out(service_key, REQUIRES)
            if snapshot.type_of(e["target"]) == "eligibility_rule"
        ]
        for rule_key, edge in sorted(edges, key=lambda item: item[0]):
            rule = snapshot.node(rule_key)
            if rule is None:
                continue
            subject = subjects.get(service_key, "self")
            party = edge["properties"].get("when_party") or edge["properties"].get("party")
            whose = subject if party == "beneficiary" else "self"
            condition = condition_of(rule["properties"])
            scoped = scope_condition(condition, whose) if condition else None
            view = {**facts, **implicit_facts(whose)}
            evaluation = evaluate(scoped, view) if scoped else Evaluation("unknown")
            results.append(
                EligibilityResult(
                    rule_key=rule["key"],
                    service_key=service_key,
                    subject=subject,
                    status=evaluation.status,
                    explanation=explain(rule, scoped, evaluation, view),  # type: ignore[arg-type]
                    missing_facts=evaluation.missing,
                    fact_keys=evaluation.used,
                    evidence_ids=[f"ref:{rule['key']}"],
                    verify_on_official_page=bool(
                        rule["properties"].get("verify_on_official_page") or condition is None
                    ),
                )
            )
    return results
