"""Test fixtures for backend/whatsapp/tests/.

Provides
--------
conn
    asyncpg connection wrapping each test in a rolled-back transaction.
    Tests are skipped automatically when the database is unavailable.
    Set TEST_DATABASE_URL (or the DB_* vars below) before running.

fake_redis
    In-process FakeRedis stub — no real Redis needed.

error_redis
    FakeRedis that raises ConnectionError on every call.
    Used to verify the fail-closed behaviour (RateLimitError on Redis outage).
"""
import os
from typing import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# DB connection settings
# ---------------------------------------------------------------------------
_DB_HOST = os.getenv("DB_HOST", "localhost")
_DB_PORT = int(os.getenv("DB_PORT", "5432"))
_DB_NAME = os.getenv("DB_NAME", "solvetax_test")
_DB_USER = os.getenv("DB_USER", "solvetax")
_DB_PASS = os.getenv("DB_PASSWORD", "testpass")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    f"postgresql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/{_DB_NAME}",
)

# Migrations must be applied to the test DB before the suite runs.
# CI does this via `python db/migrate/run_migrations.py` before `pytest`.
# For local dev: run `DB_SSL=disable python db/migrate/run_migrations.py` once.


@pytest_asyncio.fixture
async def conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """Asyncpg connection; wraps each test in a rolled-back transaction.

    Tests are skipped when the database is unavailable so a missing test-DB
    doesn't fail unrelated CI jobs.
    """
    try:
        connection: asyncpg.Connection = await asyncpg.connect(
            dsn=TEST_DATABASE_URL,
            ssl=False,
        )
    except Exception as exc:
        pytest.skip(f"Test database unavailable ({exc}); skipping DB tests")

    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


# ---------------------------------------------------------------------------
# Fake Redis stubs (~20 lines; no fakeredis dependency)
# ---------------------------------------------------------------------------

class FakeRedis:
    """In-memory Redis stub that supports incr and expire.

    `set_count(key, value)` pre-seeds a counter so tests can simulate
    already-at-cap state without issuing N real INCR calls.
    """

    def __init__(self) -> None:
        self._data: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass  # TTL not needed for unit tests

    def set_count(self, key: str, value: int) -> None:
        """Seed the counter; used to simulate at-cap or near-cap state."""
        self._data[key] = value


class ErrorRedis:
    """Redis stub that always raises ConnectionError.

    Verifies the fail-CLOSED behaviour: when Redis is unreachable,
    send_service.send() must raise RateLimitError rather than sending blind.
    """

    async def incr(self, key: str) -> int:
        raise ConnectionError("Redis unreachable (test stub)")

    async def expire(self, key: str, seconds: int) -> None:
        raise ConnectionError("Redis unreachable (test stub)")


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def error_redis() -> ErrorRedis:
    return ErrorRedis()
