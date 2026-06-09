import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status, Query
from typing import Optional, List
from datetime import datetime, timezone
from app.security.rbac import require_permission
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json

router = APIRouter(
    prefix="/api/v1/crm/filing-rule-engine",
    tags=["GST Filing Rule Engine"]
)

@router.get(
    "/gst-filing-rule-all",
    summary="Fetch all GST Filing Rule Engine configurations",
    responses={
        200: {"description": "Filing rules fetched successfully."},
        500: {"description": "Database or internal error."},
    },
)
async def list_gst_filing_rule_engines(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Fetches configuration records from gst_filing_rule_engine table.

    Note: due dates and recurrence cadence for return-detail seeding/chaining are
    implemented in gst_return_details_rebuild.py and gst_filing_auto_generation.py
    (hardcoded). This table is reference/config only until wired into those paths.
    """
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )
    cache_key = build_cache_key(
        "gst_filing_rule_engine:list_all",
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async def _load_gst_filing_rule_engines():
        try:
            columns = [
                "id", "filing_type", "display_name", "filing_category",
                "frequency", "return_type", "taxpayer_type", "due_day",
                "due_day_secondary", "due_month_offset", "turnover_limits", "is_active"
            ]

            sql = f"""
                SELECT {", ".join(columns)}
                FROM {DB_SCHEMA}.gst_filing_rule_engine
                ORDER BY id
            """

            async with pool.acquire() as conn:
                rows = await conn.fetch(sql)

            log.info("Filing rules fetched successfully | count=%s", len(rows))
            return {
                "data": [dict(r) for r in rows],
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during filing rules fetch")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )
        except Exception:
            log.exception("Unexpected error during filing rules fetch")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_gst_filing_rule_engines,
        ttl_seconds=300,
        tags=["gst_filing_rule_engine:list_all:index"],
    )
