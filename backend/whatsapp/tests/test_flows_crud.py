"""CRUD tests for wa_flows table (Slice 1 API).

Uses the `conn` fixture from conftest.py — each test is wrapped in a
rolled-back transaction so no state persists between tests.

Tests are skipped automatically when:
  - The database is unavailable (conn fixture handles this).
  - The wa_flows table does not yet exist (V003 migration not applied).

To run locally:
    DB_HOST=localhost DB_NAME=<testdb> DB_USER=$(whoami) \\
    DB_SSL=disable python -m pytest backend/whatsapp/tests/test_flows_crud.py -v

Prerequisites:
    DB_SSL=disable python db/migrate/run_migrations.py
"""
from __future__ import annotations

import json
import uuid

import asyncpg
import pytest
import pytest_asyncio

from backend.whatsapp.flow_validation import validate_flow

_SCHEMA = "solvetax"


# ---------------------------------------------------------------------------
# Module-level skip if wa_flows table is missing
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _require_wa_flows(conn):
    """Skip tests in this module if the wa_flows table is not present."""
    try:
        await conn.fetchval(f"SELECT 1 FROM {_SCHEMA}.wa_flows LIMIT 0")
    except asyncpg.exceptions.UndefinedTableError as exc:
        pytest.skip(f"wa_flows table not found ({exc}); run V003 migration first")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_flow(
    conn,
    name: str = "Test Flow",
    trigger_type: str = "crm_event",
    draft_data: dict | None = None,
) -> asyncpg.Record:
    if draft_data is None:
        return await conn.fetchrow(
            f"INSERT INTO {_SCHEMA}.wa_flows (name, trigger_type)"
            f" VALUES ($1, $2)"
            f" RETURNING id, name, trigger_type, status, is_active,"
            f"           draft_data, live_data, version, created_by,"
            f"           created_at, updated_at",
            name, trigger_type,
        )
    return await conn.fetchrow(
        f"INSERT INTO {_SCHEMA}.wa_flows (name, trigger_type, draft_data)"
        f" VALUES ($1, $2, $3::jsonb)"
        f" RETURNING id, name, trigger_type, status, is_active,"
        f"           draft_data, live_data, version, created_by,"
        f"           created_at, updated_at",
        name, trigger_type, json.dumps(draft_data),
    )


def _parse_jsonb(val):
    if val is None:
        return None
    if isinstance(val, str):
        return json.loads(val)
    return val


# ---------------------------------------------------------------------------
# CREATE — default column values
# ---------------------------------------------------------------------------

async def test_create_flow_defaults(conn):
    """Newly inserted flow has correct default column values."""
    row = await _insert_flow(conn)

    assert row["status"] == "draft"
    assert row["version"] == 0
    assert row["is_active"] is True
    assert row["live_data"] is None
    assert row["created_by"] is None
    dd = _parse_jsonb(row["draft_data"])
    assert dd == {}


async def test_create_flow_stores_name_and_trigger_type(conn):
    """Name and trigger_type are persisted as supplied."""
    row = await _insert_flow(conn, "GST Deadline Reminder", "scheduled_date")
    assert row["name"] == "GST Deadline Reminder"
    assert row["trigger_type"] == "scheduled_date"


async def test_create_flow_all_valid_trigger_types(conn):
    """All three trigger types satisfy the CHECK constraint."""
    for ttype in ("inbound_keyword", "scheduled_date", "crm_event"):
        row = await _insert_flow(conn, f"Flow {ttype}", ttype)
        assert row["trigger_type"] == ttype


async def test_create_flow_invalid_trigger_type_rejected(conn):
    """Invalid trigger_type violates the CHECK constraint."""
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await conn.execute(
            f"INSERT INTO {_SCHEMA}.wa_flows (name, trigger_type)"
            f" VALUES ($1, $2)",
            "Bad Flow", "invalid_type",
        )


async def test_create_flow_invalid_status_rejected(conn):
    """Invalid status violates the CHECK constraint."""
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await conn.execute(
            f"INSERT INTO {_SCHEMA}.wa_flows (name, trigger_type, status)"
            f" VALUES ($1, $2, $3)",
            "Bad Flow", "crm_event", "invalid_status",
        )


# ---------------------------------------------------------------------------
# READ — list and detail
# ---------------------------------------------------------------------------

async def test_list_flows_includes_created(conn):
    """Inserted flow appears in SELECT *."""
    row = await _insert_flow(conn, "My Unique Flow")
    rows = await conn.fetch(
        f"SELECT id FROM {_SCHEMA}.wa_flows ORDER BY updated_at DESC"
    )
    ids = [r["id"] for r in rows]
    assert row["id"] in ids


async def test_get_flow_by_id(conn):
    """SELECT by id returns the correct row."""
    row = await _insert_flow(conn, "Detail Test", "scheduled_date")
    fetched = await conn.fetchrow(
        f"SELECT id, name, trigger_type, status FROM {_SCHEMA}.wa_flows WHERE id = $1",
        row["id"],
    )
    assert fetched is not None
    assert fetched["name"] == "Detail Test"
    assert fetched["trigger_type"] == "scheduled_date"
    assert fetched["status"] == "draft"


async def test_get_nonexistent_flow_returns_none(conn):
    """SELECT by a random UUID that doesn't exist returns None."""
    result = await conn.fetchrow(
        f"SELECT id FROM {_SCHEMA}.wa_flows WHERE id = $1",
        uuid.uuid4(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# UPDATE DRAFT (PUT .../draft)
# ---------------------------------------------------------------------------

async def test_update_draft_data(conn):
    """draft_data can be updated with a new JSONB graph."""
    row = await _insert_flow(conn)
    draft = {
        "nodes": [{"id": "n1", "type": "endFlow", "data": {"config": {}}}],
        "edges": [],
        "viewport": {},
    }
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows SET draft_data = $1::jsonb, updated_at = now()"
        f" WHERE id = $2",
        json.dumps(draft), row["id"],
    )
    updated = await conn.fetchrow(
        f"SELECT draft_data FROM {_SCHEMA}.wa_flows WHERE id = $1", row["id"]
    )
    dd = _parse_jsonb(updated["draft_data"])
    assert isinstance(dd, dict)
    assert dd["nodes"][0]["type"] == "endFlow"


async def test_update_draft_preserves_other_columns(conn):
    """Updating draft_data does not change status or version."""
    row = await _insert_flow(conn)
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows SET draft_data = $1::jsonb WHERE id = $2",
        json.dumps({"nodes": [], "edges": []}), row["id"],
    )
    updated = await conn.fetchrow(
        f"SELECT status, version FROM {_SCHEMA}.wa_flows WHERE id = $1", row["id"]
    )
    assert updated["status"] == "draft"
    assert updated["version"] == 0


# ---------------------------------------------------------------------------
# PATCH is_active
# ---------------------------------------------------------------------------

async def test_toggle_is_active_to_false(conn):
    """is_active can be set to false."""
    row = await _insert_flow(conn)
    assert row["is_active"] is True

    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows SET is_active = false, updated_at = now()"
        f" WHERE id = $1",
        row["id"],
    )
    updated = await conn.fetchrow(
        f"SELECT is_active FROM {_SCHEMA}.wa_flows WHERE id = $1", row["id"]
    )
    assert updated["is_active"] is False


async def test_toggle_is_active_back_to_true(conn):
    """is_active can be re-enabled after being disabled."""
    row = await _insert_flow(conn)
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows SET is_active = false WHERE id = $1", row["id"]
    )
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows SET is_active = true WHERE id = $1", row["id"]
    )
    updated = await conn.fetchrow(
        f"SELECT is_active FROM {_SCHEMA}.wa_flows WHERE id = $1", row["id"]
    )
    assert updated["is_active"] is True


# ---------------------------------------------------------------------------
# PUBLISH — SQL level
# ---------------------------------------------------------------------------

async def test_publish_copies_draft_to_live_and_increments_version(conn):
    """Publish: live_data = draft_data, version += 1, status = 'published'."""
    draft = {"nodes": [], "edges": [], "viewport": {}}
    row = await _insert_flow(conn, draft_data=draft)
    assert row["version"] == 0

    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows"
        f" SET live_data = draft_data, status = 'published',"
        f"     version = version + 1, updated_at = now()"
        f" WHERE id = $1",
        row["id"],
    )
    published = await conn.fetchrow(
        f"SELECT status, version, live_data, draft_data FROM {_SCHEMA}.wa_flows WHERE id = $1",
        row["id"],
    )
    assert published["status"] == "published"
    assert published["version"] == 1
    ld = _parse_jsonb(published["live_data"])
    dd = _parse_jsonb(published["draft_data"])
    assert ld == dd


async def test_publish_twice_increments_version_each_time(conn):
    """Each publish increments version by 1."""
    row = await _insert_flow(conn, draft_data={"nodes": [], "edges": []})
    for expected_version in (1, 2):
        await conn.execute(
            f"UPDATE {_SCHEMA}.wa_flows"
            f" SET live_data = draft_data, status = 'published',"
            f"     version = version + 1, updated_at = now()"
            f" WHERE id = $1",
            row["id"],
        )
        v = await conn.fetchval(
            f"SELECT version FROM {_SCHEMA}.wa_flows WHERE id = $1", row["id"]
        )
        assert v == expected_version


async def test_can_archive_published_flow(conn):
    """Status can be updated to 'archived' (valid CHECK value)."""
    row = await _insert_flow(conn)
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_flows SET status = 'archived' WHERE id = $1", row["id"]
    )
    s = await conn.fetchval(
        f"SELECT status FROM {_SCHEMA}.wa_flows WHERE id = $1", row["id"]
    )
    assert s == "archived"


# ---------------------------------------------------------------------------
# validate_flow integration (pure function — no DB access)
# ---------------------------------------------------------------------------

async def test_validate_flow_called_on_draft_data(conn):
    """validate_flow() on a stored empty draft_data returns issues (no trigger)."""
    row = await _insert_flow(conn)
    dd = _parse_jsonb(row["draft_data"]) or {}
    issues = validate_flow(dd)
    # Empty draft has no trigger node → should have at least one issue
    assert len(issues) > 0


async def test_validate_flow_on_valid_graph_returns_empty(conn):
    """validate_flow() on a well-formed graph returns no issues."""
    valid_draft = {
        "nodes": [
            {"id": "t1", "type": "scheduledDate",
             "data": {"config": {"source": "gstr3b_due_date", "days_before": 7}}},
            {"id": "n1", "type": "sendMessage",
             "data": {"config": {"body": "Reminder"}}},
            {"id": "n2", "type": "endFlow", "data": {"config": {}}},
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "n1",
             "sourceHandle": "output", "targetHandle": "input"},
            {"id": "e2", "source": "n1", "target": "n2",
             "sourceHandle": "output", "targetHandle": "input"},
        ],
        "viewport": {},
    }
    row = await _insert_flow(conn, draft_data=valid_draft)
    dd = _parse_jsonb(row["draft_data"]) or {}
    issues = validate_flow(dd)
    assert issues == [], f"Expected no issues, got: {issues}"
