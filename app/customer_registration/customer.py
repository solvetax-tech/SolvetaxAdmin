import logging
import uuid
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import constr, validator
from typing import Optional, List
from datetime import datetime
from app.customer_registration.schemas import CustomerIn, CustomerEditIn, CustomerOut
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import require_permission
from app.logger import logger
from app.utils import mask_sensitive_data,generate_uuid
import json
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(
    prefix="/api/v1/customers",
    tags=["Customers"]
)
#--------------------------------------------------------------
# CREATE CUSTOMER (is_active DEFAULT = TRUE at DB level)
#--------------------------------------------------------------
@router.post(
    "",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Customer",
)
async def create_customer(
    payload: CustomerIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Customer (Production Standard + Version Audit)

    ✔ Atomic transaction (Customer + Version)
    ✔ entity_type = 'CUSTOMER'
    ✔ entity_id = 1 (default)
    ✔ action = 'CREATE'
    ✔ json populated
    ✔ updated_json = NULL
    ✔ Structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if emp_id_raw else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    masked_email = mask_sensitive_data(payload.email)
    masked_mobile = mask_sensitive_data(payload.mobile)

    log.info(
        "Incoming create customer request | email=%s mobile=%s",
        masked_email,
        masked_mobile,
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
                # 1️⃣ Insert Customer
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.customers
                    (
                        full_name, email, mobile, business_name,
                        business_description, business_image_url,
                        business_type, state, city, remark,
                        rm_id, op_id, referral_id
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13
                    )
                    RETURNING *
                """

                customer_row = await conn.fetchrow(
                    insert_sql,
                    payload.full_name,
                    payload.email,
                    payload.mobile,
                    payload.business_name,
                    payload.business_description,
                    str(payload.business_image_url)
                    if payload.business_image_url
                    else None,
                    payload.business_type,
                    payload.state,
                    payload.city,
                    payload.remark,
                    payload.rm_id,
                    payload.op_id,
                    payload.referral_id,
                )

                if not customer_row:
                    log.error("Customer creation failed - no row returned")
                    raise HTTPException(
                        status_code=500,
                        detail="Customer creation failed.",
                    )

                customer_id = customer_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Insert Version Audit (INLINE)
                # --------------------------------------------------
                version_sql = f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "CUSTOMER",
                    1,
                    customer_id,
                    "CREATE",
                    json.dumps(dict(customer_row), default=str),
                    None,
                )

            log.info(
                "Customer created successfully with audit | customer_id=%s",
                customer_id,
            )

            response_data = dict(customer_row)
            response_data["message"] = "Customer created successfully."
            return response_data

        # --------------------------------------------------
        # Exception Handling (Production Grade)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate customer detected")
            raise HTTPException(
                status_code=409,
                detail="Customer already exists.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference (rm_id/op_id)")
            raise HTTPException(
                status_code=400,
                detail="Invalid rm_id or op_id.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during customer creation | error=%s",
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
            log.exception("Unexpected error during customer creation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

# -------------------------------------------------------------------
# LIST CUSTOMERS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

from fastapi import Request
@router.get(
    "/customer_get/filter",
    summary="Filter Customers",
)
async def filter_customers(
    customer_id: Optional[int] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    business_type: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Filter Customers API (RBAC REMOVED - Same as Employee Filter)

    Validation Responsibility Split:
    --------------------------------
    1️⃣ FastAPI:
        - Type validation
        - Pagination limits

    2️⃣ Database:
        - Filtering logic only (no RBAC restrictions)
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming customer filter request limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # Date Sanity Validation (IDENTICAL to employee_get)
    # --------------------------------------------------
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

        # --------------------------------------------------
        # Business Filters (SAME PATTERN AS employee_get)
        # --------------------------------------------------

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if full_name and full_name.strip():
            conditions.append(f"full_name ILIKE ${param_index}")
            values.append(f"%{full_name.strip()}%")
            param_index += 1

        if email and email.strip():
            conditions.append(f"email ILIKE ${param_index}")
            values.append(f"%{email.strip()}%")
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        if business_type:
            conditions.append(f"business_type = ${param_index}")
            values.append(business_type)
            param_index += 1

        if state:
            conditions.append(f"state = ${param_index}")
            values.append(state)
            param_index += 1

        if city:
            conditions.append(f"city = ${param_index}")
            values.append(city)
            param_index += 1

        if rm_id is not None:
            conditions.append(f"rm_id = ${param_index}")
            values.append(rm_id)
            param_index += 1

        if op_id is not None:
            conditions.append(f"op_id = ${param_index}")
            values.append(op_id)
            param_index += 1

        # --------------------------------------------------
        # Status Filtering (IDENTICAL to employee_get)
        # --------------------------------------------------
        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filtering (IDENTICAL to employee_get)
        # --------------------------------------------------

        if from_date:
            if from_date.tzinfo is None:
                from_date = from_date.replace(tzinfo=IST)
        else:
            from_date = from_date.astimezone(IST)
        conditions.append(f"created_at >= ${param_index}")
        values.append(from_date)
        param_index += 1

        if to_date:
            if to_date.tzinfo is None:
                to_date = to_date.replace(tzinfo=IST)
        else:
            to_date = to_date.astimezone(IST)
        conditions.append(f"created_at <= ${param_index}")
        values.append(to_date)
        param_index += 1


        # --------------------------------------------------
        # WHERE Clause Builder (EXACT SAME AS employee_get)
        # --------------------------------------------------
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.customers
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("Customers filtered successfully count=%s", len(rows))

        return [
            {**dict(row), "message": "Customers filtered successfully."}
            for row in rows
        ]

    # --------------------------------------------------
    # DB VALIDATIONS (IDENTICAL to employee_get)
    # --------------------------------------------------
    except asyncpg.PostgresError:
        log.exception("Database error during customer filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error during customer filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )



# -------------------------------------------------------------------
# GET CUSTOMER BY ID
# -------------------------------------------------------------------
@router.get(
    "/{customer_id}",
    summary="Get Customer",
)
async def get_customer(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Customer by ID (Production Standard)

    Validation Responsibility Split:
    --------------------------------
    1. Authentication & Authorization via dependency
    2. Path param type validation handled by FastAPI
    3. Existence validation handled by DB query
    """

    # --------------------------------------------------
    # Request Context & Structured Logging (Aligned)
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming get customer request customer_id=%s",
        customer_id,
    )

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
         WHERE customer_id = $1
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
            row = await conn.fetchrow(sql, customer_id)

        # --------------------------------------------------
        # Not Found Handling (Consistent Style)
        # --------------------------------------------------
        if not row:
            log.warning(
                "Customer not found customer_id=%s",
                customer_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Customer not found.",
            )

        log.info(
            "Customer fetched successfully customer_id=%s",
            customer_id,
        )

        # Return raw dict with message (same style as filter/list APIs)
        return {
            **dict(row),
            "message": "Customer fetched successfully.",
        }

    # --------------------------------------------------
    # IMPORTANT: Re-raise HTTP Exceptions First
    # --------------------------------------------------
    except HTTPException:
        raise

    # --------------------------------------------------
    # DATABASE ERROR HANDLING (Improved)
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during get customer customer_id=%s error=%s",
            customer_id,
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
            "Unexpected error during get customer customer_id=%s",
            customer_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# --------------------------------------------------------------
# EDIT CUSTOMER (WITH FULL VERSION AUDIT - ENTERPRISE READY)
# --------------------------------------------------------------

@router.post(
    "/{customer_id}/customer-dyn/edit",
    summary="Edit Customer (Dynamic Update + Version Audit - Production Ready)",
)
async def edit_customer(
    customer_id: int,
    payload: CustomerEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Enterprise-Grade Dynamic Customer Update API with Version Audit

    ✔ Dynamic PATCH-style update
    ✔ OLD snapshot stored in versions.json
    ✔ NEW snapshot stored in versions.updated_json
    ✔ Atomic transaction (update + audit)
    ✔ Full asyncpg exception coverage
    ✔ Structured logging
    ✔ Safe SQL parameterization
    ✔ Datetime-safe JSON serialization
    """

    # --------------------------------------------------
    # Request Context & Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    # Safe emp_id conversion
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_customer",
        },
    )

    log.info(
        "Incoming edit customer request | customer_id=%s",
        customer_id,
    )

    # --------------------------------------------------
    # Extract Provided Fields
    # --------------------------------------------------
    try:
        update_data: Dict[str, Any] = payload.model_dump(exclude_unset=True)
    except Exception as e:
        log.exception(
            "Failed to serialize payload | customer_id=%s | error=%s",
            customer_id,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        log.warning(
            "No fields provided for update | customer_id=%s",
            customer_id,
        )
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

        if "phone_number" in update_data and update_data["phone_number"]:
            update_data["phone_number"] = update_data["phone_number"].strip()

        # Convert URL fields
        url_fields = ["business_image_url", "website_url"]
        for field in url_fields:
            if field in update_data and update_data[field]:
                update_data[field] = str(update_data[field])

    except Exception as e:
        log.exception(
            "Error during normalization | customer_id=%s | payload=%s | error=%s",
            customer_id,
            update_data,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid field values provided.",
        )

    # --------------------------------------------------
    # Database Pool
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
                # 1️⃣ Fetch OLD Snapshot
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                     LIMIT 1
                    """,
                    customer_id,
                )

                if not old_row:
                    log.warning(
                        "Customer not found for update | customer_id=%s",
                        customer_id,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="Customer not found.",
                    )

                # --------------------------------------------------
                # 2️⃣ Build Dynamic UPDATE Query
                # --------------------------------------------------
                fields = []
                values = []
                param_index = 1

                for field_name, value in update_data.items():
                    fields.append(f"{field_name} = ${param_index}")
                    values.append(value)
                    param_index += 1

                fields.append("updated_at = NOW()")

                update_sql = f"""
                    UPDATE {DB_SCHEMA}.customers
                       SET {', '.join(fields)}
                     WHERE customer_id = ${param_index}
                     RETURNING *
                """

                values.append(customer_id)

                log.debug(
                    "Executing update | customer_id=%s | fields=%s",
                    customer_id,
                    list(update_data.keys()),
                )

                new_row = await conn.fetchrow(update_sql, *values)

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
                    "CUSTOMER",
                    1,
                    customer_id,
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Customer updated successfully with audit | customer_id=%s",
                customer_id,
            )

            return {
                **dict(new_row),
                "message": "Customer updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # FULL DATABASE EXCEPTION COVERAGE
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            log.warning(
                "Unique constraint violation | customer_id=%s | payload=%s | error=%s",
                customer_id,
                update_data,
                str(e),
            )
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.warning(
                "Foreign key violation | customer_id=%s | payload=%s | error=%s",
                customer_id,
                update_data,
                str(e),
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.warning(
                "Check constraint violation | customer_id=%s | error=%s",
                customer_id,
                str(e),
            )
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError as e:
            log.warning(
                "NOT NULL constraint violation | customer_id=%s | error=%s",
                customer_id,
                str(e),
            )
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError as e:
            log.error(
                "Invalid data format | customer_id=%s | error=%s",
                customer_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Postgres error during update | customer_id=%s | error=%s",
                customer_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception as e:
            log.exception(
                "Unexpected error during customer update | customer_id=%s | error=%s",
                customer_id,
                str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# =========================================================
# SOFT DELETE CUSTOMER (is_active = false) WITH VERSION AUDIT
# =========================================================

@router.delete(
    "/{customer_id}/soft_delete",
    summary="Soft delete customer by setting is_active to false (With Audit)",
)
async def soft_delete_customer(
    customer_id: int,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    Soft Delete Customer with Version Audit

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
            "api": "soft_delete_customer",
        },
    )

    log.info(
        "Incoming soft delete customer request | customer_id=%s",
        customer_id,
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
                    UPDATE {DB_SCHEMA}.customers
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE customer_id = $1
                       AND is_active = TRUE
                     RETURNING *
                """

                deleted_row = await conn.fetchrow(delete_sql, customer_id)

                if not deleted_row:
                    # Check existence separately
                    check_row = await conn.fetchrow(
                        f"""
                        SELECT customer_id, is_active
                          FROM {DB_SCHEMA}.customers
                         WHERE customer_id = $1
                        """,
                        customer_id,
                    )

                    if not check_row:
                        log.warning("Customer not found | customer_id=%s", customer_id)
                        raise HTTPException(
                            status_code=404,
                            detail="Customer not found.",
                        )

                    log.warning(
                        "Customer already inactive | customer_id=%s",
                        customer_id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Customer already inactive.",
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

                # NEW state snapshot (is_active = FALSE)
                deleted_snapshot = dict(deleted_row)

                await conn.execute(
                    version_sql,
                    emp_id,
                    "CUSTOMER",                     # entity_type
                    1,                              # entity_id (your default)
                    customer_id,
                    "DELETE",
                    None,                           # json must be NULL
                    json.dumps(deleted_snapshot, default=str),  # updated_json
                )

            log.info(
                "Customer soft deleted successfully with audit | customer_id=%s",
                customer_id,
            )

            return {
                **dict(deleted_row),
                "message": "Customer soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # FULL DATABASE EXCEPTION COVERAGE
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.error(
                "Foreign key violation during soft delete | "
                "customer_id=%s | error=%s",
                customer_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.error(
                "Audit constraint violation | "
                "customer_id=%s | error=%s",
                customer_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Audit constraint validation failed.",
            )

        except asyncpg.exceptions.DataError as e:
            log.error(
                "Data error during soft delete | "
                "customer_id=%s | error=%s",
                customer_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during soft delete | "
                "customer_id=%s | error=%s",
                customer_id,
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
                "Unexpected error during soft delete | "
                "customer_id=%s | error=%s",
                customer_id,
                str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
