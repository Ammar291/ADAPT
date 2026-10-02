"""Session binding and rate limits for assistant traffic.

* Voice session ids are signed (HMAC with the server's session secret) and carry their
  owner and expiry, so a tool call can be checked against the session it claims without
  any storage: it must come from the same user, before expiry.
* Session minting, tool calls and text turns are rate-limited per user (Redis counters), so
  a runaway model loop or a scripted client can't hammer the API or the OpenAI account.

Every tool runs as the request's principal through the API. Traffic fails closed when
Redis is unavailable so an outage cannot remove the provider spending limits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any, Protocol

from redis.exceptions import RedisError

from app.core.errors import AdapterUnavailable, AppError, Conflict, Forbidden

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 2 * 3600  # comfortably longer than a Realtime session can last
MAX_TOOL_CALLS_PER_SESSION = 300
MAX_TOOL_CALLS_PER_MINUTE = 60
MAX_SESSIONS_PER_MINUTE = 10
MAX_TEXT_TURNS_PER_MINUTE = 20


class TooManyRequests(AppError):
    status, code, title = 429, "rate_limited", "Too many requests. Wait a moment and try again"


class KeyValueStore(Protocol):
    """The subset of the (async) Redis client the guard uses. Each call is awaited."""

    def incr(self, name: str, amount: int = 1) -> Any: ...
    def expire(self, name: str, time: int) -> Any: ...
    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...
    def set(self, name: str, value: str, *, nx: bool, ex: int) -> Any: ...


def _invalid() -> Forbidden:
    return Forbidden("This voice session has ended. Start a new one.", code="voice_session_invalid")


class AssistantGuard:
    def __init__(self, store: KeyValueStore, *, secret: str) -> None:
        self._store = store
        self._key = hashlib.sha256(f"adapt-voice-session:{secret}".encode()).digest()

    # --- signed session ids -------------------------------------------------------------

    def _sign(self, user_id: str, expires: int, nonce: str) -> str:
        mac = hmac.new(self._key, f"{user_id}:{expires}:{nonce}".encode(), hashlib.sha256)
        return base64.urlsafe_b64encode(mac.digest()[:18]).decode().rstrip("=")

    def new_session_id(self, user_id: str, *, now: float | None = None) -> str:
        expires = int((now if now is not None else time.time()) + SESSION_TTL_SECONDS)
        nonce = secrets.token_hex(8)
        # "." never occurs in base64url, so the parts split unambiguously.
        return f"vs.{expires}.{nonce}.{self._sign(user_id, expires, nonce)}"

    def verify_session_id(self, session_id: str, user_id: str, *, now: float | None = None) -> None:
        parts = session_id.split(".")
        if len(parts) != 4 or parts[0] != "vs" or not parts[1].isdigit():
            raise _invalid()
        _, expires, nonce, signature = parts
        if int(expires) <= (now if now is not None else time.time()):
            raise _invalid()
        if not hmac.compare_digest(signature, self._sign(user_id, int(expires), nonce)):
            raise _invalid()

    # --- rate limits ---------------------------------------------------------------------

    async def _count(self, key: str, *, window: int) -> int:
        try:
            return int(
                await self._store.eval(
                    "local n = redis.call('INCR', KEYS[1]); "
                    "if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; return n",
                    1,
                    key,
                    window,
                )
            )
        except (RedisError, OSError):
            logger.warning("assistant_guard_unavailable", extra={"key_kind": key.split(":")[2]})
            raise AdapterUnavailable(
                "The assistant is temporarily unavailable. Try again shortly.",
                code="assistant_guard_unavailable",
            ) from None

    async def _limit(self, key: str, *, limit: int, window: int) -> None:
        count = await self._count(key, window=window)
        if count > limit:
            raise TooManyRequests()

    @staticmethod
    def _minute() -> int:
        return int(time.time() // 60)

    async def check_mint(self, user_id: str) -> None:
        """Before asking OpenAI for a secret, so an over-limit client costs nothing."""
        await self._limit(
            f"adapt:voice:mint:{user_id}:{self._minute()}", limit=MAX_SESSIONS_PER_MINUTE, window=60
        )

    async def check_tool_call(self, session_id: str, user_id: str) -> None:
        self.verify_session_id(session_id, user_id)
        await self._limit(
            f"adapt:voice:calls:{session_id}",
            limit=MAX_TOOL_CALLS_PER_SESSION,
            window=SESSION_TTL_SECONDS,
        )
        await self.check_tool_rate(user_id)

    async def claim_tool_call(self, session_id: str, call_id: str) -> None:
        """A provider call id may start work once, including concurrent deliveries."""
        digest = hashlib.sha256(f"{session_id}:{call_id}".encode()).hexdigest()
        try:
            claimed = await self._store.set(
                f"adapt:voice:replay:{digest}",
                "1",
                nx=True,
                ex=SESSION_TTL_SECONDS,
            )
        except (RedisError, OSError):
            raise AdapterUnavailable(
                "The assistant is temporarily unavailable",
                code="assistant_guard_unavailable",
            ) from None
        if not claimed:
            raise Conflict("This tool call was already handled", code="voice_call_replayed")

    async def check_tool_rate(self, user_id: str) -> None:
        """Per-user tool budget, shared by voice and text."""
        await self._limit(
            f"adapt:voice:rate:{user_id}:{self._minute()}",
            limit=MAX_TOOL_CALLS_PER_MINUTE,
            window=60,
        )

    async def check_text_turn(self, user_id: str) -> None:
        await self._limit(
            f"adapt:assistant:rate:{user_id}:{self._minute()}",
            limit=MAX_TEXT_TURNS_PER_MINUTE,
            window=60,
        )
