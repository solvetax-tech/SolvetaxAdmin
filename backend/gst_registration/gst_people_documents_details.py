"""
person_document_details — one person per row for a GST registration, with that
person's documents held inline as a JSONB array (see V002 migration).

Replaces the split gst_people + gst_documents modules. The RM creates a person
and their whole document set in one save; the OP reads/downloads them (each file
named by its document type) and updates the registration status elsewhere.

Documents element shape: {"document_type": "...", "document_url": "https://..."}.
gstin / ownership_category / customer_id are NOT stored here — they are read
from gst_registration via gst_registration_id. Required-documents rules stay in
document_config, joined through the registration's ownership_category.
"""

import json
import logging
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.security.rbac import require_permission
from backend.gst_registration.schemas import (
    PersonWithDocumentsIn,
    PersonWithDocumentsEditIn,
    DocumentUpsertIn,
)
from backend.utils import (
    get_db_pool,
    DB_SCHEMA,
    generate_uuid,
    build_gst_visibility,
    extract_blob_path,
    generate_blob_sas_url,
)
from backend.logger import logger
from backend.text_search_filters import append_fuzzy_name_filter
from backend.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)

router = APIRouter(
    prefix="/api/v1/person-document-details",
    tags=["Person Document Details"],
)

IST = ZoneInfo("Asia/Kolkata")
ENTITY_TYPE = "PERSON_DOCUMENT_DETAILS"

_FILTER_TAG = "person_document_details:filter:index"
_REQUIRED_TAG = "person_document_details:required_documents:index"


async def _invalidate_cache() -> None:
    await redis_invalidate_tag(_FILTER_TAG)
    await redis_invalidate_tag(_REQUIRED_TAG)


def _emp_id(current_user) -> Optional[int]:
    raw = current_user.get("emp_id") or current_user.get("sub")
    return int(raw) if str(raw).isdigit() else None


def _parse_documents(raw) -> list:
    """asyncpg may hand back JSONB as text; normalize to a Python list."""
    if raw is None:
        return []
    if isinstance(raw, (list, dict)):
        return raw if isinstance(raw, list) else [raw]
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _serialize_person(row) -> dict:
    """Row -> response dict with documents as a real JSON array."""
    data = dict(row)
    if "documents" in data:
        data["documents"] = _parse_documents(data["documents"])
    return data


def _dump_documents(items) -> str:
    """Normalize PersonDocumentItem list -> JSON text, deduped by type (last wins)."""
    by_type = {}
    for item in items or []:
        dtype = str(item.document_type).strip().upper()
        by_type[dtype] = {
            "document_type": dtype,
            "document_url": str(item.document_url).strip(),
        }
    return json.dumps(list(by_type.values()))


def _scope_to_visible_registrations(role_norm, emp_id, start_idx):
    """
    IDOR guard: a person is visible only if its parent GST registration is
    visible to the caller. Returns (clause_or_None, values, next_idx). The
    clause constrains pdd.gst_registration_id.
    """
    vis_sql, vis_vals, next_idx = build_gst_visibility(role_norm, emp_id, start_idx, DB_SCHEMA)
    if not vis_sql:
        return None, [], next_idx
    clause = (
        f"pdd.gst_registration_id IN "
        f"(SELECT g.id FROM {DB_SCHEMA}.gst_registration g WHERE {vis_sql})"
    )
    return clause, vis_vals, next_idx


# ------------------------------------------------------------------------- #
# DESIGNATIONS (by the registration's ownership category)
# ------------------------------------------------------------------------- #
@router.get(
    "/gst-registration/{gst_id}/designations",
    summary="Get designations for a GST registration's ownership category",
)
async def get_designations(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    cache_key = build_cache_key("person_document_details:designations", gst_id=gst_id, emp_id=emp_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load():
        async with pool.acquire() as conn:
            gst_row = await conn.fetchrow(
                f"""
                SELECT id, ownership_category
                FROM {DB_SCHEMA}.gst_registration
                WHERE id = $1 AND is_active = TRUE
                """,
                gst_id,
            )
            if not gst_row:
                raise HTTPException(status_code=404, detail="GST registration not found or inactive.")

            ownership_norm = (
                str(gst_row["ownership_category"]).strip().upper()
                if gst_row["ownership_category"] is not None else None
            )
            rows = await conn.fetch(
                f"""
                SELECT value, display_name, description
                FROM {DB_SCHEMA}.gst_registration_config
                WHERE upper(trim(config_type)) = $1 AND is_active = TRUE
                ORDER BY sort_order
                """,
                ownership_norm,
            )
            return {
                "gst_id": gst_id,
                "ownership_category": gst_row["ownership_category"],
                "designations": [dict(r) for r in rows],
                "request_id": request_id,
            }

    return await redis_get_or_set_json(
        cache_key, loader=_load, ttl_seconds=300,
        tags=["person_document_details:designations:index"],
    )


# ------------------------------------------------------------------------- #
# CREATE PERSON + DOCUMENTS (one save)
# ------------------------------------------------------------------------- #
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a person with their documents (single save)",
    responses={
        201: {"description": "Person created."},
        400: {"description": "Validation failed or GST not found."},
        409: {"description": "Duplicate value."},
        500: {"description": "Database or internal error."},
    },
)
async def create_person_with_documents(
    payload: PersonWithDocumentsIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})
    now = datetime.now(IST)

    log.info(
        "Create person+documents | gst_registration_id=%s docs=%s",
        payload.gst_registration_id, len(payload.documents),
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT id, customer_id, is_active
                    FROM {DB_SCHEMA}.gst_registration
                    WHERE id = $1
                    """,
                    payload.gst_registration_id,
                )
                if not gst_row:
                    raise HTTPException(status_code=400, detail="GST registration not found.")
                if not gst_row["is_active"]:
                    raise HTTPException(status_code=400, detail="GST registration is inactive.")

                documents_json = _dump_documents(payload.documents)

                person_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.person_document_details
                        (gst_registration_id, full_name, designation, phone, email,
                         pan, aadhaar, is_primary, documents, is_active, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,TRUE,$10,$10)
                    RETURNING *
                    """,
                    payload.gst_registration_id,
                    payload.full_name,
                    payload.designation,
                    payload.phone,
                    payload.email,
                    payload.pan,
                    payload.aadhaar,
                    payload.is_primary,
                    documents_json,
                    now,
                )
                if not person_row:
                    raise HTTPException(status_code=500, detail="Person creation failed.")

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id, ENTITY_TYPE, person_row["person_id"], gst_row["customer_id"],
                    "CREATE", json.dumps(_serialize_person(person_row), default=str), None,
                )

            await _invalidate_cache()
            log.info("Person created | person_id=%s", person_row["person_id"])
            return {
                **_serialize_person(person_row),
                "message": "Person and documents created successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.UniqueViolationError as e:
            raise HTTPException(status_code=409, detail=_UNIQUE_MAP.get(
                getattr(e, "constraint_name", None), "Duplicate value violates a uniqueness rule."))
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Invalid GST registration reference.")
        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(status_code=400, detail=_CHECK_MAP.get(
                getattr(e, "constraint_name", None), "Data violates a validation rule."))
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error during person create")
            raise HTTPException(status_code=500, detail="Database error.")
        except Exception:
            log.exception("Unexpected error during person create")
            raise HTTPException(status_code=500, detail="Internal server error.")


_UNIQUE_MAP = {
    "ux_pdd_one_primary": "Only one active primary member is allowed per registration.",
    "ux_pdd_pan_per_reg": "This PAN already exists for this registration.",
    "ux_pdd_aadhaar_per_reg": "This Aadhaar already exists for this registration.",
    "ux_pdd_email_per_reg": "This email already exists for this registration.",
    "ux_pdd_phone_per_reg": "This phone already exists for this registration.",
}
_CHECK_MAP = {
    "chk_pdd_pan_format": "Invalid PAN format. Expected: ABCDE1234F",
    "chk_pdd_aadhaar_format": "Invalid Aadhaar format (12 digits).",
    "chk_pdd_phone_format": "Invalid phone format (10 digits).",
    "chk_pdd_documents_is_array": "Documents must be a list.",
}


# ------------------------------------------------------------------------- #
# LIST PERSONS (+ their documents) — dynamic filter + pagination
# ------------------------------------------------------------------------- #
@router.get(
    "/dynamic_filter",
    summary="Filter persons (with their documents)",
)
async def list_persons(
    person_id: Optional[int] = None,
    gst_registration_id: Optional[int] = None,
    full_name: Optional[str] = None,
    designation: Optional[str] = None,
    pan: Optional[str] = None,
    aadhaar: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    is_primary: Optional[bool] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date cannot be greater than to_date.")

    pan_norm = pan.strip().upper() if pan and pan.strip() else None
    aadhaar_norm = aadhaar.strip() if aadhaar and aadhaar.strip() else None
    phone_norm = phone.strip() if phone and phone.strip() else None
    email_norm = email.strip().lower() if email and email.strip() else None
    full_name_norm = full_name.strip() if full_name and full_name.strip() else None
    designation_norm = designation.strip() if designation and designation.strip() else None

    cache_key = build_cache_key(
        "person_document_details:filter",
        person_id=person_id, gst_registration_id=gst_registration_id,
        full_name=full_name_norm, designation=designation_norm, pan=pan_norm,
        aadhaar=aadhaar_norm, phone=phone_norm, email=email_norm,
        is_primary=is_primary, is_active=is_active, include_inactive=include_inactive,
        from_date=from_date, to_date=to_date, limit=limit, offset=offset,
        role=role_norm, emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load():
        conditions, values, idx = [], [], 1

        if person_id is not None:
            conditions.append(f"pdd.person_id = ${idx}"); values.append(person_id); idx += 1
        if gst_registration_id is not None:
            conditions.append(f"pdd.gst_registration_id = ${idx}"); values.append(gst_registration_id); idx += 1
        if pan_norm:
            conditions.append(f"upper(pdd.pan) = ${idx}"); values.append(pan_norm); idx += 1
        if aadhaar_norm:
            conditions.append(f"trim(pdd.aadhaar) = ${idx}"); values.append(aadhaar_norm); idx += 1
        if phone_norm:
            conditions.append(f"btrim(pdd.phone) = btrim(${idx}::text)"); values.append(phone_norm); idx += 1
        if email_norm:
            conditions.append(f"lower(pdd.email) = ${idx}"); values.append(email_norm); idx += 1
        if is_primary is not None:
            conditions.append(f"pdd.is_primary = ${idx}"); values.append(is_primary); idx += 1
        if full_name_norm:
            idx = append_fuzzy_name_filter(conditions, values, idx, "pdd.full_name", full_name_norm)
        if designation_norm:
            conditions.append(f"upper(trim(pdd.designation)) = upper(trim(${idx}))")
            values.append(designation_norm); idx += 1

        if is_active is not None:
            conditions.append(f"pdd.is_active = ${idx}"); values.append(is_active); idx += 1
        elif not include_inactive:
            conditions.append("pdd.is_active = TRUE")

        if from_date:
            conditions.append(f"pdd.created_at::date >= ${idx}"); values.append(from_date); idx += 1
        if to_date:
            conditions.append(f"pdd.created_at::date <= ${idx}"); values.append(to_date); idx += 1

        vis_clause, vis_vals, idx = _scope_to_visible_registrations(role_norm, emp_id, idx)
        if vis_clause:
            conditions.append(vis_clause); values.extend(vis_vals)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        count_sql = f"SELECT COUNT(*) FROM {DB_SCHEMA}.person_document_details pdd {where_clause}"
        data_sql = f"""
            SELECT pdd.*,
                   g.rm_id, g.created_by, g.ownership_category,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name
            FROM {DB_SCHEMA}.person_document_details pdd
            LEFT JOIN {DB_SCHEMA}.gst_registration g ON pdd.gst_registration_id = g.id
            LEFT JOIN {DB_SCHEMA}.employees e_rm ON g.rm_id = e_rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_creator ON g.created_by = e_creator.emp_id
            {where_clause}
            ORDER BY pdd.created_at DESC, pdd.person_id DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """
        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(data_sql, *(values + [limit, offset]))
            return {"data": [_serialize_person(r) for r in rows], "total": total,
                    "limit": limit, "offset": offset, "request_id": request_id}
        except asyncpg.PostgresError:
            log.exception("Database error during person filtering")
            raise HTTPException(status_code=500, detail="Database error occurred during filtering.")

    return await redis_get_or_set_json(cache_key, loader=_load, ttl_seconds=300, tags=[_FILTER_TAG])


async def _fetch_person_scoped(conn, person_id, role_norm, emp_id, *, for_update=False, active_only=False):
    """Fetch a person the caller may see (IDOR-scoped), or None."""
    conditions = ["pdd.person_id = $1"]
    values = [person_id]
    if active_only:
        conditions.append("pdd.is_active = TRUE")
    vis_clause, vis_vals, _ = _scope_to_visible_registrations(role_norm, emp_id, 2)
    if vis_clause:
        conditions.append(vis_clause); values.extend(vis_vals)
    lock = "FOR UPDATE OF pdd" if for_update else ""
    return await conn.fetchrow(
        f"""
        SELECT pdd.*, g.customer_id, g.ownership_category
        FROM {DB_SCHEMA}.person_document_details pdd
        LEFT JOIN {DB_SCHEMA}.gst_registration g ON pdd.gst_registration_id = g.id
        WHERE {' AND '.join(conditions)}
        {lock}
        """,
        *values,
    )


# ------------------------------------------------------------------------- #
# GET ONE PERSON
# ------------------------------------------------------------------------- #
@router.get("/{person_id}", summary="Get one person with their documents")
async def get_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await _fetch_person_scoped(conn, person_id, role_norm, emp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Person not found.")
    return _serialize_person(row)


# ------------------------------------------------------------------------- #
# EDIT PERSON FIELDS
# ------------------------------------------------------------------------- #
@router.post("/{person_id}/edit", summary="Edit a person's fields")
async def edit_person(
    person_id: int,
    payload: PersonWithDocumentsEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                old_row = await _fetch_person_scoped(conn, person_id, role_norm, emp_id, for_update=True, active_only=True)
                if not old_row:
                    raise HTTPException(status_code=404, detail="Person not found or inactive.")

                if all(k in old_row and old_row[k] == v for k, v in update_data.items()):
                    raise HTTPException(status_code=400, detail="No changes detected to update.")

                # Promoting this person to primary demotes any current primary.
                if update_data.get("is_primary") is True:
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.person_document_details
                        SET is_primary = FALSE, updated_at = NOW()
                        WHERE gst_registration_id = $1 AND is_primary = TRUE
                          AND is_active = TRUE AND person_id <> $2
                        """,
                        old_row["gst_registration_id"], person_id,
                    )

                fields, values, idx = [], [], 1
                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}"); values.append(v); idx += 1
                fields.append("updated_at = NOW()")
                values.append(person_id)
                new_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.person_document_details
                    SET {', '.join(fields)}
                    WHERE person_id = ${idx}
                    RETURNING *
                    """,
                    *values,
                )
                if not new_row:
                    raise HTTPException(status_code=409, detail="Person state changed. Please retry.")

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id, ENTITY_TYPE, person_id, old_row["customer_id"], "UPDATE",
                    json.dumps(_serialize_person(old_row), default=str),
                    json.dumps(_serialize_person(new_row), default=str),
                )

            await _invalidate_cache()
            return {**_serialize_person(new_row), "message": "Person updated successfully.",
                    "request_id": request_id}

        except asyncpg.exceptions.UniqueViolationError as e:
            raise HTTPException(status_code=409, detail=_UNIQUE_MAP.get(
                getattr(e, "constraint_name", None), "Duplicate value violates a uniqueness rule."))
        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(status_code=400, detail=_CHECK_MAP.get(
                getattr(e, "constraint_name", None), "Data violates a validation rule."))
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error during person edit")
            raise HTTPException(status_code=500, detail="Database error occurred.")
        except Exception:
            log.exception("Unexpected error during person edit")
            raise HTTPException(status_code=500, detail="Internal server error.")


# ------------------------------------------------------------------------- #
# UPSERT A DOCUMENT (add or replace by document_type)
# ------------------------------------------------------------------------- #
@router.post("/{person_id}/documents", summary="Add or replace one document on a person")
async def upsert_document(
    person_id: int,
    payload: DocumentUpsertIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    dtype = str(payload.document_type).strip().upper()
    new_doc = json.dumps([{"document_type": dtype, "document_url": str(payload.document_url).strip()}])

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                old_row = await _fetch_person_scoped(conn, person_id, role_norm, emp_id, for_update=True, active_only=True)
                if not old_row:
                    raise HTTPException(status_code=404, detail="Person not found or inactive.")

                # Drop any existing document of this type, then append the new one.
                new_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.person_document_details
                    SET documents = COALESCE(
                            (SELECT jsonb_agg(d) FROM jsonb_array_elements(documents) d
                             WHERE d->>'document_type' <> $2),
                            '[]'::jsonb
                        ) || $3::jsonb,
                        updated_at = NOW()
                    WHERE person_id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    person_id, dtype, new_doc,
                )
                if not new_row:
                    raise HTTPException(status_code=409, detail="Person state changed. Please retry.")

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id, ENTITY_TYPE, person_id, old_row["customer_id"], "UPDATE",
                    json.dumps(_serialize_person(old_row), default=str),
                    json.dumps(_serialize_person(new_row), default=str),
                )

            await _invalidate_cache()
            return {**_serialize_person(new_row), "message": "Document saved.", "request_id": request_id}
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error during document upsert")
            raise HTTPException(status_code=500, detail="Database error occurred.")


# ------------------------------------------------------------------------- #
# REMOVE A DOCUMENT (by document_type)
# ------------------------------------------------------------------------- #
@router.delete("/{person_id}/documents/{document_type}", summary="Remove one document from a person")
async def remove_document(
    person_id: int,
    document_type: str,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})
    dtype = document_type.strip().upper()

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                old_row = await _fetch_person_scoped(conn, person_id, role_norm, emp_id, for_update=True, active_only=True)
                if not old_row:
                    raise HTTPException(status_code=404, detail="Person not found or inactive.")
                if not any(d.get("document_type") == dtype for d in _parse_documents(old_row["documents"])):
                    raise HTTPException(status_code=404, detail="Document type not found on this person.")

                new_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.person_document_details
                    SET documents = COALESCE(
                            (SELECT jsonb_agg(d) FROM jsonb_array_elements(documents) d
                             WHERE d->>'document_type' <> $2),
                            '[]'::jsonb
                        ),
                        updated_at = NOW()
                    WHERE person_id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    person_id, dtype,
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id, ENTITY_TYPE, person_id, old_row["customer_id"], "UPDATE",
                    json.dumps(_serialize_person(old_row), default=str),
                    json.dumps(_serialize_person(new_row), default=str),
                )

            await _invalidate_cache()
            return {**_serialize_person(new_row), "message": "Document removed.", "request_id": request_id}
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error during document removal")
            raise HTTPException(status_code=500, detail="Database error occurred.")


# ------------------------------------------------------------------------- #
# SOFT DELETE / ACTIVATE PERSON
# ------------------------------------------------------------------------- #
@router.delete("/{person_id}/soft_delete", summary="Soft delete a person")
async def soft_delete_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await _fetch_person_scoped(conn, person_id, role_norm, emp_id, for_update=True)
                if not row:
                    raise HTTPException(status_code=404, detail="Person not found.")
                if row["is_active"] is False:
                    raise HTTPException(status_code=400, detail="Person is already inactive.")

                # Don't orphan the registration: block deleting the primary while
                # other active members remain.
                if row["is_primary"]:
                    others = await conn.fetchval(
                        f"""
                        SELECT COUNT(*) FROM {DB_SCHEMA}.person_document_details
                        WHERE gst_registration_id = $1 AND is_active = TRUE AND person_id <> $2
                        """,
                        row["gst_registration_id"], person_id,
                    )
                    if others > 0:
                        raise HTTPException(
                            status_code=400,
                            detail="Cannot delete the primary member while other active members exist. "
                                   "Assign another primary first.",
                        )

                deleted = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.person_document_details
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE person_id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    person_id,
                )
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id, ENTITY_TYPE, person_id, row["customer_id"], "DELETE", None, None,
                )

            await _invalidate_cache()
            return {**_serialize_person(deleted), "message": "Person soft deleted.", "request_id": request_id}
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error during person soft delete")
            raise HTTPException(status_code=500, detail="Database error occurred.")


@router.post("/{person_id}/activate", summary="Reactivate a person")
async def activate_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await _fetch_person_scoped(conn, person_id, role_norm, emp_id, for_update=True)
                if not row:
                    raise HTTPException(status_code=404, detail="Person not found.")
                if row["is_active"]:
                    raise HTTPException(status_code=400, detail="Person already active.")

                activated = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.person_document_details
                    SET is_active = TRUE, updated_at = NOW()
                    WHERE person_id = $1 AND is_active = FALSE
                    RETURNING *
                    """,
                    person_id,
                )
                if not activated:
                    raise HTTPException(status_code=409, detail="Person state changed. Please retry.")

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id, ENTITY_TYPE, person_id, row["customer_id"], "ACTIVATE", None, None,
                )

            await _invalidate_cache()
            return {**_serialize_person(activated), "message": "Person activated.", "request_id": request_id}
        except asyncpg.exceptions.UniqueViolationError as e:
            raise HTTPException(status_code=409, detail=_UNIQUE_MAP.get(
                getattr(e, "constraint_name", None), "Reactivation conflicts with an existing member."))
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error during person activation")
            raise HTTPException(status_code=500, detail="Database error occurred.")


# ------------------------------------------------------------------------- #
# REQUIRED DOCUMENTS (by ownership category, minus what's uploaded)
# ------------------------------------------------------------------------- #
@router.get("/{person_id}/required-documents", summary="Document types still missing for a person")
async def required_documents(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    cache_key = build_cache_key("person_document_details:required_documents", person_id=person_id, emp_id=emp_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load():
        async with pool.acquire() as conn:
            person = await _fetch_person_scoped(conn, person_id, role_norm, emp_id, active_only=True)
            if not person:
                raise HTTPException(status_code=404, detail="Person not found or inactive.")

            rows = await conn.fetch(
                f"""
                SELECT dc.value, dc.display_name, dc.description, dc.is_mandatory
                FROM {DB_SCHEMA}.person_document_details pdd
                JOIN {DB_SCHEMA}.gst_registration g ON g.id = pdd.gst_registration_id
                JOIN {DB_SCHEMA}.document_config dc
                    ON dc.ownership_category = g.ownership_category
                    AND dc.registration = 'GST_REGISTRATION'
                    AND dc.is_active = TRUE
                WHERE pdd.person_id = $1 AND pdd.is_active = TRUE
                AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(pdd.documents) d
                    WHERE d->>'document_type' = dc.value
                )
                ORDER BY dc.sort_order
                """,
                person_id,
            )
            return {
                "person_id": person_id,
                "documents": [dict(r) for r in rows],
                "request_id": request_id,
            }

    return await redis_get_or_set_json(cache_key, loader=_load, ttl_seconds=300, tags=[_REQUIRED_TAG])


# ------------------------------------------------------------------------- #
# DOWNLOAD A DOCUMENT (named by its document type)
# ------------------------------------------------------------------------- #
@router.get("/{person_id}/documents/{document_type}/download",
            summary="Secure download URL for a document, named by its document type")
async def download_document(
    person_id: int,
    document_type: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = _emp_id(current_user)
    role_norm = str(current_user.get("role")).strip().upper() if current_user.get("role") else None
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})
    dtype = document_type.strip().upper()

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # IDOR guard: the person (and thus the document) must be visible to the caller.
        person = await _fetch_person_scoped(conn, person_id, role_norm, emp_id)
        if not person:
            raise HTTPException(status_code=404, detail="Document not found.")

        doc = next((d for d in _parse_documents(person["documents"]) if d.get("document_type") == dtype), None)
        if not doc or not doc.get("document_url"):
            raise HTTPException(status_code=404, detail="Document not found.")

        # Prefer the friendly display name for the download filename.
        display_name = await conn.fetchval(
            f"""
            SELECT display_name FROM {DB_SCHEMA}.document_config
            WHERE registration = 'GST_REGISTRATION'
              AND ownership_category = $1 AND value = $2 AND is_active = TRUE
            LIMIT 1
            """,
            person["ownership_category"], dtype,
        )

    download_name = (display_name or dtype.replace("_", " ").title())
    try:
        blob_path = extract_blob_path(doc["document_url"])
        sas_url = generate_blob_sas_url(blob_path, disposition="attachment", download_filename=download_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document URL.")
    except Exception:
        log.exception("Failed generating download URL")
        raise HTTPException(status_code=500, detail="Unable to generate document download link.")

    return {"download_url": sas_url, "document_type": dtype, "request_id": request_id}
