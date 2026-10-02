"""All API routes, mounted under `settings.api_prefix` (`/api`).

Core routes live in `app.api.routes`. Feature workstreams ship their own routers; each is
mounted when its module imports, and for the few paths the core also serves (governance
graph, user graph, journey reads) the feature router replaces the core fallback. A feature
router that fails to import is logged and skipped so one unfinished workstream cannot take
the whole API down.
"""

from __future__ import annotations

import importlib
import logging

from fastapi import APIRouter

from app.api.routes import (
    agents,
    appointments,
    auth,
    catalogue,
    generated_documents,
    graph,
    journeys,
    profile,
    system,
)

logger = logging.getLogger(__name__)


def _feature_router(module_name: str, attr: str = "router") -> APIRouter | None:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        missing = (
            isinstance(exc, ModuleNotFoundError)
            and exc.name is not None
            and (module_name.startswith(exc.name))
        )
        if not missing:
            logger.error(
                "feature_router_unavailable",
                extra={"module": module_name, "error": type(exc).__name__, "detail": str(exc)},
            )
        return None
    router = getattr(module, attr, None)
    return router if isinstance(router, APIRouter) else None


api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(profile.router)
# Literal /documents/generated paths must precede any /documents/{id} route.
api_router.include_router(generated_documents.router)
api_router.include_router(catalogue.router)
api_router.include_router(appointments.router)
api_router.include_router(agents.router)
api_router.include_router(graph.journey_router)

# Knowledge layer: /knowledge/* and its richer /graph/governance view.
if (knowledge := _feature_router("app.knowledge.router")) is not None:
    api_router.include_router(knowledge)
knowledge_graph = _feature_router("app.knowledge.router", "graph_router")
api_router.include_router(knowledge_graph or graph.governance_router)
if knowledge_graph is not None:
    # Node detail stays available from the core router under its own path.
    api_router.include_router(
        APIRouter(routes=[r for r in graph.governance_router.routes if "nodes" in r.path])  # type: ignore[attr-defined]
    )

# Documents & personalization: uploads, extraction, facts, review tasks, /graph/user.
for name in ("app.documents.router",):
    if (feature := _feature_router(name)) is not None:
        api_router.include_router(feature)
user_graph = _feature_router("app.personalization.router")
api_router.include_router(user_graph or graph.user_router)

# Journey agent: journeys, simulation, reviews, actions and approvals.
journey_agent = _feature_router("app.agents.journey.api")
api_router.include_router(journey_agent or journeys.router)

for name in (
    "app.research.api",
    "app.voice.router",
    "app.interpreter.router",
    "app.demo_scenarios.router",
):
    if (feature := _feature_router(name)) is not None:
        api_router.include_router(feature)
