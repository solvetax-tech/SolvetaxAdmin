import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from backend.security.rbac import require_permission
from backend.utils import get_db_pool, DB_SCHEMA, generate_uuid
from backend.logger import logger
from backend.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/gst-filing-config",
    tags=["GST Filing Config"]
)


@router.get(
    "/gst-filing-config",
    summary="Filter GST Filing Configurations",
    responses={
        200: {"description": "GST filing configs fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def list_gst_filing_configs(

    id: Optional[int] = None,
    filing_type: Optional[str] = None,
    filing_category: Optional[str] = None,
    frequency: Optional[str] = None,
    applicable_turnover: Optional[str] = None,
    applicable_return_type: Optional[str] = None,

    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),

    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming GST filing config filter | limit=%s offset=%s",
        limit,
        offset,
    )
    filing_type_norm = filing_type.strip().upper() if isinstance(filing_type, str) else None
    filing_category_norm = filing_category.strip().upper() if isinstance(filing_category, str) else None
    frequency_norm = frequency.strip().upper() if isinstance(frequency, str) else None
    applicable_turnover_norm = applicable_turnover.strip().upper() if isinstance(applicable_turnover, str) else None
    applicable_return_type_norm = applicable_return_type.strip().upper() if isinstance(applicable_return_type, str) else None
    cache_key = build_cache_key(
        "gst_filing_config:list",
        id=id,
        filing_type=filing_type_norm,
        filing_category=filing_category_norm,
        frequency=frequency_norm,
        applicable_turnover=applicable_turnover_norm,
        applicable_return_type=applicable_return_type_norm,
        is_active=is_active,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
        emp_id=emp_id,
    )

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

    async def _load_gst_filing_configs():
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Filters
        # --------------------------------------------------

        if id is not None:
            conditions.append(f"id = ${param_index}")
            values.append(id)
            param_index += 1

        if filing_type_norm:
            conditions.append(f"upper(filing_type) = ${param_index}")
            values.append(filing_type_norm)
            param_index += 1

        if filing_category_norm:
            conditions.append(f"upper(filing_category) = ${param_index}")
            values.append(filing_category_norm)
            param_index += 1

        if frequency_norm:
            conditions.append(f"upper(frequency) = ${param_index}")
            values.append(frequency_norm)
            param_index += 1

        if applicable_turnover_norm:
            conditions.append(f"applicable_turnover = ${param_index}")
            values.append(applicable_turnover_norm)
            param_index += 1

        if applicable_return_type_norm:
            conditions.append(f"applicable_return_type = ${param_index}")
            values.append(applicable_return_type_norm)
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # WHERE CLAUSE
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.gst_filing_config
            {where_clause}
        """

        data_sql = f"""
            SELECT *
            FROM {DB_SCHEMA}.gst_filing_config
            {where_clause}
            ORDER BY sort_order, id
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(data_sql, *values_with_pagination)

            log.info(
                "GST filing configs fetched successfully | returned=%s total=%s",
                len(rows),
                total,
            )

            return {
                "data": [dict(r) for r in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing config filtering")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing config filtering")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_gst_filing_configs,
        ttl_seconds=300,
        tags=["gst_filing_config:list:index"],
    )