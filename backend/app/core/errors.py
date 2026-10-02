"""Application errors, rendered as RFC 9457 problem details (`application/problem+json`).

Services raise `AppError` subclasses; they never build HTTP responses themselves.
The stable machine-readable `code` is what clients branch on — never the message.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.contracts.common import FieldError, ProblemDetail
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status: int = 500
    code: str = "internal_error"
    title: str = "Something went wrong"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        title: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        if code:
            self.code = code
        if title:
            self.title = title
        self.extra = extra or {}

    def to_problem(self, instance: str | None = None) -> ProblemDetail:
        return ProblemDetail(
            type=f"https://adapt.local/problems/{self.code}",
            title=self.title,
            status=self.status,
            detail=self.detail,
            code=self.code,
            instance=instance,
            request_id=request_id_var.get(),
            extra=self.extra or None,
        )


class BadRequest(AppError):
    status, code, title = 400, "bad_request", "The request is not valid"


class Unauthorized(AppError):
    status, code, title = 401, "unauthorized", "Sign in to continue"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "You do not have access to this resource"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "The resource changed or already exists"


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "The upload is too large"


class UnprocessableEntity(AppError):
    status, code, title = 422, "unprocessable", "The request could not be processed"


class ApprovalRequired(AppError):
    """Raised when a consequential action is attempted without a recorded human approval."""

    status, code, title = 409, "approval_required", "This action needs your approval first"


class AdapterUnavailable(AppError):
    """A capability is not available in the current adapter mode (e.g. demo without fixture)."""

    status, code, title = (
        503,
        "capability_unavailable",
        "This capability is not available right now",
    )


class UpstreamError(AppError):
    status, code, title = 502, "upstream_error", "An external service did not respond as expected"


def _problem_response(
    problem: ProblemDetail, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type=PROBLEM_JSON,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            **(headers or {}),
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            logger.warning(
                "app_error",
                extra={
                    "code": exc.code,
                    "route": getattr(request.scope.get("route"), "path", "unmatched"),
                },
            )
        return _problem_response(exc.to_problem(request.url.path))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            FieldError(
                loc=[str(part) for part in err.get("loc", ())],
                message=str(err.get("msg", "Invalid value")),
                type=str(err.get("type", "value_error")),
            )
            for err in exc.errors()
        ]
        problem = ProblemDetail(
            type="https://adapt.local/problems/validation_failed",
            title="Some fields need attention",
            status=422,
            code="validation_failed",
            instance=request.url.path,
            request_id=request_id_var.get(),
            errors=errors,
        )
        return _problem_response(problem)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}.get(
            exc.status_code, "http_error"
        )
        problem = ProblemDetail(
            type=f"https://adapt.local/problems/{code}",
            title=str(exc.detail) if exc.detail else "Request failed",
            status=exc.status_code,
            code=code,
            instance=request.url.path,
            request_id=request_id_var.get(),
        )
        return _problem_response(problem, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            extra={"route": getattr(request.scope.get("route"), "path", "unmatched")},
        )
        problem = ProblemDetail(
            type="https://adapt.local/problems/internal_error",
            title="Something went wrong on our side",
            status=500,
            code="internal_error",
            instance=request.url.path,
            request_id=request_id_var.get(),
        )
        return _problem_response(problem)
