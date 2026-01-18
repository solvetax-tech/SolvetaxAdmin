import logging
import uuid
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime

from app.company_registration.schemas import (
    CompanyRegistrationDocumentIn,
    CompanyRegistrationDocumentEditIn,
    CompanyRegistrationDocumentOut
)

from app.utils import get_db_pool, DB_SCHEMA

router = APIRouter(
    prefix="/api/v1/company-documents",
    tags=["Company Registration Documents"]
)

# -------------------------------------------------------------------
# LOGGER
# -------------------------------------------------------------------

logger = logging.getLogger("company_documents")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------
# CREATE COMPANY REGISTRATION DOCUMENT
# -------------------------------------------------------------------

@router.post("", response_model=CompanyRegistrationDocumentOut)
async def create_company_registration_document(
    payload: CompanyRegistrationDocumentIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Creating company document cin=%s type=%s",
        request_id, payload.cin, payload.document_type
    )

    pool = await get_db_pool()

    # Validate CIN
    company_row = await pool.fetchrow(
        f"SELECT cin FROM {DB_SCHEMA}.company_registration WHERE cin=$1",
        payload.cin
    )
    if not company_row:
        raise HTTPException(status_code=400, detail="CIN not found")

    # Validate person_id (optional)
    if payload.person_id:
        person_row = await pool.fetchrow(
            f"""
            SELECT person_id
              FROM {DB_SCHEMA}.company_registration_persons
             WHERE person_id=$1
            """,
            payload.person_id
        )
        if not person_row:
            raise HTTPException(
                status_code=400,
                detail="Company registration person not found"
            )

    sql = f"""
        INSERT INTO {DB_SCHEMA}.company_registration_documents
        (cin, person_id, document_type, document_url)
        VALUES ($1,$2,$3,$4)
        RETURNING *
    """

    try:
        row = await pool.fetchrow(
            sql,
            payload.cin,
            payload.person_id,
            payload.document_type,
            payload.document_url
        )
    except Exception as e:
        logger.exception(
            "[request_id=%s] Company document create failed: %s",
            request_id, str(e)
        )
        raise HTTPException(
            status_code=500,
            detail="Company registration document creation failed"
        )

    result = dict(row)
    result["document_id"] = int(result["document_id"])
    result["message"] = "Company registration document created successfully."

    return result

# -------------------------------------------------------------------
# LIST COMPANY REGISTRATION DOCUMENTS
# -------------------------------------------------------------------

@router.get("", response_model=List[CompanyRegistrationDocumentOut])
async def list_company_registration_documents(
    cin: Optional[str] = None,
    person_id: Optional[int] = None,
    document_type: Optional[str] = None,
    verified: Optional[bool] = None,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Listing company documents cin=%s person_id=%s",
        request_id, cin, person_id
    )

    pool = await get_db_pool()
    conditions, values = [], []

    if cin:
        conditions.append(f"cin=${len(values)+1}")
        values.append(cin)

    if person_id:
        conditions.append(f"person_id=${len(values)+1}")
        values.append(person_id)

    if document_type:
        conditions.append(f"document_type=${len(values)+1}")
        values.append(document_type)

    if verified is not None:
        conditions.append(f"verified=${len(values)+1}")
        values.append(verified)

    if from_date:
        conditions.append(f"uploaded_at >= ${len(values)+1}")
        values.append(from_date)

    if to_date:
        conditions.append(f"uploaded_at <= ${len(values)+1}")
        values.append(to_date)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.company_registration_documents
          {where_clause}
         ORDER BY uploaded_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    try:
        values.extend([limit, offset])
        rows = await pool.fetch(sql, *values)

        return [
            {
                **dict(r),
                "document_id": int(r["document_id"]),
                "message": "Company registration documents listed successfully."
            }
            for r in rows
        ]

    except Exception as e:
        logger.exception(
            "[request_id=%s] Exception during document listing: %s",
            request_id, str(e)
        )
        raise HTTPException(
            status_code=500,
            detail="Exception during company registration document listing"
        )

# -------------------------------------------------------------------
# GET DOCUMENT BY ID
# -------------------------------------------------------------------

@router.get("/{document_id}", response_model=CompanyRegistrationDocumentOut)
async def get_company_registration_document(document_id: int):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Fetching company document document_id=%s",
        request_id, document_id
    )

    pool = await get_db_pool()
    row = await pool.fetchrow(
        f"""
        SELECT *
          FROM {DB_SCHEMA}.company_registration_documents
         WHERE document_id=$1
         LIMIT 1
        """,
        document_id
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Company registration document not found"
        )

    result = dict(row)
    result["document_id"] = int(result["document_id"])
    result["message"] = "Company registration document fetched successfully."

    return result

# -------------------------------------------------------------------
# EDIT DOCUMENT BY ID
# -------------------------------------------------------------------

@router.post("/{document_id}/edit", response_model=CompanyRegistrationDocumentOut)
async def edit_company_registration_document(
    document_id: int,
    payload: CompanyRegistrationDocumentEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing company document document_id=%s",
        request_id, document_id
    )

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration_documents
        SET {', '.join(fields)}
        WHERE document_id=${len(values)+1}
        RETURNING *
    """
    values.append(document_id)

    row = await pool.fetchrow(sql, *values)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Company registration document not found"
        )

    return {
        **dict(row),
        "document_id": int(row["document_id"]),
        "message": "Company registration document updated successfully."
    }

# -------------------------------------------------------------------
# BULK EDIT BY CIN
# -------------------------------------------------------------------

@router.post("/by-cin/{cin}/edit", response_model=List[CompanyRegistrationDocumentOut])
async def edit_company_registration_document_by_cin(
    cin: str,
    payload: CompanyRegistrationDocumentEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing company documents cin=%s",
        request_id, cin
    )

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.company_registration_documents
        SET {', '.join(fields)}
        WHERE cin=${len(values)+1}
        RETURNING *
    """
    values.append(cin)

    rows = await pool.fetch(sql, *values)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Company registration document not found"
        )

    return [
        {
            **dict(r),
            "document_id": int(r["document_id"]),
            "message": "Company registration document updated successfully."
        }
        for r in rows
    ]

# -------------------------------------------------------------------
# VALIDATION API
# -------------------------------------------------------------------

@router.get("/validate")
async def validate_company_registration_document(
    cin: str,
    document_type: Optional[str] = None,
    person_id: Optional[int] = None
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Validating company document cin=%s type=%s",
        request_id, cin, document_type
    )

    pool = await get_db_pool()
    checks = {}

    if document_type:
        checks["document_type_exists_for_cin"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration_documents
                 WHERE cin=$1
                   AND document_type=$2
                """,
                cin, document_type
            )
        )

    if person_id:
        checks["person_id_exists"] = bool(
            await pool.fetchval(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.company_registration_documents
                 WHERE person_id=$1
                """,
                person_id
            )
        )

    return checks

# -------------------------------------------------------------------
# LOGGER SAFETY
# -------------------------------------------------------------------

logger = logging.getLogger("company_documents")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
