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
    ✔ entity_id = 4 (default)
    ✔ action = 'CREATE'
    ✔ json populated
    ✔ updated_json = NULL
    ✔ IST timezone safe
    ✔ Structured logging
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
    # IST Time (TIMESTAMPTZ SAFE)
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # Normalize Fields
    # --------------------------------------------------
    username = payload.username.strip() if payload.username else None
    email = payload.email.strip().lower() if payload.email else None
    secondary_email = payload.secondary_email.strip().lower() if payload.secondary_email else None
    mobile = payload.mobile.strip() if payload.mobile else None

    log.info(
        "Incoming GST create request | customer_id=%s username=%s",
        payload.customer_id,
        username,
    )

    # --------------------------------------------------
    # Database Pool Acquisition
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
                exists = await conn.fetchrow(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                      AND mobile = $2
                      AND is_active = TRUE
                    LIMIT 1
                    """,
                    payload.customer_id,
                    mobile,
                )

                if not exists:
                    log.warning("Customer not found for GST registration")
                    raise HTTPException(
                        status_code=400,
                        detail="Customer not found with given customer_id and mobile.",
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
                    payload.password,  # stored as requested
                    payload.pan,
                    payload.registration_type,
                    payload.ownership_category,
                    payload.business_type,
                    payload.state,
                    payload.turnover_details,
                    payload.created_by or emp_id,
                    payload.rm_id,
                    payload.gstin,
                    payload.is_filing_needed,
                    mobile,
                    payload.is_active,
                    email,
                    secondary_email,
                    now,
                    now,
                )

                if not gst_row:
                    log.error("GST registration creation failed - no row returned")
                    raise HTTPException(
                        status_code=500,
                        detail="GST registration creation failed.",
                    )

                gst_id = gst_row["id"]

                # --------------------------------------------------
                # 3️⃣ Insert Version Audit (INLINE)
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
                    4,  # entity_id for GST
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(gst_row), default=str),
                    None,
                )

            log.info(
                "GST registration created successfully with audit | gst_id=%s",
                gst_id,
            )

            response_data = dict(gst_row)
            response_data["message"] = "GST registration created successfully."
            response_data["request_id"] = request_id

            return response_data

        # --------------------------------------------------
        # Exception Handling (Production Grade)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate GST detected (GSTIN/Username)")
            raise HTTPException(
                status_code=409,
                detail="GSTIN or Username already exists.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference during GST creation")
            raise HTTPException(
                status_code=400,
                detail="Invalid reference provided.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during GST creation | error=%s",
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error.",
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
    Filter GST Registrations (Production Standard)

    Validation Responsibility:
    --------------------------
    1. FastAPI: Type + pagination validation
    2. DB: Filtering logic
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming GST filter request limit=%s offset=%s", limit, offset)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    try:
        pool = await get_db_pool()

        conditions = []
        values = []
        param_index = 1

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gstin and gstin.strip():
            conditions.append(f"gstin ILIKE ${param_index}")
            values.append(f"%{gstin.strip()}%")
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        if email and email.strip():
            conditions.append(f"email ILIKE ${param_index}")
            values.append(f"%{email.strip()}%")
            param_index += 1

        if secondary_email and secondary_email.strip():
            conditions.append(f"secondary_email ILIKE ${param_index}")
            values.append(f"%{secondary_email.strip()}%")
            param_index += 1

        if rm_id is not None:
            conditions.append(f"rm_id = ${param_index}")
            values.append(rm_id)
            param_index += 1

        if business_type:
            conditions.append(f"business_type = ${param_index}")
            values.append(business_type)
            param_index += 1

        if registration_status:
            conditions.append(f"registration_status = ${param_index}")
            values.append(registration_status)
            param_index += 1

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        if from_date:
            conditions.append(f"created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

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

        log.info("GST registrations filtered successfully count=%s", len(rows))

        return [
            {**dict(row), "message": "GST registrations filtered successfully."}
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error during GST filtering")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error during GST filtering")
        raise HTTPException(status_code=500, detail="Internal server error.")

# -------------------------------------------------------------------
# GET GST REGISTRATION BY GSTIN
# -------------------------------------------------------------------
@router.get(
    "/{gstin}/single_filter",
    summary="Get GST Registration",
    responses={
        200: {"description": "GST registration details."},
        404: {"description": "GST registration not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_gst_registration(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get GST Registration by GSTIN (Production Standard)

    Validation Responsibility Split:
    --------------------------------
    1. Authentication & Authorization via dependency
    2. Path param type validation handled by FastAPI
    3. Existence validation handled by DB query
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming get GST request gstin=%s",
        gstin,
    )

    # --------------------------------------------------
    # SQL Query Definition
    # --------------------------------------------------
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.gst_registration
         WHERE gstin = $1
         LIMIT 1
    """

    # --------------------------------------------------
    # Database Pool Acquisition Safety
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
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, gstin)

        # --------------------------------------------------
        # Not Found Handling
        # --------------------------------------------------
        if not row:
            log.warning(
                "GST registration not found gstin=%s",
                gstin,
            )
            raise HTTPException(
                status_code=404,
                detail="GST registration not found.",
            )

        log.info(
            "GST registration fetched successfully gstin=%s",
            gstin,
        )

        return {
            **dict(row),
            "message": "GST registration fetched successfully.",
            "request_id": request_id,
        }

    # --------------------------------------------------
    # IMPORTANT: Re-raise HTTP Exceptions First
    # --------------------------------------------------
    except HTTPException:
        raise

    # --------------------------------------------------
    # DATABASE ERROR HANDLING (Production Grade)
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during get GST gstin=%s error=%s",
            gstin,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    # --------------------------------------------------
    # FALLBACK UNEXPECTED ERROR (WITH STACK TRACE)
    # --------------------------------------------------
    except Exception:
        log.exception(
            "Unexpected error during get GST gstin=%s",
            gstin,
        )
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
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    # Safe emp_id conversion for version table
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_gst",
        },
    )

    log.info("Incoming edit GST request | gstin=%s", gstin)

    # --------------------------------------------------
    # Extract Only Provided Fields (Dynamic Update)
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception as e:
        log.exception(
            "Failed to serialize GST payload | gstin=%s | error=%s",
            gstin,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        log.warning("No fields provided for update | gstin=%s", gstin)
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Normalize Critical Fields
    # --------------------------------------------------
    try:
        if "email" in update_data and update_data["email"]:
            update_data["email"] = update_data["email"].strip().lower()

        if "secondary_email" in update_data and update_data["secondary_email"]:
            update_data["secondary_email"] = update_data["secondary_email"].strip().lower()

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "username" in update_data and update_data["username"]:
            update_data["username"] = update_data["username"].strip()

    except Exception as e:
        log.exception(
            "Error during GST field normalization | gstin=%s | payload=%s | error=%s",
            gstin,
            update_data,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid field values provided.",
        )

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception(
            "Database pool acquisition failed | gstin=%s | error=%s",
            gstin,
            str(e),
        )
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
                     WHERE gstin = $1
                     LIMIT 1
                    """,
                    gstin,
                )

                if not old_row:
                    log.warning("GST registration not found for update | gstin=%s", gstin)
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
                     WHERE gstin = ${param_index}
                     RETURNING *
                """

                values.append(gstin)

                log.debug(
                    "Executing GST update query | gstin=%s | fields=%s",
                    gstin,
                    list(update_data.keys()),
                )

                new_row = await conn.fetchrow(sql, *values)

                # --------------------------------------------------
                # 3️⃣ Insert Version Audit (GST)
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
                    4,  # Your GST entity_id
                    new_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "GST updated successfully with audit | gstin=%s | updated_fields=%s",
                gstin,
                list(update_data.keys()),
            )

            return {
                **dict(new_row),
                "message": "GST registration updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # FULL DATABASE EXCEPTION COVERAGE (UNCHANGED)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "") or ""
            log.warning(
                "Unique constraint violation | gstin=%s | constraint=%s",
                gstin,
                constraint,
            )
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning("Check constraint violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning("NOT NULL constraint violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            log.error(
                "Invalid data format error | gstin=%s",
                gstin,
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Postgres database error during GST update | gstin=%s | error=%s",
                gstin,
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
            log.exception(
                "Unexpected error during GST update | gstin=%s",
                gstin,
            )
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

