"""Pure-ASGI middleware (safe for streaming/SSE responses)."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.logging import request_id_var
from app.core.origins import trusted_origin

access_log = logging.getLogger("adapt.access")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    """Request IDs, private-data cache policy, baseline security headers and a redacted
    access log.

    Every `/api` response is `Cache-Control: no-store` — responses carry private data,
    and neither the browser, a proxy nor the service worker may cache them. The access log
    records method, route template, status and duration: never queries, headers, cookies or
    bodies (uploads and passports never reach the log).
    """

    def __init__(
        self, app: ASGIApp, *, api_prefix: str = "/api", demo_capabilities: list[str] | None = None
    ) -> None:
        self.app = app
        self.api_prefix = api_prefix
        self.demo_header = ",".join(demo_capabilities or [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        is_api = scope["path"].startswith(self.api_prefix)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault("X-Frame-Options", "DENY")
                if is_api:
                    headers["Cache-Control"] = "no-store"
                    if self.demo_header:
                        # Developer-visible signal only; the UI stays natural for end users.
                        headers["X-ADAPT-Demo-Adapters"] = self.demo_header
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if is_api:
                route = scope.get("route")
                access_log.info(
                    "api_request",
                    extra={
                        "method": scope.get("method", "-"),
                        "route": getattr(route, "path", "unmatched"),
                        "status": status_holder.get("status", 0),
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    },
                )
            request_id_var.reset(token)


class BrowserOriginMiddleware:
    """Reject cross-origin mutations before auth, parsing, uploads or side effects.

    Bearer clients need no CSRF token. Cookie mutations require a browser Origin.
    Non-browser requests without cookies remain available for sign-in and public reads.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app, self.settings = app, settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["path"].startswith(self.settings.api_prefix + "/")
            and scope.get("method") not in {"GET", "HEAD", "OPTIONS"}
        ):
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            bearer = headers.get("authorization", "").lower().startswith("bearer ")
            cookie = self.settings.session_cookie_name + "=" in headers.get("cookie", "")
            invalid = origin is not None and not trusted_origin(
                origin,
                scheme=scope["scheme"],
                host=headers.get("host", ""),
                settings=self.settings,
            )
            missing = (
                origin is None
                and not bearer
                and (cookie or headers.get("sec-fetch-site") in {"cross-site", "same-site"})
            )
            if invalid or missing:
                response = JSONResponse(
                    {
                        "title": "This origin may not change your workspace",
                        "status": 403,
                        "code": "origin_not_allowed",
                    },
                    status_code=403,
                    media_type="application/problem+json",
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
