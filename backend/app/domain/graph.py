"""Knowledge-graph typing rules (mirrored by a database trigger on `graph_edges`).

Two logical graphs share the `graph_nodes` / `graph_edges` tables (`graph_type`):

* governance -> governance edges describe public institutional knowledge.
* user -> user edges describe a single user's private situation (their digital twin).
* user -> governance edges personalise ("my goal PURSUES this service"). They are
  private: they live in the user graph and carry the user's ownership.

A governance edge may never touch a user node — otherwise public graph queries could
reveal private nodes.
"""

from __future__ import annotations

from app.domain.enums import GovernanceNodeType, GraphEdgeType, GraphType, TwinNodeType

GOVERNANCE_EDGE_TYPES: frozenset[GraphEdgeType] = frozenset(
    {
        GraphEdgeType.PROVIDES,
        GraphEdgeType.REQUIRES,
        GraphEdgeType.DEPENDS_ON,
        GraphEdgeType.SATISFIED_BY,
        GraphEdgeType.PRODUCES,
        GraphEdgeType.APPLIES_TO,
        GraphEdgeType.AVAILABLE_AT,
        GraphEdgeType.MAY_REQUIRE,
        GraphEdgeType.GOVERNED_BY,
        GraphEdgeType.LOCATED_IN,
    }
)

TWIN_INTERNAL_EDGE_TYPES: frozenset[GraphEdgeType] = frozenset(
    {
        GraphEdgeType.HAS_HOUSEHOLD_MEMBER,
        GraphEdgeType.MEMBER_OF,
        GraphEdgeType.HAS_DOCUMENT,
        GraphEdgeType.HOLDS_VISA,
        GraphEdgeType.HAS_NATIONALITY,
        GraphEdgeType.HAS_GOAL,
        GraphEdgeType.PREFERS,
        GraphEdgeType.SEEKS,
        GraphEdgeType.FOUNDER_OF,
        GraphEdgeType.ENGAGES_IN,
        GraphEdgeType.SPEAKS,
        GraphEdgeType.HAS_BUDGET,
        GraphEdgeType.HAS_APPOINTMENT,
    }
)

CROSS_GRAPH_EDGE_TYPES: frozenset[GraphEdgeType] = frozenset(
    {
        GraphEdgeType.PURSUES,
        GraphEdgeType.SATISFIES,
        GraphEdgeType.INSTANCE_OF,
        GraphEdgeType.ELIGIBLE_FOR,
        GraphEdgeType.BLOCKED_BY,
    }
)

GOVERNANCE_NODE_TYPES = frozenset(t.value for t in GovernanceNodeType)
TWIN_NODE_TYPES = frozenset(t.value for t in TwinNodeType)


class GraphRuleError(ValueError):
    pass


def edge_graph_type(relation: GraphEdgeType, source: GraphType, target: GraphType) -> GraphType:
    """Return the graph an edge must be stored in, or raise if the combination is illegal."""
    if relation in GOVERNANCE_EDGE_TYPES:
        if source is GraphType.GOVERNANCE and target is GraphType.GOVERNANCE:
            return GraphType.GOVERNANCE
        raise GraphRuleError(f"{relation.value} edges must connect two governance nodes")
    if relation in TWIN_INTERNAL_EDGE_TYPES:
        if source is GraphType.USER and target is GraphType.USER:
            return GraphType.USER
        raise GraphRuleError(f"{relation.value} edges must connect two user-graph nodes")
    if relation in CROSS_GRAPH_EDGE_TYPES:
        if source is GraphType.USER and target is GraphType.GOVERNANCE:
            return GraphType.USER
        raise GraphRuleError(
            f"{relation.value} edges must go from a user-graph node to a governance node"
        )
    raise GraphRuleError(f"unknown edge type '{relation}'")
