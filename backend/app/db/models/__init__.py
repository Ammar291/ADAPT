"""ORM models. Importing this package registers every table on `Base.metadata`.

Feature packages owned by other workstreams may contribute tables of their own through a
`models` module listed in `_FEATURE_MODEL_MODULES`. Such a module registers its tables on
the same `Base` and may export `PRIVATE_TABLES` (owner-only RLS tables it creates in its
own migration); they are appended to the list below.
"""

from __future__ import annotations

import importlib

from app.db.models.actions import Action, ActionApproval, Appointment, GeneratedDocument
from app.db.models.agents import AgentEvent, AgentRun
from app.db.models.catalogue import Community, CulturalGuide, Event
from app.db.models.governance import GovernanceChunk, GovernanceDocument, GovernanceSource
from app.db.models.graph import GraphEdge, GraphEdgeEvidence, GraphNode, GraphNodeEvidence
from app.db.models.journeys import Journey, JourneyEdge, JourneyNode
from app.db.models.profile import HouseholdMember, UserGoal, UserPreference, UserProfile
from app.db.models.tenancy import Tenant, User

# Tables holding private user data created by the core migrations. Each has an RLS owner
# policy, and `tests/integration/test_isolation.py` asserts the full list (including
# feature tables) matches the live database.
CORE_PRIVATE_TABLES: tuple[str, ...] = (
    "user_profiles",
    "household_members",
    "user_preferences",
    "user_goals",
    "journeys",
    "journey_nodes",
    "journey_edges",
    "agent_runs",
    "agent_events",
    "generated_documents",
    "actions",
    "action_approvals",
    "appointments",
)

# Shared reference tables: readable by the runtime role, written only by the owner role.
PUBLIC_TABLES: tuple[str, ...] = (
    "governance_sources",
    "governance_documents",
    "governance_chunks",
    "graph_node_evidence",
    "graph_edge_evidence",
    "communities",
    "events",
    "cultural_guides",
)

_FEATURE_MODEL_MODULES: tuple[str, ...] = (
    "app.db.models.user_data",
    "app.documents.models",
    "app.personalization.models",
    "app.research.models",
)


def _load_feature_models() -> tuple[str, ...]:
    extra: list[str] = []
    for name in _FEATURE_MODEL_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name is not None and name.startswith(exc.name):
                continue  # that feature package is not part of this build
            raise
        extra.extend(getattr(module, "PRIVATE_TABLES", ()))
    return tuple(extra)


PRIVATE_TABLES: tuple[str, ...] = CORE_PRIVATE_TABLES + _load_feature_models()

__all__ = [
    "CORE_PRIVATE_TABLES",
    "PRIVATE_TABLES",
    "PUBLIC_TABLES",
    "Action",
    "ActionApproval",
    "AgentEvent",
    "AgentRun",
    "Appointment",
    "Community",
    "CulturalGuide",
    "Event",
    "GeneratedDocument",
    "GovernanceChunk",
    "GovernanceDocument",
    "GovernanceSource",
    "GraphEdge",
    "GraphEdgeEvidence",
    "GraphNode",
    "GraphNodeEvidence",
    "HouseholdMember",
    "Journey",
    "JourneyEdge",
    "JourneyNode",
    "Tenant",
    "User",
    "UserGoal",
    "UserPreference",
    "UserProfile",
]
