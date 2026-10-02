"""Private user graph (digital twin) contracts: entities, facts, schema, explanations.

`UserGraphView` is only ever served to its owner. It never embeds governance content in
user entities: public governance nodes the twin links to appear separately, as
`linked_governance_nodes`, clearly typed as governance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from app.contracts.common import ApiModel
from app.contracts.graph import GovernanceNodeOut
from app.documents.catalogue import DocumentKind
from app.domain.enums import FactSource, GraphEdgeType, GraphType, TwinNodeType
from app.personalization.facts_model import FactStatus


class UserFactOut(ApiModel):
    """One personal detail with its provenance."""

    id: UUID
    node_id: UUID
    entity_type: TwinNodeType
    attribute: str
    attribute_label: str
    value: JsonValue | None = Field(description="Canonical value; null only while it awaits review")
    value_display: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: FactSource
    source_document_id: UUID | None = None
    source_document_kind: DocumentKind | None = None
    source_ref: str | None = Field(default=None, description="e.g. 'profile:user_goals:<id>'")
    extraction_method: str | None = Field(
        default=None, description="e.g. 'local:pdf-text+mrz', 'openai:<model>', 'user_entry'"
    )
    status: FactStatus
    confirmed_by_user: bool
    corrected: bool
    issues: list[str] = Field(default_factory=list, description="Why it needs review")
    origin: str = Field(description="Where it came from, phrased for people")
    observed_at: datetime
    updated_at: datetime


EntityStatus = Literal["confirmed", "unconfirmed", "proposed"]


class UserEntityOut(ApiModel):
    id: UUID
    graph_type: GraphType = GraphType.USER
    type: TwinNodeType
    key: str = Field(description="Stable, contains no personal data")
    label: str
    parent_id: UUID | None = None
    relation: GraphEdgeType | None = Field(default=None, description="Edge from the parent")
    status: EntityStatus = Field(
        description="confirmed: all facts confirmed by you; proposed: only awaiting review"
    )
    facts: list[UserFactOut]


class UserEdgeOut(ApiModel):
    id: UUID
    relation: GraphEdgeType
    source: UUID
    target: UUID
    links_to_governance: bool = Field(
        description="True for private links from your twin to public governance knowledge"
    )


class UserGraphView(ApiModel):
    graph_type: GraphType = GraphType.USER
    nodes: list[UserEntityOut]
    edges: list[UserEdgeOut]
    linked_governance_nodes: list[GovernanceNodeOut] = Field(
        description="Public reference knowledge your twin links to. Not personal data."
    )
    open_review_tasks: int
    generated_at: datetime


class UserFactCreate(ApiModel):
    """State a fact about an existing entity (`node_id`) or an entity of `entity_type`.

    For single entities (spouse, household, housing) and for identity attributes
    (a nationality's country, a child's name), the matching entity is reused.
    """

    node_id: UUID | None = None
    entity_type: TwinNodeType | None = None
    parent_id: UUID | None = Field(default=None, description="Parent entity; default: you")
    attribute: str = Field(min_length=1, max_length=60)
    value: JsonValue


class UserFactUpdate(ApiModel):
    """Correct (`value`) and/or confirm a fact. Confirming a proposal accepts it."""

    value: JsonValue | None = None
    confirm: bool | None = None


class AttributeSchemaOut(ApiModel):
    name: str
    label: str
    kind: str
    choices: list[dict[str, str]] = Field(default_factory=list)
    sensitive: bool = False


class EntitySchemaOut(ApiModel):
    type: TwinNodeType
    label: str
    cardinality: Literal["hub", "one", "many"]
    relation: GraphEdgeType | None
    parents: list[TwinNodeType]
    identity: str | None
    attributes: list[AttributeSchemaOut]


class UserGraphSchema(ApiModel):
    entities: list[EntitySchemaOut]


class FactEvidenceOut(ApiModel):
    """One fact a recommendation used, and where it came from."""

    fact_id: UUID
    removed: bool = Field(description="True when the fact has since been removed")
    entity_type: TwinNodeType | None = None
    entity_label: str | None = None
    attribute: str | None = None
    attribute_label: str | None = None
    value_display: str | None = None
    origin: str
    source: FactSource | None = None
    source_document_id: UUID | None = None
    confirmed_by_user: bool = False
    statement: str = Field(
        description="e.g. 'Spouse · Date of marriage: read from your marriage certificate'"
    )


class PlanningFactOut(ApiModel):
    """A detail ADAPT takes into account when planning, with the facts behind it."""

    key: str = Field(description="Shared key, e.g. 'household.move_with_spouse'")
    label: str
    value: JsonValue
    source: FactSource
    confidence: float
    confirmed: bool
    fact_ids: list[UUID]
    basis: list[FactEvidenceOut]


class PersonalisationView(ApiModel):
    facts: list[PlanningFactOut]
    generated_at: datetime


class FactExplainRequest(ApiModel):
    fact_ids: list[UUID] = Field(max_length=200)
