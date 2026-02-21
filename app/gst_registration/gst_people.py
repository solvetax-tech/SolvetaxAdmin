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
# CREATE REGISTRATION PERSON (Production + Version Audit + IST)
# -------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Person",
)
async def create_registration_person(
    payload: RegistrationPersonIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Registration Person (Production Standard + Version Audit)

    ✔ Atomic transaction (Person + Version)
    ✔ entity_type = 'REGISTRATION_PERSON'
    ✔ entity_id = 5 (example)
    ✔ action = 'CREATE'
    ✔ json populated
    ✔ updated_json = NULL
    ✔ IST timezone safe
    ✔ Structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid
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
    full_name = payload.full_name.strip()
    role = payload.role.strip()
    email = payload.email.strip().lower() if payload.email else None
    mobile = payload.mobile.strip() if payload.mobile else None
    pan = payload.pan.strip().upper() if payload.pan else None
    aadhaar = payload.aadhaar.strip() if payload.aadhaar else None

    log.info(
        "Incoming registration person create | gstin=%s role=%s",
        payload.gstin,
        role,
    )

    # --------------------------------------------------
    # Database Pool
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
                     WHERE gstin = $1
                     LIMIT 1
                    """,
                    payload.gstin,
                )

                if not gst_row:
                    raise HTTPException(status_code=400, detail="GSTIN not found.")

                if gst_row["is_active"] is False:
                    raise HTTPException(status_code=400, detail="GSTIN is inactive.")

                derived_customer_id = gst_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Insert Registration Person
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.registration_persons
                    (
                        customer_id,
                        gstin,
                        full_name,
                        role,
                        pan,
                        aadhaar,
                        email,
                        mobile,
                        is_primary_customer,
                        created_at,
                        updated_at,
                        is_active
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,TRUE)
                    RETURNING *
                """

                person_row = await conn.fetchrow(
                    insert_sql,
                    derived_customer_id,
                    payload.gstin,
                    full_name,
                    role,
                    pan,
                    aadhaar,
                    email,
                    mobile,
                    payload.is_primary_customer,
                    now,
                    now,
                )

                if not person_row:
                    raise HTTPException(
                        status_code=500,
                        detail="Registration person creation failed.",
                    )

                person_id = person_row["person_id"]

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
                    "REGISTRATION_PERSON",
                    5,  # entity id for registration person
                    derived_customer_id,
                    "CREATE",
                    json.dumps(dict(person_row), default=str),
                    None,
                )

            log.info(
                "Registration person created successfully with audit | person_id=%s",
                person_id,
            )

            response_data = dict(person_row)
            response_data["message"] = "Registration person created successfully."
            response_data["request_id"] = request_id

            return response_data

        # --------------------------------------------------
        # Exception Handling
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(status_code=409, detail="Duplicate registration person.")

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Invalid foreign key reference.")

        except asyncpg.PostgresError:
            log.exception("Database error during registration person creation")
            raise HTTPException(status_code=500, detail="Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person creation")
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
    person_id: Optional[int] = None,   # ✅ ADDED
    customer_id: Optional[int] = None,
    mobile: Optional[str] = None,
    full_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Filter Registration Persons (Production Standard)

    Validation Responsibility:
    --------------------------
    1. FastAPI: Type + pagination validation
    2. DB: Filtering logic
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
        "Incoming registration persons filter request limit=%s offset=%s",
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

    try:
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Business Filters
        # --------------------------------------------------

        if gstin and gstin.strip():
            conditions.append(f"gstin ILIKE ${param_index}")
            values.append(f"%{gstin.strip()}%")
            param_index += 1

        # ✅ NEW FILTER ADDED
        if person_id is not None:
            conditions.append(f"person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        if full_name and full_name.strip():
            conditions.append(f"full_name ILIKE ${param_index}")
            values.append(f"%{full_name.strip()}%")
            param_index += 1

        # --------------------------------------------------
        # Active Status Filtering (Enterprise Pattern)
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
            "Registration persons filtered successfully count=%s",
            len(rows),
        )

        return [
            {
                **dict(row),
                "message": "Registration persons filtered successfully.",
            }
            for row in rows
        ]

    # --------------------------------------------------
    # Database Exception Handling
    # --------------------------------------------------
    except asyncpg.PostgresError:
        log.exception("Database error during registration persons filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

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

@router.get(
    "/{gstin}/{person_id}/single_filter",
    summary="Get Registration Person by GSTIN",
    responses={
        200: {"description": "Registration person details."},
        404: {"description": "Registration person not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_registration_person(
    gstin: str,
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Registration Person by GSTIN (Production Standard)

    ✔ Returns only active records
    ✔ Structured logging
    ✔ GSTIN masked in logs
    ✔ Safe SQL parameterization
    ✔ Full DB exception coverage
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    masked_gstin = mask_gstin(gstin)

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "get_registration_person",
        },
    )

    log.info(
        "Incoming get registration person request | gstin=%s | person_id=%s",
        masked_gstin,
        person_id,
    )

    # --------------------------------------------------
    # SQL Query (Active Only)
    # --------------------------------------------------
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_persons
         WHERE gstin = $1
           AND person_id = $2
           AND is_active = TRUE
         LIMIT 1
    """

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

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, gstin, person_id)

        # --------------------------------------------------
        # Not Found Handling (Includes Inactive Records)
        # --------------------------------------------------
        if not row:
            log.warning(
                "Registration person not found or inactive | gstin=%s | person_id=%s",
                masked_gstin,
                person_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Registration person not found.",
            )

        log.info(
            "Registration person fetched successfully | gstin=%s | person_id=%s",
            masked_gstin,
            person_id,
        )

        return {
            **dict(row),
            "message": "Registration person fetched successfully.",
            "request_id": request_id,
        }

    # --------------------------------------------------
    # Re-raise HTTP Exceptions
    # --------------------------------------------------
    except HTTPException:
        raise

    # --------------------------------------------------
    # Database Error Handling
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration person fetch | "
            "gstin=%s | person_id=%s | error=%s",
            masked_gstin,
            person_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    # --------------------------------------------------
    # Unexpected Error Handling
    # --------------------------------------------------
    except Exception:
        log.exception(
            "Unexpected error during registration person fetch | "
            "gstin=%s | person_id=%s",
            masked_gstin,
            person_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

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
    masked_gstin = mask_gstin(gstin)

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
        masked_gstin,
        person_id,
    )

    # --------------------------------------------------
    # Extract Payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed | gstin=%s", masked_gstin)
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Normalize Fields
    # --------------------------------------------------
    if "email" in update_data and update_data["email"]:
        update_data["email"] = update_data["email"].strip().lower()

    if "mobile" in update_data and update_data["mobile"]:
        update_data["mobile"] = update_data["mobile"].strip()

    if "pan" in update_data and update_data["pan"]:
        update_data["pan"] = update_data["pan"].strip().upper()

    if "aadhaar" in update_data and update_data["aadhaar"]:
        update_data["aadhaar"] = update_data["aadhaar"].strip()

    if "full_name" in update_data and update_data["full_name"]:
        update_data["full_name"] = update_data["full_name"].strip()

    if "role" in update_data and update_data["role"]:
        update_data["role"] = update_data["role"].strip()

    # --------------------------------------------------
    # DB Connection
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool acquisition failed | gstin=%s", masked_gstin)
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Validate GST
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gstin, is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE gstin = $1
                     LIMIT 1
                    """,
                    gstin,
                )

                if not gst_row:
                    raise HTTPException(status_code=404, detail="GST not found.")

                if gst_row["is_active"] is False:
                    raise HTTPException(status_code=400, detail="GST is inactive.")

                # --------------------------------------------------
                # 2️⃣ Fetch OLD Person
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_persons
                     WHERE gstin = $1
                       AND person_id = $2
                     LIMIT 1
                    """,
                    gstin,
                    person_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration person not found.",
                    )

                # --------------------------------------------------
                # 3️⃣ Validate Customer if updating
                # --------------------------------------------------
                if "customer_id" in update_data:

                    customer_row = await conn.fetchrow(
                        f"""
                        SELECT customer_id, is_active
                          FROM {DB_SCHEMA}.customers
                         WHERE customer_id = $1
                         LIMIT 1
                        """,
                        update_data["customer_id"],
                    )

                    if not customer_row:
                        raise HTTPException(
                            status_code=404,
                            detail="Customer not found.",
                        )

                    if customer_row["is_active"] is False:
                        raise HTTPException(
                            status_code=400,
                            detail="Customer is inactive.",
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
                     WHERE gstin = ${param_index}
                       AND person_id = ${param_index + 1}
                     RETURNING *
                """

                values.append(gstin)
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

            return {
                **dict(new_row),
                "message": "Registration person updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE VIOLATION HANDLING (Exact)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:

            constraint_name = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                "uq_reg_person_email": "Email already exists.",
                "uq_reg_person_pan": "PAN already exists.",
                "uq_reg_person_mobile": "Mobile already exists.",
                "uq_reg_person_aadhaar": "Aadhaar already exists.",
                "uq_reg_person_primary_per_gstin_customer":
                    "Only one primary person allowed per GSTIN for this customer.",
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

        except asyncpg.PostgresError:
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# =========================================================
# SOFT DELETE REGISTRATION PERSON (is_active = false) WITH VERSION AUDIT
# =========================================================

@router.delete(
    "/{gstin}/{person_id}/soft_delete",
    summary="Soft delete Registration Person (With Audit)",
    responses={
        200: {"description": "Registration person soft deleted successfully."},
        400: {"description": "Registration person already inactive."},
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
    Soft Delete Registration Person with Version Audit

    ✔ Atomic transaction (Soft Delete + Version Insert)
    ✔ Concurrency safe (AND is_active = TRUE)
    ✔ json = NULL (for DELETE)
    ✔ updated_json = NEW snapshot (is_active = FALSE)
    ✔ action = 'DELETE'
    ✔ Enterprise structured logging
    ✔ Full asyncpg exception handling
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    masked_gstin = mask_gstin(gstin)

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "soft_delete_registration_person",
        },
    )

    log.info(
        "Incoming soft delete registration person request | gstin=%s | person_id=%s",
        masked_gstin,
        person_id,
    )

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception(
            "Database pool acquisition failed during registration person soft delete | error=%s",
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
                # 1️⃣ Perform Soft Delete (Concurrency Safe)
                # --------------------------------------------------
                sql = f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE gstin = $1
                       AND person_id = $2
                       AND is_active = TRUE
                     RETURNING *
                """

                row = await conn.fetchrow(sql, gstin, person_id)

                # --------------------------------------------------
                # Not Found / Already Inactive Handling
                # --------------------------------------------------
                if not row:
                    check_sql = f"""
                        SELECT gstin, person_id, is_active
                          FROM {DB_SCHEMA}.registration_persons
                         WHERE gstin = $1
                           AND person_id = $2
                    """

                    existing = await conn.fetchrow(check_sql, gstin, person_id)

                    if not existing:
                        log.warning(
                            "Registration person not found for soft delete | gstin=%s | person_id=%s",
                            masked_gstin,
                            person_id,
                        )
                        raise HTTPException(
                            status_code=404,
                            detail="Registration person not found.",
                        )

                    if existing["is_active"] is False:
                        log.warning(
                            "Registration person already inactive | gstin=%s | person_id=%s",
                            masked_gstin,
                            person_id,
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="Registration person is already inactive.",
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

                deleted_snapshot = dict(row)

                await conn.execute(
                    version_sql,
                    emp_id,
                    "REGISTRATION_PERSON",
                    5,  # ✅ NOT CHANGED
                    deleted_snapshot["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(deleted_snapshot, default=str),
                )

            log.info(
                "Registration person soft deleted successfully with audit | gstin=%s | person_id=%s",
                masked_gstin,
                person_id,
            )

            return {
                **dict(row),
                "message": "Registration person soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DATABASE EXCEPTION HANDLING (Enterprise Grade)
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.error(
                "Foreign key violation during registration person soft delete | "
                "gstin=%s | person_id=%s | error=%s",
                masked_gstin,
                person_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.error(
                "Audit constraint violation during registration person soft delete | "
                "gstin=%s | person_id=%s | error=%s",
                masked_gstin,
                person_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Audit constraint validation failed.",
            )

        except asyncpg.exceptions.DataError as e:
            log.error(
                "Data error during registration person soft delete | "
                "gstin=%s | person_id=%s | error=%s",
                masked_gstin,
                person_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during registration person soft delete | "
                "gstin=%s | person_id=%s | error=%s",
                masked_gstin,
                person_id,
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
                "Unexpected error during registration person soft delete | "
                "gstin=%s | person_id=%s | error=%s",
                masked_gstin,
                person_id,
                str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )