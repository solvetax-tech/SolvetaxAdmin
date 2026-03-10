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
    ✔ service_required / service_provided supported
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
        "Incoming create customer request | email=%s mobile=%s service_required=%s service_provided=%s",
        masked_email,
        masked_mobile,
        payload.service_required,
        payload.service_provided,
    )

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            },
        )

    async with pool.acquire() as conn:
        try:
            # --------------------------------------------------
            # PROACTIVE DUPLICATE CHECK
            # --------------------------------------------------
            duplicate_row = await conn.fetchrow(
                f"""
                SELECT 
                    EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE email = $1) AS email_match,
                    EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE mobile = $2) AS mobile_match
                """,
                payload.email,
                payload.mobile
            )

            field_errors = {}
            if duplicate_row["email_match"]:
                field_errors["email"] = "Email already exists."
            if duplicate_row["mobile_match"]:
                field_errors["mobile"] = "Mobile number already exists."

            if field_errors:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "type": "validation_error",
                            "message": "Validation failed",
                            "fields": field_errors
                        }
                    }
                )

            async with conn.transaction():

                # --------------------------------------------------
                # Normalize Service Arrays
                # --------------------------------------------------

                service_required = payload.service_required or []
                service_provided = payload.service_provided or []

                # --------------------------------------------------
                # 1️⃣ Insert Customer
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
                        service_required,
                        service_provided
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15
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
                    service_required,
                    service_provided,
                )

                if not customer_row:
                    log.error("Customer creation failed - no row returned")
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": {
                                "type": "server_error",
                                "message": "Customer creation failed.",
                                "fields": {}
                            }
                        },
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
                "Customer created successfully | customer_id=%s",
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

            field_errors = {}
            if constraint == "uq_customers_mobile":
                field_errors["mobile"] = "Mobile number already exists."
            elif constraint == "uq_customers_email":
                field_errors["email"] = "Email already exists."

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Duplicate value violation."}
                    }
                },
            )

        # --------------------------------------------------
        # FOREIGN KEY HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            field_errors = {}
            if constraint == "customers_rm_id_fkey":
                field_errors["rm_id"] = "Invalid rm_id provided."
            elif constraint == "customers_op_id_fkey":
                field_errors["op_id"] = "Invalid op_id provided."

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Invalid foreign key reference."}
                    }
                },
            )

        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": f"Data violates constraint: {getattr(e, 'constraint_name', '')}"}
                    }
                },
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Missing required field value."}
                    }
                },
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid data format provided."}
                    }
                },
            )

        # --------------------------------------------------
        # GENERIC DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError:
            log.exception("Database error during customer creation")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {}
                    }
                },
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during customer creation")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Internal server error.",
                        "fields": {}
                    }
                },
            )

# -------------------------------------------------------------------
# GET CUSTOMER BY ID (Enterprise Production + Detail Audit)
# -------------------------------------------------------------------
@router.get(
    "/{customer_id}",
    summary="Get Customer Details (Production Ready)",
    responses={
        200: {"description": "Customer details fetched successfully."},
        404: {"description": "Customer not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_customer_by_id(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    ✔ Fetch single customer with RM and OP names
    ✔ Concurrency safe
    ✔ Detail audit logging
    """
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_customer_by_id"},
    )

    log.info("Incoming get customer request | customer_id=%s", customer_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:
        query = f"""
            SELECT c.*,
                   e_rm.first_name AS rm_name,
                   e_op.first_name AS op_name
            FROM {DB_SCHEMA}.customers c
            LEFT JOIN {DB_SCHEMA}.employees e_rm
                   ON c.rm_id = e_rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_op
                   ON c.op_id = e_op.emp_id
            WHERE c.customer_id = $1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, customer_id)

        if not row:
            log.warning("Customer not found | customer_id=%s", customer_id)
            raise HTTPException(
                status_code=404,
                detail="Customer not found.",
            )

        log.info("Customer fetched successfully | customer_id=%s", customer_id)
        return dict(row)

    except asyncpg.PostgresError:
        log.exception("Database error during customer fetch")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )
    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error during customer fetch")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# -------------------------------------------------------------------
# LIST CUSTOMERS (Enterprise Filter + Pagination + Services Support)
# -------------------------------------------------------------------

STANDARD_FILTERS = {
    "customer_id": ("customer_id =", lambda v: v),
    "full_name": ("full_name ILIKE", lambda v: f"%{v.strip()}%"),
    "email": ("email ILIKE", lambda v: f"%{v.strip().lower()}%"),
    "mobile": ("mobile =", lambda v: v.strip()),
    "business_type": ("business_type =", lambda v: v),
    "state": ("state =", lambda v: v),
    "city": ("city =", lambda v: v),
    "rm_id": ("rm_id =", lambda v: v),
    "op_id": ("op_id =", lambda v: v),
}

ARRAY_FILTERS = {
    "service_required": ("service_required", "ANY"),
    "services_required_all": ("service_required", "@>"),
    "services_required_any": ("service_required", "&&"),

    "service_provided": ("service_provided", "ANY"),
    "services_provided_all": ("service_provided", "@>"),
    "services_provided_any": ("service_provided", "&&"),
}

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

    # service filters
    service_required: Optional[str] = None,
    services_required_all: Optional[List[str]] = Query(None),
    services_required_any: Optional[List[str]] = Query(None),

    service_provided: Optional[str] = None,
    services_provided_all: Optional[List[str]] = Query(None),
    services_provided_any: Optional[List[str]] = Query(None),

    # date filters
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,

    # pagination
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    # NEW: cursor pagination
    cursor: Optional[datetime] = None,

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_customers"},
    )

    log.info(
        "Incoming customer filter | limit=%s offset=%s cursor=%s",
        limit,
        offset,
        cursor,
    )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:

        params = locals()
        conditions = []
        values = []
        idx = 1

        # --------------------------------------------------
        # STANDARD FILTERS
        # --------------------------------------------------
        for key, (sql_op, formatter) in STANDARD_FILTERS.items():

            value = params.get(key)

            if value is not None:
                conditions.append(f"{sql_op} ${idx}")
                values.append(formatter(value))
                idx += 1

        # --------------------------------------------------
        # ARRAY FILTERS
        # --------------------------------------------------
        for key, (column, operator) in ARRAY_FILTERS.items():

            value = params.get(key)

            if not value:
                continue

            if isinstance(value, list):
                cleaned = [v.strip() for v in value if isinstance(v, str) and v.strip()]
                if not cleaned:
                    continue
                value = cleaned

            elif isinstance(value, str):
                value = value.strip()

            if operator == "ANY":
                conditions.append(f"${idx} = ANY({column})")
            else:
                conditions.append(f"{column} {operator} ${idx}")

            values.append(value)
            idx += 1

        # --------------------------------------------------
        # STATUS FILTER
        # --------------------------------------------------
        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            values.append(is_active)
            idx += 1

        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # DATE FILTER
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
        # CURSOR PAGINATION
        # --------------------------------------------------
        if cursor:
            conditions.append(f"created_at < ${idx}")
            values.append(cursor)
            idx += 1

        # --------------------------------------------------
        # WHERE CLAUSE
        # --------------------------------------------------
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        where_clause_c = (
            where_clause.replace("WHERE ", "WHERE c.")
            .replace(" AND ", " AND c.")
            if where_clause
            else ""
        )

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.customers c
            {where_clause_c}
        """

        # --------------------------------------------------
        # PAGINATION LOGIC
        # --------------------------------------------------
        if cursor:
            pagination_sql = f"LIMIT ${idx}"
            values_with_pagination = values + [limit]
        else:
            pagination_sql = f"LIMIT ${idx} OFFSET ${idx + 1}"
            values_with_pagination = values + [limit, offset]

        main_sql = f"""
            SELECT c.*,
                   e_rm.first_name AS rm_name,
                   e_op.first_name AS op_name
            FROM {DB_SCHEMA}.customers c
            LEFT JOIN {DB_SCHEMA}.employees e_rm
                   ON c.rm_id = e_rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_op
                   ON c.op_id = e_op.emp_id
            {where_clause_c}
            ORDER BY c.created_at DESC
            {pagination_sql}
        """

        async with pool.acquire() as conn:

            total_count = await conn.fetchval(count_sql, *values)

            rows = await conn.fetch(main_sql, *values_with_pagination)

        next_cursor = rows[-1]["created_at"] if rows else None

        log.info(
            "Customer filter success | total=%s returned=%s",
            total_count,
            len(rows),
        )

        return {
            "data": [dict(row) for row in rows],
            "next_cursor": next_cursor
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
# -------------------------------------------------------------------
# EDIT CUSTOMER (Dynamic PATCH + Services Support + Version Audit)
# -------------------------------------------------------------------

@router.post(
    "/{customer_id}/edit",
    summary="Edit Customer (Dynamic PATCH + Audit)",
    responses={
        200: {"description": "Customer updated successfully."},
        400: {"description": "Validation failed."},
        404: {"description": "Customer not found."},
        409: {"description": "Duplicate value violation."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_customer(
    customer_id: int,
    payload: CustomerEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_customer"},
    )

    log.info("Incoming edit customer request | customer_id=%s", customer_id)

    # --------------------------------------------------
    # Extract payload fields
    # --------------------------------------------------

    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Invalid request payload.",
                    "fields": {}
                }
            },
        )

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "No fields provided for update.",
                    "fields": {}
                }
            },
        )

    # --------------------------------------------------
    # NOTE: Duplicate validation will be performed after
    # fetching the existing row so we can exclude the
    # current customer_id safely.
    # --------------------------------------------------

    # --------------------------------------------------
    # Normalize service arrays
    # --------------------------------------------------

    if "service_required" in update_data and update_data["service_required"] is None:
        update_data["service_required"] = []

    if "service_provided" in update_data and update_data["service_provided"] is None:
        update_data["service_provided"] = []

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            }
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing Customer (Row Lock)
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
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer not found.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # PROACTIVE DUPLICATE CHECK (Exclude current record)
                # --------------------------------------------------

                duplicate_checks = []
                values = []
                idx = 1
                field_errors = {}

                if "email" in update_data:
                    duplicate_checks.append(
                        f"EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE lower(trim(email)) = lower(trim(${idx})) AND customer_id != ${idx+1}) AS email_match"
                    )
                    values.append(update_data["email"])
                    values.append(customer_id)
                    idx += 2

                if "mobile" in update_data:
                    duplicate_checks.append(
                        f"EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE trim(mobile) = trim(${idx}) AND customer_id != ${idx+1}) AS mobile_match"
                    )
                    values.append(update_data["mobile"])
                    values.append(customer_id)
                    idx += 2

                if duplicate_checks:
                    dup_sql = f"SELECT {', '.join(duplicate_checks)}"
                    dup_row = await conn.fetchrow(dup_sql, *values)

                    if dup_row:
                        if "email_match" in dup_row and dup_row["email_match"]:
                            field_errors["email"] = "Email already exists."
                        if "mobile_match" in dup_row and dup_row["mobile_match"]:
                            field_errors["mobile"] = "Mobile number already exists."

                if field_errors:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors
                            }
                        }
                    )

                # --------------------------------------------------
                # 2️⃣ Reject if no actual change
                # --------------------------------------------------

                no_change = True
                for k, v in update_data.items():
                    if k in old_row and old_row[k] != v:
                        no_change = False
                        break

                if no_change:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "No changes detected to update.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 3️⃣ Build Dynamic Update
                # --------------------------------------------------

                fields = []
                values = []
                idx = 1

                for key, value in update_data.items():
                    fields.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1

                fields.append("updated_at = NOW()")

                values.append(customer_id)

                update_sql = f"""
                    UPDATE {DB_SCHEMA}.customers
                    SET {', '.join(fields)}
                    WHERE customer_id = ${idx}
                    RETURNING *
                """

                new_row = await conn.fetchrow(update_sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer state changed. Please retry.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit
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
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------

        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            field_errors = {}
            if constraint == "uq_customers_mobile":
                field_errors["mobile"] = "Mobile number already exists."
            elif constraint == "uq_customers_email":
                field_errors["email"] = "Email already exists."

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Duplicate value violation."}
                    }
                },
            )

        except asyncpg.exceptions.ForeignKeyViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            field_errors = {}
            if constraint == "customers_rm_id_fkey":
                field_errors["rm_id"] = "Invalid rm_id provided."
            elif constraint == "customers_op_id_fkey":
                field_errors["op_id"] = "Invalid op_id provided."

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Invalid foreign key reference."}
                    }
                },
            )

        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": f"Data violates constraint: {getattr(e, 'constraint_name', '')}"}
                    }
                },
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Missing required field value."}
                    }
                },
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid data format provided."}
                    }
                },
            )

        # --------------------------------------------------
        # GENERIC DB ERROR
        # --------------------------------------------------

        except asyncpg.PostgresError:
            log.exception("Database error during customer update")
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
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            },
        )

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
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer not found.",
                                "fields": {}
                            }
                        }
                    )

                if customer["is_active"] is False:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer already inactive.",
                                "fields": {}
                            }
                        }
                    )

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
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Cannot deactivate customer. Multiple active GST registrations detected.",
                                "fields": {}
                            }
                        }
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
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {}
                    }
                }
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Internal server error.",
                        "fields": {}
                    }
                }
            )

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
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            },
        )

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
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer not found.",
                                "fields": {}
                            }
                        },
                    )

                if customer["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer is already active.",
                                "fields": {}
                            }
                        },
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
                            detail={
                                "error": {
                                    "type": "validation_error",
                                    "message": "GST state changed. Please retry.",
                                    "fields": {}
                                }
                            },
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
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Foreign key constraint violation."}
                    }
                },
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK constraint error")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": str(e)}
                    }
                },
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid data format."}
                    }
                },
            )

        except asyncpg.PostgresError as e:
            log.exception("Database error during activation")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {}
                    }
                },
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during activation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )