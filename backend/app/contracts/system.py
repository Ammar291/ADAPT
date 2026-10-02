from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.contracts.common import ApiModel

AdapterMode = Literal["live", "demo"]
ComponentState = Literal["ok", "degraded", "down"]


class HealthStatus(ApiModel):
    status: Literal["ok"]
    version: str


class ComponentHealth(ApiModel):
    name: str
    state: ComponentState
    detail: str | None = None


class ReadinessStatus(ApiModel):
    status: ComponentState
    components: list[ComponentHealth]
    checked_at: datetime


class AdapterInfo(ApiModel):
    capability: str
    mode: AdapterMode
    provider: str


class FeatureFlags(ApiModel):
    """Capabilities the UI may offer. Workstreams flip these on as endpoints ship."""

    journeys: bool
    document_upload: bool
    voice: bool
    web_research: bool
    demo_auth: bool
    onboarding: bool
    discover: bool
    appointments: bool
    approvals: bool
    generated_documents: bool
    demo_scenarios: bool = False  # scripted demo runs (/demo/scenarios), demo deployments only


class SystemInfo(ApiModel):
    """Public, non-sensitive runtime information. Drives the developer demo-mode badge."""

    app_name: str
    version: str
    environment: str
    demo_mode: bool
    adapters: list[AdapterInfo]
    features: FeatureFlags
