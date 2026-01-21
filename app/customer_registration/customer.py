import logging
import uuid
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import EmailStr, constr, validator
from typing import Optional, List
import re
from datetime import datetime
from app.customer_registration.schemas import CustomerIn, CustomerOut, CustomerEditIn
from app.customer_registration.validators import validate_email, validate_mobile, validate_url
from app.utils import get_db_pool, DB_SCHEMA
from fastapi.security import OAuth2PasswordBearer

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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# Utility function to mask sensitive data
def mask_sensitive_data(data: Optional[str]) -> str:
    if not data:
        return ""
    if len(data) <= 4:
        return "*" * len(data)
    return data[:2] + "*" * (len(data) - 4) + data[-2:]


from app.token_validator import validate_token

async def get_current_user(token: str = Depends(oauth2_scheme)):
    valid, reason = await validate_token(token)
    if not valid:
        raise HTTPException(status_code=401, detail=f"Invalid authentication credentials: {reason}")
    # Optionally decode token to extract user info here if needed
    return {"token": token}


# -------------------------------------------------------------------
# CREATE CUSTOMER (is_active DEFAULT = TRUE at DB level)
# -------------------------------------------------------------------

@router.post("", response_model=CustomerOut, dependencies=[Depends(get_current_user)])
async def create_customer(payload: CustomerIn):
    """
    Validations and checks performed before customer creation:
    - Email format validation using custom validate_email function.
    - Mobile number format validation using custom validate_mobile function.
    - Uniqueness check for active customers by email or mobile to prevent duplicates.
    - User authentication is required (via token).
    - Rate limiting or request throttling should be implemented to control API request volume
      and prevent abuse or overload of system resources.
    """

    request_id = str(uuid.uuid4())
    masked_email = mask_sensitive_data(payload.email)
    masked_mobile = mask_sensitive_data(payload.mobile)
    logger.info("[request_id=%s] Creating customer with email=%s, mobile=%s", request_id, masked_email, masked_mobile)
    pool = await get_db_pool()
    now = datetime.utcnow()

    if not validate_email(payload.email):
        logger.warning("[request_id=%s] Invalid email format: %s", request_id, masked_email)
        raise HTTPException(status_code=400, detail="Invalid email format")
    if not validate_mobile(payload.mobile):
        logger.warning("[request_id=%s] Invalid mobile format: %s", request_id, masked_mobile)
        raise HTTPException(status_code=400, detail="Invalid mobile number format")

    if payload.business_image_url is not None:
        try:
            validate_url(payload.business_image_url)
        except ValueError as e:
            logger.warning("[request_id=%s] Invalid business_image_url format: %s", request_id, str(e))
            raise HTTPException(status_code=400, detail="Invalid business_image_url format")
    check_sql = f"""
        SELECT customer_id FROM {DB_SCHEMA}.customers
        WHERE (email = $1 OR mobile = $2) AND is_active = TRUE
        LIMIT 1
    """
    existing = await pool.fetchrow(check_sql, payload.email, payload.mobile)
    if existing:
        logger.warning("[request_id=%s] Active customer already exists with customer_id=%s, email=%s, mobile=%s", request_id, existing['customer_id'] if existing else 'N/A', masked_email, masked_mobile)
        raise HTTPException(status_code=409, detail="Active customer already exists with this email or mobile number.")
    try:
        sql = f"""
            INSERT INTO {DB_SCHEMA}.customers
            (full_name, email, mobile, business_name, business_description,
             business_image_url, business_type, state, city, remark, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING *
        """

        row = await pool.fetchrow(
            sql,
            payload.full_name,
            payload.email,
            payload.mobile,
            payload.business_name,
            payload.business_description,
            payload.business_image_url,
            payload.business_type,
            payload.state,
            payload.city,
            payload.remark,
            now,
            now
        )

        if not row:
            logger.error("[request_id=%s] Customer creation failed for name: %s", request_id, payload.full_name)
            raise HTTPException(status_code=500, detail="Customer creation failed")

        logger.info("[request_id=%s] Customer created: id=%s, name=%s", request_id, row["customer_id"], row["full_name"])
        return {**dict(row), "customer_id": row["customer_id"], "message": "Customer created successfully."}
    except Exception as e:
        logger.exception("[request_id=%s] Exception during customer creation: %s", request_id, str(e))
        raise


# -------------------------------------------------------------------
# LIST CUSTOMERS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

@router.get("", response_model=List[CustomerOut], dependencies=[Depends(get_current_user)])
async def list_customers(
    customer_id: Optional[int] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    business_type: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
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

    if customer_id:
        conditions.append(f"customer_id = ${len(values)+1}")
        values.append(customer_id)

    if full_name:
        conditions.append(f"full_name ILIKE ${len(values)+1}")
        values.append(f"%{full_name}%")

    if email:
        conditions.append(f"email ILIKE ${len(values)+1}")
        values.append(f"%{email}%")

    if mobile:
        conditions.append(f"mobile = ${len(values)+1}")
        values.append(mobile)

    if business_type:
        conditions.append(f"business_type = ${len(values)+1}")
        values.append(business_type)

    if state:
        conditions.append(f"state = ${len(values)+1}")
        values.append(state)

    if city:
        conditions.append(f"city = ${len(values)+1}")
        values.append(city)

    if is_active is not None:
        conditions.append(f"is_active = ${len(values)+1}")
        values.append(is_active)

    if not include_inactive:
        conditions.append(f"is_active = TRUE")

    if from_date:
        conditions.append(f"created_at >= ${len(values)+1}")
        values.append(from_date)

    if to_date:
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
        rows = await pool.fetch(sql, *values)

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

@router.get("/{customer_id}", response_model=CustomerOut, dependencies=[Depends(get_current_user)])
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
        row = await pool.fetchrow(sql, customer_id)
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

@router.post("/{customer_id}/edit", response_model=CustomerOut, dependencies=[Depends(get_current_user)])
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

    # Validate mandatory full_name presence if provided and not empty
    if payload.full_name is not None:
        if not payload.full_name.strip():
            raise HTTPException(status_code=400, detail="Full name cannot be empty")
        fields.append("full_name=$%d" % (len(values)+1))
        values.append(payload.full_name)

    # Validate and check email uniqueness if provided
    if payload.email is not None:
        if not validate_email(payload.email):
            logger.warning("[request_id=%s] Invalid email format during update: %s", customer_id, payload.email)
            raise HTTPException(status_code=400, detail="Invalid email format")

        # Check email uniqueness excluding current customer
        existing_email = await pool.fetchrow(f"""
            SELECT customer_id FROM {DB_SCHEMA}.customers
            WHERE TRIM(email) = TRIM($1) AND is_active = TRUE AND customer_id != $2
            LIMIT 1
        """, payload.email, customer_id)
        if existing_email:
            raise HTTPException(status_code=409, detail="Email already in use by another active customer")
        fields.append("email=$%d" % (len(values)+1))
        values.append(payload.email)

    # Validate and check mobile uniqueness if provided
    if payload.mobile is not None:
        if not validate_mobile(payload.mobile):
            logger.warning("[request_id=%s] Invalid mobile format during update: %s", customer_id, payload.mobile)
            raise HTTPException(status_code=400, detail="Invalid mobile number format")

        # Check that the provided mobile belongs to this customer or is unique
        existing_mobile = await pool.fetchrow(f"""
            SELECT customer_id FROM {DB_SCHEMA}.customers
            WHERE TRIM(mobile) = TRIM($1) AND is_active = TRUE AND customer_id != $2
            LIMIT 1
        """, payload.mobile, customer_id)
        if existing_mobile:
            logger.info(f"Existing mobile check: found customer_id={existing_mobile['customer_id']} for mobile={payload.mobile} updating customer_id={customer_id}")
        if existing_mobile:
            raise HTTPException(status_code=409, detail="Mobile number already in use by another active customer")
        fields.append("mobile=$%d" % (len(values)+1))
        values.append(payload.mobile)

    if payload.business_name is not None:
        fields.append("business_name=$%d" % (len(values)+1))
        values.append(payload.business_name)

    if payload.business_description is not None:
        fields.append("business_description=$%d" % (len(values)+1))
        values.append(payload.business_description)

    if payload.business_image_url is not None:
        try:
            validate_url(payload.business_image_url)
        except ValueError as e:
            logger.warning("[request_id=%s] Invalid business_image_url format during update: %s", customer_id, str(e))
            raise HTTPException(status_code=400, detail="Invalid business_image_url format")
        fields.append("business_image_url=$%d" % (len(values)+1))
        values.append(payload.business_image_url)

    if payload.business_type is not None:
        fields.append("business_type=$%d" % (len(values)+1))
        values.append(payload.business_type)

    if payload.state is not None:
        fields.append("state=$%d" % (len(values)+1))
        values.append(payload.state)

    if payload.city is not None:
        fields.append("city=$%d" % (len(values)+1))
        values.append(payload.city)

    if payload.remark is not None:
        fields.append("remark=$%d" % (len(values)+1))
        values.append(payload.remark)

    if payload.is_active is not None:
        fields.append("is_active=$%d" % (len(values)+1))
        values.append(payload.is_active)

    if not fields:
        logger.warning("No fields to update for customer_id=%s", customer_id)
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
        row = await pool.fetchrow(sql, *values)
        if not row:
            logger.warning("Customer not found for update: id=%s", customer_id)
            raise HTTPException(status_code=404, detail="Customer not found")
        request_id = str(uuid.uuid4())
        logger.info("[request_id=%s] Customer updated: customer_id=%s, mobile=***, email=***", request_id, customer_id)
        return {**dict(row), "customer_id": row["customer_id"], "message": "Customer updated successfully."}
    except Exception as e:
        logger.exception("Exception during edit_customer: %s", str(e))
        raise
