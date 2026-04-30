import json
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.contact_support.schemas import ContactSupportEditIn, ContactSupportIn
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.security.public_security import enforce_public_security
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/contact-support", tags=["Contact Support"])


def _contact_support_filter_tag() -> str:
    return "contact_support:filter:index"


def _contact_support_detail_tag(contact_id: int) -> str:
    return f"contact_support:detail:index:{contact_id}"


async def _invalidate_contact_support_cache(contact_id: Optional[int] = None) -> None:
    await redis_invalidate_tag(_contact_support_filter_tag())
    if contact_id is not None:
        await redis_invalidate_tag(_contact_support_detail_tag(contact_id))


def _raise_contact_support_validation_error(fields: dict, status_code: int = 400, message: str = "Validation failed") -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "type": "validation_error",
                "message": message,
                "fields": fields,
            }
        },
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create contact support request")
async def create_contact_support(
    request: Request,
    payload: ContactSupportIn,
):
    await enforce_public_security(
        request=request,
        bucket="public:create_contact_support",
        max_requests=20,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            duplicate_row = await conn.fetchrow(
                f"""
                SELECT EXISTS(
                    SELECT 1
                    FROM {DB_SCHEMA}.contact_support
                    WHERE is_active = TRUE
                      AND trim(phone_number) = trim($1::text)
                      AND COALESCE(trim(referal_phone_number), '') = COALESCE(trim($2::text), '')
                      AND upper(COALESCE(trim(service_required), '')) = upper(COALESCE(trim($3::text), ''))
                ) AS combo_match
                """,
                payload.phone_number,
                payload.referal_phone_number,
                payload.service_required,
            )
            if duplicate_row and duplicate_row["combo_match"]:
                _raise_contact_support_validation_error(
                    {
                        "phone_number": "A request with this phone number, referral phone number and service already exists.",
                        "referal_phone_number": "A request with this phone number, referral phone number and service already exists.",
                        "service_required": "A request with this phone number, referral phone number and service already exists.",
                    },
                    status_code=409,
                    message="Contact support request already exists for this phone/service combination.",
                )
            row = await conn.fetchrow(
                f"""
                INSERT INTO {DB_SCHEMA}.contact_support
                (
                    your_name,
                    phone_number,
                    email_address,
                    service_required,
                    referal_phone_number,
                    your_message,
                    created_at,
                    updated_at
                )
                VALUES ($1,$2,$3,$4,$5,$6,NOW(),NOW())
                RETURNING *
                """,
                payload.your_name,
                payload.phone_number,
                payload.email_address,
                payload.service_required,
                payload.referal_phone_number,
                payload.your_message,
            )
        await _invalidate_contact_support_cache()
        return {"message": "Contact support request created successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.exceptions.UniqueViolationError:
        _raise_contact_support_validation_error(
            {
                "phone_number": "A request with this phone number, referral phone number and service already exists.",
                "referal_phone_number": "A request with this phone number, referral phone number and service already exists.",
                "service_required": "A request with this phone number, referral phone number and service already exists.",
            },
            status_code=409,
            message="Contact support request already exists for this phone/service combination.",
        )
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.get("/filter", summary="Filter contact support requests")
async def filter_contact_support(
    id: Optional[int] = None,
    phone_number: Optional[str] = None,
    email_address: Optional[str] = None,
    service_required: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    referal_phone_number: Optional[str] = None,
    is_service_provided: Optional[bool] = None,
    is_resolved: Optional[bool] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""
    phone_number = phone_number.strip() if phone_number else None
    email_address = email_address.strip().lower() if email_address else None
    service_required = service_required.strip().upper() if service_required else None
    referal_phone_number = referal_phone_number.strip() if referal_phone_number else None

    cache_key = build_cache_key(
        "contact_support_filter",
        id=id,
        phone_number=phone_number,
        email_address=email_address,
        service_required=service_required,
        rm_id=rm_id,
        op_id=op_id,
        referal_phone_number=referal_phone_number,
        is_service_provided=is_service_provided,
        is_resolved=is_resolved,
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
        add_eq("c.id", id)
    if phone_number:
        add_eq("trim(c.phone_number)", phone_number)
    if email_address:
        add_eq("lower(trim(c.email_address))", email_address)
    if service_required:
        add_eq("upper(trim(c.service_required))", service_required)
    if rm_id is not None:
        add_eq("c.rm_id", rm_id)
    if op_id is not None:
        add_eq("c.op_id", op_id)
    if referal_phone_number:
        add_eq("trim(c.referal_phone_number)", referal_phone_number)
    if is_service_provided is not None:
        add_eq("c.is_service_provided", is_service_provided)
    if is_resolved is not None:
        add_eq("c.is_resolved", is_resolved)
    if is_active is not None:
        add_eq("c.is_active", is_active)
    elif not include_inactive:
        conditions.append("c.is_active = TRUE")

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    f"SELECT COUNT(*)::bigint FROM {DB_SCHEMA}.contact_support c {where_sql}",
                    *values,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT c.*
                    FROM {DB_SCHEMA}.contact_support c
                    {where_sql}
                    ORDER BY c.updated_at DESC, c.id DESC
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
        tags=[_contact_support_filter_tag()],
    )


@router.get("/{contact_id}", summary="Get contact support request by id")
async def get_contact_support(
    contact_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    emp_id = current_user.get("emp_id") or current_user.get("sub")
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    cache_key = build_cache_key(
        "contact_support_detail",
        contact_id=contact_id,
        role=role_norm,
        emp_id=emp_id,
    )

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {DB_SCHEMA}.contact_support WHERE id = $1",
                    contact_id,
                )
            if not row:
                raise HTTPException(status_code=404, detail="Contact support request not found.")
            return dict(row)
        except asyncpg.PostgresError:
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_contact_support_detail_tag(contact_id)],
    )


@router.post("/{contact_id}/edit", summary="Edit contact support request")
async def edit_contact_support(
    contact_id: int,
    payload: ContactSupportEditIn,
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
                    f"SELECT * FROM {DB_SCHEMA}.contact_support WHERE id = $1 FOR UPDATE",
                    contact_id,
                )
                if not existing:
                    raise HTTPException(status_code=404, detail="Contact support request not found.")

                phone_value = update_data.get("phone_number", existing["phone_number"])
                referal_phone_value = update_data.get("referal_phone_number", existing["referal_phone_number"])
                service_value = update_data.get("service_required", existing["service_required"])
                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT EXISTS(
                        SELECT 1
                        FROM {DB_SCHEMA}.contact_support
                        WHERE id <> $1
                          AND is_active = TRUE
                          AND trim(phone_number) = trim($2::text)
                          AND COALESCE(trim(referal_phone_number), '') = COALESCE(trim($3::text), '')
                          AND upper(COALESCE(trim(service_required), '')) = upper(COALESCE(trim($4::text), ''))
                    ) AS combo_match
                    """,
                    contact_id,
                    phone_value,
                    referal_phone_value,
                    service_value,
                )
                if duplicate_row and duplicate_row["combo_match"]:
                    _raise_contact_support_validation_error(
                        {
                            "phone_number": "A request with this phone number, referral phone number and service already exists.",
                            "referal_phone_number": "A request with this phone number, referral phone number and service already exists.",
                            "service_required": "A request with this phone number, referral phone number and service already exists.",
                        },
                        status_code=409,
                        message="Contact support request already exists for this phone/service combination.",
                    )

                fields = []
                values = []
                idx = 1
                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1
                fields.append("updated_at = NOW()")
                values.append(contact_id)
                row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.contact_support
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
                    "CONTACT_SUPPORT",
                    contact_id,
                    None,
                    "UPDATE",
                    json.dumps(dict(existing), default=str),
                    json.dumps(dict(row), default=str),
                )
        await _invalidate_contact_support_cache(contact_id)
        return {"message": "Contact support request updated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.exceptions.UniqueViolationError:
        _raise_contact_support_validation_error(
            {
                "phone_number": "A request with this phone number, referral phone number and service already exists.",
                "referal_phone_number": "A request with this phone number, referral phone number and service already exists.",
                "service_required": "A request with this phone number, referral phone number and service already exists.",
            },
            status_code=409,
            message="Contact support request already exists for this phone/service combination.",
        )
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.delete("/{contact_id}/soft_delete", summary="Deactivate contact support request")
async def soft_delete_contact_support(
    contact_id: int,
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
                    UPDATE {DB_SCHEMA}.contact_support
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    contact_id,
                )
                if row:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        emp_id,
                        "CONTACT_SUPPORT",
                        row["id"],
                        None,
                        "DELETE",
                        None,
                        None,
                    )
        if not row:
            raise HTTPException(status_code=404, detail="Contact support request not found or already inactive.")
        await _invalidate_contact_support_cache(contact_id)
        return {"message": "Contact support request deactivated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{contact_id}/activate", summary="Activate contact support request")
async def activate_contact_support(
    contact_id: int,
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
                    UPDATE {DB_SCHEMA}.contact_support
                    SET is_active = TRUE, updated_at = NOW()
                    WHERE id = $1 AND is_active = FALSE
                    RETURNING *
                    """,
                    contact_id,
                )
                if row:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        emp_id,
                        "CONTACT_SUPPORT",
                        row["id"],
                        None,
                        "ACTIVATE",
                        None,
                        None,
                    )
        if not row:
            raise HTTPException(status_code=404, detail="Contact support request not found or already active.")
        await _invalidate_contact_support_cache(contact_id)
        return {"message": "Contact support request activated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")
