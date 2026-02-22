import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime
from app.gst_registration.schemas import GSTRegistrationIn, GSTRegistrationEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.security.rbac import require_permission
from app.logger import logger
from zoneinfo import ZoneInfo
import json
import uuid
from datetime import datetime

router = APIRouter(
    prefix="/api/v1/gst-registrations",
    tags=["GST Registration"]
)

# -------------------------------------------------------------------
# CREATE GST REGISTRATION (Production Standard + Version Audit + IST)
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
    """
    Create GST Registration
    -----------------------
    ✔ Atomic transaction (GST + Version)
    ✔ DB-level validation (PAN-GST match, approved logic)
    ✔ Username uniqueness (case-insensitive)
    ✔ Trigger handles approved_at
    ✔ Enterprise-grade structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming GST create request | customer_id=%s | username=%s",
        payload.customer_id,
        payload.username,
    )

    # --------------------------------------------------
    # IST Timestamp
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

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
                # 1️⃣ Validate Customer Exists & Active
                # --------------------------------------------------
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
                    raise HTTPException(
                        status_code=400,
                        detail="Customer not found.",
                    )

                if not customer_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Customer is inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Insert GST Registration
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.gst_registration (
                        customer_id,
                        username,
                        password,
                        pan,
                        gstin,
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
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,
                        $20,$21,$22,$23
                    )
                    RETURNING *
                """

                gst_row = await conn.fetchrow(
                    insert_sql,
                    payload.customer_id,
                    payload.username,
                    payload.password,   # assume already hashed before call
                    payload.pan,
                    payload.gstin,
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
                    payload.is_active,
                    payload.mobile,
                    payload.email,
                    payload.secondary_email,
                    payload.created_by or emp_id,
                    payload.rm_id,
                    now,
                    now,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=500,
                        detail="GST registration creation failed.",
                    )

                # --------------------------------------------------
                # 3️⃣ Insert Version Audit
                # --------------------------------------------------
                version_sql = f"""
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
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "GST_REGISTRATION",
                    4,
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(gst_row), default=str),
                    None,
                )

            log.info(
                "GST registration created successfully | gst_id=%s",
                gst_row["id"],
            )

            return {
                **dict(gst_row),
                "message": "GST registration created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "gst_registration_gstin_key": "GSTIN already exists.",
                "uq_gst_username_lower": "Username already exists.",
                "uq_gst_pan_gstin": "PAN and GSTIN combination already exists.",
                "uq_gst_gstin_mobile_active": "Mobile already used for this GST (active).",
                }

            log.warning(
                "Unique constraint violation | constraint=%s",
                constraint,
                exc_info=True,
            )

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        # --------------------------------------------------
        # CHECK CONSTRAINT
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_gst_format": "Invalid GSTIN format.",
                "chk_pan_format": "Invalid PAN format.",
                "chk_mobile_format": "Invalid mobile number format.",
                "chk_secondary_email_format": "Invalid secondary email format.",
                "chk_gstin_pan_match": "PAN does not match GSTIN.",
                "chk_approved_logic": "Invalid approved status logic.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # GENERAL DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError as e:
            log.error("Database error | %s", str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST creation")
            raise HTTPException(status_code=500, detail="Internal server error.")
# -------------------------------------------------------------------
# LIST GST REGISTRATIONS (DYNAMIC FILTER + PAGINATION)
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
    customer_id: Optional[int] = None,
    gstin: Optional[str] = None,
    mobile: Optional[str] = None,
    email: Optional[str] = None,
    secondary_email: Optional[str] = None,
    rm_id: Optional[int] = None,
    business_type: Optional[str] = None,
    registration_status: Optional[str] = None,
    ownership_category: Optional[str] = None,
    state: Optional[str] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Enterprise Grade GST Filtering

    ✔ Fully index aligned
    ✔ Trim + case-safe filtering
    ✔ Deterministic ordering
    ✔ Pagination metadata returned
    ✔ Structured logging
    ✔ Total count for UI
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = str(uuid.uuid4())
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming GST filter | limit=%s offset=%s",
        limit,
        offset,
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
        # Indexed Exact Match Filters
        # --------------------------------------------------

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gstin and gstin.strip():
            conditions.append(f"upper(gstin) = ${param_index}")
            values.append(gstin.strip().upper())
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        if email and email.strip():
            conditions.append(f"lower(email) = ${param_index}")
            values.append(email.strip().lower())
            param_index += 1

        if secondary_email and secondary_email.strip():
            conditions.append(f"lower(secondary_email) = ${param_index}")
            values.append(secondary_email.strip().lower())
            param_index += 1

        if rm_id is not None:
            conditions.append(f"rm_id = ${param_index}")
            values.append(rm_id)
            param_index += 1

        # --------------------------------------------------
        # Uppercase Stored Business Fields
        # --------------------------------------------------

        if business_type and business_type.strip():
            conditions.append(f"business_type = ${param_index}")
            values.append(business_type.strip().upper())
            param_index += 1

        if registration_status and registration_status.strip():
            conditions.append(f"registration_status = ${param_index}")
            values.append(registration_status.strip().upper())
            param_index += 1

        if ownership_category and ownership_category.strip():
            conditions.append(f"ownership_category = ${param_index}")
            values.append(ownership_category.strip().upper())
            param_index += 1

        if state and state.strip():
            conditions.append(f"state = ${param_index}")
            values.append(state.strip().upper())
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern (Enterprise Standard)
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filtering
        # --------------------------------------------------

        if from_date:
            conditions.append(f"created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )

        # --------------------------------------------------
        # Queries
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.gst_registration
              {where_clause}
        """

        data_sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.gst_registration
              {where_clause}
             ORDER BY created_at DESC, id DESC
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
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "returned": len(rows),
            },
            "request_id": request_id,
            "message": "GST registrations filtered successfully.",
        }

    # --------------------------------------------------
    # Database Exception Handling
    # --------------------------------------------------

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
# EDIT GST REGISTRATION (Enterprise Production + Version Audit)
# -------------------------------------------------------------------
@router.post(
    "/{gstin}/edit",
    summary="Edit GST Registration (Production Ready + Version Audit)",
    responses={
        200: {"description": "GST registration updated successfully."},
        400: {"description": "Validation failed or invalid reference."},
        404: {"description": "GST registration not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_gst_registration(
    gstin: str,
    payload: GSTRegistrationEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    ✔ Dynamic update
    ✔ Strict normalization
    ✔ Version audit
    ✔ DB constraint aligned
    ✔ Trigger-safe (approved_at controlled by DB)
    ✔ Unique constraint mapped precisely
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    normalized_gstin = gstin.strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_gst_registration",
        },
    )

    log.info("Incoming GST edit request | gstin=%s", normalized_gstin)

    # --------------------------------------------------
    # Extract Update Data
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # 🚫 Never allow manual approved_at manipulation
    update_data.pop("approved_at", None)

    # --------------------------------------------------
    # Strict Normalization (Aligned with DB Indexes)
    # --------------------------------------------------
    try:
        upper_fields = [
            "gstin",
            "pan",
            "business_type",
            "registration_type",
            "turnover_details",
            "registration_status",
            "ownership_category",
            "state",
        ]

        lower_fields = [
            "email",
            "secondary_email",
        ]

        for field in upper_fields:
            if field in update_data and update_data[field]:
                update_data[field] = update_data[field].strip().upper()

        for field in lower_fields:
            if field in update_data and update_data[field]:
                update_data[field] = update_data[field].strip().lower()

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "username" in update_data and update_data["username"]:
            update_data["username"] = update_data["username"].strip()

    except Exception:
        log.exception("Normalization failed")
        raise HTTPException(
            status_code=400,
            detail="Invalid field values provided.",
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

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing Record
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE upper(gstin) = $1
                     LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                # --------------------------------------------------
                # 2️⃣ Build Dynamic Update
                # --------------------------------------------------
                fields = []
                values = []
                param_index = 1

                for field_name, value in update_data.items():
                    fields.append(f"{field_name} = ${param_index}")
                    values.append(value)
                    param_index += 1

                fields.append("updated_at = NOW()")

                sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET {', '.join(fields)}
                     WHERE upper(gstin) = ${param_index}
                     RETURNING *
                """

                values.append(normalized_gstin)

                new_row = await conn.fetchrow(sql, *values)

                # --------------------------------------------------
                # 3️⃣ Version Audit
                # --------------------------------------------------
                version_sql = f"""
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
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "GST_REGISTRATION",
                    4,
                    new_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "GST updated successfully | gstin=%s | fields=%s",
                normalized_gstin,
                list(update_data.keys()),
            )

            return {
                **dict(new_row),
                "message": "GST registration updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Unique Constraint Mapping
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "") or ""

            UNIQUE_MAP = {
                "gst_registration_gstin_key": "GSTIN already exists.",
                "gst_registration_username_key": "Username already exists.",
                "uq_gst_username_lower": "Username already exists (case insensitive).",
                "uq_gst_gstin_mobile_active": "Mobile already assigned to an active GST.",
                "uq_gst_pan_gstin": "PAN and GSTIN combination already exists.",
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    "Duplicate field value violates unique constraint.",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference provided.",
            )

        # --------------------------------------------------
# CHECK CONSTRAINT HANDLING (DETAILED)
# --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)
            CHECK_MAP = {
                "chk_gst_format":"Invalid GSTIN format.",
                "chk_pan_format":"Invalid PAN format. Expected format: ABCDE1234F.",
                "chk_mobile_format":"Invalid mobile number format. Must be 10 digits.",
                "chk_secondary_email_format":"Invalid secondary email format.",
                "chk_gstin_pan_match":"PAN does not match GSTIN. PAN must match characters 3–12 of GSTIN.",
                "chk_approved_logic":"Invalid approved status logic. If status is APPROVED, approved_at must be set. Otherwise it must be NULL.",
                }
            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                    ),
                    )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )  
# =========================================================
# SOFT DELETE GST REGISTRATION (Enterprise + Version Audit)
# =========================================================

@router.delete(
    "/{gstin}/soft_delete",
    summary="Soft delete GST registration (Production Ready + Audit)",
    responses={
        200: {"description": "GST registration soft deleted successfully."},
        400: {"description": "Validation failed or already inactive."},
        404: {"description": "GST registration not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_gst_registration(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    ✔ Atomic transaction (Soft Delete + Version Insert)
    ✔ Concurrency safe (AND is_active = TRUE)
    ✔ Case-insensitive GSTIN match
    ✔ json = NULL (for DELETE)
    ✔ updated_json = NEW snapshot
    ✔ Structured logging
    ✔ Full exception mapping
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    normalized_gstin = gstin.strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "soft_delete_gst_registration",
        },
    )

    log.info("Incoming soft delete GST request | gstin=%s", normalized_gstin)

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
                # 1️⃣ Soft Delete (Concurrency Safe)
                # --------------------------------------------------
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = TRUE
                     RETURNING *
                """

                deleted_row = await conn.fetchrow(delete_sql, normalized_gstin)

                # --------------------------------------------------
                # If nothing updated → check existence
                # --------------------------------------------------
                if not deleted_row:
                    existing_row = await conn.fetchrow(
                        f"""
                        SELECT gstin, is_active
                          FROM {DB_SCHEMA}.gst_registration
                         WHERE upper(gstin) = $1
                        """,
                        normalized_gstin,
                    )

                    if not existing_row:
                        log.warning("GST registration not found")
                        raise HTTPException(
                            status_code=404,
                            detail="GST registration not found.",
                        )

                    if existing_row["is_active"] is False:
                        log.warning("GST already inactive")
                        raise HTTPException(
                            status_code=400,
                            detail="GST registration already inactive.",
                        )

                # --------------------------------------------------
                # 2️⃣ Version Audit Insert
                # --------------------------------------------------
                version_sql = f"""
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
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "GST_REGISTRATION",
                    4,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_row), default=str),
                )

            log.info(
                "GST soft deleted successfully | gstin=%s",
                normalized_gstin,
            )

            return {
                **dict(deleted_row),
                "message": "GST registration soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Database Exception Mapping
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(
                status_code=400,
                detail="Constraint validation failed.",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST soft delete")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST soft delete")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )