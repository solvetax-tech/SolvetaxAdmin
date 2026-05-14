"""Bulk RM/OP assignment for `customer_services` (CRM-style; no CSV import)."""

import json
import logging
from typing import List, Optional

import asyncpg
from fastapi import HTTPException

from app.customer_service.schemas import CustomerServiceBulkAssignExecuteIn
from app.redis_cache import invalidate_tag as redis_invalidate_tag
from app.utils import DB_SCHEMA, build_customer_service_visibility, get_db_pool

logger = logging.getLogger(__name__)


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


async def _invalidate_customer_services_index_caches() -> None:
    for tag in (
        "customer_services:filter:index",
        "customer_services:dashboard:index",
        "customer_services:pending:index",
        "customer_service_followups:list:index",
        "customer_service_followups:counts:index",
        "customer_service_followups:alerts:index",
    ):
        await redis_invalidate_tag(tag)


async def svc_bulk_assign_candidates(
    *,
    customer_id: Optional[int],
    service_codes: Optional[List[str]],
    service_statuses: Optional[List[str]],
    is_active: Optional[bool],
    null_rm: Optional[bool],
    null_op: Optional[bool],
    limit: int,
    offset: int,
    current_user: dict,
) -> dict:
    role, emp_id = _user_ctx(current_user)
    _require_row_context(role, emp_id)

    codes_n: List[str] = []
    if service_codes:
        codes_n = list(
            dict.fromkeys(
                c.strip().upper()
                for c in service_codes
                if isinstance(c, str) and c.strip()
            )
        )

    status_n: List[str] = []
    if service_statuses:
        status_n = list(
            dict.fromkeys(
                s.strip().upper()
                for s in service_statuses
                if isinstance(s, str) and s.strip()
            )
        )
        for s in status_n:
            if s not in {"PENDING", "PROVIDED"}:
                raise HTTPException(
                    status_code=400,
                    detail={"service_statuses": f"Invalid status: {s}"},
                )

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            clauses = []
            params: list = []

            if customer_id is not None:
                params.append(customer_id)
                clauses.append(f"cs.customer_id = ${len(params)}")

            if codes_n:
                params.append(codes_n)
                clauses.append(f"upper(trim(cs.service_code)) = ANY(${len(params)})")

            if status_n:
                params.append(status_n)
                clauses.append(f"cs.service_status = ANY(${len(params)})")

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

            vis_sql, vis_vals, _ = build_customer_service_visibility(
                role, emp_id if emp_id > 0 else None, len(params) + 1, DB_SCHEMA
            )
            where_parts = []
            if clauses:
                where_parts.append(" AND ".join(clauses))
            if vis_sql:
                where_parts.append(vis_sql)
                params.extend(vis_vals)

            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            lim_idx = len(params) + 1
            off_idx = len(params) + 2

            count_sql = f"""
                SELECT COUNT(*)::bigint
                  FROM {DB_SCHEMA}.customer_services cs
                {where_sql}
            """
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
                    c.mobile
                  FROM {DB_SCHEMA}.customer_services cs
                  JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
                {where_sql}
                ORDER BY cs.updated_at DESC NULLS LAST, cs.id DESC
                LIMIT ${lim_idx} OFFSET ${off_idx}
            """

            total = await conn.fetchval(count_sql, *params)
            rows = await conn.fetch(list_sql, *params, limit, offset)

            return {
                "items": [dict(r) for r in rows],
                "total": int(total or 0),
                "limit": limit,
                "offset": offset,
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
                valid_rows = await conn.fetch(
                    f"""
                    SELECT emp_id FROM {DB_SCHEMA}.employees
                     WHERE is_active = TRUE AND emp_id = ANY($1::bigint[])
                    """,
                    emps,
                )
                valid_emp_ids = [int(r["emp_id"]) for r in valid_rows]
                if len(valid_emp_ids) != len(emps):
                    raise HTTPException(
                        status_code=400,
                        detail="One or more employees are invalid or inactive.",
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
