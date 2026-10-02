"""Topology of the journey and what-if graphs, derived from the node specs the graph
builders use, so the drawing can't drift from what actually runs.

Served at GET /api/agents/journey/topology and GET /api/agents/what_if/topology. The
frontend lights nodes up from `node_*` events and draws the what-if graph as a branch
off the base pipeline.
"""

from __future__ import annotations

from itertools import pairwise

from app.agents.journey.nodes import JOURNEY_SEQUENCE
from app.agents.journey.simulation import SIMULATION_NODE_SPECS
from app.agents.journey.spec import NodeSpec, spec_of
from app.agents.journey.vocab import NodeId
from app.contracts.agents import AgentTopology, TopologyEdge, TopologyNode

JOURNEY_SPECS: tuple[NodeSpec, ...] = tuple(spec_of(n) for n in JOURNEY_SEQUENCE)
_CONDITIONS = {
    NodeId.DOCUMENT_ANALYSIS: "pauses if a document value needs checking",
    NodeId.HUMAN_APPROVAL: "pauses for your approval",
    NodeId.EXECUTION_OR_HANDOFF: "pauses for your confirmation",
}


def _node(spec: NodeSpec) -> TopologyNode:
    return TopologyNode(
        id=spec.id.value,
        label=spec.label,
        description=spec.description,
        kind=spec.kind,
        lane=spec.lane,
    )


def _journey() -> AgentTopology:
    ids = ["__start__", *(s.id.value for s in JOURNEY_SPECS), "__end__"]
    edges = [
        TopologyEdge(
            source=source,
            target=target,
            condition=_CONDITIONS.get(NodeId(source))
            if source in NodeId._value2member_map_
            else None,
        )
        for source, target in pairwise(ids)
    ]
    return AgentTopology(
        graph="journey", version="2", nodes=[_node(s) for s in JOURNEY_SPECS], edges=edges
    )


def _what_if() -> AgentTopology:
    specs = SIMULATION_NODE_SPECS
    rerunnable = [s.id.value for s in specs[1:-1]]
    compare = specs[-1].id.value
    edges = [TopologyEdge(source="__start__", target=specs[0].id.value)]
    for index, source in enumerate([specs[0].id.value, *rerunnable]):
        for target in [*rerunnable[index:], compare]:
            edges.append(
                TopologyEdge(
                    source=source,
                    target=target,
                    condition="if affected" if target != compare else "nothing else affected",
                )
            )
    edges.append(TopologyEdge(source=compare, target="__end__"))
    return AgentTopology(graph="what_if", version="1", nodes=[_node(s) for s in specs], edges=edges)


JOURNEY_TOPOLOGY = _journey()
WHAT_IF_TOPOLOGY = _what_if()
