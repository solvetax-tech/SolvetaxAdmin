import logging
import asyncpg
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends,status
from typing import Optional, List

from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationDocumentIn,
    RegistrationDocumentEditIn,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger


router = APIRouter(
    prefix="/api/v1/gst-documents",
    tags=["GST Registration Documents"],
)

# -------------------------------------------------------------------
# CREATE REGISTRATION DOCUMENT (Production Standard + Version Audit + IST)
# -------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Document",
    responses={
        201: {"description": "Registration document created successfully."},
        400: {"description": "Validation failed or GSTIN/person not found."},
        409: {"description": "Duplicate document."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_document(
    payload: RegistrationDocumentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Registration Document (Production Standard + Version Audit)

    ✔ Atomic transaction (Document + Version)
    ✔ entity_type = 'REGISTRATION_DOCUMENT'
    ✔ entity_id = 6 (example)
    ✔ action = 'CREATE'
    ✔ json populated
    ✔ updated_json = NULL
    ✔ IST timezone safe
    ✔ Structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    # --------------------------------------------------
    # IST Time (TIMESTAMPTZ SAFE)
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # Normalize Fields
    # --------------------------------------------------
    document_type = payload.document_type.strip()
    ownership_category = (
        payload.ownership_category.strip()
        if payload.ownership_category
        else None
    )
    mobile = payload.mobile.strip() if payload.mobile else None
    document_url = str(payload.document_url)

    log.info(
        "Incoming registration document create | gstin=%s type=%s",
        payload.gstin,
        document_type,
    )

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gstin, customer_id, is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE gstin = $1
                     LIMIT 1
                    """,
                    payload.gstin,
                )

                if not gst_row:
                    log.warning("GSTIN not found | gstin=%s", payload.gstin)
                    raise HTTPException(
                        status_code=400,
                        detail="GSTIN not found.",
                    )

                if gst_row["is_active"] is False:
                    log.warning("GSTIN inactive | gstin=%s", payload.gstin)
                    raise HTTPException(
                        status_code=400,
                        detail="GSTIN is inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Validate Registration Person (If Provided)
                # --------------------------------------------------
                if payload.person_id:
                    person_row = await conn.fetchrow(
                        f"""
                        SELECT person_id, is_active
                          FROM {DB_SCHEMA}.registration_persons
                         WHERE person_id = $1
                         LIMIT 1
                        """,
                        payload.person_id,
                    )

                    if not person_row:
                        log.warning(
                            "Registration person not found | person_id=%s",
                            payload.person_id,
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="Registration person not found.",
                        )

                    if person_row["is_active"] is False:
                        log.warning(
                            "Registration person inactive | person_id=%s",
                            payload.person_id,
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="Registration person is inactive.",
                        )

                # --------------------------------------------------
                # 3️⃣ Insert Registration Document
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.registration_documents
                    (
                        gstin,
                        person_id,
                        document_type,
                        document_url,
                        ownership_category,
                        mobile,
                        created_at,
                        updated_at,
                        is_active
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,TRUE)
                    RETURNING *
                """

                row = await conn.fetchrow(
                    insert_sql,
                    payload.gstin,
                    payload.person_id,
                    document_type,
                    document_url,
                    ownership_category,
                    mobile,
                    now,
                    now,
                )

                if not row:
                    log.error("Registration document creation failed - no row returned")
                    raise HTTPException(
                        status_code=500,
                        detail="Registration document creation failed.",
                    )

                document_id = row["document_id"]

                # --------------------------------------------------
                # 4️⃣ Insert Version Audit (INLINE)
                # --------------------------------------------------
                version_sql = f"""
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
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    6,  # your entity_id for registration_document
                    gst_row["customer_id"],
                    "CREATE",
                    json.dumps(dict(row), default=str),
                    None,
                )

            log.info(
                "Registration document created successfully with audit | document_id=%s",
                document_id,
            )

            response_data = dict(row)
            response_data["message"] = "Registration document created successfully."
            response_data["request_id"] = request_id

            return response_data

        # --------------------------------------------------
        # Exception Handling (Production Grade)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate registration document detected")
            raise HTTPException(
                status_code=409,
                detail="Duplicate registration document.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference during document creation")
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning("Check constraint violation during document creation")
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning("NOT NULL constraint violation during document creation")
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            log.exception("Invalid data format during document creation", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during document creation | error=%s",
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during document creation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
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
    Filter Registration Documents (Production Standard)

    Validation Responsibility:
    --------------------------
    1. FastAPI: Type + pagination validation
    2. DB: Filtering logic only
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming registration document filter request limit=%s offset=%s",
        limit,
        offset,
    )

    # --------------------------------------------------
    # Date Validation
    # --------------------------------------------------
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Business Filters
        # --------------------------------------------------

        if gstin and gstin.strip():
            conditions.append(f"gstin ILIKE ${param_index}")
            values.append(f"%{gstin.strip()}%")
            param_index += 1

        if person_id is not None:
            conditions.append(f"person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if document_type and document_type.strip():
            conditions.append(f"document_type ILIKE ${param_index}")
            values.append(f"%{document_type.strip()}%")
            param_index += 1

        if verified is not None:
            conditions.append(f"verified = ${param_index}")
            values.append(verified)
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        # --------------------------------------------------
        # Active Status Filtering (Enterprise Pattern)
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
              FROM {DB_SCHEMA}.registration_documents
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info(
            "Registration documents filtered successfully count=%s",
            len(rows),
        )

        return [
            {
                **dict(row),
                "message": "Registration documents filtered successfully.",
            }
            for row in rows
        ]

    # --------------------------------------------------
    # IMPORTANT: Re-raise HTTP Exceptions First
    # --------------------------------------------------
    except HTTPException:
        raise

    # --------------------------------------------------
    # Database Exception Handling
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration document filtering | error=%s",
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    # --------------------------------------------------
    # Unexpected Error Handling
    # --------------------------------------------------
    except Exception:
        log.exception("Unexpected error during registration document filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# GET REGISTRATION DOCUMENT BY GSTIN (ACTIVE ONLY)
# -------------------------------------------------------------------

@router.get(
    "/{gstin}/single_filter",
    summary="Get Registration Document",
    responses={
        200: {"description": "Registration document details."},
        404: {"description": "Registration document not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_registration_document(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Registration Document by GSTIN (Production Standard)

    Validation Responsibility Split:
    --------------------------------
    1. Authentication & Authorization via dependency
    2. Path param validation handled by FastAPI
    3. Existence validation handled by DB query
    4. Returns only ACTIVE documents
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    # Safe emp_id normalization
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    # Mask GSTIN for logs (Security Best Practice)
    def mask_gstin(value: str) -> str:
        value = value.strip()
        if len(value) <= 4:
            return "****"
        return f"{value[:2]}******{value[-2:]}"

    masked_gstin = mask_gstin(gstin)

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "get_registration_document",
        },
    )

    log.info(
        "Incoming get registration document request | gstin=%s",
        masked_gstin,
    )

    # --------------------------------------------------
    # SQL Query Definition (ACTIVE ONLY)
    # --------------------------------------------------
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_documents
         WHERE gstin = $1
           AND is_active = TRUE
         LIMIT 1
    """

    # --------------------------------------------------
    # Database Pool Acquisition Safety
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, gstin)

        # --------------------------------------------------
        # Not Found Handling
        # --------------------------------------------------
        if not row:
            log.warning(
                "Registration document not found or inactive | gstin=%s",
                masked_gstin,
            )
            raise HTTPException(
                status_code=404,
                detail="Registration document not found.",
            )

        log.info(
            "Registration document fetched successfully | gstin=%s",
            masked_gstin,
        )

        return {
            **dict(row),
            "message": "Registration document fetched successfully.",
            "request_id": request_id,
        }

    # --------------------------------------------------
    # IMPORTANT: Re-raise HTTP Exceptions First
    # --------------------------------------------------
    except HTTPException:
        raise

    # --------------------------------------------------
    # DATABASE ERROR HANDLING (Production Grade)
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration document fetch | "
            "gstin=%s | error=%s",
            masked_gstin,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    # --------------------------------------------------
    # FALLBACK UNEXPECTED ERROR (WITH STACK TRACE)
    # --------------------------------------------------
    except Exception:
        log.exception(
            "Unexpected error during registration document fetch | gstin=%s",
            masked_gstin,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# -------------------------------------------------------------------
# EDIT REGISTRATION DOCUMENT (Dynamic Update - Production Ready + Version Audit)
# -------------------------------------------------------------------
@router.post(
    "/{gstin}/edit",
    summary="Edit Registration Document (Dynamic Update - Production Ready)",
    responses={
        200: {"description": "Registration document updated successfully."},
        400: {"description": "Validation failed or invalid data."},
        404: {"description": "Registration document not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_document(
    gstin: str,
    payload: RegistrationDocumentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    # Safe emp_id conversion for version table
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_registration_document",
        },
    )

    log.info(
        "Incoming edit registration document request | gstin=%s",
        gstin,
    )

    # --------------------------------------------------
    # Extract Only Provided Fields
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception as e:
        log.exception(
            "Failed to serialize payload | gstin=%s | error=%s",
            gstin,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        log.warning("No fields provided for update | gstin=%s", gstin)
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Normalize Critical Fields
    # --------------------------------------------------
    try:
        if "document_type" in update_data and update_data["document_type"]:
            update_data["document_type"] = update_data["document_type"].strip()

        if "ownership_category" in update_data and update_data["ownership_category"]:
            update_data["ownership_category"] = update_data["ownership_category"].strip()

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "document_url" in update_data and update_data["document_url"]:
            update_data["document_url"] = str(update_data["document_url"]).strip()

    except Exception as e:
        log.exception(
            "Error during field normalization | gstin=%s | payload=%s | error=%s",
            gstin,
            update_data,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid field values provided.",
        )

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception(
            "Database pool acquisition failed | gstin=%s | error=%s",
            gstin,
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch OLD Snapshot (Active Only)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_documents
                     WHERE gstin = $1
                       AND is_active = TRUE
                     LIMIT 1
                    """,
                    gstin,
                )

                if not old_row:
                    log.warning(
                        "Registration document not found for update | gstin=%s",
                        gstin,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found.",
                    )

                # --------------------------------------------------
                # 2️⃣ Build Dynamic SET Clause
                # --------------------------------------------------
                fields = []
                values = []
                param_index = 1

                for field_name, value in update_data.items():
                    fields.append(f"{field_name} = ${param_index}")
                    values.append(value)
                    param_index += 1

                fields.append("updated_at = NOW()")

                sql = f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET {', '.join(fields)}
                     WHERE gstin = ${param_index}
                       AND is_active = TRUE
                     RETURNING *
                """

                values.append(gstin)

                log.debug(
                    "Executing registration document update | gstin=%s | fields=%s",
                    gstin,
                    list(update_data.keys()),
                )

                new_row = await conn.fetchrow(sql, *values)

                # --------------------------------------------------
                # 3️⃣ Insert Version Audit
                # --------------------------------------------------
                version_sql = f"""
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
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    6,  # Your entity_id for registration_document
                    None,  # No direct customer_id in this table
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Registration document updated successfully with audit | gstin=%s | updated_fields=%s",
                gstin,
                list(update_data.keys()),
            )

            return {
                **dict(new_row),
                "message": "Registration document updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # FULL DATABASE EXCEPTION COVERAGE
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Unique constraint violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning("Check constraint violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning("NOT NULL constraint violation | gstin=%s", gstin)
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            log.error(
                "Invalid data format error | gstin=%s",
                gstin,
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Postgres database error during document update | gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception(
                "Unexpected error during document update | gstin=%s",
                gstin,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# =========================================================
# SOFT DELETE REGISTRATION DOCUMENT (is_active = false) WITH VERSION AUDIT
# =========================================================

@router.delete(
    "/{gstin}/soft_delete",
    summary="Soft delete Registration Document (With Audit)",
    responses={
        200: {"description": "Registration document soft deleted successfully."},
        400: {"description": "Registration document already inactive."},
        404: {"description": "Registration document not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_document(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft Delete Registration Document with Version Audit

    ✔ Atomic transaction (Soft Delete + Version Insert)
    ✔ Concurrency safe (AND is_active = TRUE)
    ✔ json = NULL (for DELETE)
    ✔ updated_json = NEW snapshot (is_active = FALSE)
    ✔ action = 'DELETE'
    ✔ Enterprise structured logging
    ✔ Full asyncpg exception handling
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "soft_delete_registration_document",
        },
    )

    log.info(
        "Incoming soft delete registration document request | gstin=%s",
        gstin,
    )

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception(
            "Database pool acquisition failed during registration document soft delete | error=%s",
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Perform Soft Delete (Concurrency Safe)
                # --------------------------------------------------
                sql = f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE gstin = $1
                       AND is_active = TRUE
                     RETURNING *
                """

                row = await conn.fetchrow(sql, gstin)

                # --------------------------------------------------
                # Not Found / Already Inactive Handling
                # --------------------------------------------------
                if not row:
                    check_sql = f"""
                        SELECT gstin, is_active
                          FROM {DB_SCHEMA}.registration_documents
                         WHERE gstin = $1
                    """

                    existing = await conn.fetchrow(check_sql, gstin)

                    if not existing:
                        log.warning(
                            "Registration document not found for soft delete | gstin=%s",
                            gstin,
                        )
                        raise HTTPException(
                            status_code=404,
                            detail="Registration document not found.",
                        )

                    if existing["is_active"] is False:
                        log.warning(
                            "Registration document already inactive | gstin=%s",
                            gstin,
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="Registration document is already inactive.",
                        )

                # --------------------------------------------------
                # 2️⃣ Insert Version Audit (DELETE)
                # --------------------------------------------------
                version_sql = f"""
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
                """

                deleted_snapshot = dict(row)

                await conn.execute(
                    version_sql,
                    emp_id,
                    "REGISTRATION_DOCUMENT",   # entity_type
                    6,                         # your entity_id for registration_document
                    None,                      # No direct customer_id reference
                    "DELETE",
                    None,                      # json must be NULL
                    json.dumps(deleted_snapshot, default=str),
                )

            log.info(
                "Registration document soft deleted successfully with audit | gstin=%s",
                gstin,
            )

            return {
                **dict(row),
                "message": "Registration document soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DATABASE EXCEPTION HANDLING (Enterprise Grade)
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.error(
                "Foreign key violation during registration document soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.error(
                "Audit constraint violation during registration document soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Audit constraint validation failed.",
            )

        except asyncpg.exceptions.DataError as e:
            log.error(
                "Data error during registration document soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during registration document soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except HTTPException:
            raise

        except Exception as e:
            log.exception(
                "Unexpected error during registration document soft delete | "
                "gstin=%s | error=%s",
                gstin,
                str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )