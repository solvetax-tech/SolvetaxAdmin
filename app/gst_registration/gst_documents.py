import uuid
import asyncpg
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List

from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationDocumentIn,
    RegistrationDocumentEditIn,
    RegistrationDocumentOut,
)
from app.utils import get_db_pool, DB_SCHEMA
from app.logger import logger


router = APIRouter(
    prefix="/api/v1/gst-documents",
    tags=["GST Registration Documents"],
)

# -------------------------------------------------------------------
# CREATE REGISTRATION DOCUMENT
# -------------------------------------------------------------------

@router.post(
    "",
    response_model=RegistrationDocumentOut,
    summary="Create Registration Document",
)
async def create_registration_document(
    payload: RegistrationDocumentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Creating registration document gstin=%s type=%s",
             payload.gstin, payload.document_type)

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            # Validate GSTIN exists
            gst_exists = await conn.fetchval(
                f"SELECT 1 FROM {DB_SCHEMA}.gst_registration WHERE gstin=$1",
                payload.gstin,
            )
            if not gst_exists:
                raise HTTPException(status_code=400, detail="GSTIN not found.")

            # Validate person_id (if provided)
            if payload.person_id:
                person_exists = await conn.fetchval(
                    f"""
                    SELECT 1 FROM {DB_SCHEMA}.registration_persons
                    WHERE person_id=$1
                    """,
                    payload.person_id,
                )
                if not person_exists:
                    raise HTTPException(status_code=400, detail="Registration person not found.")

            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.registration_documents
                    (gstin, person_id, document_type, document_url,
                     ownership_category, mobile, uploaded_at)
                    VALUES ($1,$2,$3,$4,$5,$6,NOW())
                    RETURNING *
                    """,
                    payload.gstin,
                    payload.person_id,
                    payload.document_type,
                    payload.document_url,
                    payload.ownership_category,
                    payload.mobile,
                )

            response = RegistrationDocumentOut.model_validate(row)

            log.info("Registration document created document_id=%s",
                     row["document_id"])

            return response.model_copy(
                update={"message": "Registration document created successfully."}
            )

        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate registration document")
            raise HTTPException(status_code=409, detail="Duplicate registration document.")

        except asyncpg.PostgresError:
            log.exception("Database error during document creation")
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during document creation")
            raise HTTPException(status_code=500, detail="Internal server error.")


# -------------------------------------------------------------------
# LIST REGISTRATION DOCUMENTS (DYNAMIC FILTER)
# -------------------------------------------------------------------

@router.get(
    "",
    response_model=List[RegistrationDocumentOut],
    summary="List Registration Documents",
)
async def list_registration_documents(
    gstin: Optional[str] = None,
    person_id: Optional[int] = None,
    document_type: Optional[str] = None,
    verified: Optional[bool] = None,
    mobile: Optional[str] = None,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
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

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date cannot be greater than to_date.")

    pool = await get_db_pool()

    conditions = []
    values = []
    param_index = 1

    if gstin:
        conditions.append(f"gstin = ${param_index}")
        values.append(gstin)
        param_index += 1

    if person_id:
        conditions.append(f"person_id = ${param_index}")
        values.append(person_id)
        param_index += 1

    if document_type:
        conditions.append(f"document_type = ${param_index}")
        values.append(document_type)
        param_index += 1

    if verified is not None:
        conditions.append(f"verified = ${param_index}")
        values.append(verified)
        param_index += 1

    if mobile:
        conditions.append(f"mobile = ${param_index}")
        values.append(mobile)
        param_index += 1

    if from_date:
        conditions.append(f"uploaded_at >= ${param_index}")
        values.append(from_date)
        param_index += 1

    if to_date:
        conditions.append(f"uploaded_at <= ${param_index}")
        values.append(to_date)
        param_index += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_documents
          {where_clause}
         ORDER BY uploaded_at DESC
         LIMIT ${param_index} OFFSET ${param_index + 1}
    """

    values.extend([limit, offset])

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("Registration documents listed count=%s", len(rows))

        return [
            RegistrationDocumentOut.model_validate(row).model_copy(
                update={"message": "Registration documents listed successfully."}
            )
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error during listing")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error during listing")
        raise HTTPException(status_code=500, detail="Internal server error.")


# -------------------------------------------------------------------
# EDIT REGISTRATION DOCUMENT (DYNAMIC UPDATE)
# -------------------------------------------------------------------

@router.post(
    "/{document_id}/edit",
    response_model=RegistrationDocumentOut,
    summary="Edit Registration Document",
)
async def edit_registration_document(
    document_id: int,
    payload: RegistrationDocumentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            fields = []
            values = []

            for index, (key, value) in enumerate(update_data.items(), start=1):
                fields.append(f"{key} = ${index}")
                values.append(value)

            sql = f"""
                UPDATE {DB_SCHEMA}.registration_documents
                SET {', '.join(fields)}, updated_at = NOW()
                WHERE document_id = ${len(values) + 1}
                RETURNING *
            """

            values.append(document_id)

            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            if not row:
                raise HTTPException(status_code=404, detail="Registration document not found.")

            log.info("Registration document updated document_id=%s", document_id)

            return RegistrationDocumentOut.model_validate(row).model_copy(
                update={"message": "Registration document updated successfully."}
            )

        except asyncpg.PostgresError:
            log.exception("Database error during document update")
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during document update")
            raise HTTPException(status_code=500, detail="Internal server error.")
