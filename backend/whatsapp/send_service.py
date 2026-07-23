"""WhatsApp send-service: guardrail enforcement layer.

Every outbound WhatsApp send — from the scheduler, from flow-engine handlers,
or from staff-initiated routes — must pass through `send()`.  No flow
definition can bypass these checks regardless of how it is authored.

Guardrails enforced in order
-----------------------------
1. Consent  — wa_consent row for the phone with revoked_at IS NULL must exist.
2. Quiet hours — current IST hour must be within
   [wa_instance_config.quiet_hours_start, wa_instance_config.quiet_hours_end).
3. Daily rate cap — Redis key wa:daily_sends:{instance}:{YYYY-MM-DD} (IST date)
   is incremented; if the new count exceeds wa_instance_config.daily_send_cap
   the send is rejected.

Redis fail-CLOSED policy
-------------------------
If Redis is unreachable, the rate counter cannot be incremented.  In that
situation we raise RateLimitError instead of allowing the send through.
This is the ONE deliberate exception to the codebase's Redis fail-open
convention (redis_cache.py): an uncounted send is a ban-risk send under the
Baileys warm-up ladder.  Deferring is always safer than sending blind when the
counter state is unknown.

Sources
-------
- doc 09 §3.7 (guardrail enforcement spec)
- doc 09 §5   (Slice 0 exit criteria)
- doc 06 §2.2 (send_service responsibilities)
"""
import logging
from datetime import datetime
from typing import Any

import pytz

from backend.utils import DB_SCHEMA

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")


class ConsentError(Exception):
    """No active wa_consent row exists for the phone number."""


class QuietHoursError(Exception):
    """Current IST time is outside [quiet_hours_start, quiet_hours_end)."""


class RateLimitError(Exception):
    """Daily send cap reached, OR Redis is unreachable (fail-closed)."""


def _now_ist() -> datetime:
    """Return the current IST datetime.

    Extracted as a module-level function so tests can monkeypatch it without
    touching the stdlib datetime class.
    """
    return datetime.now(_IST)


async def send(
    conn: Any,
    redis: Any,
    phone: str,
    body: str,
    category: str,
    sink: Any,
) -> str:
    """Enforce all guardrails, then delegate to sink.send_text and return its message ID.

    phone is 10-digit with no country prefix; category is a log label.
    Raises ConsentError (no active wa_consent row for phone),
    QuietHoursError (outside configured IST window, or no active
    wa_instance_config row), or RateLimitError (daily cap reached, or
    Redis unreachable — fail closed).
    """
    # 1. Consent check ---------------------------------------------------------
    consent_ok = await conn.fetchval(
        f"SELECT 1 FROM {DB_SCHEMA}.wa_consent"
        f" WHERE phone = $1 AND revoked_at IS NULL LIMIT 1",
        phone,
    )
    if not consent_ok:
        raise ConsentError(
            f"No active WhatsApp consent for phone {phone!r}"
        )

    # 2. Load active instance config -------------------------------------------
    config = await conn.fetchrow(
        f"SELECT instance_name, daily_send_cap, quiet_hours_start, quiet_hours_end"
        f" FROM {DB_SCHEMA}.wa_instance_config WHERE is_active = true LIMIT 1"
    )
    if config is None:
        raise QuietHoursError(
            "No active wa_instance_config row found; cannot enforce quiet hours"
        )

    # 3. Quiet hours check -----------------------------------------------------
    now_ist = _now_ist()
    current_hour = now_ist.hour
    start_h: int = config["quiet_hours_start"]
    end_h: int = config["quiet_hours_end"]

    if not (start_h <= current_hour < end_h):
        raise QuietHoursError(
            f"Outside quiet-hours window {start_h:02d}:00–{end_h:02d}:00 IST; "
            f"current IST hour is {current_hour:02d}"
        )

    # 4. Daily rate cap (fail CLOSED on Redis failure) -------------------------
    instance_name: str = config["instance_name"]
    date_str = now_ist.strftime("%Y-%m-%d")
    rate_key = f"wa:daily_sends:{instance_name}:{date_str}"

    try:
        count = await redis.incr(rate_key)
        if count == 1:
            # First send of the day — attach a TTL so the key self-expires.
            # The 86400s TTL is approximate; using IST-midnight expiry would
            # require a Lua script.  The slight over-count at day boundaries
            # is safe: it only delays sends by one tick, never allows extras.
            await redis.expire(rate_key, 86400)
    except Exception:
        # Fail CLOSED: Redis is unreachable so we cannot count this send.
        # An uncounted send risks exceeding the Baileys warm-up daily limit,
        # which may trigger a WhatsApp number ban.  Deferring is safer than
        # sending blind.  This is the documented exception to the codebase's
        # Redis fail-open convention (redis_cache.py).
        logger.warning(
            "wa_send_blocked reason=redis_unavailable key=%s phone=%s",
            rate_key,
            phone,
        )
        raise RateLimitError(
            f"Redis unavailable — send blocked for phone {phone!r} "
            "to prevent an uncounted ban-risk send"
        )

    cap: int = config["daily_send_cap"]
    if count > cap:
        raise RateLimitError(
            f"Daily send cap ({cap}) reached for instance {instance_name!r} on {date_str}"
        )

    # 5. All guardrails passed — delegate to sink ------------------------------
    logger.info(
        "wa_send_ok phone=%s category=%s instance=%s daily_count=%s cap=%s",
        phone,
        category,
        instance_name,
        count,
        cap,
    )
    return await sink.send_text(phone, body, instance_name)
