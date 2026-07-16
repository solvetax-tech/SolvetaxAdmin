"""
CRM bulk-assign schedulers (Postgres) + run logs (AUTO + MANUAL).

Lead assignments still update ``crm_leads`` only. Schedulers and logs use dedicated tables
(see scripts/crm_bulk_assign_scheduler.sql).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import HTTPException

from backend.common.status_constants import normalize_run_type
from backend.crm.crm_leads_common import (
    _invalidate_crm_cache,
    _svc_execute_bulk_assign,
    _svc_get_bulk_assign_candidates,
)
from backend.crm.schemas_common import CRMBulkAssignExecuteIn, CRMBulkAutoAssignConfigIn
from backend.utils import DB_SCHEMA, get_db_pool

logger = logging.getLogger(__name__)

_SYSTEM_ADMIN_USER = {"role": "ADMIN", "emp_id": 1}


def _table_exists_error(exc: Exception) -> bool:
    return isinstance(exc, asyncpg.UndefinedTableError)


def _row_to_rule(row: asyncpg.Record) -> Dict[str, Any]:
    filters = row["filters"]
    if isinstance(filters, str):
        filters = json.loads(filters)
    rr = row["rr_state"]
    if isinstance(rr, str):
        rr = json.loads(rr)
    rm_users = row["selected_rm_usernames"]
    if isinstance(rm_users, str):
        rm_users = json.loads(rm_users)
    op_users = row["selected_op_usernames"]
    if isinstance(op_users, str):
        op_users = json.loads(op_users)
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "entity_type": row["entity_type"],
        "filters": filters or {},
        "assign_rm": bool(row["assign_rm"]),
        "assign_op": bool(row["assign_op"]),
        "selected_rm_usernames": rm_users or [],
        "selected_op_usernames": op_users or [],
        "per_employee_limit_rm": row["per_employee_limit_rm"],
        "per_employee_limit_op": row["per_employee_limit_op"],
        "assign_unassigned_only": bool(row["assign_unassigned_only"]),
        "interval_minutes": int(row["interval_minutes"]),
        "rr_state": rr or {"RM": 0, "OP": 0},
        "last_run_at": row["last_run_at"].isoformat() if row["last_run_at"] else None,
        "last_run_summary": None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _payload_to_db_fields(payload: CRMBulkAutoAssignConfigIn, *, updated_by: int) -> Dict[str, Any]:
    f = payload.filters
    entity_types = list(
        dict.fromkeys(
            [
                et.strip().upper()
                for et in ([payload.entity_type] + (f.entity_types or []))
                if isinstance(et, str) and et.strip()
            ]
        )
    )
    filters = {
        "stages": f.stages,
        "rm_ids": f.rm_ids,
        "op_ids": f.op_ids,
        "lead_types": f.lead_types,
        "ays": f.ays,
        "tags": f.tags,
        "lead_sources": f.lead_sources,
        "entity_types": entity_types,
        "follow_up_statuses": f.follow_up_statuses,
        "null_fields": f.null_fields,
        "not_null_fields": f.not_null_fields,
        "is_active": f.is_active,
        "match_mode": f.match_mode,
        "filter_mode": f.filter_mode,
        "limit": f.limit,
    }
    return {
        "name": (payload.name or "Scheduler").strip()[:120],
        "entity_type": (payload.entity_type or "").strip().upper(),
        "enabled": payload.enabled,
        "filters": json.dumps(filters),
        "assign_rm": payload.assign_rm,
        "assign_op": payload.assign_op,
        "selected_rm_usernames": json.dumps(payload.selected_rm_usernames or []),
        "selected_op_usernames": json.dumps(payload.selected_op_usernames or []),
        "per_employee_limit_rm": payload.per_employee_limit_rm,
        "per_employee_limit_op": payload.per_employee_limit_op,
        "assign_unassigned_only": payload.assign_unassigned_only,
        "interval_minutes": payload.interval_minutes,
        "updated_by": updated_by,
    }


async def _fetch_scheduler_row(conn, scheduler_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        f"""
        SELECT *
        FROM {DB_SCHEMA}.crm_bulk_assign_schedulers
        WHERE id = $1 AND is_active = TRUE
        """,
        scheduler_id,
    )


async def _fetch_scheduler_rows(
    conn: asyncpg.Connection,
    *,
    entity_type: Optional[str] = None,
) -> List[asyncpg.Record]:
    clauses = ["s.is_active = TRUE"]
    params: list = []
    if entity_type:
        params.append((entity_type or "").strip().upper())
        clauses.append(f"upper(trim(s.entity_type)) = ${len(params)}")
    where_sql = " AND ".join(clauses)
    return await conn.fetch(
        f"""
        SELECT s.*,
               (
                 SELECT l.summary
                 FROM {DB_SCHEMA}.crm_bulk_assign_logs l
                 WHERE l.scheduler_id = s.id
                 ORDER BY l.created_at DESC
                 LIMIT 1
               ) AS last_log_summary
        FROM {DB_SCHEMA}.crm_bulk_assign_schedulers s
        WHERE {where_sql}
        ORDER BY upper(trim(s.entity_type)), s.updated_at DESC, s.id DESC
        """,
        *params,
    )


def _rows_to_scheduler_items(rows: List[asyncpg.Record]) -> List[Dict[str, Any]]:
    items = []
    for row in rows:
        rule = _row_to_rule(row)
        ls = row.get("last_log_summary")
        if ls:
            if isinstance(ls, str):
                ls = json.loads(ls)
            rule["last_run_summary"] = ls
        items.append(rule)
    return items


async def svc_list_bulk_assign_schedulers(entity_type: Optional[str] = None) -> Dict[str, Any]:
    et = (entity_type or "").strip().upper() or None
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            rows = await _fetch_scheduler_rows(conn, entity_type=et)
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            return {"entity_type": et, "items": [], "storage_ready": False}
        raise HTTPException(status_code=500, detail="Database error.") from exc

    items = _rows_to_scheduler_items(rows)
    enabled_count = sum(1 for item in items if item.get("enabled"))
    return {
        "entity_type": et,
        "items": items,
        "total": len(items),
        "enabled_count": enabled_count,
        "storage_ready": True,
    }


async def svc_toggle_bulk_assign_scheduler_enabled(
    scheduler_id: int,
    *,
    enabled: bool,
    updated_by: int,
) -> Dict[str, Any]:
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            row = await _fetch_scheduler_row(conn, scheduler_id)
            if not row:
                raise HTTPException(status_code=404, detail="Scheduler not found.")
            if enabled:
                if not row["assign_rm"] and not row["assign_op"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Enable at least one of RM or OP assignment before turning the scheduler on.",
                    )
                rm_users = row["selected_rm_usernames"]
                if isinstance(rm_users, str):
                    rm_users = json.loads(rm_users)
                op_users = row["selected_op_usernames"]
                if isinstance(op_users, str):
                    op_users = json.loads(op_users)
                if row["assign_rm"] and not (rm_users or []):
                    raise HTTPException(
                        status_code=400,
                        detail="Select at least one RM before turning the scheduler on.",
                    )
                if row["assign_op"] and not (op_users or []):
                    raise HTTPException(
                        status_code=400,
                        detail="Select at least one OP before turning the scheduler on.",
                    )
            row = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.crm_bulk_assign_schedulers
                SET enabled = $2, updated_by = $3, updated_at = NOW()
                WHERE id = $1 AND is_active = TRUE
                RETURNING *
                """,
                scheduler_id,
                enabled,
                updated_by,
            )
    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            raise HTTPException(
                status_code=503,
                detail="Run scripts/crm_bulk_assign_scheduler.sql to enable schedulers and logs.",
            ) from exc
        raise HTTPException(status_code=500, detail="Database error.") from exc

    rule = _row_to_rule(row)
    return {"configured": True, **rule}


async def svc_get_bulk_assign_scheduler(scheduler_id: int) -> Dict[str, Any]:
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            row = await _fetch_scheduler_row(conn, scheduler_id)
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            raise HTTPException(
                status_code=503,
                detail="Run scripts/crm_bulk_assign_scheduler.sql to enable schedulers and logs.",
            ) from exc
        raise HTTPException(status_code=500, detail="Database error.") from exc
    if not row:
        raise HTTPException(status_code=404, detail="Scheduler not found.")
    rule = _row_to_rule(row)
    return {"configured": True, **rule}


async def svc_save_bulk_auto_assign_config(
    payload: CRMBulkAutoAssignConfigIn,
    *,
    updated_by: int,
) -> Dict[str, Any]:
    fields = _payload_to_db_fields(payload, updated_by=updated_by)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            if payload.id:
                existing = await _fetch_scheduler_row(conn, payload.id)
                if not existing:
                    raise HTTPException(status_code=404, detail="Scheduler not found.")
                rr = existing.get("rr_state")
                if isinstance(rr, str):
                    rr = json.loads(rr)
                rr = dict(rr or {"RM": 0, "OP": 0})
                old_rm = existing["selected_rm_usernames"]
                if isinstance(old_rm, str):
                    old_rm = json.loads(old_rm)
                old_op = existing["selected_op_usernames"]
                if isinstance(old_op, str):
                    old_op = json.loads(old_op)
                if list(old_rm or []) != list(payload.selected_rm_usernames or []):
                    rr["RM"] = 0
                if list(old_op or []) != list(payload.selected_op_usernames or []):
                    rr["OP"] = 0
                row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.crm_bulk_assign_schedulers
                    SET name = $2,
                        entity_type = $3,
                        enabled = $4,
                        filters = $5::jsonb,
                        assign_rm = $6,
                        assign_op = $7,
                        selected_rm_usernames = $8::jsonb,
                        selected_op_usernames = $9::jsonb,
                        per_employee_limit_rm = $10,
                        per_employee_limit_op = $11,
                        assign_unassigned_only = $12,
                        interval_minutes = $13,
                        rr_state = $14::jsonb,
                        updated_by = $15,
                        updated_at = NOW()
                    WHERE id = $1 AND is_active = TRUE
                    RETURNING *
                    """,
                    payload.id,
                    fields["name"],
                    fields["entity_type"],
                    fields["enabled"],
                    fields["filters"],
                    fields["assign_rm"],
                    fields["assign_op"],
                    fields["selected_rm_usernames"],
                    fields["selected_op_usernames"],
                    fields["per_employee_limit_rm"],
                    fields["per_employee_limit_op"],
                    fields["assign_unassigned_only"],
                    fields["interval_minutes"],
                    json.dumps(rr),
                    updated_by,
                )
            else:
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.crm_bulk_assign_schedulers (
                        name, entity_type, enabled, filters,
                        assign_rm, assign_op,
                        selected_rm_usernames, selected_op_usernames,
                        per_employee_limit_rm, per_employee_limit_op,
                        assign_unassigned_only, interval_minutes,
                        created_by, updated_by
                    ) VALUES (
                        $1, $2, $3, $4::jsonb,
                        $5, $6,
                        $7::jsonb, $8::jsonb,
                        $9, $10,
                        $11, $12,
                        $13, $13
                    )
                    RETURNING *
                    """,
                    fields["name"],
                    fields["entity_type"],
                    fields["enabled"],
                    fields["filters"],
                    fields["assign_rm"],
                    fields["assign_op"],
                    fields["selected_rm_usernames"],
                    fields["selected_op_usernames"],
                    fields["per_employee_limit_rm"],
                    fields["per_employee_limit_op"],
                    fields["assign_unassigned_only"],
                    fields["interval_minutes"],
                    updated_by,
                )
    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            raise HTTPException(
                status_code=503,
                detail="Run scripts/crm_bulk_assign_scheduler.sql to enable schedulers and logs.",
            ) from exc
        logger.exception("Failed to save bulk-assign scheduler")
        raise HTTPException(status_code=500, detail="Database error.") from exc

    rule = _row_to_rule(row)
    return {"configured": True, **rule}


async def svc_delete_bulk_assign_scheduler(scheduler_id: int, *, updated_by: int) -> Dict[str, Any]:
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.crm_bulk_assign_schedulers
                SET is_active = FALSE, enabled = FALSE, updated_by = $2, updated_at = NOW()
                WHERE id = $1 AND is_active = TRUE
                RETURNING id, name
                """,
                scheduler_id,
                updated_by,
            )
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            raise HTTPException(status_code=503, detail="Scheduler tables not installed.") from exc
        raise HTTPException(status_code=500, detail="Database error.") from exc
    if not row:
        raise HTTPException(status_code=404, detail="Scheduler not found.")
    return {"message": f"Scheduler '{row['name']}' removed.", "id": int(row["id"])}


def _role_assigned_count(roles: Dict[str, Any], role: str, summary: Dict[str, Any]) -> int:
    role_block = roles.get(role)
    if isinstance(role_block, dict) and role_block.get("total_assigned") is not None:
        return int(role_block["total_assigned"])
    if (summary.get("assignment_role") or "").strip().upper() == role:
        return int(summary.get("total_assigned") or 0)
    return int(summary.get(f"total_assigned_{role.lower()}") or 0)


def _assigned_roles_label(summary: Dict[str, Any]) -> str:
    roles = summary.get("roles") or {}
    labels = []
    for role in ("RM", "OP"):
        if _role_assigned_count(roles, role, summary) > 0:
            labels.append(role)
    if labels:
        return " + ".join(labels)
    ar = (summary.get("assignment_role") or "").strip().upper()
    return ar if ar in {"RM", "OP"} else "—"


async def insert_bulk_assign_log(
    *,
    run_type: str,
    entity_type: str,
    scheduler_id: Optional[int],
    triggered_by: Optional[int],
    summary: Dict[str, Any],
) -> None:
    # run_type reaches the column unmediated by any Pydantic model, and the value CHECK is
    # gone. required=True because the column is NOT NULL with no default -- a blank would
    # otherwise normalize to None and fail as a NotNullViolation deep in the INSERT below.
    try:
        run_type_norm = normalize_run_type(run_type, required=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    roles = summary.get("roles") or {}
    rm_n = _role_assigned_count(roles, "RM", summary)
    op_n = _role_assigned_count(roles, "OP", summary)
    matched = int(summary.get("candidates_matched") or summary.get("total_selected") or 0)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.crm_bulk_assign_logs (
                    scheduler_id, run_type, entity_type, triggered_by,
                    candidates_matched, total_assigned_rm, total_assigned_op, summary
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                scheduler_id,
                run_type_norm,
                (entity_type or "").strip().upper(),
                triggered_by,
                matched,
                rm_n,
                op_n,
                json.dumps(summary, default=str),
            )
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            logger.warning("crm_bulk_assign_logs table missing; skip log insert")
            return
        logger.exception("Failed to insert bulk-assign log")


async def svc_list_bulk_assign_logs(
    *,
    entity_type: Optional[str] = None,
    run_type: Optional[str] = None,
    scheduler_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    pool = await get_db_pool()
    clauses = ["TRUE"]
    params: list = []
    if entity_type:
        params.append((entity_type or "").strip().upper())
        clauses.append(f"upper(trim(l.entity_type)) = ${len(params)}")
    if run_type:
        try:
            params.append(normalize_run_type(run_type))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        clauses.append(f"l.run_type = ${len(params)}")
    if scheduler_id is not None:
        params.append(scheduler_id)
        clauses.append(f"l.scheduler_id = ${len(params)}")
    where_sql = " AND ".join(clauses)
    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM {DB_SCHEMA}.crm_bulk_assign_logs l WHERE {where_sql}",
                *params,
            )
            params.extend([limit, offset])
            rows = await conn.fetch(
                f"""
                SELECT l.*, s.name AS scheduler_name
                FROM {DB_SCHEMA}.crm_bulk_assign_logs l
                LEFT JOIN {DB_SCHEMA}.crm_bulk_assign_schedulers s ON s.id = l.scheduler_id
                WHERE {where_sql}
                ORDER BY l.created_at DESC
                LIMIT ${len(params) - 1} OFFSET ${len(params)}
                """,
                *params,
            )
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            return {"items": [], "total": 0, "limit": limit, "offset": offset, "storage_ready": False}
        raise HTTPException(status_code=500, detail="Database error.") from exc

    items = []
    for row in rows:
        sm = row["summary"]
        if isinstance(sm, str):
            sm = json.loads(sm)
        items.append(
            {
                "id": int(row["id"]),
                "scheduler_id": row["scheduler_id"],
                "scheduler_name": row.get("scheduler_name"),
                "run_type": row["run_type"],
                "entity_type": row["entity_type"],
                "triggered_by": row["triggered_by"],
                "candidates_matched": row["candidates_matched"],
                "total_assigned_rm": row["total_assigned_rm"],
                "total_assigned_op": row["total_assigned_op"],
                "assigned_roles": _assigned_roles_label(sm or {}),
                "summary": sm,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "storage_ready": True,
    }


def _lead_created_at_sort_key(row: Dict[str, Any]) -> tuple:
    """Oldest leads first — fair FIFO for auto-assign round-robin."""
    created_at = row.get("created_at")
    if created_at is None:
        created_ts = ""
    elif isinstance(created_at, datetime):
        created_ts = created_at.isoformat()
    else:
        created_ts = str(created_at)
    lead_id = row.get("id")
    return (created_ts, int(lead_id) if lead_id is not None else 0)


async def _fetch_matching_leads(rule: Dict[str, Any]) -> List[Dict[str, Any]]:
    f = rule.get("filters") or {}
    entity_types = f.get("entity_types") or [rule["entity_type"]]
    result = await _svc_get_bulk_assign_candidates(
        stages=f.get("stages") or None,
        rm_ids=f.get("rm_ids") or None,
        op_ids=f.get("op_ids") or None,
        lead_types=f.get("lead_types") or None,
        ays=f.get("ays") or None,
        tags=f.get("tags") or None,
        lead_sources=f.get("lead_sources") or None,
        entity_types=entity_types,
        follow_up_statuses=f.get("follow_up_statuses") or None,
        null_fields=f.get("null_fields") or None,
        not_null_fields=f.get("not_null_fields") or None,
        is_active=f.get("is_active"),
        match_mode=f.get("match_mode") or "AND",
        filter_mode=f.get("filter_mode") or "IN",
        limit=int(f.get("limit") or 500),
        offset=0,
        current_user=_SYSTEM_ADMIN_USER,
    )
    items = result.get("items") or []
    items.sort(key=_lead_created_at_sort_key)
    return items


async def _execute_role_assign(
    lead_ids: List[int],
    *,
    assignment_role: str,
    usernames: List[str],
    per_employee_limit: Optional[int],
    round_robin_start_index: int = 0,
) -> Dict[str, Any]:
    if not lead_ids:
        return {
            "assignment_role": assignment_role,
            "total_selected": 0,
            "total_assigned": 0,
            "per_employee_counts": {},
            "round_robin_next_index": int(round_robin_start_index or 0),
        }
    payload = CRMBulkAssignExecuteIn(
        lead_ids=lead_ids,
        selected_usernames=usernames,
        assignment_role=assignment_role,
        per_employee_limit=per_employee_limit,
        round_robin_start_index=int(round_robin_start_index or 0),
    )
    return await _svc_execute_bulk_assign(payload=payload, current_user=_SYSTEM_ADMIN_USER)


def _filter_leads_for_role(leads: List[Dict[str, Any]], role: str, unassigned_only: bool) -> List[int]:
    ids: List[int] = []
    for row in leads:
        lid = row.get("id")
        if lid is None:
            continue
        if unassigned_only:
            if role == "RM" and row.get("rm_id") is not None:
                continue
            if role == "OP" and row.get("op_id") is not None:
                continue
        ids.append(int(lid))
    return ids


async def run_auto_assign_scheduler(scheduler_id: int, *, force: bool = False) -> Optional[Dict[str, Any]]:
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            row = await _fetch_scheduler_row(conn, scheduler_id)
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            return None
        raise

    if not row or not row["enabled"]:
        return None

    rule = _row_to_rule(row)
    now = datetime.now(timezone.utc)
    interval = int(row["interval_minutes"] or 5)

    # Atomically CLAIM this run. Two overlapping scheduler ticks (a slow run
    # overlapping the next tick, or the scheduler active on more than one
    # worker) must not both pass the interval gate and double-assign the same
    # leads. This conditional UPDATE — which advances last_run_at only if the
    # interval has elapsed — succeeds for exactly one runner; everyone else
    # gets no row back and bails. `force` skips the claim for manual runs.
    if not force:
        async with pool.acquire() as conn:
            claimed = await conn.fetchval(
                f"""
                UPDATE {DB_SCHEMA}.crm_bulk_assign_schedulers
                SET last_run_at = $2,
                    updated_at = NOW()
                WHERE id = $1
                  AND enabled = TRUE
                  AND (
                        last_run_at IS NULL
                        OR last_run_at <= $2 - ($3 * INTERVAL '1 minute')
                      )
                RETURNING id
                """,
                scheduler_id,
                now,
                interval,
            )
        if not claimed:
            return None

    leads = await _fetch_matching_leads(rule)
    unassigned_only = bool(rule.get("assign_unassigned_only", True))
    rr_state = rule.get("rr_state") or {"RM": 0, "OP": 0}
    next_rr_state = dict(rr_state)
    summary: Dict[str, Any] = {
        "scheduler_id": scheduler_id,
        "scheduler_name": rule.get("name"),
        "entity_type": rule["entity_type"],
        "candidates_matched": len(leads),
        "roles": {},
        "rr_state_before": rr_state,
        "ran_at": now.isoformat(),
    }

    try:
        if rule.get("assign_rm") and rule.get("selected_rm_usernames"):
            rm_ids = _filter_leads_for_role(leads, "RM", unassigned_only)
            rm_result = await _execute_role_assign(
                rm_ids,
                assignment_role="RM",
                usernames=list(rule["selected_rm_usernames"]),
                per_employee_limit=rule.get("per_employee_limit_rm"),
                round_robin_start_index=int(rr_state.get("RM") or 0),
            )
            summary["roles"]["RM"] = rm_result
            next_rr_state["RM"] = int(rm_result.get("round_robin_next_index") or 0)
        if rule.get("assign_op") and rule.get("selected_op_usernames"):
            op_ids = _filter_leads_for_role(leads, "OP", unassigned_only)
            op_result = await _execute_role_assign(
                op_ids,
                assignment_role="OP",
                usernames=list(rule["selected_op_usernames"]),
                per_employee_limit=rule.get("per_employee_limit_op"),
                round_robin_start_index=int(rr_state.get("OP") or 0),
            )
            summary["roles"]["OP"] = op_result
            next_rr_state["OP"] = int(op_result.get("round_robin_next_index") or 0)
        summary["rr_state_after"] = next_rr_state
    except HTTPException:
        raise
    except Exception:
        logger.exception("CRM auto bulk-assign failed scheduler_id=%s", scheduler_id)
        summary["error"] = "assignment_failed"
    else:
        await _invalidate_crm_cache()

    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.crm_bulk_assign_schedulers
            SET last_run_at = $2,
                rr_state = $3::jsonb,
                updated_at = NOW()
            WHERE id = $1
            """,
            scheduler_id,
            now,
            json.dumps(next_rr_state),
        )

    await insert_bulk_assign_log(
        run_type="AUTO",
        entity_type=rule["entity_type"],
        scheduler_id=scheduler_id,
        triggered_by=None,
        summary=summary,
    )
    logger.info("CRM auto bulk-assign scheduler %s: %s", scheduler_id, summary)
    return summary


async def run_auto_assign_for_rule(entity_type: str, *, force: bool = False) -> Optional[Dict[str, Any]]:
    """Legacy: run first enabled scheduler for entity_type, or by id via new API."""
    et = (entity_type or "").strip().upper()
    listed = await svc_list_bulk_assign_schedulers(et)
    for item in listed.get("items") or []:
        if item.get("enabled"):
            return await run_auto_assign_scheduler(int(item["id"]), force=force)
    return None


async def run_due_crm_bulk_auto_assign_jobs() -> int:
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, last_run_at, interval_minutes
                FROM {DB_SCHEMA}.crm_bulk_assign_schedulers
                WHERE is_active = TRUE AND enabled = TRUE
                """
            )
    except asyncpg.PostgresError as exc:
        if _table_exists_error(exc):
            return 0
        logger.exception("Failed to list due CRM bulk-assign schedulers")
        return 0

    now = datetime.now(timezone.utc)
    ran = 0
    for row in rows:
        sid = int(row["id"])
        interval = int(row["interval_minutes"] or 5)
        last_run_at = row["last_run_at"]
        due = True
        if last_run_at:
            lr = last_run_at.replace(tzinfo=timezone.utc) if last_run_at.tzinfo is None else last_run_at
            due = now - lr >= timedelta(minutes=interval)
        if due and await run_auto_assign_scheduler(sid, force=True):
            ran += 1
    return ran


# Backward-compatible single-config getters
async def svc_get_bulk_auto_assign_config(entity_type: str) -> Dict[str, Any]:
    listed = await svc_list_bulk_assign_schedulers(entity_type)
    if not listed.get("storage_ready"):
        return {
            "entity_type": (entity_type or "").strip().upper(),
            "enabled": False,
            "configured": False,
            "storage_ready": False,
        }
    items = listed.get("items") or []
    if not items:
        return {
            "entity_type": (entity_type or "").strip().upper(),
            "enabled": False,
            "configured": False,
            "storage_ready": True,
            "schedulers": [],
        }
    first = items[0]
    return {"configured": True, "storage_ready": True, "schedulers": items, **first}
