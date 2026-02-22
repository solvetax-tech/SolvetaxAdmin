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
from datetime import datetime
from zoneinfo import ZoneInfo
import json

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
        400: {"description": "Validation failed or GST/person not found."},
        409: {"description": "Duplicate document."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_document(
    payload: RegistrationDocumentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Registration Document
    ----------------------------
    ✔ Atomic transaction (Document + Version)
    ✔ GST must exist & active
    ✔ Person must belong to same GST (if provided)
    ✔ Person must be active
    ✔ One active document per GST/person/type enforced by DB
    ✔ Enterprise structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    normalized_gstin = payload.gstin.strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming Registration Document create | gstin=%s | type=%s",
        normalized_gstin,
        payload.document_type,
    )

    # --------------------------------------------------
    # IST Timestamp
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

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
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.gst_registration
                    WHERE upper(gstin) = $1
                    LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=400,
                        detail="GSTIN not found.",
                    )

                if not gst_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="GSTIN is inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Validate Person (If Provided)
                # --------------------------------------------------
                if payload.person_id:

                    person_row = await conn.fetchrow(
                        f"""
                        SELECT person_id, gstin, is_active
                        FROM {DB_SCHEMA}.registration_persons
                        WHERE person_id = $1
                        LIMIT 1
                        """,
                        payload.person_id,
                    )

                    if not person_row:
                        raise HTTPException(
                            status_code=400,
                            detail="Registration person not found.",
                        )

                    if person_row["is_active"] is False:
                        raise HTTPException(
                            status_code=400,
                            detail="Registration person is inactive.",
                        )

                    if person_row["gstin"].strip().upper() != normalized_gstin:
                        raise HTTPException(
                            status_code=400,
                            detail="Person does not belong to this GSTIN.",
                        )

                # --------------------------------------------------
                # 3️⃣ Insert Registration Document
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.registration_documents (
                        gstin,
                        person_id,
                        document_type,
                        document_url,
                        ownership_category,
                        mobile,
                        verified,
                        created_at,
                        updated_at,
                        is_active
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,FALSE,$7,$8,TRUE
                    )
                    RETURNING *
                """

                document_row = await conn.fetchrow(
                    insert_sql,
                    normalized_gstin,
                    payload.person_id,
                    payload.document_type.strip().upper(),
                    str(payload.document_url),
                    payload.ownership_category.strip().upper()
                        if payload.ownership_category else None,
                    payload.mobile.strip() if payload.mobile else None,
                    now,
                    now,
                )

                if not document_row:
                    raise HTTPException(
                        status_code=500,
                        detail="Registration document creation failed.",
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit Insert
                # --------------------------------------------------
                version_sql = f"""
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
                """

                await conn.execute(
                    version_sql,
                    emp_id,
                    "REGISTRATION_DOCUMENT",
                    6,
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

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                 "uq_doc_gstin_person_type_active":
                     "This document type already exists for this GST/person (active)."
            }

            log.warning(
                "Unique constraint violation | constraint=%s",
                constraint,
                exc_info=True,
            )

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        # --------------------------------------------------
        # CHECK CONSTRAINT HANDLING (DETAILED)
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_doc_gst_format": "Invalid GSTIN format.",
                "chk_doc_mobile_format": "Invalid mobile number format.",
                "chk_doc_verified_logic":
                    "Verification logic invalid.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # GENERAL DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError as e:
            log.error("Database error | %s", str(e), exc_info=True)
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

    log.info(
        "Incoming registration document filter | limit=%s offset=%s",
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
    # DB Pool
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
              FROM {DB_SCHEMA}.registration_documents
              {where_clause}
             ORDER BY created_at DESC, document_id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info(
            "Registration documents filtered successfully | count=%s",
            len(rows),
        )

        return [
            {
                **dict(row),
                "message": "Registration documents filtered successfully.",
                "request_id": request_id,
            }
            for row in rows
        ]

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
            detail="Database error occurred during filtering.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during registration document filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# EDIT REGISTRATION DOCUMENT (GSTIN + DOCUMENT_ID)
# -------------------------------------------------------------------
@router.post(
    "/{gstin}/{document_id}/edit",
    summary="Edit Registration Document (Production Ready + Version Audit)",
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
    document_id: int,
    payload: RegistrationDocumentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    normalized_gstin = gstin.strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_registration_document",
        },
    )

    log.info(
        "Incoming edit registration document | gstin=%s | document_id=%s",
        normalized_gstin,
        document_id,
    )

    # --------------------------------------------------
    # Extract Payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    # --------------------------------------------------
    # Normalize Fields
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

    except Exception:
        log.exception("Normalization failed")
        raise HTTPException(status_code=400, detail="Invalid field values provided.")

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
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gstin, customer_id, is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE upper(gstin) = $1
                     LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not gst_row:
                    raise HTTPException(status_code=404, detail="GST not found.")

                if not gst_row["is_active"]:
                    raise HTTPException(status_code=400, detail="GST is inactive.")

                # --------------------------------------------------
                # 2️⃣ Fetch Existing Document
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_documents
                     WHERE document_id = $1
                       AND upper(gstin) = $2
                     LIMIT 1
                    """,
                    document_id,
                    normalized_gstin,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found.",
                    )

                # --------------------------------------------------
                # 3️⃣ Business Logic Enforcement
                # --------------------------------------------------

                # 🚫 Prevent document deactivation if person is active
                if "is_active" in update_data and update_data["is_active"] is False:

                    if old_row["person_id"]:
                        person_row = await conn.fetchrow(
                            f"""
                            SELECT is_active
                              FROM {DB_SCHEMA}.registration_persons
                             WHERE person_id = $1
                            """,
                            old_row["person_id"],
                        )

                        if person_row and person_row["is_active"]:
                            raise HTTPException(
                                status_code=400,
                                detail="Deactivate the person first before deactivating this document.",
                            )

                # 🚫 Prevent activation if person is inactive
                if "is_active" in update_data and update_data["is_active"] is True:

                    if old_row["person_id"]:
                        person_row = await conn.fetchrow(
                            f"""
                            SELECT is_active
                              FROM {DB_SCHEMA}.registration_persons
                             WHERE person_id = $1
                            """,
                            old_row["person_id"],
                        )

                        if person_row and not person_row["is_active"]:
                            raise HTTPException(
                                status_code=400,
                                detail="Cannot activate document while person is inactive.",
                            )

                # --------------------------------------------------
                # 4️⃣ Build Dynamic Update
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
                     WHERE document_id = ${param_index}
                       AND upper(gstin) = ${param_index + 1}
                     RETURNING *
                """

                values.append(document_id)
                values.append(normalized_gstin)

                new_row = await conn.fetchrow(sql, *values)

                # --------------------------------------------------
                # 5️⃣ Version Audit
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
                    6,
                    gst_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Registration document updated successfully | document_id=%s",
                document_id,
            )

            return {
                **dict(new_row),
                "message": "Registration document updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # EXCEPTION HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(
                status_code=400,
                detail="Constraint validation failed.",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during registration document update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration document update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# -------------------------------------------------------------------
# SOFT DELETE REGISTRATION DOCUMENT (GSTIN + DOCUMENT_ID)
# -------------------------------------------------------------------
@router.delete(
    "/{gstin}/{document_id}/soft_delete",
    summary="Soft delete Registration Document (Production Ready + Version Audit)",
    responses={
        200: {"description": "Registration document soft deleted successfully."},
        400: {"description": "Validation failed."},
        404: {"description": "Registration document not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_document(
    gstin: str,
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    normalized_gstin = gstin.strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "soft_delete_registration_document",
        },
    )

    log.info(
        "Incoming soft delete registration document | gstin=%s | document_id=%s",
        normalized_gstin,
        document_id,
    )

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
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT gstin, customer_id, is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE upper(gstin) = $1
                     LIMIT 1
                    """,
                    normalized_gstin,
                )

                if not gst_row:
                    raise HTTPException(status_code=404, detail="GST not found.")

                if not gst_row["is_active"]:
                    raise HTTPException(status_code=400, detail="GST is inactive.")

                # --------------------------------------------------
                # 2️⃣ Fetch Existing Document (Active Only)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_documents
                     WHERE document_id = $1
                       AND upper(gstin) = $2
                     LIMIT 1
                    """,
                    document_id,
                    normalized_gstin,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found.",
                    )

                # --------------------------------------------------
                # 3️⃣ Business Rule:
                #     Cannot delete document if person still active
                # --------------------------------------------------
                if old_row["person_id"]:
                    person_row = await conn.fetchrow(
                        f"""
                        SELECT is_active
                          FROM {DB_SCHEMA}.registration_persons
                         WHERE person_id = $1
                        """,
                        old_row["person_id"],
                    )

                    if person_row and person_row["is_active"]:
                        raise HTTPException(
                            status_code=400,
                            detail="Deactivate the person first before deleting this document.",
                        )

                # --------------------------------------------------
                # 4️⃣ Concurrency Safe Soft Delete
                # --------------------------------------------------
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE document_id = $1
                       AND upper(gstin) = $2
                       AND is_active = TRUE
                     RETURNING *
                """

                deleted_row = await conn.fetchrow(
                    delete_sql,
                    document_id,
                    normalized_gstin,
                )

                if not deleted_row:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration document is already inactive.",
                    )

                # --------------------------------------------------
                # 5️⃣ Version Audit (DELETE)
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
                    6,
                    gst_row["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_row), default=str),
                )

            log.info(
                "Registration document soft deleted successfully | document_id=%s",
                document_id,
            )

            return {
                **dict(deleted_row),
                "message": "Registration document soft deleted successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DB EXCEPTION HANDLING
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
            log.exception("Database error during registration document soft delete")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration document soft delete")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )