from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum


def str_enum(enum_cls: type[StrEnum], length: int = 40) -> Enum:
    """Store a StrEnum as VARCHAR (values, not names). Allowed values are enforced by a
    named CHECK constraint from `enum_check`, which keeps migrations explicit."""
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


def enum_check(column: str, enum_cls: type[StrEnum], name: str | None = None) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name or f"{column}_valid")
