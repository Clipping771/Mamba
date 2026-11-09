"""Test harness.

DB tests run against a real PostgreSQL (TEST_DATABASE_URL, else DATABASE_URL). The database
name must end in `_test`: the schema is dropped and rebuilt with Alembic at session start,
and all tables are truncated before each DB test. Without a reachable database DB tests are
skipped, unless REQUIRE_DB=1 (CI), where they fail.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# ---- configure the app for tests BEFORE importing it
_DEFAULT_TEST_DB = "postgresql+asyncpg://blackmamba:blackmamba@localhost:5432/blackmamba_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", _DEFAULT_TEST_DB
)
os.environ.update(
    {
        "DATABASE_URL": TEST_DATABASE_URL,
        "APP_ENV": "test",
        "STORAGE_BACKEND": "memory",
        "RATE_LIMIT_BACKEND": "memory",
        "LLM_PROVIDER": "fake",
        "SMTP_HOST": "",
        "ARCHIVE_ALLOW_PRIVATE_HOSTS": "false",
        "SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
        "PUBLIC_WEB_URL": "http://web.test",
    }
)

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from blackmamba.core.config import get_settings  # noqa: E402
from blackmamba.core.db import get_engine, get_sessionmaker  # noqa: E402
from blackmamba.main import create_app  # noqa: E402
from blackmamba.services.queue import get_job_queue  # noqa: E402
from blackmamba.services.rate_limit import get_rate_limiter  # noqa: E402
from blackmamba.services.storage import get_storage  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]
TABLES = [
    "finding_evidence",
    "findings",
    "notes",
    "evidence",
    "archive_jobs",
    "cases",
    "one_time_tokens",
    "audit_log",
    "users",
    "organizations",
]


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_rate_limiter.cache_clear()
    get_storage.cache_clear()


async def _probe() -> None:
    conn = await asyncpg.connect(_plain_dsn(TEST_DATABASE_URL), timeout=3)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def database_ready() -> Iterator[bool]:
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
    if not db_name.endswith("_test"):
        pytest.fail(f"refusing to wipe database {db_name!r}: name must end with _test")
    try:
        asyncio.run(_probe())
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"PostgreSQL required but unreachable: {exc}")
        yield False
        return
    _clear_caches()
    cfg = Config(str(API_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield True


@pytest.fixture
async def db(database_ready: bool) -> AsyncIterator[None]:
    """Clean database for one test."""
    if not database_ready:
        pytest.skip("PostgreSQL not reachable (set REQUIRE_DB=1 to fail instead)")
    _clear_caches()
    async with get_engine().begin() as conn:
        # Bypass append-only triggers (superuser test role) to reset state between tests.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    yield
    await get_engine().dispose()
    _clear_caches()


@pytest.fixture
async def session(db: None) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


class RecordingQueue:
    def __init__(self) -> None:
        self.archive_jobs: list[uuid.UUID] = []

    def enqueue_archive(self, job_id: uuid.UUID) -> None:
        self.archive_jobs.append(job_id)


@pytest.fixture
def job_queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def app(job_queue: RecordingQueue) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_job_queue] = lambda: job_queue
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await get_engine().dispose()
