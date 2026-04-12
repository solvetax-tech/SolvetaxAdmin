import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime
from app.gst_registration.schemas import (
    GSTRegistrationIn,
    GSTRegistrationEditIn,
    CustomerSnapshotForGstOut,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_visibility, build_customer_visibility
from app.security.rbac import require_permission
from app.logger import logger
from zoneinfo import ZoneInfo
import json
import uuid
from datetime import datetime
import re

router = APIRouter(
    prefix="/api/v1/gst-registrations",
    tags=["GST Registration"]
)

# CRM `crm_leads.entity_type` when the lead is tied to a GST registration row.
CRM_LEAD_ENTITY_TYPE_GST_REGISTRATION = "GST_REGISTRATION"


async def _sync_crm_lead_with_gst(
    conn: asyncpg.Connection,
    gst_row: asyncpg.Record,
):
    """
    Syncs crm_leads with gst_registration lifecycle.
    Safe no-op when CRM tables are unavailable.
    """
    try:
        mobile = gst_row.get("mobile")
        if not mobile:
            return

        existing = await conn.fetchrow(
            f"""
            SELECT *
            FROM {DB_SCHEMA}.crm_leads
            WHERE entity_type = $1
              AND entity_id = $2
              AND is_active = TRUE
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            CRM_LEAD_ENTITY_TYPE_GST_REGISTRATION,
            gst_row["id"],
        )

        # Fallback: reuse latest active lead by mobile if GST link is missing.
        if not existing:
            existing = await conn.fetchrow(
                f"""
                SELECT *
                FROM {DB_SCHEMA}.crm_leads
                WHERE mobile = $1
                  AND is_active = TRUE
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                mobile,
            )

        remarks = "Auto synced from GST registration create/edit."

        if existing:
            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.crm_leads
                SET mobile = $1,
                    entity_id = $2,
                    entity_type = $3,
                    rm_id = $4,
                    op_id = $5,
                    is_active = $6,
                    updated_at = NOW()
                WHERE id = $7
                """,
                mobile,
                gst_row["id"],
                CRM_LEAD_ENTITY_TYPE_GST_REGISTRATION,
                gst_row.get("rm_id"),
                gst_row.get("created_by"),
                gst_row.get("is_active"),
                existing["id"],
            )
        else:
            await conn.fetchval(
                f"""
                INSERT INTO {DB_SCHEMA}.crm_leads (
                    mobile, entity_id, entity_type, stage, rm_id, op_id, is_active, remarks, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
                RETURNING id
                """,
                mobile,
                gst_row["id"],
                CRM_LEAD_ENTITY_TYPE_GST_REGISTRATION,
                "FRESH_LEAD",
                gst_row.get("rm_id"),
                gst_row.get("created_by"),
                gst_row.get("is_active"),
                remarks,
            )
    except asyncpg.UndefinedTableError:
        logger.warning("CRM tables not found; skipping CRM sync.")
    except asyncpg.PostgresError:
        logger.exception("CRM sync failed; continuing GST flow.")
# -------------------------------------------------------------------
# CREATE GST REGISTRATION
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Registration",
    responses={
        201: {"description": "GST registration created successfully."},
        400: {"description": "Validation failed or customer not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def create_gst_registration(
    payload: GSTRegistrationIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    # Assignment: mirror customer create — RM defaults rm_id; created_by = current emp_id only when role is OP.
    rm_id = payload.rm_id
    if role_norm == "RM" and rm_id is None:
        rm_id = emp_id
    created_by_val = emp_id if role_norm == "OP" else None
    op_id_for_service = emp_id if role_norm == "OP" else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                customer_row = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                    LIMIT 1
                    """,
                    payload.customer_id,
                )

                if not customer_row:
                    raise HTTPException(400, "Customer not found.")

                if not customer_row["is_active"]:
                    raise HTTPException(400, "Customer is inactive.")

                # --------------------------------------------------
                # Pre-validation (format + duplicates)
                # --------------------------------------------------
                field_errors = {}

                gstin_value = payload.gstin.strip().upper() if payload.gstin else None
                pan_value = payload.pan.strip().upper() if payload.pan else None
                mobile_value = payload.mobile.strip() if payload.mobile else None
                username_value = payload.username.strip() if payload.username else None
                secondary_email_value = payload.secondary_email.strip().lower() if payload.secondary_email else None

                username_value = username_value or None
                mobile_value = mobile_value or None
                secondary_email_value = secondary_email_value or None

                if gstin_value and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]", gstin_value):
                    field_errors["gstin"] = "Invalid GSTIN format."

                if pan_value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_value):
                    field_errors["pan"] = "Invalid PAN format."

                if mobile_value and not re.fullmatch(r"[0-9]{10}", mobile_value):
                    field_errors["mobile"] = "Invalid mobile number format."

                if secondary_email_value:
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", secondary_email_value):
                        field_errors["secondary_email"] = "Invalid secondary email format."

                if gstin_value and pan_value:
                    gstin_pan = gstin_value[2:12]
                    if gstin_pan != pan_value:
                        field_errors["pan"] = "PAN does not match GSTIN."

                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT
                        CASE
                            WHEN $1::text IS NULL OR trim($1::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE gstin IS NOT NULL
                                   AND upper(trim(gstin)) = upper(trim($1::text))
                            )
                        END AS gstin_match,
                        CASE
                            WHEN $2::text IS NULL OR trim($2::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE username IS NOT NULL
                                   AND lower(trim(username)) = lower(trim($2::text))
                            )
                        END AS username_match,
                        CASE
                            WHEN $3::text IS NULL OR trim($3::text) = '' OR $4::text IS NULL OR trim($4::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE is_active = TRUE
                                   AND upper(trim(gstin)) = upper(trim($3::text))
                                   AND mobile = trim($4::text)
                            )
                        END AS gstin_mobile_match
                    """,
                    gstin_value,
                    username_value,
                    gstin_value,
                    mobile_value,
                )

                has_duplicate = False
                if duplicate_row:
                    if duplicate_row["gstin_match"]:
                        field_errors["gstin"] = "GSTIN already exists."
                        has_duplicate = True
                    if duplicate_row["username_match"]:
                        field_errors["username"] = "Username already exists."
                        has_duplicate = True

                if field_errors:
                    raise HTTPException(
                        status_code=409 if has_duplicate else 400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                            }
                        },
                    )

                if rm_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail="rm_id is required (or sign in as RM to default rm_id to yourself).",
                    )

                # --------------------------------------------------
                # INSERT GST
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.gst_registration (
                        customer_id,
                        username,
                        password,
                        pan,
                        gstin,
                        business_name,
                        registration_type,
                        ownership_category,
                        business_type,
                        state,
                        turnover_details,
                        registration_status,
                        suspension_reason,
                        cancellation_reason,
                        is_rcm_applicable,
                        is_filing_needed,
                        is_active,
                        mobile,
                        email,
                        secondary_email,
                        created_by,
                        rm_id,
                        filing_preference,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                        $21,$22,$23,$24,$25
                    )
                    RETURNING *
                """

                gst_row = await conn.fetchrow(
                    insert_sql,
                    payload.customer_id,
                    username_value,
                    payload.password,
                    pan_value,
                    gstin_value,
                    payload.business_name,
                    payload.registration_type,
                    payload.ownership_category,
                    payload.business_type,
                    payload.state,
                    payload.turnover_details,
                    payload.registration_status,
                    payload.suspension_reason,
                    payload.cancellation_reason,
                    payload.is_rcm_applicable,
                    payload.is_filing_needed,
                    True,
                    mobile_value,
                    payload.email,
                    secondary_email_value,
                    created_by_val,
                    rm_id,
                    getattr(payload, "filing_preference", None),
                    now,
                    now,
                )

                if not gst_row:
                    raise HTTPException(500, "GST registration creation failed.")

                # --------------------------------------------------
                # ✅ ALWAYS INSERT SERVICE_ID = 1
                # --------------------------------------------------
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
                    1,  # 🔥 FIXED SERVICE_ID
                    "PENDING",
                    rm_id,
                    op_id_for_service,
                    "GST_REGISTRATION",
                    gst_row["id"],
                    now,
                )

                # --------------------------------------------------
                # CRM LEAD SYNC (best-effort, non-blocking)
                # --------------------------------------------------
                await _sync_crm_lead_with_gst(conn, gst_row)

                # --------------------------------------------------
                # VERSION LOG
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
                    "GST_REGISTRATION",
                    gst_row["id"],
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(gst_row), default=str),
                    None,
                )

            return {
                **dict(gst_row),
                "message": "GST registration created successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "gst_registration_gstin_key": ("gstin", "GSTIN already exists."),
                "uq_gst_username_lower": ("username", "Username already exists."),
                "uq_gst_gstin_mobile_active": ("mobile", "Mobile already mapped to GST.")
            }

            field, message = UNIQUE_MAP.get(
                constraint,
                ("non_field_error", "Duplicate value violates unique constraint.")
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_gst_format": ("gstin", "Invalid GSTIN format."),
                "chk_pan_format": ("pan", "Invalid PAN format."),
                "chk_mobile_format": ("mobile", "Invalid mobile number format."),
                "chk_secondary_email_format": ("secondary_email", "Invalid secondary email format."),
                "chk_gstin_pan_match": ("pan", "PAN does not match GSTIN."),
                "chk_approved_logic": ("registration_status", "Invalid approved status logic."),
            }

            field, message = CHECK_MAP.get(
                constraint,
                ("non_field_error", f"Data violates constraint: {constraint}")
            )

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST registration create")
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST registration create")
            raise HTTPException(500, "Internal server error.")
# -------------------------------------------------------------------
# FILTER GST REGISTRATIONS (ENTERPRISE PRODUCTION READY)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter GST Registrations",
    responses={
        200: {"description": "GST registrations filtered successfully."},
        400: {"description": "Validation failed (e.g. invalid date range)."},
        500: {"description": "Database or internal error."},
    },
)
async def list_gst_registrations(
    gst_registration_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    gstin: Optional[str] = None,
    gstin_is_null: Optional[bool] = None,
    mobile: Optional[str] = None,
    mobile_is_null: Optional[bool] = None,
    email: Optional[str] = None,
    email_is_null: Optional[bool] = None,
    secondary_email: Optional[str] = None,
    secondary_email_is_null: Optional[bool] = None,
    rm_id: Optional[int] = None,
    created_by: Optional[int] = None,
    business_name: Optional[str] = None,
    business_name_is_null: Optional[bool] = None,
    business_type: Optional[str] = None,
    registration_status: Optional[str] = None,
    ownership_category: Optional[str] = None,
    state: Optional[str] = None,
    filing_preference: Optional[str] = None,  # ✅ ADDED
    has_service: Optional[bool] = None,       # ✅ ADDED
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = str(uuid.uuid4())

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming GST filter | limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # 🔥 ADDED VALIDATIONS (NO REMOVAL)
    # --------------------------------------------------

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    # ✅ TIMEZONE NORMALIZATION
    def normalize_dt(dt):
        if dt and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    from_date = normalize_dt(from_date)
    to_date = normalize_dt(to_date)

    # ✅ SAFE NORMALIZATION
    gstin = gstin.strip().upper() if gstin else None
    mobile = mobile.strip() if mobile else None
    email = email.strip().lower() if email else None
    secondary_email = secondary_email.strip().lower() if secondary_email else None

    # ✅ ENUM VALIDATIONS
    valid_registration_status = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED"}
    if registration_status and registration_status.strip().upper() not in valid_registration_status:
        raise HTTPException(400, "Invalid registration_status")

    valid_business_types = {"PROPRIETORSHIP", "PARTNERSHIP", "COMPANY", "LLP"}
    if business_type and business_type.strip().upper() not in valid_business_types:
        raise HTTPException(400, "Invalid business_type")

    valid_ownership = {"INDIVIDUAL", "COMPANY", "PARTNERSHIP"}
    if ownership_category and ownership_category.strip().upper() not in valid_ownership:
        raise HTTPException(400, "Invalid ownership_category")

    valid_filing_pref = {"MONTHLY", "QUARTERLY"}
    if filing_preference and filing_preference.strip().upper() not in valid_filing_pref:
        raise HTTPException(400, "Invalid filing_preference")

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

        join_customer_services = False  # ✅ ADDED

        # --------------------------------------------------
        # Indexed Exact Match Filters
        # --------------------------------------------------

        if gst_registration_id is not None:
            conditions.append(f"g.id = ${param_index}")
            values.append(gst_registration_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"g.customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gstin_is_null:
            conditions.append("g.gstin IS NULL")
        elif gstin:
            conditions.append(f"upper(g.gstin) = ${param_index}")
            values.append(gstin)
            param_index += 1

        if mobile_is_null:
            conditions.append("g.mobile IS NULL")
        elif mobile:
            conditions.append(f"g.mobile = ${param_index}")
            values.append(mobile)
            param_index += 1

        if email_is_null:
            conditions.append("g.email IS NULL")
        elif email:
            conditions.append(f"lower(g.email) = ${param_index}")
            values.append(email)
            param_index += 1

        if secondary_email_is_null:
            conditions.append("g.secondary_email IS NULL")
        elif secondary_email:
            conditions.append(f"lower(g.secondary_email) = ${param_index}")
            values.append(secondary_email)
            param_index += 1

        if rm_id is not None:
            conditions.append(f"g.rm_id = ${param_index}")
            values.append(rm_id)
            param_index += 1

        if created_by is not None:
            conditions.append(f"g.created_by = ${param_index}")
            values.append(created_by)
            param_index += 1

        if business_name_is_null:
            conditions.append("g.business_name IS NULL")

        elif business_name and business_name.strip():
            business_name_clean = business_name.strip()
            conditions.append(
                f"""(
                    g.business_name ILIKE ${param_index}
                    OR similarity(g.business_name, ${param_index + 1}) >= 0.8
                )"""
            )
            values.append(f"%{business_name_clean}%")
            values.append(business_name_clean)
            param_index += 2

        if business_type and business_type.strip():
            conditions.append(f"g.business_type = ${param_index}")
            values.append(business_type.strip().upper())
            param_index += 1

        if registration_status and registration_status.strip():
            conditions.append(f"g.registration_status = ${param_index}")
            values.append(registration_status.strip().upper())
            param_index += 1

        if ownership_category and ownership_category.strip():
            conditions.append(f"g.ownership_category = ${param_index}")
            values.append(ownership_category.strip().upper())
            param_index += 1

        if state and state.strip():
            conditions.append(f"g.state = ${param_index}")
            values.append(state.strip().upper())
            param_index += 1

        if filing_preference and filing_preference.strip():
            conditions.append(f"g.filing_preference = ${param_index}")
            values.append(filing_preference.strip().upper())
            param_index += 1

        if has_service is not None:
            join_customer_services = True
            if has_service:
                conditions.append("cs.entity_id IS NOT NULL")
            else:
                conditions.append("cs.entity_id IS NULL")

        if is_active is not None:
            conditions.append(f"g.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("g.is_active = TRUE")

        if from_date:
            conditions.append(f"g.created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"g.created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY
        # --------------------------------------------------

        visibility_sql, visibility_values, param_index = build_gst_visibility(
            role,
            emp_id,
            param_index,
            DB_SCHEMA,
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # JOIN (FIXED DUPLICATE ISSUE)
        # --------------------------------------------------

        join_sql = ""
        if join_customer_services:
            join_sql = f"""
            LEFT JOIN (
                SELECT DISTINCT entity_id
                FROM {DB_SCHEMA}.customer_services
                WHERE entity_type = 'GST_REGISTRATION'
                  AND status = 'ACTIVE'
            ) cs ON cs.entity_id = g.id
            """

        count_sql = f"""
            SELECT COUNT(1)
              FROM {DB_SCHEMA}.gst_registration g
              {join_sql}
              {where_clause}
        """

        data_sql = f"""
            SELECT g.*,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name
              FROM {DB_SCHEMA}.gst_registration g
              LEFT JOIN {DB_SCHEMA}.employees e_rm
                     ON g.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_creator
                     ON g.created_by = e_creator.emp_id
              {join_sql}
              {where_clause}
             ORDER BY g.created_at DESC, g.id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total_count = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "GST filter success | returned=%s total=%s",
            len(rows),
            total_count,
        )

        return {
            "data": [dict(row) for row in rows],
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    except asyncpg.PostgresError as e:
        log.error(
            "Database error during GST filtering | error=%s",
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
        log.exception("Unexpected error during GST filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )


# -------------------------------------------------------------------
# CUSTOMER SNAPSHOT FOR GST (from customers.customer_id)
# -------------------------------------------------------------------
@router.get(
    "/customer/{customer_id}/fields",
    response_model=CustomerSnapshotForGstOut,
    summary="Get customer fields for GST registration",
    responses={
        200: {"description": "Customer fields returned."},
        400: {"description": "Customer inactive."},
        404: {"description": "Customer not found or not visible for current user."},
        500: {"description": "Database or internal error."},
    },
)
async def get_customer_fields_for_gst(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Returns `business_name`, `business_type`, `state`, `op_id`, `rm_id`, `mobile`
    from `customers` where `customers.customer_id` = `customer_id`.
    Visibility matches customer list (RM/OP/manager scoping).
    """
    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_customer_fields_for_gst"},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    vis_sql, vis_vals, _next_idx = build_customer_visibility(role_norm, emp_id, 2, DB_SCHEMA)
    values = [customer_id]
    where_extra = ""
    if vis_sql:
        where_extra = f" AND ({vis_sql})"
        values.extend(vis_vals)

    sql = f"""
        SELECT c.customer_id,
               c.business_name,
               c.business_type,
               c.state,
               c.op_id,
               c.rm_id,
               c.mobile,
               c.is_active
        FROM {DB_SCHEMA}.customers c
        WHERE c.customer_id = $1
        {where_extra}
        LIMIT 1
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *values)
    except asyncpg.PostgresError:
        log.exception("Database error fetching customer snapshot for GST")
        raise HTTPException(status_code=500, detail="Database error.")

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Customer not found or not accessible.",
        )

    if not row["is_active"]:
        raise HTTPException(status_code=400, detail="Customer is inactive.")

    return CustomerSnapshotForGstOut(
        customer_id=row["customer_id"],
        business_name=row["business_name"],
        business_type=row["business_type"],
        state=row["state"],
        op_id=row["op_id"],
        rm_id=row["rm_id"],
        mobile=row["mobile"],
    )


# -------------------------------------------------------------------
# EDIT GST REGISTRATION (Enterprise Production + Version Audit)
# -------------------------------------------------------------------
@router.post(
    "/{gst_id}/edit",
    summary="Edit GST Registration (Production Ready + Version Audit)",
    responses={
        200: {"description": "GST registration updated successfully."},
        400: {"description": "Validation failed or invalid reference."},
        404: {"description": "GST registration not found or inactive."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_gst_registration(
    gst_id: int,
    payload: GSTRegistrationEditIn,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    ✔ Dynamic update
    ✔ Only active GST can be updated
    ✔ ID-based architecture (no GSTIN cascade)
    ✔ Version audit
    ✔ DB constraint aligned
    ✔ Trigger-safe (approved_at controlled by DB)
    ✔ Concurrency safe (FOR UPDATE)
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_gst_registration"},
    )

    log.info("Incoming GST edit request | gst_id=%s", gst_id)

    # --------------------------------------------------
    # Extract Payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(status_code=400, detail="At least one field must be provided for update.")

    update_data.pop("approved_at", None)  # Never allow manual update

    # --------------------------------------------------
    # 🔥 ADDED (1): NORMALIZATION BEFORE DUPLICATE CHECK
    # --------------------------------------------------
    def normalize(k, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            if k in ["gstin", "pan"]:
                return v.upper()
            if k in ["email", "secondary_email"]:
                return v.lower()
        return v

    update_data = {k: normalize(k, v) for k, v in update_data.items()}

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing GST (ACTIVE ONLY + LOCK)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE id = $1
                       AND is_active = TRUE
                     FOR UPDATE
                    """,
                    gst_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found or inactive, First Activate the GST to edit",
                    )

                # --------------------------------------------------
                # Pre-validation (format + duplicates) for edit
                # --------------------------------------------------
                field_errors = {}

                gstin_value = update_data.get("gstin", old_row.get("gstin"))
                pan_value = update_data.get("pan", old_row.get("pan"))
                mobile_value = update_data.get("mobile", old_row.get("mobile"))
                username_value = update_data.get("username", old_row.get("username"))
                secondary_email_value = update_data.get("secondary_email", old_row.get("secondary_email"))

                if gstin_value:
                    gstin_value = gstin_value.strip().upper()
                if pan_value:
                    pan_value = pan_value.strip().upper()
                if mobile_value:
                    mobile_value = mobile_value.strip()
                if username_value:
                    username_value = username_value.strip()
                if secondary_email_value:
                    secondary_email_value = secondary_email_value.strip().lower()

                if gstin_value and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]", gstin_value):
                    field_errors["gstin"] = "Invalid GSTIN format."

                if pan_value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_value):
                    field_errors["pan"] = "Invalid PAN format."

                if mobile_value and not re.fullmatch(r"[0-9]{10}", mobile_value):
                    field_errors["mobile"] = "Invalid mobile number format."

                if secondary_email_value:
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", secondary_email_value):
                        field_errors["secondary_email"] = "Invalid secondary email format."

                if gstin_value and pan_value:
                    gstin_pan = gstin_value[2:12]
                    if gstin_pan != pan_value:
                        field_errors["pan"] = "PAN does not match GSTIN."

                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT
                        CASE
                            WHEN $1::text IS NULL OR trim($1::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE id <> $5
                                   AND gstin IS NOT NULL
                                   AND upper(trim(gstin)) = upper(trim($1::text))
                            )
                        END AS gstin_match,
                        CASE
                            WHEN $2::text IS NULL OR trim($2::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE id <> $5
                                   AND username IS NOT NULL
                                   AND lower(trim(username)) = lower(trim($2::text))
                            )
                        END AS username_match,
                        CASE
                            WHEN $3::text IS NULL OR trim($3::text) = '' OR $4::text IS NULL OR trim($4::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE id <> $5
                                   AND is_active = TRUE
                                   AND upper(trim(gstin)) = upper(trim($3::text))
                                   AND mobile = trim($4::text)
                            )
                        END AS gstin_mobile_match
                    """,
                    gstin_value,
                    username_value,
                    gstin_value,
                    mobile_value,
                    gst_id,
                )

                has_duplicate = False
                if duplicate_row:
                    if duplicate_row["gstin_match"]:
                        field_errors["gstin"] = "GSTIN already exists."
                        has_duplicate = True
                    if duplicate_row["username_match"]:
                        field_errors["username"] = "Username already exists."
                        has_duplicate = True

                if field_errors:
                    raise HTTPException(
                        status_code=409 if has_duplicate else 400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                            }
                        },
                    )

                # --------------------------------------------------
                # 🔥 ADDED (2): SAFE NO CHANGE CHECK
                # --------------------------------------------------
                no_change = True
                for k, v in update_data.items():
                    if k in old_row and str(old_row[k]).strip() != str(v).strip():
                        no_change = False
                        break

                if no_change:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "No changes detected to update.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 3️⃣ Dynamic Update
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")
                values.append(gst_id)

                sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET {', '.join(fields)}
                     WHERE id = ${idx}
                       AND is_active = TRUE
                     RETURNING *
                """

                new_row = await conn.fetchrow(sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="GST state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id,
                     action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "GST_REGISTRATION",
                    new_row["id"],
                    new_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

                await _sync_crm_lead_with_gst(
                    conn,
                    new_row,
                )

                log.info(
                    "GST updated successfully | gst_id=%s | fields=%s",
                    gst_id,
                    list(update_data.keys()),
                )

                return {
                    **dict(new_row),
                    "message": "GST registration updated successfully.",
                    "request_id": request_id,
                }

        # --------------------------------------------------
        # UNIQUE CONSTRAINTS
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                "gst_registration_gstin_key": ("gstin", "GSTIN already exists."),
                "uq_gst_username_lower": ("username", "Username already exists."),
                "uq_gst_gstin_mobile_active": ("mobile", "Mobile already assigned to an active GST."),
            }

            field, message = UNIQUE_MAP.get(
                constraint,
                ("non_field_error", "Duplicate value violates unique constraint.")
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Invalid foreign key reference provided.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_gst_format": ("gstin", "Invalid GSTIN format."),
                "chk_pan_format": ("pan", "Invalid PAN format."),
                "chk_mobile_format": ("mobile", "Invalid mobile number format."),
                "chk_secondary_email_format": ("secondary_email", "Invalid secondary email format."),
                "chk_gstin_pan_match": ("pan", "PAN does not match GSTIN."),
                "chk_approved_logic": ("registration_status", "Invalid approved status logic."),
            }

            field, message = CHECK_MAP.get(
                constraint,
                ("non_field_error", f"Data violates constraint: {constraint}")
            )

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(status_code=400, detail="Missing required field value.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format provided.")

        except asyncpg.PostgresError:
            log.exception("Database error during GST update")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST update")
            raise HTTPException(status_code=500, detail="Internal server error.")

@router.delete(
    "/{gst_id}/soft_delete",
    summary="Soft delete GST registration (Enterprise + Cascade + Audit)",
    responses={
        200: {"description": "GST registration soft deleted successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "GST registration not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_gst_registration(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "soft_delete_gst_registration",
        },
    )

    log.info("Incoming soft delete GST | gst_id=%s", gst_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing GST (LOCK)
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE id = $1
                     FOR UPDATE
                    """,
                    gst_id,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                if gst_row["is_active"] is False:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration already inactive.confirm associated persons and docs are inactivate state or not.",
                    )

                # --------------------------------------------------
                # 2️⃣ Soft Delete GST
                # --------------------------------------------------
                deleted_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = TRUE
                     RETURNING *
                    """,
                    gst_id,
                )

                if not deleted_gst:
                    raise HTTPException(
                        status_code=400,
                        detail="Unable to deactivate GST registration.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Soft Delete Persons
                # --------------------------------------------------
                deleted_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE gst_registration_id = $1
                       AND is_active = TRUE
                     RETURNING person_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 4️⃣ Cascade Soft Delete Documents
                # --------------------------------------------------
                deleted_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons p
                     WHERE d.person_id = p.person_id
                       AND p.gst_registration_id = $1
                       AND d.is_active = TRUE
                     RETURNING d.document_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 5️⃣ CUSTOMER SERVICE SYNC
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET status = 'INACTIVE'
                     WHERE entity_type = 'GST_REGISTRATION'
                       AND entity_id = $1
                    """,
                    gst_id,
                )

                await _sync_crm_lead_with_gst(conn, deleted_gst)

                # --------------------------------------------------
                # 6️⃣ Version Audit (GST ONLY)
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
                    "GST_REGISTRATION",
                    deleted_gst["id"],
                    deleted_gst["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            log.info(
                "GST soft deleted successfully | gst_id=%s | persons_deactivated=%s | documents_deactivated=%s",
                gst_id,
                len(deleted_persons),
                len(deleted_documents),
            )

            return {
                **dict(deleted_gst),
                "persons_deactivated_count": len(deleted_persons),
                "documents_deactivated_count": len(deleted_documents),
                "message": "GST registration soft deleted successfully. "
                           "All associated persons and documents deactivated.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK constraint error")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Postgres error during GST soft delete")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")

@router.post(
    "/{gst_id}/activate",
    summary="Activate GST Registration (Production Ready + Audit + Cascade)",
    responses={
        200: {"description": "GST registration activated successfully."},
        400: {"description": "Validation failed or already active."},
        404: {"description": "GST registration not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_gst_registration(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_gst_registration",
        },
    )

    log.info("Incoming GST activation | gst_id=%s", gst_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch GST + Customer Status (LOCK)
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gst.*, c.is_active AS customer_active
                      FROM {DB_SCHEMA}.gst_registration gst
                      JOIN {DB_SCHEMA}.customers c
                        ON gst.customer_id = c.customer_id
                     WHERE gst.id = $1
                     FOR UPDATE
                    """,
                    gst_id,
                )

                if not gst_row:
                    raise HTTPException(404, "GST registration not found.")

                if gst_row["is_active"]:
                    raise HTTPException(400, "GST registration already active.")

                if not gst_row["customer_active"]:
                    raise HTTPException(
                        400,
                        "Cannot activate GST: associated customer is inactive.",
                    )

                customer_id = gst_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Activate GST
                # --------------------------------------------------
                activated_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    gst_id,
                )

                if not activated_gst:
                    raise HTTPException(
                        409,
                        "GST state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Activate Persons
                # --------------------------------------------------
                activated_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE gst_registration_id = $1
                       AND is_active = FALSE
                     RETURNING person_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 4️⃣ Cascade Activate Documents
                # --------------------------------------------------
                activated_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = TRUE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons p
                     WHERE d.person_id = p.person_id
                       AND p.gst_registration_id = $1
                       AND d.is_active = FALSE
                     RETURNING d.document_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 5️⃣ CUSTOMER SERVICE SYNC
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET status = 'ACTIVE'
                     WHERE entity_type = 'GST_REGISTRATION'
                       AND entity_id = $1
                       AND status = 'INACTIVE'
                    """,
                    gst_id,
                )

                await _sync_crm_lead_with_gst(conn, activated_gst)

                # --------------------------------------------------
                # 6️⃣ Version Audit
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
                    "GST_REGISTRATION",
                    activated_gst["id"],
                    customer_id,
                    "ACTIVATE",
                    None,
                    None,
                )

            log.info(
                "GST activated successfully | gst_id=%s | persons_activated=%s | documents_activated=%s",
                gst_id,
                len(activated_persons),
                len(activated_documents),
            )

            return {
                **dict(activated_gst),
                "persons_activated_count": len(activated_persons),
                "documents_activated_count": len(activated_documents),
                "message": "GST registration activated successfully. "
                           "All associated persons and documents activated.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK ERROR")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Database error during GST activation")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST activation")
            raise HTTPException(status_code=500, detail="Internal server error.")