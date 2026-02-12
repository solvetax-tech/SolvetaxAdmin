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
from app.utils import mask_sensitive_data

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
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    now = datetime.utcnow()

    masked_email = mask_sensitive_data(payload.email)
    masked_mobile = mask_sensitive_data(payload.mobile)

    log.info(
        "Incoming create customer request email=%s mobile=%s",
        masked_email,
        masked_mobile,
    )

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            insert_sql = f"""
                INSERT INTO {DB_SCHEMA}.customers
                (full_name, email, mobile, business_name, business_description,
                 business_image_url, business_type, state, city, remark,
                 rm_id, op_id, referral_id, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(
                    insert_sql,
                    payload.full_name,
                    payload.email,
                    payload.mobile,
                    payload.business_name,
                    payload.business_description,
                    str(payload.business_image_url) if payload.business_image_url else None,
                    payload.business_type,
                    payload.state,
                    payload.city,
                    payload.remark,
                    payload.rm_id,
                    payload.op_id,
                    payload.referral_id,
                    now,
                    now,
                )

            if not row:
                log.error("Customer creation failed - no row returned")
                raise HTTPException(
                    status_code=500,
                    detail="Customer creation failed.",
                )

            log.info(
                "Customer created successfully customer_id=%s",
                row["customer_id"],
            )

            # Return full dict response directly instead of Pydantic validation
            import json
            allowed_fields = set(CustomerOut.model_fields.keys())
            filtered_response = {key: value for key, value in row.items() if key in allowed_fields}
            filtered_response["message"] = "Customer created successfully."
            json_response = json.loads(json.dumps(filtered_response, default=str))

            return json_response

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

        except asyncpg.PostgresError:
            log.exception("Database error during customer creation")
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

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
    "",
    response_model=List[CustomerOut],
    summary="List Customers",
)
async def list_customers(
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

    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming list customers request limit=%s offset=%s", limit, offset)

    # 🔹 Date sanity check
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

        # ------------------------------
        # Business Filters
        # ------------------------------

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

        # ------------------------------
        # Role-Based Security Filtering
        # ------------------------------

        roles = current_user.get("roles", [])
        is_admin = "ADMIN" in roles
        is_rm = "RM" in roles
        is_op = "OP" in roles

        if not is_admin:
            if is_rm and not is_op:
                conditions.append(f"rm_id = ${param_index}")
                values.append(emp_id)
                param_index += 1

            elif is_op and not is_rm:
                conditions.append(f"op_id = ${param_index}")
                values.append(emp_id)
                param_index += 1

            else:
                conditions.append(
                    f"(rm_id = ${param_index} OR op_id = ${param_index + 1})"
                )
                values.extend([emp_id, emp_id])
                param_index += 2

        else:
            if rm_id is not None:
                conditions.append(f"rm_id = ${param_index}")
                values.append(rm_id)
                param_index += 1

            if op_id is not None:
                conditions.append(f"op_id = ${param_index}")
                values.append(op_id)
                param_index += 1

        # ------------------------------
        # Status Filtering
        # ------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # ------------------------------
        # Date Filtering
        # ------------------------------

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
              FROM {DB_SCHEMA}.customers
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("Customers listed successfully count=%s", len(rows))

        return [
            CustomerOut.model_validate(row).model_copy(
                update={"message": "Customers listed successfully."}
            )
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error during customer listing")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error during customer listing")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )


# -------------------------------------------------------------------
# GET CUSTOMER BY ID
# -------------------------------------------------------------------
@router.get(
    "/{customer_id}/single_filter",
    response_model=CustomerOut,
    summary="Get Customer",
)
async def get_customer(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Customer by ID

    Validation Responsibility Split:
    --------------------------------
    1. Authentication & Authorization handled via dependency.
    2. customer_id type validation handled by FastAPI (int).
    3. Existence validation handled by DB query.
    """

    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming get customer request customer_id=%s", customer_id)

    pool = await get_db_pool()

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
         WHERE customer_id = $1
         LIMIT 1
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, customer_id)

        if not row:
            log.warning("Customer not found")
            raise HTTPException(
                status_code=404,
                detail="Customer not found.",
            )

        log.info("Customer fetched successfully customer_id=%s", customer_id)

        # Strict response validation
        response = CustomerOut.model_validate(row)

        return response.model_copy(
            update={"message": "Customer fetched successfully."}
        )

    # --------------------------------------------------
    # DB VALIDATIONS
    # --------------------------------------------------

    except asyncpg.PostgresError:
        log.error("Database error during get customer")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error during get customer")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# --------------------------------------------------------------
# EDIT CUSTOMER (is_active EDITABLE)
# --------------------------------------------------------------
@router.post(
    "/{customer_id}/customer-dyn/edit",
    response_model=CustomerOut,
    summary="Edit Customer",
)
async def edit_customer(
    customer_id: int,
    payload: CustomerEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming edit customer request customer_id=%s", customer_id)

    # Extract only provided fields (dynamic update)
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        log.warning("No fields provided for update")
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            fields = []
            values = []

            # --------------------------------------------------
            # Build dynamic SET clause safely
            # --------------------------------------------------
            for index, (key, value) in enumerate(update_data.items(), start=1):
                # Handle HttpUrl if present
                if key == "business_image_url" and value:
                    value = str(value)

                fields.append(f"{key} = ${index}")
                values.append(value)

            # Always update timestamp
            fields.append("updated_at = NOW()")

            sql = f"""
                UPDATE {DB_SCHEMA}.customers
                SET {', '.join(fields)}
                WHERE customer_id = ${len(values) + 1}
                RETURNING *
            """

            values.append(customer_id)

            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            if not row:
                log.warning("Customer not found for update")
                raise HTTPException(
                    status_code=404,
                    detail="Customer not found.",
                )

            log.info(
                "Customer updated successfully customer_id=%s",
                customer_id,
            )

            # Filter response like create API
            import json
            allowed_fields = set(CustomerOut.model_fields.keys())
            filtered_response = {
                key: value for key, value in row.items()
                if key in allowed_fields
            }

            filtered_response["message"] = "Customer updated successfully."
            json_response = json.loads(json.dumps(filtered_response, default=str))

            return json_response

        # --------------------------------------------------
        # DB VALIDATIONS
        # --------------------------------------------------

        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate field value violates unique constraint")
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference (rm_id/op_id)")
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during customer update")
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except Exception:
            log.exception("Unexpected error during customer update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
