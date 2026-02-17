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


router = APIRouter(
    prefix="/api/v1/gst-people",
    tags=["GST Registration People"]
)


# -------------------------------------------------------------------
# CREATE REGISTRATION PERSON (PRODUCTION STANDARD)
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Person",
    responses={
        201: {"description": "Registration person created successfully."},
        400: {"description": "Validation failed or GSTIN not found."},
        409: {"description": "Duplicate registration person."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_person(
    payload: RegistrationPersonIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Registration Person (Production Standard)

    Validation Responsibility:
    --------------------------
    1. Schema-level validation (Pydantic)
    2. GST existence & active validation (DB)
    3. Customer derived from GST (Single Source of Truth)
    4. DB-level constraint validation (UNIQUE / FK / NOT NULL / CHECK)
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    # --------------------------------------------------
    # Normalize Fields
    # --------------------------------------------------
    full_name = payload.full_name.strip() if payload.full_name else None
    role = payload.role.strip() if payload.role else None
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
            # --------------------------------------------------
            # Validate GST Exists & Active
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
                log.warning("GSTIN not found gstin=%s", payload.gstin)
                raise HTTPException(
                    status_code=400,
                    detail="GSTIN not found.",
                )

            if gst_row["is_active"] is False:
                log.warning("GSTIN inactive gstin=%s", payload.gstin)
                raise HTTPException(
                    status_code=400,
                    detail="GSTIN is inactive.",
                )

            # --------------------------------------------------
            # Derive Customer From GST (Single Source of Truth)
            # --------------------------------------------------
            derived_customer_id = gst_row["customer_id"]

            if payload.customer_id and payload.customer_id != derived_customer_id:
                log.warning(
                    "Customer mismatch | gst_customer_id=%s payload_customer_id=%s",
                    derived_customer_id,
                    payload.customer_id,
                )
                raise HTTPException(
                    status_code=400,
                    detail="Customer ID does not match GST registration.",
                )

            # --------------------------------------------------
            # Insert Registration Person
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
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW(),NOW(),TRUE)
                RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(
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
                )

            if not row:
                log.error("Registration person insert returned empty row")
                raise HTTPException(
                    status_code=500,
                    detail="Registration person creation failed.",
                )

            log.info(
                "Registration person created successfully person_id=%s",
                row["person_id"],
            )

            return {
                **dict(row),
                "message": "Registration person created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Database Exception Handling (Full Coverage)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Unique constraint violation during registration person creation")
            raise HTTPException(
                status_code=409,
                detail="Duplicate registration person.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation during registration person creation")
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning("Check constraint violation")
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning("NOT NULL constraint violation")
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            log.exception("Invalid data format during registration person creation", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during registration person creation")
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person creation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

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
# GET REGISTRATION PERSON BY PERSON_ID (ACTIVE ONLY)
# -------------------------------------------------------------------
@router.get(
    "/{person_id}/single_filter",
    summary="Get Registration Person",
    responses={
        200: {"description": "Registration person details."},
        404: {"description": "Registration person not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_registration_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Registration Person by person_id (Production Standard)

    ✔ Returns only active records
    ✔ Structured logging
    ✔ Safe SQL parameterization
    ✔ Full DB exception coverage
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "get_registration_person",
        },
    )

    log.info(
        "Incoming get registration person request | person_id=%s",
        person_id,
    )

    # --------------------------------------------------
    # SQL Query (Active Only)
    # --------------------------------------------------
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_persons
         WHERE person_id = $1
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
            row = await conn.fetchrow(sql, person_id)

        # --------------------------------------------------
        # Not Found Handling (Includes Inactive Records)
        # --------------------------------------------------
        if not row:
            log.warning(
                "Registration person not found or inactive | person_id=%s",
                person_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Registration person not found.",
            )

        log.info(
            "Registration person fetched successfully | person_id=%s",
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
            "person_id=%s | error=%s",
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
            "person_id=%s",
            person_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )


# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON (Dynamic Update - Production Ready)
# -------------------------------------------------------------------
@router.post(
    "/{person_id}/edit",
    summary="Edit Registration Person (Dynamic Update - Production Ready)",
    responses={
        200: {"description": "Registration person updated successfully."},
        400: {"description": "Validation failed or invalid data."},
        404: {"description": "Registration person not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_person(
    person_id: int,
    payload: RegistrationPersonEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Production-Ready Dynamic Registration Person Update API

    Features:
    ---------
    ✔ Dynamic field update (PATCH-like behavior)
    ✔ Structured logging with request_id & emp_id
    ✔ Field normalization (email, mobile, name)
    ✔ Safe SQL parameterization
    ✔ Transaction handling
    ✔ Full DB exception coverage
    ✔ Enterprise-grade error handling

    Validation Responsibility:
    --------------------------
    1. Schema-Level (Pydantic - RegistrationPersonEditIn)
    2. Database-Level:
       - FOREIGN KEY constraints
       - NOT NULL constraints
       - Check constraints
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_registration_person",
        },
    )

    log.info("Incoming edit registration person request | person_id=%s", person_id)

    # --------------------------------------------------
    # Extract Only Provided Fields
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception as e:
        log.exception(
            "Failed to serialize payload | person_id=%s | error=%s",
            person_id,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        log.warning("No fields provided for update | person_id=%s", person_id)
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

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "full_name" in update_data and update_data["full_name"]:
            update_data["full_name"] = update_data["full_name"].strip()

        if "role" in update_data and update_data["role"]:
            update_data["role"] = update_data["role"].strip()

    except Exception as e:
        log.exception(
            "Error during field normalization | person_id=%s | payload=%s | error=%s",
            person_id,
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
            "Database pool acquisition failed | person_id=%s | error=%s",
            person_id,
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            fields = []
            values = []
            param_index = 1

            # --------------------------------------------------
            # Build Dynamic SET Clause (SQL Injection Safe)
            # --------------------------------------------------
            for field_name, value in update_data.items():
                fields.append(f"{field_name} = ${param_index}")
                values.append(value)
                param_index += 1

            # NOTE:
            # registration_persons table does NOT have updated_at column.
            # So we are NOT appending updated_at = NOW()

            sql = f"""
                UPDATE {DB_SCHEMA}.registration_persons
                   SET {', '.join(fields)}
                 WHERE person_id = ${param_index}
                 RETURNING *
            """

            values.append(person_id)

            log.debug(
                "Executing registration person update query | person_id=%s | fields=%s",
                person_id,
                list(update_data.keys()),
            )

            # --------------------------------------------------
            # Transaction (Atomic Update)
            # --------------------------------------------------
            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            # --------------------------------------------------
            # Not Found Handling
            # --------------------------------------------------
            if not row:
                log.warning("Registration person not found | person_id=%s", person_id)
                raise HTTPException(
                    status_code=404,
                    detail="Registration person not found.",
                )

            log.info(
                "Registration person updated successfully | person_id=%s | updated_fields=%s",
                person_id,
                list(update_data.keys()),
            )

            return {
                **dict(row),
                "message": "Registration person updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DATABASE EXCEPTION HANDLING (Full Coverage)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Unique constraint violation | person_id=%s", person_id)
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation | person_id=%s", person_id)
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning("Check constraint violation | person_id=%s", person_id)
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning("NOT NULL constraint violation | person_id=%s", person_id)
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            log.error(
                "Invalid data format error | person_id=%s",
                person_id,
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Postgres database error during registration person update | "
                "person_id=%s | error=%s",
                person_id,
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
                "Unexpected error during registration person update | person_id=%s",
                person_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )


# =========================================================
# SOFT DELETE REGISTRATION PERSON (is_active = false)
# =========================================================

@router.delete(
    "/{person_id}/soft_delete",
    summary="Soft delete Registration Person by setting is_active to false",
    responses={
        200: {"description": "Registration person soft deleted successfully."},
        400: {"description": "Registration person already inactive."},
        404: {"description": "Registration person not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete Registration Person by updating is_active to FALSE.

    Behavior:
    ---------
    - Does NOT remove the row from DB
    - Sets is_active = FALSE
    - Updates updated_at timestamp
    - Maintains referential integrity (FK safe)
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "soft_delete_registration_person",
        },
    )

    log.info(
        "Incoming soft delete registration person request | person_id=%s",
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
            # --------------------------------------------------
            # Soft Delete Query
            # --------------------------------------------------
            sql = f"""
                UPDATE {DB_SCHEMA}.registration_persons
                   SET is_active = FALSE,
                       updated_at = NOW()
                 WHERE person_id = $1
                   AND is_active = TRUE
                 RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(sql, person_id)

            # --------------------------------------------------
            # Not Found / Already Inactive Handling
            # --------------------------------------------------
            if not row:
                check_sql = f"""
                    SELECT person_id, is_active
                      FROM {DB_SCHEMA}.registration_persons
                     WHERE person_id = $1
                """

                existing = await conn.fetchrow(check_sql, person_id)

                if not existing:
                    log.warning(
                        "Registration person not found for soft delete | person_id=%s",
                        person_id,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="Registration person not found.",
                    )

                if existing["is_active"] is False:
                    log.warning(
                        "Registration person already inactive | person_id=%s",
                        person_id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Registration person is already inactive.",
                    )

            log.info(
                "Registration person soft deleted successfully | person_id=%s",
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
                "person_id=%s | error=%s",
                person_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during registration person soft delete | "
                "person_id=%s | error=%s",
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
                "person_id=%s | error=%s",
                person_id,
                str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
