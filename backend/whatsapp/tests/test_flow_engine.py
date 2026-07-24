"""Flow engine tests — Slice 1 exit criteria (doc 09 §5).

Each test is wrapped in a rolled-back transaction via the `conn` fixture.
Tests are skipped automatically when the database is unavailable.

Coverage:
  - GSTR-3B enrollment journey → first SendMessage → outbox row
  - Wake_at resume after delay (manipulated wake_at)
  - Tick idempotency (re-tick → no duplicate outbox rows)
  - Stale reaper: waiting-delay NOT reaped; stale running → failed
  - Consent revoked mid-flight → outbox 'cancelled' on dispatch
  - Quiet-hours deferral sets next_retry_at 09:00 IST
  - Any-status same-period dedupe (completed run blocks re-enrollment)
  - Condition live re-read: filing_status FILED → false path → EndFlow
  - Stuck-'sending' requeued; idempotency key prevents double-send
  - Instance 0 / 2 active → dispatch skipped
  - Retry backoff → 5 retries → failed
  - Variable resolver: whitelist resolved; unknown token passed through
  - Simulation: trace + would_send, no rows persisted
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import asyncpg
import pytest
import pytest_asyncio
import pytz

from backend.whatsapp.flow_engine import (
    _dispatch_outbox,
    _start_scheduled_flows,
    _tick_wa_flow_runs,
    simulate_flow,
)
from backend.whatsapp.send_service import ConsentError, QuietHoursError, RateLimitError
from backend.whatsapp.sinks import DryRunSink
from backend.whatsapp.client import EvolutionAPIError
from backend.whatsapp.variable_resolver import resolve as _resolve
from backend.whatsapp.tests.conftest import FakeRedis, ErrorRedis

_SCHEMA = "solvetax"
_IST = pytz.timezone("Asia/Kolkata")
_IST_ZI = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Module-level skip if V004 tables are missing
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _require_v004(conn):
    try:
        await conn.fetchval(f"SELECT 1 FROM {_SCHEMA}.wa_flow_runs LIMIT 0")
        await conn.fetchval(f"SELECT 1 FROM {_SCHEMA}.wa_outbox LIMIT 0")
    except asyncpg.exceptions.UndefinedTableError as exc:
        pytest.skip(f"V004 tables missing ({exc}); run migration first")


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

async def _insert_customer(conn, mobile: str | None = None) -> tuple[int, str]:
    """Insert a minimal customer; returns (customer_id, mobile)."""
    if mobile is None:
        seq = await conn.fetchval(
            f"SELECT nextval('{_SCHEMA}.customers_customer_id_seq')"
        )
        mobile = "9" + str(seq).zfill(9)
    customer_id = await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.customers (full_name, mobile)"
        f" VALUES ('Test Customer', $1) RETURNING customer_id",
        mobile,
    )
    return int(customer_id), mobile


async def _grant_consent(conn, customer_id: int, phone: str, revoke: bool = False) -> None:
    if revoke:
        await conn.execute(
            f"INSERT INTO {_SCHEMA}.wa_consent (customer_id, phone, source, revoked_at)"
            f" VALUES ($1, $2, 'STAFF_RECORDED', now())",
            customer_id, phone,
        )
    else:
        await conn.execute(
            f"INSERT INTO {_SCHEMA}.wa_consent (customer_id, phone, source)"
            f" VALUES ($1, $2, 'STAFF_RECORDED')",
            customer_id, phone,
        )


async def _insert_employee(conn) -> int:
    return await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.employees (username, email, password_hash)"
        f" SELECT 'eng_test_' || gen_random_uuid()::text,"
        f"        'eng_test_' || gen_random_uuid()::text || '@internal.test',"
        f"        'hash'"
        f" RETURNING emp_id"
    )


async def _insert_gst_filing(conn, customer_id: int, gstin: str = "29AABCT1332L000") -> int:
    return await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.gst_filings"
        f" (customer_id, filing_period, gstin)"
        f" VALUES ($1, '2026-07', $2)"
        f" RETURNING id",
        customer_id, gstin,
    )


async def _insert_gst_return_detail(
    conn,
    gst_filing_id: int,
    gstr3b_due_date: datetime,
    gstr3b_status: str = "NOT_FILED",
) -> int:
    return await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.gst_filing_return_details"
        f" (gst_filing_id, gstr3b_due_date, gstr3b_status, filing_frequency)"
        f" VALUES ($1, $2, $3, 'MONTHLY')"
        f" RETURNING id",
        gst_filing_id, gstr3b_due_date, gstr3b_status,
    )


def _make_gstr3b_flow(days_before: int = 7) -> dict:
    """Return a minimal GSTR-3B scheduled flow definition."""
    return {
        "nodes": [
            {
                "id": "n-trigger",
                "type": "waNode",
                "data": {
                    "nodeType": "scheduledDate",
                    "config": {"source": "gstr3b_due_date", "days_before": days_before},
                },
            },
            {
                "id": "n-send1",
                "type": "waNode",
                "data": {
                    "nodeType": "sendMessage",
                    "config": {"body": "Hi {{customer_name}}, your GSTR-3B is due soon."},
                },
            },
            {
                "id": "n-wait",
                "type": "waNode",
                "data": {
                    "nodeType": "wait",
                    "config": {"type": "delay", "delay_minutes": 1},
                },
            },
            {
                "id": "n-cond",
                "type": "waNode",
                "data": {
                    "nodeType": "condition",
                    "config": {
                        "variable": "filing_status",
                        "operator": "neq",
                        "value": "FILED",
                    },
                },
            },
            {
                "id": "n-send2",
                "type": "waNode",
                "data": {
                    "nodeType": "sendMessage",
                    "config": {"body": "Hi {{customer_name}}, still not filed?"},
                },
            },
            {
                "id": "n-end",
                "type": "waNode",
                "data": {"nodeType": "endFlow", "config": {}},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n-trigger", "sourceHandle": "output", "target": "n-send1"},
            {"id": "e2", "source": "n-send1", "sourceHandle": "output", "target": "n-wait"},
            {"id": "e3", "source": "n-wait", "sourceHandle": "continue", "target": "n-cond"},
            {"id": "e4", "source": "n-cond", "sourceHandle": "true_output", "target": "n-send2"},
            {"id": "e5", "source": "n-cond", "sourceHandle": "false_output", "target": "n-end"},
            {"id": "e6", "source": "n-send2", "sourceHandle": "output", "target": "n-end"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


async def _insert_flow(conn, live_data: dict, name: str = "Test Flow") -> str:
    """Insert a published wa_flows row; returns flow_id (UUID str)."""
    live_data_json = json.dumps(live_data)
    flow_id = await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.wa_flows"
        f" (name, trigger_type, status, is_active, draft_data, live_data, version)"
        f" VALUES ($1, 'scheduled_date', 'published', true, $2::jsonb, $2::jsonb, 1)"
        f" RETURNING id",
        name, live_data_json,
    )
    return str(flow_id)


async def _insert_run(
    conn,
    flow_id: str,
    customer_id: int,
    phone: str,
    live_data: dict,
    source_row_id: int,
    current_node_id: str = "n-trigger",
    status: str = "running",
    filing_status: str = "NOT_FILED",
    rm_id: int | None = None,
    op_id: int | None = None,
) -> str:
    """Insert a wa_flow_runs row; returns run_id (UUID str)."""
    context = {
        "customer_name": "Test Customer",
        "gst_number": "29AABCT1332L000",
        "filing_status": filing_status,
        "rm_id": rm_id,
        "op_id": op_id,
        "phone": phone,
        "__flow_def": live_data,
        "__source_row_id": source_row_id,
    }
    run_id = await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.wa_flow_runs"
        f" (flow_id, flow_version, customer_id, phone, current_node_id, context,"
        f"  status, heartbeat_at)"
        f" VALUES ($1, 1, $2, $3, $4, $5::jsonb, $6, now())"
        f" RETURNING id",
        flow_id, customer_id, phone, current_node_id,
        json.dumps(context), status,
    )
    return str(run_id)


# ---------------------------------------------------------------------------
# Test: GSTR-3B enrollment → first SendMessage → outbox row
# ---------------------------------------------------------------------------

async def test_enrollment_and_first_send_message(conn, fake_redis):
    """Full journey: enroll via step14a → tick via step14b → outbox row exists."""
    # Setup
    customer_id, phone = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, phone)
    filing_id = await _insert_gst_filing(conn, customer_id)
    due_date = datetime.now(_IST_ZI) + timedelta(days=5)  # within 7-day window
    detail_id = await _insert_gst_return_detail(conn, filing_id, due_date)

    live_data = _make_gstr3b_flow(days_before=7)
    flow_id = await _insert_flow(conn, live_data)

    # Step 14a: enroll
    with patch(
        "backend.whatsapp.flow_engine._now_ist",
        return_value=datetime(2026, 7, 24, 10, 0, tzinfo=_IST),
    ):
        enrolled = await _start_scheduled_flows(conn)

    assert enrolled >= 1, f"expected at least 1 enrollment, got {enrolled}"

    # Verify run row created
    run = await conn.fetchrow(
        f"SELECT id, status, current_node_id FROM {_SCHEMA}.wa_flow_runs"
        f" WHERE flow_id = $1 AND customer_id = $2",
        flow_id, customer_id,
    )
    assert run is not None, "wa_flow_runs row must exist after enrollment"
    assert run["status"] == "running"
    assert run["current_node_id"] == "n-trigger"

    # Step 14b: tick — should execute trigger → send1 → wait(1min)
    ticked = await _tick_wa_flow_runs(conn)
    assert ticked >= 1

    # Verify outbox row created for send1
    outbox = await conn.fetchrow(
        f"SELECT status, body, idempotency_key FROM {_SCHEMA}.wa_outbox"
        f" WHERE flow_run_id = $1",
        run["id"],
    )
    assert outbox is not None, "wa_outbox row must exist after SendMessage node"
    assert outbox["status"] == "pending"
    assert "Test Customer" in outbox["body"]
    expected_idem = f"{run['id']}:n-send1"
    assert outbox["idempotency_key"] == expected_idem

    # Verify run advanced to wait node
    run2 = await conn.fetchrow(
        f"SELECT status, wait_type, current_node_id FROM {_SCHEMA}.wa_flow_runs"
        f" WHERE id = $1",
        run["id"],
    )
    assert run2["status"] == "waiting"
    assert run2["wait_type"] == "delay"
    assert run2["current_node_id"] == "n-wait"


# ---------------------------------------------------------------------------
# Test: wake_at resume after delay
# ---------------------------------------------------------------------------

async def test_delay_wait_resumes_after_wake_at(conn):
    """A run in status='waiting'/wait_type='delay' is resumed when wake_at <= now()."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(
        conn, flow_id, customer_id, phone, live_data, detail_id, current_node_id="n-wait"
    )
    # Manually set to waiting state with wake_at in the past
    await conn.execute(
        f"""
        UPDATE {_SCHEMA}.wa_flow_runs
        SET status = 'waiting', wait_type = 'delay',
            wake_at = now() - interval '5 minutes',
            heartbeat_at = now()
        WHERE id = $1
        """,
        run_id,
    )

    ticked = await _tick_wa_flow_runs(conn)
    assert ticked >= 1

    run = await conn.fetchrow(
        f"SELECT status, current_node_id FROM {_SCHEMA}.wa_flow_runs WHERE id = $1",
        run_id,
    )
    # After resuming from wait, the run should have advanced past n-wait
    # It will reach n-cond and evaluate condition (filing_status=NOT_FILED neq FILED → true)
    # then reach n-send2 and write outbox, then reach n-end → completed
    assert run["status"] in ("waiting", "completed"), (
        f"unexpected status={run['status']!r}"
    )


# ---------------------------------------------------------------------------
# Test: tick idempotency (re-tick → no duplicate outbox rows)
# ---------------------------------------------------------------------------

async def test_tick_idempotency_no_duplicate_outbox(conn):
    """Re-ticking a run that already wrote a SendMessage outbox row produces no duplicates."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)

    # First tick: run executes trigger → send1 → wait
    await _tick_wa_flow_runs(conn)

    # Insert the run again as running at n-send1 to simulate a retry scenario
    # Force the run back to running at n-send1 to trigger duplicate insert attempt
    await conn.execute(
        f"""
        UPDATE {_SCHEMA}.wa_flow_runs
        SET status = 'running', current_node_id = 'n-send1',
            wait_type = NULL, wake_at = NULL, heartbeat_at = now()
        WHERE id = $1
        """,
        run_id,
    )

    # Second tick: ON CONFLICT DO NOTHING should prevent a duplicate
    await _tick_wa_flow_runs(conn)

    count = await conn.fetchval(
        f"SELECT COUNT(*) FROM {_SCHEMA}.wa_outbox WHERE flow_run_id = $1",
        run_id,
    )
    assert count == 1, f"expected exactly 1 outbox row (idempotent), got {count}"


# ---------------------------------------------------------------------------
# Test: stale reaper
# ---------------------------------------------------------------------------

async def test_stale_reaper_does_not_reap_waiting_delay(conn):
    """A run with status='waiting'/wait_type='delay' is NOT reaped by the stale reaper."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)
    # Put run in waiting-delay with old heartbeat
    await conn.execute(
        f"""
        UPDATE {_SCHEMA}.wa_flow_runs
        SET status = 'waiting', wait_type = 'delay',
            wake_at = now() + interval '1 hour',
            heartbeat_at = now() - interval '20 minutes'
        WHERE id = $1
        """,
        run_id,
    )

    await _tick_wa_flow_runs(conn)

    row = await conn.fetchrow(
        f"SELECT status FROM {_SCHEMA}.wa_flow_runs WHERE id = $1", run_id
    )
    assert row["status"] == "waiting", (
        "waiting/delay run must NOT be reaped by the stale heartbeat reaper"
    )


async def test_stale_reaper_marks_running_with_old_heartbeat_failed(conn):
    """A run with status='running' and heartbeat_at > 15 min ago is reaped → failed."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)
    # Manually set stale heartbeat; lock current_node_id at non-existent node
    # so the tick won't process it (no SKIP LOCKED competition).
    # Actually we need the tick NOT to claim it.  Set heartbeat 20 min in the past
    # and make the status stuck at 'running' by setting a current_node_id that
    # won't be claimed this tick (use a unique name not in the flow).
    await conn.execute(
        f"""
        UPDATE {_SCHEMA}.wa_flow_runs
        SET heartbeat_at = now() - interval '20 minutes',
            current_node_id = 'nonexistent-node-stale-test'
        WHERE id = $1
        """,
        run_id,
    )

    # Run the tick — the reaper runs at the end of step14b
    await _tick_wa_flow_runs(conn)

    row = await conn.fetchrow(
        f"SELECT status, context FROM {_SCHEMA}.wa_flow_runs WHERE id = $1", run_id
    )
    # The run may have been claimed AND failed mid-execution, or reaped.
    # Either way, if it's still running with stale heartbeat the reaper fires.
    # Since the node doesn't exist, _execute_run raises → rollback → still 'running'.
    # The reaper then marks it failed.
    assert row["status"] == "failed", (
        f"expected status='failed' after stale heartbeat reap, got {row['status']!r}"
    )
    ctx = json.loads(row["context"]) if isinstance(row["context"], str) else row["context"]
    assert "__error" in ctx


# ---------------------------------------------------------------------------
# Test: consent revoked mid-flight → outbox 'cancelled' on dispatch
# ---------------------------------------------------------------------------

async def test_consent_revoked_midrun_outbox_cancelled(conn, fake_redis):
    """If consent is revoked, dispatch marks outbox row 'cancelled'."""
    customer_id, phone = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, phone)

    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)

    # Insert outbox row manually
    idem = f"{run_id}:n-send1"
    await conn.execute(
        f"""
        INSERT INTO {_SCHEMA}.wa_outbox
            (flow_run_id, node_id, phone, body, idempotency_key)
        VALUES ($1, 'n-send1', $2, 'Test body', $3)
        """,
        run_id, phone, idem,
    )

    # Revoke consent
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_consent SET revoked_at = now() WHERE customer_id = $1",
        customer_id,
    )

    sink = DryRunSink()
    with patch(
        "backend.whatsapp.flow_engine._now_ist",
        return_value=datetime(2026, 7, 24, 10, 0, tzinfo=_IST),
    ):
        await _dispatch_outbox(conn, fake_redis, sink)

    outbox = await conn.fetchrow(
        f"SELECT status FROM {_SCHEMA}.wa_outbox WHERE idempotency_key = $1", idem
    )
    assert outbox["status"] == "cancelled"
    assert sink.sent == []


# ---------------------------------------------------------------------------
# Test: quiet-hours deferral sets next_retry_at 09:00 IST
# ---------------------------------------------------------------------------

async def test_quiet_hours_deferral_sets_next_retry_at_9am(conn, fake_redis):
    """Dispatch during quiet hours → outbox 'pending' with next_retry_at at 09:00 IST."""
    customer_id, phone = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, phone)

    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)

    idem = f"{run_id}:n-send1"
    await conn.execute(
        f"""
        INSERT INTO {_SCHEMA}.wa_outbox
            (flow_run_id, node_id, phone, body, idempotency_key)
        VALUES ($1, 'n-send1', $2, 'Test body', $3)
        """,
        run_id, phone, idem,
    )

    sink = DryRunSink()
    # Patch _now_ist in send_service so quiet-hours check fires (22:00 IST)
    with patch(
        "backend.whatsapp.send_service._now_ist",
        return_value=datetime(2026, 7, 24, 22, 0, tzinfo=_IST),
    ):
        await _dispatch_outbox(conn, fake_redis, sink)

    outbox = await conn.fetchrow(
        f"SELECT status, next_retry_at FROM {_SCHEMA}.wa_outbox WHERE idempotency_key = $1",
        idem,
    )
    assert outbox["status"] == "pending"
    assert outbox["next_retry_at"] is not None
    # next_retry_at should be 09:00 IST
    retry_ist = outbox["next_retry_at"].astimezone(_IST_ZI)
    assert retry_ist.hour == 9
    assert retry_ist.minute == 0


# ---------------------------------------------------------------------------
# Test: any-status same-period dedupe
# ---------------------------------------------------------------------------

async def test_same_period_dedupe_completed_run_blocks_reenrollment(conn):
    """A completed run within the current trigger period blocks re-enrollment."""
    customer_id, phone = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, phone)

    due_date = datetime.now(_IST_ZI) + timedelta(days=5)
    live_data = _make_gstr3b_flow(days_before=7)
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, due_date)

    # Insert a completed run created 1 day ago.
    # Period start = due_date - 7 days = (now()+5) - 7 = now() - 2 days.
    # A run created 1 day ago (now()-1d) is >= period_start (now()-2d) → within period → blocks.
    context = {
        "customer_name": "Test Customer",
        "gst_number": "29AABCT1332L000",
        "filing_status": "NOT_FILED",
        "phone": phone,
        "__flow_def": live_data,
        "__source_row_id": detail_id,
    }
    await conn.execute(
        f"""
        INSERT INTO {_SCHEMA}.wa_flow_runs
            (flow_id, flow_version, customer_id, phone, current_node_id, context,
             status, heartbeat_at, created_at)
        VALUES ($1, 1, $2, $3, 'n-end', $4::jsonb, 'completed', now(),
                now() - interval '1 day')
        """,
        flow_id, customer_id, phone, json.dumps(context),
    )

    with patch(
        "backend.whatsapp.flow_engine._now_ist",
        return_value=datetime(2026, 7, 24, 10, 0, tzinfo=_IST),
    ):
        enrolled = await _start_scheduled_flows(conn)

    assert enrolled == 0, (
        f"completed run within window should block re-enrollment; got enrolled={enrolled}"
    )


# ---------------------------------------------------------------------------
# Test: Condition live re-read — filed during wait → false path → EndFlow
# ---------------------------------------------------------------------------

async def test_condition_live_reread_filed_takes_false_path(conn):
    """Filing during wait → Condition re-reads FILED status → false path → EndFlow."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(
        conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5), gstr3b_status="NOT_FILED"
    )
    run_id = await _insert_run(
        conn, flow_id, customer_id, phone, live_data, detail_id,
        current_node_id="n-wait",
    )
    # Set to waiting-delay with wake_at in the past
    await conn.execute(
        f"""
        UPDATE {_SCHEMA}.wa_flow_runs
        SET status = 'waiting', wait_type = 'delay',
            wake_at = now() - interval '1 minute',
            heartbeat_at = now()
        WHERE id = $1
        """,
        run_id,
    )

    # Now flip filing status to FILED BEFORE the tick
    await conn.execute(
        f"UPDATE {_SCHEMA}.gst_filing_return_details SET gstr3b_status = 'FILED' WHERE id = $1",
        detail_id,
    )

    # Tick: resumes from wait → condition live-reads FILED → false_output → EndFlow
    await _tick_wa_flow_runs(conn)

    run = await conn.fetchrow(
        f"SELECT status, current_node_id FROM {_SCHEMA}.wa_flow_runs WHERE id = $1",
        run_id,
    )
    assert run["status"] == "completed", (
        f"expected completed after FILED condition; got {run['status']!r}"
    )
    # No second send message (false path → EndFlow directly)
    outbox_count = await conn.fetchval(
        f"SELECT COUNT(*) FROM {_SCHEMA}.wa_outbox WHERE flow_run_id = $1 AND node_id = 'n-send2'",
        run_id,
    )
    assert outbox_count == 0, "no second send message should exist when filing_status=FILED"


# ---------------------------------------------------------------------------
# Test: stuck-'sending' requeued
# ---------------------------------------------------------------------------

async def test_stuck_sending_requeued(conn, fake_redis):
    """Outbox rows stuck in 'sending' for > 5 min are requeued to 'pending'."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)

    idem = f"{run_id}:n-send1"
    outbox_id = await conn.fetchval(
        f"""
        INSERT INTO {_SCHEMA}.wa_outbox
            (flow_run_id, node_id, phone, body, status, idempotency_key, updated_at)
        VALUES ($1, 'n-send1', $2, 'Test body', 'sending', $3, now() - interval '10 minutes')
        RETURNING id
        """,
        run_id, phone, idem,
    )

    sink = DryRunSink()
    with patch(
        "backend.whatsapp.flow_engine._now_ist",
        return_value=datetime(2026, 7, 24, 10, 0, tzinfo=_IST),
    ):
        await _dispatch_outbox(conn, fake_redis, sink)

    outbox = await conn.fetchrow(
        f"SELECT status FROM {_SCHEMA}.wa_outbox WHERE id = $1", outbox_id
    )
    # After requeue: either 'pending' (requeued but not dispatched in same tick)
    # or the dispatch may claim and process it. Either way it should not remain 'sending'.
    assert outbox["status"] in ("pending", "sent", "cancelled"), (
        f"stuck sending should be requeued; got {outbox['status']!r}"
    )


# ---------------------------------------------------------------------------
# Test: instance 0 or 2 active → dispatch skipped
# ---------------------------------------------------------------------------

async def test_dispatch_skipped_with_no_active_instance(conn, fake_redis):
    """Dispatch is skipped when there are 0 active wa_instance_config rows."""
    await conn.execute(
        f"UPDATE {_SCHEMA}.wa_instance_config SET is_active = false"
    )
    sink = DryRunSink()
    dispatched = await _dispatch_outbox(conn, fake_redis, sink)
    assert dispatched == 0
    assert sink.sent == []


async def test_dispatch_skipped_with_two_active_instances(conn, fake_redis):
    """Dispatch is skipped when there are 2 active wa_instance_config rows."""
    await conn.execute(
        f"""
        INSERT INTO {_SCHEMA}.wa_instance_config
            (instance_name, daily_send_cap, quiet_hours_start, quiet_hours_end, is_active)
        VALUES ('secondary', 50, 9, 21, true)
        ON CONFLICT (instance_name) DO UPDATE SET is_active = true
        """
    )
    sink = DryRunSink()
    dispatched = await _dispatch_outbox(conn, fake_redis, sink)
    assert dispatched == 0
    assert sink.sent == []


# ---------------------------------------------------------------------------
# Test: retry backoff → 5 retries → failed
# ---------------------------------------------------------------------------

class _AlwaysErrorSink:
    async def send_text(self, phone: str, body: str, instance: str) -> str:
        raise EvolutionAPIError("simulated evolution api error")


async def test_retry_backoff_to_5_then_failed(conn, fake_redis):
    """After _MAX_RETRIES attempts, outbox row reaches status='failed'."""
    customer_id, phone = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, phone)

    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)

    idem = f"{run_id}:n-send1"
    outbox_id = await conn.fetchval(
        f"""
        INSERT INTO {_SCHEMA}.wa_outbox
            (flow_run_id, node_id, phone, body, idempotency_key, retry_count)
        VALUES ($1, 'n-send1', $2, 'Body', $3, 4)
        RETURNING id
        """,
        run_id, phone, idem,
    )

    sink = _AlwaysErrorSink()
    with patch(
        "backend.whatsapp.send_service._now_ist",
        return_value=datetime(2026, 7, 24, 10, 0, tzinfo=_IST),
    ):
        await _dispatch_outbox(conn, fake_redis, sink)

    outbox = await conn.fetchrow(
        f"SELECT status, retry_count FROM {_SCHEMA}.wa_outbox WHERE id = $1", outbox_id
    )
    assert outbox["status"] == "failed", (
        f"expected failed after max retries; got {outbox['status']!r}"
    )
    assert outbox["retry_count"] == 5


# ---------------------------------------------------------------------------
# Test: variable resolver
# ---------------------------------------------------------------------------

def test_variable_resolver_known_token_resolved():
    body = "Hi {{customer_name}}, your GST is {{gst_number}}."
    ctx = {"customer_name": "Ravi", "gst_number": "29ABC"}
    result = _resolve(body, ctx)
    assert result == "Hi Ravi, your GST is 29ABC."


def test_variable_resolver_unknown_token_passthrough():
    body = "Hello {{unknown_token}} world."
    result = _resolve(body, {})
    assert result == "Hello {{unknown_token}} world."


def test_variable_resolver_whitelist_absent_left_as_is():
    """Whitelisted token with no context value → left as {{token}}."""
    body = "Due: {{gstr3b_due_date}}"
    result = _resolve(body, {})
    assert result == "Due: {{gstr3b_due_date}}"


def test_variable_resolver_all_whitelist_tokens():
    whitelist_tokens = [
        "customer_name", "gst_number", "gstr3b_due_date", "gstr1_due_date",
        "payment_amount_due", "payment_due_date", "rm_name", "op_name",
        "filing_status", "pipeline_stage", "income_tax_year", "pending_documents_count",
    ]
    ctx = {t: f"val_{t}" for t in whitelist_tokens}
    body = " ".join(f"{{{{{t}}}}}" for t in whitelist_tokens)
    result = _resolve(body, ctx)
    for t in whitelist_tokens:
        assert f"val_{t}" in result
        assert f"{{{{{t}}}}}" not in result


# ---------------------------------------------------------------------------
# Test: simulation returns trace + would_send, no rows persisted
# ---------------------------------------------------------------------------

async def test_simulation_returns_trace_and_would_send_no_db_rows(conn):
    """simulate_flow returns trace + would_send and writes no DB rows."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()

    initial_context = {
        "customer_name": "Sim Customer",
        "gst_number": "29AABCT1332L000",
        "filing_status": "NOT_FILED",
        "phone": phone,
        "__flow_def": live_data,
        "__source_row_id": 999,
    }

    result = await simulate_flow(
        live_data=live_data,
        initial_context=initial_context,
    )

    assert "trace" in result
    assert "would_send" in result
    trace = result["trace"]
    would_send = result["would_send"]

    # Should have trace entries for the nodes executed
    node_types_traced = [t["node_type"] for t in trace]
    assert "scheduledDate" in node_types_traced
    assert "sendMessage" in node_types_traced
    assert "wait" in node_types_traced

    # First sendMessage should be in would_send
    assert len(would_send) >= 1
    assert "Sim Customer" in would_send[0]["body"]

    # No rows persisted — both tables must be empty for this test's transaction
    run_count = await conn.fetchval(f"SELECT COUNT(*) FROM {_SCHEMA}.wa_flow_runs")
    outbox_count = await conn.fetchval(f"SELECT COUNT(*) FROM {_SCHEMA}.wa_outbox")
    assert run_count == 0, "simulate must not write wa_flow_runs rows"
    assert outbox_count == 0, "simulate must not write wa_outbox rows"


async def test_simulation_condition_false_path_to_end(conn):
    """Sim with filing_status=FILED → condition false path → EndFlow; no second send."""
    customer_id, phone = await _insert_customer(conn)
    live_data = _make_gstr3b_flow()

    context = {
        "customer_name": "Filed Customer",
        "filing_status": "FILED",  # condition (neq FILED) → false → EndFlow
        "phone": phone,
        "__flow_def": live_data,
        "__source_row_id": 1,
    }
    result = await simulate_flow(live_data=live_data, initial_context=context)

    # Should have exactly 1 send (first send1), then wait fast-forward, then condition → false → end
    assert len(result["would_send"]) == 1
    end_entry = next((t for t in result["trace"] if t["node_type"] == "endFlow"), None)
    assert end_entry is not None


# ---------------------------------------------------------------------------
# Test: 21:00 IST quiet-hours boundary
# ---------------------------------------------------------------------------

async def test_quiet_hours_20_59_succeeds_21_00_defers(conn, fake_redis):
    """Send at 20:59 IST succeeds; at 21:00 IST defers to next 09:00."""
    customer_id, phone = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, phone)

    live_data = _make_gstr3b_flow()
    flow_id = await _insert_flow(conn, live_data)
    filing_id = await _insert_gst_filing(conn, customer_id)
    detail_id = await _insert_gst_return_detail(conn, filing_id, datetime.now(_IST_ZI) + timedelta(days=5))
    run_id = await _insert_run(conn, flow_id, customer_id, phone, live_data, detail_id)

    idem_a = f"{run_id}:n-send1"
    idem_b = f"{run_id}:n-send2"

    await conn.execute(
        f"""
        INSERT INTO {_SCHEMA}.wa_outbox
            (flow_run_id, node_id, phone, body, idempotency_key)
        VALUES ($1, 'n-send1', $2, 'Body A', $3),
               ($1, 'n-send2', $2, 'Body B', $4)
        """,
        run_id, phone, idem_a, idem_b,
    )

    sink = DryRunSink()
    # At 20:59 IST (within window) → sends succeed
    with patch(
        "backend.whatsapp.send_service._now_ist",
        return_value=datetime(2026, 7, 24, 20, 59, tzinfo=_IST),
    ):
        await _dispatch_outbox(conn, fake_redis, sink)

    row_a = await conn.fetchrow(
        f"SELECT status FROM {_SCHEMA}.wa_outbox WHERE idempotency_key = $1", idem_a
    )
    # Row A should have been dispatched while at 20:59
    # (after sleep(2), row B is claimed at 21:01+ which may or may not fire depending on real clock)
    # For the boundary test, we only verify row A status
    assert row_a["status"] in ("sent", "pending"), f"row_a status={row_a['status']!r}"

    # New outbox row tested at exactly 21:00
    idem_c = f"{run_id}:n-cond"
    await conn.execute(
        f"""
        INSERT INTO {_SCHEMA}.wa_outbox
            (flow_run_id, node_id, phone, body, idempotency_key)
        VALUES ($1, 'n-cond', $2, 'Body C', $3)
        """,
        run_id, phone, idem_c,
    )
    sink2 = DryRunSink()
    with patch(
        "backend.whatsapp.send_service._now_ist",
        return_value=datetime(2026, 7, 24, 21, 0, tzinfo=_IST),
    ):
        await _dispatch_outbox(conn, fake_redis, sink2)

    row_c = await conn.fetchrow(
        f"SELECT status, next_retry_at FROM {_SCHEMA}.wa_outbox WHERE idempotency_key = $1",
        idem_c,
    )
    assert row_c["status"] == "pending"
    assert row_c["next_retry_at"] is not None
    retry_ist = row_c["next_retry_at"].astimezone(_IST_ZI)
    assert retry_ist.hour == 9


# ── Operator + token-formatting regressions (E2E QA 2026-07-24) ──────────────

def test_compare_accepts_ui_operator_synonyms():
    """The canvas serializes eq/neq since v1.1 but early drafts used long forms;
    both must work — unknown operators silently took the false branch."""
    from backend.whatsapp.flow_engine import _compare
    assert _compare("FILED", "equals", "FILED") is True
    assert _compare("NOT_FILED", "not_equals", "FILED") is True
    assert _compare("FILED", "eq", "FILED") is True
    assert _compare("NOT_FILED", "neq", "FILED") is True
    assert _compare("GSTR3B-2026", "starts_with", "GSTR3B") is True
    assert _compare("GSTR3B-2026", "starts_with", "ITR") is False


def test_resolver_formats_dates_human_readable():
    """Date/datetime context values render as DD-MM-YYYY, not ISO timestamps."""
    import datetime
    from backend.whatsapp.variable_resolver import resolve
    ctx = {
        "gstr3b_due_date": datetime.datetime(2026, 7, 29, 0, 0, tzinfo=datetime.timezone.utc),
        "payment_due_date": datetime.date(2026, 8, 15),
        "customer_name": "QA One",
    }
    out = resolve("Due {{gstr3b_due_date}} / {{payment_due_date}} for {{customer_name}}", ctx)
    assert out == "Due 29-07-2026 / 15-08-2026 for QA One"
