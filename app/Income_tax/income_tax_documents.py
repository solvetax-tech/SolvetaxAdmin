import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional
import json

from app.Income_tax.schemas import IncomeTaxDocumentIn, IncomeTaxDocumentEditIn
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, build_income_tax_visibility, get_db_pool, generate_uuid

router = APIRouter(prefix="/api/v1/income-tax-documents", tags=["Income Tax Documents"])


def _income_tax_documents_filter_tag() -> str:
    return "income_tax_documents:filter:index"


async def _invalidate_income_tax_document_cache() -> None:
    await redis_invalidate_tag(_income_tax_documents_filter_tag())


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create income tax document")
async def create_income_tax_document(
    payload: IncomeTaxDocumentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                parent = await conn.fetchval(
                    f"SELECT 1 FROM {DB_SCHEMA}.income_tax WHERE id = $1 AND is_active = TRUE",
                    payload.income_tax_id,
                )
                if not parent:
                    raise HTTPException(status_code=400, detail="Invalid income_tax_id.")
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.income_tax_documents
                    (income_tax_id, document_type, document_url, remarks, verified, is_active, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,TRUE,NOW(),NOW())
                    RETURNING *
                    """,
                    payload.income_tax_id,
                    payload.document_type,
                    payload.document_url,
                    payload.remarks,
                    payload.verified,
                )
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX_DOCUMENT",
                    row["id"],
                    None,
                    "CREATE",
                    json.dumps(dict(row), default=str),
                    None,
                )
            await _invalidate_income_tax_document_cache()
            return {"message": "Income tax document created successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.get("/filter", summary="Filter income tax documents")
async def filter_income_tax_documents(
    id: Optional[int] = None,
    income_tax_id: Optional[int] = None,
    document_type: Optional[str] = None,
    verified: Optional[bool] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""
    cache_key = build_cache_key(
        "income_tax_documents_filter",
        id=id,
        income_tax_id=income_tax_id,
        document_type=document_type.strip().upper() if document_type else None,
        verified=verified,
        is_active=is_active,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
        role=role_norm,
        emp_id=emp_id,
    )

    conditions = []
    values = []
    idx = 1

    def add_eq(col, val):
        nonlocal idx
        conditions.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    if id is not None:
        add_eq("d.id", id)
    if income_tax_id is not None:
        add_eq("d.income_tax_id", income_tax_id)
    if document_type:
        add_eq("d.document_type", document_type.strip().upper())
    if verified is not None:
        add_eq("d.verified", verified)
    if is_active is not None:
        add_eq("d.is_active", is_active)
    elif not include_inactive:
        conditions.append("d.is_active = TRUE")

    visibility_sql, visibility_values, idx = build_income_tax_visibility(
        role_norm,
        emp_id,
        idx,
        DB_SCHEMA,
        alias="i",
    )
    if visibility_sql:
        conditions.append(f"({visibility_sql})")
        values.extend(visibility_values)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)::bigint
                    FROM {DB_SCHEMA}.income_tax_documents d
                    JOIN {DB_SCHEMA}.income_tax i ON i.id = d.income_tax_id
                    {where_sql}
                    """,
                    *values,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT d.*
                    FROM {DB_SCHEMA}.income_tax_documents d
                    JOIN {DB_SCHEMA}.income_tax i ON i.id = d.income_tax_id
                    {where_sql}
                    ORDER BY d.updated_at DESC, d.id DESC
                    LIMIT ${idx} OFFSET ${idx + 1}
                    """,
                    *values,
                    limit,
                    offset,
                )
            return {"items": [dict(r) for r in rows], "total": int(total or 0), "limit": limit, "offset": offset, "request_id": request_id}
        except asyncpg.PostgresError:
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_income_tax_documents_filter_tag()],
    )


@router.post("/{document_id}/edit", summary="Edit income tax document")
async def edit_income_tax_document(
    document_id: int,
    payload: IncomeTaxDocumentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    f"SELECT * FROM {DB_SCHEMA}.income_tax_documents WHERE id = $1 FOR UPDATE",
                    document_id,
                )
                if not existing:
                    raise HTTPException(status_code=404, detail="Income tax document not found.")

                fields = []
                values = []
                idx = 1
                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1
                fields.append("updated_at = NOW()")
                values.append(document_id)
                row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.income_tax_documents
                    SET {', '.join(fields)}
                    WHERE id = ${idx}
                    RETURNING *
                    """,
                    *values,
                )
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX_DOCUMENT",
                    document_id,
                    None,
                    "UPDATE",
                    json.dumps(dict(existing), default=str),
                    json.dumps(dict(row), default=str),
                )
        await _invalidate_income_tax_document_cache()
        return {"message": "Income tax document updated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.delete("/{document_id}/soft_delete", summary="Soft delete income tax document")
async def soft_delete_income_tax_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.income_tax_documents
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    document_id,
                )
                if row:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        emp_id,
                        "INCOME_TAX_DOCUMENT",
                        row["id"],
                        None,
                        "DELETE",
                        None,
                        None,
                    )
        if not row:
            raise HTTPException(status_code=404, detail="Income tax document not found or already inactive.")
        await _invalidate_income_tax_document_cache()
        return {"message": "Income tax document deactivated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{document_id}/activate", summary="Activate income tax document")
async def activate_income_tax_document(
    document_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.income_tax_documents
                    SET is_active = TRUE, updated_at = NOW()
                    WHERE id = $1 AND is_active = FALSE
                    RETURNING *
                    """,
                    document_id,
                )
                if row:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        emp_id,
                        "INCOME_TAX_DOCUMENT",
                        row["id"],
                        None,
                        "ACTIVATE",
                        None,
                        None,
                    )
        if not row:
            raise HTTPException(status_code=404, detail="Income tax document not found or already active.")
        await _invalidate_income_tax_document_cache()
        return {"message": "Income tax document activated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")
