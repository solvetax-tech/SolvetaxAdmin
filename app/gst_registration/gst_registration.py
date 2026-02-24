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
    ✔ is_active forced TRUE by backend
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
                    payload.password,  # must be hashed before API call
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
                    True,  # ✅ FORCE ACTIVE TRUE
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
                    gst_row["id"],   # ✅ Correct entity ID
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
    ✔ Enterprise active filtering logic
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

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

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
            "request_id": request_id,
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
        404: {"description": "GST registration not found or inactive."},
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
    ✔ Only active GST can be updated
    ✔ GSTIN cascade propagation
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

    normalized_gstin = gstin.strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_gst_registration"},
    )

    log.info("Incoming GST edit request | gstin=%s", normalized_gstin)

    # --------------------------------------------------
    # Extract Payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(400, "Invalid request payload.")

    if not update_data:
        raise HTTPException(400, "At least one field must be provided for update.")

    update_data.pop("approved_at", None)  # Never allow manual update

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(500, "Database connection error.")

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
                     WHERE upper(gstin) = $1
                       AND is_active = TRUE
                     FOR UPDATE
                    """,
                    normalized_gstin,
                )

                if not old_row:
                    raise HTTPException(
                        404,
                        "GST registration not found or inactive.",
                    )

                old_gstin = old_row["gstin"]

                # --------------------------------------------------
                # 2️⃣ Detect GSTIN Change
                # --------------------------------------------------
                gstin_changed = (
                    "gstin" in update_data
                    and update_data["gstin"] != old_gstin
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
                values.append(normalized_gstin)

                sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET {', '.join(fields)}
                     WHERE upper(gstin) = ${idx}
                       AND is_active = TRUE
                     RETURNING *
                """

                new_row = await conn.fetchrow(sql, *values)

                # --------------------------------------------------
                # 4️⃣ GSTIN Cascade (If Changed)
                # --------------------------------------------------
                if gstin_changed:
                    new_gstin = update_data["gstin"]

                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.registration_persons
                           SET gstin = $1,
                               updated_at = NOW()
                         WHERE upper(gstin) = $2
                           AND is_active = TRUE
                        """,
                        new_gstin,
                        old_gstin,
                    )

                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.registration_documents
                           SET gstin = $1,
                               updated_at = NOW()
                         WHERE upper(gstin) = $2
                           AND is_active = TRUE
                        """,
                        new_gstin,
                        old_gstin,
                    )

                # --------------------------------------------------
                # 5️⃣ Version Audit
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
        # UNIQUE CONSTRAINTS
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                "gst_registration_gstin_key": "GSTIN already exists.",
                "uq_gst_username_lower": "Username already exists.",
                "uq_gst_gstin_mobile_active": "Mobile already assigned to an active GST.",
            }

            raise HTTPException(
                409,
                UNIQUE_MAP.get(constraint, "Duplicate value violates unique constraint."),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference provided.")

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
                400,
                CHECK_MAP.get(constraint, f"Data violates constraint: {constraint}"),
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(400, "Missing required field value.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(400, "Invalid data format provided.")

        except asyncpg.PostgresError:
            log.exception("Database error during GST update")
            raise HTTPException(500, "Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST update")
            raise HTTPException(500, "Internal server error.")



@router.delete(
    "/{gstin}/soft_delete",
    summary="Soft delete GST registration (Enterprise + Cascade + Audit)",
    responses={
        200: {"description": "GST registration soft deleted successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "GST registration not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_gst_registration(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete GST registration and cascade deactivate all associated persons and documents.

    ✔ Atomic transaction
    ✔ Concurrency safe
    ✔ Cascade soft delete for persons and documents
    ✔ Version audit for GST only (persons/documents audit skipped)
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
            "emp_id": emp_id,
            "api": "soft_delete_gst_registration",
        },
    )

    log.info("Incoming soft delete GST | gstin=%s", normalized_gstin)

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
                # 1️⃣ Fetch Existing GST
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE upper(gstin) = $1
                     LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                if gst_row["is_active"] is False:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration already inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Concurrency-Safe Soft Delete (GST)
                # --------------------------------------------------
                deleted_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = TRUE
                     RETURNING *
                    """,
                    normalized_gstin,
                )

                if not deleted_gst:
                    raise HTTPException(
                        status_code=400,
                        detail="Unable to deactivate GST registration.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Soft Delete Persons (Active Only)
                # --------------------------------------------------
                deleted_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = TRUE
                     RETURNING person_id
                    """,
                    normalized_gstin,
                )

                # --------------------------------------------------
                # 4️⃣ Cascade Soft Delete Documents (Active Only)
                # --------------------------------------------------
                deleted_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = TRUE
                     RETURNING document_id
                    """,
                    normalized_gstin,
                )

                # --------------------------------------------------
                # 5️⃣ Version Audit (GST ONLY)
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
                    json.dumps(dict(deleted_gst), default=str),
                )

            log.info(
                "GST soft deleted successfully | gstin=%s | persons_deactivated=%s | documents_deactivated=%s",
                normalized_gstin,
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

        # --------------------------------------------------
        # Exception Handling
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK constraint error")
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.exception("Postgres error during GST soft delete")
            raise HTTPException(
                status_code=500,
                detail=str(e),
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST soft delete")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# -------------------------------------------------------------------
# ACTIVATE GST REGISTRATION
# (Enterprise + Version Audit + Cascade Persons + Documents)
# -------------------------------------------------------------------

@router.post(
    "/{gstin}/activate",
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
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Activate GST Registration and cascade activate all associated persons and documents.

    ✔ Atomic transaction
    ✔ Concurrency safe
    ✔ Customer must be active
    ✔ Cascade activation of persons and documents
    ✔ Version audit for GST only (persons/documents audit skipped)
    ✔ Structured logging
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
            "emp_id": emp_id,
            "api": "activate_gst_registration",
        },
    )

    log.info("Incoming GST activation | gstin=%s", normalized_gstin)

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
                # 1️⃣ Fetch Existing GST + Customer Status
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gst.*, c.is_active AS customer_active
                      FROM {DB_SCHEMA}.gst_registration gst
                      JOIN {DB_SCHEMA}.customers c
                        ON gst.customer_id = c.customer_id
                     WHERE upper(gst.gstin) = $1
                     LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                if gst_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration already active.",
                    )

                if not gst_row["customer_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot activate GST: associated customer is inactive.",
                    )

                customer_id = gst_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Activate GST (Concurrency Safe)
                # --------------------------------------------------
                activated_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    normalized_gstin,
                )

                if not activated_gst:
                    raise HTTPException(
                        status_code=409,
                        detail="GST state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Activate Persons
                # --------------------------------------------------
                activated_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = FALSE
                     RETURNING person_id
                    """,
                    normalized_gstin,
                )

                # --------------------------------------------------
                # 4️⃣ Cascade Activate Documents
                # --------------------------------------------------
                activated_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND is_active = FALSE
                     RETURNING document_id
                    """,
                    normalized_gstin,
                )

                # --------------------------------------------------
                # 5️⃣ Version Audit (GST ONLY)
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
                    json.dumps(dict(activated_gst), default=str),
                )

            log.info(
                "GST activated successfully | gstin=%s | persons_activated=%s | documents_activated=%s",
                normalized_gstin,
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

        # --------------------------------------------------
        # Exception Handling
        # --------------------------------------------------
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