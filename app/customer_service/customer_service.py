"""REST APIs for `customer_services` and legacy list/dashboard routes (see bottom). Follow-ups: `app/follow_ups/customer_service_followups.py`; service catalog: `service_config.py`."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.customer_service.bulk_lead_assignment import (
    _invalidate_customer_services_index_caches,
    svc_bulk_assign_candidates,
    svc_bulk_assign_execute,
)
from app.customer_service.schemas import (
    CustomerServiceBulkAssignCandidatesOut,
    CustomerServiceBulkAssignExecuteIn,
    CustomerServiceDetailOut,
    CustomerServiceListItemOut,
    CustomerServicePatchIn,
    CustomerServiceStatusPatchIn,
)
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.logger import logger
from app.security.rbac import require_admin, require_permission
from app.utils import (
    DB_SCHEMA,
    build_customer_service_visibility,
    generate_uuid,
    get_db_pool,
)

router = APIRouter(
    prefix="/api/v1/customer-service",
    tags=["Customer Service"],
)

IST = ZoneInfo("Asia/Kolkata")


def _customer_service_list_tag() -> str:
    return "customer_service:staff:list:index"


def _customer_service_detail_tag(service_id: int) -> str:
    return f"customer_service:staff:detail:{service_id}"


def _raise_validation(fields: dict, message: str = "Validation failed", code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={
            "error": {
                "type": "validation_error",
                "message": message,
                "fields": fields,
            }
        },
    )


def _ctx(user: dict):
    role = (user.get("role") or "").strip().upper()
    raw = user.get("emp_id") or user.get("sub")
    emp_id = int(raw) if str(raw).isdigit() else 0
    return role, emp_id


def _require_emp(role: str, emp_id: int) -> None:
    if role == "ADMIN":
        return
    if emp_id <= 0:
        raise HTTPException(status_code=403, detail="Employee context required.")


async def _assert_customer_service_row_visibility(
    conn: asyncpg.Connection,
    *,
    customer_service_id: int,
    role: str,
    emp_id: int,
) -> None:
    vis_sql, vis_vals, _ = build_customer_service_visibility(
        role, emp_id if emp_id > 0 else None, 2, DB_SCHEMA
    )
    if not vis_sql:
        return
    ok = await conn.fetchval(
        f"""
        SELECT EXISTS(
            SELECT 1 FROM {DB_SCHEMA}.customer_services cs
             WHERE cs.id = $1 AND {vis_sql}
        )
        """,
        customer_service_id,
        *vis_vals,
    )
    if not ok:
        raise HTTPException(status_code=403, detail="Not allowed to access this customer service.")


async def _validate_employee(conn: asyncpg.Connection, emp_id: int) -> bool:
    row = await conn.fetchval(
        f"""
        SELECT EXISTS(
            SELECT 1 FROM {DB_SCHEMA}.employees
             WHERE emp_id = $1 AND is_active = TRUE
        )
        """,
        emp_id,
    )
    return bool(row)


@router.get(
    "/filter",
    response_model=None,
    summary="Filter customer services (service-level)",
)
async def filter_customer_services_staff(
    customer_id: Optional[int] = Query(None, gt=0),
    service_code: Optional[str] = Query(None),
    service_status: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    rm_id: Optional[int] = Query(None),
    op_id: Optional[int] = Query(None),
    mobile: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    status_u = service_status.strip().upper() if isinstance(service_status, str) and service_status.strip() else None
    if status_u and status_u not in {"PENDING", "PROVIDED"}:
        _raise_validation({"service_status": "Must be PENDING or PROVIDED."})

    code_u = service_code.strip().upper() if isinstance(service_code, str) and service_code.strip() else None
    mobile_q = mobile.strip() if isinstance(mobile, str) and mobile.strip() else None

    cache_key = build_cache_key(
        "customer_service:staff:filter",
        role=role,
        emp_id=emp_id,
        customer_id=customer_id,
        service_code=code_u,
        service_status=status_u,
        is_active=is_active,
        rm_id=rm_id,
        op_id=op_id,
        mobile=mobile_q,
        limit=limit,
        offset=offset,
    )

    pool = await get_db_pool()

    async def _load():
        clauses = []
        params: list = []
        if customer_id is not None:
            params.append(customer_id)
            clauses.append(f"cs.customer_id = ${len(params)}")
        if code_u:
            params.append(code_u)
            clauses.append(f"upper(trim(cs.service_code)) = ${len(params)}")
        if status_u:
            params.append(status_u)
            clauses.append(f"upper(trim(cs.service_status)) = ${len(params)}")
        if is_active is not None:
            params.append(is_active)
            clauses.append(f"cs.is_active = ${len(params)}")
        if rm_id is not None:
            params.append(rm_id)
            clauses.append(f"cs.rm_id = ${len(params)}")
        if op_id is not None:
            params.append(op_id)
            clauses.append(f"cs.op_id = ${len(params)}")
        if mobile_q:
            params.append(mobile_q)
            clauses.append(f"trim(c.mobile) = trim(${len(params)}::text)")

        vis_sql, vis_vals, _ = build_customer_service_visibility(
            role, emp_id if emp_id > 0 else None, len(params) + 1, DB_SCHEMA
        )
        parts = list(clauses)
        if vis_sql:
            parts.append(vis_sql)
            params.extend(vis_vals)
        where_sql = f"WHERE {' AND '.join(parts)}" if parts else ""

        lim_i = len(params) + 1
        off_i = len(params) + 2

        sql = f"""
            SELECT
                cs.id,
                cs.customer_id,
                cs.service_code,
                cs.service_status,
                cs.provided_at,
                cs.is_active,
                cs.rm_id,
                cs.op_id,
                cs.created_at,
                cs.updated_at,
                c.full_name,
                c.mobile,
                sc.service_name
            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
            LEFT JOIN LATERAL (
                SELECT sc.service_name
                FROM {DB_SCHEMA}.service_config sc
                WHERE upper(trim(sc.service_code)) = upper(trim(cs.service_code))
                  AND sc.is_active IS NOT DISTINCT FROM TRUE
                LIMIT 1
            ) sc ON TRUE
            {where_sql}
            ORDER BY cs.updated_at DESC NULLS LAST, cs.id DESC
            LIMIT ${lim_i} OFFSET ${off_i}
        """
        cnt_sql = f"""
            SELECT COUNT(*)::bigint
              FROM {DB_SCHEMA}.customer_services cs
              JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
            {where_sql}
        """
        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(cnt_sql, *params)
                rows = await conn.fetch(sql, *params, limit, offset)
        except asyncpg.PostgresError:
            logger.exception("customer_service filter DB error")
            raise HTTPException(500, "Database error.")

        items = [CustomerServiceListItemOut(**dict(r)).model_dump() for r in rows]
        return {
            "data": items,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load,
        ttl_seconds=120,
        tags=[_customer_service_list_tag()],
    )


@router.get(
    "/bulk-assign/candidates",
    response_model=CustomerServiceBulkAssignCandidatesOut,
    summary="List customer_services eligible for bulk RM/OP assignment",
)
async def bulk_assign_candidates(
    customer_id: Optional[int] = Query(None, gt=0),
    customer_ids: Optional[List[int]] = Query(None),
    service_codes: Optional[List[str]] = Query(None),
    service_statuses: Optional[List[str]] = Query(None),
    rm_ids: Optional[List[int]] = Query(None),
    op_ids: Optional[List[int]] = Query(None),
    is_active: Optional[bool] = Query(None),
    null_rm: Optional[bool] = Query(
        None,
        description="If true, only rows with rm_id IS NULL (e.g. before bulk RM assign).",
    ),
    null_op: Optional[bool] = Query(
        None,
        description="If true, only rows with op_id IS NULL (e.g. before bulk OP assign).",
    ),
    null_fields: Optional[List[str]] = Query(None),
    not_null_fields: Optional[List[str]] = Query(None),
    match_mode: str = Query("AND", description="AND or OR across provided filters."),
    filter_mode: str = Query("IN", description="IN or NOT_IN for provided filter values."),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    out = await svc_bulk_assign_candidates(
        customer_id=customer_id,
        customer_ids=customer_ids,
        service_codes=service_codes,
        service_statuses=service_statuses,
        rm_ids=rm_ids,
        op_ids=op_ids,
        is_active=is_active,
        null_rm=null_rm,
        null_op=null_op,
        null_fields=null_fields,
        not_null_fields=not_null_fields,
        match_mode=match_mode,
        filter_mode=filter_mode,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )
    return CustomerServiceBulkAssignCandidatesOut(**out)


@router.post(
    "/bulk-assign/execute",
    summary="Bulk assign RM or OP (ADMIN only, round-robin)",
    description=(
        "Sets rm_id when assignment_role is RM, op_id when assignment_role is OP. "
        "Each selected_employee_ids entry must be an active employee with matching role (RM or OP)."
    ),
)
async def bulk_assign_execute(
    payload: CustomerServiceBulkAssignExecuteIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    return await svc_bulk_assign_execute(payload, current_user)


@router.get(
    "/{customer_service_id}",
    response_model=CustomerServiceDetailOut,
    summary="Get one customer service (service-level, ADMIN only)",
)
async def get_customer_service_detail(
    customer_service_id: int,
    current_user=Depends(require_admin()),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    cache_key = build_cache_key(
        "customer_service:staff:detail",
        role=role,
        emp_id=emp_id,
        customer_service_id=customer_service_id,
    )

    pool = await get_db_pool()

    async def _load():
        clauses = [f"cs.id = $1"]
        params: list = [customer_service_id]

        vis_sql, vis_vals, _ = build_customer_service_visibility(
            role, emp_id if emp_id > 0 else None, len(params) + 1, DB_SCHEMA
        )
        if vis_sql:
            clauses.append(vis_sql)
            params.extend(vis_vals)

        where_sql = "WHERE " + " AND ".join(clauses)

        sql = f"""
            SELECT
                cs.id,
                cs.customer_id,
                cs.service_code,
                cs.service_status,
                cs.provided_at,
                cs.is_active,
                cs.rm_id,
                cs.op_id,
                cs.created_at,
                cs.updated_at,
                c.full_name,
                c.mobile,
                c.business_name,
                sc.service_name,
                rm.first_name AS rm_first_name,
                op.first_name AS op_first_name
            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
            LEFT JOIN {DB_SCHEMA}.service_config sc
              ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
             AND sc.is_active IS NOT DISTINCT FROM TRUE
            LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = cs.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = cs.op_id
            {where_sql}
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        if not row:
            raise HTTPException(status_code=404, detail="Customer service not found.")
        return CustomerServiceDetailOut(**dict(row)).model_dump()

    return await redis_get_or_set_json(
        cache_key,
        loader=_load,
        ttl_seconds=120,
        tags=[
            _customer_service_list_tag(),
            _customer_service_detail_tag(customer_service_id),
        ],
    )


@router.delete(
    "/{customer_service_id}/soft_delete",
    summary="Soft delete customer service (service row only + audit)",
    responses={
        200: {"description": "Customer service deactivated successfully."},
        400: {"description": "Business validation failed."},
        403: {"description": "Not allowed."},
        404: {"description": "Customer service not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_customer_service(
    customer_service_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id_ctx = int(raw) if str(raw).isdigit() else None

    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id_ctx,
            "api": "soft_delete_customer_service",
        },
    )

    log.info("Incoming customer service soft delete | customer_service_id=%s", customer_service_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customer_services
                     WHERE id = $1
                     FOR UPDATE
                    """,
                    customer_service_id,
                )

                if not old_row:
                    raise HTTPException(status_code=404, detail="Customer service not found.")

                await _assert_customer_service_row_visibility(
                    conn,
                    customer_service_id=customer_service_id,
                    role=role,
                    emp_id=emp_id,
                )

                if old_row.get("is_active") is False:
                    raise HTTPException(
                        status_code=400,
                        detail="Customer service already inactive.",
                    )

                pending_followups = (
                    str(old_row.get("followup_status") or "").upper() == "PENDING"
                    and old_row.get("followup_at") is not None
                )
                if pending_followups:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot deactivate service with pending followups.",
                    )

                if str(old_row.get("service_status") or "").upper() == "PROVIDED":
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot deactivate completed service.",
                    )

                deleted_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = TRUE
                     RETURNING *
                    """,
                    customer_service_id,
                )

                if not deleted_row:
                    raise HTTPException(
                        status_code=400,
                        detail="Unable to deactivate customer service.",
                    )

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
                    emp_id_ctx,
                    "CUSTOMER_SERVICE",
                    customer_service_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            log.info(
                "Customer service soft deleted | customer_service_id=%s",
                customer_service_id,
            )
            await _invalidate_customer_services_index_caches()
            await redis_invalidate_tag(_customer_service_list_tag())
            await redis_invalidate_tag(_customer_service_detail_tag(customer_service_id))

            return {
                **dict(deleted_row),
                "message": "Customer service soft deleted successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK constraint error")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Postgres error during customer service soft delete")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during customer service soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")


@router.post(
    "/{customer_service_id}/activate",
    summary="Activate customer service (Production Ready + Audit)",
    responses={
        200: {"description": "Customer service activated successfully."},
        400: {"description": "Validation failed or already active."},
        403: {"description": "Not allowed."},
        404: {"description": "Customer service not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_customer_service_row(
    customer_service_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id_ctx = int(raw) if str(raw).isdigit() else None

    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id_ctx,
            "api": "activate_customer_service_row",
        },
    )

    log.info("Incoming customer service activate | customer_service_id=%s", customer_service_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                cs_row = await conn.fetchrow(
                    f"""
                    SELECT cs.*
                      FROM {DB_SCHEMA}.customer_services cs
                     WHERE cs.id = $1
                     FOR UPDATE
                    """,
                    customer_service_id,
                )

                if not cs_row:
                    raise HTTPException(status_code=404, detail="Customer service not found.")

                await _assert_customer_service_row_visibility(
                    conn,
                    customer_service_id=customer_service_id,
                    role=role,
                    emp_id=emp_id,
                )

                if cs_row.get("is_active") is True:
                    raise HTTPException(status_code=400, detail="Customer service already active.")

                cust_active = await conn.fetchval(
                    f"""
                    SELECT c.is_active
                      FROM {DB_SCHEMA}.customers c
                     WHERE c.customer_id = $1
                    """,
                    cs_row["customer_id"],
                )
                if cust_active is False:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot activate customer service: associated customer is inactive.",
                    )

                activated = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    customer_service_id,
                )

                if not activated:
                    raise HTTPException(
                        status_code=409,
                        detail="Customer service state changed. Please retry.",
                    )

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
                    emp_id_ctx,
                    "CUSTOMER_SERVICE",
                    customer_service_id,
                    activated["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            log.info(
                "Customer service activated | customer_service_id=%s",
                customer_service_id,
            )
            await _invalidate_customer_services_index_caches()
            await redis_invalidate_tag(_customer_service_list_tag())
            await redis_invalidate_tag(_customer_service_detail_tag(customer_service_id))

            return {
                **dict(activated),
                "message": "Customer service activated successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK ERROR")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Database error during customer service activate")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during customer service activate")
            raise HTTPException(status_code=500, detail="Internal server error.")


@router.patch(
    "/{customer_service_id}/service-status",
    summary="Update customer service status only (EMPLOYEE WRITE, visibility applies)",
)
async def patch_customer_service_status(
    customer_service_id: int,
    payload: CustomerServiceStatusPatchIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id_ctx = int(raw) if str(raw).isdigit() else None

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customer_services
                     WHERE id = $1
                     FOR UPDATE
                    """,
                    customer_service_id,
                )
                if not old_row:
                    raise HTTPException(404, "Customer service not found.")

                await _assert_customer_service_row_visibility(
                    conn,
                    customer_service_id=customer_service_id,
                    role=role,
                    emp_id=emp_id,
                )

                new_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET service_status = $1,
                           updated_at = NOW()
                     WHERE id = $2
                     RETURNING *
                    """,
                    payload.service_status,
                    customer_service_id,
                )

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
                    emp_id_ctx,
                    "CUSTOMER_SERVICE",
                    customer_service_id,
                    new_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

        await _invalidate_customer_services_index_caches()
        await redis_invalidate_tag(_customer_service_list_tag())
        await redis_invalidate_tag(_customer_service_detail_tag(customer_service_id))

        return {
            "message": "Customer service status updated.",
            "data": dict(new_row),
            "request_id": generate_uuid(),
        }
    except HTTPException:
        raise
    except asyncpg.PostgresError:
        logger.exception("patch customer_service status DB error")
        raise HTTPException(500, "Database error.")


@router.patch(
    "/{customer_service_id}",
    summary="Patch customer service (RM/OP/service_status/is_active only, ADMIN only)",
)
async def patch_customer_service(
    customer_service_id: int,
    payload: CustomerServicePatchIn,
    current_user=Depends(require_admin()),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id_ctx = int(raw) if str(raw).isdigit() else None

    data = payload.model_dump(exclude_unset=True)
    if not data:
        _raise_validation({}, message="No fields to update.")

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customer_services
                     WHERE id = $1
                     FOR UPDATE
                    """,
                    customer_service_id,
                )
                if not old_row:
                    raise HTTPException(404, "Customer service not found.")

                await _assert_customer_service_row_visibility(
                    conn,
                    customer_service_id=customer_service_id,
                    role=role,
                    emp_id=emp_id,
                )

                if "rm_id" in data and data["rm_id"] is not None:
                    if not await _validate_employee(conn, int(data["rm_id"])):
                        _raise_validation({"rm_id": "Invalid or inactive employee."})

                if "op_id" in data and data["op_id"] is not None:
                    if not await _validate_employee(conn, int(data["op_id"])):
                        _raise_validation({"op_id": "Invalid or inactive employee."})

                sets = []
                vals: list = []
                i = 1
                for key in ("rm_id", "op_id", "service_status", "is_active"):
                    if key not in data:
                        continue
                    sets.append(f"{key} = ${i}")
                    vals.append(data[key])
                    i += 1

                vals.append(customer_service_id)
                upd_sql = f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET {", ".join(sets)}, updated_at = NOW()
                     WHERE id = ${i}
                     RETURNING *
                """
                new_row = await conn.fetchrow(upd_sql, *vals)

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
                    emp_id_ctx,
                    "CUSTOMER_SERVICE",
                    customer_service_id,
                    new_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

        await _invalidate_customer_services_index_caches()
        await redis_invalidate_tag(_customer_service_list_tag())
        await redis_invalidate_tag(_customer_service_detail_tag(customer_service_id))

        return {
            "message": "Customer service updated.",
            "data": dict(new_row),
            "request_id": generate_uuid(),
        }
    except HTTPException:
        raise
    except asyncpg.PostgresError:
        logger.exception("patch customer_service DB error")
        raise HTTPException(500, "Database error.")


# ---------------------------------------------------------------------------
# Migrated from app.customer_registration.services (legacy paths)
# (Redis cache tags unchanged for continuity.)
# ---------------------------------------------------------------------------

def _legacy_cs_filter_tag() -> str:
    return "customer_services:filter:index"


def _legacy_cs_dashboard_tag() -> str:
    return "customer_services:dashboard:index"


def _legacy_cs_pending_tag() -> str:
    return "customer_services:pending:index"


def _legacy_cs_progress_tracker_tag() -> str:
    return "customer_services:progress_tracker:index"


def _derive_customer_progress_status(provided_count: int, pending_count: int) -> str:
    if provided_count > 0 and pending_count == 0:
        return "COMPLETED"
    if provided_count > 0 and pending_count > 0:
        return "IN_PROGRESS"
    return "NOT_STARTED"


@router.get(
    "/customer-services/progress-tracker",
    response_model=None,
    summary="Per-customer service progress (PENDING/PROVIDED counts, visibility, Redis)",
)
async def get_customer_services_progress_tracker(
    overall_status: Optional[str] = Query(
        None,
        description="Filter rows: NOT_STARTED | IN_PROGRESS | COMPLETED",
    ),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    status_filter = None
    if overall_status and str(overall_status).strip():
        status_filter = str(overall_status).strip().upper()
        if status_filter not in {"NOT_STARTED", "IN_PROGRESS", "COMPLETED"}:
            raise HTTPException(status_code=400, detail="Invalid overall_status")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_customer_services_progress_tracker"},
    )
    cache_key = build_cache_key(
        "customer_services:progress_tracker",
        overall_status=status_filter,
        limit=limit,
        offset=offset,
        role=(role or "").strip().upper() or None,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load_progress_tracker():
        conditions = ["cs.is_active IS TRUE"]
        values: list = []
        idx = 1

        visibility_sql, visibility_values, idx = build_customer_service_visibility(
            role, emp_id, idx, DB_SCHEMA
        )
        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        agg_sql = f"""
            WITH scoped AS (
                SELECT
                    cs.customer_id,
                    cs.service_status,
                    cs.rm_id,
                    cs.op_id,
                    cs.created_at,
                    c.full_name,
                    c.business_name,
                    c.mobile,
                    COALESCE(NULLIF(trim(sc.service_name), ''), upper(trim(cs.service_code))) AS service_label,
                    rm.first_name AS rm_first_name,
                    op.first_name AS op_first_name
                FROM {DB_SCHEMA}.customer_services cs
                JOIN {DB_SCHEMA}.customers c
                  ON c.customer_id = cs.customer_id
                LEFT JOIN {DB_SCHEMA}.service_config sc
                  ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
                 AND sc.is_active IS NOT DISTINCT FROM TRUE
                LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = cs.rm_id
                LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = cs.op_id
                {where_clause}
            ),
            per_customer AS (
                SELECT
                    customer_id,
                    MAX(full_name) AS customer_name,
                    MAX(business_name) AS business_name,
                    MAX(mobile) AS phone_number,
                    COUNT(*)::int AS required_count,
                    COUNT(*) FILTER (WHERE upper(trim(service_status)) = 'PROVIDED')::int AS provided_count,
                    COUNT(*) FILTER (WHERE upper(trim(service_status)) = 'PENDING')::int AS pending_count,
                    MAX(created_at) AS latest_service_at,
                    (ARRAY_AGG(rm_id ORDER BY created_at DESC NULLS LAST))[1] AS rm_id,
                    (ARRAY_AGG(op_id ORDER BY created_at DESC NULLS LAST))[1] AS op_id,
                    (ARRAY_AGG(rm_first_name ORDER BY created_at DESC NULLS LAST))[1] AS rm_username,
                    (ARRAY_AGG(op_first_name ORDER BY created_at DESC NULLS LAST))[1] AS op_username,
                    COALESCE(
                        array_agg(DISTINCT service_label)
                        FILTER (WHERE service_label IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS required_services,
                    COALESCE(
                        array_agg(DISTINCT service_label)
                        FILTER (
                            WHERE service_label IS NOT NULL
                              AND upper(trim(service_status)) = 'PROVIDED'
                        ),
                        ARRAY[]::text[]
                    ) AS provided_services,
                    COALESCE(
                        array_agg(DISTINCT service_label)
                        FILTER (
                            WHERE service_label IS NOT NULL
                              AND upper(trim(service_status)) = 'PENDING'
                        ),
                        ARRAY[]::text[]
                    ) AS pending_services
                FROM scoped
                GROUP BY customer_id
                HAVING COUNT(*) > 0
            ),
            enriched AS (
                SELECT
                    *,
                    CASE
                        WHEN provided_count > 0 AND pending_count = 0 THEN 'COMPLETED'
                        WHEN provided_count > 0 AND pending_count > 0 THEN 'IN_PROGRESS'
                        ELSE 'NOT_STARTED'
                    END AS overall_status,
                    CASE
                        WHEN required_count > 0
                        THEN ROUND((provided_count::numeric / required_count::numeric) * 100)::int
                        ELSE 0
                    END AS completion_percent
                FROM per_customer
            )
            SELECT *
            FROM enriched
            ORDER BY latest_service_at DESC NULLS LAST, customer_id ASC
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(agg_sql, *values)

        all_rows = []
        summary = {
            "tracked_customers": 0,
            "completed": 0,
            "in_progress": 0,
            "not_started": 0,
        }
        for row in rows:
            item = dict(row)
            item["overall_status"] = _derive_customer_progress_status(
                int(item.get("provided_count") or 0),
                int(item.get("pending_count") or 0),
            )
            summary["tracked_customers"] += 1
            st = item["overall_status"]
            if st == "COMPLETED":
                summary["completed"] += 1
            elif st == "IN_PROGRESS":
                summary["in_progress"] += 1
            else:
                summary["not_started"] += 1

            if status_filter and item["overall_status"] != status_filter:
                continue
            all_rows.append(item)

        total_count = len(all_rows)
        page_rows = all_rows[offset : offset + limit]

        return {
            "data": {
                "summary": summary,
                "rows": page_rows,
                "count": len(page_rows),
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
            },
            "request_id": request_id,
        }

    try:
        return await redis_get_or_set_json(
            cache_key,
            loader=_load_progress_tracker,
            ttl_seconds=300,
            tags=[_legacy_cs_progress_tracker_tag()],
        )
    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error fetching progress tracker")
        raise HTTPException(status_code=500, detail="Internal server error.")


@router.get(
    "/customer-services/filter",
    response_model=None,
    summary="Filter customer services (extended: cursor, multi service_codes)",
)
async def filter_customer_services_extended(
    id: Optional[int] = None,
    customer_id: Optional[int] = None,
    service_code: Optional[str] = None,
    service_codes: Optional[List[str]] = Query(None),
    service_status: Optional[str] = None,
    status: Optional[str] = None,
    is_active: Optional[bool] = Query(None),
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cursor: Optional[datetime] = None,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    service_status_u = (
        service_status.strip().upper()
        if isinstance(service_status, str) and service_status.strip()
        else None
    )

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_customer_services_extended"},
    )
    cache_key = build_cache_key(
        "customer_services:filter",
        id=id,
        customer_id=customer_id,
        service_code=service_code,
        service_codes=service_codes,
        service_status=service_status_u,
        status=status,
        is_active=is_active,
        rm_id=rm_id,
        op_id=op_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
        cursor=cursor,
        role=(role or "").strip().upper() or None,
        emp_id=emp_id,
    )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date cannot be greater than to_date")

    if from_date and from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)

    if to_date and to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)

    if cursor and cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=timezone.utc)

    if service_code and service_codes:
        raise HTTPException(
            status_code=400,
            detail="Use either service_code or service_codes, not both",
        )

    valid_service_status = {"PENDING", "PROVIDED"}
    if service_status_u and service_status_u not in valid_service_status:
        raise HTTPException(status_code=400, detail="Invalid service_status")

    valid_status = {"ACTIVE", "INACTIVE"}
    if status and status.strip().upper() not in valid_status:
        raise HTTPException(status_code=400, detail="Invalid status (use ACTIVE or INACTIVE).")

    if is_active is not None and status:
        raise HTTPException(
            status_code=400,
            detail="Use either is_active or status, not both.",
        )

    if cursor and offset > 0:
        raise HTTPException(
            status_code=400,
            detail="offset should not be used with cursor pagination",
        )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    try:

        async def _load_filtered_customer_services():
            conditions = []
            values = []
            idx = 1

            if id is not None:
                conditions.append(f"cs.id = ${idx}")
                values.append(id)
                idx += 1

            if customer_id is not None:
                conditions.append(f"cs.customer_id = ${idx}")
                values.append(customer_id)
                idx += 1

            if rm_id is not None:
                conditions.append(f"cs.rm_id = ${idx}")
                values.append(rm_id)
                idx += 1

            if op_id is not None:
                conditions.append(f"cs.op_id = ${idx}")
                values.append(op_id)
                idx += 1

            if service_status_u:
                conditions.append(f"upper(trim(cs.service_status)) = ${idx}")
                values.append(service_status_u)
                idx += 1

            effective_is_active = is_active
            if status is not None and effective_is_active is None:
                su = str(status).strip().upper()
                if su == "ACTIVE":
                    effective_is_active = True
                elif su == "INACTIVE":
                    effective_is_active = False

            if effective_is_active is not None:
                conditions.append(f"cs.is_active = ${idx}")
                values.append(effective_is_active)
                idx += 1

            if service_code:
                conditions.append(f"upper(trim(cs.service_code)) = upper(trim(${idx}::text))")
                values.append(service_code.strip())
                idx += 1

            if service_codes:
                cleaned = [str(s).strip().upper() for s in service_codes if s and str(s).strip()]
                if cleaned:
                    conditions.append(f"upper(trim(cs.service_code)) = ANY(${idx})")
                    values.append(cleaned)
                    idx += 1

            if from_date:
                conditions.append(f"cs.created_at >= ${idx}")
                values.append(from_date)
                idx += 1

            if to_date:
                conditions.append(f"cs.created_at <= ${idx}")
                values.append(to_date)
                idx += 1

            if cursor:
                conditions.append(f"cs.created_at < ${idx}")
                values.append(cursor)
                idx += 1

            visibility_sql, visibility_values, idx = build_customer_service_visibility(
                role, emp_id, idx, DB_SCHEMA
            )

            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            if cursor:
                pagination_sql = f"LIMIT ${idx}"
                values_with_pagination = values + [limit]
            else:
                pagination_sql = f"LIMIT ${idx} OFFSET ${idx+1}"
                values_with_pagination = values + [limit, offset]

            main_sql = f"""
            SELECT
                cs.id,
                cs.customer_id,
                cs.service_code,
                cs.service_status,
                cs.is_active,
                cs.rm_id,
                cs.op_id,
                cs.provided_at,
                cs.created_at,
                cs.updated_at,

                c.full_name,
                c.mobile,
                c.business_name,
                sc.service_name,

                rm.first_name AS rm_name,
                op.first_name AS op_name

            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.customers c
                ON c.customer_id = cs.customer_id
            LEFT JOIN {DB_SCHEMA}.service_config sc
              ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
             AND sc.is_active IS NOT DISTINCT FROM TRUE
            LEFT JOIN {DB_SCHEMA}.employees rm
                ON rm.emp_id = cs.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op
                ON op.emp_id = cs.op_id

            {where_clause}
            ORDER BY cs.created_at DESC
            {pagination_sql}
        """

            async with pool.acquire() as conn:
                rows = await conn.fetch(main_sql, *values_with_pagination)

            next_cursor = rows[-1]["created_at"] if rows else None

            return {
                "data": [dict(row) for row in rows],
                "next_cursor": next_cursor,
                "request_id": request_id,
            }

        return await redis_get_or_set_json(
            cache_key,
            loader=_load_filtered_customer_services,
            ttl_seconds=300,
            tags=[_legacy_cs_filter_tag()],
        )

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(status_code=500, detail="Database error")

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/customer-services/dashboard/stats",
    response_model=None,
    summary="Customer services dashboard stats (IST windows)",
)
async def get_customer_services_dashboard_stats(
    filter_type: Optional[str] = Query(
        None,
        description="today | yesterday | last_7_days | last_1_month | last_2_months",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "api": "get_customer_services_dashboard_stats"},
    )
    cache_key = build_cache_key(
        "customer_services:dashboard",
        filter_type=filter_type,
        role=(role or "").strip().upper() or None,
        emp_id=emp_id,
    )

    now = datetime.now(IST)

    start_dt = None
    end_dt = None

    valid_filters = {
        "today",
        "yesterday",
        "last_7_days",
        "last_1_month",
        "last_2_months",
    }

    if filter_type and filter_type not in valid_filters:
        raise HTTPException(400, "Invalid filter_type")

    if filter_type:
        if filter_type == "today":
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = now
        elif filter_type == "yesterday":
            yesterday = now - timedelta(days=1)
            start_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=1)
        elif filter_type == "last_7_days":
            start_dt = now - timedelta(days=7)
            end_dt = now
        elif filter_type == "last_1_month":
            start_dt = now - timedelta(days=30)
            end_dt = now
        elif filter_type == "last_2_months":
            start_dt = now - timedelta(days=60)
            end_dt = now

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:

            async def _load_service_dashboard_stats():
                conditions = ["cs.is_active IS TRUE"]
                values = []
                idx = 1

                if start_dt and end_dt:
                    conditions.append(f"cs.created_at >= ${idx}")
                    values.append(start_dt)
                    idx += 1

                    conditions.append(f"cs.created_at <= ${idx}")
                    values.append(end_dt)
                    idx += 1

                visibility_sql, visibility_values, idx = build_customer_service_visibility(
                    role, emp_id, idx, DB_SCHEMA
                )

                if visibility_sql:
                    conditions.append(visibility_sql)
                    values.extend(visibility_values)

                where_clause = f"WHERE {' AND '.join(conditions)}"

                query = f"""
                SELECT
                    COUNT(*) FILTER (WHERE cs.service_status = 'PENDING') AS pending_services,
                    COUNT(*) FILTER (WHERE cs.service_status = 'PROVIDED') AS provided_services,
                    COUNT(*) AS total_services
                FROM {DB_SCHEMA}.customer_services cs
                {where_clause}
            """

                row = await conn.fetchrow(query, *values)

                return {
                    "data": dict(row)
                    if row
                    else {
                        "pending_services": 0,
                        "provided_services": 0,
                        "total_services": 0,
                    },
                    "request_id": request_id,
                }

            return await redis_get_or_set_json(
                cache_key,
                loader=_load_service_dashboard_stats,
                ttl_seconds=300,
                tags=[_legacy_cs_dashboard_tag()],
            )

        except Exception as e:
            log.error("Error fetching service dashboard stats: %s", e)
            raise HTTPException(500, "Database internal error.")


@router.get(
    "/customer-services/pending",
    response_model=None,
    summary="Pending customer services (active rows, service_status=PENDING)",
)
async def get_customer_services_pending_list(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error.")

    try:
        cache_key = build_cache_key(
            "customer_services:pending",
            limit=limit,
            offset=offset,
            role=(role or "").strip().upper() or None,
            emp_id=emp_id,
        )

        async def _load_pending_services():
            conditions = [
                "cs.service_status = 'PENDING'",
                "cs.is_active IS TRUE",
            ]

            values = []
            idx = 1

            visibility_sql, visibility_values, idx = build_customer_service_visibility(
                role, emp_id, idx, DB_SCHEMA
            )

            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            where_clause = f"WHERE {' AND '.join(conditions)}"

            query = f"""
                SELECT
                    cs.id,
                    cs.customer_id,
                    c.full_name,
                    sc.service_name,
                    cs.service_code,
                    cs.rm_id,
                    cs.op_id,
                    cs.created_at
                FROM {DB_SCHEMA}.customer_services cs
                JOIN {DB_SCHEMA}.customers c
                    ON c.customer_id = cs.customer_id
                LEFT JOIN {DB_SCHEMA}.service_config sc
                  ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
                 AND sc.is_active IS NOT DISTINCT FROM TRUE
                {where_clause}
                ORDER BY cs.created_at DESC
                LIMIT ${idx} OFFSET ${idx+1}
            """

            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values, limit, offset)

            return {
                "data": [dict(r) for r in rows],
                "request_id": request_id,
            }

        return await redis_get_or_set_json(
            cache_key,
            loader=_load_pending_services,
            ttl_seconds=300,
            tags=[_legacy_cs_pending_tag()],
        )

    except Exception:
        raise HTTPException(500, "Internal server error")
