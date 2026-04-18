import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime, timedelta
from app.gst_registration_filing.schemas import (
    GSTFilingIn,
    GSTFilingYearlyIn,
    GSTFilingEditIn,
    GSTReturnStatusUpdateIn,
    GSTReturnDetailsBulkDeleteIn,
    GSTRegistrationFilingPrefillOut,
)
from app.gst_registration_filing.gst_filing_auto_policy import auto_enable_blocked_by_missed
from app.utils import (
    get_db_pool,
    DB_SCHEMA,
    generate_uuid,
    build_gst_filing_visibility,
    build_gst_visibility,
)
from app.security.rbac import require_permission
from app.logger import logger
from zoneinfo import ZoneInfo
import json
import uuid
import re
import calendar

router = APIRouter(
    prefix="/api/v1/gst-filings",
    tags=["GST Filings"]
)

class GstFilingApiMessages:
    """User-facing strings for HTTP responses in this module (UI copy)."""

    DB_UNAVAILABLE = (
        "We could not reach the database. Please wait a moment and try again."
    )
    DB_SAVE_FAILED = (
        "Your changes could not be saved because of a database error. Please try again."
    )
    SERVER_ERROR = (
        "Something unexpected happened on the server. Please try again or contact support."
    )
    INVALID_DATA_FORMAT = (
        "The submitted data could not be processed. Check the format and try again."
    )
    FOREIGN_KEY_BLOCKED = (
        "This action cannot be completed because related records are missing or invalid."
    )
    FILING_NOT_FOUND = "No GST filing was found for this ID."
    FILTER_FAILED = SERVER_ERROR
    FILING_PERIOD_FORMAT_INVALID = (
        "Filing period must look like APR-2024, Q1-2024, or 2024-25. Please correct it."
    )
    CREATE_MODE_MANUAL_ONLY = (
        "New GST filings can only be created in MANUAL mode. Choose MANUAL and try again."
    )
    CREATE_CUSTOMER_INVALID = (
        "The customer is missing or inactive. Pick an active customer before continuing."
    )
    CREATE_GST_REGISTRATION_INVALID = (
        "The GST registration is missing or inactive. Link a valid registration or GSTIN."
    )
    PREFILL_GST_REGISTRATION_NOT_FOUND = (
        "No active GST registration was found for this ID, or you do not have access."
    )
    CREATE_ALREADY_EXISTS = (
        "A GST filing for this customer, period, and GSTIN already exists."
    )
    CREATE_REGULAR_FREQUENCY_INVALID = (
        "Regular taxpayers need MONTHLY or QUARTERLY filing frequency for return schedules."
    )
    CREATE_SUCCESS = "GST filing was created successfully."
    CREATE_DUPLICATE = (
        "This GST filing already exists (duplicate record). Open the existing filing instead."
    )
    FILING_PERIOD_INVALID = (
        "Filing period is not valid. Use formats like APR-2024, Q1-2024, or 2024-25."
    )
    UPDATE_NO_CHANGES = "No changes were sent. Update at least one field and try again."
    UPDATE_GST_REFERENCE_REQUIRED = (
        "Either a GST registration ID or a GSTIN is required to save this filing."
    )
    UPDATE_TAXPAYER_TYPE_INVALID_RECALC = (
        "Taxpayer type must be REGULAR or COMPOSITION when return schedules are rebuilt."
    )
    UPDATE_SUCCESS = "GST filing was updated successfully."
    UPDATE_DUPLICATE = CREATE_DUPLICATE
    DEACTIVATE_ALREADY_INACTIVE = "This GST filing is already inactive."
    DEACTIVATE_FILED_BLOCK = (
        "Completed (filed) GST filings cannot be deactivated. Contact support if you need a correction."
    )
    CUSTOMER_NOT_FOUND = "The linked customer could not be found."
    DEACTIVATE_CUSTOMER_INACTIVE = (
        "The customer is inactive. Activate the customer before deactivating this filing."
    )
    DEACTIVATE_FAILED = (
        "The GST filing could not be deactivated. Refresh the page and try again."
    )
    DEACTIVATE_SUCCESS = (
        "GST filing was deactivated. Related documents were deactivated as well."
    )
    CONSTRAINT_RULE_BLOCKED = "The action was blocked because a data rule was violated."
    CONSTRAINT_NAMED = "This action was blocked by validation rule: {constraint}."
    ACTIVATE_ALREADY_ACTIVE = "This GST filing is already active."
    ACTIVATE_CUSTOMER_INACTIVE = (
        "The customer is inactive. Activate the customer before reactivating this filing."
    )
    ACTIVATE_CONFLICT_RETRY = (
        "This filing changed while you were working. Refresh the page and try again."
    )
    ACTIVATE_SUCCESS = (
        "GST filing was activated. Related documents were activated as well."
    )
    RETURN_DETAILS_NOT_FOUND_BY_ID = (
        "No GST return-detail row exists for this ID. Confirm the return-detail ID from the filing screen."
    )
    RETURN_DETAILS_ROWS_MISSING = (
        "Return schedule rows are missing for this filing. Contact support if this looks wrong."
    )
    RETURN_STATUS_NOT_APPLICABLE_PREFIX = (
        "These return fields do not apply to this filing and cannot be updated here: "
    )
    RETURN_STATUS_NONE_UPDATED = (
        "Return statuses were not updated. The filing may not support the fields you chose, or nothing changed."
    )
    RETURN_STATUS_SUCCESS = "Return statuses were saved successfully."
    RETURN_STATUS_FK_INVALID = (
        "Return status could not be saved because a linked GST filing reference is invalid."
    )
    RETURN_STATUS_CONSTRAINT = (
        "Return status could not be saved because it breaks a validation rule."
    )
    RETURN_STATUS_CONSTRAINT_NAMED = "Return status blocked by rule: {constraint}."
    RETURN_STATUS_PAYLOAD_INVALID = (
        "Return status values could not be read. Use only allowed status values and try again."
    )
    RETURN_DETAILS_BULK_DELETE_SUCCESS = "Eligible MISSED return-detail rows were deleted."
    AUTO_ENABLE_BLOCKED_MISSED = (
        "Automatic return generation cannot be turned on while this filing has too many "
        "missed return periods. Resolve or deactivate those rows, then try again."
    )

    @staticmethod
    def return_status_not_applicable(field_names):
        return (
            GstFilingApiMessages.RETURN_STATUS_NOT_APPLICABLE_PREFIX
            + ", ".join(field_names)
        )


# Calendar buffer before earliest due for next_auto_generate_at (prep / auto-generation window).
_LEAD_DAYS_MONTHLY = 10
_LEAD_DAYS_QUARTERLY = 12
_LEAD_DAYS_YEARLY_ANNUAL = 7


def _lead_days_for_periodic_frequency(filing_frequency: str) -> int:
    if filing_frequency == "MONTHLY":
        return _LEAD_DAYS_MONTHLY
    if filing_frequency == "QUARTERLY":
        return _LEAD_DAYS_QUARTERLY
    return _LEAD_DAYS_YEARLY_ANNUAL


def _compute_next_auto_generate_at(*due_dates, lead_days: int = _LEAD_DAYS_YEARLY_ANNUAL):
    valid = [d for d in due_dates if d is not None]
    if not valid:
        return None
    return min(valid) - timedelta(days=lead_days)
# -------------------------------------------------------------------
# FILTER GST FILINGS (FINAL - WITH USERNAME + PASSWORD + RENT + EMAIL + ESTIMATED INVOICE)
# -------------------------------------------------------------------
@router.get(
    "/filter",
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
    filing_category: Optional[str] = None,
    filing_period: Optional[str] = None,

    # BUSINESS
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

    # EXTRA
    username: Optional[str] = None,
    email_id: Optional[str] = None,
    rent_min: Optional[float] = None,
    rent_max: Optional[float] = None,
    rule14a: Optional[bool] = None,

    # 🔥 DUE DATE FILTER (FROM RETURN TABLE)
    due_from: Optional[datetime] = None,
    due_to: Optional[datetime] = None,

    # DATES
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    data_received_from: Optional[datetime] = None,
    data_received_to: Optional[datetime] = None,

    # FLAGS
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    is_overdue: Optional[bool] = None,
    is_upcoming: Optional[bool] = None,
    is_auto_enabled: Optional[bool] = None,
    is_auto_generated: Optional[bool] = None,
    include_details: bool = Query(True),

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
        {"request_id": request_id, "emp_id": emp_id},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    try:
        conditions = []
        values = []
        idx = 1

        # ----------------------------
        # BASIC FILTERS
        # ----------------------------
        if id:
            conditions.append(f"f.id = ${idx}")
            values.append(id); idx += 1

        if customer_id:
            conditions.append(f"f.customer_id = ${idx}")
            values.append(customer_id); idx += 1

        if gst_registration_id:
            conditions.append(f"f.gst_registration_id = ${idx}")
            values.append(gst_registration_id); idx += 1

        if gstin:
            conditions.append(f"upper(f.gstin) = ${idx}")
            values.append(gstin.upper()); idx += 1

        if service_id:
            conditions.append(f"f.service_id = ${idx}")
            values.append(service_id); idx += 1

        if filing_category:
            conditions.append(f"f.filing_category = ${idx}")
            values.append(filing_category.upper()); idx += 1

        if filing_period:
            conditions.append(f"f.filing_period = ${idx}")
            values.append(filing_period.upper()); idx += 1

        # ----------------------------
        # BUSINESS
        # ----------------------------
        if filing_frequency:
            conditions.append(f"f.filing_frequency = ${idx}")
            values.append(filing_frequency.upper()); idx += 1

        if taxpayer_type:
            conditions.append(f"f.taxpayer_type = ${idx}")
            values.append(taxpayer_type.upper()); idx += 1

        if turnover_details:
            conditions.append(f"f.turnover_details = ${idx}")
            values.append(turnover_details.upper()); idx += 1

        if state:
            conditions.append(f"upper(f.state) = ${idx}")
            values.append(state.upper()); idx += 1

        # ----------------------------
        # STATUS
        # ----------------------------
        if status:
            conditions.append(f"f.status = ${idx}")
            values.append(status.upper()); idx += 1

        if statuses:
            conditions.append(f"f.status = ANY(${idx})")
            values.append([s.upper() for s in statuses]); idx += 1

        # ----------------------------
        # EXTRA FILTERS
        # ----------------------------
        if username:
            conditions.append(f"f.username ILIKE ${idx}")
            values.append(f"%{username}%"); idx += 1

        if email_id:
            conditions.append(f"lower(f.email_id) = ${idx}")
            values.append(email_id.lower()); idx += 1

        if rent_min is not None:
            conditions.append(f"f.rent >= ${idx}")
            values.append(rent_min); idx += 1

        if rent_max is not None:
            conditions.append(f"f.rent <= ${idx}")
            values.append(rent_max); idx += 1

        if rule14a is not None:
            conditions.append(f"f.rule14a = ${idx}")
            values.append(rule14a); idx += 1

        # ----------------------------
        # 🔥 DUE DATE FILTER (RETURN TABLE)
        # ----------------------------
        if due_from:
            conditions.append(f"""
                GREATEST(
                    COALESCE(d.gstr1_due_date, '-infinity'::timestamptz),
                    COALESCE(d.gstr3b_due_date, '-infinity'::timestamptz),
                    COALESCE(d.gstr9_due_date, '-infinity'::timestamptz),
                    COALESCE(d.gstr9c_due_date, '-infinity'::timestamptz),
                    COALESCE(d.cmp08_due_date, '-infinity'::timestamptz),
                    COALESCE(d.gstr4_due_date, '-infinity'::timestamptz)
                ) >= ${idx}
            """)
            values.append(due_from); idx += 1

        if due_to:
            conditions.append(f"""
                LEAST(
                    COALESCE(d.gstr1_due_date, 'infinity'::timestamptz),
                    COALESCE(d.gstr3b_due_date, 'infinity'::timestamptz),
                    COALESCE(d.gstr9_due_date, 'infinity'::timestamptz),
                    COALESCE(d.gstr9c_due_date, 'infinity'::timestamptz),
                    COALESCE(d.cmp08_due_date, 'infinity'::timestamptz),
                    COALESCE(d.gstr4_due_date, 'infinity'::timestamptz)
                ) <= ${idx}
            """)
            values.append(due_to); idx += 1

        # ----------------------------
        # FLAGS
        # ----------------------------
        if is_overdue:
            conditions.append("""
                (
                    (d.gstr1_status = 'NOT_FILED' AND d.gstr1_due_date < NOW())
                    OR (d.gstr3b_status = 'NOT_FILED' AND d.gstr3b_due_date < NOW())
                    OR (d.gstr9_status = 'NOT_FILED' AND d.gstr9_due_date < NOW())
                    OR (d.gstr9c_status = 'NOT_FILED' AND d.gstr9c_due_date < NOW())
                    OR (d.cmp08_status = 'NOT_FILED' AND d.cmp08_due_date < NOW())
                    OR (d.gstr4_status = 'NOT_FILED' AND d.gstr4_due_date < NOW())
                )
            """)

        if is_upcoming:
            conditions.append("""
                (
                    (d.gstr1_status = 'NOT_FILED' AND d.gstr1_due_date >= NOW())
                    OR (d.gstr3b_status = 'NOT_FILED' AND d.gstr3b_due_date >= NOW())
                    OR (d.gstr9_status = 'NOT_FILED' AND d.gstr9_due_date >= NOW())
                    OR (d.gstr9c_status = 'NOT_FILED' AND d.gstr9c_due_date >= NOW())
                    OR (d.cmp08_status = 'NOT_FILED' AND d.cmp08_due_date >= NOW())
                    OR (d.gstr4_status = 'NOT_FILED' AND d.gstr4_due_date >= NOW())
                )
            """)

        if is_active is not None:
            conditions.append(f"f.is_active = ${idx}")
            values.append(is_active); idx += 1
        elif not include_inactive:
            conditions.append("f.is_active = TRUE")

        if is_auto_enabled is not None:
            conditions.append(f"f.is_auto_enabled = ${idx}")
            values.append(is_auto_enabled); idx += 1

        if is_auto_generated is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM {DB_SCHEMA}.gst_filing_return_details d_auto "
                f"WHERE d_auto.gst_filing_id = f.id AND d_auto.is_auto_generated = ${idx})"
            )
            values.append(is_auto_generated); idx += 1

        # ----------------------------
        # VISIBILITY
        # ----------------------------
        visibility_sql, visibility_values, idx = build_gst_filing_visibility(
            role, emp_id, idx, DB_SCHEMA
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # ----------------------------
        # FINAL QUERY
        # ----------------------------
        select_clause = f"""
            SELECT f.*, 
                   COALESCE(f.business_name, r.business_name) AS business_name,
                   COALESCE(f.business_type, r.business_type) AS business_type,
                   COALESCE(f.state, r.state) AS state
        """
        
        from_clause = f"""
            FROM {DB_SCHEMA}.gst_filings f
            LEFT JOIN {DB_SCHEMA}.gst_registration r
                ON r.id = f.gst_registration_id
        """

        if include_details:
            query = f"""
                {select_clause}, d.*
                {from_clause}
                LEFT JOIN {DB_SCHEMA}.gst_filing_return_details d
                    ON d.gst_filing_id = f.id
                {where_clause}
                ORDER BY f.created_at DESC
                LIMIT ${idx} OFFSET ${idx+1}
            """
        else:
            query = f"""
                {select_clause}
                {from_clause}
                {where_clause}
                ORDER BY f.created_at DESC
                LIMIT ${idx} OFFSET ${idx+1}
            """

        values += [limit, offset]

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *values)

        data = [dict(r) for r in rows]

        # 🔥 PASSWORD MASK
        for d in data:
            d["password"] = None

        return {
            "data": data,
            "count": len(data),
            "limit": limit,
            "offset": offset,
            "request_id": request_id
        }

    except Exception:
        log.exception("Filter error")
        raise HTTPException(500, GstFilingApiMessages.FILTER_FAILED)


def _upper_or_none(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s.upper() if s else None
    return str(v).upper()


@router.get(
    "/gst-registration/{gst_registration_id}/prefill",
    summary="Load GST registration snapshot for new filing form",
    response_model=GSTRegistrationFilingPrefillOut,
)
async def get_gst_registration_prefill_for_filing(
    gst_registration_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):
    """
    Returns identity + filing-related fields from `gst_registration` so the UI can
    show them before `POST /gst-filings`. Does not change create logic, which only
    needs a small SELECT for validation and credential fallback.
    """
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "get_gst_registration_prefill_for_filing",
        },
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    conditions = ["g.id = $1", "g.is_active = TRUE"]
    values = [gst_registration_id]
    idx = 2

    visibility_sql, visibility_values, idx = build_gst_visibility(
        role_norm, emp_id, idx, DB_SCHEMA
    )
    if visibility_sql:
        conditions.append(f"({visibility_sql})")
        values.extend(visibility_values)

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            g.*,
            c.business_name AS customer_business_name,
            c.business_type AS customer_business_type,
            c.business_description AS customer_business_description
        FROM {DB_SCHEMA}.gst_registration g
        LEFT JOIN {DB_SCHEMA}.customers c
          ON c.customer_id = g.customer_id
        WHERE {where_clause}
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *values)
    except Exception:
        log.exception("Prefill query failed")
        raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)

    if not row:
        raise HTTPException(404, GstFilingApiMessages.PREFILL_GST_REGISTRATION_NOT_FOUND)

    r = dict(row)
    pwd = r.get("password")
    password_set = bool(pwd and str(pwd).strip())

    taxpayer_type = _upper_or_none(
        r.get("taxpayer_type") or r.get("registration_type")
    )
    filing_frequency = _upper_or_none(
        r.get("filing_frequency") or r.get("filing_preference")
    )
    
    # 🔥 Priority Logic: Reg-specific first, fallback to customer-level
    final_business_name = (r.get("business_name") or "").strip()
    if not final_business_name:
        final_business_name = (r.get("customer_business_name") or "").strip()
        
    final_business_type = _upper_or_none(
        r.get("business_type") or r.get("customer_business_type")
    )

    return GSTRegistrationFilingPrefillOut(
        request_id=request_id,
        gst_registration_id=int(r["id"]),
        gstin=_upper_or_none(r.get("gstin")),
        is_active=bool(r["is_active"]),
        username=(r.get("username") or "").strip(),
        password_set=password_set,
        taxpayer_type=taxpayer_type,
        filing_frequency=filing_frequency,
        turnover_details=_upper_or_none(r.get("turnover_details")),
        state=_upper_or_none(r.get("state")),
        gst_reg_status=_upper_or_none(r.get("registration_status")),
        business_name=final_business_name or None,
        business_type=final_business_type,
        business_description=(r.get("customer_business_description") or "").strip() or None,
        rm_id=r.get("rm_id"),
        op_id=r.get("created_by"),
        email_id=(r.get("email") or "").strip() or None,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing",
)
async def create_gst_filing(
    payload: GSTFilingIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_gst_filing"},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    GROUP_2_STATES = {
        "DELHI","UTTAR_PRADESH","BIHAR","WEST_BENGAL","ODISHA",
        "JHARKHAND","CHHATTISGARH","MADHYA_PRADESH","RAJASTHAN",
        "HARYANA","PUNJAB","HIMACHAL_PRADESH","UTTARAKHAND",
        "JAMMU_AND_KASHMIR","LADAKH","SIKKIM","ARUNACHAL_PRADESH",
        "NAGALAND","MANIPUR","MIZORAM","TRIPURA","MEGHALAYA",
        "ASSAM","CHANDIGARH"
    }

    from dateutil.relativedelta import relativedelta

    def generate_previous_period(freq: str):
        prev = now - relativedelta(months=1)
        if freq == "MONTHLY":
            return prev.strftime("%b-%Y").upper()
        elif freq == "QUARTERLY":
            q = (prev.month - 1) // 3 + 1
            return f"Q{q}-{prev.year}"
        else:
            return f"{prev.year}-{str(prev.year+1)[-2:]}" if prev.month >= 4 else f"{prev.year-1}-{str(prev.year)[-2:]}"

    def parse_filing_period_to_date(filing_period: str):
        try:
            return datetime.strptime(filing_period, "%b-%Y")
        except:
            pass

        if filing_period.startswith("Q"):
            q = int(filing_period[1])
            year = int(filing_period.split("-")[1])
            month = (q - 1) * 3 + 1
            return datetime(year, month, 1)

        if "-" in filing_period:
            year = int(filing_period[:4])
            return datetime(year, 4, 1)

        raise HTTPException(400, GstFilingApiMessages.FILING_PERIOD_FORMAT_INVALID)

    def build_due_date(base_date, month_offset, day):
        target = base_date + relativedelta(months=month_offset)
        return datetime(target.year, target.month, day, tzinfo=IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    filing_frequency = payload.filing_frequency.upper()
    filing_category = payload.filing_category.upper()
    state = payload.state.strip().upper() if payload.state else None
    gst_reg_status = payload.gst_reg_status.strip().upper() if payload.gst_reg_status else None

    username = payload.username.strip() if payload.username else None
    password = payload.password.strip() if payload.password else None
    email_id = payload.email_id.strip().lower() if payload.email_id else None

    # --------------------------------------------------
    # DEFAULT ASSIGNMENT BASED ON ROLE
    # --------------------------------------------------
    rm_id = payload.rm_id
    op_id = payload.op_id

    if role == "RM" and rm_id is None:
        rm_id = emp_id
    if role == "OP" and op_id is None:
        op_id = emp_id

    status = "DATA_PENDING"

    if payload.mode != "MANUAL":
        raise HTTPException(400, GstFilingApiMessages.CREATE_MODE_MANUAL_ONLY)

    filing_period = payload.filing_period or generate_previous_period(filing_frequency)

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # ================= CUSTOMER =================
                customer = await conn.fetchrow(
                    f"""SELECT customer_id, is_active
                        FROM {DB_SCHEMA}.customers
                        WHERE customer_id = $1""",
                    payload.customer_id,
                )

                if not customer or not customer["is_active"]:
                    raise HTTPException(400, GstFilingApiMessages.CREATE_CUSTOMER_INVALID)

                # ================= GST =================
                if payload.gst_registration_id:
                    gst = await conn.fetchrow(
                        f"""SELECT id, gstin, is_active
                              , username, password, registration_status
                            FROM {DB_SCHEMA}.gst_registration
                            WHERE id = $1""",
                        payload.gst_registration_id,
                    )

                    if not gst or not gst["is_active"]:
                        raise HTTPException(400, GstFilingApiMessages.CREATE_GST_REGISTRATION_INVALID)

                    gstin = gst["gstin"]
                    # If caller didn't pass credentials explicitly, fall back to GST registration credentials.
                    if username is None:
                        username = gst.get("username")
                    if password is None:
                        password = gst.get("password")
                    if gst_reg_status is None:
                        gst_reg_status = _upper_or_none(gst.get("registration_status"))
                else:
                    gstin = payload.gstin

                # ================= DUPLICATE =================
                duplicate = await conn.fetchval(
                    f"""
                    SELECT 1 FROM {DB_SCHEMA}.gst_filings
                    WHERE customer_id = $1
                      AND gst_registration_id IS NOT DISTINCT FROM $2
                      AND gstin IS NOT DISTINCT FROM $3
                      AND filing_period = $4
                      AND is_active = TRUE
                    """,
                    payload.customer_id,
                    payload.gst_registration_id,
                    gstin,
                    filing_period,
                )

                if duplicate:
                    return {
                        "message": GstFilingApiMessages.CREATE_ALREADY_EXISTS,
                        "request_id": request_id,
                    }

                # ================= INSERT GST FILING =================
                service_id = {"MONTHLY":4,"QUARTERLY":5,"YEARLY":6}[filing_frequency]

                filing_row = await conn.fetchrow(
                    f"""INSERT INTO {DB_SCHEMA}.gst_filings (
                        customer_id, gst_registration_id, gstin,
                        filing_category, filing_period, status,
                        service_id, priority, remarks,
                        rm_id, op_id,
                        is_auto_enabled,
                        taxpayer_type, filing_frequency,
                        turnover_details, state, gst_reg_status,
                        username, password, email_id, rent, rule14a,
                        business_name, business_type, business_description,
                        created_at, updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                        $21,$22,$23,$24,$25,
                        $26,$27
                    )
                    RETURNING *""",
                    payload.customer_id,
                    payload.gst_registration_id,
                    gstin,
                    filing_category,
                    filing_period,
                    status,
                    service_id,
                    payload.priority,
                    payload.remarks,
                    rm_id,
                    op_id,
                    True,
                    payload.taxpayer_type,
                    filing_frequency,
                    payload.turnover_details,
                    state,
                    gst_reg_status,
                    username,
                    password,
                    email_id,
                    payload.rent,
                    payload.rule14a,
                    payload.business_name,
                    payload.business_type,
                    payload.business_description,
                    now,
                    now,
                )

                filing_id = filing_row["id"]

                base_date = parse_filing_period_to_date(filing_period)

                def build_due_date_safe(base_dt, month_offset: int, day: int):
                    target = base_dt + relativedelta(months=month_offset)
                    last_day = calendar.monthrange(target.year, target.month)[1]
                    safe_day = min(day, last_day)
                    return datetime(target.year, target.month, safe_day, tzinfo=IST)

                def _get_status(due):
                    return "MISSED" if due and due < now else "NOT_FILED"

                if filing_category == "ANNUAL" and filing_frequency == "YEARLY":
                    # Annual returns only (same as legacy `/gst-filings/yearly`): one row — no GSTR-1/3B/CMP-08.
                    if payload.taxpayer_type == "REGULAR":
                        gstr9_due = build_due_date_safe(base_date, 9, 31)
                        gstr9c_valid = payload.turnover_details == "MORE_THAN_5CR"
                        gstr9c_due = build_due_date_safe(base_date, 9, 31) if gstr9c_valid else None
                        
                        gstr9_status = _get_status(gstr9_due)
                        gstr9c_status = _get_status(gstr9c_due) if gstr9c_valid else None

                        next_auto = _compute_next_auto_generate_at(
                            gstr9_due,
                            gstr9c_due,
                            lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
                        )
                        await conn.execute(
                            f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                                gst_filing_id,
                                filing_frequency,
                                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                                is_auto_generated, next_auto_generate_at
                            )
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                            filing_id,
                            "YEARLY",
                            None,
                            None,
                            gstr9_status,
                            gstr9c_status,
                            None,
                            None,
                            None,
                            None,
                            gstr9_due,
                            gstr9c_due,
                            None,
                            None,
                            False,
                            next_auto,
                        )
                    else:
                        gstr4_due = build_due_date_safe(base_date, 9, 30)
                        gstr4_status = _get_status(gstr4_due)
                        next_auto = _compute_next_auto_generate_at(
                            gstr4_due,
                            lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
                        )
                        await conn.execute(
                            f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                                gst_filing_id,
                                filing_frequency,
                                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                                is_auto_generated, next_auto_generate_at
                            )
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                            filing_id,
                            "YEARLY",
                            None,
                            None,
                            None,
                            None,
                            None,
                            gstr4_status,
                            None,
                            None,
                            None,
                            None,
                            None,
                            gstr4_due,
                            False,
                            next_auto,
                        )

                elif payload.taxpayer_type == "REGULAR":
                    # Row 1: GSTR1 + GSTR3B (RETURN category — MONTHLY / QUARTERLY only here)
                    if filing_frequency == "MONTHLY":
                        gstr1_due = build_due_date_safe(base_date, 1, 11)
                        gstr3b_due = build_due_date_safe(base_date, 1, 20)
                    elif filing_frequency == "QUARTERLY":
                        gstr1_due = build_due_date_safe(base_date, 1, 13)
                        due_day_3b = 24 if state in GROUP_2_STATES else 22
                        gstr3b_due = build_due_date_safe(base_date, 1, due_day_3b)
                    else:
                        raise HTTPException(400, GstFilingApiMessages.CREATE_REGULAR_FREQUENCY_INVALID)

                    gstr1_status = _get_status(gstr1_due)
                    gstr3b_status = _get_status(gstr3b_due)

                    next_auto_periodic = _compute_next_auto_generate_at(
                        gstr1_due,
                        gstr3b_due,
                        lead_days=_lead_days_for_periodic_frequency(filing_frequency),
                    )
                    await conn.execute(
                        f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                            gst_filing_id,
                            filing_frequency,
                            gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                            gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                            is_auto_generated, next_auto_generate_at
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                        filing_id,
                        filing_frequency,
                        gstr1_status,
                        gstr3b_status,
                        None,
                        None,
                        None,
                        None,
                        gstr1_due,
                        gstr3b_due,
                        None,
                        None,
                        None,
                        None,
                        False,
                        next_auto_periodic,
                    )

                    # Row 2: GSTR9 (+ GSTR9C when turnover > 5CR)
                    gstr9_due = build_due_date_safe(base_date, 9, 31)
                    gstr9c_valid = payload.turnover_details == "MORE_THAN_5CR"
                    gstr9c_due = build_due_date_safe(base_date, 9, 31) if gstr9c_valid else None
                    
                    gstr9_status = _get_status(gstr9_due)
                    gstr9c_status = _get_status(gstr9c_due) if gstr9c_valid else None

                    next_auto_annual = _compute_next_auto_generate_at(
                        gstr9_due,
                        gstr9c_due,
                        lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
                    )
                    await conn.execute(
                        f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                            gst_filing_id,
                            filing_frequency,
                            gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                            gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                            is_auto_generated, next_auto_generate_at
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                        filing_id,
                        "YEARLY",
                        None,
                        None,
                        gstr9_status,
                        gstr9c_status,
                        None,
                        None,
                        None,
                        None,
                        gstr9_due,
                        gstr9c_due,
                        None,
                        None,
                        False,
                        next_auto_annual,
                    )

                elif payload.taxpayer_type == "COMPOSITION":
                    # Row 1: CMP08
                    cmp08_due = build_due_date_safe(base_date, 1, 18)
                    cmp08_status = _get_status(cmp08_due)
                    next_auto_cmp = _compute_next_auto_generate_at(
                        cmp08_due,
                        lead_days=_LEAD_DAYS_QUARTERLY,
                    )
                    await conn.execute(
                        f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                            gst_filing_id,
                            filing_frequency,
                            gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                            gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                            is_auto_generated, next_auto_generate_at
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                        filing_id,
                        "QUARTERLY",
                        None,
                        None,
                        None,
                        None,
                        cmp08_status,
                        None,
                        None,
                        None,
                        None,
                        None,
                        cmp08_due,
                        None,
                        False,
                        next_auto_cmp,
                    )

                    # Row 2: GSTR4
                    gstr4_due = build_due_date_safe(base_date, 9, 30)
                    gstr4_status = _get_status(gstr4_due)
                    next_auto_g4 = _compute_next_auto_generate_at(
                        gstr4_due,
                        lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
                    )
                    await conn.execute(
                        f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                            gst_filing_id,
                            filing_frequency,
                            gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                            gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                            is_auto_generated, next_auto_generate_at
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                        filing_id,
                        "YEARLY",
                        None,
                        None,
                        None,
                        None,
                        None,
                        gstr4_status,
                        None,
                        None,
                        None,
                        None,
                        None,
                        gstr4_due,
                        False,
                        next_auto_g4,
                    )

                # ================= CUSTOMER SERVICE =================
                await conn.execute(
                    f"""INSERT INTO {DB_SCHEMA}.customer_services (
                        customer_id, service_id, service_status,
                        rm_id, op_id, entity_type, entity_id, created_at
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT DO NOTHING""",
                    payload.customer_id,
                    service_id,
                    "PENDING",
                    rm_id,
                    op_id,
                    "GST_FILING",
                    filing_id,
                    now,
                )

                # ================= VERSION LOG =================
                await conn.execute(
                    f"""INSERT INTO {DB_SCHEMA}.versions (
                        emp_id, entity_type, entity_id,
                        customer_id, action, json, updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                    emp_id,
                    "GST_FILING",
                    filing_id,
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(filing_row), default=str),
                    None,
                )

                return {
                    "data": {
                        **dict(filing_row),
                        # UI: don't expose credentials in API responses
                        "password": None,
                    },
                    "message": GstFilingApiMessages.CREATE_SUCCESS,
                    "request_id": request_id,
                }

        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(409, GstFilingApiMessages.CREATE_DUPLICATE)

        except asyncpg.PostgresError:
            log.exception("Database error")
            raise HTTPException(500, GstFilingApiMessages.DB_SAVE_FAILED)

        except Exception:
            log.exception("Unexpected error")
            raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)


@router.post(
    "/yearly",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing (ANNUAL + YEARLY only)",
)
async def create_gst_filing_yearly(
    payload: GSTFilingYearlyIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):
    """
    Convenience alias for `POST /gst-filings` with `filing_category=ANNUAL`,
    `filing_frequency=YEARLY`, `mode=MANUAL` — same handler and annual-only return-detail seeding.
    """
    merged = GSTFilingIn(
        customer_id=payload.customer_id,
        gst_registration_id=payload.gst_registration_id,
        gstin=payload.gstin,
        filing_category="ANNUAL",
        taxpayer_type=payload.taxpayer_type,
        filing_frequency="YEARLY",
        turnover_details=payload.turnover_details,
        state=payload.state,
        filing_period=payload.filing_period,
        rm_id=payload.rm_id,
        op_id=payload.op_id,
        priority=payload.priority,
        remarks=payload.remarks,
        username=payload.username,
        password=payload.password,
        rent=payload.rent,
        email_id=payload.email_id,
        rule14a=payload.rule14a,
    )
    return await create_gst_filing(merged, current_user)


# -------------------------------------------------------------------
# UPDATE GST FILING (FINAL - WITH USERNAME + PASSWORD + RENT + EMAIL 
# -------------------------------------------------------------------
@router.patch("/{filing_id}")
async def update_gst_filing(
    filing_id: int,
    payload: GSTFilingEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
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

    GROUP_2_STATES = {
        "DELHI","UTTAR_PRADESH","BIHAR","WEST_BENGAL","ODISHA",
        "JHARKHAND","CHHATTISGARH","MADHYA_PRADESH","RAJASTHAN",
        "HARYANA","PUNJAB","HIMACHAL_PRADESH","UTTARAKHAND",
        "JAMMU_AND_KASHMIR","LADAKH","SIKKIM","ARUNACHAL_PRADESH",
        "NAGALAND","MANIPUR","MIZORAM","TRIPURA","MEGHALAYA",
        "ASSAM","CHANDIGARH"
    }

    from dateutil.relativedelta import relativedelta

    def parse_filing_period(fp: str):
        try:
            return datetime.strptime(fp, "%b-%Y")
        except:
            pass

        if fp.startswith("Q"):
            q = int(fp[1])
            year = int(fp.split("-")[1])
            return datetime(year, (q - 1) * 3 + 1, 1)

        if "-" in fp:
            year = int(fp[:4])
            return datetime(year, 4, 1)

        raise HTTPException(400, GstFilingApiMessages.FILING_PERIOD_INVALID)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection error")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # =====================================================
                # LOCK EXISTING RECORD
                # =====================================================
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
                    raise HTTPException(404, GstFilingApiMessages.FILING_NOT_FOUND)

                update_data = payload.model_dump(exclude_unset=True)

                if not update_data:
                    raise HTTPException(400, GstFilingApiMessages.UPDATE_NO_CHANGES)

                # =====================================================
                # NORMALIZATION
                # =====================================================
                for key in [
                    "filing_category",
                    "filing_frequency",
                    "taxpayer_type",
                    "turnover_details",
                    "state",
                    "filing_period",
                ]:
                    if key in update_data and update_data[key]:
                        update_data[key] = update_data[key].upper()

                if "email_id" in update_data and update_data["email_id"]:
                    update_data["email_id"] = update_data["email_id"].lower().strip()

                if "username" in update_data and update_data["username"]:
                    update_data["username"] = update_data["username"].strip()

                if "password" in update_data and update_data["password"]:
                    update_data["password"] = update_data["password"].strip()
                if "business_name" in update_data and update_data["business_name"]:
                    update_data["business_name"] = update_data["business_name"].strip()
                if "business_description" in update_data and update_data["business_description"]:
                    update_data["business_description"] = update_data["business_description"].strip()

                if "filing_frequency" in update_data:
                    update_data["service_id"] = _FILING_FREQUENCY_TO_SERVICE_ID[
                        update_data["filing_frequency"]
                    ]

                # =====================================================
                # GST VALIDATION
                # =====================================================
                new_reg = update_data.get("gst_registration_id", old["gst_registration_id"])
                new_gstin = update_data.get("gstin", old["gstin"])

                if not new_reg and not new_gstin:
                    raise HTTPException(400, GstFilingApiMessages.UPDATE_GST_REFERENCE_REQUIRED)

                # Keep filing's gst_reg_status in sync with selected registration unless caller explicitly sets it.
                if "gst_registration_id" in update_data and update_data.get("gst_registration_id") is not None:
                    linked_reg_status = await conn.fetchval(
                        f"""
                        SELECT registration_status
                        FROM {DB_SCHEMA}.gst_registration
                        WHERE id = $1
                        """,
                        update_data["gst_registration_id"],
                    )
                    if linked_reg_status is None:
                        raise HTTPException(400, GstFilingApiMessages.CREATE_GST_REGISTRATION_INVALID)
                    if "gst_reg_status" not in update_data:
                        update_data["gst_reg_status"] = str(linked_reg_status).strip().upper()

                # =====================================================
                # MERGED VALUES (FINAL STATE)
                # =====================================================
                filing_category = update_data.get("filing_category", old["filing_category"])
                filing_frequency = update_data.get("filing_frequency", old["filing_frequency"])
                taxpayer_type = update_data.get("taxpayer_type", old["taxpayer_type"])
                turnover_details = update_data.get("turnover_details", old["turnover_details"])
                state = update_data.get("state", old["state"])
                filing_period = update_data.get("filing_period", old["filing_period"])

                # =====================================================
                # 🔥 RECALCULATION CHECK
                # =====================================================
                recalc_required = any(
                    k in update_data
                    for k in [
                        "filing_category",
                        "filing_frequency",
                        "taxpayer_type",
                        "turnover_details",
                        "state",
                        "filing_period",
                    ]
                )

                if (
                    "is_auto_enabled" in update_data
                    and update_data["is_auto_enabled"] is True
                    and not old["is_auto_enabled"]
                ):
                    if await auto_enable_blocked_by_missed(
                        conn,
                        filing_id,
                        filing_category,
                        filing_frequency,
                        taxpayer_type,
                    ):
                        raise HTTPException(
                            400, GstFilingApiMessages.AUTO_ENABLE_BLOCKED_MISSED
                        )

                # =====================================================
                # UPDATE MAIN TABLE
                # =====================================================
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

                # =====================================================
                # 🔥 REBUILD RETURN DETAILS (IF REQUIRED)
                # =====================================================
                if recalc_required:
                    def build_due_date_safe(base_dt, month_offset: int, day: int):
                        target = base_dt + relativedelta(months=month_offset)
                        last_day = calendar.monthrange(target.year, target.month)[1]
                        safe_day = min(day, last_day)
                        return datetime(target.year, target.month, safe_day, tzinfo=IST)

                    base_date = parse_filing_period(filing_period)

                    # DELETE OLD DETAILS (rebuild using your fixed two-row model)
                    await conn.execute(
                        f"""
                        DELETE FROM {DB_SCHEMA}.gst_filing_return_details
                        WHERE gst_filing_id = $1
                        """,
                        filing_id,
                    )

                    if taxpayer_type == "REGULAR":
                        # Row 1: GSTR1 + GSTR3B (only for MONTHLY/QUARTERLY)
                        if filing_frequency in ("MONTHLY", "QUARTERLY"):
                            if filing_frequency == "MONTHLY":
                                gstr1_due = build_due_date_safe(base_date, 1, 11)
                                gstr3b_due = build_due_date_safe(base_date, 1, 20)
                            else:
                                gstr1_due = build_due_date_safe(base_date, 1, 13)
                                due_day_3b = 24 if state in GROUP_2_STATES else 22
                                gstr3b_due = build_due_date_safe(base_date, 1, due_day_3b)

                            next_auto_periodic = _compute_next_auto_generate_at(
                                gstr1_due,
                                gstr3b_due,
                                lead_days=_lead_days_for_periodic_frequency(filing_frequency),
                            )
                            await conn.execute(
                                f"""
                                INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                                    gst_filing_id,
                                    filing_frequency,
                                    gstr1_status, gstr3b_status, gstr9_status, gstr9c_status,
                                    cmp08_status, gstr4_status,
                                    gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date,
                                    cmp08_due_date, gstr4_due_date,
                                    is_auto_generated, next_auto_generate_at
                                )
                                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                                """,
                                filing_id,
                                filing_frequency,
                                "NOT_FILED",
                                "NOT_FILED",
                                None,
                                None,
                                None,
                                None,
                                gstr1_due,
                                gstr3b_due,
                                None,
                                None,
                                None,
                                None,
                                False,
                                next_auto_periodic,
                            )

                        # Row 2: GSTR9 (+ GSTR9C when turnover > 5CR)
                        gstr9_due = build_due_date_safe(base_date, 9, 31)
                        gstr9c_status = (
                            "NOT_FILED" if turnover_details == "MORE_THAN_5CR" else None
                        )
                        gstr9c_due = gstr9_due if gstr9c_status else None

                        next_auto_annual = _compute_next_auto_generate_at(
                            gstr9_due,
                            gstr9c_due,
                            lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
                        )
                        await conn.execute(
                            f"""
                            INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                                gst_filing_id,
                                filing_frequency,
                                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status,
                                cmp08_status, gstr4_status,
                                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date,
                                cmp08_due_date, gstr4_due_date,
                                is_auto_generated, next_auto_generate_at
                            )
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                            """,
                            filing_id,
                            "YEARLY",
                            None,
                            None,
                            "NOT_FILED",
                            gstr9c_status,
                            None,
                            None,
                            None,
                            None,
                            gstr9_due,
                            gstr9c_due,
                            None,
                            None,
                            False,
                            next_auto_annual,
                        )

                    elif taxpayer_type == "COMPOSITION":
                        # Row 1: CMP08
                        cmp08_due = build_due_date_safe(base_date, 1, 18)
                        next_auto_cmp = _compute_next_auto_generate_at(
                            cmp08_due,
                            lead_days=_LEAD_DAYS_QUARTERLY,
                        )
                        await conn.execute(
                            f"""
                            INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                                gst_filing_id,
                                filing_frequency,
                                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status,
                                cmp08_status, gstr4_status,
                                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date,
                                cmp08_due_date, gstr4_due_date,
                                is_auto_generated, next_auto_generate_at
                            )
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                            """,
                            filing_id,
                            "QUARTERLY",
                            None,
                            None,
                            None,
                            None,
                            "NOT_FILED",
                            None,
                            None,
                            None,
                            None,
                            None,
                            cmp08_due,
                            None,
                            False,
                            next_auto_cmp,
                        )

                        # Row 2: GSTR4
                        gstr4_due = build_due_date_safe(base_date, 9, 30)
                        next_auto_g4 = _compute_next_auto_generate_at(
                            gstr4_due,
                            lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
                        )
                        await conn.execute(
                            f"""
                            INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                                gst_filing_id,
                                filing_frequency,
                                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status,
                                cmp08_status, gstr4_status,
                                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date,
                                cmp08_due_date, gstr4_due_date,
                                is_auto_generated, next_auto_generate_at
                            )
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                            """,
                            filing_id,
                            "YEARLY",
                            None,
                            None,
                            None,
                            None,
                            None,
                            "NOT_FILED",
                            None,
                            None,
                            None,
                            None,
                            None,
                            gstr4_due,
                            False,
                            next_auto_g4,
                        )

                    else:
                        raise HTTPException(400, GstFilingApiMessages.UPDATE_TAXPAYER_TYPE_INVALID_RECALC)

                # =====================================================
                # VERSION LOG
                # =====================================================
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions (
                        emp_id, entity_type, entity_id,
                        customer_id, action, json, updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "GST_FILING",
                    filing_id,
                    new["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old), default=str),
                    json.dumps(dict(new), default=str),
                )

                result = dict(new)
                result["password"] = None

                return {
                    "data": result,
                    "message": GstFilingApiMessages.UPDATE_SUCCESS,
                    "request_id": request_id,
                }

        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(409, GstFilingApiMessages.CREATE_DUPLICATE)

        except asyncpg.PostgresError:
            log.exception("Database error")
            raise HTTPException(500, GstFilingApiMessages.DB_SAVE_FAILED)

        except Exception:
            log.exception("Unexpected error")
            raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)

# -------------------------------------------------------------------
# SOFT DELETE GST FILING (WITH CUSTOMER CHECK + DOC CASCADE)
# -------------------------------------------------------------------
@router.delete(
    "/{filing_id}/deactivate",
    summary="Deactivate GST Filing (Cascade Documents + Audit)",
)
async def deactivate_gst_filing(
    filing_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "deactivate_gst_filing",
        },
    )

    log.info("Incoming deactivate GST filing | filing_id=%s", filing_id)

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ FETCH GST FILING
                # --------------------------------------------------
                filing = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    filing_id,
                )

                if not filing:
                    raise HTTPException(404, GstFilingApiMessages.FILING_NOT_FOUND)

                if not filing["is_active"]:
                    raise HTTPException(400, GstFilingApiMessages.DEACTIVATE_ALREADY_INACTIVE)

                # 🔥 OPTIONAL SAFETY (REAL WORLD)
                if filing["status"] == "FILED":
                    raise HTTPException(400, GstFilingApiMessages.DEACTIVATE_FILED_BLOCK)

                # --------------------------------------------------
                # 2️⃣ CUSTOMER VALIDATION
                # --------------------------------------------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                    """,
                    filing["customer_id"],
                )

                if not customer:
                    raise HTTPException(400, GstFilingApiMessages.CUSTOMER_NOT_FOUND)

                if not customer["is_active"]:
                    raise HTTPException(
                        400,
                        GstFilingApiMessages.DEACTIVATE_CUSTOMER_INACTIVE,
                    )

                # --------------------------------------------------
                # 3️⃣ DEACTIVATE GST FILING
                # --------------------------------------------------
                updated_filing = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings
                    SET is_active = FALSE,
                        updated_at = $2
                    WHERE id = $1
                      AND is_active = TRUE
                    RETURNING *
                    """,
                    filing_id,
                    now,
                )

                if not updated_filing:
                    raise HTTPException(400, GstFilingApiMessages.DEACTIVATE_FAILED)

                # --------------------------------------------------
                # 4️⃣ CASCADE DEACTIVATE DOCUMENTS
                # --------------------------------------------------
                deactivated_docs = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings_documents
                    SET is_active = FALSE,
                        updated_at = $2
                    WHERE gst_filing_id = $1
                      AND is_active = TRUE
                    RETURNING document_id
                    """,
                    filing_id,
                    now,
                )

                # ==================================================
                # 🔥 NEW: DEACTIVATE RETURN DETAILS
                # ==================================================
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filing_return_details
                    SET is_active = FALSE,
                        updated_at = $2
                    WHERE gst_filing_id = $1
                      AND is_active = TRUE
                    """,
                    filing_id,
                    now,
                )

                # ==================================================
                # 🔥 NEW: CUSTOMER SERVICE SYNC
                # ==================================================
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                    SET status = 'INACTIVE'
                    WHERE entity_type = 'GST_FILING'
                      AND entity_id = $1
                    """,
                    filing_id,
                )

                # --------------------------------------------------
                # 5️⃣ VERSION AUDIT
                # --------------------------------------------------
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
                    filing_id,
                    filing["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            log.info(
                "GST filing deactivated | filing_id=%s | docs_deactivated=%s",
                filing_id,
                len(deactivated_docs),
            )

            return {
                "data": dict(updated_filing),
                "documents_deactivated_count": len(deactivated_docs),
                "message": GstFilingApiMessages.DEACTIVATE_SUCCESS,
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, GstFilingApiMessages.FOREIGN_KEY_BLOCKED)

        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(
                400,
                f"{GstFilingApiMessages.CONSTRAINT_RULE_BLOCKED} ({e})",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(400, GstFilingApiMessages.INVALID_DATA_FORMAT)

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing deactivate")
            raise HTTPException(500, GstFilingApiMessages.DB_SAVE_FAILED)

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing deactivate")
            raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)
# -------------------------------------------------------------------
# ACTIVATE GST FILING (ENTERPRISE FINAL - CLEAN VALIDATION + CASCADE)
# -------------------------------------------------------------------
@router.post(
    "/{filing_id}/activate",
    summary="Activate GST Filing (Cascade Documents + Audit)",
)
async def activate_gst_filing(
    filing_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):

    # --------------------------------------------------
    # REQUEST CONTEXT
    # --------------------------------------------------
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_gst_filing",
        },
    )

    log.info("Incoming activate GST filing | filing_id=%s", filing_id)

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # DB CONNECTION
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ FETCH GST FILING (LOCK ROW)
                # --------------------------------------------------
                filing = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    filing_id,
                )

                if not filing:
                    raise HTTPException(404, GstFilingApiMessages.FILING_NOT_FOUND)

                if filing["is_active"]:
                    raise HTTPException(400, GstFilingApiMessages.ACTIVATE_ALREADY_ACTIVE)

                # --------------------------------------------------
                # 2️⃣ FETCH CUSTOMER (SEPARATE VALIDATION 🔥)
                # --------------------------------------------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                    """,
                    filing["customer_id"],
                )

                if not customer:
                    raise HTTPException(400, GstFilingApiMessages.CUSTOMER_NOT_FOUND)

                if not customer["is_active"]:
                    raise HTTPException(
                        400,
                        GstFilingApiMessages.ACTIVATE_CUSTOMER_INACTIVE,
                    )

                # --------------------------------------------------
                # 3️⃣ ACTIVATE GST FILING
                # --------------------------------------------------
                activated_filing = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings
                    SET is_active = TRUE,
                        updated_at = $2
                    WHERE id = $1
                      AND is_active = FALSE
                    RETURNING *
                    """,
                    filing_id,
                    now,
                )

                if not activated_filing:
                    raise HTTPException(
                        409,
                        GstFilingApiMessages.ACTIVATE_CONFLICT_RETRY,
                    )

                # --------------------------------------------------
                # 4️⃣ CASCADE ACTIVATE DOCUMENTS
                # --------------------------------------------------
                activated_docs = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings_documents
                    SET is_active = TRUE,
                        updated_at = $2
                    WHERE gst_filing_id = $1
                      AND is_active = FALSE
                    RETURNING document_id
                    """,
                    filing_id,
                    now,
                )

                # --------------------------------------------------
                # 4.1️⃣ CASCADE ACTIVATE RETURN DETAILS
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filing_return_details
                    SET is_active = TRUE,
                        updated_at = $2
                    WHERE gst_filing_id = $1
                      AND is_active = FALSE
                    """,
                    filing_id,
                    now,
                )

                # --------------------------------------------------
                # 4.2️⃣ RESTORE CUSTOMER SERVICE (PENDING)
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                    SET status = 'ACTIVE'
                    WHERE entity_type = 'GST_FILING'
                      AND entity_id = $1
                      AND status = 'INACTIVE'
                    """,
                    filing_id
                )

                # --------------------------------------------------
                # 5️⃣ VERSION AUDIT
                # --------------------------------------------------
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
                    filing_id,
                    filing["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            # --------------------------------------------------
            # SUCCESS RESPONSE
            # --------------------------------------------------
            log.info(
                "GST filing activated successfully | filing_id=%s | docs_activated=%s",
                filing_id,
                len(activated_docs),
            )

            return {
                "data": dict(activated_filing),
                "documents_activated_count": len(activated_docs),
                "message": GstFilingApiMessages.ACTIVATE_SUCCESS,
                "request_id": request_id,
            }

        # --------------------------------------------------
        # ERROR HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, GstFilingApiMessages.FOREIGN_KEY_BLOCKED)

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)
            raise HTTPException(
                status_code=400,
                detail=(
                    GstFilingApiMessages.CONSTRAINT_NAMED.format(constraint=constraint)
                    if constraint
                    else GstFilingApiMessages.CONSTRAINT_RULE_BLOCKED
                ),
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(400, GstFilingApiMessages.INVALID_DATA_FORMAT)

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing activation")
            raise HTTPException(500, GstFilingApiMessages.DB_SAVE_FAILED)

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing activation")
            raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)

# -------------------------------------------------------------------
# UPDATE RETURN STATUSES (FILED/NOT_FILED + ACTIVATE/DEACTIVATE ROWS)
# -------------------------------------------------------------------
@router.patch(
    "/{filing_id}/returns/status",
    summary="Update GST return statuses (GSTR1/3B/9/9C/CMP08/GSTR4) and optional activation",
)
async def update_return_statuses(
    filing_id: int,
    payload: GSTReturnStatusUpdateIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "update_return_statuses"},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # 1️⃣ Ensure filing exists
                filing = await conn.fetchrow(
                    f"""
                    SELECT id
                    FROM {DB_SCHEMA}.gst_filing_return_details
                    WHERE id = $1
                    """,
                    filing_id,
                )

                if not filing:
                    raise HTTPException(404, GstFilingApiMessages.RETURN_DETAILS_NOT_FOUND_BY_ID)

                detail_rows = await conn.fetch(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filing_return_details
                    WHERE id = $1
                    ORDER BY id
                    """,
                    filing_id,
                )

                if not detail_rows:
                    raise HTTPException(
                        404,
                        GstFilingApiMessages.RETURN_DETAILS_ROWS_MISSING,
                    )

                # 2️⃣ Optional: activate/deactivate detail rows
                if payload.is_active is not None:
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_filing_return_details
                        SET is_active = $2,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        filing_id,
                        payload.is_active,
                    )

                if payload.filing_frequency is not None:
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_filing_return_details
                        SET filing_frequency = $2,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        filing_id,
                        payload.filing_frequency,
                    )

                # 3️⃣ Build status updates only for provided fields
                status_fields = {
                    "gstr1_status": payload.gstr1_status,
                    "gstr3b_status": payload.gstr3b_status,
                    "gstr9_status": payload.gstr9_status,
                    "gstr9c_status": payload.gstr9c_status,
                    "cmp08_status": payload.cmp08_status,
                    "gstr4_status": payload.gstr4_status,
                }

                if any(v is not None for v in status_fields.values()):
                    requested_fields = [
                        field_name for field_name, field_value in status_fields.items()
                        if field_value is not None
                    ]
                    applicable_fields = []
                    non_applicable_fields = []

                    for field_name in requested_fields:
                        has_applicable_row = any(
                            row[field_name] is not None for row in detail_rows
                        )
                        if has_applicable_row:
                            applicable_fields.append(field_name)
                        else:
                            non_applicable_fields.append(field_name)

                    if non_applicable_fields:
                        raise HTTPException(
                            400,
                            GstFilingApiMessages.return_status_not_applicable(non_applicable_fields),
                        )

                    set_clauses = []
                    values = [filing_id]
                    idx = 2

                    for column in applicable_fields:
                        new_value = status_fields[column]
                        if new_value is not None:
                            set_clauses.append(
                                f"{column} = CASE WHEN {column} IS NOT NULL THEN ${idx}::varchar ELSE {column} END"
                            )
                            values.append(new_value)
                            idx += 1

                    if set_clauses:
                        update_result = await conn.execute(
                            f"""
                            UPDATE {DB_SCHEMA}.gst_filing_return_details
                            SET {', '.join(set_clauses)},
                                updated_at = NOW()
                            WHERE id = $1
                            """,
                            *values,
                        )
                        updated_count = int(update_result.split(" ")[-1])
                        if updated_count == 0:
                            raise HTTPException(
                                400,
                                GstFilingApiMessages.RETURN_STATUS_NONE_UPDATED,
                            )

                rows = await conn.fetch(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filing_return_details
                    WHERE id = $1
                    ORDER BY id
                    """,
                    filing_id,
                )

                updated_fields = [
                    k for k, v in status_fields.items()
                    if v is not None
                ]
                if payload.filing_frequency is not None:
                    updated_fields.append("filing_frequency")
                active_rows = sum(1 for r in rows if r["is_active"])

                return {
                    "data": [dict(r) for r in rows],
                    "message": GstFilingApiMessages.RETURN_STATUS_SUCCESS,
                    "updated_fields": updated_fields,
                    "active_return_details_count": active_rows,
                    "total_return_details_count": len(rows),
                    "request_id": request_id,
                }

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.exception("Foreign key error during return status update")
            raise HTTPException(400, GstFilingApiMessages.RETURN_STATUS_FK_INVALID)

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("Constraint violation during return status update")
            constraint = getattr(e, "constraint_name", None)
            if constraint:
                raise HTTPException(
                    400,
                    GstFilingApiMessages.RETURN_STATUS_CONSTRAINT_NAMED.format(constraint=constraint),
                )
            raise HTTPException(400, GstFilingApiMessages.RETURN_STATUS_CONSTRAINT)

        except asyncpg.exceptions.DataError:
            log.exception("Invalid data format during return status update")
            raise HTTPException(400, GstFilingApiMessages.RETURN_STATUS_PAYLOAD_INVALID)

        except asyncpg.PostgresError:
            log.exception("Database error during return status update")
            raise HTTPException(500, GstFilingApiMessages.DB_SAVE_FAILED)

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during return status update")
            raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)


@router.post(
    "/returns/delete-missed",
    summary="Bulk delete MISSED GST return-detail rows by IDs",
)
async def bulk_delete_missed_return_details(
    payload: GSTReturnDetailsBulkDeleteIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "bulk_delete_missed_return_details"},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, GstFilingApiMessages.DB_UNAVAILABLE)

    requested_ids = payload.return_detail_ids
    visibility_sql, visibility_values, _ = build_gst_filing_visibility(role, emp_id, 2, DB_SCHEMA)
    visibility_clause = f"AND ({visibility_sql})" if visibility_sql else ""

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

    select_sql = f"""
        SELECT d.id
        FROM {DB_SCHEMA}.gst_filing_return_details d
        JOIN {DB_SCHEMA}.gst_filings f
          ON f.id = d.gst_filing_id
        WHERE d.id = ANY($1::bigint[])
          AND {missed_predicate}
          {visibility_clause}
    """

    delete_sql = f"""
        DELETE FROM {DB_SCHEMA}.gst_filing_return_details d
        USING {DB_SCHEMA}.gst_filings f
        WHERE d.gst_filing_id = f.id
          AND d.id = ANY($1::bigint[])
          AND {missed_predicate}
          {visibility_clause}
        RETURNING d.id
    """

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                selected_rows = await conn.fetch(select_sql, requested_ids, *visibility_values)
                selected_ids = [int(r["id"]) for r in selected_rows]
                deleted_rows = await conn.fetch(delete_sql, requested_ids, *visibility_values)
                deleted_ids = [int(r["id"]) for r in deleted_rows]
    except asyncpg.PostgresError:
        log.exception("Database error during bulk delete missed return details")
        raise HTTPException(500, GstFilingApiMessages.DB_SAVE_FAILED)
    except Exception:
        log.exception("Unexpected error during bulk delete missed return details")
        raise HTTPException(500, GstFilingApiMessages.SERVER_ERROR)

    skipped_ids = [rid for rid in requested_ids if rid not in selected_ids]

    return {
        "message": GstFilingApiMessages.RETURN_DETAILS_BULK_DELETE_SUCCESS,
        "deleted_ids": deleted_ids,
        "deleted_count": len(deleted_ids),
        "skipped_ids": skipped_ids,
        "skipped_count": len(skipped_ids),
        "request_id": request_id,
    }