"""Tests for create_task_for_emp (Slice 0 exit criteria).

Covers
------
- NOT NULL columns satisfied (scheduled_at, time_slots, status)
- time_slots = [scheduled_at]
- Next-business-day logic: Friday → Monday (Fri→Mon case per the spec)
- Explicit scheduled_at is used as-is (no override)

No network calls are made.
"""
from datetime import date as date_cls, datetime, time as time_cls
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from backend.employee_tasks.employee_tasks import create_task_for_emp

_IST = ZoneInfo("Asia/Kolkata")
_SCHEMA = "solvetax"


async def _insert_employee(conn) -> int:
    """Insert a minimal employee row; returns emp_id."""
    return await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.employees (username, email, password_hash)"
        f" SELECT 'wa_test_' || gen_random_uuid()::text,"
        f"        'wa_test_' || gen_random_uuid()::text || '@internal.test',"
        f"        'fakehash'"
        f" RETURNING emp_id"
    )


# ---------------------------------------------------------------------------
# Explicit scheduled_at
# ---------------------------------------------------------------------------

async def test_explicit_scheduled_at_satisfies_not_nulls(conn):
    """Passing scheduled_at explicitly: all NOT NULL columns must be set."""
    emp_id = await _insert_employee(conn)
    scheduled = datetime(2024, 3, 18, 10, 0, 0, tzinfo=_IST)

    task_id = await create_task_for_emp(
        conn, emp_id, "Follow up on GST docs", "Please upload Form 16", scheduled
    )
    assert isinstance(task_id, int)

    row = await conn.fetchrow(
        f"SELECT emp_id, title, description, scheduled_at, time_slots, status"
        f" FROM {_SCHEMA}.employee_tasks WHERE id = $1",
        task_id,
    )
    assert row["emp_id"] == emp_id
    assert row["title"] == "Follow up on GST docs"
    assert row["description"] == "Please upload Form 16"
    assert row["status"] == "PENDING"
    # time_slots must equal [scheduled_at]
    assert len(row["time_slots"]) == 1
    # Compare as UTC-normalised instants (asyncpg returns TIMESTAMPTZ in UTC)
    expected_utc = scheduled.astimezone(ZoneInfo("UTC"))
    actual_utc = row["time_slots"][0].astimezone(ZoneInfo("UTC"))
    assert actual_utc == expected_utc
    assert row["scheduled_at"].astimezone(ZoneInfo("UTC")) == expected_utc


async def test_explicit_scheduled_at_no_description(conn):
    """description is optional (None); all NOT NULLs still satisfied."""
    emp_id = await _insert_employee(conn)
    scheduled = datetime(2024, 3, 18, 10, 0, 0, tzinfo=_IST)
    task_id = await create_task_for_emp(conn, emp_id, "Quick nudge", scheduled_at=scheduled)

    row = await conn.fetchrow(
        f"SELECT description, status, time_slots FROM {_SCHEMA}.employee_tasks WHERE id = $1",
        task_id,
    )
    assert row["description"] is None
    assert row["status"] == "PENDING"
    assert len(row["time_slots"]) == 1


# ---------------------------------------------------------------------------
# Next-business-day: Friday → Monday
# ---------------------------------------------------------------------------

async def test_next_business_day_friday_to_monday(conn):
    """When today is Friday, scheduled_at must land on Monday at 10:00 IST."""
    emp_id = await _insert_employee(conn)

    friday = date_cls(2024, 1, 12)  # Fri 12-Jan-2024
    with patch(
        "backend.employee_tasks.employee_tasks._date_today_ist",
        return_value=friday,
    ):
        task_id = await create_task_for_emp(conn, emp_id, "System nudge")

    row = await conn.fetchrow(
        f"SELECT scheduled_at, time_slots FROM {_SCHEMA}.employee_tasks WHERE id = $1",
        task_id,
    )
    # scheduled_at in IST must be Monday 15-Jan-2024 10:00
    sched_ist = row["scheduled_at"].astimezone(_IST)
    assert sched_ist.date() == date_cls(2024, 1, 15), f"Expected Mon 15-Jan, got {sched_ist.date()}"
    assert sched_ist.hour == 10
    assert sched_ist.minute == 0
    # time_slots == [scheduled_at]
    assert len(row["time_slots"]) == 1
    slot_ist = row["time_slots"][0].astimezone(_IST)
    assert slot_ist == sched_ist


async def test_next_business_day_saturday_to_monday(conn):
    """Saturday + 1 = Sunday → skip again → Monday."""
    emp_id = await _insert_employee(conn)

    saturday = date_cls(2024, 1, 13)  # Sat 13-Jan-2024
    with patch(
        "backend.employee_tasks.employee_tasks._date_today_ist",
        return_value=saturday,
    ):
        task_id = await create_task_for_emp(conn, emp_id, "Weekend nudge")

    row = await conn.fetchrow(
        f"SELECT scheduled_at FROM {_SCHEMA}.employee_tasks WHERE id = $1",
        task_id,
    )
    sched_ist = row["scheduled_at"].astimezone(_IST)
    # Saturday+1=Sun (skip), Sun+1=Mon (weekday 0)
    assert sched_ist.date() == date_cls(2024, 1, 15)
    assert sched_ist.hour == 10


async def test_next_business_day_thursday_to_friday(conn):
    """Thursday + 1 = Friday (normal weekday); no skip needed."""
    emp_id = await _insert_employee(conn)

    thursday = date_cls(2024, 1, 11)  # Thu 11-Jan-2024
    with patch(
        "backend.employee_tasks.employee_tasks._date_today_ist",
        return_value=thursday,
    ):
        task_id = await create_task_for_emp(conn, emp_id, "Thu nudge")

    row = await conn.fetchrow(
        f"SELECT scheduled_at FROM {_SCHEMA}.employee_tasks WHERE id = $1",
        task_id,
    )
    sched_ist = row["scheduled_at"].astimezone(_IST)
    assert sched_ist.date() == date_cls(2024, 1, 12)  # Friday
    assert sched_ist.weekday() == 4  # 4 = Friday
    assert sched_ist.hour == 10
