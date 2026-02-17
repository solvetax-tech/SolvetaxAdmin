import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime
from app.gst_registration.schemas import GSTRegistrationIn, GSTRegistrationEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.security.rbac import require_permission
from app.logger import logger

router = APIRouter(
    prefix="/api/v1/gst-registrations",
    tags=["GST Registration"]
)

# -------------------------------------------------------------------
# CREATE GST REGISTRATION (PRODUCTION SAFE - CLEAN VERSION)
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
    Create GST Registration (Production Standard)

    Validation Responsibility:
    --------------------------
    1. Schema-level validation (Pydantic)
    2. Customer existence validation (DB)
    3. DB-level constraint validation
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
            # --------------------------------------------------
            # Validate Customer
            # --------------------------------------------------
            exists = await conn.fetchrow(
                f"""
                SELECT 1 FROM {DB_SCHEMA}.customers
                WHERE customer_id=$1
                  AND mobile=$2
                  AND is_active=TRUE
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
            # Insert GST Registration
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
                    'DRAFT',$13,$14,$15,$16,$17,NOW(),NOW()
                )
                RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(
                    insert_sql,
                    payload.customer_id,
                    username,
                    payload.password,  # plain as requested
                    payload.pan,
                    payload.registration_type,
                    payload.ownership_category,
                    payload.business_type,
                    payload.state,
                    payload.turnover_details,
                    payload.created_by or (
                        int(emp_id) if emp_id not in (None, "-") else None
                    ),
                    payload.rm_id,
                    payload.gstin,
                    payload.is_filing_needed,
                    mobile,
                    payload.is_active,
                    email,
                    secondary_email,
                )

            if not row:
                log.error("GST insert returned empty row")
                raise HTTPException(
                    status_code=500,
                    detail="GST registration creation failed.",
                )

            log.info("GST registration created successfully id=%s", row["id"])

            return {
                **dict(row),
                "message": "GST registration created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DB Exception Handling
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Unique constraint violation during GST creation")
            raise HTTPException(status_code=409, detail="Duplicate field value.")

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation during GST creation")
            raise HTTPException(status_code=400, detail="Invalid reference.")

        except asyncpg.PostgresError:
            log.exception("Database error during GST creation")
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
# EDIT GST REGISTRATION (Dynamic Update - Production Ready)
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
    """
    Production-Ready Dynamic GST Update API

    Features:
    ---------
    ✔ Dynamic field update (PATCH-like behavior)
    ✔ Structured logging with request_id & emp_id
    ✔ Field normalization (email, mobile)
    ✔ Safe SQL parameterization
    ✔ Transaction handling
    ✔ Full DB exception coverage
    ✔ Enterprise-grade error handling

    Validation Responsibility:
    --------------------------
    1. Schema-Level (Pydantic - GSTRegistrationEditIn)
    2. Database-Level:
       - UNIQUE constraints
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

            # Always update timestamp
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

            # --------------------------------------------------
            # Transaction (Atomic Update)
            # --------------------------------------------------
            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            # --------------------------------------------------
            # Not Found Handling
            # --------------------------------------------------
            if not row:
                log.warning("GST registration not found for update | gstin=%s", gstin)
                raise HTTPException(
                    status_code=404,
                    detail="GST registration not found.",
                )

            log.info(
                "GST updated successfully | gstin=%s | updated_fields=%s",
                gstin,
                list(update_data.keys()),
            )

            return {
                **dict(row),
                "message": "GST registration updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DATABASE EXCEPTION HANDLING (Full Coverage)
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
# SOFT DELETE GST REGISTRATION (is_active = false)
# =========================================================

@router.delete(
    "/{gstin}/soft_delete",
    summary="Soft delete GST registration by setting is_active to false",
    responses={
        200: {"description": "GST registration soft deleted successfully."},
        400: {"description": "GST registration already inactive."},
        404: {"description": "GST registration not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_gst_registration(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete GST registration by updating is_active to FALSE.

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
        {"request_id": request_id, "emp_id": current_emp_id, "api": "soft_delete_gst"},
    )

    log.info("Incoming soft delete GST request | gstin=%s", gstin)

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception(
            "Database pool acquisition failed during GST soft delete | error=%s",
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
                UPDATE {DB_SCHEMA}.gst_registration
                   SET is_active = FALSE,
                       updated_at = NOW()
                 WHERE gstin = $1
                   AND is_active = TRUE
                 RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(sql, gstin)

            # --------------------------------------------------
            # Not Found / Already Deleted Handling
            # --------------------------------------------------
            if not row:
                # Check existence separately
                check_sql = f"""
                    SELECT gstin, is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE gstin = $1
                """
                existing = await conn.fetchrow(check_sql, gstin)

                if not existing:
                    log.warning(
                        "GST registration not found for soft delete | gstin=%s",
                        gstin,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                if existing["is_active"] is False:
                    log.warning(
                        "GST registration already inactive | gstin=%s",
                        gstin,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration is already inactive.",
                    )

            log.info(
                "GST registration soft deleted successfully | gstin=%s",
                gstin,
            )

            return {
                **dict(row),
                "message": "GST registration soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DATABASE EXCEPTION HANDLING (Production Grade)
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
