"""Integration fixtures: a real PostgreSQL (pgvector) database.

Requires ADAPT_TEST_DATABASE_URL (runtime role, subject to RLS) and
ADAPT_TEST_OWNER_DATABASE_URL (schema owner). `docker compose up postgres` creates the
`adapt_test` database and roles. Tests are skipped when the variables are unset.

Each test session starts from an empty schema (downgrade to base, upgrade to head — which
also exercises every downgrade path) and seeds the shared reference data. Several people
running the suite at once should each point the variables at their own database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from arq.connections import ArqRedis
from dotenv import load_dotenv

from app.adapters.embeddings import HashingEmbedder
from app.adapters.registry import build_adapters
from app.core import compat
from app.core.config import Settings
from app.core.container import Container
from app.core.security import issue_session_token
from app.db.session import Database
from app.domain.principal import Principal
from app.events.notifier import NullNotifier
from app.main import create_app
from app.repositories import accounts
from app.seed.__main__ import seed_reference_data

BACKEND = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND.parent / ".env", override=False)

APP_URL = os.environ.get("ADAPT_TEST_DATABASE_URL")
OWNER_URL = os.environ.get("ADAPT_TEST_OWNER_DATABASE_URL")
SECRET = "integration-test-session-secret-0123456789"

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if APP_URL and OWNER_URL:
        return
    skip = pytest.mark.skip(reason="set ADAPT_TEST_DATABASE_URL and ADAPT_TEST_OWNER_DATABASE_URL")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Fresh schema per test session, plus the governance knowledge and catalogue."""
    assert OWNER_URL
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", OWNER_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    async def _seed() -> None:
        owner = Database(OWNER_URL, pool_size=1)
        async with owner.public_session() as session:
            await seed_reference_data(session, HashingEmbedder())
            await session.commit()
        await owner.dispose()

    compat.run(_seed())


@pytest.fixture(scope="session")
async def owner_db() -> AsyncIterator[Database]:
    assert OWNER_URL
    db = Database(OWNER_URL, pool_size=2)
    yield db
    await db.dispose()


@pytest.fixture(scope="session")
async def app_db() -> AsyncIterator[Database]:
    assert APP_URL
    db = Database(APP_URL, pool_size=4)
    yield db
    await db.dispose()


async def make_principal(db: Database, display_name: str = "Test") -> Principal:
    """Create an account through the runtime role (as sign-up does, under RLS)."""
    user = await accounts.create_account(db, display_name=display_name, is_demo=True)
    return Principal(user_id=user.id, tenant_id=user.tenant_id, is_demo=True)


@pytest.fixture
async def alice(app_db: Database) -> Principal:
    return await make_principal(app_db, "Alice")


@pytest.fixture
async def bob(app_db: Database) -> Principal:
    return await make_principal(app_db, "Bob")


class RecordingQueue:
    """Stands in for ARQ: records jobs instead of sending them to Redis."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, function: str, *, job_id: str, **kwargs: Any) -> str:
        self.jobs.append((function, kwargs))
        return job_id


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": APP_URL,
        "redis_url": "redis://127.0.0.1:1/0",  # unreachable: streams fall back to polling
        "session_secret": SECRET,
        "document_storage_dir": tmp_path,
        "openai_api_key": None,
        "adapter_llm": "demo",
        "adapter_embeddings": "demo",
        "adapter_ocr": "demo",
        "adapter_voice": "demo",
        "adapter_web_search": "demo",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def container(app_db: Database, tmp_path: Path) -> Container:
    settings = make_settings(tmp_path)
    return Container(
        settings=settings,
        db=app_db,
        redis=ArqRedis.from_url("redis://127.0.0.1:1/0"),  # never contacted
        notifier=NullNotifier(),
        adapters=build_adapters(settings),
        queue=RecordingQueue(),  # type: ignore[arg-type]
    )


@pytest.fixture
async def api(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container.settings, container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        yield client


def auth(principal: Principal) -> dict[str, str]:
    token = issue_session_token(principal, secret=SECRET, ttl_hours=1).token
    return {"Authorization": f"Bearer {token}"}
