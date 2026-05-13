import logging
import uuid
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import constr, validator
from typing import Optional, List
from datetime import datetime
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import require_permission
from app.logger import logger
from app.utils import mask_sensitive_data,generate_uuid
import json
from zoneinfo import ZoneInfo
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(
    prefix="/api/v1/services-config",
    tags=["Services_config"]
)


def _services_dropdown_cache_key(
    service_category_cleaned: Optional[str],
    role: Optional[str],
    emp_id: Optional[int],
) -> str:
    return build_cache_key(
        "service_config:get_services",
        service_category=service_category_cleaned,
        role=(role or "").strip().upper() or None,
        emp_id=emp_id,
    )

# -------------------------------------------------------------------
# GET SERVICE CONFIG (Dropdown)
# -------------------------------------------------------------------
@router.get(
    "/services",
    summary="Get Services for Dropdown",
    responses={
        200: {"description": "Services fetched successfully."},
        500: {"description": "Database error."},
    },
)
async def get_services(
    service_category: Optional[str] = None,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id if emp_id is not None else "-"},
    )

    # --------------------------------------------------
    # Normalize Input
    # --------------------------------------------------

    service_category_cleaned = (
        service_category.strip().upper()
        if service_category and service_category.strip()
        else None
    )

    log.info(
        "Fetching services dropdown | category=%s",
        service_category_cleaned
    )
    cache_key = _services_dropdown_cache_key(service_category_cleaned, role, emp_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:

        async def _load_services_dropdown():
            conditions = ["is_active = TRUE"]
            values = []
            param_index = 1

            # --------------------------------------------------
            # CATEGORY FILTER
            # --------------------------------------------------

            if service_category_cleaned:
                conditions.append(f"service_category = ${param_index}")
                values.append(service_category_cleaned)
                param_index += 1

            where_clause = f"WHERE {' AND '.join(conditions)}"

            # --------------------------------------------------
            # MAIN QUERY (IMPROVED)
            # --------------------------------------------------

            sql = f"""
                SELECT
                    id,
                    service_category,
                    service_code,
                    service_name,
                    description
                FROM {DB_SCHEMA}.service_config
                {where_clause}
                ORDER BY service_category, service_name
            """

            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *values)

            log.info(
                "Services fetched successfully | count=%s",
                len(rows)
            )

            return {
                "data": [dict(row) for row in rows],
                "count": len(rows),
                "request_id": request_id,
            }

        return await redis_get_or_set_json(
            cache_key,
            loader=_load_services_dropdown,
            ttl_seconds=300,
            tags=["service_config:get_services:index"],
        )

    except asyncpg.PostgresError as e:
        log.error(
            "Database error while fetching services | error=%s",
            str(e),
            exc_info=True,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error while fetching services")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )