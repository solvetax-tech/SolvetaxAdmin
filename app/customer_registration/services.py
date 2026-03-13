import logging
import uuid
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import constr, validator
from typing import Optional, List
from datetime import datetime, timedelta
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import require_permission
from app.logger import logger
from app.utils import mask_sensitive_data,generate_uuid
import json
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")



router = APIRouter(
    prefix="/api/v1/services",
    tags=["services"]
)
<<<<<<< HEAD
=======

>>>>>>> b0f824b (Resolved merge conflict and integrated remote changes)
from fastapi import Query
from datetime import datetime
@router.get(
    "/customer-services/filter",
    summary="Filter Customer Services (Dynamic Filter)",
    responses={
        200: {"description": "Customer services fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def filter_customer_services(

    id: Optional[int] = None,
    customer_id: Optional[int] = None,

    # Service filter by code
    service_code: Optional[str] = None,
    service_codes: Optional[List[str]] = Query(None),

    service_status: Optional[str] = None,
    status: Optional[str] = None,

    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,

    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,

    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    cursor: Optional[datetime] = None,

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_customer_services"},
    )

    log.info(
        "Incoming customer services filter | limit=%s offset=%s cursor=%s",
        limit,
        offset,
        cursor,
    )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

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
        idx = 1

        # --------------------------------------------------
        # STANDARD FILTERS
        # --------------------------------------------------

        if id is not None:
            conditions.append(f"cs.id = ${idx}")
            values.append(id)
            idx += 1

        if customer_id is not None:
            conditions.append(f"cs.customer_id = ${idx}")
            values.append(customer_id)
            idx += 1

        if rm_id is not None:
            conditions.append(f"cs.rm_id = ${idx}")
            values.append(rm_id)
            idx += 1

        if op_id is not None:
            conditions.append(f"cs.op_id = ${idx}")
            values.append(op_id)
            idx += 1

        if service_status:
            conditions.append(f"cs.service_status = ${idx}")
            values.append(service_status)
            idx += 1

        if status:
            conditions.append(f"cs.status = ${idx}")
            values.append(status)
            idx += 1

        # --------------------------------------------------
        # SERVICE CODE FILTER
        # --------------------------------------------------

        if service_code:
            conditions.append(f"s.service_code = ${idx}")
            values.append(service_code.strip())
            idx += 1

        if service_codes:

            cleaned = [
                s.strip()
                for s in service_codes
                if isinstance(s, str) and s.strip()
            ]

            if cleaned:

                conditions.append(f"s.service_code = ANY(${idx})")
                values.append(cleaned)
                idx += 1

        # --------------------------------------------------
        # DATE FILTER
        # --------------------------------------------------

        if from_date:
            conditions.append(f"cs.created_at >= ${idx}")
            values.append(from_date)
            idx += 1

        if to_date:
            conditions.append(f"cs.created_at <= ${idx}")
            values.append(to_date)
            idx += 1

        # --------------------------------------------------
        # CURSOR PAGINATION
        # --------------------------------------------------

        if cursor:
            conditions.append(f"cs.created_at < ${idx}")
            values.append(cursor)
            idx += 1

        # --------------------------------------------------
        # WHERE CLAUSE
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT QUERY
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.service_config s
                 ON s.id = cs.service_id
            {where_clause}
        """

        # --------------------------------------------------
        # PAGINATION
        # --------------------------------------------------

        if cursor:
            pagination_sql = f"LIMIT ${idx}"
            values_with_pagination = values + [limit]
        else:
            pagination_sql = f"LIMIT ${idx} OFFSET ${idx+1}"
            values_with_pagination = values + [limit, offset]

        # --------------------------------------------------
        # MAIN QUERY
        # --------------------------------------------------

        main_sql = f"""
            SELECT
                cs.*,
                c.full_name,
                s.service_code,
                s.service_name,
                rm.first_name AS rm_name,
                op.first_name AS op_name
            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.customers c
                ON c.customer_id = cs.customer_id
            JOIN {DB_SCHEMA}.service_config s
                ON s.id = cs.service_id
            LEFT JOIN {DB_SCHEMA}.employees rm
                ON rm.emp_id = cs.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op
                ON op.emp_id = cs.op_id
            {where_clause}
            ORDER BY cs.created_at DESC
            {pagination_sql}
        """

        async with pool.acquire() as conn:

            total_count = await conn.fetchval(count_sql, *values)

            rows = await conn.fetch(main_sql, *values_with_pagination)

        next_cursor = rows[-1]["created_at"] if rows else None

        log.info(
            "Customer services filter success | total=%s returned=%s",
            total_count,
            len(rows),
        )

        return {
            "data": [dict(row) for row in rows],
            "next_cursor": next_cursor
        }

    except asyncpg.PostgresError:

        log.exception("Database error during customer services filtering")

        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:

        log.exception("Unexpected error during customer services filtering")

        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )


@router.post(
    "/customer-services/{service_id}/activate",
    summary="Activate Customer Service (With Audit)",
)
async def activate_customer_service(
    service_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "activate_customer_service"},
    )

    log.info("Activating customer service | id=%s", service_id)

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

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # Lock existing row
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.customer_services
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    service_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Customer service not found.",
                    )

                # --------------------------------------------------
                # Update Status
                # --------------------------------------------------
                new_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                    SET status = 'ACTIVE'
                    WHERE id = $1
                    RETURNING *
                    """,
                    service_id,
                )

                # --------------------------------------------------
                # Audit
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "CUSTOMER_SERVICE",
                    service_id,
                    old_row["customer_id"],
                    "ACTIVATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info("Customer service activated | id=%s", service_id)

            return {
                **dict(new_row),
                "message": "Customer service activated successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during activation")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during activation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )


@router.post(
    "/customer-services/{service_id}/deactivate",
    summary="Deactivate Customer Service (With Audit)",
)
async def deactivate_customer_service(
    service_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "deactivate_customer_service"},
    )

    log.info("Deactivating customer service | id=%s", service_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.customer_services
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    service_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Customer service not found.",
                    )

                new_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                    SET status = 'INACTIVE'
                    WHERE id = $1
                    RETURNING *
                    """,
                    service_id,
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "CUSTOMER_SERVICE",
                    service_id,
                    old_row["customer_id"],
                    "DEACTIVATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info("Customer service deactivated | id=%s", service_id)

            return {
                **dict(new_row),
                "message": "Customer service deactivated successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during deactivation")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during deactivation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )


@router.get(
    "/services/dashboard/stats",
    summary="Service Dashboard Stats",
)
async def get_service_dashboard_stats(
    filter_type: Optional[str] = Query(
        None,
        description="today | yesterday | last_7_days | last_1_month | last_2_months"
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Service Dashboard Statistics with dynamic filtering.
    """
    request_id = generate_uuid()

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "api": "get_service_dashboard_stats"},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)
    start_dt = None
    end_dt = None

    if filter_type:
        if filter_type == "today":
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = now
        elif filter_type == "yesterday":
            yesterday = now - timedelta(days=1)
            start_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=1)
        elif filter_type == "last_7_days":
            start_dt = now - timedelta(days=7)
            end_dt = now
        elif filter_type == "last_1_month":
            start_dt = now - timedelta(days=30)
            end_dt = now
        elif filter_type == "last_2_months":
            start_dt = now - timedelta(days=60)
            end_dt = now

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            where_clause = ""
            params = []
            if start_dt and end_dt:
                where_clause = "WHERE created_at >= $1 AND created_at <= $2"
                params = [start_dt, end_dt]

            query = f"""
                SELECT
                    COUNT(*) FILTER (WHERE service_status = 'PENDING') AS pending_services,
                    COUNT(*) FILTER (WHERE service_status = 'PROVIDED') AS provided_services,
                    COUNT(*) AS total_services
                FROM {DB_SCHEMA}.customer_services
                {where_clause}
            """
            row = await conn.fetchrow(query, *params)
            return {
                "data": dict(row) if row else {"pending_services": 0, "provided_services": 0, "total_services": 0},
                "request_id": request_id
            }
        except Exception as e:
            log.error(f"Error fetching service dashboard stats: {e}")
            raise HTTPException(status_code=500, detail="Database internal error.")


@router.get(
    "/services/pending",
    summary="Get All Pending Services",
)
async def get_pending_services(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(status_code=500, detail="Database connection error.")

    query = f"""
        SELECT
            cs.id,
            c.customer_id,
            c.full_name,
            s.service_name,
            cs.rm_id,
            cs.op_id,
            cs.created_at
        FROM {DB_SCHEMA}.customer_services cs
        JOIN {DB_SCHEMA}.customers c
            ON c.customer_id = cs.customer_id
        JOIN {DB_SCHEMA}.service_config s
            ON s.id = cs.service_id
        WHERE cs.service_status = 'PENDING'
        ORDER BY cs.created_at DESC
        LIMIT $1 OFFSET $2
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit, offset)

    return {
        "data": [dict(r) for r in rows],
        "request_id": request_id,
    }


