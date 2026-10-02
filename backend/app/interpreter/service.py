"""Signed interpreter lifecycle and spending limits, independent of assistant guards."""

from __future__ import annotations

import hashlib
import time
from typing import Any
from uuid import uuid4

import jwt
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AdapterUnavailable, AppError, BadRequest, Forbidden
from app.domain.principal import Principal
from app.interpreter.contracts import SessionOut, SessionRequest, Speaker, StreamCredential
from app.interpreter.provider import TranslationProvider

TTL = 3600


class RateLimited(AppError):
    status, code, title = 429, "interpreter_rate_limited", "Wait a moment before trying again"


class InterpreterSessionService:
    def __init__(
        self, provider: TranslationProvider, store: Any, settings: Settings, principal: Principal
    ) -> None:
        self.provider, self.store, self.settings, self.principal = (
            provider,
            store,
            settings,
            principal,
        )
        self.owner = f"{principal.tenant_id}:{principal.user_id}"
        self.key = hashlib.sha256(
            f"adapt-interpreter:{settings.session_secret.get_secret_value()}".encode()
        ).digest()

    async def limit(self, kind: str, maximum: int) -> None:
        try:
            count = await self.store.eval(
                "local n = redis.call('INCR', KEYS[1]); "
                "if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end; return n",
                1,
                f"adapt:interpreter:{kind}:{self.owner}:{int(time.time() // 60)}",
            )
        except (RedisError, OSError):
            raise AdapterUnavailable(
                "Interpreter sessions are temporarily unavailable. Try again shortly.",
                code="interpreter_store_unavailable",
            ) from None
        if int(count) > maximum:
            raise RateLimited()

    def validate_pair(self, pair: SessionRequest) -> None:
        cap = self.provider.capabilities()
        if pair.recorded and not cap.fallback_enabled:
            raise BadRequest(
                "Recorded translation is disabled", code="interpreter_pair_unsupported"
            )
        languages = {lang.code: lang for lang in cap.languages}
        if pair.source == pair.target:
            raise BadRequest("Choose two different languages", code="interpreter_pair_unsupported")
        for code in (pair.source, pair.target):
            language = languages.get(code)
            if (
                not language
                or not language.input
                or not (language.output or (cap.fallback_enabled and language.fallback))
            ):
                raise BadRequest(
                    "This language pair is not available for two-way translation.",
                    code="interpreter_pair_unsupported",
                )

    async def verify(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.key,
                algorithms=["HS256"],
                audience="adapt-interpreter",
                options={"require": ["sub", "exp", "jti", "source", "target", "mode"]},
            )
            if claims["sub"] != self.owner:
                raise ValueError()
            if await self.store.get(f"adapt:interpreter:ended:{claims['jti']}"):
                raise ValueError()
            return claims
        except (jwt.InvalidTokenError, ValueError, KeyError):
            raise Forbidden(
                "This interpreter session has ended or expired. Start a new conversation.",
                code="interpreter_session_expired",
            ) from None
        except (RedisError, OSError):
            raise AdapterUnavailable("Cannot verify this interpreter session") from None

    async def create(self, pair: SessionRequest, session_id: str | None = None) -> SessionOut:
        self.validate_pair(pair)
        cap = self.provider.capabilities()
        if cap.mode == "unavailable":
            raise AdapterUnavailable("Set OPENAI_API_KEY on the server to enable the interpreter")
        if session_id:
            claims = await self.verify(session_id)
            if (
                claims["source"],
                claims["target"],
                claims["mode"],
                claims.get("recorded", False),
            ) != (pair.source, pair.target, cap.mode, pair.recorded):
                raise BadRequest("Start a new session to change the language pair")
            expires = claims["exp"]
        else:
            expires = int(time.time()) + TTL
            session_id = jwt.encode(
                {
                    "aud": "adapt-interpreter",
                    "sub": self.owner,
                    "exp": expires,
                    "jti": uuid4().hex,
                    "source": pair.source,
                    "target": pair.target,
                    "mode": cap.mode,
                    "recorded": pair.recorded,
                },
                self.key,
                algorithm="HS256",
            )
        await self.limit("mint", 10)
        streams = []
        directions: tuple[tuple[Speaker, str, str], ...] = (
            ("a", pair.source, pair.target),
            ("b", pair.target, pair.source),
        )
        for speaker, source, target in directions:
            if cap.mode == "demo":
                streams.append(
                    StreamCredential(
                        speaker=speaker, source=source, target=target, transport="demo"
                    )
                )
            elif pair.recorded:
                streams.append(
                    StreamCredential(
                        speaker=speaker, source=source, target=target, transport="recorded"
                    )
                )
            else:
                streams.append(await self.provider.credential(speaker, source, target))
        return SessionOut(session_id=session_id, mode=cap.mode, expires_at=expires, streams=streams)

    async def end(self, token: str) -> None:
        claims = await self.verify(token)
        try:
            await self.store.set(
                f"adapt:interpreter:ended:{claims['jti']}",
                "1",
                ex=max(1, claims["exp"] - int(time.time())),
            )
        except (RedisError, OSError):
            raise AdapterUnavailable("Could not close the interpreter session") from None
