"""Bulk RM/OP assignment for `customer_services` (CRM-style; no CSV import)."""

import json
import logging
from typing import List, Optional

import asyncpg
from fastapi import HTTPException

from backend.common.status_constants import SERVICE_STATUSES
from backend.customer_service.schemas import CustomerServiceBulkAssignExecuteIn
from backend.redis_cache import invalidate_tag as redis_invalidate_tag
from backend.utils import DB_SCHEMA, build_customer_service_visibility, get_db_pool

logger = logging.getLogger(__name__)

NULL_FIELD_SQL = {
    "RM_ID": "cs.rm_id",
    "OP_ID": "cs.op_id",
    "SERVICE_CODE": "cs.service_code",
    "SERVICE_STATUS": "cs.service_status",
    "PROVIDED_AT": "cs.provided_at",
    "CUSTOMER_ID": "cs.customer_id",
}


def _user_ctx(current_user):
    role = (current_user.get("role") or "").strip().upper()
    emp_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_raw) if str(emp_raw).isdigit() else 0
    return role, emp_id


def _require_row_context(role: str, emp_id: int) -> None:
    if role == "ADMIN":
        return
    if emp_id <= 0:
        raise HTTPException(
            status_code=403,
            detail="Employee context required for this operation.",
        )


def _normalize_code(value: str) -> str:
    return str(value or "").strip().upper()


def _norm_str_list(vals: Optional[List[str]]) -> List[str]:
    return list(
        dict.fromkeys(
            [_normalize_code(v) for v in (vals or []) if isinstance(v, str) and v.strip()]
        )
    )


def _norm_int_list(vals: Optional[List[int]]) -> List[int]:
    out: List[int] = []
    seen = set()
    for raw in vals or []:
        try:
            num = int(raw)
        except (TypeError, ValueError):
            continue
        if num <= 0 or num in seen:
            continue
        seen.add(num)
        out.append(num)
    return out


async def _invalidate_customer_services_index_caches() -> None:
    for tag in (
        "customer_services:filter:index",
        "customer_services:dashboard:index",
        "customer_services:pending:index",
        "customer_services:progress_tracker:index",
        "customer_service_followups:list:index",
        "customer_service_followups:counts:index",
        "customer_service_followups:alerts:index",
    ):
        await redis_invalidate_tag(tag)
    # A customer_services write can flip service_status into/out of a "done" state,
    # which changes what qualifies for the service-done-payment-pending dashboard.
    from backend.Dashboard.service_done_payment_pending import (
        invalidate_service_done_payment_pending_cache,
    )
    await invalidate_service_done_payment_pending_cache()


async def svc_bulk_assign_candidates(
    *,
    customer_id: Optional[int],
    customer_ids: Optional[List[int]],
    service_codes: Optional[List[str]],
    service_statuses: Optional[List[str]],
    rm_ids: Optional[List[int]],
    op_ids: Optional[List[int]],
    is_active: Optional[bool],
    null_rm: Optional[bool],
    null_op: Optional[bool],
    null_fields: Optional[List[str]],
    not_null_fields: Optional[List[str]],
    match_mode: str,
    filter_mode: str,
    limit: int,
    offset: int,
    current_user: dict,
) -> dict:
    role, emp_id = _user_ctx(current_user)
    _require_row_context(role, emp_id)

    mode = _normalize_code(match_mode)
    if mode not in {"AND", "OR"}:
        raise HTTPException(status_code=400, detail={"match_mode": "Use AND or OR."})

    filter_mode_norm = _normalize_code(filter_mode)
    if filter_mode_norm not in {"IN", "NOT_IN"}:
        raise HTTPException(status_code=400, detail={"filter_mode": "Use IN or NOT_IN."})

    codes_n = _norm_str_list(service_codes)
    status_n = _norm_str_list(service_statuses)
    for s in status_n:
        if s not in SERVICE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail={"service_statuses": f"Invalid status: {s}"},
            )

    rm_ids_n = _norm_int_list(rm_ids)
    op_ids_n = _norm_int_list(op_ids)
    customer_ids_n = _norm_int_list(customer_ids)
    null_fields_n = _norm_str_list(null_fields)
    not_null_fields_n = _norm_str_list(not_null_fields)

    invalid_null = [f for f in null_fields_n if f not in NULL_FIELD_SQL]
    if invalid_null:
        raise HTTPException(
            status_code=400,
            detail={"null_fields": f"Unsupported values: {', '.join(invalid_null)}"},
        )
    invalid_not_null = [f for f in not_null_fields_n if f not in NULL_FIELD_SQL]
    if invalid_not_null:
        raise HTTPException(
            status_code=400,
            detail={"not_null_fields": f"Unsupported values: {', '.join(invalid_not_null)}"},
        )
    overlap = sorted(set(null_fields_n) & set(not_null_fields_n))
    if overlap:
        raise HTTPException(
            status_code=400,
            detail={"null_fields": f"Conflicts with not_null_fields: {', '.join(overlap)}"},
        )

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            clauses = []
            params: list = []

            if customer_ids_n:
                params.append(customer_ids_n)
                clauses.append(
                    f"cs.customer_id = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (cs.customer_id = ANY(${len(params)}))"
                )
            elif customer_id is not None:
                params.append(customer_id)
                clauses.append(f"cs.customer_id = ${len(params)}")

            if codes_n:
                params.append(codes_n)
                clauses.append(
                    f"upper(trim(cs.service_code)) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (upper(trim(cs.service_code)) = ANY(${len(params)}))"
                )

            if status_n:
                params.append(status_n)
                clauses.append(
                    f"upper(trim(cs.service_status)) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (upper(trim(cs.service_status)) = ANY(${len(params)}))"
                )

            if rm_ids_n:
                params.append(rm_ids_n)
                clauses.append(
                    f"cs.rm_id = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (cs.rm_id = ANY(${len(params)}))"
                )

            if op_ids_n:
                params.append(op_ids_n)
                clauses.append(
                    f"cs.op_id = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (cs.op_id = ANY(${len(params)}))"
                )

            if is_active is not None:
                params.append(is_active)
                clauses.append(f"cs.is_active = ${len(params)}")

            if null_rm is True:
                clauses.append("cs.rm_id IS NULL")
            elif null_rm is False:
                clauses.append("cs.rm_id IS NOT NULL")

            if null_op is True:
                clauses.append("cs.op_id IS NULL")
            elif null_op is False:
                clauses.append("cs.op_id IS NOT NULL")

            for key in null_fields_n:
                clauses.append(f"{NULL_FIELD_SQL[key]} IS NULL")
            for key in not_null_fields_n:
                clauses.append(f"{NULL_FIELD_SQL[key]} IS NOT NULL")

            where_parts = []
            if clauses:
                joiner = " OR " if mode == "OR" else " AND "
                where_parts.append(f"({joiner.join(clauses)})")

            vis_sql, vis_vals, _ = build_customer_service_visibility(
                role, emp_id if emp_id > 0 else None, len(params) + 1, DB_SCHEMA
            )
            if vis_sql:
                where_parts.append(vis_sql)
                params.extend(vis_vals)

            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            base_from = f"""
                FROM {DB_SCHEMA}.customer_services cs
                LEFT JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
                LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = cs.rm_id
                LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = cs.op_id
            """

            count_sql = f"SELECT COUNT(*)::bigint {base_from} {where_sql}"
            list_sql = f"""
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
                    erm.username AS rm_username,
                    eop.username AS op_username
                  {base_from}
                {where_sql}
                ORDER BY cs.updated_at DESC NULLS LAST, cs.id DESC
                LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
            """

            params_with_page = list(params) + [limit, offset]
            total = await conn.fetchval(count_sql, *params)
            rows = await conn.fetch(list_sql, *params_with_page)

            return {
                "items": [dict(r) for r in rows],
                "total": int(total or 0),
                "limit": limit,
                "offset": offset,
                "match_mode": mode,
                "filter_mode": filter_mode_norm,
                "null_fields": null_fields_n,
                "not_null_fields": not_null_fields_n,
            }
    except asyncpg.PostgresError:
        logger.exception("DB error in customer_services bulk-assign candidates")
        raise HTTPException(status_code=500, detail="Database error.")


async def svc_bulk_assign_execute(
    payload: CustomerServiceBulkAssignExecuteIn,
    current_user: dict,
) -> dict:
    role, emp_id = _user_ctx(current_user)
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only ADMIN can bulk assign customer services.")

    ids = list(dict.fromkeys(payload.customer_service_ids))
    emps = list(dict.fromkeys(payload.selected_employee_ids))
    pool = await get_db_pool()

    raw = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id_ctx = int(raw) if str(raw).isdigit() else None

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                expected_role = payload.assignment_role
                valid_rows = await conn.fetch(
                    f"""
                    SELECT emp_id FROM {DB_SCHEMA}.employees
                     WHERE is_active = TRUE
                       AND emp_id = ANY($1::bigint[])
                       AND role = $2
                    """,
                    emps,
                    expected_role,
                )
                valid_emp_ids = [int(r["emp_id"]) for r in valid_rows]
                if len(valid_emp_ids) != len(emps):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "One or more employees are invalid, inactive, or do not match "
                            f"assignment_role={payload.assignment_role} (expect employees.role "
                            f"to be {payload.assignment_role})."
                        ),
                    )

                vis_sql, vis_vals, _ = build_customer_service_visibility(
                    role, emp_id if emp_id > 0 else None, 2, DB_SCHEMA
                )
                vis_clause = f" AND {vis_sql}" if vis_sql else ""

                locked = await conn.fetch(
                    f"""
                    SELECT cs.id
                      FROM {DB_SCHEMA}.customer_services cs
                     WHERE cs.id = ANY($1::bigint[])
                       {vis_clause}
                     FOR UPDATE SKIP LOCKED
                    """,
                    ids,
                    *vis_vals,
                )
                cs_ids = [int(r["id"]) for r in locked]

                per_employee_counts = {eid: 0 for eid in valid_emp_ids}
                emp_cursor = 0
                assigned_total = 0

                for cs_id in cs_ids:
                    assigned = False
                    for _ in range(len(valid_emp_ids)):
                        assignee = valid_emp_ids[emp_cursor % len(valid_emp_ids)]
                        emp_cursor += 1
                        if (
                            payload.per_employee_limit is not None
                            and per_employee_counts[assignee] >= payload.per_employee_limit
                        ):
                            continue
                        old_row = await conn.fetchrow(
                            f"""
                            SELECT * FROM {DB_SCHEMA}.customer_services
                             WHERE id = $1
                            """,
                            cs_id,
                        )
                        if payload.assignment_role == "RM":
                            new_row = await conn.fetchrow(
                                f"""
                                UPDATE {DB_SCHEMA}.customer_services
                                   SET rm_id = $1, updated_at = NOW()
                                 WHERE id = $2
                                 RETURNING *
                                """,
                                assignee,
                                cs_id,
                            )
                        else:
                            new_row = await conn.fetchrow(
                                f"""
                                UPDATE {DB_SCHEMA}.customer_services
                                   SET op_id = $1, updated_at = NOW()
                                 WHERE id = $2
                                 RETURNING *
                                """,
                                assignee,
                                cs_id,
                            )
                        if old_row and new_row:
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
                                cs_id,
                                new_row["customer_id"],
                                "UPDATE",
                                json.dumps(dict(old_row), default=str),
                                json.dumps(dict(new_row), default=str),
                            )
                        per_employee_counts[assignee] += 1
                        assigned_total += 1
                        assigned = True
                        break
                    if not assigned:
                        break

        await _invalidate_customer_services_index_caches()

        return {
            "message": "Customer service bulk assignment completed.",
            "assignment_role": payload.assignment_role,
            "total_selected": len(ids),
            "total_assigned": assigned_total,
            "per_employee_counts": per_employee_counts,
        }
    except asyncpg.PostgresError:
        logger.exception("DB error during customer_services bulk assign")
        raise HTTPException(status_code=500, detail="Database error.")
