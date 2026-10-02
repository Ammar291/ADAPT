"""In-process client for ADAPT's own public API, acting as the signed-in user.

Voice and text tools never import feature services or touch the database. They call the
same HTTP routes the UI uses, over an ASGI transport (no network hop), with the caller's
session token. Validation, authorisation and row-level security therefore apply exactly as
they do for the user's own requests, and a tool can never do more than the user could.

`serves()` tells a tool whether this build has a route at all, so an unshipped feature is
reported as "unavailable" rather than confused with a missing resource.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi.routing import iter_route_contexts
from starlette.routing import BaseRoute
from starlette.types import ASGIApp

_PARAM = re.compile(r"\{[^}]+\}")
_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
DEFAULT_TIMEOUT_SECONDS = 20.0


def _normalise(template: str) -> str:
    return _PARAM.sub("{}", template.rstrip("/") or "/")


def route_table(routes: Iterable[BaseRoute]) -> frozenset[tuple[str, str]]:
    """(METHOD, normalised path) for every HTTP route of the application, including routes
    of included routers (FastAPI keeps those nested rather than flattening them)."""
    table: set[tuple[str, str]] = set()
    for route in iter_route_contexts(list(routes)):
        path = route.path_format or route.path
        methods = route.methods
        if isinstance(path, str) and methods:
            table.update((method, _normalise(path)) for method in methods)
    return frozenset(table)


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def code(self) -> str | None:
        """The problem-details `code`, when the API returned one."""
        if isinstance(self.body, dict) and isinstance(self.body.get("code"), str):
            return str(self.body["code"])
        return None

    @property
    def detail(self) -> str | None:
        if isinstance(self.body, dict):
            for key in ("detail", "title"):
                if isinstance(self.body.get(key), str):
                    return str(self.body[key])
        return None


class ApiGateway:
    def __init__(
        self,
        app: ASGIApp,
        routes: frozenset[tuple[str, str]],
        *,
        prefix: str,
        token: str,
        request_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._routes = routes
        self._prefix = prefix.rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-ADAPT-Channel": "assistant",
        }
        if request_id:
            headers["X-Request-ID"] = request_id
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://adapt.internal",
            headers=headers,
            timeout=timeout,
        )

    async def __aenter__(self) -> ApiGateway:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    def serves(self, method: str, template: str) -> bool:
        return (method.upper(), _normalise(self._prefix + template)) in self._routes

    def first_served(self, method: str, templates: Sequence[str]) -> str | None:
        """The first of several candidate routes this build serves (routes move while
        workstreams land; tools list the current path first and older ones after)."""
        return next((t for t in templates if self.serves(method, t)), None)

    async def request(
        self,
        method: str,
        template: str,
        *,
        path_params: Sequence[str] = (),
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> ApiResponse:
        path = template
        for value in path_params:
            text = str(value)
            # The ASGI path is decoded before routing, so quoting alone can't stop "a/b".
            if not _SEGMENT.match(text):
                raise ValueError("invalid path parameter")
            path = _PARAM.sub(quote(text, safe=""), path, count=1)
        response = await self._client.request(
            method,
            self._prefix + path,
            params={k: v for k, v in (params or {}).items() if v is not None},
            json=json,
        )
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        return ApiResponse(response.status_code, body)

    async def get(
        self,
        template: str,
        *,
        path_params: Sequence[str] = (),
        params: dict[str, Any] | None = None,
    ) -> ApiResponse:
        return await self.request("GET", template, path_params=path_params, params=params)

    async def post(
        self, template: str, *, path_params: Sequence[str] = (), json: Any = None
    ) -> ApiResponse:
        return await self.request("POST", template, path_params=path_params, json=json)
