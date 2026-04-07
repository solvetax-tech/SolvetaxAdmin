from fastapi import Query
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_filing_visibility
from app.security.rbac import require_permission
from app.logger import logger
import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard Metrics"]
)


def _to_ist_or_none(dt: Optional[datetime], ist: ZoneInfo) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=ist) if dt.tzinfo is None else dt.astimezone(ist)


def _build_gst_missed_filters(
    *,
    role: str,
    emp_id: Optional[int],
    gst_filing_id: Optional[int],
    customer_id: Optional[int],
    gst_registration_id: Optional[int],
    cx_number: Optional[str],
    rm_id: Optional[int],
    op_id: Optional[int],
    filing_category: Optional[str],
    filing_status: Optional[str],
    filing_frequency: Optional[str],
    is_auto_enabled: Optional[bool],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
    data_received_from: Optional[datetime],
    data_received_to: Optional[datetime],
    filed_from: Optional[datetime],
    filed_to: Optional[datetime],
    include_inactive: bool,
):
    conditions = []
    values = []
    idx = 1

    if not include_inactive:
        conditions.append("f.is_active = TRUE")
    if gst_filing_id is not None:
        conditions.append(f"f.id = ${idx}")
        values.append(gst_filing_id)
        idx += 1
    if customer_id is not None:
        conditions.append(f"f.customer_id = ${idx}")
        values.append(customer_id)
        idx += 1
    if gst_registration_id is not None:
        conditions.append(f"f.gst_registration_id = ${idx}")
        values.append(gst_registration_id)
        idx += 1
    if cx_number:
        conditions.append(f"c.mobile = ${idx}")
        values.append(cx_number)
        idx += 1
    if rm_id is not None:
        conditions.append(f"f.rm_id = ${idx}")
        values.append(rm_id)
        idx += 1
    if op_id is not None:
        conditions.append(f"f.op_id = ${idx}")
        values.append(op_id)
        idx += 1
    if filing_category:
        conditions.append(f"f.filing_category = ${idx}")
        values.append(filing_category)
        idx += 1
    if filing_status:
        conditions.append(f"f.status = ${idx}")
        values.append(filing_status)
        idx += 1
    if filing_frequency:
        conditions.append(f"f.filing_frequency = ${idx}")
        values.append(filing_frequency)
        idx += 1
    if is_auto_enabled is not None:
        conditions.append(f"f.is_auto_enabled = ${idx}")
        values.append(is_auto_enabled)
        idx += 1
    if created_from is not None:
        conditions.append(f"f.created_at >= ${idx}")
        values.append(created_from)
        idx += 1
    if created_to is not None:
        conditions.append(f"f.created_at <= ${idx}")
        values.append(created_to)
        idx += 1
    if data_received_from is not None:
        conditions.append(f"f.data_received_at >= ${idx}")
        values.append(data_received_from)
        idx += 1
    if data_received_to is not None:
        conditions.append(f"f.data_received_at <= ${idx}")
        values.append(data_received_to)
        idx += 1
    if filed_from is not None:
        conditions.append(f"f.filed_at >= ${idx}")
        values.append(filed_from)
        idx += 1
    if filed_to is not None:
        conditions.append(f"f.filed_at <= ${idx}")
        values.append(filed_to)
        idx += 1

    visibility_sql, visibility_values, idx = build_gst_filing_visibility(
        role, emp_id, idx, DB_SCHEMA
    )
    if visibility_sql:
        conditions.append(visibility_sql)
        values.extend(visibility_values)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, values, idx


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

@router.get(
    "/payment-metrics",
    summary="Get Payment Collection Metrics",
)
async def get_payment_dashboard_metrics(
    filter_type: Optional[str] = Query(
        None,
        description="today | yesterday | last_7_days | last_1_month | last_2_months"
    ),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user=Depends(require_permission("USER_ACCESS", "READ")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": current_emp_id, "api": "payment_dashboard_metrics"})

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    if filter_type:
        if filter_type == "today":
            start_dt, end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0), now
        elif filter_type == "yesterday":
            start_dt = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=1)
        elif filter_type == "last_7_days":
            start_dt, end_dt = now - timedelta(days=7), now
        elif filter_type == "last_1_month":
            start_dt, end_dt = now - timedelta(days=30), now
        elif filter_type == "last_2_months":
            start_dt, end_dt = now - timedelta(days=60), now
        else:
            raise HTTPException(status_code=400, detail="Invalid filter_type")
    elif start_date and end_date:
        start_dt = start_date.replace(tzinfo=IST) if start_date.tzinfo is None else start_date.astimezone(IST)
        end_dt = end_date.replace(tzinfo=IST) if end_date.tzinfo is None else end_date.astimezone(IST)
    else:
        raise HTTPException(status_code=400, detail="Missing filter")

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Aggregate collected amount and total pending
            sql = f"""
                SELECT 
                    SUM(COALESCE(paid_amount, 0)) AS total_received,
                    SUM(CASE 
                        WHEN payment_status != 'CANCELLED' THEN COALESCE(net_amount, 0) - COALESCE(paid_amount, 0) 
                        ELSE 0 
                    END) AS total_pending
                FROM {DB_SCHEMA}.payments
                WHERE created_at >= $1 AND created_at <= $2
                  AND is_active = TRUE
            """
            row = await conn.fetchrow(sql, start_dt, end_dt)
            return {
                "total_received": float(row["total_received"] or 0),
                "total_pending": float(row["total_pending"] or 0),
                "request_id": request_id
            }
    except Exception as e:
        log.exception("Payment dashboard error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/gst-missed-filings/gt-one",
    summary="GST filings with MISSED return rows greater than one",
)
async def get_gst_missed_filings_gt_one(
    gst_filing_id: Optional[int] = Query(None, gt=0),
    customer_id: Optional[int] = Query(None, gt=0),
    gst_registration_id: Optional[int] = Query(None, gt=0),
    cx_number: Optional[str] = Query(None, min_length=6, max_length=15),
    rm_id: Optional[int] = Query(None, gt=0),
    op_id: Optional[int] = Query(None, gt=0),
    filing_category: Optional[str] = Query(None, description="RETURN | ANNUAL"),
    filing_status: Optional[str] = Query(None, description="DATA_PENDING | DATA_RECEIVED | IN_PREPARATION | PENDING_OTP | READY_TO_FILE | FILED | OVERDUE"),
    filing_frequency: Optional[str] = Query(
        None, description="Optional: MONTHLY | QUARTERLY | YEARLY"
    ),
    is_auto_enabled: Optional[bool] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    data_received_from: Optional[datetime] = Query(None),
    data_received_to: Optional[datetime] = Query(None),
    filed_from: Optional[datetime] = Query(None),
    filed_to: Optional[datetime] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = str(current_user.get("role") or "").strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_gst_missed_filings_gt_one"},
    )

    freq = filing_frequency.strip().upper() if isinstance(filing_frequency, str) else None
    filing_category_norm = filing_category.strip().upper() if isinstance(filing_category, str) else None
    filing_status_norm = filing_status.strip().upper() if isinstance(filing_status, str) else None
    cx_number_norm = cx_number.strip() if isinstance(cx_number, str) else None
    ist = ZoneInfo("Asia/Kolkata")
    created_from_ist = _to_ist_or_none(created_from, ist)
    created_to_ist = _to_ist_or_none(created_to, ist)
    data_received_from_ist = _to_ist_or_none(data_received_from, ist)
    data_received_to_ist = _to_ist_or_none(data_received_to, ist)
    filed_from_ist = _to_ist_or_none(filed_from, ist)
    filed_to_ist = _to_ist_or_none(filed_to, ist)
    ist = ZoneInfo("Asia/Kolkata")
    created_from_ist = _to_ist_or_none(created_from, ist)
    created_to_ist = _to_ist_or_none(created_to, ist)
    data_received_from_ist = _to_ist_or_none(data_received_from, ist)
    data_received_to_ist = _to_ist_or_none(data_received_to, ist)
    filed_from_ist = _to_ist_or_none(filed_from, ist)
    filed_to_ist = _to_ist_or_none(filed_to, ist)
    ist = ZoneInfo("Asia/Kolkata")
    created_from_ist = _to_ist_or_none(created_from, ist)
    created_to_ist = _to_ist_or_none(created_to, ist)
    data_received_from_ist = _to_ist_or_none(data_received_from, ist)
    data_received_to_ist = _to_ist_or_none(data_received_to, ist)
    filed_from_ist = _to_ist_or_none(filed_from, ist)
    filed_to_ist = _to_ist_or_none(filed_to, ist)

    if freq and freq not in {"MONTHLY", "QUARTERLY", "YEARLY"}:
        raise HTTPException(status_code=400, detail="Invalid filing_frequency.")
    if filing_category_norm and filing_category_norm not in {"RETURN", "ANNUAL"}:
        raise HTTPException(status_code=400, detail="Invalid filing_category.")
    if filing_status_norm and filing_status_norm not in {
        "DATA_PENDING", "DATA_RECEIVED", "IN_PREPARATION", "PENDING_OTP", "READY_TO_FILE", "FILED", "OVERDUE"
    }:
        raise HTTPException(status_code=400, detail="Invalid filing_status.")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    missed_predicate = """
        (
            d.gstr1_status = 'MISSED'
            OR d.gstr3b_status = 'MISSED'
            OR d.gstr9_status = 'MISSED'
            OR d.gstr9c_status = 'MISSED'
            OR d.cmp08_status = 'MISSED'
            OR d.gstr4_status = 'MISSED'
        )
    """

    where_clause, values, idx = _build_gst_missed_filters(
        role=role,
        emp_id=emp_id,
        gst_filing_id=gst_filing_id,
        customer_id=customer_id,
        gst_registration_id=gst_registration_id,
        cx_number=cx_number_norm,
        rm_id=rm_id,
        op_id=op_id,
        filing_category=filing_category_norm,
        filing_status=filing_status_norm,
        filing_frequency=freq,
        is_auto_enabled=is_auto_enabled,
        created_from=created_from_ist,
        created_to=created_to_ist,
        data_received_from=data_received_from_ist,
        data_received_to=data_received_to_ist,
        filed_from=filed_from_ist,
        filed_to=filed_to_ist,
        include_inactive=include_inactive,
    )

    base_cte = f"""
        WITH per_filing AS (
            SELECT
                f.id AS gst_filing_id,
                f.customer_id,
                c.mobile AS cx_number,
                f.gst_registration_id,
                f.rm_id,
                f.op_id,
                f.filing_frequency,
                COUNT(d.id) AS missed_records_count
            FROM {DB_SCHEMA}.gst_filings f
            JOIN {DB_SCHEMA}.gst_filing_return_details d
              ON d.gst_filing_id = f.id
             AND d.is_active = TRUE
             AND {missed_predicate}
            LEFT JOIN {DB_SCHEMA}.customers c
              ON c.customer_id = f.customer_id
            {where_clause}
            GROUP BY
                f.id, f.customer_id, c.mobile,
                f.gst_registration_id, f.rm_id, f.op_id, f.filing_frequency
            HAVING COUNT(d.id) > 1
        )
    """

    count_sql = base_cte + " SELECT COUNT(*) AS total_count FROM per_filing "
    data_sql = (
        base_cte
        + f"""
        SELECT *
        FROM per_filing
        ORDER BY missed_records_count DESC, gst_filing_id DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """
    )

    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *(values + [limit, offset]))
    except asyncpg.PostgresError:
        log.exception("Database error for gt-one MISSED dashboard query")
        raise HTTPException(status_code=500, detail="Database error.")
    except Exception:
        log.exception("Unexpected error for gt-one MISSED dashboard query")
        raise HTTPException(status_code=500, detail="Internal server error.")

    return {
        "data": [dict(r) for r in rows],
        "count": len(rows),
        "total_count": int(total or 0),
        "limit": limit,
        "offset": offset,
        "request_id": request_id,
    }


@router.get(
    "/gst-missed-filings/buckets",
    summary="GST missed filings buckets in one API (exact_one / gt_one / gt_limit)",
)
async def get_gst_missed_filings_buckets(
    threshold: int = Query(3, ge=2, description="Threshold for gt_limit bucket."),
    bucket: str = Query("gt_limit", description="exact_one | gt_one | gt_limit"),
    gst_filing_id: Optional[int] = Query(None, gt=0),
    customer_id: Optional[int] = Query(None, gt=0),
    gst_registration_id: Optional[int] = Query(None, gt=0),
    cx_number: Optional[str] = Query(None, min_length=6, max_length=15),
    rm_id: Optional[int] = Query(None, gt=0),
    op_id: Optional[int] = Query(None, gt=0),
    filing_category: Optional[str] = Query(None, description="RETURN | ANNUAL"),
    filing_status: Optional[str] = Query(None, description="DATA_PENDING | DATA_RECEIVED | IN_PREPARATION | PENDING_OTP | READY_TO_FILE | FILED | OVERDUE"),
    filing_frequency: Optional[str] = Query(None, description="MONTHLY | QUARTERLY | YEARLY"),
    is_auto_enabled: Optional[bool] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    data_received_from: Optional[datetime] = Query(None),
    data_received_to: Optional[datetime] = Query(None),
    filed_from: Optional[datetime] = Query(None),
    filed_to: Optional[datetime] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = str(current_user.get("role") or "").strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_gst_missed_filings_buckets"},
    )

    bucket_norm = bucket.strip().lower()
    if bucket_norm not in {"exact_one", "gt_one", "gt_limit"}:
        raise HTTPException(status_code=400, detail="Invalid bucket.")

    freq = filing_frequency.strip().upper() if isinstance(filing_frequency, str) else None
    filing_category_norm = filing_category.strip().upper() if isinstance(filing_category, str) else None
    filing_status_norm = filing_status.strip().upper() if isinstance(filing_status, str) else None
    cx_number_norm = cx_number.strip() if isinstance(cx_number, str) else None

    if freq and freq not in {"MONTHLY", "QUARTERLY", "YEARLY"}:
        raise HTTPException(status_code=400, detail="Invalid filing_frequency.")
    if filing_category_norm and filing_category_norm not in {"RETURN", "ANNUAL"}:
        raise HTTPException(status_code=400, detail="Invalid filing_category.")
    if filing_status_norm and filing_status_norm not in {
        "DATA_PENDING", "DATA_RECEIVED", "IN_PREPARATION", "PENDING_OTP", "READY_TO_FILE", "FILED", "OVERDUE"
    }:
        raise HTTPException(status_code=400, detail="Invalid filing_status.")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    missed_predicate = """
        (
            d.gstr1_status = 'MISSED'
            OR d.gstr3b_status = 'MISSED'
            OR d.gstr9_status = 'MISSED'
            OR d.gstr9c_status = 'MISSED'
            OR d.cmp08_status = 'MISSED'
            OR d.gstr4_status = 'MISSED'
        )
    """

    where_clause, values, idx = _build_gst_missed_filters(
        role=role,
        emp_id=emp_id,
        gst_filing_id=gst_filing_id,
        customer_id=customer_id,
        gst_registration_id=gst_registration_id,
        cx_number=cx_number_norm,
        rm_id=rm_id,
        op_id=op_id,
        filing_category=filing_category_norm,
        filing_status=filing_status_norm,
        filing_frequency=freq,
        is_auto_enabled=is_auto_enabled,
        created_from=created_from_ist,
        created_to=created_to_ist,
        data_received_from=data_received_from_ist,
        data_received_to=data_received_to_ist,
        filed_from=filed_from_ist,
        filed_to=filed_to_ist,
        include_inactive=include_inactive,
    )

    base_cte = f"""
        WITH per_filing AS (
            SELECT
                f.id AS gst_filing_id,
                f.customer_id,
                c.mobile AS cx_number,
                f.gst_registration_id,
                f.rm_id,
                f.op_id,
                f.filing_frequency,
                COUNT(d.id) AS missed_records_count
            FROM {DB_SCHEMA}.gst_filings f
            JOIN {DB_SCHEMA}.gst_filing_return_details d
              ON d.gst_filing_id = f.id
             AND d.is_active = TRUE
             AND {missed_predicate}
            LEFT JOIN {DB_SCHEMA}.customers c
              ON c.customer_id = f.customer_id
            {where_clause}
            GROUP BY
                f.id, f.customer_id, c.mobile,
                f.gst_registration_id, f.rm_id, f.op_id, f.filing_frequency
        )
    """

    summary_sql = (
        base_cte
        + f"""
        SELECT
            COUNT(*) FILTER (WHERE missed_records_count = 1) AS exact_one_count,
            COUNT(*) FILTER (WHERE missed_records_count > 1) AS gt_one_count,
            COUNT(*) FILTER (WHERE missed_records_count >= ${idx}) AS gt_limit_count
        FROM per_filing
        """
    )
    idx += 1

    if bucket_norm == "exact_one":
        bucket_condition = "missed_records_count = 1"
        order_clause = "gst_filing_id DESC"
    elif bucket_norm == "gt_one":
        bucket_condition = "missed_records_count > 1"
        order_clause = "missed_records_count DESC, gst_filing_id DESC"
    else:
        bucket_condition = f"missed_records_count >= ${idx}"
        order_clause = "missed_records_count DESC, gst_filing_id DESC"
        idx += 1

    data_sql = (
        base_cte
        + f"""
        SELECT *
        FROM per_filing
        WHERE {bucket_condition}
        ORDER BY {order_clause}
        LIMIT ${idx} OFFSET ${idx+1}
        """
    )

    data_values = list(values) + [threshold]
    if bucket_norm == "gt_limit":
        data_values.append(threshold)
    data_values += [limit, offset]

    try:
        async with pool.acquire() as conn:
            summary_row = await conn.fetchrow(summary_sql, *(values + [threshold]))
            rows = await conn.fetch(data_sql, *data_values)
    except asyncpg.PostgresError:
        log.exception("Database error for MISSED bucket dashboard query")
        raise HTTPException(status_code=500, detail="Database error.")
    except Exception:
        log.exception("Unexpected error for MISSED bucket dashboard query")
        raise HTTPException(status_code=500, detail="Internal server error.")

    exact_one_count = int(summary_row["exact_one_count"] or 0)
    gt_one_count = int(summary_row["gt_one_count"] or 0)
    gt_limit_count = int(summary_row["gt_limit_count"] or 0)
    selected_total = (
        exact_one_count if bucket_norm == "exact_one"
        else gt_one_count if bucket_norm == "gt_one"
        else gt_limit_count
    )

    return {
        "data": [dict(r) for r in rows],
        "bucket": bucket_norm,
        "threshold": threshold,
        "count": len(rows),
        "total_count": selected_total,
        "summary": {
            "exact_one_count": exact_one_count,
            "gt_one_count": gt_one_count,
            "gt_limit_count": gt_limit_count,
        },
        "limit": limit,
        "offset": offset,
        "request_id": request_id,
    }


@router.get(
    "/gst-missed-filings/exact-one",
    summary="GST filings with exactly one MISSED return row",
)
async def get_gst_missed_filings_exact_one(
    gst_filing_id: Optional[int] = Query(None, gt=0),
    customer_id: Optional[int] = Query(None, gt=0),
    gst_registration_id: Optional[int] = Query(None, gt=0),
    cx_number: Optional[str] = Query(None, min_length=6, max_length=15),
    rm_id: Optional[int] = Query(None, gt=0),
    op_id: Optional[int] = Query(None, gt=0),
    filing_category: Optional[str] = Query(None, description="RETURN | ANNUAL"),
    filing_status: Optional[str] = Query(None, description="DATA_PENDING | DATA_RECEIVED | IN_PREPARATION | PENDING_OTP | READY_TO_FILE | FILED | OVERDUE"),
    filing_frequency: Optional[str] = Query(
        None, description="Optional: MONTHLY | QUARTERLY | YEARLY"
    ),
    is_auto_enabled: Optional[bool] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    data_received_from: Optional[datetime] = Query(None),
    data_received_to: Optional[datetime] = Query(None),
    filed_from: Optional[datetime] = Query(None),
    filed_to: Optional[datetime] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = str(current_user.get("role") or "").strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_gst_missed_filings_exact_one"},
    )

    freq = filing_frequency.strip().upper() if isinstance(filing_frequency, str) else None
    filing_category_norm = filing_category.strip().upper() if isinstance(filing_category, str) else None
    filing_status_norm = filing_status.strip().upper() if isinstance(filing_status, str) else None
    cx_number_norm = cx_number.strip() if isinstance(cx_number, str) else None

    if freq and freq not in {"MONTHLY", "QUARTERLY", "YEARLY"}:
        raise HTTPException(status_code=400, detail="Invalid filing_frequency.")
    if filing_category_norm and filing_category_norm not in {"RETURN", "ANNUAL"}:
        raise HTTPException(status_code=400, detail="Invalid filing_category.")
    if filing_status_norm and filing_status_norm not in {
        "DATA_PENDING", "DATA_RECEIVED", "IN_PREPARATION", "PENDING_OTP", "READY_TO_FILE", "FILED", "OVERDUE"
    }:
        raise HTTPException(status_code=400, detail="Invalid filing_status.")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    missed_predicate = """
        (
            d.gstr1_status = 'MISSED'
            OR d.gstr3b_status = 'MISSED'
            OR d.gstr9_status = 'MISSED'
            OR d.gstr9c_status = 'MISSED'
            OR d.cmp08_status = 'MISSED'
            OR d.gstr4_status = 'MISSED'
        )
    """

    where_clause, values, idx = _build_gst_missed_filters(
        role=role,
        emp_id=emp_id,
        gst_filing_id=gst_filing_id,
        customer_id=customer_id,
        gst_registration_id=gst_registration_id,
        cx_number=cx_number_norm,
        rm_id=rm_id,
        op_id=op_id,
        filing_category=filing_category_norm,
        filing_status=filing_status_norm,
        filing_frequency=freq,
        is_auto_enabled=is_auto_enabled,
        created_from=created_from_ist,
        created_to=created_to_ist,
        data_received_from=data_received_from_ist,
        data_received_to=data_received_to_ist,
        filed_from=filed_from_ist,
        filed_to=filed_to_ist,
        include_inactive=include_inactive,
    )

    base_cte = f"""
        WITH per_filing AS (
            SELECT
                f.id AS gst_filing_id,
                f.customer_id,
                c.mobile AS cx_number,
                f.gst_registration_id,
                f.rm_id,
                f.op_id,
                f.filing_frequency,
                COUNT(d.id) AS missed_records_count
            FROM {DB_SCHEMA}.gst_filings f
            JOIN {DB_SCHEMA}.gst_filing_return_details d
              ON d.gst_filing_id = f.id
             AND d.is_active = TRUE
             AND {missed_predicate}
            LEFT JOIN {DB_SCHEMA}.customers c
              ON c.customer_id = f.customer_id
            {where_clause}
            GROUP BY
                f.id, f.customer_id, c.mobile,
                f.gst_registration_id, f.rm_id, f.op_id, f.filing_frequency
            HAVING COUNT(d.id) = 1
        )
    """

    count_sql = base_cte + " SELECT COUNT(*) AS total_count FROM per_filing "
    data_sql = (
        base_cte
        + f"""
        SELECT *
        FROM per_filing
        ORDER BY gst_filing_id DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """
    )

    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *(values + [limit, offset]))
    except asyncpg.PostgresError:
        log.exception("Database error for exact-one MISSED dashboard query")
        raise HTTPException(status_code=500, detail="Database error.")
    except Exception:
        log.exception("Unexpected error for exact-one MISSED dashboard query")
        raise HTTPException(status_code=500, detail="Internal server error.")

    return {
        "data": [dict(r) for r in rows],
        "count": len(rows),
        "total_count": int(total or 0),
        "limit": limit,
        "offset": offset,
        "request_id": request_id,
    }
