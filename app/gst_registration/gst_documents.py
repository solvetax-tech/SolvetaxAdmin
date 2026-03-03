import logging
import asyncpg
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends,status,UploadFile, File
from typing import Optional, List
from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationDocumentIn,
    RegistrationDocumentEditIn,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, get_blob_service_client, AZURE_STORAGE_CONTAINER
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os

router = APIRouter(
    prefix="/api/v1/gst-documents",
    tags=["GST Registration Documents"],
)

# -------------------------------------------------------------------
# UPLOAD REGISTRATION DOCUMENT FILE (Blob Only - No DB)
# -------------------------------------------------------------------

@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload Registration Document File (Blob Only)",
    responses={
        201: {"description": "File uploaded successfully."},
        400: {"description": "Invalid file."},
        500: {"description": "Blob upload failed."},
    },
)
async def upload_registration_document_file(
    file: UploadFile = File(...),
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    ✔ Azure Blob upload only
    ✔ File validation
    ✔ Uses singleton blob client from utils
    ✔ No DB interaction
    ✔ Production structured logging
    """

    # --------------------------------------------------
    # Local Upload Helper (Scoped to This API Only)
    # --------------------------------------------------
    def upload_file_to_blob(file_bytes: bytes, filename: str, folder: str = "gst-documents") -> str:
        """
        Upload file to Azure Blob Storage.
        Returns blob URL.
        """

        blob_service_client = get_blob_service_client()

        unique_filename = f"{generate_uuid()}_{filename}"
        blob_path = f"{folder}/{unique_filename}"

        blob_client = blob_service_client.get_blob_client(
            container=AZURE_STORAGE_CONTAINER,
            blob=blob_path,
        )

        blob_client.upload_blob(file_bytes, overwrite=True)

        return blob_client.url

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming document file upload | filename=%s", file.filename)

    # --------------------------------------------------
    # File Validation
    # --------------------------------------------------
    ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png"]
    MAX_FILE_SIZE = 2*5 * 1024 * 1024  # 10MB

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PDF, JPG, PNG.",
        )

    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 10MB limit.",
        )

    try:
        blob_url = upload_file_to_blob(contents, file.filename)

    except Exception:
        log.exception("Azure blob upload failed")
        raise HTTPException(
            status_code=500,
            detail="Blob upload failed.",
        )

    log.info("File uploaded successfully | blob_url=%s", blob_url)

    return {
        "blob_url": blob_url,
        "filename": file.filename,
        "message": "File uploaded successfully.",
        "request_id": request_id,
    }

# -------------------------------------------------------------------
# CREATE REGISTRATION DOCUMENT (Production Standard + Version Audit + IST)
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Document",
    responses={
        201: {"description": "Registration document created successfully."},
        400: {"description": "Validation failed or GST/person not found."},
        409: {"description": "Duplicate document."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_document(
    payload: RegistrationDocumentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming Registration Document create | person_id=%s | type=%s | verified=%s",
        payload.person_id,
        payload.document_type,
        payload.verified,
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Person (source of truth)
                # --------------------------------------------------
                person_row = await conn.fetchrow(
                    f"""
                    SELECT gst_registration_id,
                           mobile,
                           is_active
                      FROM {DB_SCHEMA}.gst_registration_persons
                     WHERE person_id = $1
                     LIMIT 1
                    """,
                    payload.person_id,
                )

                if not person_row:
                    raise HTTPException(status_code=400, detail="Registration person not found.")

                if person_row["is_active"] is False:
                    raise HTTPException(status_code=400, detail="Registration person is inactive.")

                # --------------------------------------------------
                # 2️⃣ Fetch GST via FK (Correct Architecture)
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT id,
                           gstin,
                           customer_id,
                           is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE id = $1
                     LIMIT 1
                    """,
                    person_row["gst_registration_id"],
                )

                if not gst_row:
                    raise HTTPException(status_code=400, detail="Associated GST registration not found.")

                if gst_row["is_active"] is False:
                    raise HTTPException(status_code=400, detail="Associated GST is inactive.")

                # GSTIN may be NULL — handle safely
                gstin = gst_row["gstin"].strip().upper() if gst_row["gstin"] else None
                mobile = person_row["mobile"].strip() if person_row["mobile"] else None

                # --------------------------------------------------
                # 3️⃣ Insert Registration Document
                # --------------------------------------------------
                document_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.gst_registration_documents (
                        gstin,
                        person_id,
                        document_type,
                        document_url,
                        mobile,
                        verified,
                        verified_by,
                        created_at,
                        updated_at,
                        is_active
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,TRUE
                    )
                    RETURNING *
                    """,
                    gstin,
                    payload.person_id,
                    payload.document_type.strip().upper(),
                    str(payload.document_url).strip(),
                    mobile,
                    payload.verified,
                    emp_id if payload.verified else None,
                    now,
                    now,
                )

                if not document_row:
                    raise HTTPException(status_code=500, detail="Registration document creation failed.")

                # --------------------------------------------------
                # 4️⃣ Version Audit
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    document_row["document_id"],
                    gst_row["customer_id"],
                    "CREATE",
                    json.dumps(dict(document_row), default=str),
                    None,
                )

            log.info(
                "Registration document created successfully | document_id=%s",
                document_row["document_id"],
            )

            return {
                **dict(document_row),
                "message": "Registration document created successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)
            UNIQUE_MAP = {
                "uq_doc_person_type_active":
                    "This document type already exists for this person (active)."
            }
            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Invalid foreign key reference.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)
            CHECK_MAP = {
                "chk_doc_gst_format": "Invalid GSTIN format.",
                "chk_doc_mobile_format": "Invalid mobile number format.",
                "chk_doc_verified_logic": "Verification logic invalid.",
            }
            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(constraint, f"Data violates constraint: {constraint}"),
            )

        except asyncpg.PostgresError:
            log.exception("Database error during document creation")
            raise HTTPException(status_code=500, detail="Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during Registration Document creation")
            raise HTTPException(status_code=500, detail="Internal server error.")
# -------------------------------------------------------------------
# LIST REGISTRATION DOCUMENTS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter Registration Documents",
    responses={
        200: {"description": "Registration documents filtered successfully."},
        400: {"description": "Validation failed (e.g. invalid date range)."},
        500: {"description": "Database or internal error."},
    },
)
async def list_registration_documents(
    gstin: Optional[str] = None,
    person_id: Optional[int] = None,
    document_type: Optional[str] = None,
    verified: Optional[bool] = None,
    mobile: Optional[str] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Filter Registration Documents (Enterprise Standard)

    ✔ Fully aligned with DB logic
    ✔ Uppercase GSTIN safe
    ✔ Mobile trimmed
    ✔ Active filtering pattern consistent
    ✔ Deterministic ordering
    ✔ Pagination safe
    ✔ Structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming registration document filter | limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # Date Validation
    # --------------------------------------------------
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date cannot be greater than to_date.")

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    try:
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Indexed Exact Match Filters
        # --------------------------------------------------
        if person_id is not None:
            conditions.append(f"person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if gstin and gstin.strip():
            conditions.append(f"upper(gstin) = ${param_index}")
            values.append(gstin.strip().upper())
            param_index += 1

        if verified is not None:
            conditions.append(f"verified = ${param_index}")
            values.append(verified)
            param_index += 1
            # Optional strict DB consistency
            if verified:
                conditions.append("verified_by IS NOT NULL AND verified_at IS NOT NULL")
            else:
                conditions.append("verified_by IS NULL AND verified_at IS NULL")

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        # --------------------------------------------------
        # Partial Match Filters
        # --------------------------------------------------
        if document_type and document_type.strip():
            conditions.append(f"document_type ILIKE ${param_index}")
            values.append(f"%{document_type.strip()}%")
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern (Enterprise Standard)
        # --------------------------------------------------
        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filtering (created_at based)
        # --------------------------------------------------
        if from_date:
            conditions.append(f"created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # WHERE Clause Builder
        # --------------------------------------------------
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.gst_registration_documents
              {where_clause}
             ORDER BY created_at DESC, document_id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("Registration documents filtered successfully | count=%s", len(rows))

        return [
            {
                **dict(row),
                "message": "Registration documents filtered successfully.",
                "request_id": request_id,
            }
            for row in rows
        ]

    except asyncpg.PostgresError as e:
        log.error("Database error during registration document filtering | error=%s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Database error occurred during filtering.")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during registration document filtering")
        raise HTTPException(status_code=500, detail="Internal server error.")

@router.post(
    "/{document_id}/edit",
    summary="Edit Registration Document (Flexible Verified + Version Audit)",
    responses={
        200: {"description": "Registration document updated successfully."},
        400: {"description": "Validation failed or invalid reference."},
        404: {"description": "Registration document not found or inactive."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_document(
    document_id: int,
    payload: RegistrationDocumentEditIn,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    Editable fields:
    ✔ document_type
    ✔ document_url
    ✔ verified (flexible; verified_by set automatically)
    """

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    # --------------------------------------------------
    # Extract Update Data
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(status_code=400, detail="No editable fields provided.")

    # --------------------------------------------------
    # Flexible verified logic
    # --------------------------------------------------
    if "verified" in update_data:
        if update_data["verified"]:
            update_data["verified_by"] = emp_id
        else:
            update_data["verified_by"] = None

    # --------------------------------------------------
    # Normalize strings
    # --------------------------------------------------
    if "document_type" in update_data and update_data["document_type"]:
        update_data["document_type"] = update_data["document_type"].strip().upper()

    if "document_url" in update_data and update_data["document_url"]:
        update_data["document_url"] = str(update_data["document_url"]).strip()

    # --------------------------------------------------
    # DB Update
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 🔥 FIXED QUERY (JOIN to get customer_id)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT d.*, rp.customer_id
                      FROM {DB_SCHEMA}.gst_registration_documents d
                      JOIN {DB_SCHEMA}.gst_registration_persons rp
                        ON d.person_id = rp.person_id
                     WHERE d.document_id = $1
                       AND d.is_active = TRUE
                     LIMIT 1
                    """,
                    document_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found or inactive.",
                    )

                # --------------------------------------------------
                # Reject if no actual change
                # --------------------------------------------------
                no_change = True
                for k, v in update_data.items():
                    if k in old_row and old_row[k] != v:
                        no_change = False
                        break

                if no_change:
                    log.info("No changes detected for document_id=%s", document_id)
                    raise HTTPException(
                        status_code=400,
                        detail="No changes detected to update.",
                    )

                # --------------------------------------------------
                # Build dynamic update
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")
                values.append(document_id)

                sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents
                       SET {', '.join(fields)}
                     WHERE document_id = ${idx}
                     RETURNING *
                """

                new_row = await conn.fetchrow(sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Document became inactive before update.",
                    )

                # --------------------------------------------------
                # Version Audit (CORRECT customer_id now available)
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    document_id,
                    old_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

                return {
                    **dict(new_row),
                    "message": "Registration document updated successfully.",
                    "request_id": request_id,
                }

        # -------------------------
        # DB Error Handling
        # -------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "") or ""
            UNIQUE_MAP = {
                "uq_doc_gstin_type_active": "This document type already exists for this GST.",
                "uq_doc_person_type_active": "This document type already exists for this person.",
            }
            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    "Duplicate field value violates unique constraint.",
                ),
            )

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)
            CHECK_MAP = {
                "chk_doc_gst_format": "Invalid GSTIN format.",
                "chk_doc_mobile_format": "Invalid mobile number format. Must be 10 digits.",
                "chk_verified_active": "Invalid verification logic.",
            }
            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference provided.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during document update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during document update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
@router.delete(
    "/{document_id}/soft_delete",
    summary="Soft delete Registration Document (Production Ready + Audit)",
    responses={
        200: {"description": "Registration document soft deleted successfully."},
        400: {"description": "Validation failed or already inactive."},
        404: {"description": "Registration document not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    ✔ Atomic transaction (Soft Delete + Version Insert)
    ✔ Concurrency safe (AND is_active = TRUE)
    ✔ json = NULL (for DELETE)
    ✔ updated_json = NEW snapshot
    ✔ Person-state enforcement (must be active)
    ✔ Verified flexible (optional log if verified=True)
    ✔ Structured logging
    ✔ Full exception mapping
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "soft_delete_registration_document",
        },
    )

    log.info("Incoming document soft delete | document_id=%s", document_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 🔥 FIX: Use JOIN to get customer_id
                # --------------------------------------------------
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons rp
                     WHERE d.document_id = $1
                       AND d.person_id = rp.person_id
                       AND d.is_active = TRUE
                     RETURNING d.*, rp.customer_id
                """

                deleted_row = await conn.fetchrow(delete_sql, document_id)

                # --------------------------------------------------
                # If nothing updated → check existence
                # --------------------------------------------------
                if not deleted_row:
                    existing_row = await conn.fetchrow(
                        f"""
                        SELECT document_id, is_active
                          FROM {DB_SCHEMA}.gst_registration_documents
                         WHERE document_id = $1
                        """,
                        document_id,
                    )

                    if not existing_row:
                        raise HTTPException(
                            status_code=404,
                            detail="Registration document not found.",
                        )

                    if existing_row["is_active"] is False:
                        raise HTTPException(
                            status_code=400,
                            detail="Registration document already inactive.",
                        )

                    raise HTTPException(
                        status_code=409,
                        detail="Document state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 2️⃣ Business Rule Enforcement (Person must be active)
                # --------------------------------------------------
                if deleted_row["person_id"]:
                    person_row = await conn.fetchrow(
                        f"""
                        SELECT is_active
                          FROM {DB_SCHEMA}.gst_registration_persons
                         WHERE person_id = $1
                        """,
                        deleted_row["person_id"],
                    )

                    if person_row and person_row["is_active"] is False:
                        raise HTTPException(
                            status_code=400,
                            detail="Cannot delete document: activate the associated person first.",
                        )

                # Optional: log if deleting a verified document
                if deleted_row["verified"]:
                    log.warning(
                        "Soft deleting a verified document | document_id=%s | emp_id=%s",
                        document_id,
                        emp_id,
                    )

                # --------------------------------------------------
                # 3️⃣ Version Audit Insert
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    document_id,
                    deleted_row["customer_id"],   # ✅ now exists
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_row), default=str),
                )

            log.info(
                "Document soft deleted successfully | document_id=%s",
                document_id,
            )

            return {
                **dict(deleted_row),
                "message": "Registration document soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Exception Mapping
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(
                status_code=400,
                detail="Constraint validation failed.",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during document soft delete")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during document soft delete")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )


@router.post(
    "/{document_id}/activate",
    summary="Activate Registration Document (Production Ready + Audit)",
    responses={
        200: {"description": "Registration document activated successfully."},
        400: {"description": "Validation failed or already active."},
        404: {"description": "Registration document not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_registration_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_registration_document",
        },
    )

    log.info("Incoming document activation | document_id=%s", document_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Document WITH ROW LOCK
                # --------------------------------------------------
                doc_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration_documents
                     WHERE document_id = $1
                     FOR UPDATE
                    """,
                    document_id,
                )

                if not doc_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found.",
                    )

                if doc_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration document already active.",
                    )

                # --------------------------------------------------
                # 2️⃣ Validate Parent Person BEFORE Activation
                # --------------------------------------------------
                if doc_row["person_id"]:
                    person_row = await conn.fetchrow(
                        f"""
                        SELECT is_active
                          FROM {DB_SCHEMA}.gst_registration_persons
                         WHERE person_id = $1
                        """,
                        doc_row["person_id"],
                    )

                    if not person_row:
                        raise HTTPException(
                            status_code=400,
                            detail="Associated person not found.",
                        )

                    if person_row["is_active"] is False:
                        raise HTTPException(
                            status_code=400,
                            detail="Cannot activate document: activate the associated person first.",
                        )

                # --------------------------------------------------
                # 3️⃣ Activate Document (JOIN to fetch customer_id)
                # --------------------------------------------------
                activated_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = TRUE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons rp
                     WHERE d.document_id = $1
                       AND d.person_id = rp.person_id
                       AND d.is_active = FALSE
                     RETURNING d.*, rp.customer_id
                    """,
                    document_id,
                )

                if not activated_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Document state changed. Please retry.",
                    )

                # Optional: Log if verified document
                if activated_row.get("verified"):
                    log.warning(
                        "Activating verified document | document_id=%s",
                        document_id,
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    document_id,
                    activated_row["customer_id"],   # ✅ now exists
                    "ACTIVATE",
                    None,
                    json.dumps(dict(activated_row), default=str),
                )

            log.info("Document activated successfully | document_id=%s", document_id)

            return {
                **dict(activated_row),
                "message": "Registration document activated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Exception Mapping
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(status_code=400, detail="Constraint validation failed.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError:
            log.exception("Database error during document activation")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during document activation")
            raise HTTPException(status_code=500, detail="Internal server error.")