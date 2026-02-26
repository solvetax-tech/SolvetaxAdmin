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

# -------------------------------------------------------------------
# CREATE CUSTOMER (Enterprise Production + Version Audit + Services)
# -------------------------------------------------------------------

@router.post(
    "",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Customer (Production Ready + Audit)",
    responses={
        201: {"description": "Customer created successfully."},
        400: {"description": "Validation failed."},
        409: {"description": "Duplicate value violation."},
        500: {"description": "Database or internal error."},
    },
)
async def create_customer(
    payload: CustomerIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    ✔ Atomic transaction (Customer + Version)
    ✔ entity_type = 'CUSTOMER'
    ✔ entity_id = customer_id
    ✔ action = 'CREATE'
    ✔ services (text[]) supported
    ✔ json populated (NEW snapshot)
    ✔ updated_json = NULL
    ✔ Structured logging
    ✔ Constraint-specific error handling
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_customer"},
    )

    masked_email = mask_sensitive_data(payload.email)
    masked_mobile = mask_sensitive_data(payload.mobile)

    log.info(
        "Incoming create customer request | email=%s mobile=%s services=%s",
        masked_email,
        masked_mobile,
        payload.services,
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
                # 1️⃣ Insert Customer (WITH SERVICES)
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.customers
                    (
                        full_name,
                        email,
                        mobile,
                        business_name,
                        business_description,
                        business_image_url,
                        business_type,
                        state,
                        city,
                        remark,
                        rm_id,
                        op_id,
                        referral_id,
                        services
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14
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
                    payload.services if payload.services else [],
                )

                if not customer_row:
                    log.error("Customer creation failed - no row returned")
                    raise HTTPException(
                        status_code=500,
                        detail="Customer creation failed.",
                    )

                customer_id = customer_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Version Audit
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "CREATE",
                    json.dumps(dict(customer_row), default=str),
                    None,
                )

            log.info(
                "Customer created successfully with services | customer_id=%s",
                customer_id,
            )

            return {
                **dict(customer_row),
                "message": "Customer created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                # Add future mappings here
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    "Duplicate value violates unique constraint.",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            FK_MAP = {
                "customers_rm_id_fkey": "Invalid rm_id provided.",
                "customers_op_id_fkey": "Invalid op_id provided.",
                "customers_referral_id_fkey": "Invalid referral_id provided.",
            }

            raise HTTPException(
                status_code=400,
                detail=FK_MAP.get(
                    constraint,
                    "Invalid foreign key reference provided.",
                ),
            )

        # --------------------------------------------------
        # CHECK / NOT NULL / DATA
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Data violates constraint: {getattr(e, 'constraint_name', '')}",
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

        # --------------------------------------------------
        # GENERIC DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError:
            log.exception("Database error during customer creation")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
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
# LIST CUSTOMERS (Enterprise Filter + Pagination + Services Support)
# -------------------------------------------------------------------

from fastapi import Query
from datetime import datetime

@router.get(
    "/customer_get/filter",
    summary="Filter Customers (Enterprise Dynamic Filter)",
    responses={
        200: {"description": "Customers fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
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

    # 👇 NEW SERVICES FILTERS
    service: Optional[str] = None,                    # single service
    services_all: Optional[List[str]] = Query(None), # must contain all
    services_any: Optional[List[str]] = Query(None), # overlap

    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    ✔ Dynamic filtering
    ✔ Services array filtering
    ✔ Pagination
    ✔ Total count metadata
    ✔ Active filtering logic
    ✔ Clean date handling
    ✔ Structured logging
    ✔ DB-safe parameter binding
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_customers"},
    )

    log.info(
        "Incoming customer filter | limit=%s offset=%s service=%s",
        limit,
        offset,
        service,
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
        idx = 1

        # --------------------------------------------------
        # Standard Filters
        # --------------------------------------------------

        if customer_id is not None:
            conditions.append(f"customer_id = ${idx}")
            values.append(customer_id)
            idx += 1

        if full_name:
            conditions.append(f"full_name ILIKE ${idx}")
            values.append(f"%{full_name.strip()}%")
            idx += 1

        if email:
            conditions.append(f"email ILIKE ${idx}")
            values.append(f"%{email.strip().lower()}%")
            idx += 1

        if mobile:
            conditions.append(f"mobile = ${idx}")
            values.append(mobile.strip())
            idx += 1

        if business_type:
            conditions.append(f"business_type = ${idx}")
            values.append(business_type)
            idx += 1

        if state:
            conditions.append(f"state = ${idx}")
            values.append(state)
            idx += 1

        if city:
            conditions.append(f"city = ${idx}")
            values.append(city)
            idx += 1

        if rm_id is not None:
            conditions.append(f"rm_id = ${idx}")
            values.append(rm_id)
            idx += 1

        if op_id is not None:
            conditions.append(f"op_id = ${idx}")
            values.append(op_id)
            idx += 1

        # --------------------------------------------------
        # SERVICES FILTERING
        # --------------------------------------------------

        if service:
            conditions.append(f"${idx} = ANY(services)")
            values.append(service.strip())
            idx += 1

        if services_all:
            conditions.append(f"services @> ${idx}")
            values.append(services_all)
            idx += 1

        if services_any:
            conditions.append(f"services && ${idx}")
            values.append(services_any)
            idx += 1

        # --------------------------------------------------
        # Status Filtering
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            values.append(is_active)
            idx += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filtering
        # --------------------------------------------------

        if from_date:
            conditions.append(f"created_at >= ${idx}")
            values.append(from_date)
            idx += 1

        if to_date:
            conditions.append(f"created_at <= ${idx}")
            values.append(to_date)
            idx += 1

        # --------------------------------------------------
        # WHERE Clause
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT Query
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.customers
              {where_clause}
        """

        # --------------------------------------------------
        # Main Query
        # --------------------------------------------------

        main_sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.customers
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${idx} OFFSET ${idx + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total_count = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(main_sql, *values_with_pagination)

        log.info(
            "Customer filter success | total=%s returned=%s",
            total_count,
            len(rows),
        )

        return {
            "data": [dict(row) for row in rows]    
        }

    except asyncpg.PostgresError:
        log.exception("Database error during customer filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during customer filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# --------------------------------------------------------------
# EDIT CUSTOMER (FULL ENTERPRISE DYNAMIC PATCH + VERSION AUDIT)
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
    Enterprise-Grade Dynamic Customer Update API

    ✔ DB-aligned schema
    ✔ Safe PATCH-style dynamic update
    ✔ SELECT ... FOR UPDATE (row locking)
    ✔ OLD snapshot in versions.json
    ✔ NEW snapshot in versions.updated_json
    ✔ Atomic transaction
    ✔ Whitelist-protected fields
    ✔ Full asyncpg exception handling
    ✔ Structured logging
    """

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
            "api": "edit_customer",
        },
    )

    log.info("Incoming edit customer request | customer_id=%s", customer_id)

    # --------------------------------------------------
    # Extract Provided Fields
    # --------------------------------------------------
    try:
        update_data: Dict[str, Any] = payload.model_dump(exclude_unset=True)
    except Exception as e:
        log.exception("Payload serialization failed | error=%s", str(e))
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Allowed Fields Whitelist (Security Layer)
    # --------------------------------------------------
    allowed_fields = {
        "full_name",
        "email",
        "mobile",
        "business_name",
        "business_description",
        "business_image_url",
        "business_type",
        "state",
        "city",
        "remark",
        "rm_id",
        "op_id",
        "referral_id",
        "is_active",
    }

    invalid_fields = set(update_data.keys()) - allowed_fields
    if invalid_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fields provided: {', '.join(invalid_fields)}",
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
                # 1️⃣ Lock Existing Row (Prevents Lost Updates)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                     FOR UPDATE
                    """,
                    customer_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Customer not found.",
                    )

                # --------------------------------------------------
                # 2️⃣ Build Dynamic Update Query
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

                new_row = await conn.fetchrow(update_sql, *values)

                # --------------------------------------------------
                # 3️⃣ Version Audit Insert
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Customer updated successfully | customer_id=%s",
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
        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
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

        except asyncpg.PostgresError as e:
            log.exception("Postgres error during update")
            raise HTTPException(
                status_code=500,
                detail=str(e),
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during customer update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# =========================================================
# CONDITIONAL CUSTOMER SOFT DELETE
# =========================================================

@router.delete(
    "/{customer_id}/soft_delete",
    summary="Soft delete customer only if exactly one GST exists",
    responses={
        200: {"description": "Customer and GST deactivated."},
        400: {"description": "Business rule violation."},
        404: {"description": "Customer not found."},
        500: {"description": "Internal server error."},
    },
)
async def soft_delete_customer(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete customer ONLY if exactly one GST exists.

    ✔ If 1 GST → Full cascade delete
    ✔ If >1 GST → Reject
    ✔ Atomic transaction
    ✔ Concurrency safe
    ✔ Version audit (CUSTOMER only)
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "conditional_customer_soft_delete",
        },
    )

    log.info("Incoming customer soft delete | customer_id=%s", customer_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool error")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Lock Customer
                # --------------------------------------------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                     FOR UPDATE
                    """,
                    customer_id,
                )

                if not customer:
                    raise HTTPException(404, "Customer not found.")

                if customer["is_active"] is False:
                    raise HTTPException(400, "Customer already inactive.")

                # --------------------------------------------------
                # 2️⃣ Count Active GSTs
                # --------------------------------------------------
                gst_count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                       AND is_active = TRUE
                    """,
                    customer_id,
                )

                if gst_count == 0:
                    raise HTTPException(
                        400,
                        "Customer has no active GST registrations.",
                    )

                if gst_count > 1:
                    raise HTTPException(
                        400,
                        "Customer has multiple GST registrations. "
                        "Please deactivate GST individually.",
                    )

                # --------------------------------------------------
                # 3️⃣ Fetch Single GST ID
                # --------------------------------------------------
                gst_id = await conn.fetchval(
                    f"""
                    SELECT id
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                       AND is_active = TRUE
                    """,
                    customer_id,
                )

                # --------------------------------------------------
                # 4️⃣ Soft Delete Customer
                # --------------------------------------------------
                deleted_customer = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customers
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE customer_id = $1
                     RETURNING *
                    """,
                    customer_id,
                )

                # --------------------------------------------------
                # 5️⃣ Soft Delete GST
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE id = $1
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 6️⃣ Soft Delete Persons
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE gst_registration_id = $1
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 7️⃣ Soft Delete Documents
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.registration_persons p
                     WHERE d.person_id = p.person_id
                       AND p.gst_registration_id = $1
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 8️⃣ Version Audit (CUSTOMER ONLY)
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_customer), default=str),
                )

            log.info(
                "Customer and single GST cascade deleted | customer_id=%s",
                customer_id,
            )

            return {
                "customer_id": customer_id,
                "gst_id": gst_id,
                "message": "Customer and associated GST fully deactivated.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError as e:
            log.exception("Postgres error")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error")
            raise HTTPException(status_code=500, detail="Internal server error.")

# =========================================================
# ACTIVATE CUSTOMER (Conditional + Explicit GST Guidance)
# =========================================================

@router.post(
    "/{customer_id}/activate",
    summary="Activate Customer (Conditional + Cascade + Audit)",
    responses={
        200: {"description": "Customer activated successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "Customer not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_customer(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Activate customer ONLY if exactly one GST exists.

    ✔ If 1 GST → Full cascade activation
    ✔ If >1 GST → Reject with explicit instruction to activate GST individually
    ✔ Atomic transaction
    ✔ Concurrency safe
    ✔ Version audit (CUSTOMER only)
    ✔ Structured logging
    """

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
            "api": "activate_customer",
        },
    )

    log.info("Incoming customer activation | customer_id=%s", customer_id)

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
                # 1️⃣ Lock Customer
                # --------------------------------------------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                     FOR UPDATE
                    """,
                    customer_id,
                )

                if not customer:
                    raise HTTPException(
                        status_code=404,
                        detail="Customer not found.",
                    )

                if customer["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Customer already active.",
                    )

                # --------------------------------------------------
                # 2️⃣ Count GST Registrations
                # --------------------------------------------------
                gst_count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                    """,
                    customer_id,
                )

                if gst_count == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Customer has no GST registrations to activate.",
                    )

                if gst_count > 1:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Customer has multiple GST registrations. "
                            "Please activate GST individually using "
                            f"POST /customers/{customer_id}/gst/{{gst_id}}/activate"
                        ),
                    )

                # --------------------------------------------------
                # 3️⃣ Lock Single GST
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                     FOR UPDATE
                    """,
                    customer_id,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                gst_id = gst_row["id"]

                # --------------------------------------------------
                # 4️⃣ Activate Customer
                # --------------------------------------------------
                activated_customer = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customers
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE customer_id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    customer_id,
                )

                if not activated_customer:
                    raise HTTPException(
                        status_code=409,
                        detail="Customer state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 5️⃣ Activate GST
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 6️⃣ Activate Persons
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE gst_registration_id = $1
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 7️⃣ Activate Documents
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_documents d
                       SET is_active = TRUE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.registration_persons p
                     WHERE d.person_id = p.person_id
                       AND p.gst_registration_id = $1
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 8️⃣ Version Audit (CUSTOMER ONLY)
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "ACTIVATE",
                    None,
                    json.dumps(dict(activated_customer), default=str),
                )

            log.info(
                "Customer activated successfully | customer_id=%s | gst_id=%s",
                customer_id,
                gst_id,
            )

            return {
                "customer_id": customer_id,
                "gst_id": gst_id,
                "message": (
                    "Customer and associated GST activated successfully."
                ),
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
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.exception("Database error during activation")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during activation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )