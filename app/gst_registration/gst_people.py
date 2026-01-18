import logging
import uuid
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List

from app.gst_registration.schemas import (
    RegistrationPersonIn,
    RegistrationPersonEditIn,
    RegistrationPersonOut
)
from app.utils import get_db_pool, DB_SCHEMA

router = APIRouter(
    prefix="/api/v1/gst-people",
    tags=["GST Registration People"]
)

# -------------------------------------------------------------------
# LOGGER
# -------------------------------------------------------------------

logger = logging.getLogger("gst_people")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------
# CREATE REGISTRATION PERSON
# -------------------------------------------------------------------

@router.post("", response_model=RegistrationPersonOut)
async def create_registration_person(payload: RegistrationPersonIn):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Creating registration person gstin=%s role=%s",
        request_id, payload.gstin, payload.role
    )

    pool = await get_db_pool()

    gst_row = await pool.fetchrow(
        f"SELECT gstin FROM {DB_SCHEMA}.gst_registration WHERE gstin=$1",
        payload.gstin
    )
    if not gst_row:
        logger.warning(
            "[request_id=%s] GSTIN not found: %s",
            request_id, payload.gstin
        )
        raise HTTPException(status_code=400, detail="GSTIN not found")

    if payload.customer_id:
        cust_row = await pool.fetchrow(
            f"SELECT customer_id FROM {DB_SCHEMA}.customers WHERE customer_id=$1",
            payload.customer_id
        )
        if not cust_row:
            logger.warning(
                "[request_id=%s] Customer not found: %s",
                request_id, payload.customer_id
            )
            raise HTTPException(status_code=400, detail="Customer not found")

    sql = f"""
        INSERT INTO {DB_SCHEMA}.registration_persons
        (customer_id, gstin, full_name, role, pan, aadhaar, email, mobile, is_primary_customer)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING *
    """

    try:
        row = await pool.fetchrow(
            sql,
            payload.customer_id,
            payload.gstin,
            payload.full_name,
            payload.role,
            payload.pan,
            payload.aadhaar,
            payload.email,
            payload.mobile,
            payload.is_primary_customer
        )
    except Exception as e:
        logger.exception(
            "[request_id=%s] Registration person create failed: %s",
            request_id, str(e)
        )
        raise HTTPException(status_code=500, detail="Registration person creation failed")

    result = dict(row)
    result["person_id"] = int(result["person_id"])
    result["message"] = "Registration person created successfully."

    logger.info(
        "[request_id=%s] Registration person created person_id=%s gstin=%s",
        request_id, result["person_id"], payload.gstin
    )

    return result

# -------------------------------------------------------------------
# LIST REGISTRATION PERSONS
# -------------------------------------------------------------------

@router.get("", response_model=List[RegistrationPersonOut])
async def list_registration_persons(
    gstin: Optional[str] = None,
    customer_id: Optional[int] = None,
    mobile: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Listing registration persons gstin=%s customer_id=%s",
        request_id, gstin, customer_id
    )

    pool = await get_db_pool()
    conditions, values = [], []

    if gstin:
        conditions.append(f"gstin = ${len(values)+1}")
        values.append(gstin)
    if customer_id:
        conditions.append(f"customer_id = ${len(values)+1}")
        values.append(customer_id)
    if mobile:
        conditions.append(f"mobile = ${len(values)+1}")
        values.append(mobile)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
        FROM {DB_SCHEMA}.registration_persons
        {where_clause}
        ORDER BY person_id DESC
        LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    values.extend([limit, offset])
    rows = await pool.fetch(sql, *values)

    logger.info(
        "[request_id=%s] Listed registration persons count=%d",
        request_id, len(rows)
    )

    return [
        {**dict(r), "person_id": int(r["person_id"]),
         "message": "Registration persons listed successfully."}
        for r in rows
    ]

# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON (ALL UPDATES GUARDED)
# -------------------------------------------------------------------

@router.post("/{person_id}/edit", response_model=RegistrationPersonOut)
async def edit_registration_person(person_id: int, payload: RegistrationPersonEditIn):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing registration person person_id=%s",
        request_id, person_id
    )

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        logger.warning(
            "[request_id=%s] No fields to update person_id=%s",
            request_id, person_id
        )
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.registration_persons
        SET {', '.join(fields)}
        WHERE person_id=${len(values)+1}
        RETURNING *
    """
    values.append(person_id)

    try:
        row = await pool.fetchrow(sql, *values)
    except Exception as e:
        logger.exception(
            "[request_id=%s] Update failed person_id=%s: %s",
            request_id, person_id, str(e)
        )
        raise HTTPException(status_code=500, detail="Registration person update failed")

    if not row:
        logger.warning(
            "[request_id=%s] Registration person not found person_id=%s",
            request_id, person_id
        )
        raise HTTPException(status_code=404, detail="Registration person not found")

    result = dict(row)
    result["person_id"] = int(result["person_id"])
    result["message"] = "Registration person updated successfully."

    logger.info(
        "[request_id=%s] Registration person updated person_id=%s",
        request_id, person_id
    )

    return result



# -------------------------------------------------------------------
# VALIDATION API
# -------------------------------------------------------------------

@router.get("/validate")
async def validate_person(
    gstin: str,
    pan: Optional[str] = None,
    aadhaar: Optional[str] = None,
    mobile: Optional[str] = None
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Validating registration person gstin=%s",
        request_id, gstin
    )

    pool = await get_db_pool()
    checks = {}

    if pan:
        checks["pan_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.registration_persons WHERE gstin=$1 AND pan=$2",
            gstin, pan
        ))

    if aadhaar:
        checks["aadhaar_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.registration_persons WHERE aadhaar=$1",
            aadhaar
        ))

    if mobile:
        checks["mobile_exists"] = bool(await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.registration_persons WHERE mobile=$1",
            mobile
        ))

    return checks



# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON BY GSTIN (DYNAMIC)
# -------------------------------------------------------------------

@router.post("/by-gstin/{gstin}/edit", response_model=List[RegistrationPersonOut])
async def edit_registration_person_by_gstin(
    gstin: str,
    payload: RegistrationPersonEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing registration persons gstin=%s",
        request_id, gstin
    )

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        logger.warning(
            "[request_id=%s] No fields to update gstin=%s",
            request_id, gstin
        )
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.registration_persons
        SET {', '.join(fields)}
        WHERE gstin=${len(values)+1}
        RETURNING *
    """
    values.append(gstin)

    try:
        rows = await pool.fetch(sql, *values)
    except Exception as e:
        logger.exception(
            "[request_id=%s] Update failed gstin=%s: %s",
            request_id, gstin, str(e)
        )
        raise HTTPException(status_code=500, detail="Registration person update failed")

    if not rows:
        logger.warning(
            "[request_id=%s] No registration persons found gstin=%s",
            request_id, gstin
        )
        raise HTTPException(status_code=404, detail="Registration person not found")

    logger.info(
        "[request_id=%s] Registration persons updated count=%d gstin=%s",
        request_id, len(rows), gstin
    )

    return [
        {**dict(r), "person_id": int(r["person_id"]),
         "message": "Registration person updated successfully."}
        for r in rows
    ]


# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON BY MOBILE (DYNAMIC)
# -------------------------------------------------------------------

@router.post("/by-mobile/{mobile}/edit", response_model=List[RegistrationPersonOut])
async def edit_registration_person_by_mobile(
    mobile: str,
    payload: RegistrationPersonEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing registration persons mobile=***",
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
        UPDATE {DB_SCHEMA}.registration_persons
        SET {', '.join(fields)}
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
        raise HTTPException(status_code=500, detail="Registration person update failed")

    if not rows:
        logger.warning(
            "[request_id=%s] No registration persons found mobile=***",
            request_id
        )
        raise HTTPException(status_code=404, detail="Registration person not found")

    logger.info(
        "[request_id=%s] Registration persons updated count=%d mobile=***",
        request_id, len(rows)
    )

    return [
        {**dict(r), "person_id": int(r["person_id"]),
         "message": "Registration person updated successfully."}
        for r in rows
    ]


# -------------------------------------------------------------------
# LOGGER SAFETY (MATCH GST FILE)
# -------------------------------------------------------------------

logger = logging.getLogger("gst_people")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
