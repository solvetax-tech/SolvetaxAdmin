import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.utils import (
    build_customer_visibility,
    get_db_pool,
    DB_SCHEMA,
    generate_uuid,
)
from app.logger import logger
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/version",
    tags=["Version History"]
)


def _version_filter_tag() -> str:
    return "version:filter:index"
# -------------------------------------------------------------------
# LIST VERSIONS (ENTERPRISE DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

@router.get(
    "/dynamic_filter",
    summary="Filter Version History (Enterprise Standard)",
    responses={
        200: {"description": "Versions filtered successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def list_versions(
    id: Optional[int] = None,
    emp_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    action: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    role_norm = str(current_user.get("role") or "").strip().upper()
    emp_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id_for_vis = int(emp_raw) if str(emp_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming version filter request | limit=%s offset=%s", limit, offset)
    cache_key = build_cache_key(
        "version:list",
        id=id,
        emp_id=emp_id,
        entity_type=entity_type.strip().upper() if entity_type else None,
        entity_id=entity_id,
        customer_id=customer_id,
        action=action.strip().upper() if action else None,
        from_date=from_date.isoformat() if from_date else None,
        to_date=to_date.isoformat() if to_date else None,
        limit=limit,
        offset=offset,
        role=role_norm,
        current_emp_id=current_emp_id,
    )

    # --------------------------------------------------
    # Date Validation
    # --------------------------------------------------
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    # --------------------------------------------------
    # Action Validation (DB CHECK aligned)
    # --------------------------------------------------
    ALLOWED_ACTIONS = {"CREATE", "UPDATE", "DELETE", "ACTIVATE"}

    if action:
        action = action.strip().upper()
        if action not in ALLOWED_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action. Allowed: {', '.join(ALLOWED_ACTIONS)}",
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

    async def _load_versions():
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Indexed Exact Match Filters (Optimized)
        # --------------------------------------------------

        if id is not None:
            conditions.append(f"v.id = ${param_index}")
            values.append(id)
            param_index += 1

        if emp_id is not None:
            conditions.append(f"v.emp_id = ${param_index}")
            values.append(emp_id)
            param_index += 1

        if entity_type:
            conditions.append(f"v.entity_type = ${param_index}")
            values.append(entity_type.strip().upper())
            param_index += 1

        if entity_id is not None:
            conditions.append(f"v.entity_id = ${param_index}")
            values.append(entity_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"v.customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if action:
            conditions.append(f"v.action = ${param_index}")
            values.append(action)
            param_index += 1

        # --------------------------------------------------
        # Date Filtering (Indexed Column)
        # --------------------------------------------------

        if from_date:
            conditions.append(f"v.created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"v.created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        if role_norm != "ADMIN":
            visibility_sql, visibility_values, param_index = build_customer_visibility(
                role_norm,
                emp_id_for_vis,
                param_index,
                DB_SCHEMA,
            )
            if visibility_sql:
                conditions.append(f"v.customer_id IS NOT NULL AND ({visibility_sql})")
                values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE Clause Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT Query (Pagination Metadata)
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.versions v
              LEFT JOIN {DB_SCHEMA}.customers c ON v.customer_id = c.customer_id
              {where_clause}
        """

        # --------------------------------------------------
        # Main Query (Deterministic Order)
        # --------------------------------------------------

        main_sql = f"""
            SELECT v.*, 
                   e.username as emp_name,
                   c.business_name as customer_name
              FROM {DB_SCHEMA}.versions v
              LEFT JOIN {DB_SCHEMA}.employees e ON v.emp_id = e.emp_id
              LEFT JOIN {DB_SCHEMA}.customers c ON v.customer_id = c.customer_id
              {where_clause}
             ORDER BY v.created_at DESC, v.id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        try:
            async with pool.acquire() as conn:
                total_count = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(main_sql, *values_with_pagination)

            log.info(
                "Version filter success | total=%s returned=%s",
                total_count,
                len(rows),
            )

            return {
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "data": [
                    {
                        **dict(row),
                        "request_id": request_id,
                    }
                    for row in rows
                ],
            }
        except asyncpg.PostgresError as e:
            log.error(
                "Database error during version filtering | error=%s",
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error occurred during filtering.",
            )
        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error during version filtering")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_versions,
        ttl_seconds=300,
        tags=[_version_filter_tag()],
    )