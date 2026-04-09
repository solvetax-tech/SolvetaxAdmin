import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.crm.schemas import CRMCallUpdateIn, CRMLeadEditIn
from app.logger import logger
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/crm/leads", tags=["CRM Leads"])

IST = ZoneInfo("Asia/Kolkata")

FIRST_PITCH_ALLOWED_STAGES = {"FRESH_LEAD", "PENDING_REGISTRATION_DATA", "FOLLOW_UP", "INTERESTED"}
FINAL_PITCH_ALLOWED_STAGES = {"GST_REGISTRATION_DONE", "SCHEDULED_PAYMENTS"}
CLOSED_STAGES = {"SUBSCRIBED", "NOT_INTERESTED"}
ALL_STAGES = FIRST_PITCH_ALLOWED_STAGES | FINAL_PITCH_ALLOWED_STAGES | CLOSED_STAGES

FIRST_PITCH_CONNECTED = {"CONNECTED_AND_SCHEDULED", "CALL_BACK"}
FINAL_PITCH_CONNECTED = {"SCHEDULED_PAYMENT", "SUBSCRIBED_COMPLETED"}


def _normalize_code(value: str) -> str:
    return value.strip().upper()


def _validation_error(message: str, fields: Optional[dict] = None) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": {"type": "validation_error", "message": message, "fields": fields or {}}},
    )


def _get_user_context(current_user):
    role = (current_user.get("role") or "").strip().upper()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else 0
    return role, emp_id


def _build_crm_visibility(role: str, emp_id: int, idx: int):
    if role == "ADMIN":
        return None, [], idx
    if role == "RM":
        return f"l.rm_id = ${idx}", [emp_id], idx + 1
    if role == "OP":
        return f"l.op_id = ${idx}", [emp_id], idx + 1
    if role in {"SALES_MANAGER", "OP_MANAGER"}:
        sql = f"""
        (
            l.rm_id IN (
                SELECT tm.emp_id
                FROM {DB_SCHEMA}.team_members tm
                JOIN {DB_SCHEMA}.team_managers mg ON tm.team_id = mg.team_id
                WHERE mg.manager_emp_id = ${idx}
            )
            OR
            l.op_id IN (
                SELECT tm.emp_id
                FROM {DB_SCHEMA}.team_members tm
                JOIN {DB_SCHEMA}.team_managers mg ON tm.team_id = mg.team_id
                WHERE mg.manager_emp_id = ${idx}
            )
        )
        """
        return sql, [emp_id], idx + 1
    return None, [], idx


def _transition_stage(call_type_code: str, call_status_code: str) -> Optional[str]:
    if call_type_code == "FIRST_PITCH_CALL":
        if call_status_code in {"CALL_BUSY", "CALL_BACK"}:
            return "FOLLOW_UP"
        if call_status_code == "CONNECTED_AND_SCHEDULED":
            return "INTERESTED"
        if call_status_code == "NOT_INTERESTED":
            return "NOT_INTERESTED"
        if call_status_code in {"CALL_NOT_ANSWERED", "CALL_NOT_CONNECTED"}:
            return None
        raise _validation_error(
            "Invalid status for first pitch.",
            {"call_status_code": f"{call_status_code} is not allowed in FIRST_PITCH_CALL."},
        )

    if call_type_code == "FINAL_PITCH_CALL":
        if call_status_code == "SCHEDULED_PAYMENT":
            return "SCHEDULED_PAYMENTS"
        if call_status_code == "SUBSCRIBED_COMPLETED":
            return "SUBSCRIBED"
        if call_status_code == "NOT_INTERESTED":
            raise _validation_error(
                "Invalid status for final pitch.",
                {"call_status_code": "NOT_INTERESTED is not allowed in FINAL_PITCH_CALL."},
            )
        if call_status_code in {"CALL_NOT_ANSWERED", "CALL_NOT_CONNECTED", "CALL_BUSY", "CALL_BACK", "CONNECTED_AND_SCHEDULED"}:
            return None
        raise _validation_error(
            "Invalid status for final pitch.",
            {"call_status_code": f"{call_status_code} is not allowed in FINAL_PITCH_CALL."},
        )

    raise _validation_error("Unsupported call type.", {"call_type_code": call_type_code})


async def _validate_call_config(conn: asyncpg.Connection, call_type_code: str, call_status_code: str) -> None:
    type_exists = await conn.fetchval(
        f"SELECT 1 FROM {DB_SCHEMA}.crm_call_types WHERE code = $1 AND is_active = TRUE LIMIT 1",
        call_type_code,
    )
    if not type_exists:
        raise _validation_error("Invalid call type.", {"call_type_code": f"{call_type_code} is invalid/inactive."})

    status_exists = await conn.fetchval(
        f"SELECT 1 FROM {DB_SCHEMA}.crm_call_statuses WHERE code = $1 AND is_active = TRUE LIMIT 1",
        call_status_code,
    )
    if not status_exists:
        raise _validation_error("Invalid call status.", {"call_status_code": f"{call_status_code} is invalid/inactive."})


@router.get("/{lead_id:int}", summary="Get CRM lead by id")
async def get_crm_lead(lead_id: int, current_user=Depends(require_permission("EMPLOYEE", "CRM"))):
    role, emp_id = _get_user_context(current_user)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            params = [lead_id]
            where = ["l.id = $1"]
            vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, 2)
            if vis_sql:
                where.append(vis_sql)
                params.extend(vis_vals)

            row = await conn.fetchrow(
                f"SELECT l.* FROM {DB_SCHEMA}.crm_leads l WHERE {' AND '.join(where)}",
                *params,
            )
            if not row:
                raise HTTPException(status_code=404, detail="CRM lead not found.")
            return dict(row)
    except asyncpg.PostgresError:
        logger.exception("Database error while fetching CRM lead")
        raise HTTPException(status_code=500, detail="Database error.")


@router.get("/filter", summary="Filter CRM leads")
async def filter_crm_leads(
    stage: Optional[str] = None,
    mobile: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _get_user_context(current_user)
    if stage:
        stage = _normalize_code(stage)
        if stage not in ALL_STAGES:
            raise _validation_error("Invalid stage filter.", {"stage": "Unsupported stage value."})
    if mobile:
        m = mobile.strip()
        if not m.isdigit() or len(m) != 10:
            raise _validation_error("Invalid mobile filter.", {"mobile": "Must be a 10-digit number."})
        mobile = m

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            where = ["TRUE"]
            params = []
            if stage:
                params.append(stage)
                where.append(f"l.stage = ${len(params)}")
            if mobile:
                params.append(mobile)
                where.append(f"l.mobile = ${len(params)}")
            if rm_id is not None:
                params.append(rm_id)
                where.append(f"l.rm_id = ${len(params)}")
            if op_id is not None:
                params.append(op_id)
                where.append(f"l.op_id = ${len(params)}")
            if is_active is not None:
                params.append(is_active)
                where.append(f"l.is_active = ${len(params)}")

            vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, len(params) + 1)
            if vis_sql:
                where.append(vis_sql)
                params.extend(vis_vals)

            count_params = list(params)
            params.extend([limit, offset])
            count_sql = f"SELECT COUNT(*) FROM {DB_SCHEMA}.crm_leads l WHERE {' AND '.join(where)}"
            list_sql = f"""
                SELECT l.*
                FROM {DB_SCHEMA}.crm_leads l
                WHERE {' AND '.join(where)}
                ORDER BY l.updated_at DESC, l.id DESC
                LIMIT ${len(params)-1} OFFSET ${len(params)}
            """
            total = await conn.fetchval(count_sql, *count_params)
            rows = await conn.fetch(list_sql, *params)
            return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}
    except asyncpg.PostgresError:
        logger.exception("Database error while filtering CRM leads")
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{lead_id:int}/edit", summary="Edit CRM lead")
async def edit_crm_lead(
    lead_id: int,
    payload: CRMLeadEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    role = (current_user.get("role") or "").strip().upper()
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only ADMIN can edit CRM leads directly.")

    update_data = payload.model_dump(exclude_unset=True)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                old_row = await conn.fetchrow(
                    f"SELECT * FROM {DB_SCHEMA}.crm_leads WHERE id = $1 FOR UPDATE",
                    lead_id,
                )
                if not old_row:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")
                if old_row["stage"] in CLOSED_STAGES and "stage" in update_data:
                    raise _validation_error(
                        "Closed lead stage cannot be changed.",
                        {"stage": f"Lead is closed in {old_row['stage']}."},
                    )
                if "followup_at" in update_data and update_data["followup_at"] is not None:
                    if update_data["followup_at"] <= datetime.now(IST):
                        raise _validation_error("Invalid followup datetime.", {"followup_at": "Must be a future datetime."})

                fields, values, idx = [], [], 1
                for key, value in update_data.items():
                    fields.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
                fields.append("updated_at = NOW()")
                values.append(lead_id)

                new_row = await conn.fetchrow(
                    f"UPDATE {DB_SCHEMA}.crm_leads SET {', '.join(fields)} WHERE id = ${idx} RETURNING *",
                    *values,
                )
                return {"message": "CRM lead updated successfully.", "lead": dict(new_row)}
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise _validation_error("Invalid foreign key reference.", {"rm_id/op_id": "Referenced employee not found."})
    except asyncpg.exceptions.CheckViolationError as e:
        raise _validation_error("Constraint validation failed.", {"constraint": getattr(e, "constraint_name", "unknown")})
    except asyncpg.PostgresError:
        logger.exception("Database error while editing CRM lead")
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{lead_id:int}/activate", summary="Activate CRM lead")
async def activate_crm_lead(lead_id: int, current_user=Depends(require_permission("EMPLOYEE", "DELETE"))):
    del current_user
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval(f"SELECT 1 FROM {DB_SCHEMA}.crm_leads WHERE id = $1", lead_id)
            if not exists:
                raise HTTPException(status_code=404, detail="CRM lead not found.")
            row = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.crm_leads
                SET is_active = TRUE, updated_at = NOW()
                WHERE id = $1 AND is_active = FALSE
                RETURNING *
                """,
                lead_id,
            )
            if not row:
                raise _validation_error("CRM lead already active.")
            return {"message": "CRM lead activated.", "lead": dict(row)}
    except asyncpg.PostgresError:
        logger.exception("Database error while activating CRM lead")
        raise HTTPException(status_code=500, detail="Database error.")


@router.delete("/{lead_id:int}/deactivate", summary="Deactivate CRM lead")
async def deactivate_crm_lead(lead_id: int, current_user=Depends(require_permission("EMPLOYEE", "DELETE"))):
    del current_user
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval(f"SELECT 1 FROM {DB_SCHEMA}.crm_leads WHERE id = $1", lead_id)
            if not exists:
                raise HTTPException(status_code=404, detail="CRM lead not found.")
            row = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.crm_leads
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = $1 AND is_active = TRUE
                RETURNING *
                """,
                lead_id,
            )
            if not row:
                raise _validation_error("CRM lead already inactive.")
            return {"message": "CRM lead deactivated.", "lead": dict(row)}
    except asyncpg.PostgresError:
        logger.exception("Database error while deactivating CRM lead")
        raise HTTPException(status_code=500, detail="Database error.")


@router.get("/{lead_id:int}/activities", summary="Get CRM lead activities")
async def list_crm_activities(
    lead_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "CRM")),
):
    role, emp_id = _get_user_context(current_user)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            where = ["l.id = $1"]
            params = [lead_id]
            vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, 2)
            if vis_sql:
                where.append(vis_sql)
                params.extend(vis_vals)

            lead_exists = await conn.fetchval(
                f"SELECT 1 FROM {DB_SCHEMA}.crm_leads l WHERE {' AND '.join(where)}",
                *params,
            )
            if not lead_exists:
                raise HTTPException(status_code=404, detail="CRM lead not found.")

            rows = await conn.fetch(
                f"""
                SELECT a.*
                FROM {DB_SCHEMA}.crm_activities a
                WHERE a.lead_id = $1
                ORDER BY a.performed_at DESC, a.id DESC
                LIMIT $2 OFFSET $3
                """,
                lead_id,
                limit,
                offset,
            )
            return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset}
    except asyncpg.PostgresError:
        logger.exception("Database error while fetching CRM activities")
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{lead_id:int}/call-update", status_code=status.HTTP_200_OK, summary="Update call status and apply CRM transitions")
async def update_crm_call(
    lead_id: int,
    payload: CRMCallUpdateIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    role = (current_user.get("role") or "").strip().upper()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    if role in {"RM", "OP"} and emp_id is None:
        raise _validation_error("Invalid user context.", {"emp_id": "Missing employee id in token."})
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id, "api": "crm_call_update"})

    call_type_code = _normalize_code(payload.call_type_code)
    call_status_code = _normalize_code(payload.call_status_code)

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _validate_call_config(conn, call_type_code, call_status_code)

                lead = await conn.fetchrow(
                    f"SELECT * FROM {DB_SCHEMA}.crm_leads WHERE id = $1 FOR UPDATE",
                    lead_id,
                )
                if not lead:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")
                if not lead["is_active"]:
                    raise _validation_error("Inactive lead cannot be updated via call flow.")

                current_stage = lead["stage"]
                if current_stage in CLOSED_STAGES:
                    raise _validation_error(
                        "Lead is closed; stage updates are not allowed.",
                        {"stage": f"Current stage is {current_stage}."},
                    )
                if call_type_code == "FIRST_PITCH_CALL" and current_stage not in FIRST_PITCH_ALLOWED_STAGES:
                    raise _validation_error(
                        "Invalid stage for first pitch.",
                        {"stage": f"{current_stage} is not allowed for FIRST_PITCH_CALL."},
                    )
                if call_type_code == "FINAL_PITCH_CALL" and current_stage not in FINAL_PITCH_ALLOWED_STAGES:
                    raise _validation_error(
                        "Invalid stage for final pitch.",
                        {"stage": f"{current_stage} is not allowed for FINAL_PITCH_CALL."},
                    )

                if payload.followup_at is not None and payload.followup_at <= datetime.now(IST):
                    raise _validation_error("Invalid followup datetime.", {"followup_at": "Must be a future datetime."})
                if call_status_code in {"CALL_BACK", "SCHEDULED_PAYMENT"} and payload.followup_at is None:
                    raise _validation_error("followup_at is required.", {"followup_at": f"Required for {call_status_code}."})

                target_stage = _transition_stage(call_type_code, call_status_code)
                connected_inc = int(
                    (call_type_code == "FIRST_PITCH_CALL" and call_status_code in FIRST_PITCH_CONNECTED)
                    or (call_type_code == "FINAL_PITCH_CALL" and call_status_code in FINAL_PITCH_CONNECTED)
                )
                new_stage = target_stage or current_stage

                updated = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.crm_leads
                    SET stage = $1,
                        call_attempted_count = call_attempted_count + 1,
                        call_connected_count = call_connected_count + $2,
                        last_dailed_at = NOW(),
                        followup_at = COALESCE($3, followup_at),
                        remarks = COALESCE($4, remarks),
                        rm_id = CASE WHEN $6 = 'RM' THEN $7 ELSE rm_id END,
                        op_id = CASE WHEN $6 = 'OP' THEN $7 ELSE op_id END,
                        updated_at = NOW()
                    WHERE id = $5
                    RETURNING *
                    """,
                    new_stage,
                    connected_inc,
                    payload.followup_at,
                    payload.remarks,
                    lead_id,
                    role,
                    emp_id,
                )

                activity_id = await conn.fetchval(
                    f"""
                    INSERT INTO {DB_SCHEMA}.crm_activities (
                        lead_id, activity_type, call_type_code, call_status_code,
                        old_stage, new_stage, followup_at, remarks, performed_by, performed_at, created_at
                    )
                    VALUES ($1, 'CALL', $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
                    RETURNING id
                    """,
                    lead_id,
                    call_type_code,
                    call_status_code,
                    current_stage,
                    new_stage,
                    payload.followup_at,
                    payload.remarks,
                    emp_id,
                )

                log.info(
                    "CRM call updated | lead_id=%s old_stage=%s new_stage=%s type=%s status=%s",
                    lead_id,
                    current_stage,
                    new_stage,
                    call_type_code,
                    call_status_code,
                )

                return {
                    "message": "Call update applied",
                    "lead_id": lead_id,
                    "old_stage": current_stage,
                    "new_stage": new_stage,
                    "call_attempted_count": updated["call_attempted_count"],
                    "call_connected_count": updated["call_connected_count"],
                    "last_dailed_at": updated["last_dailed_at"],
                    "followup_at": updated["followup_at"],
                    "activity_id": activity_id,
                }
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise _validation_error("Invalid foreign key reference.", {"performed_by": "Employee reference invalid."})
    except asyncpg.exceptions.CheckViolationError as e:
        raise _validation_error("Constraint validation failed.", {"constraint": getattr(e, "constraint_name", "unknown")})
    except asyncpg.PostgresError:
        logger.exception("Database error while applying CRM call update")
        raise HTTPException(status_code=500, detail="Database error.")
