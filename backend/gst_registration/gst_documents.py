import logging
import asyncpg
from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Query, Depends,status,UploadFile, File
from typing import Optional, List
from backend.security.rbac import require_permission
from backend.gst_registration.schemas import (
    RegistrationDocumentIn,
    RegistrationDocumentEditIn,
)
from backend.utils import get_db_pool, DB_SCHEMA, generate_uuid, get_blob_service_client, AZURE_STORAGE_CONTAINER, generate_blob_sas_url, extract_blob_path,build_gst_visibility, build_gst_filing_visibility
from backend.logger import logger
from backend.text_search_filters import append_fuzzy_name_filter
from backend.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
from urllib.parse import urlparse

router = APIRouter(
    prefix="/api/v1/gst-documents",
    tags=["GST Registration Documents"],
)


def _gst_documents_filter_tag() -> str:
    return "gst_documents:filter:index"


async def _invalidate_gst_documents_cache() -> None:
    await redis_invalidate_tag(_gst_documents_filter_tag())
    # Required-documents GET depends on gst_registration_documents table state.
    await redis_invalidate_tag("document_config:required_documents:index")

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
                        verified_at,
                        created_at,
                        updated_at,
                        is_active
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,TRUE
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
                    now if payload.verified else None,
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
            await _invalidate_gst_documents_cache()

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
            if constraint not in UNIQUE_MAP:
                log.warning("Unmapped unique violation | constraint=%s", constraint)
            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    "Duplicate value violates a uniqueness rule.",
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
            if constraint not in CHECK_MAP:
                log.warning("Unmapped check violation | constraint=%s", constraint)
            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(constraint, "Data violates a validation rule."),
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
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    """
    Filter Registration Documents (Enterprise Standard)
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    role = current_user.get("role")

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
    role_norm = str(role).strip().upper() if role is not None else None
    emp_id_for_scope = int(current_emp_id) if str(current_emp_id).isdigit() else None
    gstin_norm = gstin.strip().upper() if gstin and gstin.strip() else None
    document_type_norm = document_type.strip() if document_type and document_type.strip() else None
    mobile_norm = mobile.strip() if mobile and mobile.strip() else None
    cache_key = build_cache_key(
        "gst_documents:filter",
        gstin=gstin_norm,
        person_id=person_id,
        document_type=document_type_norm,
        verified=verified,
        mobile=mobile_norm,
        is_active=is_active,
        include_inactive=include_inactive,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
        role=role_norm,
        emp_id=emp_id_for_scope,
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

    async def _load_registration_documents():
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Indexed Exact Match Filters
        # --------------------------------------------------

        if person_id is not None:
            conditions.append(f"d.person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if gstin_norm:
            conditions.append(f"UPPER(d.gstin) = ${param_index}")
            values.append(gstin_norm)
            param_index += 1

        if verified is not None:
            conditions.append(f"d.verified = ${param_index}")
            values.append(verified)
            param_index += 1

        if mobile_norm:
            conditions.append(f"d.mobile = ${param_index}")
            values.append(mobile_norm)
            param_index += 1

        # --------------------------------------------------
        # Partial Match Filters
        # --------------------------------------------------

        if document_type_norm:
            # Fixed dropdown enum — exact match, not fuzzy substring/word match.
            conditions.append(f"upper(trim(d.document_type)) = upper(trim(${param_index}))")
            values.append(document_type_norm)
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"d.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("d.is_active = TRUE")

        # --------------------------------------------------
        # Date Filtering
        # --------------------------------------------------

        if from_date:
            conditions.append(f"d.created_at::date >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"d.created_at::date <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY (GST → PERSON → DOCUMENT)
        # --------------------------------------------------

        visibility_sql, visibility_values, param_index = build_gst_visibility(
            role_norm,
            emp_id_for_scope,
            param_index,
            DB_SCHEMA,
        )

        if visibility_sql:

            visibility_sql = f"""
            d.person_id IN (
                SELECT p.person_id
                FROM {DB_SCHEMA}.gst_registration_persons p
                WHERE p.gst_registration_id IN (
                    SELECT g.id
                    FROM {DB_SCHEMA}.gst_registration g
                    WHERE {visibility_sql}
                )
            )
            """

            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT Query
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.gst_registration_documents d
            {where_clause}
        """

        # --------------------------------------------------
        # DATA Query
        # --------------------------------------------------

        data_sql = f"""
            SELECT
                d.*,
                p.full_name,
                g.rm_id,
                g.created_by,
                e_rm.first_name AS rm_name,
                e_creator.first_name AS created_by_name,
                e_verify.first_name AS verified_by_name
            FROM {DB_SCHEMA}.gst_registration_documents d
            LEFT JOIN {DB_SCHEMA}.gst_registration_persons p
                   ON d.person_id = p.person_id
            LEFT JOIN {DB_SCHEMA}.gst_registration g
                   ON p.gst_registration_id = g.id
            LEFT JOIN {DB_SCHEMA}.employees e_rm
                   ON g.rm_id = e_rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_creator
                   ON g.created_by = e_creator.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_verify
                   ON d.verified_by = e_verify.emp_id
            {where_clause}
            ORDER BY d.created_at DESC, d.document_id DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(data_sql, *values_with_pagination)

            log.info(
                "Registration documents filtered successfully | returned=%s total=%s",
                len(rows),
                total,
            )

            return {
                "data": [dict(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
                "request_id": request_id,
            }

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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_registration_documents,
        ttl_seconds=300,
        tags=[_gst_documents_filter_tag()],
    )
# -------------------------------------------------------------------
# EDIT REGISTRATION DOCUMENT (Flexible Verified + Version Audit)
# -------------------------------------------------------------------
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

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

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
            update_data["verified_at"] = now
        else:
            update_data["verified_by"] = None
            update_data["verified_at"] = None

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
                #     IDOR guard: a document is visible only if its person's
                #     parent GST registration is visible to the caller.
                # --------------------------------------------------
                visibility_sql, visibility_values, _vidx = build_gst_visibility(
                    role_norm, emp_id, 2, DB_SCHEMA,
                )
                fetch_conditions = ["d.document_id = $1", "d.is_active = TRUE"]
                fetch_values = [document_id]
                if visibility_sql:
                    # g (gst_registration) is joined directly below → scope on it.
                    fetch_conditions.append(f"({visibility_sql})")
                    fetch_values.extend(visibility_values)

                # customer_id lives on gst_registration (source of truth), not on
                # gst_registration_persons; join it (alias g) and select g.customer_id.
                old_row = await conn.fetchrow(
                    f"""
                    SELECT d.*, g.customer_id
                      FROM {DB_SCHEMA}.gst_registration_documents d
                      JOIN {DB_SCHEMA}.gst_registration_persons rp
                        ON d.person_id = rp.person_id
                      JOIN {DB_SCHEMA}.gst_registration g
                        ON rp.gst_registration_id = g.id
                     WHERE {' AND '.join(fetch_conditions)}
                     LIMIT 1
                    """,
                    *fetch_values,
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
                       AND is_active = TRUE
                     RETURNING *
                """

                new_row = await conn.fetchrow(sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Document state changed. Please retry.",
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
                await _invalidate_gst_documents_cache()

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
                    "Data violates a validation rule.",
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

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

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
                #     IDOR guard: only mutate a document whose person's parent
                #     GST registration is visible to the caller. Scope BOTH the
                #     update and the existence fallback so a non-visible doc
                #     returns 404 rather than leaking its existence.
                # --------------------------------------------------
                visibility_sql, visibility_values, _vidx = build_gst_visibility(
                    role_norm, emp_id, 2, DB_SCHEMA,
                )
                del_vis_clause = ""
                exist_vis_clause = ""
                extra_values = []
                if visibility_sql:
                    # g (gst_registration) is joined directly below, so scope on it.
                    del_vis_clause = f" AND ({visibility_sql})"
                    exist_vis_clause = (
                        f" AND person_id IN "
                        f"(SELECT p.person_id FROM {DB_SCHEMA}.gst_registration_persons p "
                        f"WHERE p.gst_registration_id IN "
                        f"(SELECT g.id FROM {DB_SCHEMA}.gst_registration g WHERE {visibility_sql}))"
                    )
                    extra_values = visibility_values

                # gst_registration_persons has no customer_id — the customer is
                # linked via gst_registration. Join it (alias g) to both scope
                # visibility and RETURN the correct customer_id (fixes a latent
                # `rp.customer_id does not exist` crash present before this change).
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons rp
                           JOIN {DB_SCHEMA}.gst_registration g
                             ON rp.gst_registration_id = g.id
                     WHERE d.document_id = $1
                       AND d.person_id = rp.person_id
                       AND d.is_active = TRUE
                       {del_vis_clause}
                     RETURNING d.*, g.customer_id
                """

                deleted_row = await conn.fetchrow(delete_sql, document_id, *extra_values)

                # --------------------------------------------------
                # If nothing updated → check existence
                # --------------------------------------------------
                if not deleted_row:
                    existing_row = await conn.fetchrow(
                        f"""
                        SELECT document_id, is_active
                          FROM {DB_SCHEMA}.gst_registration_documents
                         WHERE document_id = $1
                         {exist_vis_clause}
                        """,
                        document_id, *extra_values,
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
                    None,
                )

            log.info(
                "Document soft deleted successfully | document_id=%s",
                document_id,
            )
            await _invalidate_gst_documents_cache()

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
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

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
                #     IDOR guard: document visible only if its person's parent
                #     GST registration is visible to the caller.
                # --------------------------------------------------
                visibility_sql, visibility_values, _vidx = build_gst_visibility(
                    role_norm, emp_id, 2, DB_SCHEMA,
                )
                fetch_conditions = ["document_id = $1"]
                fetch_values = [document_id]
                if visibility_sql:
                    fetch_conditions.append(
                        f"person_id IN "
                        f"(SELECT p.person_id FROM {DB_SCHEMA}.gst_registration_persons p "
                        f"WHERE p.gst_registration_id IN "
                        f"(SELECT g.id FROM {DB_SCHEMA}.gst_registration g WHERE {visibility_sql}))"
                    )
                    fetch_values.extend(visibility_values)

                doc_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration_documents
                     WHERE {' AND '.join(fetch_conditions)}
                     FOR UPDATE
                    """,
                    *fetch_values,
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
                           JOIN {DB_SCHEMA}.gst_registration g
                             ON rp.gst_registration_id = g.id
                     WHERE d.document_id = $1
                       AND d.person_id = rp.person_id
                       AND d.is_active = FALSE
                     RETURNING d.*, g.customer_id
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
                    None,
                )

            log.info("Document activated successfully | document_id=%s", document_id)
            await _invalidate_gst_documents_cache()

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

# -------------------------------------------------------------------
# DEACTIVATE GST FILING DOCUMENT (SOFT DELETE)
# -------------------------------------------------------------------
@router.delete(
    "/gst-filing-documents/{document_id}/deactivate",
    summary="Deactivate GST Filing Document (Production Ready + Audit)",
)
async def deactivate_gst_filing_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id_raw,
            "api": "deactivate_gst_filing_document",
        },
    )

    log.info("Incoming GST filing document deactivate | document_id=%s", document_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 🔥 UPDATE WITH JOIN (GET CUSTOMER_ID)
                #     IDOR guard: only mutate a filing-document whose parent
                #     filing is visible to the caller. Scope BOTH the update and
                #     the existence fallback so a non-visible doc returns 404.
                # --------------------------------------------------
                visibility_sql, visibility_values, _vidx = build_gst_filing_visibility(
                    role_norm, emp_id, 2, DB_SCHEMA,
                )
                del_vis_clause = ""
                exist_vis_clause = ""
                extra_values = []
                if visibility_sql:
                    del_vis_clause = f" AND ({visibility_sql})"
                    exist_vis_clause = (
                        f" AND gst_filing_id IN "
                        f"(SELECT f.id FROM {DB_SCHEMA}.gst_filings f WHERE {visibility_sql})"
                    )
                    extra_values = visibility_values

                deleted_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_filings f
                     WHERE d.document_id = $1
                       AND d.gst_filing_id = f.id
                       AND d.is_active = TRUE
                       {del_vis_clause}
                     RETURNING d.*, f.customer_id
                    """,
                    document_id, *extra_values,
                )

                # --------------------------------------------------
                # HANDLE NOT UPDATED
                # --------------------------------------------------
                if not deleted_row:
                    existing = await conn.fetchrow(
                        f"""
                        SELECT document_id, is_active
                        FROM {DB_SCHEMA}.gst_filings_documents
                        WHERE document_id = $1
                        {exist_vis_clause}
                        """,
                        document_id, *extra_values,
                    )

                    if not existing:
                        raise HTTPException(404, "GST filing document not found.")

                    if existing["is_active"] is False:
                        raise HTTPException(400, "Document already inactive.")

                    raise HTTPException(409, "Document state changed. Please retry.")

                # --------------------------------------------------
                # OPTIONAL LOGGING
                # --------------------------------------------------
                if deleted_row["verified"]:
                    log.warning(
                        "Deactivating verified document | document_id=%s",
                        document_id,
                    )

                # --------------------------------------------------
                # VERSION AUDIT
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "GST_FILING_DOCUMENT",
                    document_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            log.info("Document deactivated successfully | document_id=%s", document_id)
            await _invalidate_gst_documents_cache()

            return {
                **dict(deleted_row),
                "message": "GST filing document deactivated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # ERROR HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(400, f"Constraint violated: {getattr(e,'constraint_name',None)}")

        except asyncpg.exceptions.DataError:
            raise HTTPException(400, "Invalid data format.")

        except asyncpg.PostgresError:
            log.exception("Database error during document deactivate")
            raise HTTPException(500, "Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during document deactivate")
            raise HTTPException(500, "Internal server error.")

