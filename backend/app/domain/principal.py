"""The authenticated actor on whose behalf private data is read or written."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    is_demo: bool = False

    def as_job_args(self) -> dict[str, str]:
        """Serialisable form passed to background jobs (never trust job input for more)."""
        return {"user_id": str(self.user_id), "tenant_id": str(self.tenant_id)}

    @classmethod
    def from_job_args(cls, user_id: str, tenant_id: str) -> Principal:
        return cls(user_id=UUID(user_id), tenant_id=UUID(tenant_id))
