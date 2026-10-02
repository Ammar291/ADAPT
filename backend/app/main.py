"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.router import api_router
from app.contracts import EXTRA_CONTRACT_MODELS
from app.core.config import Settings, get_settings
from app.core.container import Container
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import BrowserOriginMiddleware, RequestContextMiddleware

logger = logging.getLogger(__name__)


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """OpenAPI document including contracts that are not (yet) bound to a route.

    This document is the source for the generated TypeScript types in
    `packages/contracts` (see `scripts/export_openapi.py`).
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="ADAPT API",
        version=app.version,
        description="Abu Dhabi Digital Arrival & Planning Twin",
        routes=app.routes,
    )
    components: dict[str, Any] = schema.setdefault("components", {}).setdefault("schemas", {})
    for model, is_request in EXTRA_CONTRACT_MODELS:
        model_schema = model.model_json_schema(
            ref_template="#/components/schemas/{model}",
            mode="validation" if is_request else "serialization",
        )
        for name, definition in model_schema.pop("$defs", {}).items():
            components.setdefault(name, definition)
        components.setdefault(model.__name__, model_schema)
    schema["components"]["schemas"] = dict(sorted(components.items()))
    app.openapi_schema = schema
    return schema


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.json_logs)
    container = container or Container.create(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "adapt_api_started",
            extra={
                "environment": settings.environment.value,
                "demo": container.adapters.demo_capabilities,
            },
        )
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title="ADAPT API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else f"{settings.api_prefix}/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else f"{settings.api_prefix}/openapi.json",
    )
    app.state.container = container
    app.state.settings = settings

    install_error_handlers(app)
    app.add_middleware(BrowserOriginMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-ADAPT-Demo-Adapters"],
    )
    app.add_middleware(
        RequestContextMiddleware,
        api_prefix=settings.api_prefix,
        demo_capabilities=container.adapters.demo_capabilities,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
    return app


def __getattr__(name: str) -> Any:
    # `uvicorn app.main:app` — build lazily so importing this module has no side effects.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
