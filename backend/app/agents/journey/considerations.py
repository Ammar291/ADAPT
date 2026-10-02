"""Things you may not have considered: cited findings over a saved plan (pure; no DB).

A consideration is neither a risk (nothing is wrong) nor a step (nothing new to do). It
points out a consequence of the rules that is easy to miss, usually an order that only
shows when two areas of life meet, such as housing and a spouse's visa. Each rule reads the
plan the agent produced (tasks, requirements, facts, evidence) and the governance nodes it
came from. The rule must cite official passages the plan already holds, or nothing is shown:
no citation, no consideration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypedDict

from app.agents.journey.facts import fact_ids_for
from app.agents.journey.state import GovNode, UserFact


class Consideration(TypedDict):
    id: str
    title: str
    detail: str
    area: str
    task_keys: list[str]
    governance_keys: list[str]
    evidence_ids: list[str]
    fact_keys: list[str]
    fact_ids: list[str]


class _Plan:
    """Read helpers over a plan snapshot (see nodes/human.py `plan_snapshot`)."""

    def __init__(self, plan: Mapping[str, Any], nodes: Mapping[str, GovNode]) -> None:
        self.nodes = nodes
        self.tasks: dict[str, dict[str, Any]] = {t["key"]: t for t in plan.get("tasks", [])}
        self.requirements: list[dict[str, Any]] = list(plan.get("requirements", []))
        self.evidence: list[dict[str, Any]] = list(plan.get("evidence", []))
        self.facts: dict[str, UserFact] = {f["key"]: f for f in plan.get("facts", [])}

    def open_tasks(self, node_key: str) -> list[dict[str, Any]]:
        return [
            t
            for t in self.tasks.values()
            if t["node_key"] == node_key and t["status"] not in ("done", "not_applicable")
        ]

    def requirement(self, node_key: str) -> dict[str, Any] | None:
        return next((r for r in self.requirements if r["node_key"] == node_key), None)

    def cited(self, governance_keys: list[str]) -> list[str]:
        """Evidence ids with an official URL for these governance keys, passages first."""
        wanted = set(governance_keys)
        found = [
            e for e in self.evidence if e.get("governance_key") in wanted and e.get("source_url")
        ]
        found.sort(key=lambda e: (e.get("kind") != "official_passage", e["id"]))
        return [e["id"] for e in found]

    def condition_mentions(self, node_key: str, fact_key: str) -> bool:
        node = self.nodes.get(node_key)
        return node is not None and fact_key in repr(node["properties"].get("condition"))


def _make(
    plan: _Plan,
    ident: str,
    title: str,
    detail: str,
    area: str,
    task_keys: list[str],
    governance_keys: list[str],
    fact_keys: list[str],
) -> Consideration | None:
    evidence = plan.cited(governance_keys)
    if not evidence:
        return None
    keys = [k for k in dict.fromkeys(task_keys) if k in plan.tasks]
    return Consideration(
        id=f"consideration:{ident}",
        title=title,
        detail=detail,
        area=area,
        task_keys=keys,
        governance_keys=list(dict.fromkeys(governance_keys)),
        evidence_ids=evidence,
        fact_keys=fact_keys,
        fact_ids=fact_ids_for(plan.facts, fact_keys),
    )


def attestation_abroad(plan: _Plan) -> Consideration | None:
    """A foreign certificate is attested where it was issued before UAE MoFA will attest it
    (requirement.home_country_attestation -> service.uae_mission_attestation)."""
    mission = plan.open_tasks("service.uae_mission_attestation")
    if not mission:
        return None
    home = plan.requirement("requirement.home_country_attestation")
    home_done = home is not None and home["status"] == "satisfied"
    family = [t["key"] for t in plan.open_tasks("service.family_residence_visa")]
    tasks = [
        "appointment.uae_mission_visit",
        mission[0]["key"],
        "service.mofa_attestation",
        "requirement.home_country_attestation",
        *family,
    ]
    keys = [
        "requirement.home_country_attestation",
        "service.uae_mission_attestation",
        "appointment.uae_mission_visit",
        "service.mofa_attestation",
    ]
    tail = (
        " Your spouse's residence visa needs the attested certificate."
        if family
        else " The UAE needs the attested certificate."
    )
    if home_done:
        return _make(
            plan,
            "attestation_abroad",
            "The next attestation stamp is added where your certificate was issued",
            "ADAPT read that your marriage certificate already carries the issuing country's "
            "foreign-ministry attestation. The next stamp comes from the UAE mission in that "
            "country, and UAE MoFA attests the certificate only after it, so plan the mission "
            "step before you fly." + tail,
            "family",
            tasks,
            keys,
            ["meets.home_country_attestation"],
        )
    return _make(
        plan,
        "attestation_abroad",
        "Your certificate's attestation starts in the country that issued it",
        "UAE MoFA only attests a foreign certificate after the issuing country's foreign "
        "ministry and the UAE mission there have attested it. Both of those steps happen "
        "where it was issued, so start them before you fly." + tail,
        "family",
        tasks,
        keys,
        [],
    )


def lease_before_family_visa(plan: _Plan) -> Consideration | None:
    """The family visa's housing proof is a registered lease when renting, and registering
    a lease (Tawtheeq) needs the sponsor's own residence documents first. The planner can't
    draw this edge (an owner proves housing differently), so it is pointed out instead."""
    family = plan.open_tasks("service.family_residence_visa")
    housing = plan.requirement("requirement.family_accommodation")
    tawtheeq = plan.open_tasks("service.tawtheeq")
    if not family or housing is None or housing["status"] == "satisfied" or not tawtheeq:
        return None
    if not plan.condition_mentions(
        "requirement.family_accommodation", "documents.tenancy_contract_registered"
    ):
        return None
    before = [plan.tasks[k] for k in tawtheeq[0].get("depends_on", []) if k in plan.tasks]
    if not before:
        return None
    steps = " and ".join(t["title"][0].lower() + t["title"][1:] for t in before)
    return _make(
        plan,
        "lease_before_family_visa",
        "Your spouse's visa waits on a registered lease, and the lease waits on your own visa",
        "ICP asks a sponsor for housing that fits the family, shown by a certified lease or "
        "proof of ownership. If you rent, that proof is a lease registered in Tawtheeq, and "
        f"Tawtheeq comes only after these steps: {steps}. So your own residence comes first, "
        "then a lease registered in your name, then your spouse's visa. Choose a home with "
        "room for both of you before you sign.",
        "housing",
        [
            *(t["key"] for t in before),
            tawtheeq[0]["key"],
            *(t["key"] for t in plan.tasks.values() if t["node_key"] == housing["node_key"]),
            *(t["key"] for t in family),
        ],
        ["requirement.family_accommodation", "service.tawtheeq"],
        ["household.move_with_spouse"],
    )


RULES: tuple[Callable[[_Plan], Consideration | None], ...] = (
    attestation_abroad,
    lease_before_family_visa,
)


def detect_considerations(
    plan: Mapping[str, Any], governance_nodes: Mapping[str, GovNode]
) -> list[Consideration]:
    view = _Plan(plan, governance_nodes)
    return [c for rule in RULES if (c := rule(view)) is not None]
