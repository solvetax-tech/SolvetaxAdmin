import logging
import uuid
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime
from app.security.rbac import require_permission
from app.security.team_scope import require_team_access

from app.gst_registration.schemas import (
    RegistrationDocumentIn,
    RegistrationDocumentEditIn,
    RegistrationDocumentOut
)
from app.utils import get_db_pool, DB_SCHEMA

router = APIRouter(
    prefix="/api/v1/gst-documents",
    tags=["GST Registration Documents"]
)

# -------------------------------------------------------------------
# LOGGER
# -------------------------------------------------------------------

logger = logging.getLogger("gst_documents")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------
# CREATE REGISTRATION DOCUMENT
# -------------------------------------------------------------------

@router.post("", response_model=RegistrationDocumentOut, dependencies=[Depends(require_permission("EMPLOYEE", "WRITE"))])
async def create_registration_document(payload: RegistrationDocumentIn):
    request_id = str(uuid.uuid4())
    logger.info("[request_id=%s] Creating registration document gstin=%s type=%s", request_id, payload.gstin, payload.document_type)

    pool = await get_db_pool()

    # Validate GSTIN
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

    # Validate person_id if provided
    if payload.person_id:
        person_row = await pool.fetchrow(
            f"SELECT person_id FROM {DB_SCHEMA}.registration_persons WHERE person_id=$1",
            payload.person_id
        )
        if not person_row:
            logger.warning(
                "[request_id=%s] Person not found: %s",
                request_id, payload.person_id
            )
            raise HTTPException(status_code=400, detail="Registration person not found")

    sql = f"""
        INSERT INTO {DB_SCHEMA}.registration_documents
        (gstin, person_id, document_type, document_url, ownership_category, mobile)
        VALUES ($1,$2,$3,$4,$5,$6)
        RETURNING *
    """

    try:
        row = await pool.fetchrow(
            sql,
            payload.gstin,
            payload.person_id,
            payload.document_type,
            payload.document_url,
            payload.ownership_category,
            payload.mobile
        )
    except Exception as e:
        logger.exception(
            "[request_id=%s] Registration document create failed: %s",
            request_id, str(e)
        )
        raise HTTPException(status_code=500, detail="Registration document creation failed")

    result = dict(row)
    result["document_id"] = int(result["document_id"])
    result["message"] = "Registration document created successfully."

    logger.info(
        "[request_id=%s] Registration document created document_id=%s gstin=%s",
        request_id, result["document_id"], payload.gstin
    )

    return result

# -------------------------------------------------------------------
# LIST REGISTRATION DOCUMENTS
# -------------------------------------------------------------------

@router.get("", response_model=List[RegistrationDocumentOut], dependencies=[Depends(require_permission("EMPLOYEE", "READ"))])
async def list_registration_documents(
    gstin: Optional[str] = None,
    person_id: Optional[int] = None,
    document_type: Optional[str] = None,
    verified: Optional[bool] = None,
    mobile: Optional[str] = None,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Listing registration documents gstin=%s person_id=%s",
        request_id, gstin, person_id
    )

    pool = await get_db_pool()
    conditions, values = [], []

    if gstin:
        conditions.append(f"gstin = ${len(values)+1}")
        values.append(gstin)

    if person_id:
        conditions.append(f"person_id = ${len(values)+1}")
        values.append(person_id)

    if document_type:
        conditions.append(f"document_type = ${len(values)+1}")
        values.append(document_type)

    if verified is not None:
        conditions.append(f"verified = ${len(values)+1}")
        values.append(verified)

    if mobile:
        conditions.append(f"mobile = ${len(values)+1}")
        values.append(mobile)

    if from_date:
        conditions.append(f"uploaded_at >= ${len(values)+1}")
        values.append(from_date)

    if to_date:
        conditions.append(f"uploaded_at <= ${len(values)+1}")
        values.append(to_date)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_documents
          {where_clause}
         ORDER BY uploaded_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """

    try:
        values.extend([limit, offset])
        rows = await pool.fetch(sql, *values)

        logger.info(
            "[request_id=%s] Registration documents listed count=%d",
            request_id, len(rows)
        )

        return [
            {
                **dict(r),
                "document_id": int(r["document_id"]),
                "message": "Registration documents listed successfully."
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
            detail="Exception during registration document listing"
        )
    

@router.get("/{document_id}", response_model=RegistrationDocumentOut, dependencies=[Depends(require_permission("EMPLOYEE", "READ"))])
async def get_registration_document(document_id: int):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Fetching registration document document_id=%s",
        request_id, document_id
    )

    pool = await get_db_pool()
    row = await pool.fetchrow(
        f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_documents
         WHERE document_id=$1
         LIMIT 1
        """,
        document_id
    )

    if not row:
        logger.warning(
            "[request_id=%s] Document not found document_id=%s",
            request_id, document_id
        )
        raise HTTPException(status_code=404, detail="Registration document not found")

    result = dict(row)
    result["document_id"] = int(result["document_id"])
    result["message"] = "Registration document fetched successfully."

    return result


# -------------------------------------------------------------------
# EDIT REGISTRATION DOCUMENT BY ID (DYNAMIC)
# -------------------------------------------------------------------

@router.post("/{document_id}/edit", response_model=RegistrationDocumentOut, dependencies=[Depends(require_permission("EMPLOYEE", "WRITE"))])
async def edit_registration_document(
    document_id: int,
    payload: RegistrationDocumentEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing registration document document_id=%s",
        request_id, document_id
    )

    pool = await get_db_pool()
    fields, values = [], []

    for k, v in payload.dict(exclude_unset=True).items():
        fields.append(f"{k}=${len(values)+1}")
        values.append(v)

    if not fields:
        logger.warning(
            "[request_id=%s] No fields to update document_id=%s",
            request_id, document_id
        )
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE {DB_SCHEMA}.registration_documents
        SET {', '.join(fields)}
        WHERE document_id=${len(values)+1}
        RETURNING *
    """
    values.append(document_id)

    try:
        row = await pool.fetchrow(sql, *values)
    except Exception as e:
        logger.exception(
            "[request_id=%s] Update failed document_id=%s: %s",
            request_id, document_id, str(e)
        )
        raise HTTPException(status_code=500, detail="Registration document update failed")

    if not row:
        logger.warning(
            "[request_id=%s] Document not found document_id=%s",
            request_id, document_id
        )
        raise HTTPException(status_code=404, detail="Registration document not found")

    result = dict(row)
    result["document_id"] = int(result["document_id"])
    result["message"] = "Registration document updated successfully."

    logger.info(
        "[request_id=%s] Registration document updated document_id=%s",
        request_id, document_id
    )

    return result



@router.post("/by-mobile/{mobile}/edit", response_model=List[RegistrationDocumentOut], dependencies=[Depends(require_permission("EMPLOYEE", "WRITE"))])
async def edit_registration_document_by_mobile(
    mobile: str,
    payload: RegistrationDocumentEditIn
):
    request_id = str(uuid.uuid4())
    logger.info(
        "[request_id=%s] Editing registration document(s) mobile=***",
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
        UPDATE {DB_SCHEMA}.registration_documents
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
        raise HTTPException(
            status_code=500,
            detail="Registration document update failed"
        )

    if not rows:
        logger.warning(
            "[request_id=%s] No documents found for mobile=***",
            request_id
        )
        raise HTTPException(
            status_code=404,
            detail="Registration document not found"
        )

    logger.info(
        "[request_id=%s] Registration documents updated count=%d mobile=***",
        request_id, len(rows)
    )

    return [
        {
            **dict(r),
            "document_id": int(r["document_id"]),
            "message": "Registration document updated successfully."
        }
        for r in rows
    ]
# -------------------------------------------------------------------
# LOGGER SAFETY (MATCH OTHER FILES)
# -------------------------------------------------------------------

logger = logging.getLogger("gst_documents")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
