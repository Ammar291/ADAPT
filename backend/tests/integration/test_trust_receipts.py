"""Database trust constraints, tested through the restricted runtime role."""

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.errors import AdapterUnavailable
from app.db.models import Appointment
from app.db.session import Database
from app.domain.enums import AppointmentStatus
from app.domain.principal import Principal


@pytest.mark.parametrize("status", [AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED])
@pytest.mark.parametrize(
    "receipt",
    [None, {"provider": "Provider", "reference": "WRONG", "confirmed_at": "2026-10-01T00:00:00Z"}],
)
async def test_database_refuses_bookings_without_matching_provider_receipt(
    app_db: Database, alice: Principal, status: AppointmentStatus, receipt: dict | None
) -> None:
    async with app_db.user_session(alice) as session:
        session.add(
            Appointment(
                tenant_id=alice.tenant_id,
                user_id=alice.user_id,
                title="Biometrics",
                status=status,
                external_reference="USER-TYPED-1",
                booking_confirmation=receipt,
            )
        )
        with pytest.raises(DBAPIError):
            await session.commit()


async def test_runtime_database_role_is_verified(app_db: Database, owner_db: Database) -> None:
    app_db._require_rls = True
    await app_db.verify_runtime_role()
    owner_db._require_rls = True
    try:
        with pytest.raises(AdapterUnavailable) as error:
            await owner_db.verify_runtime_role()
        assert getattr(error.value, "code", None) == "unsafe_database_role"
    finally:
        owner_db._require_rls = False
