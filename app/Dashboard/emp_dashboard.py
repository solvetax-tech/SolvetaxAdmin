from fastapi import Query
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.security.rbac import require_permission
from app.logger import logger
import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard Metrics"]
)


@router.get(
    "/employee-metrics",
    summary="Get Employee Registration Metrics",
    responses={
        200: {"description": "Employee registration metrics fetched successfully."},
        400: {"description": "Invalid filter_type or invalid date range."},
        500: {"description": "Database or internal error."},
    },
)
async def get_employee_dashboard_metrics(
    filter_type: Optional[str] = Query(
        None,
        description="today | yesterday | last_7_days | last_1_month | last_2_months"
    ),
    start_date: Optional[datetime] = Query(
        None,
        description="Custom start datetime (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        None,
        description="Custom end datetime (ISO format)"
    ),
    current_user=Depends(require_permission("USER_ACCESS", "READ")),
):
    """
    Employee Registration Dashboard API (TIMESTAMPTZ Safe)

    ✔ IST timezone aware
    ✔ Works correctly with PostgreSQL TIMESTAMPTZ
    ✔ Supports predefined filters
    ✔ Supports custom datetime range
    ✔ Returns total count + metadata
    """

    # --------------------------------------------------
    # Request Context & Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "employee_dashboard_metrics",
        },
    )

    log.info("Incoming dashboard metrics request filter_type=%s", filter_type)

    # --------------------------------------------------
    # Timezone Configuration (IST)
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # Determine Date Range
    # --------------------------------------------------
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

        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid filter_type provided."
            )

    elif start_date and end_date:

        if start_date >= end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date must be less than end_date."
            )

        # Ensure timezone-aware (convert to IST if naive)
        if start_date.tzinfo is None:
            start_dt = start_date.replace(tzinfo=IST)
        else:
            start_dt = start_date.astimezone(IST)

        if end_date.tzinfo is None:
            end_dt = end_date.replace(tzinfo=IST)
        else:
            end_dt = end_date.astimezone(IST)

    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either filter_type or start_date & end_date."
        )

    # --------------------------------------------------
    # Database Query
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception("Database pool acquisition failed error=%s", e)
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            sql = f"""
                SELECT COUNT(*) AS total_employees
                FROM {DB_SCHEMA}.employees
                WHERE created_at >= $1
                  AND created_at <= $2
            """

            row = await conn.fetchrow(sql, start_dt, end_dt)

            total = row["total_employees"] if row else 0

            log.info(
                "Dashboard metrics fetched successfully | count=%s | start=%s | end=%s",
                total,
                start_dt,
                end_dt
            )

            return {
                "filter_type": filter_type,
                "start_datetime_ist": start_dt,
                "end_datetime_ist": end_dt,
                "total_employees_registered": total,
                "request_id": request_id
            }

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during dashboard query error=%s",
                e,
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except Exception:
            log.exception("Unexpected error during dashboard metrics")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )


@router.get(
    "/customer-metrics",
    summary="Get Customer Registration Metrics",
    responses={
        200: {"description": "Customer registration metrics fetched successfully."},
        400: {"description": "Invalid filter_type or invalid date range."},
        500: {"description": "Database or internal error."},
    },
)
async def get_customer_dashboard_metrics(
    filter_type: Optional[str] = Query(
        None,
        description="today | yesterday | last_7_days | last_1_month | last_2_months"
    ),
    start_date: Optional[datetime] = Query(
        None,
        description="Custom start datetime (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        None,
        description="Custom end datetime (ISO format)"
    ),
    current_user=Depends(require_permission("USER_ACCESS", "READ")),
):
    """
    Customer Registration Dashboard API (TIMESTAMPTZ Safe + IST)

    ✔ IST timezone aware
    ✔ Works correctly with PostgreSQL TIMESTAMPTZ
    ✔ Supports predefined filters
    ✔ Supports custom datetime range
    ✔ Returns count + filter metadata
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "customer_dashboard_metrics",
        },
    )

    log.info("Incoming customer dashboard metrics request filter_type=%s", filter_type)

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # Determine Date Range
    # --------------------------------------------------
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

        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid filter_type provided."
            )

    elif start_date and end_date:

        if start_date >= end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date must be less than end_date."
            )

        if start_date.tzinfo is None:
            start_dt = start_date.replace(tzinfo=IST)
        else:
            start_dt = start_date.astimezone(IST)

        if end_date.tzinfo is None:
            end_dt = end_date.replace(tzinfo=IST)
        else:
            end_dt = end_date.astimezone(IST)

    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either filter_type or start_date & end_date."
        )

    # --------------------------------------------------
    # DB Query
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception("Database pool acquisition failed error=%s", e)
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            sql = f"""
                SELECT COUNT(*) AS total_customers
                FROM {DB_SCHEMA}.customers
                WHERE created_at >= $1
                  AND created_at <= $2
            """

            row = await conn.fetchrow(sql, start_dt, end_dt)
            total = row["total_customers"] if row else 0

            log.info(
                "Customer dashboard metrics fetched successfully | count=%s",
                total
            )

            return {
                "filter_type": filter_type,
                "start_datetime_ist": start_dt,
                "end_datetime_ist": end_dt,
                "total_customers_registered": total,
                "request_id": request_id
            }

        except asyncpg.PostgresError as e:
            log.error("Database error during dashboard query error=%s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during dashboard metrics")
            raise HTTPException(status_code=500, detail="Internal server error.")

