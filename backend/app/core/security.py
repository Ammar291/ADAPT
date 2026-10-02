"""Session tokens.

The browser holds an httpOnly, SameSite=Lax cookie containing a signed JWT, so no
token is ever readable by JavaScript or stored in localStorage. API clients and tests
may send the same token as `Authorization: Bearer <token>`.

ADAPT never collects or stores UAE PASS (or any government) credentials; government
services that need the user's own login are handed off to the official channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.core.errors import Unauthorized
from app.domain.principal import Principal

_ALGORITHM = "HS256"
_AUDIENCE = "adapt-api"


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_at: datetime


def issue_session_token(principal: Principal, *, secret: str, ttl_hours: int) -> IssuedToken:
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=ttl_hours)
    claims = {
        "sub": str(principal.user_id),
        "tid": str(principal.tenant_id),
        "demo": principal.is_demo,
        "aud": _AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return IssuedToken(jwt.encode(claims, secret, algorithm=_ALGORITHM), expires_at)


def verify_session_token(token: str, *, secret: str) -> Principal:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            options={"require": ["sub", "tid", "exp"]},
        )
        return Principal(
            user_id=UUID(claims["sub"]),
            tenant_id=UUID(claims["tid"]),
            is_demo=bool(claims.get("demo", False)),
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session has expired", code="session_expired") from exc
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Unauthorized("Your session is not valid", code="session_invalid") from exc
