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
    Create GST Registration (Production Standard + Version Audit)

    ✔ Atomic transaction (GST + Version)
    ✔ entity_type = 'GST_REGISTRATION'
    ✔ entity_id = 4
    ✔ action = 'CREATE'
    ✔ json populated
    ✔ updated_json = NULL
    ✔ IST timezone safe
    ✔ Structured logging
    ✔ Precise unique constraint mapping
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

    # --------------------------------------------------
    # IST Time
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # Normalize Fields (STRICT NORMALIZATION)
    # --------------------------------------------------
    username = payload.username.strip()
    pan = payload.pan.strip().upper()
    gstin = payload.gstin.strip().upper() if payload.gstin else None
    email = payload.email.strip().lower() if payload.email else None
    secondary_email = payload.secondary_email.strip().lower() if payload.secondary_email else None
    mobile = payload.mobile.strip() if payload.mobile else None

    log.info(
        "Incoming GST create request | customer_id=%s username=%s",
        payload.customer_id,
        username,
    )

    # --------------------------------------------------
    # Database Pool
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
                    log.warning("Customer not found")
                    raise HTTPException(
                        status_code=400,
                        detail="Customer not found.",
                    )

                if customer_row["is_active"] is False:
                    log.warning("Customer inactive")
                    raise HTTPException(
                        status_code=400,
                        detail="Customer is inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Insert GST Registration
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.gst_registration (
                        customer_id, username, password, pan,
                        registration_type, ownership_category,
                        business_type, state, turnover_details,
                        created_by, rm_id, gstin,
                        registration_status, is_filing_needed,
                        mobile, is_active, email,
                        secondary_email, created_at, updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                        'DRAFT',$13,$14,$15,$16,$17,$18,$19
                    )
                    RETURNING *
                """

                gst_row = await conn.fetchrow(
                    insert_sql,
                    payload.customer_id,
                    username,
                    payload.password,
                    pan,
                    payload.registration_type,
                    payload.ownership_category,
                    payload.business_type,
                    payload.state,
                    payload.turnover_details,
                    payload.created_by or emp_id,
                    payload.rm_id,
                    gstin,
                    payload.is_filing_needed,
                    mobile,
                    payload.is_active,
                    email,
                    secondary_email,
                    now,
                    now,
                )

                if not gst_row:
                    log.error("GST registration creation failed")
                    raise HTTPException(
                        status_code=500,
                        detail="GST registration creation failed.",
                    )

                gst_id = gst_row["id"]

                # --------------------------------------------------
                # 3️⃣ Insert Version Audit
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
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(gst_row), default=str),
                    None,
                )

            log.info(
                "GST registration created successfully | gst_id=%s",
                gst_id,
            )

            response_data = dict(gst_row)
            response_data["message"] = "GST registration created successfully."
            response_data["request_id"] = request_id

            return response_data

        # --------------------------------------------------
        # UNIQUE CONSTRAINT MAPPING (PRECISE)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:

            constraint_name = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "gst_registration_gstin_key": "GSTIN already exists.",
                "gst_registration_username_key": "Username already exists.",
                "uq_gst_mobile_active": "Mobile number already in use by an active GST registration.",
                "uq_gst_secondary_email_active": "Secondary email already in use by an active GST registration.",
                "uq_gst_pan_gstin": "PAN and GSTIN combination already exists.",
            }

            log.warning(
                "Unique constraint violation | constraint=%s",
                constraint_name,
                exc_info=True,
            )

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint_name,
                    f"Duplicate value violates constraint: {constraint_name}",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference")
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference provided.",
            )

        # --------------------------------------------------
        # CHECK VIOLATION
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:
            log.warning("Check constraint violation", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail="Invalid data format (PAN/GSTIN/Mobile/Email validation failed).",
            )

        # --------------------------------------------------
        # GENERAL DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError as e:
            log.error(
                "Database error during GST creation | error=%s",
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST creation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
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
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Enterprise Grade Dynamic GST Filtering
    Fully Index Optimized
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming GST filter request | limit=%s offset=%s",
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
        # ENUM / UPPERCASE STORED FIELDS
        # --------------------------------------------------

        if business_type and business_type.strip():
            conditions.append(f"business_type = ${param_index}")
            values.append(business_type.strip().upper())
            param_index += 1

        if registration_status and registration_status.strip():
            conditions.append(f"registration_status = ${param_index}")
            values.append(registration_status.strip().upper())
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Logic (Enterprise Pattern)
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Range Filtering
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

        sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.gst_registration
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info(
            "GST registrations filtered successfully | count=%s",
            len(rows),
        )

        return [
            {
                **dict(row),
                "message": "GST registrations filtered successfully.",
                "request_id": request_id,
            }
            for row in rows
        ]

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
# EDIT GST REGISTRATION (Dynamic Update - Production Ready + Version Audit)
# -------------------------------------------------------------------
@router.post(
    "/{gstin}/edit",
    summary="Edit GST Registration (Dynamic Update - Production Ready)",
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

    # --------------------------------------------------
    # Request Context & Logging
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
    # Extract Dynamic Update Data
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Failed to serialize payload | gstin=%s", normalized_gstin)
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Normalize Critical Fields (Aligned with DB Indexes)
    # --------------------------------------------------
    try:
        if "gstin" in update_data and update_data["gstin"]:
            update_data["gstin"] = update_data["gstin"].strip().upper()

        if "pan" in update_data and update_data["pan"]:
            update_data["pan"] = update_data["pan"].strip().upper()

        if "email" in update_data and update_data["email"]:
            update_data["email"] = update_data["email"].strip().lower()

        if "secondary_email" in update_data and update_data["secondary_email"]:
            update_data["secondary_email"] = update_data["secondary_email"].strip().lower()

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "username" in update_data and update_data["username"]:
            update_data["username"] = update_data["username"].strip()

        # Uppercase business classification fields (as per your storage design)
        for field in ["business_type", "registration_type", "turnover_details", "registration_status"]:
            if field in update_data and update_data[field]:
                update_data[field] = update_data[field].strip().upper()

    except Exception:
        log.exception("Field normalization failed | gstin=%s", normalized_gstin)
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
                # 1️⃣ Fetch OLD Snapshot
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
                # 2️⃣ Build Dynamic SET Clause
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
        # Precise Exception Mapping
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "") or ""

            if "gst_registration_gstin_key" in constraint:
                detail = "GSTIN already exists."
            elif "gst_registration_username_key" in constraint:
                detail = "Username already exists."
            elif "uq_gst_mobile_active" in constraint:
                detail = "Mobile number already assigned to another active GST."
            elif "uq_gst_secondary_email_active" in constraint:
                detail = "Secondary email already assigned to another active GST."
            elif "uq_gst_pan_gstin" in constraint:
                detail = "PAN and GSTIN combination already exists."
            else:
                detail = "Duplicate field value violates unique constraint."

            raise HTTPException(status_code=409, detail=detail)

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference provided.",
            )

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed (invalid format).",
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
# SOFT DELETE GST REGISTRATION (is_active = false) WITH VERSION AUDIT
# =========================================================

@router.delete(
    "/{gstin}/soft_delete",
    summary="Soft delete GST registration (With Audit)",
)
async def soft_delete_gst_registration(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft Delete GST Registration with Version Audit

    ✔ Atomic transaction (Soft Delete + Version Insert)
    ✔ Concurrency safe (AND is_active = TRUE)
    ✔ json = NULL (for DELETE)
    ✔ updated_json = NEW snapshot (is_active = FALSE)
    ✔ action = 'DELETE'
    ✔ Enterprise structured logging
    ✔ Full asyncpg exception handling
    """

    # --------------------------------------------------
    # Request Context & Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "soft_delete_gst",
        },
    )

    log.info(
        "Incoming soft delete GST request | gstin=%s",
        gstin,
    )

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception("Database pool acquisition failed | error=%s", str(e))
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Perform Soft Delete (Concurrency Safe)
                # --------------------------------------------------
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE gstin = $1
                       AND is_active = TRUE
                     RETURNING *
                """

                deleted_row = await conn.fetchrow(delete_sql, gstin)

                if not deleted_row:
                    # Check existence separately
                    check_row = await conn.fetchrow(
                        f"""
                        SELECT gstin, is_active
                          FROM {DB_SCHEMA}.gst_registration
                         WHERE gstin = $1
                        """,
                        gstin,
                    )

                    if not check_row:
                        log.warning("GST registration not found | gstin=%s", gstin)
                        raise HTTPException(
                            status_code=404,
                            detail="GST registration not found.",
                        )

                    log.warning(
                        "GST registration already inactive | gstin=%s",
                        gstin,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration already inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Insert Version Audit (DELETE)
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

                deleted_snapshot = dict(deleted_row)

                await conn.execute(
                    version_sql,
                    emp_id,
                    "GST_REGISTRATION",               # entity_type
                    4,                                # your GST entity_id
                    deleted_row["customer_id"],       # reference customer
                    "DELETE",
                    None,                             # json must be NULL
                    json.dumps(deleted_snapshot, default=str),
                )

            log.info(
                "GST soft deleted successfully with audit | gstin=%s",
                gstin,
            )

            return {
                **dict(deleted_row),
                "message": "GST registration soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # FULL DATABASE EXCEPTION COVERAGE
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.error(
                "Foreign key violation during GST soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.error(
                "Audit constraint violation during GST soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Audit constraint validation failed.",
            )

        except asyncpg.exceptions.DataError as e:
            log.error(
                "Data error during GST soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during GST soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except HTTPException:
            raise

        except Exception as e:
            log.exception(
                "Unexpected error during GST soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

