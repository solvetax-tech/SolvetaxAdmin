import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationPersonIn,
    RegistrationPersonEditIn,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/gst-people",
    tags=["GST Registration People"]
)



# -------------------------------------------------------------------
# CREATE REGISTRATION PERSON (Production Standard + Version Audit + IST)
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Person",
    responses={
        201: {"description": "Registration person created successfully."},
        400: {"description": "Validation failed or GST not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_person(
    payload: RegistrationPersonIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Registration Person
    --------------------------
    ✔ Atomic transaction (Person + Version)
    ✔ GST must exist & active
    ✔ One primary per GST enforced by DB
    ✔ GSTIN + PAN uniqueness (active only)
    ✔ GSTIN + Aadhaar uniqueness (active only)
    ✔ Enterprise-grade structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming Registration Person create | gstin=%s | designation=%s",
        payload.gstin,
        payload.designation,
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
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.gst_registration
                    WHERE upper(gstin) = $1
                    LIMIT 1
                    """,
                    payload.gstin.strip().upper(),
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=400,
                        detail="GSTIN not found.",
                    )

                if not gst_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="GSTIN is inactive.",
                    )

                derived_customer_id = gst_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Insert Registration Person
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.registration_persons (
                        customer_id,
                        gstin,
                        full_name,
                        designation,
                        pan,
                        aadhaar,
                        email,
                        mobile,
                        is_primary_customer,
                        is_active,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,TRUE,$10,$11
                    )
                    RETURNING *
                """

                person_row = await conn.fetchrow(
                    insert_sql,
                    derived_customer_id,
                    payload.gstin.strip().upper(),
                    payload.full_name,
                    payload.designation,
                    payload.pan,
                    payload.aadhaar,
                    payload.email,
                    payload.mobile,
                    payload.is_primary_customer,
                    now,
                    now,
                )

                if not person_row:
                    raise HTTPException(
                        status_code=500,
                        detail="Registration person creation failed.",
                    )

                # --------------------------------------------------
                # 3️⃣ Version Audit Insert
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
                    "REGISTRATION_PERSON",
                    5,
                    derived_customer_id,
                    "CREATE",
                    json.dumps(dict(person_row), default=str),
                    None,
                )

            log.info(
                "Registration person created successfully | person_id=%s",
                person_row["person_id"],
            )

            return {
                **dict(person_row),
                "message": "Registration person created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING (PRECISE)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "uq_reg_person_gstin_pan_active":
                    "This PAN already exists for this GST (active).",

                "uq_reg_person_gstin_aadhaar_active":
                    "This Aadhaar already exists for this GST (active).",

                "uq_reg_primary_per_gstin":
                    "Only one active primary person is allowed per GST.",
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
        # CHECK CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_pan_format": "Invalid PAN format.",
                "chk_person_aadhaar_format": "Invalid Aadhaar format.",
                "chk_person_gst_format": "Invalid GSTIN format.",
                "chk_person_mobile_format": "Invalid mobile number format.",
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
            log.exception("Unexpected error during Registration Person creation")
            raise HTTPException(status_code=500, detail="Internal server error.")
# -------------------------------------------------------------------
# LIST REGISTRATION PERSONS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter Registration Persons",
    responses={
        200: {"description": "Registration persons filtered successfully."},
        400: {"description": "Validation failed (e.g. invalid date range)."},
        500: {"description": "Database or internal error."},
    },
)
async def list_registration_persons(
    gstin: Optional[str] = None,
    person_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    pan: Optional[str] = None,
    aadhaar: Optional[str] = None,
    mobile: Optional[str] = None,
    full_name: Optional[str] = None,
    designation: Optional[str] = None,
    is_primary_customer: Optional[bool] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Filter Registration Persons (Enterprise Standard)

    ✔ Fully aligned with DB indexes
    ✔ Trim + uppercase safe for GSTIN/PAN
    ✔ Aadhaar trimmed
    ✔ Active filtering pattern consistent with GST API
    ✔ Pagination safe
    ✔ Structured logging
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
        "Incoming registration persons filter | limit=%s offset=%s",
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
        # Indexed Filters (Optimized)
        # --------------------------------------------------

        if person_id is not None:
            conditions.append(f"person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gstin and gstin.strip():
            conditions.append(f"upper(gstin) = ${param_index}")
            values.append(gstin.strip().upper())
            param_index += 1

        if pan and pan.strip():
            conditions.append(f"upper(pan) = ${param_index}")
            values.append(pan.strip().upper())
            param_index += 1

        if aadhaar and aadhaar.strip():
            conditions.append(f"trim(aadhaar) = ${param_index}")
            values.append(aadhaar.strip())
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        if is_primary_customer is not None:
            conditions.append(f"is_primary_customer = ${param_index}")
            values.append(is_primary_customer)
            param_index += 1

        # --------------------------------------------------
        # Partial Match Filters (ILIKE)
        # --------------------------------------------------

        if full_name and full_name.strip():
            conditions.append(f"full_name ILIKE ${param_index}")
            values.append(f"%{full_name.strip()}%")
            param_index += 1

        if designation and designation.strip():
            conditions.append(f"designation ILIKE ${param_index}")
            values.append(f"%{designation.strip()}%")
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
        # Date Filtering (created_at based)
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
        # WHERE Clause Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.registration_persons
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info(
            "Registration persons filtered successfully | count=%s",
            len(rows),
        )

        return [
            {
                **dict(row),
                "message": "Registration persons filtered successfully.",
                "request_id": request_id,
            }
            for row in rows
        ]

    # --------------------------------------------------
    # Database Exception Handling
    # --------------------------------------------------

    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration persons filtering | error=%s",
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
        log.exception("Unexpected error during registration persons filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# GET REGISTRATION PERSON BY GSTIN (ACTIVE ONLY)
# -------------------------------------------------------------------

def mask_gstin(gstin: str) -> str:
    if not gstin or len(gstin) < 6:
        return "****"
    return f"{gstin[:2]}******{gstin[-3:]}"
# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON (GSTIN + PERSON_ID)
# -------------------------------------------------------------------
@router.post(
    "/{gstin}/{person_id}/edit",
    summary="Edit Registration Person (Production Ready + Version Audit)",
    responses={
        200: {"description": "Registration person updated successfully."},
        400: {"description": "Validation failed or invalid data."},
        404: {"description": "Registration person not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_person(
    gstin: str,
    person_id: int,
    payload: RegistrationPersonEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

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
            "api": "edit_registration_person",
        },
    )

    log.info(
        "Incoming edit registration person | gstin=%s | person_id=%s",
        normalized_gstin,
        person_id,
    )

    # --------------------------------------------------
    # Extract Payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Normalize Fields (Aligned with DB Indexes)
    # --------------------------------------------------
    try:
        if "pan" in update_data and update_data["pan"]:
            update_data["pan"] = update_data["pan"].strip().upper()

        if "aadhaar" in update_data and update_data["aadhaar"]:
            update_data["aadhaar"] = update_data["aadhaar"].strip()

        if "email" in update_data and update_data["email"]:
            update_data["email"] = update_data["email"].strip().lower()

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "full_name" in update_data and update_data["full_name"]:
            update_data["full_name"] = update_data["full_name"].strip()

        if "designation" in update_data and update_data["designation"]:
            update_data["designation"] = update_data["designation"].strip()

    except Exception:
        log.exception("Normalization failed")
        raise HTTPException(status_code=400, detail="Invalid field values provided.")

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
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gstin, is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE upper(gstin) = $1
                     LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not gst_row:
                    raise HTTPException(status_code=404, detail="GST not found.")

                if not gst_row["is_active"]:
                    raise HTTPException(status_code=400, detail="GST is inactive.")

                # --------------------------------------------------
                # 2️⃣ Fetch Existing Person
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_persons
                     WHERE upper(gstin) = $1
                       AND person_id = $2
                     LIMIT 1
                    """,
                    normalized_gstin,
                    person_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration person not found.",
                    )

                # --------------------------------------------------
                # 3️⃣ Primary Person Auto-Handling
                # --------------------------------------------------
                if "is_primary_customer" in update_data and update_data["is_primary_customer"] is True:

                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.registration_persons
                           SET is_primary_customer = FALSE,
                               updated_at = NOW()
                         WHERE upper(gstin) = $1
                           AND is_primary_customer = TRUE
                           AND is_active = TRUE
                        """,
                        normalized_gstin,
                    )

                # --------------------------------------------------
                # 4️⃣ Build Dynamic Update
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
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET {', '.join(fields)}
                     WHERE upper(gstin) = ${param_index}
                       AND person_id = ${param_index + 1}
                     RETURNING *
                """

                values.append(normalized_gstin)
                values.append(person_id)

                new_row = await conn.fetchrow(sql, *values)

                # --------------------------------------------------
                # 5️⃣ Version Audit
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
                    "REGISTRATION_PERSON",
                    5,
                    new_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Registration person updated successfully | person_id=%s",
                person_id,
            )

            return {
                **dict(new_row),
                "message": "Registration person updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING (ALIGNED WITH YOUR INDEXES)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:

            constraint_name = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                "uq_reg_person_gstin_aadhaar_active":
                    "Aadhaar already exists for this GST (active).",
                "uq_reg_person_gstin_pan_active":
                    "PAN already exists for this GST (active).",
                "uq_reg_primary_per_gstin":
                    "Only one active primary person allowed per GSTIN.",
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint_name,
                    f"Duplicate value violates constraint: {constraint_name}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        # --------------------------------------------------
# CHECK CONSTRAINT HANDLING (DETAILED)
# --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_pan_format": "Invalid PAN format. Expected format: ABCDE1234F.",
                "chk_person_aadhaar_format": "Invalid Aadhaar format. Must be 12 digits.",
                "chk_person_gst_format": "Invalid GSTIN format.",
                "chk_person_mobile_format": "Invalid mobile number format. Must be 10 digits.",
                }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                    ),
                    )

        except asyncpg.PostgresError:
            log.exception("Database error during registration person update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# =========================================================
# SOFT DELETE REGISTRATION PERSON (is_active = FALSE) WITH VERSION AUDIT
# =========================================================
# -------------------------------------------------------------------
# SOFT DELETE REGISTRATION PERSON (With Primary Protection + Audit)
# -------------------------------------------------------------------

@router.delete(
    "/{gstin}/{person_id}/soft_delete",
    summary="Soft delete Registration Person (Enterprise + Audit)",
    responses={
        200: {"description": "Registration person soft deleted successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "Registration person not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_person(
    gstin: str,
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft Delete Registration Person (Enterprise Grade)

    ✔ Atomic transaction
    ✔ Primary deletion protection
    ✔ Concurrency safe
    ✔ Version audit
    ✔ Structured logging
    ✔ DB constraint aligned
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
            "api": "soft_delete_registration_person",
        },
    )

    log.info(
        "Incoming soft delete registration person | gstin=%s | person_id=%s",
        normalized_gstin,
        person_id,
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
                # 1️⃣ Fetch Existing Person
                # --------------------------------------------------
                person_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_persons
                     WHERE upper(gstin) = $1
                       AND person_id = $2
                     LIMIT 1
                    """,
                    normalized_gstin,
                    person_id,
                )

                if not person_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration person not found.",
                    )

                if person_row["is_active"] is False:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration person is already inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Primary Deletion Protection Logic
                # --------------------------------------------------
                if person_row["is_primary_customer"]:

                    other_active_count = await conn.fetchval(
                        f"""
                        SELECT COUNT(*)
                          FROM {DB_SCHEMA}.registration_persons
                         WHERE upper(gstin) = $1
                           AND customer_id = $2
                           AND is_active = TRUE
                           AND person_id <> $3
                        """,
                        normalized_gstin,
                        person_row["customer_id"],
                        person_id,
                    )

                    # If other active persons exist → block deletion
                    if other_active_count > 0:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Cannot delete primary person while other active persons exist. "
                                "Please assign another primary person first."
                            ),
                        )

                # --------------------------------------------------
                # 3️⃣ Concurrency-Safe Soft Delete
                # --------------------------------------------------
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE upper(gstin) = $1
                       AND person_id = $2
                       AND is_active = TRUE
                     RETURNING *
                """

                deleted_row = await conn.fetchrow(
                    delete_sql,
                    normalized_gstin,
                    person_id,
                )

                if not deleted_row:
                    raise HTTPException(
                        status_code=400,
                        detail="Unable to delete registration person.",
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit (DELETE)
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
                    "REGISTRATION_PERSON",
                    5,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_row), default=str),
                )

            log.info(
                "Registration person soft deleted successfully | person_id=%s",
                person_id,
            )

            return {
                **dict(deleted_row),
                "message": "Registration person soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DB EXCEPTION HANDLING
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
            log.exception("Database error during registration person soft delete")
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person soft delete")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )