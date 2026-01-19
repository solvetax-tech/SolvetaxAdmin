import logging
import uuid
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import uuid
from datetime import datetime
from app.customer_registration.schemas import CustomerIn, CustomerOut, CustomerEditIn
from app.utils import get_db_pool, DB_SCHEMA

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


# -------------------------------------------------------------------
# CREATE CUSTOMER (is_active DEFAULT = TRUE at DB level)
# -------------------------------------------------------------------

@router.post("", response_model=CustomerOut)
async def create_customer(payload: CustomerIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Creating customer with email=***, mobile=***", request_id)
    pool = await get_db_pool()
    now = datetime.utcnow()
    # Check for existing active customer with same email or mobile
    check_sql = f"""
        SELECT customer_id FROM {DB_SCHEMA}.customers
        WHERE (email = $1 OR mobile = $2) AND is_active = TRUE
        LIMIT 1
    """
    existing = await pool.fetchrow(check_sql, payload.email, payload.mobile)
    if existing:
        logger.warning("[request_id=%s] Active customer already exists with customer_id=%s, email=***, mobile=***", request_id, existing['customer_id'] if existing else 'N/A')
        raise HTTPException(status_code=409, detail="Active customer already exists with this email or mobile number.")
    try:
        sql = f"""
            INSERT INTO {DB_SCHEMA}.customers
            (full_name, email, mobile, business_name, business_description,
             business_image_url, business_type, state, city, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
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



@router.get("", response_model=List[CustomerOut])
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

@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: int):
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
# FILTER BY CREATED DATE (WITH PAGINATION)
# -------------------------------------------------------------------

@router.get("/filter/by-created-date", response_model=List[CustomerOut])
async def get_customers_by_created_date(
    from_date: Optional[datetime] = Query(
        None,
        description="Start date (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)"
    ),
    to_date: Optional[datetime] = Query(
        None,
        description="End date (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    pool = await get_db_pool()
    conditions, values = ["is_active = TRUE"], []
    if from_date:
        conditions.append(f"created_at >= ${len(values)+1}")
        values.append(from_date)
    if to_date:
        conditions.append(f"created_at <= ${len(values)+1}")
        values.append(to_date)
    if len(conditions) == 1:
        logger.warning("from_date or to_date required for filter by created date")
        raise HTTPException(status_code=400, detail="from_date or to_date required")
    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
         WHERE {where_clause}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """
    try:
        values.extend([limit, offset])
        rows = await pool.fetch(sql, *values)
        logger.info("Filtered customers by created date: count=%d", len(rows))
        return [{**dict(row), "customer_id": row["customer_id"], "message": "Customer filtered by created date successfully."} for row in rows]
    except Exception as e:
        logger.exception("Exception during filter by created date: %s", str(e))
        raise


@router.get("", response_model=List[CustomerOut])
async def list_customers(
    customer_id: Optional[int] = None,
    mobile: Optional[str] = None,
    email: Optional[str] = None,
    business_type: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    is_active: Optional[bool] = None,
    from_date: Optional[datetime] = Query(
        None, description="Start date (ISO 8601 format)"
    ),
    to_date: Optional[datetime] = Query(
        None, description="End date (ISO 8601 format)"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
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

    if mobile:
        conditions.append(f"mobile = ${len(values)+1}")
        values.append(mobile)

    if email:
        conditions.append(f"email = ${len(values)+1}")
        values.append(email)

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


@router.get("/{mobile}", response_model=CustomerOut)
async def get_customer_by_mobile(mobile: str):
    pool = await get_db_pool()
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
         WHERE mobile = $1
         LIMIT 1
    """
    try:
        row = await pool.fetchrow(sql, mobile)
        if not row:
            logger.warning("Customer not found: mobile=%s", mobile)
            raise HTTPException(status_code=404, detail="Customer not found")
        logger.info("Fetched customer: customer_id=%s, mobile=***", row["customer_id"] if row else 'N/A')
        return {**dict(row), "customer_id": row["customer_id"], "message": "Customer fetched successfully."}
    except Exception as e:
        logger.exception("Exception during get_customer_by_mobile: %s", str(e))
        raise

# -------------------------------------------------------------------
# EDIT CUSTOMER (DATASOURCE-STYLE, PRODUCTION SAFE)
# -------------------------------------------------------------------

@router.post("/{customer_id}/edit", response_model=CustomerOut)
async def edit_customer(customer_id: int, payload: CustomerEditIn):
    pool = await get_db_pool()
    fields, values = [], []
    if payload.full_name is not None:
        fields.append("full_name=$%d" % (len(values)+1))
        values.append(payload.full_name)
    if payload.email is not None:
        fields.append("email=$%d" % (len(values)+1))
        values.append(payload.email)
    if payload.mobile is not None:
        fields.append("mobile=$%d" % (len(values)+1))
        values.append(payload.mobile)
    if payload.business_name is not None:
        fields.append("business_name=$%d" % (len(values)+1))
        values.append(payload.business_name)
    if payload.business_description is not None:
        fields.append("business_description=$%d" % (len(values)+1))
        values.append(payload.business_description)
    if payload.business_image_url is not None:
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

# -------------------------------------------------------------------
# LIST CUSTOMERS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

@router.get("", response_model=List[CustomerOut])
async def list_customers(
    customer_id: Optional[int] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    business_type: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    is_active: Optional[bool] = None,
    from_date: Optional[datetime] = Query(
        None, description="Start date (ISO 8601 format)"
    ),
    to_date: Optional[datetime] = Query(
        None, description="End date (ISO 8601 format)"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
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


@router.post("/{mobile}/edit", response_model=CustomerOut)
async def edit_customer_by_mobile(mobile: str, payload: CustomerEditIn):
    pool = await get_db_pool()
    fields, values = [], []
    if payload.full_name is not None:
        fields.append("full_name=$%d" % (len(values)+1))
        values.append(payload.full_name)
    if payload.email is not None:
        fields.append("email=$%d" % (len(values)+1))
        values.append(payload.email)
    if payload.mobile is not None:
        fields.append("mobile=$%d" % (len(values)+1))
        values.append(payload.mobile)
    if payload.business_name is not None:
        fields.append("business_name=$%d" % (len(values)+1))
        values.append(payload.business_name)
    if payload.business_description is not None:
        fields.append("business_description=$%d" % (len(values)+1))
        values.append(payload.business_description)
    if payload.business_image_url is not None:
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
    if payload.is_active is not None:
        fields.append("is_active=$%d" % (len(values)+1))
        values.append(payload.is_active)
    if not fields:
        logger.warning("No fields to update for mobile=%s", mobile)
        raise HTTPException(status_code=400, detail="No fields to update")
    fields.append("updated_at=NOW()")
    sql = f"""
        UPDATE {DB_SCHEMA}.customers
        SET {', '.join(fields)}
        WHERE mobile=$%d
        RETURNING *
    """ % (len(values)+1)
    values.append(mobile)
    try:
        row = await pool.fetchrow(sql, *values)
        if not row:
            logger.warning("Customer not found for update: mobile=%s", mobile)
            raise HTTPException(status_code=404, detail="Customer not found")
        request_id = str(uuid.uuid4())
        logger.info("[request_id=%s] Customer updated: customer_id=%s, mobile=***", request_id, row["customer_id"] if row else 'N/A')
        return {**dict(row), "customer_id": row["customer_id"], "message": "Customer updated successfully."}
    except Exception as e:
        logger.exception("Exception during edit_customer_by_mobile: %s", str(e))
        raise
