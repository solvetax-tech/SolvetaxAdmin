"""Tests for send_service.send() guardrails (Slice 0 exit criteria).

Covers
------
- ConsentError on no consent row
- ConsentError on revoked consent row
- QuietHoursError outside the window (before start)
- QuietHoursError at exactly quiet_hours_end (boundary)
- QuietHoursError IST conversion (mock returns IST time so .hour reads IST)
- RateLimitError when counter is at daily_send_cap
- RateLimitError when Redis is unreachable (fail-closed)
- Happy path: DryRunSink receives the phone and body

No network calls are made anywhere in this suite.
"""
from datetime import datetime
from unittest.mock import patch

import pytz
import pytest

from backend.whatsapp.send_service import (
    ConsentError,
    QuietHoursError,
    RateLimitError,
    send,
)
from backend.whatsapp.sinks import DryRunSink
from backend.whatsapp.tests.conftest import FakeRedis, ErrorRedis

_IST = pytz.timezone("Asia/Kolkata")
_SCHEMA = "solvetax"

# A phone number that won't exist in the test DB's committed data.
_TEST_PHONE = "9000000001"


def _ist(hour: int, minute: int = 0) -> datetime:
    """Return a timezone-aware IST datetime for the given hour (fixed date)."""
    return _IST.localize(datetime(2024, 1, 15, hour, minute, 0))


# ---------------------------------------------------------------------------
# Helpers shared by tests
# ---------------------------------------------------------------------------

async def _insert_customer(conn) -> int:
    """Insert a minimal customer row; returns customer_id."""
    return await conn.fetchval(
        f"INSERT INTO {_SCHEMA}.customers (full_name, mobile)"
        f" SELECT 'WA Test Customer', '9' || LPAD(nextval('{_SCHEMA}.customers_customer_id_seq')::text, 9, '0')"
        f" RETURNING customer_id"
    )


async def _grant_consent(conn, customer_id: int, phone: str, revoke: bool = False) -> None:
    if revoke:
        await conn.execute(
            f"INSERT INTO {_SCHEMA}.wa_consent"
            f" (customer_id, phone, source, revoked_at)"
            f" VALUES ($1, $2, 'STAFF_RECORDED', now())",
            customer_id, phone,
        )
    else:
        await conn.execute(
            f"INSERT INTO {_SCHEMA}.wa_consent"
            f" (customer_id, phone, source)"
            f" VALUES ($1, $2, 'STAFF_RECORDED')",
            customer_id, phone,
        )


# ---------------------------------------------------------------------------
# ConsentError tests
# ---------------------------------------------------------------------------

async def test_consent_error_no_row(conn, fake_redis):
    """send() raises ConsentError when no wa_consent row exists for the phone."""
    sink = DryRunSink()
    # Do NOT insert any consent row.
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(10)):
        with pytest.raises(ConsentError):
            await send(conn, fake_redis, _TEST_PHONE, "Hello", "test", sink)

    assert sink.sent == [], "sink must not be called when consent is absent"


async def test_consent_error_revoked_row(conn, fake_redis):
    """send() raises ConsentError when the consent row is revoked."""
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE, revoke=True)

    sink = DryRunSink()
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(10)):
        with pytest.raises(ConsentError):
            await send(conn, fake_redis, _TEST_PHONE, "Hello", "test", sink)

    assert sink.sent == []


# ---------------------------------------------------------------------------
# QuietHoursError tests
# ---------------------------------------------------------------------------

async def test_quiet_hours_before_start(conn, fake_redis):
    """send() raises QuietHoursError when hour < quiet_hours_start (9)."""
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE)

    sink = DryRunSink()
    # 08:00 IST is before quiet_hours_start=9
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(8)):
        with pytest.raises(QuietHoursError):
            await send(conn, fake_redis, _TEST_PHONE, "Hello", "test", sink)

    assert sink.sent == []


async def test_quiet_hours_at_end_boundary(conn, fake_redis):
    """send() raises QuietHoursError at exactly quiet_hours_end (21:00 IST).

    The window is [start, end) — end itself is NOT in the allowed window.
    """
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE)

    sink = DryRunSink()
    # 21:00 IST = quiet_hours_end; not (9 <= 21 < 21) → True → raise
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(21)):
        with pytest.raises(QuietHoursError):
            await send(conn, fake_redis, _TEST_PHONE, "Hello", "test", sink)

    assert sink.sent == []


async def test_quiet_hours_ist_conversion(conn, fake_redis):
    """The hour check uses IST (not UTC).

    09:00 IST = 03:30 UTC.  Passing a 9am IST mock time must be accepted
    (it is within [9, 21)); the test would fail if UTC were used (hour=3).
    """
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE)

    sink = DryRunSink()
    # 09:00 IST — within window; Redis counter starts at 0 so cap not hit
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(9)):
        # Should NOT raise QuietHoursError; will reach sink
        await send(conn, fake_redis, _TEST_PHONE, "IST test", "test", sink)

    assert len(sink.sent) == 1, "send must succeed at 09:00 IST (boundary is inclusive)"


# ---------------------------------------------------------------------------
# RateLimitError tests
# ---------------------------------------------------------------------------

async def test_rate_limit_at_cap(conn, fake_redis):
    """send() raises RateLimitError when the counter reaches daily_send_cap.

    Strategy: pre-seed the Redis counter to daily_send_cap; after INCR it
    becomes cap+1 which exceeds the cap → RateLimitError.
    """
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE)

    # Read cap from the seed row inserted by the migration
    config = await conn.fetchrow(
        f"SELECT instance_name, daily_send_cap"
        f" FROM {_SCHEMA}.wa_instance_config WHERE is_active = true LIMIT 1"
    )
    assert config is not None, "wa_instance_config seed row must exist (run migrations first)"
    instance_name = config["instance_name"]
    cap: int = config["daily_send_cap"]

    mock_time = _ist(10)
    date_str = mock_time.strftime("%Y-%m-%d")
    rate_key = f"wa:daily_sends:{instance_name}:{date_str}"
    # Pre-seed to cap so the next INCR pushes it to cap+1 > cap
    fake_redis.set_count(rate_key, cap)

    sink = DryRunSink()
    with patch("backend.whatsapp.send_service._now_ist", return_value=mock_time):
        with pytest.raises(RateLimitError):
            await send(conn, fake_redis, _TEST_PHONE, "Hello", "test", sink)

    assert sink.sent == []


async def test_rate_limit_redis_unreachable_fails_closed(conn, error_redis):
    """Redis unreachable → RateLimitError (fail-CLOSED, not fail-open).

    An uncounted send is a ban-risk send; we must never allow it through
    when we cannot maintain the counter.
    """
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE)

    sink = DryRunSink()
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(10)):
        with pytest.raises(RateLimitError):
            await send(conn, error_redis, _TEST_PHONE, "Hello", "test", sink)

    assert sink.sent == [], "sink must NOT be called when Redis is unreachable"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_happy_path_reaches_dry_run_sink(conn, fake_redis):
    """All guardrails pass → DryRunSink records the exact phone and body."""
    customer_id = await _insert_customer(conn)
    await _grant_consent(conn, customer_id, _TEST_PHONE)

    body = "Your GSTR-3B is due in 7 days."
    sink = DryRunSink()
    with patch("backend.whatsapp.send_service._now_ist", return_value=_ist(10)):
        msg_id = await send(conn, fake_redis, _TEST_PHONE, body, "deadline_reminder", sink)

    assert msg_id == "dry-run-fake-id"
    assert len(sink.sent) == 1
    sent = sink.sent[0]
    assert sent["phone"] == _TEST_PHONE
    assert sent["body"] == body
    # instance comes from the seed wa_instance_config row
    assert sent["instance"] == "primary"
