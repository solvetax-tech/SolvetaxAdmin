import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import RegistrationPaymentIn, RegistrationPaymentEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/payments_config",
    tags=["Payments Config"]
)
# -------------------------------------------------------------------
# LIST PAYMENT CONFIG (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

@router.get(
    "/payment-config",
    summary="Filter Payment Configurations",
    responses={
        200: {"description": "Payment configs fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def list_payment_configs(
    id: Optional[int] = None,
    entity_type: Optional[str] = None,
    config_type: Optional[str] = None,
    value: Optional[str] = None,
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
        "Incoming payment config filter | limit=%s offset=%s",
        limit,
        offset,
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

    try:

        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Exact Filters
        # --------------------------------------------------

        if id is not None:
            conditions.append(f"id = ${param_index}")
            values.append(id)
            param_index += 1

        if entity_type and entity_type.strip():
            conditions.append(f"upper(entity_type) = ${param_index}")
            values.append(entity_type.strip().upper())
            param_index += 1

        if config_type and config_type.strip():
            conditions.append(f"upper(config_type) = ${param_index}")
            values.append(config_type.strip().upper())
            param_index += 1

        if value and value.strip():
            conditions.append(f"upper(value) = ${param_index}")
            values.append(value.strip().upper())
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
            FROM {DB_SCHEMA}.payment_config
            {where_clause}
        """

        data_sql = f"""
            SELECT *
            FROM {DB_SCHEMA}.payment_config
            {where_clause}
            ORDER BY entity_type, sort_order, id
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:

            total = await conn.fetchval(count_sql, *values)

            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "Payment configs fetched successfully | returned=%s total=%s",
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
        log.exception("Database error during payment config filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during payment config filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )