"""Persistent, installation-specific development credentials shared by API and worker."""

from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path


def local_session_secret(storage_dir: Path, *, has_document_key: bool) -> str:
    path = storage_dir / ".adapt-session-secret"
    if not path.exists():
        if not has_document_key and storage_dir.exists() and next(storage_dir.rglob("*.bin"), None):
            raise ValueError(
                "Configure the existing SESSION_SECRET / DOCUMENT_ENCRYPTION_KEY before "
                "opening encrypted documents; shared development credentials are no longer accepted"
            )
        storage_dir.mkdir(parents=True, exist_ok=True)
        temporary = storage_dir / f".secret-{secrets.token_hex(16)}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(secrets.token_urlsafe(48))
            # Publish the complete file atomically without overwriting another process's key.
            with suppress(FileExistsError):
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    secret = path.read_text(encoding="ascii").strip()
    if len(secret) < 32 or secret.startswith("dev-only"):
        raise ValueError("The installation's development signing key is invalid")
    return secret
