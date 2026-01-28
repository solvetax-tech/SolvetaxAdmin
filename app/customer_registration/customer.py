import logging
import uuid
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import constr, validator
from typing import Optional, List
from datetime import datetime
from app.customer_registration.schemas import CustomerIn, CustomerOut, CustomerEditIn
from app.customer_registration.validators import validate_email, validate_mobile, validate_url
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import require_permission

# Configure logger
logger = logging.getLogger("customer")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

router = APIRouter(
    prefix="/api/v1/customers",
    tags=["Customers"]
)


# Utility function to mask sensitive data
def mask_sensitive_data(data: Optional[str]) -> str:
    if not data:
        return ""
    if len(data) <= 4:
        return "*" * len(data)
    return data[:2] + "*" * (len(data) - 4) + data[-2:]

#--------------------------------------------------------------
# CREATE CUSTOMER (is_active DEFAULT = TRUE at DB level)
# -------------------------------------------------------------------

@router.post(
    "",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("EMPLOYEE", "WRITE"))],
)
async def create_customer(payload: CustomerIn):
    request_id = str(uuid.uuid4())

    # Normalize and trim string inputs consistently
    full_name = payload.full_name.strip() if payload.full_name else None
    email = payload.email.strip().lower() if payload.email else None
    mobile = payload.mobile.strip() if payload.mobile else None
    business_name = payload.business_name.strip() if payload.business_name else None

    masked_email = mask_sensitive_data(email)
    masked_mobile = mask_sensitive_data(mobile)

    logger.info(
        "[request_id=%s] Creating customer email=%s mobile=%s",
        request_id, masked_email, masked_mobile
    )

    # Validate required values
    if not mobile:
        raise HTTPException(status_code=400, detail="Mobile is required")

    # Validate email only if provided
    if email and not validate_email(email):
        logger.warning("[request_id=%s] Invalid email format: %s", request_id, masked_email)
        raise HTTPException(status_code=400, detail="Invalid email format")

    if not validate_mobile(mobile):
        logger.warning("[request_id=%s] Invalid mobile format: %s", request_id, masked_mobile)
        raise HTTPException(status_code=400, detail="Invalid mobile number format")

    # Validate URL if provided
    if payload.business_image_url is not None:
        try:
            validate_url(payload.business_image_url)
        except ValueError as e:
            logger.warning(
                "[request_id=%s] Invalid business_image_url: %s",
                request_id, str(e)
            )
            raise HTTPException(status_code=400, detail="Invalid business_image_url format")

    now = datetime.utcnow()
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        if payload.rm_id is not None:
            rm_row = await conn.fetchrow(
                f"""
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE emp_id = $1
                  AND role = 'RM'
                  AND is_active = TRUE
                """,
                payload.rm_id
            )
            if not rm_row:
                logger.warning(f"[request_id={request_id}] Invalid or inactive RM id: {payload.rm_id}")
                raise HTTPException(status_code=400, detail="Invalid or inactive rm_id")

        if payload.op_id is not None:
            op_row = await conn.fetchrow(
                f"""
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE emp_id = $1
                  AND role = 'OP'
                  AND is_active = TRUE
                """,
                payload.op_id
            )
            if not op_row:
                logger.warning(f"[request_id={request_id}] Invalid or inactive OP id: {payload.op_id}")
                raise HTTPException(status_code=400, detail="Invalid or inactive op_id")

        check_sql = f"""
            SELECT customer_id
            FROM {DB_SCHEMA}.customers
            WHERE is_active = TRUE
              AND (
                  (email IS NOT NULL AND lower(trim(email)) = $1)
                  OR trim(mobile) = $2
              )
            LIMIT 1
        """

        insert_sql = f"""
            INSERT INTO {DB_SCHEMA}.customers
            (full_name, email, mobile, business_name, business_description,
             business_image_url, business_type, state, city, remark,
             rm_id, op_id, referral_id, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            RETURNING *
        """

        try:
            # Duplicate check with normalized values
            existing = await conn.fetchrow(check_sql, email, mobile)
            if existing:
                logger.warning(
                    "[request_id=%s] Duplicate customer customer_id=%s email=%s mobile=%s",
                    request_id, existing["customer_id"], masked_email, masked_mobile
                )
                raise HTTPException(
                    status_code=409,
                    detail="Active customer already exists with this email or mobile number."
                )

            # Insert inside transaction using normalized values
            async with conn.transaction():
                try:
                    row = await conn.fetchrow(
                        insert_sql,
                        full_name,
                        email,
                        mobile,
                        business_name,
                        payload.business_description,
                        payload.business_image_url,
                        payload.business_type,
                        payload.state,
                        payload.city,
                        payload.remark,
                        payload.rm_id,
                        payload.op_id,
                        payload.referral_id,
                        now,
                        now
                    )

                    if not row:
                        logger.error("[request_id=%s] Customer insert returned empty row", request_id)
                        raise HTTPException(status_code=500, detail="Customer creation failed")

                except asyncpg.exceptions.UniqueViolationError as e:
                    logger.warning(
                        "[request_id=%s] Unique violation (duplicate email/mobile): %s",
                        request_id, str(e)
                    )
                    raise HTTPException(
                        status_code=409,
                        detail="Customer already exists with this email or mobile"
                    )

                except asyncpg.exceptions.ForeignKeyViolationError as e:
                    logger.warning(
                        "[request_id=%s] Foreign key violation: %s",
                        request_id, str(e)
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid rm_id or op_id"
                    )

            logger.info(
                "[request_id=%s] Customer created customer_id=%s",
                request_id, row["customer_id"]
            )

            return {
                **dict(row),
                "customer_id": row["customer_id"],
                "message": "Customer created successfully."
            }

        # ✅ DB-level duplicate protection (race-condition safety)
        except asyncpg.exceptions.UniqueViolationError as e:
            logger.warning(
                "[request_id=%s] Unique violation (duplicate email/mobile): %s",
                request_id, str(e)
            )
            raise HTTPException(
                status_code=409,
                detail="Customer already exists with this email or mobile"
            )

        # ✅ rm_id / op_id invalid
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            logger.warning(
                "[request_id=%s] Foreign key violation: %s",
                request_id, str(e)
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid rm_id or op_id"
            )

        # ✅ other postgres errors
        except asyncpg.PostgresError as e:
            logger.exception(
                "[request_id=%s] Postgres error during customer creation: %s",
                request_id, str(e)
            )
            raise HTTPException(
                status_code=500,
                detail="Database error during customer creation"
            )

        # ✅ unknown errors
        except Exception as e:
            logger.exception(
                "[request_id=%s] Unexpected error: %s",
                request_id, str(e)
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            )


# -------------------------------------------------------------------
# LIST CUSTOMERS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

from fastapi import Request

@router.get("", response_model=List[CustomerOut], dependencies=[Depends(require_permission("EMPLOYEE", "READ"))])
async def list_customers(
    request: Request,
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
    from_date: Optional[datetime] = Query(
        None, description="Start date (ISO 8601 format)"
    ),
    to_date: Optional[datetime] = Query(
        None, description="End date (ISO 8601 format)"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Validations and checks performed before listing customers:
    - User authentication is required (via token).
    - Optional dynamic filtering using query parameters for customer_id,
      full_name, email, mobile, business_type, state, city, is_active.
    - Supports pagination with limit and offset.
    - If include_inactive is False (default), only active customers are listed.
    - Supports filtering by creation date range (from_date, to_date).
    - Internal validations on query parameters are handled by FastAPI's
      parameter validations (e.g., limit and offset ranges).
    """

    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Listing customers customer_id=%s mobile=%s",
        request_id, customer_id, "***" if mobile else None
    )

    pool = await get_db_pool()
    conditions, values = [], []

    # Extract current user info from JWT
    payload = request.state.user if hasattr(request.state, "user") else None
    if not payload:
        # fallback to rbac method to get payload from headers
        from app.security.rbac import get_current_user_payload
        payload = get_current_user_payload(request)
    current_emp_id = int(payload["sub"])
    permissions = payload.get("permissions", {}).get("platform", {})
    user_access_perms = permissions.get("USER_ACCESS", [])

    # Determine user role for team scope filtering
    user_roles = payload.get("roles", [])
    is_admin = "ADMIN" in user_roles or "WRITE" in user_access_perms
    is_rm = "RM" in user_roles
    is_op = "OP" in user_roles

    # Basic filters from query params
    if customer_id is not None:
        conditions.append(f"customer_id = ${len(values)+1}")
        values.append(customer_id)

    if full_name is not None:
        conditions.append(f"full_name ILIKE ${len(values)+1}")
        values.append(f"%{full_name}%")

    if email is not None:
        conditions.append(f"email ILIKE ${len(values)+1}")
        values.append(f"%{email}%")

    if mobile is not None:
        conditions.append(f"mobile = ${len(values)+1}")
        values.append(mobile)

    if business_type is not None:
        conditions.append(f"business_type = ${len(values)+1}")
        values.append(business_type)

    if state is not None:
        conditions.append(f"state = ${len(values)+1}")
        values.append(state)

    if city is not None:
        conditions.append(f"city = ${len(values)+1}")
        values.append(city)

    # Apply team-scope filter
    if not is_admin:
        # RM sees customers where rm_id = current_emp_id
        # OP sees customers where op_id = current_emp_id
        if is_rm and not is_op:
            conditions.append(f"rm_id = ${len(values)+1}")
            values.append(current_emp_id)
        elif is_op and not is_rm:
            conditions.append(f"op_id = ${len(values)+1}")
            values.append(current_emp_id)
        else:
            # If user has both roles or neither, restrict by rm_id or op_id matching current_emp_id
            conditions.append(f"(rm_id = ${len(values)+1} OR op_id = ${len(values)+2})")
            values.append(current_emp_id)
            values.append(current_emp_id)
    else:
        # Admin or write permission users - no team filter applied
        if rm_id is not None:
            conditions.append(f"rm_id = ${len(values)+1}")
            values.append(rm_id)

        if op_id is not None:
            conditions.append(f"op_id = ${len(values)+1}")
            values.append(op_id)

    if is_active is not None:
        conditions.append(f"is_active = ${len(values)+1}")
        values.append(is_active)

    if not include_inactive:
        conditions.append(f"is_active = TRUE")

    if from_date is not None:
        conditions.append(f"created_at >= ${len(values)+1}")
        values.append(from_date)

    if to_date is not None:
        conditions.append(f"created_at <= ${len(values)+1}")
        values.append(to_date)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
          {where_clause}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    try:
        values.extend([limit, offset])
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

            logger.info(
                "[request_id=%s] Customers filtered count=%d",
                request_id, len(rows)
            )

            return [
                {
                    **dict(row),
                    "customer_id": int(row["customer_id"]),
                    "message": "Customers listed successfully."
                }
                for row in rows
            ]

    except Exception as e:
        logger.exception(
            "[request_id=%s] Exception during customer filtering: %s",
            request_id, str(e)
        )
        raise HTTPException(
            status_code=500,
            detail="Exception during customer filtering"
        )


# -------------------------------------------------------------------
# GET CUSTOMER BY ID
# -------------------------------------------------------------------

@router.get("/{customer_id}", response_model=CustomerOut, dependencies=[Depends(require_permission("EMPLOYEE", "READ"))])
async def get_customer(customer_id: int):
    """
    Validations and checks performed before fetching a customer by ID:
    - User authentication is required (via token).
    - Checks if customer with the given ID exists; returns 404 if not found.
    """
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
                logger.warning("Customer not found: id=%s", customer_id)
                raise HTTPException(status_code=404, detail="Customer not found")
            logger.info("Fetched customer: id=%s", customer_id)
            return {**dict(row), "customer_id": row["customer_id"], "message": "Customer fetched successfully."}
    except Exception as e:
        logger.exception("Exception during get_customer: %s", str(e))
        raise
# -------------------------------------------------------------------
# EDIT CUSTOMER (DATASOURCE-STYLE, PRODUCTION SAFE)
# -------------------------------------------------------------------

@router.post("/{customer_id}/edit", response_model=CustomerOut, dependencies=[Depends(require_permission("EMPLOYEE", "WRITE"))])
async def edit_customer(customer_id: int, payload: CustomerEditIn):
    """
    Validations and checks performed before editing a customer by id:
    - Requires user authentication via token.
    - If full_name is provided, it must not be empty.
    - Email, if provided, is validated for proper format and checked for uniqueness among active customers excluding the current one; raises 409 conflict if duplicate.
    - Mobile, if provided, is validated for correct format and checked for uniqueness among active customers excluding the current one; raises 409 conflict if duplicate.
    - URL format validation for business_image_url if provided.
    - Optional business-related fields are updated if provided without additional validation.
    - At least one field must be provided for update; otherwise, raises 400 error.
    - Attempts to update the customer record; if customer not found, raises 404 error.
    - Logs relevant information and exceptions during processing.
    """

    pool = await get_db_pool()
    fields, values = [], []

    # Normalize and trim string inputs consistently before use
    full_name = payload.full_name.strip() if payload.full_name is not None else None
    email = payload.email.strip().lower() if payload.email is not None else None
    mobile = payload.mobile.strip() if payload.mobile is not None else None
    business_name = payload.business_name.strip() if payload.business_name is not None else None

    # Validate mandatory full_name presence if provided and not empty
    if full_name is not None:
        if not full_name:
            raise HTTPException(status_code=400, detail="Full name cannot be empty")
        fields.append(f"full_name=$%d" % (len(values)+1))
        values.append(full_name)

    async with pool.acquire() as conn:
        # Validate and check email uniqueness if provided
        if email is not None:
            if not validate_email(email):
                logger.warning(f"[request_id=%s] Invalid email format during update: %s" % (customer_id, email))
                raise HTTPException(status_code=400, detail="Invalid email format")

            existing_email = await conn.fetchrow(f"""
                SELECT customer_id FROM {DB_SCHEMA}.customers
                WHERE lower(trim(email)) = $1 AND is_active = TRUE AND customer_id != $2
                LIMIT 1
            """, email, customer_id)
            if existing_email:
                raise HTTPException(status_code=409, detail="Email already in use by another active customer")
            fields.append(f"email=$%d" % (len(values)+1))
            values.append(email)

        # Validate and check mobile uniqueness if provided
        if mobile is not None:
            if not validate_mobile(mobile):
                logger.warning(f"[request_id=%s] Invalid mobile format during update: %s" % (customer_id, mobile))
                raise HTTPException(status_code=400, detail="Invalid mobile number format")

            existing_mobile = await conn.fetchrow(f"""
                SELECT customer_id FROM {DB_SCHEMA}.customers
                WHERE trim(mobile) = $1 AND is_active = TRUE AND customer_id != $2
                LIMIT 1
            """, mobile, customer_id)
            if existing_mobile:
                logger.info(f"Existing mobile check: found customer_id={existing_mobile['customer_id']} for mobile={mobile} updating customer_id={customer_id}")
                raise HTTPException(status_code=409, detail="Mobile number already in use by another active customer")
            fields.append(f"mobile=$%d" % (len(values)+1))
            values.append(mobile)

        if payload.business_name is not None:
            fields.append(f"business_name=$%d" % (len(values)+1))
            values.append(business_name)

        if payload.business_description is not None:
            fields.append(f"business_description=$%d" % (len(values)+1))
            values.append(payload.business_description)

        if payload.business_image_url is not None:
            try:
                validate_url(payload.business_image_url)
            except ValueError as e:
                logger.warning(f"[request_id=%s] Invalid business_image_url format during update: %s" % (customer_id, str(e)))
                raise HTTPException(status_code=400, detail="Invalid business_image_url format")
            fields.append(f"business_image_url=$%d" % (len(values)+1))
            values.append(payload.business_image_url)

        if payload.business_type is not None:
            fields.append(f"business_type=$%d" % (len(values)+1))
            values.append(payload.business_type)

        if payload.state is not None:
            fields.append(f"state=$%d" % (len(values)+1))
            values.append(payload.state)

        if payload.city is not None:
            fields.append(f"city=$%d" % (len(values)+1))
            values.append(payload.city)

        if payload.remark is not None:
            fields.append(f"remark=$%d" % (len(values)+1))
            values.append(payload.remark)

        if payload.is_active is not None:
            fields.append(f"is_active=$%d" % (len(values)+1))
            values.append(payload.is_active)

        if payload.rm_id is not None:
            # Validate rm_id role and active status BEFORE update
            rm_row = await conn.fetchrow(
                f"""
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE emp_id = $1
                  AND role = 'RM'
                  AND is_active = TRUE
                """,
                payload.rm_id,
            )
            if not rm_row:
                logger.warning(f"[request_id=%s] Invalid or inactive RM id during update: %s" % (customer_id, payload.rm_id))
                raise HTTPException(status_code=400, detail="Invalid or inactive rm_id")
            fields.append(f"rm_id=$%d" % (len(values)+1))
            values.append(payload.rm_id)

        if payload.op_id is not None:
            # Validate op_id role and active status BEFORE update
            op_row = await conn.fetchrow(
                f"""
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE emp_id = $1
                  AND role = 'OP'
                  AND is_active = TRUE
                """,
                payload.op_id,
            )
            if not op_row:
                logger.warning(f"[request_id=%s] Invalid or inactive OP id during update: %s" % (customer_id, payload.op_id))
                raise HTTPException(status_code=400, detail="Invalid or inactive op_id")
            fields.append(f"op_id=$%d" % (len(values)+1))
            values.append(payload.op_id)

        if payload.referral_id is not None:
            fields.append(f"referral_id=$%d" % (len(values)+1))
            values.append(payload.referral_id)

        if not fields:
            logger.warning(f"No fields to update for customer_id=%s" % customer_id)
            raise HTTPException(status_code=400, detail="No fields to update")

        fields.append("updated_at=NOW()")
        sql = f"""
            UPDATE {DB_SCHEMA}.customers
            SET {', '.join(fields)}
            WHERE customer_id=$%d
            RETURNING *
        """ % (len(values)+1)
        values.append(customer_id)

        try:
            row = await conn.fetchrow(sql, *values)
            if not row:
                logger.warning(f"Customer not found for update: id=%s" % customer_id)
                raise HTTPException(status_code=404, detail="Customer not found")
            request_id = str(uuid.uuid4())
            logger.info(f"[request_id=%s] Customer updated: customer_id=%s, mobile=***, email=***" % (request_id, customer_id))
            return {**dict(row), "customer_id": row["customer_id"], "message": "Customer updated successfully."}
        except asyncpg.exceptions.UniqueViolationError as e:
            logger.warning(
                f"[request_id] Unique violation during edit_customer: {str(e)}"
            )
            raise HTTPException(status_code=409, detail="Duplicate field value violates unique constraint")
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            logger.warning(
                f"[request_id] Foreign key violation during edit_customer: {str(e)}"
            )
            raise HTTPException(status_code=400, detail="Invalid foreign key reference")
        except asyncpg.PostgresError as e:
            logger.exception(f"Database error during edit_customer: %s" % str(e))
            raise HTTPException(status_code=500, detail="Database error during customer update")
        except Exception as e:
            logger.exception(f"Exception during edit_customer: %s" % str(e))
            raise HTTPException(status_code=500, detail="Internal server error")
