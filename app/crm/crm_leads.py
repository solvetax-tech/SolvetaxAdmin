import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.crm.schemas import (
    CRMCallUpdateIn,
    CRMFollowupStatusUpdateIn,
    CRMLeadEditIn,
    CRMLeadStagesOut,
    CRMLeadStageItem,
    CRMUIMappingsOut,
    CRMUIPitchStatusItem,
    CRMUIStagePitchItem,
)
from app.logger import logger
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/crm/leads", tags=["CRM Leads"])

IST = ZoneInfo("Asia/Kolkata")

FIRST_PITCH_ALLOWED_STAGES = {"FRESH_LEAD", "FOLLOW_UP", "INTERESTED"}
FINAL_PITCH_ALLOWED_STAGES = {"GST_REGISTRATION_DONE", "SCHEDULED_PAYMENTS"}
CLOSED_STAGES = {"SUBSCRIBED", "NOT_INTERESTED"}
ALL_STAGES = (
    FIRST_PITCH_ALLOWED_STAGES
    | {"PENDING_REGISTRATION_DATA"}
    | FINAL_PITCH_ALLOWED_STAGES
    | CLOSED_STAGES
)

FIRST_PITCH_STATUSES_FALLBACK = frozenset(
    {
        "CALL_NOT_ANSWERED",
        "CALL_NOT_CONNECTED",
        "CALL_BUSY",
        "CALL_BACK",
        "CONNECTED_AND_SCHEDULED",
        "SEND_DOCS",
        "NOT_INTERESTED",
    }
)
FINAL_PITCH_STATUSES_FALLBACK = frozenset(
    {
        "CALL_NOT_ANSWERED",
        "CALL_NOT_CONNECTED",
        "CALL_BUSY",
        "CALL_BACK",
        "SCHEDULED_PAYMENT",
    }
)

FIRST_PITCH_CONNECTED = {"CONNECTED_AND_SCHEDULED", "CALL_BACK"}
FINAL_PITCH_CONNECTED = {"SCHEDULED_PAYMENT", "CALL_BACK"}
FOLLOWUP_STATUSES = {"PENDING", "COMPLETED", "MISSED"}

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
    # Roles without CRM row scope must not see or mutate leads via these APIs
    return "FALSE", [], idx


def _performed_by_emp_id(emp_id: int) -> Optional[int]:
    """Avoid inserting performed_by=0 (invalid FK); ADMIN may have no numeric emp in token."""
    return emp_id if emp_id > 0 else None


def _require_crm_row_context(role: str, emp_id: int) -> None:
    """RM/OP/managers need a positive emp_id so visibility predicates are meaningful."""
    if role == "ADMIN":
        return
    if role in {"RM", "OP", "SALES_MANAGER", "OP_MANAGER"} and emp_id <= 0:
        raise HTTPException(
            status_code=403,
            detail="Valid employee context is required for CRM lead access.",
        )


async def _fetch_crm_lead_visible(
    conn: asyncpg.Connection,
    role: str,
    emp_id: int,
    lead_id: int,
    *,
    for_update: bool = False,
) -> Optional[asyncpg.Record]:
    """Single-lead fetch with the same visibility rules as list/filter (404 if not visible)."""
    params: list = [lead_id]
    where = ["l.id = $1"]
    vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, 2)
    if vis_sql:
        where.append(vis_sql)
        params.extend(vis_vals)
    lock = " FOR UPDATE" if for_update else ""
    return await conn.fetchrow(
        f"SELECT l.* FROM {DB_SCHEMA}.crm_leads l WHERE {' AND '.join(where)}{lock}",
        *params,
    )


async def _fetch_valid_stage_codes(conn: asyncpg.Connection) -> set[str]:
    """Active stage codes from crm_lead_stages, or in-code ALL_STAGES if table missing/empty."""
    try:
        rows = await conn.fetch(
            f"""
            SELECT code FROM {DB_SCHEMA}.crm_lead_stages
            WHERE is_active
            ORDER BY sort_order
            """
        )
        if rows:
            return {r["code"] for r in rows}
    except asyncpg.UndefinedTableError:
        pass
    return set(ALL_STAGES)


def _transition_stage(call_type_code: str, call_status_code: str) -> Optional[str]:
    if call_type_code == "FIRST_PITCH_CALL":
        if call_status_code == "SEND_DOCS":
            return "PENDING_REGISTRATION_DATA"
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
        if call_status_code == "NOT_INTERESTED":
            raise _validation_error(
                "Invalid status for final pitch.",
                {"call_status_code": "NOT_INTERESTED is not allowed in FINAL_PITCH_CALL."},
            )
        if call_status_code in {"CALL_NOT_ANSWERED", "CALL_NOT_CONNECTED", "CALL_BUSY", "CALL_BACK"}:
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


async def _validate_crm_call_against_mappings(
    conn: asyncpg.Connection,
    current_stage: str,
    call_type_code: str,
    call_status_code: str,
) -> None:
    try:
        has_stage_map = await conn.fetchval(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {DB_SCHEMA}.crm_ui_mappings
                WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active
            )
            """
        )
        has_status_map = await conn.fetchval(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {DB_SCHEMA}.crm_ui_mappings
                WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active
            )
            """
        )
    except asyncpg.UndefinedTableError:
        has_stage_map = False
        has_status_map = False

    if has_stage_map:
        expected_pitch = await conn.fetchval(
            f"""
            SELECT pitch_type_code FROM {DB_SCHEMA}.crm_ui_mappings
            WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active AND stage = $1
            ORDER BY sort_order
            LIMIT 1
            """,
            current_stage,
        )
        if expected_pitch is None:
            raise _validation_error(
                "Stage is not configured for call updates.",
                {"stage": f"{current_stage} has no pitch mapping."},
            )
        if call_type_code != expected_pitch:
            raise _validation_error(
                "Call type does not match stage.",
                {
                    "call_type_code": (
                        f"Expected {expected_pitch} for stage {current_stage}, got {call_type_code}."
                    ),
                },
            )
    else:
        if call_type_code not in {"FIRST_PITCH_CALL", "FINAL_PITCH_CALL"}:
            raise _validation_error(
                "Unsupported call type.",
                {"call_type_code": call_type_code},
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

    if has_status_map:
        allowed_rows = await conn.fetch(
            f"""
            SELECT call_status_code FROM {DB_SCHEMA}.crm_ui_mappings
            WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active AND pitch_type_code = $1
            ORDER BY sort_order
            """,
            call_type_code,
        )
        codes = {r["call_status_code"] for r in allowed_rows}
        if not codes:
            raise _validation_error(
                "Pitch has no allowed call statuses configured.",
                {"call_type_code": call_type_code},
            )
        if call_status_code not in codes:
            raise _validation_error(
                "Invalid status for this pitch.",
                {"call_status_code": f"{call_status_code} is not allowed for {call_type_code}."},
            )
    else:
        if call_type_code == "FIRST_PITCH_CALL":
            if call_status_code not in FIRST_PITCH_STATUSES_FALLBACK:
                raise _validation_error(
                    "Invalid status for first pitch.",
                    {"call_status_code": f"{call_status_code} is not allowed in FIRST_PITCH_CALL."},
                )
        elif call_type_code == "FINAL_PITCH_CALL":
            if call_status_code not in FINAL_PITCH_STATUSES_FALLBACK:
                raise _validation_error(
                    "Invalid status for final pitch.",
                    {"call_status_code": f"{call_status_code} is not allowed in FINAL_PITCH_CALL."},
                )
        else:
            raise _validation_error(
                "Unsupported call type.",
                {"call_type_code": call_type_code},
            )


@router.get("/ui-mappings", summary="CRM stage/pitch and pitch/status mappings for UI")
async def get_crm_ui_mappings(current_user=Depends(require_permission("EMPLOYEE", "READ"))) -> CRMUIMappingsOut:
    _get_user_context(current_user)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            stage_rows = await conn.fetch(
                f"""
                SELECT stage, pitch_type_code, sort_order
                FROM {DB_SCHEMA}.crm_ui_mappings
                WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active
                ORDER BY sort_order, stage
                """
            )
            status_rows = await conn.fetch(
                f"""
                SELECT pitch_type_code, call_status_code, sort_order
                FROM {DB_SCHEMA}.crm_ui_mappings
                WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active
                ORDER BY pitch_type_code, sort_order, call_status_code
                """
            )
    except asyncpg.UndefinedTableError:
        logger.exception("crm_ui_mappings table missing; run docs/64-crm-ui-mappings.sql")
        raise HTTPException(status_code=500, detail="CRM UI mappings are not available.")
    except asyncpg.PostgresError:
        logger.exception("Database error while loading CRM UI mappings")
        raise HTTPException(status_code=500, detail="Database error.")

    pitch_to_statuses: dict[str, list[CRMUIPitchStatusItem]] = {}
    for r in status_rows:
        pitch = r["pitch_type_code"]
        pitch_to_statuses.setdefault(pitch, []).append(
            CRMUIPitchStatusItem(
                call_status_code=r["call_status_code"],
                sort_order=r["sort_order"],
            )
        )

    return CRMUIMappingsOut(
        stage_to_pitch=[
            CRMUIStagePitchItem(
                stage=row["stage"],
                pitch_type_code=row["pitch_type_code"],
                sort_order=row["sort_order"],
            )
            for row in stage_rows
        ],
        pitch_to_statuses=pitch_to_statuses,
    )


@router.get("/filter", summary="Filter CRM leads")
async def filter_crm_leads(
    stage: Optional[str] = None,
    follow_up_status: Optional[str] = None,
    mobile: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    if stage:
        stage = _normalize_code(stage)
    if follow_up_status:
        follow_up_status = _normalize_code(follow_up_status)
        if follow_up_status not in FOLLOWUP_STATUSES:
            raise _validation_error(
                "Invalid follow_up_status filter.",
                {"follow_up_status": "Unsupported follow-up status value."},
            )
    if mobile:
        m = mobile.strip()
        if not m.isdigit() or len(m) != 10:
            raise _validation_error("Invalid mobile filter.", {"mobile": "Must be a 10-digit number."})
        mobile = m

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            if stage:
                valid_stages = await _fetch_valid_stage_codes(conn)
                if stage not in valid_stages:
                    raise _validation_error(
                        "Invalid stage filter.",
                        {"stage": "Unsupported stage value."},
                    )
            where = ["TRUE"]
            params = []
            if stage:
                params.append(stage)
                where.append(f"l.stage = ${len(params)}")
            if follow_up_status:
                params.append(follow_up_status)
                where.append(f"l.follow_up_status = ${len(params)}")
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


@router.get("/activities/filter", summary="Filter CRM activities (visible leads only)")
async def filter_crm_activities(
    lead_id: Optional[int] = Query(None, ge=1),
    activity_type: Optional[str] = None,
    call_type_code: Optional[str] = None,
    call_status_code: Optional[str] = None,
    old_stage: Optional[str] = None,
    new_stage: Optional[str] = None,
    performed_by: Optional[int] = Query(None, gt=0),
    performed_at_from: Optional[datetime] = None,
    performed_at_to: Optional[datetime] = None,
    mobile: Optional[str] = None,
    lead_stage: Optional[str] = None,
    lead_is_active: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Lists `crm_activities` joined to `crm_leads` with the same row-level visibility as `GET /filter`.
    All query params are optional; combine as needed for the UI (timeline, RM dashboards, etc.).
    """
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)

    if activity_type is not None:
        activity_type = _normalize_code(activity_type)
        if not activity_type or len(activity_type) > 40:
            raise _validation_error(
                "Invalid activity_type filter.",
                {"activity_type": "Must be a non-empty code up to 40 characters."},
            )
    if call_type_code is not None:
        call_type_code = _normalize_code(call_type_code)
        if not call_type_code:
            raise _validation_error("Invalid call_type_code filter.", {"call_type_code": "Cannot be empty."})
    if call_status_code is not None:
        call_status_code = _normalize_code(call_status_code)
        if not call_status_code:
            raise _validation_error(
                "Invalid call_status_code filter.",
                {"call_status_code": "Cannot be empty."},
            )
    if old_stage is not None:
        old_stage = _normalize_code(old_stage)
        if not old_stage:
            raise _validation_error("Invalid old_stage filter.", {"old_stage": "Cannot be empty."})
    if new_stage is not None:
        new_stage = _normalize_code(new_stage)
        if not new_stage:
            raise _validation_error("Invalid new_stage filter.", {"new_stage": "Cannot be empty."})
    if lead_stage is not None:
        lead_stage = _normalize_code(lead_stage)
        if not lead_stage:
            raise _validation_error("Invalid lead_stage filter.", {"lead_stage": "Cannot be empty."})
    if mobile is not None:
        m = mobile.strip()
        if not m.isdigit() or len(m) != 10:
            raise _validation_error("Invalid mobile filter.", {"mobile": "Must be a 10-digit number."})
        mobile = m
    if (
        performed_at_from is not None
        and performed_at_to is not None
        and performed_at_from > performed_at_to
    ):
        raise _validation_error(
            "Invalid time range.",
            {"performed_at_from": "performed_at_from must be <= performed_at_to."},
        )

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            valid_stages = await _fetch_valid_stage_codes(conn)
            if lead_stage is not None and lead_stage not in valid_stages:
                raise _validation_error(
                    "Invalid lead_stage filter.",
                    {"lead_stage": "Unsupported stage value."},
                )
            if old_stage is not None and old_stage not in valid_stages:
                raise _validation_error(
                    "Invalid old_stage filter.",
                    {"old_stage": "Unsupported stage value."},
                )
            if new_stage is not None and new_stage not in valid_stages:
                raise _validation_error(
                    "Invalid new_stage filter.",
                    {"new_stage": "Unsupported stage value."},
                )

            where = ["TRUE"]
            params: list = []

            if lead_id is not None:
                params.append(lead_id)
                where.append(f"a.lead_id = ${len(params)}")
            if activity_type is not None:
                params.append(activity_type)
                where.append(f"a.activity_type = ${len(params)}")
            if call_type_code is not None:
                params.append(call_type_code)
                where.append(f"a.call_type_code = ${len(params)}")
            if call_status_code is not None:
                params.append(call_status_code)
                where.append(f"a.call_status_code = ${len(params)}")
            if old_stage is not None:
                params.append(old_stage)
                where.append(f"a.old_stage = ${len(params)}")
            if new_stage is not None:
                params.append(new_stage)
                where.append(f"a.new_stage = ${len(params)}")
            if performed_by is not None:
                params.append(performed_by)
                where.append(f"a.performed_by = ${len(params)}")
            if performed_at_from is not None:
                params.append(performed_at_from)
                where.append(f"a.performed_at >= ${len(params)}")
            if performed_at_to is not None:
                params.append(performed_at_to)
                where.append(f"a.performed_at <= ${len(params)}")
            if mobile is not None:
                params.append(mobile)
                where.append(f"l.mobile = ${len(params)}")
            if lead_stage is not None:
                params.append(lead_stage)
                where.append(f"l.stage = ${len(params)}")
            if lead_is_active is not None:
                params.append(lead_is_active)
                where.append(f"l.is_active = ${len(params)}")

            vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, len(params) + 1)
            if vis_sql:
                where.append(vis_sql)
                params.extend(vis_vals)

            base_from = f"""
                FROM {DB_SCHEMA}.crm_activities a
                INNER JOIN {DB_SCHEMA}.crm_leads l ON l.id = a.lead_id
            """
            where_sql = " AND ".join(where)
            count_params = list(params)
            n = len(params)
            list_params = list(params) + [limit, offset]

            count_sql = f"SELECT COUNT(*) {base_from} WHERE {where_sql}"
            list_sql = f"""
                SELECT a.* {base_from}
                WHERE {where_sql}
                ORDER BY a.performed_at DESC, a.id DESC
                LIMIT ${n + 1} OFFSET ${n + 2}
            """
            total = await conn.fetchval(count_sql, *count_params)
            rows = await conn.fetch(list_sql, *list_params)
            return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}
    except asyncpg.PostgresError:
        logger.exception("Database error while filtering CRM activities")
        raise HTTPException(status_code=500, detail="Database error.")


@router.get("/stages", summary="CRM lead pipeline stages for UI")
async def get_crm_lead_stages(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
) -> CRMLeadStagesOut:
    _get_user_context(current_user)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, code, name, sort_order
                FROM {DB_SCHEMA}.crm_lead_stages
                WHERE is_active
                ORDER BY sort_order, code
                """
            )
    except asyncpg.UndefinedTableError:
        logger.exception("crm_lead_stages missing; run docs/65-crm-lead-stages.sql")
        raise HTTPException(status_code=500, detail="CRM lead stages are not available.")
    except asyncpg.PostgresError:
        logger.exception("Database error while loading CRM lead stages")
        raise HTTPException(status_code=500, detail="Database error.")

    return CRMLeadStagesOut(
        stages=[
            CRMLeadStageItem(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                sort_order=r["sort_order"],
            )
            for r in rows
        ],
    )


@router.get("/{lead_id:int}", summary="Get CRM lead by id")
async def get_crm_lead(lead_id: int, current_user=Depends(require_permission("EMPLOYEE", "READ"))):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            row = await _fetch_crm_lead_visible(conn, role, emp_id, lead_id)
            if not row:
                raise HTTPException(status_code=404, detail="CRM lead not found.")
            return dict(row)
    except asyncpg.PostgresError:
        logger.exception("Database error while fetching CRM lead")
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


@router.get("/{lead_id:int}/activities", summary="Get CRM lead activities")
async def list_crm_activities(
    lead_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            lead = await _fetch_crm_lead_visible(conn, role, emp_id, lead_id)
            if not lead:
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


@router.post("/{lead_id:int}/followup-status", summary="Update CRM lead follow-up status")
async def update_crm_followup_status(
    lead_id: int,
    payload: CRMFollowupStatusUpdateIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)

    follow_up_status = _normalize_code(payload.follow_up_status)
    if follow_up_status not in FOLLOWUP_STATUSES:
        raise _validation_error("Invalid follow-up status.", {"follow_up_status": "Unsupported status value."})

    if payload.followup_at is not None and payload.followup_at <= datetime.now(IST):
        raise _validation_error("Invalid followup datetime.", {"followup_at": "Must be a future datetime."})

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                lead = await _fetch_crm_lead_visible(
                    conn, role, emp_id, lead_id, for_update=True
                )
                if not lead:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")
                if not lead["is_active"]:
                    raise _validation_error("Inactive lead cannot be updated.")

                old_status = lead.get("follow_up_status")

                if follow_up_status == "PENDING" and payload.followup_at is None and lead.get("followup_at") is None:
                    raise _validation_error(
                        "followup_at is required for pending status.",
                        {"followup_at": "Provide followup_at when setting PENDING."},
                    )

                updated = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.crm_leads
                    SET follow_up_status = $1,
                        followup_at = COALESCE($2, followup_at),
                        remarks = COALESCE($3, remarks),
                        missed_at = CASE WHEN $1 = 'MISSED' THEN missed_at ELSE NULL END,
                        completed_at = CASE
                            WHEN $1 = 'COMPLETED' THEN NOW()
                            ELSE NULL
                        END,
                        updated_at = NOW()
                    WHERE id = $4
                    RETURNING *
                    """,
                    follow_up_status,
                    payload.followup_at,
                    payload.remarks,
                    lead_id,
                )

                activity_id = await conn.fetchval(
                    f"""
                    INSERT INTO {DB_SCHEMA}.crm_activities (
                        lead_id, activity_type, remarks, performed_by, performed_at, created_at
                    )
                    VALUES ($1, 'FOLLOWUP_STATUS_UPDATE', $2, $3, NOW(), NOW())
                    RETURNING id
                    """,
                    lead_id,
                    (
                        f"follow_up_status: {old_status or 'NULL'} -> {follow_up_status}"
                        if payload.remarks is None
                        else f"{payload.remarks} | follow_up_status: {old_status or 'NULL'} -> {follow_up_status}"
                    ),
                    _performed_by_emp_id(emp_id),
                )

                log = logging.LoggerAdapter(
                    logger,
                    {"request_id": request_id, "emp_id": emp_id, "api": "crm_followup_status_update"},
                )
                log.info(
                    "CRM follow-up status updated | lead_id=%s old_status=%s new_status=%s",
                    lead_id,
                    old_status,
                    follow_up_status,
                )

                return {
                    "message": "Follow-up status updated successfully.",
                    "lead_id": lead_id,
                    "old_follow_up_status": old_status,
                    "follow_up_status": updated["follow_up_status"],
                    "followup_at": updated["followup_at"],
                    "missed_at": updated["missed_at"],
                    "completed_at": updated["completed_at"],
                    "activity_id": activity_id,
                }
    except asyncpg.exceptions.CheckViolationError as e:
        raise _validation_error("Constraint validation failed.", {"constraint": getattr(e, "constraint_name", "unknown")})
    except asyncpg.PostgresError:
        logger.exception("Database error while updating CRM follow-up status")
        raise HTTPException(status_code=500, detail="Database error.")


@router.post("/{lead_id:int}/call-update", status_code=status.HTTP_200_OK, summary="Update call status and apply CRM transitions")
async def update_crm_call(
    lead_id: int,
    payload: CRMCallUpdateIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id, "api": "crm_call_update"})

    call_type_code = _normalize_code(payload.call_type_code)
    call_status_code = _normalize_code(payload.call_status_code)

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _validate_call_config(conn, call_type_code, call_status_code)

                lead = await _fetch_crm_lead_visible(
                    conn, role, emp_id, lead_id, for_update=True
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
                await _validate_crm_call_against_mappings(
                    conn, current_stage, call_type_code, call_status_code
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
                        last_connected_at = CASE WHEN $2 = 1 THEN NOW() ELSE last_connected_at END,
                        followup_at = COALESCE($3, followup_at),
                        follow_up_status = CASE WHEN $3 IS NOT NULL THEN 'PENDING' ELSE follow_up_status END,
                        missed_at = CASE WHEN $3 IS NOT NULL THEN NULL ELSE missed_at END,
                        completed_at = CASE WHEN $3 IS NOT NULL THEN NULL ELSE completed_at END,
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
                    _performed_by_emp_id(emp_id),
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
                    "last_connected_at": updated["last_connected_at"],
                    "followup_at": updated["followup_at"],
                    "follow_up_status": updated["follow_up_status"],
                    "missed_at": updated["missed_at"],
                    "completed_at": updated["completed_at"],
                    "activity_id": activity_id,
                }
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise _validation_error("Invalid foreign key reference.", {"performed_by": "Employee reference invalid."})
    except asyncpg.exceptions.CheckViolationError as e:
        raise _validation_error("Constraint validation failed.", {"constraint": getattr(e, "constraint_name", "unknown")})
    except asyncpg.PostgresError:
        logger.exception("Database error while applying CRM call update")
        raise HTTPException(status_code=500, detail="Database error.")
