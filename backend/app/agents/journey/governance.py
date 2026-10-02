"""A read-only, in-memory view of the governance graph for planning.

Relations (see app/domain/enums.GraphEdgeType):
  authority -provides-> service          service -available_at-> portal
  service -requires-> document | requirement | eligibility_rule
  service -depends_on-> service | dependency      (AND over targets)
  dependency -satisfied_by-> service              (OR; `properties.when` selects one)
  service -produces-> document           service -may_require-> appointment
  eligibility_rule -applies_to-> service

Edges may carry `properties.party` (beneficiary | sponsor | household): whose document or
step the target is when the service is done for someone else (spouse sponsorship).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.agents.journey.state import GovEdge, GovernanceContext, GovNode

PROVIDES = "provides"
REQUIRES = "requires"
DEPENDS_ON = "depends_on"
SATISFIED_BY = "satisfied_by"
PRODUCES = "produces"
APPLIES_TO = "applies_to"
AVAILABLE_AT = "available_at"
MAY_REQUIRE = "may_require"

# Relations followed (forwards) when collecting the subgraph a plan can touch.
_FORWARD = (REQUIRES, DEPENDS_ON, SATISFIED_BY, AVAILABLE_AT, MAY_REQUIRE)


@dataclass(frozen=True)
class GovernanceSnapshot:
    nodes: dict[str, GovNode]
    edges: list[GovEdge]
    _out: dict[str, list[GovEdge]] = field(default_factory=dict, repr=False, compare=False)
    _in: dict[str, list[GovEdge]] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        for edge in self.edges:
            self._out.setdefault(edge["source"], []).append(edge)
            self._in.setdefault(edge["target"], []).append(edge)

    # --- construction ---------------------------------------------------------------
    @classmethod
    def of(cls, nodes: Iterable[GovNode], edges: Iterable[GovEdge]) -> GovernanceSnapshot:
        return cls(nodes={n["key"]: n for n in nodes}, edges=list(edges))

    @classmethod
    def from_context(cls, context: GovernanceContext) -> GovernanceSnapshot:
        return cls(nodes=dict(context["nodes"]), edges=list(context["edges"]))

    # --- lookups -----------------------------------------------------------------------
    def node(self, key: str) -> GovNode | None:
        return self.nodes.get(key)

    def type_of(self, key: str) -> str | None:
        node = self.nodes.get(key)
        return node["type"] if node else None

    def out(self, key: str, relation: str | None = None) -> list[GovEdge]:
        edges = self._out.get(key, [])
        return [e for e in edges if relation is None or e["relation"] == relation]

    def into(self, key: str, relation: str | None = None) -> list[GovEdge]:
        edges = self._in.get(key, [])
        return [e for e in edges if relation is None or e["relation"] == relation]

    def producers_of(self, document_key: str) -> list[str]:
        return sorted(e["source"] for e in self.into(document_key, PRODUCES))

    def authority_of(self, service_key: str) -> GovNode | None:
        for edge in self.into(service_key, PROVIDES):
            return self.nodes.get(edge["source"])
        return None

    def portal_of(self, service_key: str) -> GovNode | None:
        for edge in self.out(service_key, AVAILABLE_AT):
            return self.nodes.get(edge["target"])
        return None

    def rules_for(self, service_key: str) -> list[GovNode]:
        rules = [self.nodes.get(e["source"]) for e in self.into(service_key, APPLIES_TO)]
        rules += [
            self.nodes.get(e["target"])
            for e in self.out(service_key, REQUIRES)
            if self.type_of(e["target"]) == "eligibility_rule"
        ]
        seen: dict[str, GovNode] = {r["key"]: r for r in rules if r is not None}
        return [seen[k] for k in sorted(seen)]

    def requires_login(self, service_key: str) -> bool:
        node = self.nodes.get(service_key)
        portal = self.portal_of(service_key)
        props: dict[str, Any] = {
            **(portal["properties"] if portal else {}),
            **(node["properties"] if node else {}),
        }
        return bool(props.get("requires_uae_pass") or props.get("requires_login"))

    # --- subgraphs ---------------------------------------------------------------------
    def reachable(self, roots: Iterable[str]) -> set[str]:
        """Every node a plan rooted at `roots` can touch: prerequisites, requirements,
        producers of required documents, portals, authorities and eligibility rules."""
        seen: set[str] = set()
        stack = [r for r in roots if r in self.nodes]
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            for edge in self._out.get(key, []):
                if edge["relation"] in _FORWARD:
                    stack.append(edge["target"])
            if self.type_of(key) == "document":
                stack.extend(self.producers_of(key))
            for edge in self._in.get(key, []):
                if edge["relation"] in (PROVIDES, APPLIES_TO):
                    stack.append(edge["source"])
        return seen

    def context(self, roots: list[str], notes: list[str]) -> GovernanceContext:
        keys = self.reachable(roots)
        return GovernanceContext(
            root_services=list(roots),
            nodes={k: self.nodes[k] for k in sorted(keys)},
            edges=[e for e in self.edges if e["source"] in keys and e["target"] in keys],
            notes=list(notes),
        )
