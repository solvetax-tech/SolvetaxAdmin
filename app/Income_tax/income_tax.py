import logging
import json
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.Income_tax.schemas import IncomeTaxIn, IncomeTaxEditIn
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.security.public_security import enforce_public_security
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, build_income_tax_visibility, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/income-tax", tags=["Income Tax"])
CRM_LEAD_ENTITY_TYPE_INCOME_TAX = "INCOME_TAX"


def _income_tax_filter_tag() -> str:
    return "income_tax:filter:index"


def _income_tax_detail_tag(income_tax_id: int) -> str:
    return f"income_tax:detail:index:{income_tax_id}"


def _income_tax_full_tag(income_tax_id: int) -> str:
    return f"income_tax:full:index:{income_tax_id}"


async def _invalidate_income_tax_cache(income_tax_id: Optional[int] = None) -> None:
    await redis_invalidate_tag(_income_tax_filter_tag())
    if income_tax_id is not None:
        await redis_invalidate_tag(_income_tax_detail_tag(income_tax_id))
        await redis_invalidate_tag(_income_tax_full_tag(income_tax_id))


def _raise_income_tax_validation_error(fields: dict, status_code: int = 400, message: str = "Validation failed") -> None:
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


async def _upsert_income_tax_lead_by_mobile_entity_type(
    conn: asyncpg.Connection,
    income_tax_row: asyncpg.Record,
):
    """
    For INCOME_TAX leads, match by entity_type + mobile.
    If found, update entity_id; else insert new lead.
    """
    try:
        mobile = income_tax_row.get("mobile")
        if not mobile:
            return

        existing_lead_id = await conn.fetchval(
            f"""
            SELECT id
            FROM {DB_SCHEMA}.crm_leads
            WHERE entity_type = $1
              AND mobile = $2
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            CRM_LEAD_ENTITY_TYPE_INCOME_TAX,
            mobile,
        )
        if existing_lead_id:
            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.crm_leads
                SET entity_id = $1,
                    updated_at = NOW()
                WHERE id = $2
                """,
                income_tax_row["id"],
                existing_lead_id,
            )
            return

        await conn.fetchval(
            f"""
            INSERT INTO {DB_SCHEMA}.crm_leads (
                mobile, entity_id, entity_type, stage, rm_id, op_id, is_active, remarks, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
            RETURNING id
            """,
            mobile,
            income_tax_row["id"],
            CRM_LEAD_ENTITY_TYPE_INCOME_TAX,
            "FRESH_LEAD",
            income_tax_row.get("rm_id"),
            income_tax_row.get("op_id"),
            income_tax_row.get("is_active"),
            "Auto synced from income tax create.",
        )
    except asyncpg.UndefinedTableError:
        logger.warning("CRM tables not found; skipping income tax CRM sync.")
    except asyncpg.PostgresError:
        logger.exception("Income tax CRM sync failed; continuing income tax flow.")


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create income tax record")
async def create_income_tax(
    request: Request,
    payload: IncomeTaxIn,
):
    await enforce_public_security(
        request=request,
        bucket="public:create_income_tax",
        max_requests=15,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    emp_id = None
    role_norm = ""
    rm_id = payload.rm_id
    if role_norm == "RM" and rm_id is None:
        rm_id = emp_id
    op_id = emp_id if role_norm == "OP" else payload.op_id
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id, "api": "create_income_tax"})

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT EXISTS(
                        SELECT 1
                        FROM {DB_SCHEMA}.income_tax
                        WHERE is_active = TRUE
                          AND $1::text IS NOT NULL
                          AND upper(trim(pan_number)) = upper(trim($1::text))
                          AND trim(financial_year) = trim($2::text)
                    ) AS pan_fy_match,
                    EXISTS(
                        SELECT 1
                        FROM {DB_SCHEMA}.income_tax
                        WHERE is_active = TRUE
                          AND $1::text IS NULL
                          AND pan_number IS NULL
                          AND trim(mobile) = trim($3::text)
                          AND trim(financial_year) = trim($2::text)
                    ) AS mobile_fy_no_pan_match
                    """,
                    payload.pan_number,
                    payload.financial_year,
                    payload.mobile,
                )
                if duplicate_row and duplicate_row["pan_fy_match"]:
                    _raise_income_tax_validation_error(
                        {
                            "pan_number": "A record already exists for this PAN and financial year.",
                            "financial_year": "A record already exists for this PAN and financial year.",
                        },
                        status_code=409,
                        message="Income tax request already exists for this financial year.",
                    )
                if duplicate_row and duplicate_row["mobile_fy_no_pan_match"]:
                    _raise_income_tax_validation_error(
                        {
                            "mobile": "A record already exists for this mobile and financial year (without PAN).",
                            "financial_year": "A record already exists for this mobile and financial year (without PAN).",
                        },
                        status_code=409,
                        message="Income tax request already exists for this financial year.",
                    )

                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.income_tax (
                        client_name, mobile, language, state, priority, remarks,
                        pan_number, password, financial_year, filed_status,
                        referral_id, referral_entity, email_id, source_of_income, refund_amount,
                        rm_id, op_id, is_active, created_at, updated_at
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,TRUE,NOW(),NOW()
                    )
                    RETURNING *
                    """,
                    payload.client_name,
                    payload.mobile,
                    payload.language,
                    payload.state,
                    payload.priority,
                    payload.remarks,
                    payload.pan_number,
                    payload.password,
                    payload.financial_year,
                    payload.filed_status,
                    payload.referral_id,
                    payload.referral_entity,
                    payload.email_id,
                    payload.source_of_income,
                    payload.refund_amount,
                    rm_id,
                    op_id,
                )
                if not row:
                    raise HTTPException(status_code=500, detail="Income tax record creation failed.")

                await _upsert_income_tax_lead_by_mobile_entity_type(conn, row)

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX",
                    row["id"],
                    None,
                    "CREATE",
                    json.dumps(dict(row), default=str),
                    None,
                )
            await _invalidate_income_tax_cache(row["id"])
            return {"message": "Income tax record created successfully.", "request_id": request_id, "data": dict(row)}
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")
            unique_map = {
                "uq_income_tax_pan_financial_year_active": (
                    "pan_number",
                    "A record already exists for this PAN and financial year.",
                ),
                "income_tax_pan_number_financial_year_key": (
                    "pan_number",
                    "A record already exists for this PAN and financial year.",
                ),
                "uq_income_tax_mobile_fy_no_pan": (
                    "mobile",
                    "A record already exists for this mobile and financial year (without PAN).",
                ),
            }
            field, message = unique_map.get(
                constraint,
                ("non_field_error", "Duplicate value violates unique constraint."),
            )
            _raise_income_tax_validation_error(
                {field: message},
                status_code=409,
                message="Income tax request already exists for this financial year.",
            )
        except asyncpg.exceptions.ForeignKeyViolationError:
            _raise_income_tax_validation_error(
                {"non_field_error": "Invalid rm_id or op_id reference."},
                status_code=400,
            )
        except asyncpg.PostgresError:
            log.exception("Database error while creating income tax")
            raise HTTPException(status_code=500, detail="Database error.")


@router.get("/filter", summary="Filter income tax records")
async def filter_income_tax(
    id: Optional[int] = None,
    mobile: Optional[str] = None,
    pan_number: Optional[str] = None,
    financial_year: Optional[str] = None,
    filed_status: Optional[str] = None,
    priority: Optional[str] = None,
    language: Optional[str] = None,
    state: Optional[str] = None,
    source_of_income: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
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
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id, "api": "filter_income_tax"})
    cache_key = build_cache_key(
        "income_tax_filter",
        id=id,
        mobile=mobile.strip() if mobile else None,
        pan_number=pan_number.strip().upper() if pan_number else None,
        financial_year=financial_year.strip() if financial_year else None,
        filed_status=filed_status.strip().upper() if filed_status else None,
        priority=priority.strip().upper() if priority else None,
        language=language.strip().upper() if language else None,
        state=state.strip().upper() if state else None,
        source_of_income=source_of_income.strip().upper() if source_of_income else None,
        rm_id=rm_id,
        op_id=op_id,
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
        add_eq("i.id", id)
    if mobile:
        add_eq("trim(i.mobile)", mobile.strip())
    if pan_number:
        add_eq("upper(trim(i.pan_number))", pan_number.strip().upper())
    if financial_year:
        add_eq("i.financial_year", financial_year.strip())
    if filed_status:
        add_eq("i.filed_status", filed_status.strip().upper())
    if priority:
        add_eq("i.priority", priority.strip().upper())
    if language:
        add_eq("i.language", language.strip().upper())
    if state:
        add_eq("i.state", state.strip().upper())
    if source_of_income:
        add_eq("i.source_of_income", source_of_income.strip().upper())
    if rm_id is not None:
        add_eq("i.rm_id", rm_id)
    if op_id is not None:
        add_eq("i.op_id", op_id)
    if is_active is not None:
        add_eq("i.is_active", is_active)
    elif not include_inactive:
        conditions.append("i.is_active = TRUE")

    visibility_sql, visibility_values, idx = build_income_tax_visibility(role_norm, emp_id, idx, DB_SCHEMA)
    if visibility_sql:
        conditions.append(f"({visibility_sql})")
        values.extend(visibility_values)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    f"SELECT COUNT(*)::bigint FROM {DB_SCHEMA}.income_tax i {where_sql}",
                    *values,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT i.*
                    FROM {DB_SCHEMA}.income_tax i
                    {where_sql}
                    ORDER BY i.updated_at DESC, i.id DESC
                    LIMIT ${idx} OFFSET ${idx + 1}
                    """,
                    *values,
                    limit,
                    offset,
                )
            return {"items": [dict(r) for r in rows], "total": int(total or 0), "limit": limit, "offset": offset, "request_id": request_id}
        except asyncpg.PostgresError:
            log.exception("Database error while filtering income tax")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_income_tax_filter_tag()],
    )


@router.get("/{income_tax_id}", summary="Get income tax record by id")
async def get_income_tax(
    income_tax_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    cache_key = build_cache_key(
        "income_tax_detail",
        income_tax_id=income_tax_id,
        role=role_norm,
        emp_id=emp_id,
    )

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                visibility_sql, visibility_values, _next = build_income_tax_visibility(
                    role_norm,
                    emp_id,
                    2,
                    DB_SCHEMA,
                )
                conditions = ["i.id = $1"]
                args = [income_tax_id]
                if visibility_sql:
                    conditions.append(f"({visibility_sql})")
                    args.extend(visibility_values)
                row = await conn.fetchrow(
                    f"SELECT i.* FROM {DB_SCHEMA}.income_tax i WHERE {' AND '.join(conditions)}",
                    *args,
                )
            if not row:
                raise HTTPException(status_code=404, detail="Income tax record not found.")
            return dict(row)
        except asyncpg.PostgresError:
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_income_tax_detail_tag(income_tax_id)],
    )


@router.get("/{income_tax_id}/full", summary="Get full income tax details")
async def get_income_tax_full(
    income_tax_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    cache_key = build_cache_key(
        "income_tax_full_detail",
        income_tax_id=income_tax_id,
        role=role_norm,
        emp_id=emp_id,
    )

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                visibility_sql, visibility_values, _next = build_income_tax_visibility(
                    role_norm,
                    emp_id,
                    2,
                    DB_SCHEMA,
                )
                conditions = ["i.id = $1"]
                args = [income_tax_id]
                if visibility_sql:
                    conditions.append(f"({visibility_sql})")
                    args.extend(visibility_values)

                income_tax_row = await conn.fetchrow(
                    f"""
                    SELECT i.*
                    FROM {DB_SCHEMA}.income_tax i
                    WHERE {' AND '.join(conditions)}
                    """,
                    *args,
                )
                if not income_tax_row:
                    raise HTTPException(status_code=404, detail="Income tax record not found.")

                documents = await conn.fetch(
                    f"""
                    SELECT d.*
                    FROM {DB_SCHEMA}.income_tax_documents d
                    WHERE d.income_tax_id = $1
                    ORDER BY d.updated_at DESC, d.id DESC
                    """,
                    income_tax_id,
                )

            return {
                "income_tax": dict(income_tax_row),
                "documents": [dict(r) for r in documents],
            }
        except asyncpg.PostgresError:
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_income_tax_full_tag(income_tax_id)],
    )


@router.post("/{income_tax_id}/edit", summary="Edit income tax record")
async def edit_income_tax(
    income_tax_id: int,
    payload: IncomeTaxEditIn,
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
                old = await conn.fetchrow(
                    f"SELECT * FROM {DB_SCHEMA}.income_tax WHERE id = $1 FOR UPDATE",
                    income_tax_id,
                )
                if not old:
                    raise HTTPException(status_code=404, detail="Income tax record not found.")

                pan_value = update_data.get("pan_number", old["pan_number"])
                fy_value = update_data.get("financial_year", old["financial_year"])
                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT EXISTS(
                        SELECT 1
                        FROM {DB_SCHEMA}.income_tax
                        WHERE id <> $1
                          AND is_active = TRUE
                          AND upper(trim(pan_number)) = upper(trim($2::text))
                          AND trim(financial_year) = trim($3::text)
                    ) AS pan_fy_match
                    """,
                    income_tax_id,
                    pan_value,
                    fy_value,
                )
                if duplicate_row and duplicate_row["pan_fy_match"]:
                    _raise_income_tax_validation_error(
                        {
                            "pan_number": "PAN + financial year already exists for an active record.",
                            "financial_year": "PAN + financial year already exists for an active record.",
                        },
                        status_code=409,
                    )

                fields = []
                values = []
                idx = 1
                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1
                fields.append("updated_at = NOW()")
                values.append(income_tax_id)

                new = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.income_tax
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
                    "INCOME_TAX",
                    income_tax_id,
                    None,
                    "UPDATE",
                    json.dumps(dict(old), default=str),
                    json.dumps(dict(new), default=str),
                )
        await _invalidate_income_tax_cache(income_tax_id)
        return {"message": "Income tax record updated successfully.", "request_id": request_id, "data": dict(new)}
    except asyncpg.exceptions.UniqueViolationError as e:
        constraint = getattr(e, "constraint_name", "")
        unique_map = {
            "uq_income_tax_pan_financial_year_active": (
                "pan_number",
                "Duplicate PAN + financial year for active record.",
            ),
            "income_tax_pan_number_financial_year_key": (
                "pan_number",
                "Duplicate PAN + financial year for active record.",
            ),
        }
        field, message = unique_map.get(
            constraint,
            ("non_field_error", "Duplicate value violates unique constraint."),
        )
        _raise_income_tax_validation_error({field: message}, status_code=409)
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.delete("/{income_tax_id}/soft_delete", summary="Soft delete income tax record")
async def soft_delete_income_tax(
    income_tax_id: int,
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
                    UPDATE {DB_SCHEMA}.income_tax
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    income_tax_id,
                )
                if row:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        emp_id,
                        "INCOME_TAX",
                        row["id"],
                        None,
                        "DELETE",
                        None,
                        None,
                    )
        if not row:
            raise HTTPException(status_code=404, detail="Income tax record not found or already inactive.")
        await _invalidate_income_tax_cache(income_tax_id)
        return {"message": "Income tax record deactivated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{income_tax_id}/activate", summary="Activate income tax record")
async def activate_income_tax(
    income_tax_id: int,
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
                    UPDATE {DB_SCHEMA}.income_tax
                    SET is_active = TRUE, updated_at = NOW()
                    WHERE id = $1 AND is_active = FALSE
                    RETURNING *
                    """,
                    income_tax_id,
                )
                if row:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.versions
                        (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        emp_id,
                        "INCOME_TAX",
                        row["id"],
                        None,
                        "ACTIVATE",
                        None,
                        None,
                    )
        if not row:
            raise HTTPException(status_code=404, detail="Income tax record not found or already active.")
        await _invalidate_income_tax_cache(income_tax_id)
        return {"message": "Income tax record activated successfully.", "request_id": request_id, "data": dict(row)}
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")
