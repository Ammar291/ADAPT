"""Encrypted document storage.

Uploaded passports and certificates are encrypted at rest (Fernet / AES-128-CBC +
HMAC). Keys are opaque server-generated identifiers, never user-supplied paths.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import NotFound

logger = logging.getLogger(__name__)
_KEY_PATTERN = re.compile(r"^[a-f0-9-]{36}/[a-f0-9-]{36}$")


class DocumentStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


def derive_dev_key(secret: str) -> bytes:
    """Development-only key derived from the session secret. Production requires
    DOCUMENT_ENCRYPTION_KEY (enforced by settings validation)."""
    return base64.urlsafe_b64encode(hashlib.sha256(f"adapt-docs:{secret}".encode()).digest())


class LocalEncryptedStorage:
    def __init__(self, root: Path, key: bytes) -> None:
        self._root = root
        self._fernet = Fernet(key)

    def _path(self, key: str) -> Path:
        if not _KEY_PATTERN.match(key):
            raise ValueError("invalid storage key")
        return self._root / f"{key}.bin"

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        token = self._fernet.encrypt(data)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(token)
            tmp.replace(path)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            token = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise NotFound("Document not found") from exc
        try:
            return self._fernet.decrypt(token)
        except InvalidToken:
            logger.error("document_decrypt_failed", extra={"storage_key": key})
            raise

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
