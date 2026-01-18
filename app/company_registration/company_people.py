import logging
import uuid
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List

from app.company_registration.schemas import (
    CompanyPersonIn,
    CompanyPersonEditIn,
    CompanyPersonOut
)
from app.utils import get_db_pool, DB_SCHEMA

router = APIRouter(
    prefix="/api/v1/company-people",
    tags=["Company Registration People"]
)

# -------------------------------------------------------------------
# LOGGER
# -------------------------------------------------------------------

logger = logging.getLogger("company_people")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------
# CREATE COMPANY REGISTRATION PERSON
# -------------------------------------------------------------------

@router.post("", response_model=CompanyPersonOut)
async def create_company_person(payload: CompanyPersonIn):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Creating company person cin=%s role=%s",
        request_id, payload.cin, payload.role
    )

    pool = await get_db_pool()

    company = await pool.fetchrow(
        f"SELECT cin FROM {DB_SCHEMA}.company_registration WHERE cin=$1",
        payload.cin
    )
    if not company:
        raise HTTPException(status_code=400, detail="CIN not found")

    sql = f"""
        INSERT INTO {DB_SCHEMA}.company_registration_persons
        (
            cin, role, full_name, pan, aadhaar, voter_id, passport,
            driving_license, email, mobile, dsc_validity_date,
            dir_kyc_due_date, dir_kyc_done_date, occupation,
            area_of_occupation, education_qualification,
            present_residential_address, address_duration_years,
            username, password, is_primary_customer
        )
        VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21
        )
        RETURNING *
    """

    try:
        row = await pool.fetchrow(
            sql,
            payload.cin,
            payload.role,
            payload.full_name,
            payload.pan,
            payload.aadhaar,
            payload.voter_id,
            payload.passport,
            payload.driving_license,
            payload.email,
            payload.mobile,
            payload.dsc_validity_date,
            payload.dir_kyc_due_date,
            payload.dir_kyc_done_date,
            payload.occupation,
            payload.area_of_occupation,
            payload.education_qualification,
            payload.present_residential_address,
            payload.address_duration_years,
            payload.username,
            payload.password,
            payload.is_primary_customer
        )
    except Exception as e:
        logger.exception("[request_id=%s] Create failed: %s", request_id, str(e))
        raise HTTPException(status_code=500, detail="Company person creation failed")

    result = dict(row)
    result["person_id"] = int(result["person_id"])
    result["message"] = "Company person created successfully."

    return result

# -------------------------------------------------------------------
# LIST COMPANY REGISTRATION PERSONS
# -------------------------------------------------------------------

@router.get("", response_model=List[CompanyPersonOut])
async def list_company_persons(
    cin: Optional[str] = None,
    role: Optional[str] = None,
    mobile: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Listing company persons", request_id)

    pool = await get_db_pool()
    conditions, values = [], []

    if cin:
        conditions.append(f"cin=${len(values)+1}")
        values.append(cin)
    if role:
        conditions.append(f"role=${len(values)+1}")
        values.append(role)
    if mobile:
        conditions.append(f"mobile=${len(values)+1}")
        values.append(mobile)
    if is_active is not None:
        conditions.append(f"is_active=${len(values)+1}")
        values.append(is_active)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
        FROM {DB_SCHEMA}.company_registration_persons
        {where_clause}
        ORDER BY person_id DESC
        LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    values.extend([limit, offset])
    rows = await pool.fetch(sql, *values)

    return [
        {**dict(r), "person_id": int(r["person_id"]),
         "message": "Company persons listed successfully."}
        for r in rows
    ]

# -------------------------------------------------------------------
# EDIT COMPANY PERSON BY PERSON_ID
# -------------------------------------------------------------------

@router.post("/{person_id}/edit", response_model=CompanyPersonOut)
async def edit_company_person(person_id: int, payload: CompanyPersonEditIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Editing company person=%s", request_id, person_id)

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration_persons
        SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP
        WHERE person_id=${len(values)+1}
        RETURNING *
    """
    values.append(person_id)

    row = await pool.fetchrow(sql, *values)
    if not row:
        raise HTTPException(status_code=404, detail="Company person not found")

    return {
        **dict(row),
        "person_id": int(row["person_id"]),
        "message": "Company person updated successfully."
    }

# -------------------------------------------------------------------
# BULK EDIT BY CIN
# -------------------------------------------------------------------

@router.post("/by-cin/{cin}/edit", response_model=List[CompanyPersonOut])
async def edit_company_persons_by_cin(
    cin: str,
    payload: CompanyPersonEditIn
):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Editing persons by cin=%s", request_id, cin)

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration_persons
        SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP
        WHERE cin=${len(values)+1}
        RETURNING *
    """
    values.append(cin)

    rows = await pool.fetch(sql, *values)
    if not rows:
        raise HTTPException(status_code=404, detail="No persons found")

    return [
        {**dict(r), "person_id": int(r["person_id"]),
         "message": "Company person updated successfully."}
        for r in rows
    ]

# -------------------------------------------------------------------
# VALIDATION APIs
# -------------------------------------------------------------------

@router.get("/validate")
async def validate_company_person(
    cin: str,
    pan: Optional[str] = None,
    aadhaar: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None
):
    pool = await get_db_pool()
    checks = {}

    if pan:
        checks["pan_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.company_registration_persons WHERE cin=$1 AND pan=$2",
            cin, pan
        ))
    if aadhaar:
        checks["aadhaar_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.company_registration_persons WHERE aadhaar=$1",
            aadhaar
        ))
    if email:
        checks["email_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.company_registration_persons WHERE email=$1",
            email
        ))
    if mobile:
        checks["mobile_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.company_registration_persons WHERE mobile=$1",
            mobile
        ))

    return checks



# -------------------------------------------------------------------
# EDIT COMPANY REGISTRATION PERSON BY MOBILE (DYNAMIC)
# -------------------------------------------------------------------

@router.post("/by-mobile/{mobile}/edit", response_model=List[CompanyPersonOut])
async def edit_company_person_by_mobile(
    mobile: str,
    payload: CompanyPersonEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing company persons mobile=***",
        request_id
    )

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        logger.warning(
            "[request_id=%s] No fields to update mobile=***",
            request_id
        )
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration_persons
        SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP
        WHERE mobile=${len(values)+1}
        RETURNING *
    """
    values.append(mobile)

    try:
        rows = await pool.fetch(sql, *values)
    except Exception as e:
        logger.exception(
            "[request_id=%s] Update failed mobile=***: %s",
            request_id, str(e)
        )
        raise HTTPException(
            status_code=500,
            detail="Company registration person update failed"
        )

    if not rows:
        logger.warning(
            "[request_id=%s] No company persons found mobile=***",
            request_id
        )
        raise HTTPException(
            status_code=404,
            detail="Company registration person not found"
        )

    logger.info(
        "[request_id=%s] Company persons updated count=%d mobile=***",
        request_id, len(rows)
    )

    return [
        {
            **dict(r),
            "person_id": int(r["person_id"]),
            "message": "Company registration person updated successfully."
        }
        for r in rows
    ]


# -------------------------------------------------------------------
# SOFT DELETE / DEACTIVATE PERSON
# -------------------------------------------------------------------

@router.post("/{person_id}/deactivate")
async def deactivate_company_person(person_id: int):
    pool = await get_db_pool()

    row = await pool.fetchrow(
        f"""
        UPDATE {DB_SCHEMA}.company_registration_persons
        SET is_active=false, updated_at=CURRENT_TIMESTAMP
        WHERE person_id=$1
        RETURNING person_id
        """,
        person_id
    )

    if not row:
        raise HTTPException(status_code=404, detail="Company person not found")

    return {"message": "Company person deactivated successfully"}
