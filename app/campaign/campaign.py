"""
Public marketing capture: one append-only row per successful submit in d_customer_session
(keyed by mobile + entity_type; correlate with customers / income_tax / crm_leads by mobile).

Optional session capture uses POST /api/v1/event-logs (CampaignSubmitIn), not customer create.

DDL: see sql/d_customer_session.sql (replace schema name with DB_SCHEMA / search_path).
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request

from app.campaign.schemas import CampaignSubmitIn
from app.security.public_security import enforce_public_security
from app.utils import DB_SCHEMA, get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["campaign-analytics"])

# Fields read from CustomerIn / IncomeTaxIn / CampaignSubmitIn for session insert.
_CAMPAIGN_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "capture_page_path",
    "capture_page_url",
    "capture_page_query",
    "capture_referrer_url",
    "platform",
    "device_type",
    "device_model",
    "os_name",
    "os_version",
    "browser_name",
    "browser_version",
    "app_version",
    "environment",
    "release_tag",
    "user_agent",
    "viewport_width",
    "viewport_height",
    "screen_width",
    "screen_height",
    "capture_language",
    "timezone_offset_min",
    "lead_source",
    "ingestion_source",
)


def campaign_capture_from_model(model: Any) -> dict[str, Any]:
    """Read optional marketing/session fields from CustomerIn / IncomeTaxIn / CampaignSubmitIn."""
    out: dict[str, Any] = {}
    for k in _CAMPAIGN_FIELDS:
        if hasattr(model, k):
            out[k] = getattr(model, k, None)
    return out


async def insert_d_customer_session_capture(
    conn: asyncpg.Connection,
    *,
    schema: str,
    mobile: str,
    entity_type: str,
    capture: Mapping[str, Any],
) -> Optional[int]:
    """
    Append-only: one row per successful public submit.
    Links to CRM/customers/income_tax operationally by mobile (+ entity_type).
    """
    mob = (mobile or "").strip()
    if len(mob) != 10 or not mob.isdigit():
        return None
    et = (entity_type or "").strip().upper()[:40] or "UNKNOWN"

    def g(key: str) -> Any:
        return capture.get(key)

    q = f"""
    INSERT INTO {schema}.d_customer_session (
      mobile, entity_type,
      utm_source, utm_medium, utm_campaign, utm_content,
      capture_page_path, capture_page_url, capture_page_query, capture_referrer_url,
      platform, device_type, device_model,
      os_name, os_version, browser_name, browser_version,
      app_version, environment, release_tag, user_agent,
      viewport_width, viewport_height, screen_width, screen_height,
      language, timezone_offset_min,
      lead_source, ingestion_source,
      created_at
    ) VALUES (
      $1, $2,
      $3, $4, $5, $6,
      $7, $8, $9, $10,
      $11, $12, $13,
      $14, $15, $16, $17,
      $18, $19, $20, $21,
      $22, $23, $24, $25,
      $26, $27,
      $28, COALESCE(NULLIF(btrim($29::text), ''), 'web_submit'),
      NOW()
    )
    RETURNING id
    """

    def clip_str(val: Any, n: int) -> Optional[str]:
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        return s[:n] if len(s) > n else s

    try:
        row = await conn.fetchrow(
            q,
            mob,
            et,
            clip_str(g("utm_source"), 120),
            clip_str(g("utm_medium"), 120),
            clip_str(g("utm_campaign"), 200),
            clip_str(g("utm_content"), 200),
            clip_str(g("capture_page_path"), 1024),
            g("capture_page_url"),
            g("capture_page_query"),
            g("capture_referrer_url"),
            clip_str(g("platform"), 20),
            clip_str(g("device_type"), 20),
            clip_str(g("device_model"), 200),
            clip_str(g("os_name"), 64),
            clip_str(g("os_version"), 32),
            clip_str(g("browser_name"), 64),
            clip_str(g("browser_version"), 32),
            clip_str(g("app_version"), 64),
            clip_str(g("environment"), 32),
            clip_str(g("release_tag"), 64),
            g("user_agent"),
            g("viewport_width"),
            g("viewport_height"),
            g("screen_width"),
            g("screen_height"),
            clip_str(g("language") or g("capture_language"), 32),
            g("timezone_offset_min"),
            clip_str(g("lead_source"), 120),
            clip_str(g("ingestion_source"), 40),
        )
        return int(row["id"]) if row else None
    except asyncpg.UndefinedTableError:
        logger.warning("d_customer_session missing; skip session capture.")
        return None
    except asyncpg.UndefinedColumnError:
        logger.warning("d_customer_session schema mismatch; skip session capture.")
        return None
    except asyncpg.PostgresError:
        logger.exception("insert_d_customer_session_capture failed")
        return None


async def insert_campaign_capture_for_public_create(
    conn: asyncpg.Connection,
    *,
    mobile: str,
    entity_type: str,
    payload_model: Any,
) -> None:
    """Called inside same DB transaction as customer / income_tax create."""
    cap = campaign_capture_from_model(payload_model)
    await insert_d_customer_session_capture(
        conn,
        schema=DB_SCHEMA,
        mobile=mobile,
        entity_type=entity_type,
        capture=cap,
    )


@router.post("/api/v1/event-logs")
async def ingest_campaign_submit(request: Request, body: CampaignSubmitIn):
    """Standalone capture (same shape as optional fields on public create APIs)."""
    await enforce_public_security(
        request=request,
        bucket="public:event_logs",
        max_requests=40,
        window_seconds=60,
        block_seconds=300,
    )
    et = (body.entity_type or "UNKNOWN").strip().upper()[:40]
    pool = await get_db_pool()
    new_id: Optional[int] = None
    try:
        async with pool.acquire() as conn:
            new_id = await insert_d_customer_session_capture(
                conn,
                schema=DB_SCHEMA,
                mobile=body.mobile,
                entity_type=et,
                capture=campaign_capture_from_model(body),
            )
    except asyncpg.PostgresError as e:
        logger.exception("Campaign submit failed")
        raise HTTPException(status_code=500, detail="Database error") from e

    if new_id is None:
        raise HTTPException(status_code=503, detail="Campaign table unavailable or invalid payload")
    return {"ok": True, "campaign_capture_id": new_id, "customer_session_id": new_id}


@router.post("/api/v1/event-logs/debug/smoke")
async def campaign_event_logs_smoke(request: Request):
    await enforce_public_security(
        request=request,
        bucket="public:event_logs_smoke",
        max_requests=60,
        window_seconds=60,
        block_seconds=300,
    )
    return {"ok": True, "router": "campaign-submit"}
