import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import date, datetime
from backend.gst_registration_filing.schemas import GSTFilingDocumentIn, GSTFilingDocumentEditIn
from backend.gst_registration_filing.gst_filter_rules import (
    append_document_filter_rule_group,
    normalize_match_mode,
)
from backend.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_filing_visibility
from backend.security.rbac import require_permission
from backend.logger import logger
from backend.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from zoneinfo import ZoneInfo
import json
import uuid
import re

router = APIRouter(
    prefix="/api/v1/gst-filings-docs",
    tags=["GST Filings Docs"],
)


def _gst_filing_documents_filter_tag() -> str:
    return "gst_filing_documents:filter:index"


async def _invalidate_gst_filing_documents_cache() -> None:
    await redis_invalidate_tag(_gst_filing_documents_filter_tag())
    await redis_invalidate_tag("gst_filing:table:filings:index")
    await redis_invalidate_tag("gst_filing:table:return_details:index")

# -------------------------------------------------------------------
# CREATE GST FILING DOCUMENT (link URL in DB only; no blob)
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing Document (Excel/Sheet link)",
    responses={
        201: {"description": "GST filing document created successfully."},
        400: {"description": "Validation failed or filing not found."},
        409: {"description": "Duplicate document."},
        500: {"description": "Database or internal error."},
    },
)
async def create_gst_filing_document(
    payload: GSTFilingDocumentIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming GST Filing Document create | filing_id=%s | type=%s | verified=%s",
        payload.gst_filing_id,
        payload.document_type,
        payload.verified,
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ FETCH GST FILING (SOURCE OF TRUTH)
                # --------------------------------------------------
                filing_row = await conn.fetchrow(
                    f"""
                    SELECT id,
                           gstin,
                           customer_id,
                           is_active
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE id = $1
                    LIMIT 1
                    """,
                    payload.gst_filing_id,
                )

                if not filing_row:
                    raise HTTPException(400, "GST filing not found.")

                if filing_row["is_active"] is False:
                    raise HTTPException(400, "GST filing is inactive.")

                # GSTIN fallback
                gstin = payload.gstin or filing_row["gstin"]
                gstin = gstin.strip().upper() if gstin else None

                # --------------------------------------------------
                # 2️⃣ INSERT ROW (document_url = external link string only)
                # --------------------------------------------------
                document_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.gst_filings_documents (
                        gst_filing_id,
                        gstin,
                        document_type,
                        document_url,
                        verified,
                        verified_by,
                        verified_at,
                        remarks,
                        created_at,
                        updated_at,
                        is_active
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,TRUE
                    )
                    RETURNING *
                    """,
                    payload.gst_filing_id,
                    gstin,
                    payload.document_type,
                    payload.document_url,
                    payload.verified,
                    emp_id if payload.verified else None,
                    now if payload.verified else None,
                    payload.remarks,
                    now,
                    now,
                )

                if not document_row:
                    raise HTTPException(500, "GST filing document creation failed.")

                # --------------------------------------------------
                # 3️⃣ VERSION AUDIT
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
                    "GST_FILING_DOCUMENT",
                    document_row["document_id"],
                    filing_row["customer_id"],
                    "CREATE",
                    json.dumps(dict(document_row), default=str),
                    None,
                )

            log.info(
                "GST Filing document created successfully | document_id=%s",
                document_row["document_id"],
            )
            await _invalidate_gst_filing_documents_cache()

            return {
                **dict(document_row),
                "message": "GST filing document created successfully.",
                "request_id": request_id,
            }

        # =====================================================
        # DB ERROR HANDLING (🔥 FULL)
        # =====================================================
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "uq_gst_filing_doc_unique":
                    "This document type already exists for this filing (active)."
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_doc_gstin_format": "Invalid GSTIN format.",
                "chk_verified_logic": "Verification logic invalid.",
                "chk_document_type_upper": "Document type must be uppercase.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing document creation")
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing document creation")
            raise HTTPException(500, "Internal server error.")

# -------------------------------------------------------------------
# UPDATE GST FILING DOCUMENT (link URL in DB only; no blob)
# -------------------------------------------------------------------
@router.patch(
    "/{document_id}",
    summary="Update GST Filing Document (Excel/Sheet link)",
)
async def update_gst_filing_document(
    document_id: int,
    payload: GSTFilingDocumentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "SPECIAL")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database connection error")
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ FETCH EXISTING DOCUMENT (LOCK)
                # --------------------------------------------------
                old = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filings_documents
                    WHERE document_id = $1
                    FOR UPDATE
                    """,
                    document_id,
                )

                if not old:
                    raise HTTPException(404, "GST filing document not found")

                update_data = payload.model_dump(exclude_unset=True)

                if not update_data:
                    raise HTTPException(400, "No fields to update")

                # --------------------------------------------------
                # 2️⃣ FETCH FILING (FOR GSTIN FALLBACK)
                # --------------------------------------------------
                filing = await conn.fetchrow(
                    f"""
                    SELECT gstin, customer_id, is_active
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE id = $1
                    """,
                    old["gst_filing_id"],
                )

                if not filing:
                    raise HTTPException(400, "Associated GST filing not found")

                if filing["is_active"] is False:
                    raise HTTPException(400, "GST filing is inactive")

                # --------------------------------------------------
                # 3️⃣ GSTIN LOGIC
                # --------------------------------------------------
                if "gstin" in update_data:
                    update_data["gstin"] = (
                        update_data["gstin"]
                        or filing["gstin"]
                    )

                # --------------------------------------------------
                # 4️⃣ VERIFIED HANDLING
                # --------------------------------------------------
                if "verified" in update_data:
                    if update_data["verified"]:
                        update_data["verified_by"] = emp_id
                        update_data["verified_at"] = now
                    else:
                        update_data["verified_by"] = None
                        update_data["verified_at"] = None

                # --------------------------------------------------
                # 5️⃣ BUILD UPDATE QUERY
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append(f"updated_at = ${idx}")
                values.append(now)
                idx += 1

                values.append(document_id)

                new = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings_documents
                    SET {', '.join(fields)}
                    WHERE document_id = ${idx}
                    RETURNING *
                    """,
                    *values,
                )

                # --------------------------------------------------
                # 6️⃣ VERSION AUDIT
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
                    "GST_FILING_DOCUMENT",
                    document_id,
                    filing["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old), default=str),
                    json.dumps(dict(new), default=str),
                )
                await _invalidate_gst_filing_documents_cache()

                return {
                    "data": dict(new),
                    "message": "GST filing document updated successfully",
                    "request_id": request_id,
                }

        # =====================================================
        # DB ERROR HANDLING (🔥 FULL)
        # =====================================================
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "uq_gst_filing_doc_unique":
                    "This document type already exists for this filing (active)."
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_doc_gstin_format": "Invalid GSTIN format.",
                "chk_verified_logic": "Verification logic invalid.",
                "chk_document_type_upper": "Document type must be uppercase.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST filing document update")
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST filing document update")
            raise HTTPException(500, "Internal server error.")


# -------------------------------------------------------------------
# FILTER GST FILING DOCUMENTS (ENTERPRISE PRODUCTION READY - FINAL)
# -------------------------------------------------------------------
@router.get(
    "/gst-filing-documents/filter",
    summary="Filter GST Filing Documents",
)
async def filter_gst_filing_documents(

    # PRIMARY
    document_id: Optional[int] = None,
    gst_filing_id: Optional[int] = None,
    gstin: Optional[str] = None,

    # DOCUMENT
    document_type: Optional[str] = None,
    verified: Optional[bool] = None,
    document_filter_match: Optional[str] = Query(
        "AND",
        description="Combine document_filter_rules with AND or OR.",
    ),
    document_filter_rules: Optional[List[str]] = Query(
        None,
        description="Document rules like DOCUMENT_TYPE:WORKING_SHEET and VERIFIED:VERIFIED.",
    ),

    # USERS
    verified_by: Optional[int] = None,

    # DATE FILTERS
    created_from: Optional[date] = None,
    created_to: Optional[date] = None,

    verified_from: Optional[date] = None,
    verified_to: Optional[date] = None,

    # FLAGS
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),

    # PAGINATION
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_gst_filing_documents"},
    )

    log.info("Incoming GST filing documents filter | limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # DATE VALIDATION
    # --------------------------------------------------
    if created_from and created_to and created_from > created_to:
        raise HTTPException(400, "created_from cannot be greater than created_to")

    if verified_from and verified_to and verified_from > verified_to:
        raise HTTPException(400, "verified_from cannot be greater than verified_to")
    if document_filter_rules and (document_type or verified is not None):
        raise HTTPException(400, "Use document_filter_rules or document_type/verified, not both")
    try:
        if document_filter_rules:
            normalize_match_mode(document_filter_match)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gstin_norm = gstin.strip().upper() if gstin and gstin.strip() else None
    document_type_norm = document_type.strip().upper() if document_type and document_type.strip() else None
    cache_key = build_cache_key(
        "gst_filing_documents:filter",
        document_id=document_id,
        gst_filing_id=gst_filing_id,
        gstin=gstin_norm,
        document_type=document_type_norm,
        verified=verified,
        document_filter_match=document_filter_match,
        document_filter_rules=document_filter_rules,
        verified_by=verified_by,
        created_from=created_from,
        created_to=created_to,
        verified_from=verified_from,
        verified_to=verified_to,
        is_active=is_active,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
        role=role_norm,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    async def _load_filter_gst_filing_documents():
        conditions = []
        values = []
        idx = 1

        # --------------------------------------------------
        # BASIC FILTERS
        # --------------------------------------------------
        if document_id:
            conditions.append(f"d.document_id = ${idx}")
            values.append(document_id)
            idx += 1

        if gst_filing_id:
            conditions.append(f"d.gst_filing_id = ${idx}")
            values.append(gst_filing_id)
            idx += 1

        if gstin_norm:
            conditions.append(f"upper(d.gstin) = ${idx}")
            values.append(gstin_norm)
            idx += 1

        # --------------------------------------------------
        # DOCUMENT FILTERS
        # --------------------------------------------------
        use_document_rules = bool(document_filter_rules)

        if not use_document_rules and document_type_norm:
            conditions.append(f"d.document_type = ${idx}")
            values.append(document_type_norm)
            idx += 1

        if not use_document_rules and verified is not None:
            conditions.append(f"d.verified = ${idx}")
            values.append(verified)
            idx += 1

        if use_document_rules:
            idx = append_document_filter_rule_group(
                conditions,
                values,
                idx,
                rules=document_filter_rules,
                match_mode=document_filter_match or "AND",
            )

        if verified_by:
            conditions.append(f"d.verified_by = ${idx}")
            values.append(verified_by)
            idx += 1

        # --------------------------------------------------
        # DATE FILTERS
        # --------------------------------------------------
        if created_from:
            conditions.append(f"d.created_at::date >= ${idx}")
            values.append(created_from)
            idx += 1

        if created_to:
            conditions.append(f"d.created_at::date <= ${idx}")
            values.append(created_to)
            idx += 1

        if verified_from:
            conditions.append(f"d.verified_at::date >= ${idx}")
            values.append(verified_from)
            idx += 1

        if verified_to:
            conditions.append(f"d.verified_at::date <= ${idx}")
            values.append(verified_to)
            idx += 1

        # --------------------------------------------------
        # FLAGS
        # --------------------------------------------------
        if is_active is not None:
            conditions.append(f"d.is_active = ${idx}")
            values.append(is_active)
            idx += 1
        elif not include_inactive:
            conditions.append("d.is_active = TRUE")

        # --------------------------------------------------
        # 🔥 VISIBILITY (JOIN WITH GST FILINGS)
        # --------------------------------------------------
        visibility_sql, visibility_values, idx = build_gst_filing_visibility(
            role_norm, emp_id, idx, DB_SCHEMA
        )

        if visibility_sql:
            # IMPORTANT: apply visibility on filing alias (f)
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # --------------------------------------------------
        # QUERY BUILD
        # --------------------------------------------------
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.gst_filings_documents d
            JOIN {DB_SCHEMA}.gst_filings f
                ON f.id = d.gst_filing_id
            {where_clause}
        """

        data_sql = f"""
            SELECT 
                d.*,
                f.customer_id,
                f.filing_category,
                f.filing_period,
                f.status AS filing_status,
                rm.first_name AS rm_name,
                op.first_name AS op_name,
                vb.first_name AS verified_by_name
            FROM {DB_SCHEMA}.gst_filings_documents d
            JOIN {DB_SCHEMA}.gst_filings f
                ON f.id = d.gst_filing_id
            LEFT JOIN {DB_SCHEMA}.employees rm
                ON rm.emp_id = f.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op
                ON op.emp_id = f.op_id
            LEFT JOIN {DB_SCHEMA}.employees vb
                ON vb.emp_id = d.verified_by
            {where_clause}
            ORDER BY d.created_at DESC, d.document_id DESC
            LIMIT ${idx} OFFSET ${idx+1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "GST filing documents filter success | returned=%s total=%s",
            len(rows), total
        )

        return {
            "data": [dict(r) for r in rows],
            "count": total,
            "limit": limit,
            "offset": offset,
            "request_id": request_id
        }

    # --------------------------------------------------
    # ERROR HANDLING
    # --------------------------------------------------
    return await redis_get_or_set_json(
        cache_key,
        loader=_load_filter_gst_filing_documents,
        ttl_seconds=300,
        tags=[_gst_filing_documents_filter_tag()],
    )
# -------------------------------------------------------------------
# DEACTIVATE GST FILING DOCUMENT (SOFT DELETE)
# -------------------------------------------------------------------
@router.delete(
    "/gst-filing-documents/{document_id}/deactivate",
    summary="Deactivate GST Filing Document (Production Ready + Audit)",
)
async def deactivate_gst_filing_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

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
                # --------------------------------------------------
                deleted_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_filings f
                     WHERE d.document_id = $1
                       AND d.gst_filing_id = f.id
                       AND d.is_active = TRUE
                     RETURNING d.*, f.customer_id
                    """,
                    document_id,
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
                        """,
                        document_id,
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
            await _invalidate_gst_filing_documents_cache()

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


# -------------------------------------------------------------------
# ACTIVATE GST FILING DOCUMENT (FINAL)
# -------------------------------------------------------------------
@router.post(
    "/gst-filing-documents/{document_id}/activate",
    summary="Activate GST Filing Document (Production Ready + Audit)",
)
async def activate_gst_filing_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_gst_filing_document",
        },
    )

    log.info("Incoming GST filing document activation | document_id=%s", document_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # LOCK ROW
                # --------------------------------------------------
                doc_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_filings_documents
                    WHERE document_id = $1
                    FOR UPDATE
                    """,
                    document_id,
                )

                if not doc_row:
                    raise HTTPException(404, "GST filing document not found.")

                if doc_row["is_active"]:
                    raise HTTPException(400, "Document already active.")

                # --------------------------------------------------
                # PARENT FILINGS SAFETY (avoid activating doc under inactive filing)
                # --------------------------------------------------
                parent_filing = await conn.fetchrow(
                    f"""
                    SELECT id, is_active
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE id = $1
                    """,
                    doc_row["gst_filing_id"],
                )

                if not parent_filing:
                    raise HTTPException(
                        400,
                        "Associated GST filing not found for this document.",
                    )

                if parent_filing["is_active"] is False:
                    raise HTTPException(400, "GST filing is inactive.")

                # --------------------------------------------------
                # ACTIVATE + FETCH CUSTOMER
                # --------------------------------------------------
                activated_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings_documents d
                       SET is_active = TRUE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_filings f
                     WHERE d.document_id = $1
                       AND d.gst_filing_id = f.id
                       AND f.is_active = TRUE
                       AND d.is_active = FALSE
                     RETURNING d.*, f.customer_id
                    """,
                    document_id,
                )

                if not activated_row:
                    raise HTTPException(
                        409,
                        "Document state changed while activating. Please retry.",
                    )

                # OPTIONAL LOG
                if activated_row["verified"]:
                    log.warning("Activating verified document | document_id=%s", document_id)

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
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            log.info("Document activated successfully | document_id=%s", document_id)
            await _invalidate_gst_filing_documents_cache()

            return {
                **dict(activated_row),
                "message": "GST filing document activated successfully.",
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
            log.exception("Database error during document activation")
            raise HTTPException(500, "Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during document activation")
            raise HTTPException(500, "Internal server error.")

            





