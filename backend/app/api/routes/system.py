from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.agents.journey.topology import JOURNEY_TOPOLOGY
from app.api.deps import ContainerDep
from app.contracts.agents import AgentTopology
from app.contracts.system import (
    ComponentHealth,
    FeatureFlags,
    HealthStatus,
    ReadinessStatus,
    SystemInfo,
)

router = APIRouter(tags=["system"])

# Endpoints that exist in this build. Each feature workstream flips its flag when its API
# ships, so the UI never offers an action the server cannot perform.
SHIPPED_FEATURES: dict[str, bool] = {
    "journeys": True,  # app.agents.journey.api
    "document_upload": True,
    "voice": True,
    "web_research": True,
    "onboarding": True,
    "discover": True,
    "appointments": True,
    "approvals": True,  # app.agents.journey.api (action approvals + review gates)
    "generated_documents": True,
}


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health(container: ContainerDep) -> HealthStatus:
    return HealthStatus(status="ok", version=container.settings.app_version)


@router.get("/health/ready", response_model=ReadinessStatus, summary="Readiness of dependencies")
async def ready(container: ContainerDep) -> ReadinessStatus:
    async def check_db() -> ComponentHealth:
        try:
            await asyncio.wait_for(container.db.verify_runtime_role(), timeout=3)
            async with container.db.public_session() as session:
                await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=3)
            return ComponentHealth(name="postgres", state="ok")
        except Exception as exc:  # readiness must never raise
            return ComponentHealth(name="postgres", state="down", detail=type(exc).__name__)

    async def check_redis() -> ComponentHealth:
        try:
            await asyncio.wait_for(container.redis.ping(), timeout=3)
            return ComponentHealth(name="redis", state="ok")
        except Exception as exc:
            return ComponentHealth(name="redis", state="down", detail=type(exc).__name__)

    components = list(await asyncio.gather(check_db(), check_redis()))
    demo = container.adapters.demo_capabilities
    components.append(
        ComponentHealth(
            name="integrations",
            state="degraded" if demo else "ok",
            detail=f"demo adapters: {', '.join(demo)}" if demo else None,
        )
    )
    overall = "down" if any(c.state == "down" for c in components[:2]) else "ok"
    return ReadinessStatus(status=overall, components=components, checked_at=datetime.now(UTC))


@router.get(
    "/system/info", response_model=SystemInfo, summary="Runtime configuration (non-sensitive)"
)
async def system_info(container: ContainerDep) -> SystemInfo:
    s = container.settings
    adapters = container.adapters
    modes = {info.capability: info.mode for info in adapters.infos()}
    return SystemInfo(
        app_name=s.app_name,
        version=s.app_version,
        environment=s.environment.value,
        demo_mode=bool(adapters.demo_capabilities),
        adapters=adapters.infos(),
        features=FeatureFlags(
            journeys=SHIPPED_FEATURES["journeys"],
            document_upload=SHIPPED_FEATURES["document_upload"],
            voice=SHIPPED_FEATURES["voice"] and modes.get("voice") == "live",
            # Research works offline too (curated snapshot); `adapters` shows which mode.
            web_research=SHIPPED_FEATURES["web_research"],
            demo_auth=s.demo_auth_enabled,
            onboarding=SHIPPED_FEATURES["onboarding"],
            discover=SHIPPED_FEATURES["discover"],
            appointments=SHIPPED_FEATURES["appointments"],
            approvals=SHIPPED_FEATURES["approvals"],
            generated_documents=SHIPPED_FEATURES["generated_documents"],
            demo_scenarios=s.demo_auth_enabled,
        ),
    )


@router.get(
    "/agents/journey/topology",
    response_model=AgentTopology,
    tags=["agents"],
    summary="Nodes and edges of the journey agent graph",
)
async def journey_topology() -> AgentTopology:
    return JOURNEY_TOPOLOGY
