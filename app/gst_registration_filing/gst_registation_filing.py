import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime
from app.gst_registration_filing.schemas import GSTFilingIn, GSTFilingEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_filing_visibility
from app.security.rbac import require_permission
from app.logger import logger
from zoneinfo import ZoneInfo
import json
import uuid
from datetime import datetime
import re

router = APIRouter(
    prefix="/api/v1/gst-filings",
    tags=["GST Filings"]
)

# -------------------------------------------------------------------
# FILTER GST FILINGS (ENTERPRISE PRODUCTION READY - FINAL)
# -------------------------------------------------------------------
@router.get(
    "/gst-filings/filter",
    summary="Filter GST Filings",
)
async def filter_gst_filings(

    # PRIMARY
    id: Optional[int] = None,
    customer_id: Optional[int] = None,
    gst_registration_id: Optional[int] = None,
    gstin: Optional[str] = None,

    # SERVICE / TYPE
    service_id: Optional[int] = None,
    filing_type: Optional[str] = None,
    filing_category: Optional[str] = None,
    filing_period: Optional[str] = None,

    # 🔥 NEW BUSINESS FILTERS
    filing_frequency: Optional[str] = None,
    taxpayer_type: Optional[str] = None,
    turnover_details: Optional[str] = None,
    state: Optional[str] = None,

    # STATUS
    status: Optional[str] = None,
    statuses: Optional[List[str]] = Query(None),

    # USERS
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,

    # DATE FILTERS
    due_from: Optional[datetime] = None,
    due_to: Optional[datetime] = None,

    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,

    # 🔥 NEW DATE FILTERS
    data_received_from: Optional[datetime] = None,
    data_received_to: Optional[datetime] = None,

    next_auto_from: Optional[datetime] = None,
    next_auto_to: Optional[datetime] = None,

    # FLAGS
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),

    is_overdue: Optional[bool] = None,
    is_upcoming: Optional[bool] = None,

    # EXISTING FLAGS
    is_auto_enabled: Optional[bool] = None,
    is_auto_generated: Optional[bool] = None,

    # PAGINATION
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_gst_filings"},
    )

    log.info("Incoming GST filings filter | limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # DATE VALIDATION
    # --------------------------------------------------
    if due_from and due_to and due_from > due_to:
        raise HTTPException(400, "due_from cannot be greater than due_to")

    if created_from and created_to and created_from > created_to:
        raise HTTPException(400, "created_from cannot be greater than created_to")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    try:
        conditions = []
        values = []
        idx = 1

        # ----------------------------
        # BASIC FILTERS
        # ----------------------------
        if id:
            conditions.append(f"f.id = ${idx}")
            values.append(id)
            idx += 1

        if customer_id:
            conditions.append(f"f.customer_id = ${idx}")
            values.append(customer_id)
            idx += 1

        if gst_registration_id:
            conditions.append(f"f.gst_registration_id = ${idx}")
            values.append(gst_registration_id)
            idx += 1

        if gstin and gstin.strip():
            conditions.append(f"upper(f.gstin) = ${idx}")
            values.append(gstin.strip().upper())
            idx += 1

        if service_id:
            conditions.append(f"f.service_id = ${idx}")
            values.append(service_id)
            idx += 1

        if filing_type and filing_type.strip():
            conditions.append(f"f.filing_type = ${idx}")
            values.append(filing_type.strip().upper())
            idx += 1

        if filing_category and filing_category.strip():
            conditions.append(f"f.filing_category = ${idx}")
            values.append(filing_category.strip().upper())
            idx += 1

        if filing_period and filing_period.strip():
            conditions.append(f"f.filing_period = ${idx}")
            values.append(filing_period.strip().upper())
            idx += 1

        # ----------------------------
        # 🔥 NEW BUSINESS FILTERS
        # ----------------------------
        if filing_frequency:
            conditions.append(f"f.filing_frequency = ${idx}")
            values.append(filing_frequency.upper())
            idx += 1

        if taxpayer_type:
            conditions.append(f"f.taxpayer_type = ${idx}")
            values.append(taxpayer_type.upper())
            idx += 1

        if turnover_details:
            conditions.append(f"f.turnover_details = ${idx}")
            values.append(turnover_details.upper())
            idx += 1

        if state:
            conditions.append(f"upper(f.state) = ${idx}")
            values.append(state.upper())
            idx += 1

        # ----------------------------
        # STATUS
        # ----------------------------
        if status:
            conditions.append(f"f.status = ${idx}")
            values.append(status.upper())
            idx += 1

        if statuses:
            conditions.append(f"f.status = ANY(${idx})")
            values.append([s.upper() for s in statuses])
            idx += 1

        # ----------------------------
        # USERS
        # ----------------------------
        if rm_id:
            conditions.append(f"f.rm_id = ${idx}")
            values.append(rm_id)
            idx += 1

        if op_id:
            conditions.append(f"f.op_id = ${idx}")
            values.append(op_id)
            idx += 1

        # ----------------------------
        # DATE FILTERS
        # ----------------------------
        if due_from:
            conditions.append(f"f.due_date >= ${idx}")
            values.append(due_from)
            idx += 1

        if due_to:
            conditions.append(f"f.due_date <= ${idx}")
            values.append(due_to)
            idx += 1

        if created_from:
            conditions.append(f"f.created_at >= ${idx}")
            values.append(created_from)
            idx += 1

        if created_to:
            conditions.append(f"f.created_at <= ${idx}")
            values.append(created_to)
            idx += 1

        # 🔥 NEW DATE FILTERS
        if data_received_from:
            conditions.append(f"f.data_received_at >= ${idx}")
            values.append(data_received_from)
            idx += 1

        if data_received_to:
            conditions.append(f"f.data_received_at <= ${idx}")
            values.append(data_received_to)
            idx += 1

        if next_auto_from:
            conditions.append(f"f.next_auto_generate_at >= ${idx}")
            values.append(next_auto_from)
            idx += 1

        if next_auto_to:
            conditions.append(f"f.next_auto_generate_at <= ${idx}")
            values.append(next_auto_to)
            idx += 1

        # ----------------------------
        # FLAGS
        # ----------------------------
        if is_active is not None:
            conditions.append(f"f.is_active = ${idx}")
            values.append(is_active)
            idx += 1
        elif not include_inactive:
            conditions.append("f.is_active = TRUE")

        if is_overdue:
            conditions.append("(f.status != 'FILED' AND f.due_date < NOW())")

        if is_upcoming:
            conditions.append("(f.status = 'DATA_PENDING' AND f.due_date >= NOW())")

        if is_auto_enabled is not None:
            conditions.append(f"f.is_auto_enabled = ${idx}")
            values.append(is_auto_enabled)
            idx += 1

        if is_auto_generated is not None:
            conditions.append(f"f.is_auto_generated = ${idx}")
            values.append(is_auto_generated)
            idx += 1

        # ----------------------------
        # VISIBILITY
        # ----------------------------
        visibility_sql, visibility_values, idx = build_gst_filing_visibility(
            role, emp_id, idx, DB_SCHEMA
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # ----------------------------
        # QUERY BUILD
        # ----------------------------
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.gst_filings f
            {where_clause}
        """

        data_sql = f"""
            SELECT f.*,
                   rm.first_name AS rm_name,
                   op.first_name AS op_name
            FROM {DB_SCHEMA}.gst_filings f
            LEFT JOIN {DB_SCHEMA}.employees rm
                ON rm.emp_id = f.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op
                ON op.emp_id = f.op_id
            {where_clause}
            ORDER BY f.due_date ASC, f.id DESC
            LIMIT ${idx} OFFSET ${idx+1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info("GST filings filter success | returned=%s total=%s", len(rows), total)

        return {
            "data": [dict(r) for r in rows],
            "count": total,
            "limit": limit,
            "offset": offset,
            "request_id": request_id
        }

    except Exception:
        log.exception("Error filtering GST filings")
        raise HTTPException(500, "Internal server error")
# -------------------------------------------------------------------
# CREATE GST FILING (FINAL - FULL WITH SERVICE + VERSION LOG)
# -------------------------------------------------------------------
@router.post(
    "/gst-filings",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing",
)
async def create_gst_filing(
    payload: GSTFilingIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # =====================================================
    # NORMALIZATION
    # =====================================================
    filing_type = payload.filing_type.upper()
    filing_frequency = payload.filing_frequency.upper()
    filing_category = payload.filing_category.upper() if payload.filing_category else None
    status = payload.status.upper()

    # =====================================================
    # GENERATE filing_period
    # =====================================================
    def generate_filing_period(freq: str) -> str:
        if freq == "MONTHLY":
            return now.strftime("%b-%Y").upper()
        elif freq == "QUARTERLY":
            quarter = (now.month - 1) // 3 + 1
            return f"Q{quarter}-{now.year}"
        elif freq == "YEARLY":
            if now.month >= 4:
                return f"{now.year}-{str(now.year + 1)[-2:]}"
            else:
                return f"{now.year - 1}-{str(now.year)[-2:]}"
        else:
            raise HTTPException(400, "Invalid filing frequency")

    filing_period = payload.filing_period.upper() if payload.filing_period else generate_filing_period(filing_frequency)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # =====================================================
                # CUSTOMER VALIDATION
                # =====================================================
                customer = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                    """,
                    payload.customer_id,
                )

                if not customer:
                    raise HTTPException(400, "Customer not found")

                if not customer["is_active"]:
                    raise HTTPException(400, "Customer inactive")

                # =====================================================
                # GST VALIDATION
                # =====================================================
                if payload.gst_registration_id:

                    if payload.gstin:
                        raise HTTPException(
                            400,
                            "Do not pass gstin when gst_registration_id is provided"
                        )

                    gst = await conn.fetchrow(
                        f"""
                        SELECT id, gstin, is_active
                        FROM {DB_SCHEMA}.gst_registration
                        WHERE id = $1
                        """,
                        payload.gst_registration_id,
                    )

                    if not gst:
                        raise HTTPException(400, "Invalid GST registration")

                    if not gst["is_active"]:
                        raise HTTPException(400, "GST registration inactive")

                    gstin = gst["gstin"]

                else:
                    if not payload.gstin:
                        raise HTTPException(
                            400,
                            "gstin is required when GST is not registered with us"
                        )

                    gstin = payload.gstin

                # =====================================================
                # DUPLICATE CHECK
                # =====================================================
                duplicate = await conn.fetchval(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE gst_registration_id IS NOT DISTINCT FROM $1
                      AND gstin IS NOT DISTINCT FROM $2
                      AND filing_type = $3
                      AND filing_period = $4
                      AND is_active = TRUE
                    """,
                    payload.gst_registration_id,
                    gstin,
                    filing_type,
                    filing_period,
                )

                if duplicate:
                    raise HTTPException(409, "Filing already exists")

                # =====================================================
                # RULE ENGINE
                # =====================================================
                rule = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filing_rule_engine
                    WHERE filing_type = $1
                      AND frequency = $2
                      AND taxpayer_type = COALESCE($3, taxpayer_type)
                      AND (turnover_details = $4 OR turnover_details = 'ALL')
                      AND is_active = TRUE
                    ORDER BY sort_order
                    LIMIT 1
                    """,
                    filing_type,
                    filing_frequency,
                    payload.taxpayer_type,
                    payload.turnover_details,
                )

                if not rule:
                    raise HTTPException(400, "No filing rule configured")

                # =====================================================
                # DUE DATE CALCULATION
                # =====================================================
                import calendar, re

                if filing_frequency == "MONTHLY":
                    match = re.match(r"^([A-Z]{3})-(\d{4})$", filing_period)
                    if not match:
                        raise HTTPException(400, "Invalid monthly filing_period")

                    month_str, year = match.groups()
                    month = list(calendar.month_abbr).index(month_str.title())
                    year = int(year)

                    month = month + 1 if month < 12 else 1
                    year = year + 1 if month == 1 else year

                    due_date = datetime(year, month, rule["due_day"], tzinfo=IST)

                elif filing_frequency == "QUARTERLY":
                    match = re.match(r"^Q([1-4])-(\d{4})$", filing_period)
                    if not match:
                        raise HTTPException(400, "Invalid quarterly filing_period")

                    q, year = match.groups()
                    q, year = int(q), int(year)

                    month = q * 3 + 1
                    if month > 12:
                        month = 1
                        year += 1

                    due_date = datetime(year, month, rule["due_day"], tzinfo=IST)

                else:
                    match = re.match(r"^(\d{4})-(\d{2})$", filing_period)
                    if not match:
                        raise HTTPException(400, "Invalid yearly filing_period")

                    year = int(match.group(1)) + 1

                    due_date = datetime(
                        year,
                        rule["due_month_offset"],
                        rule["due_day"],
                        tzinfo=IST
                    )

                # =====================================================
                # SERVICE MAPPING
                # =====================================================
                service_map = {
                    "MONTHLY": 4,
                    "QUARTERLY": 5,
                    "YEARLY": 6,
                }

                service_id = service_map[filing_frequency]

                # =====================================================
                # INSERT GST FILING
                # =====================================================
                filing_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.gst_filings (
                        customer_id,
                        gst_registration_id,
                        gstin,
                        filing_type,
                        filing_category,
                        filing_period,
                        due_date,
                        status,
                        service_id,
                        priority,
                        remarks,
                        rm_id,
                        op_id,
                        is_auto_generated,
                        is_auto_enabled,
                        taxpayer_type,
                        filing_frequency,
                        turnover_details,
                        state,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21
                    )
                    RETURNING *
                    """,
                    payload.customer_id,
                    payload.gst_registration_id,
                    gstin,
                    filing_type,
                    filing_category,
                    filing_period,
                    due_date,
                    status,
                    service_id,
                    payload.priority,
                    payload.remarks,
                    payload.rm_id or emp_id,
                    payload.op_id,
                    False,
                    payload.is_auto_enabled,
                    payload.taxpayer_type,
                    filing_frequency,
                    payload.turnover_details,
                    payload.state,
                    now,
                    now,
                )

                # =====================================================
                # CUSTOMER SERVICE INSERT (🔥 IMPORTANT)
                # =====================================================
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.customer_services (
                        customer_id,
                        service_id,
                        service_status,
                        rm_id,
                        op_id,
                        entity_type,
                        entity_id,
                        created_at
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT DO NOTHING
                    """,
                    payload.customer_id,
                    service_id,
                    "PENDING",
                    payload.rm_id,
                    emp_id,
                    "GST_FILING",
                    filing_row["id"],
                    now,
                )

                # =====================================================
                # VERSION LOG (🔥 AUDIT)
                # =====================================================
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions (
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
                    "GST_FILING",
                    filing_row["id"],
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(filing_row), default=str),
                    None,
                )

                return {
                    "data": dict(filing_row),
                    "message": "GST filing created successfully",
                    "request_id": request_id,
                }

        # =====================================================
        # DB ERROR HANDLING (🔥 FULL)
        # =====================================================
        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(409, "Duplicate GST filing")

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            raise HTTPException(
                status_code=400,
                detail=f"Constraint violated: {constraint}"
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing create")
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing create")
            raise HTTPException(500, "Internal server error.")

@router.get("/gst-filings/ui_love")
async def get_gst_filings(
    request: Request,
    customer_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    filing_type: Optional[str] = Query(None),
    filing_frequency: Optional[str] = Query(None),
    taxpayer_type: Optional[str] = Query(None),
    from_due_date: Optional[datetime] = Query(None),
    to_due_date: Optional[datetime] = Query(None),

    search: Optional[str] = Query(None),
    quick_filter: Optional[str] = Query(None),

    sort_by: Optional[str] = Query("due_date"),
    sort_order: Optional[str] = Query("asc"),

    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        async with request.app.state.pool.acquire() as conn:

            user = request.state.user
            emp_id = user.get("emp_id")
            role = user.get("role")

            conditions = []
            values = []
            idx = 1

            # =====================================================
            # BASE CONDITION
            # =====================================================
            conditions.append("f.is_active = TRUE")

            # =====================================================
            # 🔐 VISIBILITY (YOUR FUNCTION)
            # =====================================================
            visibility_sql, visibility_values, idx = build_gst_filing_visibility(
                role, emp_id, idx, DB_SCHEMA
            )

            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            # =====================================================
            # FILTERS
            # =====================================================
            if customer_id:
                conditions.append(f"f.customer_id = ${idx}")
                values.append(customer_id)
                idx += 1

            if status:
                conditions.append(f"f.status = ${idx}")
                values.append(status.upper())
                idx += 1

            if filing_type:
                conditions.append(f"f.filing_type = ${idx}")
                values.append(filing_type.upper())
                idx += 1

            if filing_frequency:
                conditions.append(f"f.filing_frequency = ${idx}")
                values.append(filing_frequency.upper())
                idx += 1

            if taxpayer_type:
                conditions.append(f"f.taxpayer_type = ${idx}")
                values.append(taxpayer_type.upper())
                idx += 1

            if from_due_date:
                conditions.append(f"f.due_date >= ${idx}")
                values.append(from_due_date)
                idx += 1

            if to_due_date:
                conditions.append(f"f.due_date <= ${idx}")
                values.append(to_due_date)
                idx += 1

            # =====================================================
            # SEARCH
            # =====================================================
            if search and search.strip():
                conditions.append(f"""
                    (
                        f.gstin ILIKE ${idx}
                        OR f.filing_type ILIKE ${idx}
                        OR f.filing_period ILIKE ${idx}
                    )
                """)
                values.append(f"%{search.strip()}%")
                idx += 1

            # =====================================================
            # QUICK FILTERS
            # =====================================================
            if quick_filter == "TODAY":
                conditions.append("DATE(f.due_date) = CURRENT_DATE")

            elif quick_filter == "OVERDUE":
                conditions.append("(f.status != 'FILED' AND f.due_date < NOW())")

            elif quick_filter == "THIS_MONTH":
                conditions.append(
                    "date_trunc('month', f.due_date) = date_trunc('month', NOW())"
                )

            # =====================================================
            # WHERE
            # =====================================================
            where_clause = " AND ".join(conditions)

            # =====================================================
            # SORTING
            # =====================================================
            SORT_FIELDS = {
                "due_date": "f.due_date",
                "created_at": "f.created_at",
                "status": "f.status",
                "priority": "f.priority",
            }

            sort_column = SORT_FIELDS.get(sort_by, "f.due_date")
            order = "ASC" if sort_order.lower() == "asc" else "DESC"

            # =====================================================
            # PAGINATION
            # =====================================================
            offset = (page - 1) * limit

            # =====================================================
            # MAIN QUERY
            # =====================================================
            query = f"""
            SELECT
                f.*,
                c.name AS customer_name
            FROM {DB_SCHEMA}.gst_filings f
            LEFT JOIN {DB_SCHEMA}.customers c
                ON c.customer_id = f.customer_id
            WHERE {where_clause}
            ORDER BY {sort_column} {order}, f.id DESC
            LIMIT ${idx} OFFSET ${idx+1}
            """

            values.extend([limit, offset])

            rows = await conn.fetch(query, *values)

            # =====================================================
            # COUNT
            # =====================================================
            count_query = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.gst_filings f
            WHERE {where_clause}
            """

            total = await conn.fetchval(count_query, *values[:-2])

            # =====================================================
            # SUMMARY
            # =====================================================
            summary_query = f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'DATA_PENDING') AS pending,
                COUNT(*) FILTER (WHERE status = 'FILED') AS filed,
                COUNT(*) FILTER (
                    WHERE status != 'FILED' AND due_date < NOW()
                ) AS overdue
            FROM {DB_SCHEMA}.gst_filings f
            WHERE {where_clause}
            """

            summary = await conn.fetchrow(summary_query, *values[:-2])

            # =====================================================
            # RESPONSE
            # =====================================================
            return {
                "data": [dict(row) for row in rows],
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "pages": (total // limit) + (1 if total % limit else 0),
                },
                "summary": dict(summary) if summary else {},
            }

    except Exception:
        log.exception("Error fetching GST filings")
        raise HTTPException(500, "Internal server error")
# -------------------------------------------------------------------
# UPDATE GST FILING (FINAL - RULE ENGINE + FULL ERROR HANDLING)
# -------------------------------------------------------------------
@router.patch("/gst-filings/{filing_id}")
async def update_gst_filing(
    filing_id: int,
    payload: GSTFilingEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id = int(current_user.get("emp_id") or current_user.get("sub") or 0)

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection error")
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # LOCK EXISTING
                # --------------------------------------------------
                old = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE id=$1
                    FOR UPDATE
                    """,
                    filing_id,
                )

                if not old:
                    raise HTTPException(404, "GST filing not found")

                update_data = payload.model_dump(exclude_unset=True)

                if not update_data:
                    raise HTTPException(400, "No fields to update")

                # --------------------------------------------------
                # NORMALIZATION (EXISTING LOGIC KEPT)
                # --------------------------------------------------
                if "filing_category" in update_data and update_data["filing_category"]:
                    update_data["filing_category"] = update_data["filing_category"].upper()

                if "filing_frequency" in update_data and update_data["filing_frequency"]:
                    update_data["filing_frequency"] = update_data["filing_frequency"].upper()

                if "taxpayer_type" in update_data and update_data["taxpayer_type"]:
                    update_data["taxpayer_type"] = update_data["taxpayer_type"].upper()

                if "turnover_details" in update_data and update_data["turnover_details"]:
                    update_data["turnover_details"] = update_data["turnover_details"].upper()

                if "status" in update_data:
                    update_data["status"] = update_data["status"].upper()

                # --------------------------------------------------
                # GST SAFETY (EXISTING)
                # --------------------------------------------------
                new_reg = update_data.get("gst_registration_id", old["gst_registration_id"])
                new_gstin = update_data.get("gstin", old["gstin"])

                if not new_reg and not new_gstin:
                    raise HTTPException(400, "GST reference required")

                # --------------------------------------------------
                # FINAL MERGED VALUES
                # --------------------------------------------------
                filing_type = old["filing_type"]
                filing_frequency = update_data.get("filing_frequency", old["filing_frequency"])
                taxpayer_type = update_data.get("taxpayer_type", old["taxpayer_type"])
                turnover_details = update_data.get("turnover_details", old["turnover_details"])

                # --------------------------------------------------
                # RULE ENGINE RE-CALC (🔥 NEW)
                # --------------------------------------------------
                recalc_required = any(
                    k in update_data
                    for k in ["filing_frequency", "taxpayer_type", "turnover_details"]
                )

                if recalc_required:

                    rule = await conn.fetchrow(
                        f"""
                        SELECT *
                        FROM {DB_SCHEMA}.gst_filing_rule_engine
                        WHERE filing_type = $1
                          AND frequency = $2
                          AND taxpayer_type = COALESCE($3, taxpayer_type)
                          AND (turnover_details = $4 OR turnover_details = 'ALL')
                          AND is_active = TRUE
                        ORDER BY sort_order
                        LIMIT 1
                        """,
                        filing_type,
                        filing_frequency,
                        taxpayer_type,
                        turnover_details,
                    )

                    if not rule:
                        raise HTTPException(400, "No matching rule found")

                    import calendar

                    filing_period = old["filing_period"]

                    # -------- MONTHLY --------
                    if filing_frequency == "MONTHLY":
                        month_str, year = filing_period.split("-")
                        month = list(calendar.month_abbr).index(month_str.title())
                        year = int(year)

                        month = month + 1 if month < 12 else 1
                        year = year + 1 if month == 1 else year

                        update_data["due_date"] = datetime(
                            year, month, rule["due_day"], tzinfo=IST
                        )

                    # -------- QUARTERLY --------
                    elif filing_frequency == "QUARTERLY":
                        q, year = filing_period.split("-")
                        q = int(q.replace("Q", ""))
                        year = int(year)

                        month = q * 3 + 1
                        if month > 12:
                            month = 1
                            year += 1

                        update_data["due_date"] = datetime(
                            year, month, rule["due_day"], tzinfo=IST
                        )

                    # -------- YEARLY --------
                    else:
                        year = int(filing_period.split("-")[0]) + 1

                        update_data["due_date"] = datetime(
                            year,
                            rule["due_month_offset"],
                            rule["due_day"],
                            tzinfo=IST
                        )

                    # SERVICE UPDATE
                    service_map = {
                        "MONTHLY": 4,
                        "QUARTERLY": 5,
                        "YEARLY": 6,
                    }

                    update_data["service_id"] = service_map[filing_frequency]

                # --------------------------------------------------
                # STATUS TRANSITION (EXISTING + IMPROVED)
                # --------------------------------------------------
                VALID = {
                    "DATA_PENDING": ["DATA_RECEIVED"],
                    "DATA_RECEIVED": ["IN_PREPARATION"],
                    "IN_PREPARATION": ["PENDING_OTP"],
                    "PENDING_OTP": ["READY_TO_FILE"],
                    "READY_TO_FILE": ["FILED"],
                    "FILED": [],
                    "OVERDUE": ["DATA_RECEIVED"],
                }

                if "status" in update_data:
                    old_status = old["status"]
                    new_status = update_data["status"]

                    if new_status not in VALID.get(old_status, []):
                        raise HTTPException(400, "Invalid status transition")

                    if new_status == "FILED":
                        update_data["filed_at"] = now

                # --------------------------------------------------
                # BUILD QUERY (EXISTING)
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{k}=${idx}")
                    values.append(v)
                    idx += 1

                fields.append(f"updated_at=${idx}")
                values.append(now)
                idx += 1

                values.append(filing_id)

                new = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings
                    SET {', '.join(fields)}
                    WHERE id=${idx}
                    RETURNING *
                    """,
                    *values,
                )

                # --------------------------------------------------
                # VERSION AUDIT (EXISTING)
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    emp_id,
                    "GST_FILING",
                    filing_id,
                    new["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old), default=str),
                    json.dumps(dict(new), default=str),
                    now,
                )

                return {
                    "data": dict(new),
                    "message": "GST filing updated successfully",
                    "request_id": request_id,
                }

        # =====================================================
        # DB ERROR HANDLING (🔥 NOW INCLUDED)
        # =====================================================
        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(409, "Duplicate GST filing")

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            raise HTTPException(
                status_code=400,
                detail=f"Constraint violated: {constraint}"
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing update")
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing update")
            raise HTTPException(500, "Internal server error.")