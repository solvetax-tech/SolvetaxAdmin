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
# CREATE REGISTRATION DOCUMENT (PRODUCTION STANDARD)
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
    Create Registration Document (Production Standard)

    Validation Responsibility:
    --------------------------
    1. Schema-level validation (Pydantic)
    2. GST existence & active validation
    3. Registration Person existence & active validation (if provided)
    4. DB-level constraint validation (FK / NOT NULL / CHECK)
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

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
            # --------------------------------------------------
            # Validate GST Exists & Active
            # --------------------------------------------------
            gst_row = await conn.fetchrow(
                f"""
                SELECT gstin, is_active
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
            # Validate Registration Person (If Provided)
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
            # Insert Registration Document
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
                VALUES ($1,$2,$3,$4,$5,$6,NOW(),NOW(),TRUE)
                RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(
                    insert_sql,
                    payload.gstin,
                    payload.person_id,
                    document_type,
                    document_url,
                    ownership_category,
                    mobile,
                )

            if not row:
                log.error("Registration document insert returned empty row")
                raise HTTPException(
                    status_code=500,
                    detail="Registration document creation failed.",
                )

            log.info(
                "Registration document created successfully document_id=%s",
                row["document_id"],
            )

            return {
                **dict(row),
                "message": "Registration document created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Database Exception Handling (Full Coverage)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Unique constraint violation during document creation")
            raise HTTPException(
                status_code=409,
                detail="Duplicate registration document.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation during document creation")
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning("Check constraint violation")
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning("NOT NULL constraint violation")
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

        except asyncpg.PostgresError:
            log.exception("Database error during document creation")
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
    1. FastAPI: Type validation + pagination validation
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
        "Incoming registration documents filter request limit=%s offset=%s",
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
    # Database Exception Handling
    # --------------------------------------------------
    except asyncpg.PostgresError:
        log.exception("Database error during registration documents filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error during registration documents filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# GET REGISTRATION DOCUMENT BY DOCUMENT_ID (ACTIVE ONLY)
# -------------------------------------------------------------------

@router.get(
    "/{document_id}/single_filter",
    summary="Get Registration Document",
    responses={
        200: {"description": "Registration document details."},
        404: {"description": "Registration document not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_registration_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Registration Document by document_id (Production Standard)

    ✔ Returns only active records
    ✔ Structured logging
    ✔ Safe SQL parameterization
    ✔ Full DB exception coverage
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "get_registration_document",
        },
    )

    log.info(
        "Incoming get registration document request | document_id=%s",
        document_id,
    )

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_documents
         WHERE document_id = $1
           AND is_active = TRUE
         LIMIT 1
    """

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
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, document_id)

        if not row:
            log.warning(
                "Registration document not found or inactive | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Registration document not found.",
            )

        log.info(
            "Registration document fetched successfully | document_id=%s",
            document_id,
        )

        return {
            **dict(row),
            "message": "Registration document fetched successfully.",
            "request_id": request_id,
        }

    except HTTPException:
        raise

    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration document fetch | "
            "document_id=%s | error=%s",
            document_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception(
            "Unexpected error during registration document fetch | document_id=%s",
            document_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )


# -------------------------------------------------------------------
# EDIT REGISTRATION DOCUMENT (Dynamic Update - Production Ready)
# -------------------------------------------------------------------
@router.post(
    "/{document_id}/edit",
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
    document_id: int,
    payload: RegistrationDocumentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Production-Ready Dynamic Registration Document Update API

    Features:
    ---------
    ✔ Dynamic field update (PATCH-like behavior)
    ✔ Structured logging with request_id & emp_id
    ✔ Field normalization
    ✔ Active-only update (is_active = TRUE)
    ✔ Safe SQL parameterization
    ✔ Transaction handling
    ✔ Full DB exception coverage
    ✔ Enterprise-grade error handling

    Validation Responsibility:
    --------------------------
    1. Schema-Level (Pydantic - RegistrationDocumentEditIn)
    2. Database-Level:
       - FOREIGN KEY constraints
       - NOT NULL constraints
       - Check constraints
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "edit_registration_document",
        },
    )

    log.info(
        "Incoming edit registration document request | document_id=%s",
        document_id,
    )

    # --------------------------------------------------
    # Extract Only Provided Fields
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception as e:
        log.exception(
            "Failed to serialize payload | document_id=%s | error=%s",
            document_id,
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid request payload.",
        )

    if not update_data:
        log.warning("No fields provided for update | document_id=%s", document_id)
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
            "Error during field normalization | document_id=%s | payload=%s | error=%s",
            document_id,
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
            "Database pool acquisition failed | document_id=%s | error=%s",
            document_id,
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            fields = []
            values = []
            param_index = 1

            # --------------------------------------------------
            # Build Dynamic SET Clause (SQL Injection Safe)
            # --------------------------------------------------
            for field_name, value in update_data.items():
                fields.append(f"{field_name} = ${param_index}")
                values.append(value)
                param_index += 1

            # Always update updated_at
            fields.append("updated_at = NOW()")

            sql = f"""
                UPDATE {DB_SCHEMA}.registration_documents
                   SET {', '.join(fields)}
                 WHERE document_id = ${param_index}
                   AND is_active = TRUE
                 RETURNING *
            """

            values.append(document_id)

            log.debug(
                "Executing registration document update | document_id=%s | fields=%s",
                document_id,
                list(update_data.keys()),
            )

            # --------------------------------------------------
            # Atomic Transaction
            # --------------------------------------------------
            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            # --------------------------------------------------
            # Not Found / Inactive Handling
            # --------------------------------------------------
            if not row:
                check_sql = f"""
                    SELECT document_id, is_active
                      FROM {DB_SCHEMA}.registration_documents
                     WHERE document_id = $1
                """
                existing = await conn.fetchrow(check_sql, document_id)

                if not existing:
                    log.warning(
                        "Registration document not found | document_id=%s",
                        document_id,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found.",
                    )

                if existing["is_active"] is False:
                    log.warning(
                        "Registration document is inactive | document_id=%s",
                        document_id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Registration document is inactive.",
                    )

            log.info(
                "Registration document updated successfully | document_id=%s | updated_fields=%s",
                document_id,
                list(update_data.keys()),
            )

            return {
                **dict(row),
                "message": "Registration document updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # FULL DATABASE EXCEPTION COVERAGE
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            log.warning(
                "Unique constraint violation | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning(
                "Foreign key violation | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError:
            log.warning(
                "Check constraint violation | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Check constraint validation failed.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            log.warning(
                "NOT NULL constraint violation | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            log.error(
                "Invalid data format | document_id=%s",
                document_id,
                exc_info=True,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Postgres database error during document update | "
                "document_id=%s | error=%s",
                document_id,
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
                "Unexpected error during registration document update | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

# =========================================================
# SOFT DELETE REGISTRATION DOCUMENT (is_active = false)
# =========================================================

@router.delete(
    "/{document_id}/soft_delete",
    summary="Soft delete Registration Document by setting is_active to false",
    responses={
        200: {"description": "Registration document soft deleted successfully."},
        400: {"description": "Registration document already inactive."},
        404: {"description": "Registration document not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete Registration Document by updating is_active to FALSE.

    Behavior:
    ---------
    - Does NOT remove the row from DB
    - Sets is_active = FALSE
    - Updates updated_at timestamp
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "soft_delete_registration_document",
        },
    )

    log.info(
        "Incoming soft delete registration document request | document_id=%s",
        document_id,
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
            # --------------------------------------------------
            # Soft Delete Query
            # --------------------------------------------------
            sql = f"""
                UPDATE {DB_SCHEMA}.registration_documents
                   SET is_active = FALSE,
                       updated_at = NOW()
                 WHERE document_id = $1
                   AND is_active = TRUE
                 RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(sql, document_id)

            # --------------------------------------------------
            # Not Found / Already Inactive Handling
            # --------------------------------------------------
            if not row:
                check_sql = f"""
                    SELECT document_id, is_active
                      FROM {DB_SCHEMA}.registration_documents
                     WHERE document_id = $1
                """
                existing = await conn.fetchrow(check_sql, document_id)

                if not existing:
                    log.warning(
                        "Registration document not found | document_id=%s",
                        document_id,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="Registration document not found.",
                    )

                if existing["is_active"] is False:
                    log.warning(
                        "Registration document already inactive | document_id=%s",
                        document_id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Registration document is already inactive.",
                    )

            log.info(
                "Registration document soft deleted successfully | document_id=%s",
                document_id,
            )

            return {
                **dict(row),
                "message": "Registration document soft deleted successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Foreign key violation | document_id=%s", document_id)
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during registration document soft delete | "
                "document_id=%s | error=%s",
                document_id,
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
            log.exception(
                "Unexpected error during registration document soft delete | document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
