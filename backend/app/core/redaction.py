"""Redaction of secrets and personal data before anything is logged.

Policy: logs carry identifiers (run_id, document_id, request path templates), never
document bodies, extracted identity fields, prompts or credentials. This module is the
safety net for mistakes — a log call that accidentally includes a passport number, an API
key or a session token has it masked before the record is formatted.
"""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode

REDACTED = "[REDACTED]"

# Keys whose values are never logged, wherever they appear (dict keys, query params).
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "openai_api_key",
        "authorization",
        "cookie",
        "set-cookie",
        "sig",
        "signature",
        "session",
        "adapt_session",
        # identity-document and personal fields
        "passport_number",
        "document_number",
        "emirates_id",
        "emirates_id_number",
        "national_id",
        "mrz",
        "date_of_birth",
        "dob",
        "full_name",
        "given_names",
        "surname",
        "place_of_birth",
        "address",
        "phone",
        "email",
        "iban",
        "account_number",
        "monthly_income",
        "monthly_income_aed",
        "salary",
        # free text that may contain anything personal
        "content",
        "body",
        "body_markdown",
        "text",
        "prompt",
        "value",
        "file",
        "raw_text",
        "extracted_text",
        "ocr_text",
        "raw_content",
        "document_content",
        "fields",
        "payload",
        "arguments",
        "messages",
        "transcript",
        "input",
        "marriage_certificate",
        "passport",
        "filename",
    }
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI and similar API keys
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-" + REDACTED),
    # JWTs (session tokens)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), REDACTED),
    # Bearer credentials
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), "Bearer " + REDACTED),
    # Passport machine-readable zone lines (44 chars of A-Z, 0-9 and '<')
    (re.compile(r"[A-Z0-9<]{30,44}"), REDACTED),
    # Emirates ID numbers (784-YYYY-NNNNNNN-N)
    (re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b"), REDACTED),
    # e-mail addresses
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), REDACTED),
)


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or lowered.endswith(("_token", "_secret", "_key", "_password"))


def redact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if _is_sensitive(str(k)) else redact_value(v, depth=depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [redact_value(v, depth=depth + 1) for v in value]
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_query(query: str) -> str:
    """Mask sensitive query parameters (e.g. `sig`, `token`) in a raw query string."""
    if not query:
        return query
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode([(k, REDACTED if _is_sensitive(k) else redact_text(v)) for k, v in pairs])


_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


class RedactingFilter(logging.Filter):
    """Masks secrets and personal data in every record's message, args and extra fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = redact_value(record.args)
            else:
                record.args = tuple(redact_value(a) for a in record.args)
        for key, value in list(record.__dict__.items()):
            if key in _RESERVED or key.startswith("_") or key == "request_id":
                continue
            record.__dict__[key] = REDACTED if _is_sensitive(key) else redact_value(value)
        # Exception messages (including chained SQL/provider errors) may contain the
        # entire OCR response or bound SQL parameters. Keep frame locations and types.
        if record.exc_info:
            exc_type, _, tb = record.exc_info
            frames = traceback.extract_tb(tb)
            record.exc_text = "\n".join(
                [f"  {f.filename}:{f.lineno} in {f.name}" for f in frames]
                + [exc_type.__name__ if exc_type else "Exception"]
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = REDACTED
        record.stack_info = None
        return True
