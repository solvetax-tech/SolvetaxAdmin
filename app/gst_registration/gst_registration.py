import logging
import uuid
from fastapi import Request
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime
from app.gst_registration.schemas import GSTRegistrationIn, GSTRegistrationOut, GSTRegistrationEditIn

from app.utils import get_db_pool, DB_SCHEMA

router = APIRouter(
    prefix="/api/v1/gst-registrations",
    tags=["GST Registration"]
)

# -------------------------------------------------------------------
# CREATE GST REGISTRATION (RM INITIATES)
# -------------------------------------------------------------------

@router.post("", response_model=GSTRegistrationOut)
async def create_gst_registration(payload: GSTRegistrationIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Creating GST registration for customer_id=%s, username=%s, mobile=***, email=***", request_id, payload.customer_id, payload.username)
    pool = await get_db_pool()

    # Check if customer_id and mobile exist in customers table
    check_sql = f"""
        SELECT customer_id FROM {DB_SCHEMA}.customers
        WHERE customer_id = $1 AND mobile = $2
        LIMIT 1
    """
    customer_row = await pool.fetchrow(check_sql, payload.customer_id, payload.mobile)
    if not customer_row:
        logger.warning("Customer not found for customer_id=%s and mobile=%s. Register customer first.", payload.customer_id, payload.mobile)
        raise HTTPException(status_code=400, detail="Customer not found with given customer_id and mobile. Please register the customer first.")

    sql = f"""
        INSERT INTO {DB_SCHEMA}.gst_registration
        (customer_id, username, password, pan, registration_type, ownership_category, business_type, state, turnover_details, created_by, registration_status, is_filing_needed, mobile, is_active)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'DRAFT',$11,$12,$13)
        RETURNING *
    """

    try:
        row = await pool.fetchrow(
            sql,
            payload.customer_id,
            payload.username,
            payload.password,
            payload.pan,
            payload.registration_type,
            payload.ownership_category,
            payload.business_type,
            payload.state,
            payload.turnover_details,
            payload.created_by,
            payload.is_filing_needed,
            payload.mobile,
            payload.is_active
        )
    except Exception as e:
        import asyncpg
        if isinstance(e, asyncpg.UniqueViolationError) and 'gst_registration_username_key' in str(e):
            logger.warning("Duplicate username attempted: %s", payload.username)
            raise HTTPException(status_code=409, detail="Username already exists. Please choose a different username.")
        raise

    if not row:
        logger.error("GST registration creation failed for customer_id=%s, username=%s", payload.customer_id, payload.username)
        raise HTTPException(status_code=500, detail="GST registration creation failed")

    result = dict(row)
    logger.info("GST registration created: id=%s, customer_id=%s", result["id"], result["customer_id"])
    result["id"] = str(result["id"])
    result["customer_id"] = str(result["customer_id"])
    result["message"] = "GST registration created successfully."
    return result


# -------------------------------------------------------------------
# LIST GST REGISTRATIONS (PAGINATION)
# -------------------------------------------------------------------

@router.get("", response_model=List[GSTRegistrationOut])
async def list_gst_registrations(
    customer_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    logger.info("Listing GST registrations. customer_id=%s, limit=%d, offset=%d", customer_id, limit, offset)
    pool = await get_db_pool()

    conditions, values = [], []

    if customer_id:
        conditions.append(f"customer_id = ${len(values)+1}")
        values.append(customer_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.gst_registration
          {where_clause}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    values.extend([limit, offset])
    rows = await pool.fetch(sql, *values)

    logger.info("Listed GST registrations: count=%d", len(rows))
    return [{**dict(r), "id": str(r["id"]), "customer_id": str(r["customer_id"]), "message": "GST registrations listed successfully."} for r in rows]


@router.get("", response_model=List[GSTRegistrationOut])
async def list_gst_registrations(
    customer_id: Optional[int] = None,
    gstin: Optional[str] = None,
    mobile: Optional[str] = None,
    business_type: Optional[str] = None,
    registration_status: Optional[str] = None,
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
        "[request_id=%s] Listing GST registrations customer_id=%s gstin=%s mobile=%s",
        request_id, customer_id, gstin, "***" if mobile else None
    )

    pool = await get_db_pool()
    conditions, values = [], []

    if customer_id:
        conditions.append(f"customer_id = ${len(values)+1}")
        values.append(customer_id)

    if gstin:
        conditions.append(f"gstin = ${len(values)+1}")
        values.append(gstin)

    if mobile:
        conditions.append(f"mobile = ${len(values)+1}")
        values.append(mobile)

    if business_type:
        conditions.append(f"business_type = ${len(values)+1}")
        values.append(business_type)

    if registration_status:
        conditions.append(f"registration_status = ${len(values)+1}")
        values.append(registration_status)

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
          FROM {DB_SCHEMA}.gst_registration
          {where_clause}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    try:
        values.extend([limit, offset])
        rows = await pool.fetch(sql, *values)

        logger.info(
            "[request_id=%s] GST registrations filtered count=%d",
            request_id, len(rows)
        )

        return [
            {
                **dict(row),
                "id": str(row["id"]),
                "customer_id": str(row["customer_id"]),
                "message": "GST registrations listed successfully."
            }
            for row in rows
        ]

    except Exception as e:
        logger.exception(
            "[request_id=%s] Exception during GST registration filtering: %s",
            request_id, str(e)
        )
        raise HTTPException(
            status_code=500,
            detail="Exception during GST registration filtering"
        )



# -------------------------------------------------------------------
# GET GST REGISTRATION BY ID
# -------------------------------------------------------------------

@router.get("/{gstin}", response_model=GSTRegistrationOut)
async def get_gst_registration(gstin: str):
    logger.info("Fetching GST registration by gstin=%s", gstin)
    pool = await get_db_pool()

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.gst_registration
         WHERE gstin = $1
         LIMIT 1
    """

    row = await pool.fetchrow(sql, gstin)
    if not row:
        logger.warning("GST registration not found: gstin=%s", gstin)
        raise HTTPException(status_code=404, detail="GST registration not found")

    logger.info("Fetched GST registration: gstin=%s", gstin)
    return {**dict(row), "id": str(row["id"]), "customer_id": str(row["customer_id"]), "message": "GST registration fetched successfully."}

# FILTER GST REGISTRATIONS BY CREATED DATE (WITH PAGINATION)
@router.get("/filter/by-created-date", response_model=List[GSTRegistrationOut])
async def get_gst_registrations_by_created_date(
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
    logger.info("Filtering GST registrations by created date. from_date=%s, to_date=%s, limit=%d, offset=%d", from_date, to_date, limit, offset)
    pool = await get_db_pool()
    conditions, values = ["1=1"], []
    if from_date:
        conditions.append(f"created_at >= ${{len(values)+1}}")
        values.append(from_date)
    if to_date:
        conditions.append(f"created_at <= ${{len(values)+1}}")
        values.append(to_date)
    if len(conditions) == 1:
        logger.warning("from_date or to_date required for filter by created date")
        raise HTTPException(status_code=400, detail="from_date or to_date required")
    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.gst_registration
         WHERE {where_clause}
         ORDER BY created_at DESC
         LIMIT ${{len(values)+1}} OFFSET ${{len(values)+2}}
    """
    try:
        values.extend([limit, offset])
        rows = await pool.fetch(sql, *values)
        logger.info("Filtered GST registrations by created date: count=%d", len(rows))
        return [
            {**dict(row), "id": str(row["id"]), "customer_id": str(row["customer_id"]), "message": "GST Registration filtered by created date successfully."}
            for row in rows
        ]
    except Exception as e:
        logger.exception("Exception during filter by created date: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Exception during filter by created date: {str(e)}")
    

@router.get("/{mobile}", response_model=GSTRegistrationOut)
async def get_gst_registration_by_mobile(mobile: str):
    logger.info("Fetching GST registration: mobile=***", )
    pool = await get_db_pool()
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.gst_registration
         WHERE mobile = $1
         LIMIT 1
    """
    row = await pool.fetchrow(sql, mobile)
    if not row:
        logger.warning("GST registration not found: mobile=%s", mobile)
        raise HTTPException(status_code=404, detail="GST registration not found")
    logger.info("Fetched GST registration: mobile=%s", mobile)
    return {**dict(row), "id": str(row["id"]), "customer_id": str(row["customer_id"]), "message": "GST registration fetched successfully."}


# -------------------------------------------------------------------
# EDIT GST REGISTRATION (PORTAL UPDATES)
# -------------------------------------------------------------------

@router.post("/{gstin}/edit", response_model=GSTRegistrationOut)
async def edit_gst_registration(gstin: str, payload: GSTRegistrationEditIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Editing GST registration: gstin=%s", request_id, gstin)
    pool = await get_db_pool()
    fields, values = [], []
    if payload.gstin is not None:
        fields.append("gstin=$%d" % (len(values)+1))
        values.append(payload.gstin)
    if payload.username is not None:
        fields.append("username=$%d" % (len(values)+1))
        values.append(payload.username)
    if payload.password is not None:
        fields.append("password=$%d" % (len(values)+1))
        values.append(payload.password)
    if payload.pan is not None:
        fields.append("pan=$%d" % (len(values)+1))
        values.append(payload.pan)
    if payload.registration_type is not None:
        fields.append("registration_type=$%d" % (len(values)+1))
        values.append(payload.registration_type)
    if payload.ownership_category is not None:
        fields.append("ownership_category=$%d" % (len(values)+1))
        values.append(payload.ownership_category)
    if payload.business_type is not None:
        fields.append("business_type=$%d" % (len(values)+1))
        values.append(payload.business_type)
    if payload.state is not None:
        fields.append("state=$%d" % (len(values)+1))
        values.append(payload.state)
    if payload.turnover_details is not None:
        fields.append("turnover_details=$%d" % (len(values)+1))
        values.append(payload.turnover_details)
    if payload.registration_status is not None:
        fields.append("registration_status=$%d" % (len(values)+1))
        values.append(payload.registration_status)
    if payload.suspension_reason is not None:
        fields.append("suspension_reason=$%d" % (len(values)+1))
        values.append(payload.suspension_reason)
    if payload.cancellation_reason is not None:
        fields.append("cancellation_reason=$%d" % (len(values)+1))
        values.append(payload.cancellation_reason)
    if payload.approved_at is not None:
        fields.append("approved_at=$%d" % (len(values)+1))
        values.append(payload.approved_at)
    if payload.is_rcm_applicable is not None:
        fields.append("is_rcm_applicable=$%d" % (len(values)+1))
        values.append(payload.is_rcm_applicable)
    if payload.is_filing_needed is not None:
        fields.append("is_filing_needed=$%d" % (len(values)+1))
        values.append(payload.is_filing_needed)
    if payload.mobile is not None:
        fields.append("mobile=$%d" % (len(values)+1))
        values.append(payload.mobile)
    if payload.is_active is not None:
        fields.append("is_active=$%d" % (len(values)+1))
        values.append(payload.is_active)
    if not fields:
        logger.warning("No fields to update for gstin=%s", gstin)
        raise HTTPException(status_code=400, detail="No fields to update")
    fields.append("updated_at=NOW()")
    sql = f"""
        UPDATE {DB_SCHEMA}.gst_registration
        SET {', '.join(fields)}
        WHERE gstin=$%d
        RETURNING *
    """ % (len(values)+1)
    values.append(gstin)
    row = await pool.fetchrow(sql, *values)
    if not row:
        logger.warning("GST registration not found for update: gstin=%s", gstin)
        raise HTTPException(status_code=404, detail="GST registration not found")
    logger.info("GST registration updated: gstin=%s", gstin)
    return {**dict(row), "id": str(row["id"]), "customer_id": str(row["customer_id"]), "message": "GST registration updated successfully."}

@router.post("/{mobile}/edit", response_model=GSTRegistrationOut)
async def edit_gst_registration_by_mobile(mobile: str, payload: GSTRegistrationEditIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Editing GST registration: mobile=***", request_id)
    pool = await get_db_pool()
    fields, values = [], []
    if payload.gstin is not None:
        fields.append("gstin=$%d" % (len(values)+1))
        values.append(payload.gstin)
    if payload.username is not None:
        fields.append("username=$%d" % (len(values)+1))
        values.append(payload.username)
    if payload.password is not None:
        fields.append("password=$%d" % (len(values)+1))
        values.append(payload.password)
    if payload.registration_type is not None:
        fields.append("registration_type=$%d" % (len(values)+1))
        values.append(payload.registration_type)
    if payload.ownership_category is not None:
        fields.append("ownership_category=$%d" % (len(values)+1))
        values.append(payload.ownership_category)
    if payload.business_type is not None:
        fields.append("business_type=$%d" % (len(values)+1))
        values.append(payload.business_type)
    if payload.state is not None:
        fields.append("state=$%d" % (len(values)+1))
        values.append(payload.state)
    if payload.turnover_details is not None:
        fields.append("turnover_details=$%d" % (len(values)+1))
        values.append(payload.turnover_details)
    if payload.registration_status is not None:
        fields.append("registration_status=$%d" % (len(values)+1))
        values.append(payload.registration_status)
    if payload.suspension_reason is not None:
        fields.append("suspension_reason=$%d" % (len(values)+1))
        values.append(payload.suspension_reason)
    if payload.cancellation_reason is not None:
        fields.append("cancellation_reason=$%d" % (len(values)+1))
        values.append(payload.cancellation_reason)
    if payload.approved_at is not None:
        fields.append("approved_at=$%d" % (len(values)+1))
        values.append(payload.approved_at)
    if payload.is_rcm_applicable is not None:
        fields.append("is_rcm_applicable=$%d" % (len(values)+1))
        values.append(payload.is_rcm_applicable)
    if payload.is_filing_needed is not None:
        fields.append("is_filing_needed=$%d" % (len(values)+1))
        values.append(payload.is_filing_needed)
    if payload.is_active is not None:
        fields.append("is_active=$%d" % (len(values)+1))
        values.append(payload.is_active)
    if not fields:
        logger.warning("No fields to update for mobile=%s", mobile)
        raise HTTPException(status_code=400, detail="No fields to update")
    fields.append("updated_at=NOW()")
    sql = f"""
        UPDATE {DB_SCHEMA}.gst_registration
        SET {', '.join(fields)}
        WHERE mobile=$%d
        RETURNING *
    """ % (len(values)+1)
    values.append(mobile)
    row = await pool.fetchrow(sql, *values)
    if not row:
        logger.warning("GST registration not found for update: mobile=%s", mobile)
        raise HTTPException(status_code=404, detail="GST registration not found")
    logger.info("GST registration updated: mobile=%s", mobile)
    return {**dict(row), "id": str(row["id"]), "customer_id": str(row["customer_id"]), "message": "GST registration updated successfully."}
import logging
logger = logging.getLogger("gst_registration")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)