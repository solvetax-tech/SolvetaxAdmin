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
              FROM {DB_SCHEMA}.customers c
              {where_clause.replace('WHERE ', 'WHERE c.').replace(' AND ', ' AND c.') if where_clause else ""}
        """

        # --------------------------------------------------
        # Main Query
        # --------------------------------------------------

        main_sql = f"""
            SELECT c.*, 
                   e_rm.first_name as rm_name,
                   e_op.first_name as op_name
              FROM {DB_SCHEMA}.customers c
              LEFT JOIN {DB_SCHEMA}.employees e_rm ON c.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_op ON c.op_id = e_op.emp_id
              {where_clause.replace('WHERE ', 'WHERE c.').replace(' AND ', ' AND c.') if where_clause else ""}
             ORDER BY c.created_at DESC
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
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    ✔ Safe PATCH-style dynamic update
    ✔ Row-level locking
    ✔ Version audit
    ✔ Strict whitelist
    ✔ Atomic transaction
    ✔ text[] handling
    ✔ Full asyncpg exception coverage
    ✔ Prevent editing inactive customers
    """

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
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Whitelist Protection
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
        "services",
    }

    invalid_fields = set(update_data.keys()) - allowed_fields
    if invalid_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fields provided: {', '.join(invalid_fields)}",
        )

    # --------------------------------------------------
    # Normalize services for PostgreSQL text[]
    # --------------------------------------------------
    if "services" in update_data:
        services_value = update_data["services"]

        if services_value is None:
            update_data["services"] = []
        else:
            if not isinstance(services_value, list):
                raise HTTPException(
                    status_code=400,
                    detail="services must be a list of strings.",
                )

            cleaned_services = []
            for s in services_value:
                if not isinstance(s, str):
                    raise HTTPException(
                        status_code=400,
                        detail="Each service must be a string.",
                    )
                s = s.strip()
                if s:
                    cleaned_services.append(s)

            update_data["services"] = list(dict.fromkeys(cleaned_services))

    # --------------------------------------------------
    # Database Transaction
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # 1️⃣ Lock Row
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
                # Prevent Editing Inactive Customers
                # --------------------------------------------------
                if not old_row.get("is_active"):
                    log.warning(
                        "Edit blocked because customer is inactive | customer_id=%s",
                        customer_id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Customer is inactive. Activate the customer first and then edit.",
                    )

                # 2️⃣ Build Dynamic Update
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

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Customer state changed. Please retry.",
                    )

                # 3️⃣ Version Audit
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

            log.info("Customer updated successfully | customer_id=%s", customer_id)

            return {
                **dict(new_row),
                "message": "Customer updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Exception Handling
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
                detail=f"Constraint violation: {getattr(e, 'constraint_name', '')}",
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
            log.exception("Database error during update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
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
# SOFT DELETE CUSTOMER (Customer-First Mode + Conditional Cascade)
# =========================================================

@router.delete(
    "/{customer_id}/soft_delete",
    summary="Soft delete customer with conditional GST cascade",
    responses={
        200: {"description": "Customer deactivated successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "Customer not found."},
        500: {"description": "Internal server error."},
    },
)
async def soft_delete_customer(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete customer conditionally based on ACTIVE GST count.

    ✔ If 0 GST → Deactivate customer only
    ✔ If 1 GST → Full cascade deactivate
    ✔ If >1 GST → DO NOT deactivate customer (block operation)
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
            "api": "conditional_customer_soft_delete",
        },
    )

    log.info("Incoming customer soft delete | customer_id=%s", customer_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
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
                # 2️⃣ Count ACTIVE GSTs
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

                gst_id = None

                # --------------------------------------------------
                # 3️⃣ GST Handling Logic
                # --------------------------------------------------
                if gst_count == 1:

                    gst_row = await conn.fetchrow(
                        f"""
                        SELECT *
                          FROM {DB_SCHEMA}.gst_registration
                         WHERE customer_id = $1
                           AND is_active = TRUE
                         FOR UPDATE
                        """,
                        customer_id,
                    )

                    if not gst_row:
                        raise HTTPException(
                            409,
                            "GST state changed. Please retry.",
                        )

                    gst_id = gst_row["id"]

                elif gst_count > 1:
                    # 🔥 NEW RULE: BLOCK CUSTOMER DEACTIVATION
                    raise HTTPException(
                        400,
                        "Cannot deactivate customer. Customer has multiple active GST registrations. "
                        "Please deactivate GSTs individually from GST Registration page first.Only customers with no gstin and customers with 1 gstin are allowed to deactiavte from here",
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
                # 5️⃣ If Exactly ONE GST → Cascade Deactivation
                # --------------------------------------------------
                if gst_id:

                    # Deactivate GST
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration
                           SET is_active = FALSE,
                               updated_at = NOW()
                         WHERE id = $1
                        """,
                        gst_id,
                    )

                    # Deactivate Persons
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_persons
                           SET is_active = FALSE,
                               updated_at = NOW()
                         WHERE gst_registration_id = $1
                        """,
                        gst_id,
                    )

                    # Deactivate Documents
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_documents d
                           SET is_active = FALSE,
                               updated_at = NOW()
                          FROM {DB_SCHEMA}.gst_registration_persons p
                         WHERE d.person_id = p.person_id
                           AND p.gst_registration_id = $1
                        """,
                        gst_id,
                    )

                # --------------------------------------------------
                # 6️⃣ Version Audit (CUSTOMER ONLY)
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

            # --------------------------------------------------
            # Response Handling
            # --------------------------------------------------
            if gst_id:
                message = "Customer and associated GST, persons and documents fully deactivated."
            else:
                message = "Customer deactivated successfully."

            log.info(
                "Customer soft delete completed | customer_id=%s | gst_id=%s | gst_count=%s",
                customer_id,
                gst_id,
                gst_count,
            )

            return {
                "customer_id": customer_id,
                "gst_id": gst_id,
                "gst_count": gst_count,
                "message": message,
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
# ACTIVATE CUSTOMER (Customer-First Mode + Conditional Cascade)
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
    Activate customer conditionally based on GST count.

    ✔ If 0 GST → Activate customer only
    ✔ If 1 GST → Full cascade activation
    ✔ If >1 GST → Activate customer only + instruct manual GST activation
    ✔ Atomic transaction
    ✔ Concurrency safe (FOR UPDATE locking)
    ✔ Version audit (CUSTOMER only)
    ✔ Structured logging
    """

    # --------------------------------------------------
    # 1️⃣ Request Context
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
    # 2️⃣ DB Pool
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
                # 3️⃣ Lock Customer Row (Concurrency Safe)
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
                        detail=(
                            "Customer is already active. "
                            "Check GST Registration and activate it there if there are two gstins to this customer."
                        ),
                    )

                # --------------------------------------------------
                # 4️⃣ Count GST Registrations
                # --------------------------------------------------
                gst_count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                    """,
                    customer_id,
                )

                gst_id = None
                manual_gst_activation_required = False

                # --------------------------------------------------
                # 5️⃣ GST Handling Logic
                # --------------------------------------------------
                if gst_count == 1:

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
                            status_code=409,
                            detail="GST state changed. Please retry.",
                        )

                    gst_id = gst_row["id"]

                elif gst_count > 1:
                    manual_gst_activation_required = True

                # --------------------------------------------------
                # 6️⃣ Activate Customer
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
                # 7️⃣ If Exactly ONE GST → Cascade Activation
                # --------------------------------------------------
                if gst_id:

                    # Activate GST
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration
                           SET is_active = TRUE,
                               updated_at = NOW()
                         WHERE id = $1
                        """,
                        gst_id,
                    )

                    # Activate Persons
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_persons
                           SET is_active = TRUE,
                               updated_at = NOW()
                         WHERE gst_registration_id = $1
                        """,
                        gst_id,
                    )

                    # Activate Documents
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_documents d
                           SET is_active = TRUE,
                               updated_at = NOW()
                          FROM {DB_SCHEMA}.gst_registration_persons p
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

            # --------------------------------------------------
            # 9️⃣ Response
            # --------------------------------------------------
            if gst_id:
                message = (
                    "Customer and associated GST, persons, and documents "
                    "activated successfully."
                )
            elif manual_gst_activation_required:
                message = (
                    "Customer activated successfully. "
                    "Multiple GST registrations detected. "
                    "Please activate the required GST registrations individually "
                    "from the GST Registration page."
                )
            else:
                message = "Customer activated successfully."

            log.info(
                "Customer activation completed | customer_id=%s | gst_id=%s | gst_count=%s",
                customer_id,
                gst_id,
                gst_count,
            )

            return {
                "customer_id": customer_id,
                "gst_id": gst_id,
                "gst_count": gst_count,
                "message": message,
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