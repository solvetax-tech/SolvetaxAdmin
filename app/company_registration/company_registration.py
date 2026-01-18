import logging
import uuid
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime

from app.company_registration.schemas import (
    CompanyRegistrationIn,
    CompanyRegistrationOut,
    CompanyRegistrationEditIn
)
from app.utils import get_db_pool, DB_SCHEMA

router = APIRouter(
    prefix="/api/v1/company-registrations",
    tags=["Company Registration"]
)

logger = logging.getLogger("company_registration")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


@router.post("", response_model=CompanyRegistrationOut)
async def create_company_registration(payload: CompanyRegistrationIn):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Creating Company registration customer_id=%s username=%s mobile=***",
        request_id, payload.customer_id, payload.username
    )

    pool = await get_db_pool()

    # Validate customer
    customer_row = await pool.fetchrow(
        f"SELECT customer_id FROM {DB_SCHEMA}.customers WHERE customer_id=$1",
        payload.customer_id
    )
    if not customer_row:
        raise HTTPException(status_code=400, detail="Customer not found")

    sql = f"""
        INSERT INTO {DB_SCHEMA}.company_registration
        (
            customer_id, cin, username, password, pan,
            company_type, business_type, business_description,
            registered_email, registered_mobile,
            registered_office_address, state, city,
            registration_status, created_by, rm_id,
            is_filing_needed, is_active, company_name
        )
        VALUES
        ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'DRAFT',$14,$15,$16,$17,$18)
        RETURNING *
    """

    try:
        row = await pool.fetchrow(
            sql,
            payload.customer_id,
            payload.cin,
            payload.username,
            payload.password,
            payload.pan,
            payload.company_type,
            payload.business_type,
            payload.business_description,
            payload.registered_email,
            payload.registered_mobile,
            payload.registered_office_address,
            payload.state,
            payload.city,
            payload.created_by,
            payload.rm_id,
            payload.is_filing_needed,
            payload.is_active,
            payload.company_name
        )
    except Exception as e:
        import asyncpg
        if isinstance(e, asyncpg.UniqueViolationError):
            raise HTTPException(status_code=409, detail="CIN or Username already exists")
        raise

    result = dict(row)
    result["id"] = str(result["id"])
    result["customer_id"] = str(result["customer_id"])
    result["message"] = "Company registration created successfully."

    return result

@router.get("", response_model=List[CompanyRegistrationOut])
async def list_company_registrations(
    customer_id: Optional[int] = None,
    cin: Optional[str] = None,
    registered_mobile: Optional[str] = None,
    company_type: Optional[str] = None,
    registration_status: Optional[str] = None,
    is_active: Optional[bool] = None,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Listing company registrations customer_id=%s cin=%s",
        request_id, customer_id, cin
    )

    pool = await get_db_pool()
    conditions, values = [], []

    if customer_id:
        conditions.append(f"customer_id=${len(values)+1}")
        values.append(customer_id)

    if cin:
        conditions.append(f"cin=${len(values)+1}")
        values.append(cin)

    if registered_mobile:
        conditions.append(f"registered_mobile=${len(values)+1}")
        values.append(registered_mobile)

    if company_type:
        conditions.append(f"company_type=${len(values)+1}")
        values.append(company_type)

    if registration_status:
        conditions.append(f"registration_status=${len(values)+1}")
        values.append(registration_status)

    if is_active is not None:
        conditions.append(f"is_active=${len(values)+1}")
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
          FROM {DB_SCHEMA}.company_registration
          {where_clause}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    try:
        values.extend([limit, offset])
        rows = await pool.fetch(sql, *values)

        return [
            {
                **dict(r),
                "id": str(r["id"]),
                "customer_id": str(r["customer_id"]),
                "message": "Company registrations listed successfully."
            }
            for r in rows
        ]
    except Exception as e:
        logger.exception("[request_id=%s] List failed: %s", request_id, str(e))
        raise HTTPException(status_code=500, detail="Failed to list company registrations")

@router.get("/{cin}", response_model=CompanyRegistrationOut)
async def get_company_registration(cin: str):
    logger.info("Fetching company registration cin=%s", cin)

    pool = await get_db_pool()
    row = await pool.fetchrow(
        f"SELECT * FROM {DB_SCHEMA}.company_registration WHERE cin=$1 LIMIT 1",
        cin
    )

    if not row:
        raise HTTPException(status_code=404, detail="Company registration not found")

    return {
        **dict(row),
        "id": str(row["id"]),
        "customer_id": str(row["customer_id"]),
        "message": "Company registration fetched successfully."
    }
@router.get("/filter/by-created-date", response_model=List[CompanyRegistrationOut])
async def get_company_registrations_by_created_date(
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    pool = await get_db_pool()
    conditions, values = [], []

    if from_date:
        conditions.append(f"created_at >= ${len(values)+1}")
        values.append(from_date)

    if to_date:
        conditions.append(f"created_at <= ${len(values)+1}")
        values.append(to_date)

    if not conditions:
        raise HTTPException(status_code=400, detail="from_date or to_date required")

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.company_registration
         WHERE {' AND '.join(conditions)}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    values.extend([limit, offset])
    rows = await pool.fetch(sql, *values)

    return [
        {
            **dict(r),
            "id": str(r["id"]),
            "customer_id": str(r["customer_id"]),
            "message": "Company registrations filtered by created date."
        }
        for r in rows
    ]
@router.post("/{cin}/edit", response_model=CompanyRegistrationOut)
async def edit_company_registration(cin: str, payload: CompanyRegistrationEditIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Editing company registration cin=%s", request_id, cin)

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields.append("updated_at=NOW()")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration
        SET {', '.join(fields)}
        WHERE cin=${len(values)+1}
        RETURNING *
    """
    values.append(cin)

    row = await pool.fetchrow(sql, *values)
    if not row:
        raise HTTPException(status_code=404, detail="Company registration not found")

    return {
        **dict(row),
        "id": str(row["id"]),
        "customer_id": str(row["customer_id"]),
        "message": "Company registration updated successfully."
    }

# -------------------------------------------------------------------
# EDIT COMPANY REGISTRATION BY REGISTERED MOBILE (DYNAMIC)
# -------------------------------------------------------------------

@router.post("/by-registered-mobile/{mobile}/edit")
async def edit_company_registration_by_mobile(
    mobile: str,
    payload: CompanyRegistrationEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing company registration(s) registered_mobile=***",
        request_id
    )

    pool = await get_db_pool()
    fields, values = [], []

    for field, value in payload.dict(exclude_unset=True).items():
        fields.append(f"{field}=${len(values)+1}")
        values.append(value)

    if not fields:
        logger.warning(
            "[request_id=%s] No fields to update registered_mobile=***",
            request_id
        )
        raise HTTPException(status_code=400, detail="No fields to update")

    # Always update updated_at
    fields.append("updated_at = NOW()")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration
        SET {', '.join(fields)}
        WHERE registered_mobile = ${len(values)+1}
        RETURNING *
    """
    values.append(mobile)

    try:
        rows = await pool.fetch(sql, *values)
    except Exception as e:
        logger.exception(
            "[request_id=%s] Update failed registered_mobile=***: %s",
            request_id, str(e)
        )
        raise HTTPException(
            status_code=500,
            detail="Company registration update failed"
        )

    if not rows:
        logger.warning(
            "[request_id=%s] No company registration found registered_mobile=***",
            request_id
        )
        raise HTTPException(
            status_code=404,
            detail="Company registration not found"
        )

    logger.info(
        "[request_id=%s] Company registrations updated count=%d",
        request_id, len(rows)
    )

    return [
        {
            **dict(row),
            "id": int(row["id"]),
            "message": "Company registration updated successfully."
        }
        for row in rows
    ]

# -------------------------------------------------------------------
# VALIDATE COMPANY REGISTRATION
# -------------------------------------------------------------------

@router.get("/validate")
async def validate_company_registration(
    cin: Optional[str] = None,
    pan: Optional[str] = None,
    username: Optional[str] = None,
    registered_mobile: Optional[str] = None,
    company_name: Optional[str] = None
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Validating company registration cin=%s username=%s mobile=***",
        request_id, cin, username
    )

    pool = await get_db_pool()
    checks = {}

    if cin:
        checks["cin_exists"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration
                 WHERE cin = $1
                """,
                cin
            )
        )

    if pan:
        checks["pan_exists"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration
                 WHERE pan = $1
                """,
                pan
            )
        )

    if username:
        checks["username_exists"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration
                 WHERE username = $1
                """,
                username
            )
        )

    if registered_mobile:
        checks["mobile_exists"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration
                 WHERE registered_mobile = $1
                """,
                registered_mobile
            )
        )

    if company_name:
        checks["company_name_exists"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration
                 WHERE LOWER(company_name) = LOWER($1)
                """,
                company_name
            )
        )

    logger.info(
        "[request_id=%s] Company validation completed checks=%s",
        request_id, checks
    )

    return checks
