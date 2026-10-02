"""Process-wide logging.

Rules: never log document contents, extracted identity fields, prompts containing user
facts, or secrets. Log identifiers (run_id, user_id, document_id), not payloads. Every
handler also runs `RedactingFilter` as a safety net for mistakes (see `app.core.redaction`).
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

from app.core.redaction import RedactingFilter

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    _RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
        "message",
        "asctime",
        "request_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_text:
            payload["exc"] = record.exc_text
        elif record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    handler.addFilter(RedactingFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party loggers that are noisy at INFO or may echo request bodies.
    for noisy in ("httpx", "httpcore", "openai", "sqlalchemy.engine", "arq.jobs"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True
    # uvicorn's access log prints raw query strings (signed links); ADAPT's own access log
    # (`adapt.access`, RequestContextMiddleware) records redacted requests instead.
    logging.getLogger("uvicorn.access").disabled = True
