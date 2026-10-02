"""Interim governance-graph seed (`governance.yaml`), used only while the knowledge
layer's cited graph is unavailable. Idempotent: nodes are upserted by key, edges by
(source, target, relation), and governance edges not in the file are pruned."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GraphEdge, GraphNode
from app.domain.enums import EvidenceKind, GovernanceNodeType, GraphEdgeType, GraphType
from app.domain.graph import edge_graph_type
from app.domain.provenance import Citation, Provenance

SEED_FILE = Path(__file__).with_name("governance.yaml")
SEED_NOTE = "Curated summary. Confirm current requirements on the official page."


def load_seed(path: Path = SEED_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def normalise_edges(raw_edges: list[Any]) -> list[tuple[str, GraphEdgeType, str, dict[str, Any]]]:
    edges = []
    for raw in raw_edges:
        if isinstance(raw, list):
            source, relation, target = raw
            properties: dict[str, Any] = {}
        else:
            source, relation, target = raw["source"], raw["type"], raw["target"]
            properties = raw.get("properties") or {}
        edges.append((source, GraphEdgeType(relation), target, properties))
    return edges


def _provenance(node: dict[str, Any], titles: dict[str, str]) -> dict[str, Any]:
    url = node["official_url"]
    return Provenance(
        kind=EvidenceKind.OFFICIAL_GUIDANCE,
        citations=[Citation(source_url=url, source_title=titles.get(url, node["label"]))],
        confidence=0.6,
        note=SEED_NOTE,
    ).model_dump(mode="json")


async def seed_governance(session: AsyncSession, data: dict[str, Any]) -> tuple[int, int]:
    titles = {n["official_url"]: n["label"] for n in data["nodes"] if n["type"] == "authority"}
    for node in data["nodes"]:
        GovernanceNodeType(node["type"])  # validate vocabulary early
        values = {
            "graph_type": GraphType.GOVERNANCE.value,
            "entity_type": node["type"],
            "key": node["key"],
            "label": node["label"],
            "summary": node.get("summary"),
            "official_url": node.get("official_url"),
            "properties_json": node.get("properties") or {},
            "provenance": _provenance(node, titles) if node.get("official_url") else None,
            "valid_to": None,
        }
        stmt = insert(GraphNode).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[GraphNode.key],
            index_where=text("graph_type = 'governance'"),
            set_={
                k: stmt.excluded[k]
                for k in (
                    "entity_type",
                    "label",
                    "summary",
                    "official_url",
                    "properties_json",
                    "provenance",
                    "valid_to",
                )
            },
        )
        await session.execute(stmt)

    rows = await session.execute(
        select(GraphNode.key, GraphNode.id).where(GraphNode.graph_type == GraphType.GOVERNANCE)
    )
    ids = {key: node_id for key, node_id in rows}
    wanted: list[tuple[Any, Any, str]] = []
    for source, relation, target, properties in normalise_edges(data["edges"]):
        if source not in ids or target not in ids:
            raise ValueError(f"edge references unknown node: {source} -{relation}-> {target}")
        graph_type = edge_graph_type(relation, GraphType.GOVERNANCE, GraphType.GOVERNANCE)
        stmt = insert(GraphEdge).values(
            graph_type=graph_type.value,
            relation=relation.value,
            source_node_id=ids[source],
            target_node_id=ids[target],
            properties_json=properties,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_graph_edges_triple",
            set_={"properties_json": stmt.excluded.properties_json},
        )
        await session.execute(stmt)
        wanted.append((ids[source], ids[target], relation.value))
    await session.execute(
        delete(GraphEdge).where(
            GraphEdge.graph_type == GraphType.GOVERNANCE,
            tuple_(GraphEdge.source_node_id, GraphEdge.target_node_id, GraphEdge.relation).not_in(
                wanted
            ),
        )
    )
    return len(data["nodes"]), len(wanted)
