"""Signed, short-lived links for private document content.

A document's bytes are served only when BOTH hold:
* the request carries the owner's session (RLS scopes the lookup to them), and
* the URL carries a valid HMAC bound to the tenant, user, document and an expiry.

So a leaked link is useless to anyone else, and useless to the owner after it expires.
The signing key is derived from the session secret with a purpose label, so the raw
session secret is never used directly for two different things.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode
from uuid import UUID

from app.core.config import Settings
from app.core.errors import Forbidden
from app.domain.principal import Principal

_PURPOSE = b"adapt:document-content:v2"


def _key(settings: Settings) -> bytes:
    secret = settings.session_secret.get_secret_value().encode()
    return hmac.new(secret, _PURPOSE, hashlib.sha256).digest()


def _signature(settings: Settings, principal: Principal, document_id: UUID, expires: int) -> str:
    message = f"{principal.tenant_id}:{principal.user_id}:{document_id}:{expires}".encode()
    return hmac.new(_key(settings), message, hashlib.sha256).hexdigest()


def sign_document_url(
    settings: Settings,
    principal: Principal,
    document_id: UUID,
    *,
    ttl_seconds: int | None = None,
    now: float | None = None,
) -> str:
    """Relative URL (under the API prefix) for the document's content endpoint."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.document_url_ttl_seconds
    expires = int((now if now is not None else time.time()) + ttl)
    query = urlencode(
        {"expires": expires, "sig": _signature(settings, principal, document_id, expires)}
    )
    return f"{settings.api_prefix}/documents/{document_id}/content?{query}"


def verify_document_signature(
    settings: Settings,
    principal: Principal,
    document_id: UUID,
    *,
    expires: int,
    sig: str,
    now: float | None = None,
) -> None:
    """Raise `Forbidden` unless `sig` is valid for this user and document and not expired."""
    if expires < int(now if now is not None else time.time()):
        raise Forbidden("This document link has expired", code="document_link_expired")
    expected = _signature(settings, principal, document_id, expires)
    if not hmac.compare_digest(expected, sig):
        raise Forbidden("This document link is not valid", code="document_link_invalid")
