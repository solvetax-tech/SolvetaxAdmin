"""Shared CRM lead APIs and cross-cutting helpers (filter, bulk, activities, mappings, stages)."""

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

import asyncpg
import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import ValidationError

from backend.common.status_constants import CRM_STAGES, FOLLOWUP_STATUSES
from backend.crm.schemas_common import (
    CRMBulkAssignExecuteIn,
    CRMBulkAutoAssignConfigIn,
    CRMBulkAutoAssignEnabledPatchIn,
    CRMBulkImportIn,
    CRMLeadMarketingCreateIn,
    CRMLeadStagesOut,
    CRMLeadStageItem,
    CRMUIMappingsOut,
    CRMUIPitchStatusItem,
    CRMUIStagePitchItem,
)
from backend.logger import logger
from backend.text_search_filters import (
    append_fuzzy_name_filter,
    append_ilike_contains,
    build_fuzzy_name_clause,
)
from backend.redis_cache import (
    CACHE_TTL_ALERTS,
    CACHE_TTL_COUNTS,
    CACHE_TTL_LIST,
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from backend.security.public_security import enforce_public_security
from backend.security.rbac import require_permission
from backend.utils import DB_SCHEMA, generate_uuid, get_db_pool, employee_report_tree_subquery

IST = ZoneInfo("Asia/Kolkata")

# last_dailed_at / last_connected_at on crm_leads and crm_activities are updated only in
# _crm_apply_call_update (logged calls). System-driven stage changes (e.g. payment trigger →
# SUBSCRIBED, or other non-call paths) must not touch those columns.
# If Postgres has a BEFORE trigger that sets them when stage becomes GST_REGISTRATION_DONE or
# SUBSCRIBED, remove it, e.g.:
#   DROP TRIGGER IF EXISTS trg_crm_leads_milestone_dial_timestamps ON solvetax.crm_leads;
#   DROP FUNCTION IF EXISTS solvetax.fn_crm_leads_touch_dial_on_milestone_stage();

DEFAULT_CRM_ENTITY_TYPE = "GST_REGISTRATION"


def _crm_ui_mappings_tag() -> str:
    return "crm:ui_mappings:index"


def _crm_leads_filter_tag() -> str:
    return "crm:leads:filter:index"


def _crm_activities_filter_tag() -> str:
    return "crm:activities:filter:index"


def _crm_stages_tag() -> str:
    return "crm:stages:index"


def _crm_lead_by_entity_tag() -> str:
    return "crm:lead:by_entity:index"


def _crm_lead_by_id_tag(lead_id: int) -> str:
    return f"crm:lead:by_id:{lead_id}"


def _crm_lead_calls_tag(lead_id: int) -> str:
    return f"crm:lead:calls:{lead_id}"


def _crm_lead_stage_history_tag(lead_id: int) -> str:
    return f"crm:lead:stage_history:{lead_id}"


def _crm_lead_activities_tag(lead_id: int) -> str:
    return f"crm:lead:activities:{lead_id}"


async def _invalidate_crm_cache(lead_id: Optional[int] = None) -> None:
    await redis_invalidate_tag(_crm_leads_filter_tag())
    await redis_invalidate_tag(_crm_followup_counts_tag())
    await redis_invalidate_tag(_crm_followup_alerts_tag())
    await redis_invalidate_tag(_crm_followup_list_tag())
    await redis_invalidate_tag(_crm_activities_filter_tag())
    await redis_invalidate_tag(_crm_lead_by_entity_tag())
    if lead_id is not None:
        await redis_invalidate_tag(_crm_lead_by_id_tag(lead_id))
        await redis_invalidate_tag(_crm_lead_calls_tag(lead_id))
        await redis_invalidate_tag(_crm_lead_stage_history_tag(lead_id))
        await redis_invalidate_tag(_crm_lead_activities_tag(lead_id))


def _entity_type_query(value: Optional[str]) -> str:
    """Normalize entity_type for CRM reference data and lead filters (default GST registration CRM)."""
    v = (value or DEFAULT_CRM_ENTITY_TYPE).strip().upper()
    return v if v else DEFAULT_CRM_ENTITY_TYPE


def _crm_entity_type_match_sql(et_value: str, param_no: int, alias: str = "l") -> str:
    """
    Case/space-insensitive entity_type predicate. For the default GST funnel, legacy rows whose
    entity_type is NULL/blank are treated as GST_REGISTRATION (mirrors _crm_lead_matches_funnel_entity_type),
    so they are not silently dropped from list/filter results that display them.
    """
    base = f"upper(trim({alias}.entity_type)) = ${param_no}"
    if et_value == DEFAULT_CRM_ENTITY_TYPE:
        return f"({base} OR NULLIF(trim({alias}.entity_type), '') IS NULL)"
    return base


def _smart_board_stages(entity_type: Optional[str]) -> tuple[str, ...]:
    et = _entity_type_query(entity_type)
    if et == "INCOME_TAX":
        return SMART_BOARD_STAGES_ITR
    return SMART_BOARD_STAGES_GST


def _smart_board_stage_order_sql(entity_type: Optional[str]) -> str:
    """ORDER BY expression: PENDING_* → INTERESTED → FOLLOW_UP → FRESH_LEAD."""
    stages = _smart_board_stages(entity_type)
    cases = ", ".join(f"WHEN '{code}' THEN {i + 1}" for i, code in enumerate(stages))
    return f"CASE upper(trim(l.stage)) {cases} ELSE 99 END"


def _smart_board_call_priority_sql() -> str:
    """
    Within the same stage, sort by dial/connect pattern (lower = higher priority):
      1) 0 attempted, 0 connected — never called
      2) N attempted, 0 connected — dialed but never connected (1-0, 2-0, 3-0, …)
      3) N attempted, N connected — equal counts (1-1, 2-2, …)
      4) everything else (e.g. 3-2)
    """
    a = "COALESCE(l.call_attempted_count, 0)"
    c = "COALESCE(l.call_connected_count, 0)"
    return f"""CASE
        WHEN {a} = 0 AND {c} = 0 THEN 1
        WHEN {c} = 0 AND {a} > 0 THEN 2
        WHEN {a} = {c} AND {a} > 0 THEN 3
        ELSE 4
    END"""


def _smart_board_order_sql(entity_type: Optional[str]) -> str:
    """Full Smart Board ORDER BY: stage tier, then call tier, then recency."""
    return (
        f"{_smart_board_stage_order_sql(entity_type)} ASC, "
        f"{_smart_board_call_priority_sql()} ASC, "
        "l.updated_at DESC NULLS LAST, l.id DESC"
    )


def _mapping_row_entity_type(row: asyncpg.Record) -> Optional[str]:
    if "entity_type" not in row.keys():
        return None
    v = row["entity_type"]
    if v is None:
        return None
    s = str(v).strip()
    return s.upper() if s else None


def _crm_mapping_type_precedence_sql(param_idx: int) -> str:
    """Prefer row.entity_type = requested type over global NULL (applies to all). Lower sorts first."""
    return f"(CASE WHEN entity_type = ${param_idx} THEN 0 WHEN entity_type IS NULL THEN 1 ELSE 2 END)"


FIRST_PITCH_ALLOWED_STAGES = {"FRESH_LEAD", "FOLLOW_UP", "INTERESTED"}
FINAL_PITCH_ALLOWED_STAGES = {"GST_REGISTRATION_DONE", "SCHEDULED_PAYMENTS"}
CLOSED_STAGES = {"SUBSCRIBED", "NOT_INTERESTED"}

# Smart Board: show only these stages, highest priority first (see _smart_board_stage_order_sql).
SMART_BOARD_STAGES_GST = (
    "PENDING_REGISTRATION_DATA",
    "INTERESTED",
    "FOLLOW_UP",
    "FRESH_LEAD",
)
SMART_BOARD_STAGES_ITR = (
    "PENDING_ITR_DATA",
    "INTERESTED",
    "FOLLOW_UP",
    "FRESH_LEAD",
)
# Fallback when DB has no configured rows yet; union of GST + ITR funnel stage codes used in this app.
ALL_STAGES = frozenset(CRM_STAGES)

FIRST_PITCH_STATUSES_FALLBACK = frozenset(
    {
        "CALL_NOT_ANSWERED",
        "CALL_NOT_CONNECTED",
        "CALL_BUSY",
        "CALL_DONE",
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
        "CALL_DONE",
        "CALL_BACK",
        "SCHEDULED_PAYMENT",
        "NOT_INTERESTED",
    }
)

# FIRST_PITCH_CALL / FINAL_PITCH_CALL: no CRM stage change (CALL_DONE still counts as connected below).
_STATUSES_NO_STAGE_CHANGE = frozenset(
    {"CALL_NOT_ANSWERED", "CALL_NOT_CONNECTED", "CALL_BUSY", "CALL_DONE"}
)

# CONNECTED_AND_SCHEDULED only applies within this funnel (not e.g. PENDING_REGISTRATION_DATA).
_FIRST_PITCH_CONNECTED_STAGES = frozenset(
    {"FRESH_LEAD", "FOLLOW_UP", "INTERESTED"}
)

# FIRST_PITCH_CALL: connected only when outcome implies contact (not no-answer/busy).
FIRST_PITCH_CONNECTED = {
    "CALL_BACK",
    "CONNECTED_AND_SCHEDULED",
    "SEND_DOCS",
    "NOT_INTERESTED",
    "CALL_DONE",
}
# FINAL_PITCH_CALL: NOT_INTERESTED does not increment connected (first pitch only).
FINAL_PITCH_CONNECTED = {"SCHEDULED_PAYMENT", "CALL_BACK", "CALL_DONE"}

CRM_SERVICE_FOLLOWUP_STAGES: tuple[str, ...] = (
    "FRESH_LEAD",
    "FRESH_LEADS",
    "NEW",
    "FOLLOW_UP",
    "FOLLOWUP",
    "INTERESTED",
)
CRM_PAYMENT_FOLLOWUP_STAGES: tuple[str, ...] = (
    "SCHEDULED_PAYMENT",
    "SCHEDULED_PAYMENTS",
)


def _crm_followup_counts_tag() -> str:
    return "crm:leads:followup_counts:index"


def _crm_followup_alerts_tag() -> str:
    return "crm:leads:followup_alerts:index"


def _crm_followup_list_tag() -> str:
    return "crm:leads:followup_list:index"


def _normalize_crm_followup_category(category: Optional[str]) -> str:
    cat = (category or "service").strip().lower()
    if cat not in ("service", "payment"):
        raise _validation_error(
            "Invalid follow-up category.",
            {"category": "Must be service or payment."},
        )
    return cat

# Re-engage from NOT_INTERESTED when the client agrees to send documents.
SEND_DOCS_REOPEN_FROM_STAGE = "NOT_INTERESTED"


def _is_send_docs_reopen_from_not_interested(current_stage: str, call_status_code: str) -> bool:
    stage = (current_stage or "").strip().upper()
    status = (call_status_code or "").strip().upper()
    return stage == SEND_DOCS_REOPEN_FROM_STAGE and status == "SEND_DOCS"


def _closed_stage_blocks_call_update(current_stage: str, call_status_code: str) -> bool:
    """SUBSCRIBED stays closed; NOT_INTERESTED allows SEND_DOCS to move back to pending data."""
    stage = (current_stage or "").strip().upper()
    if stage not in CLOSED_STAGES:
        return False
    if _is_send_docs_reopen_from_not_interested(stage, call_status_code):
        return False
    return True


def _allows_first_pitch_call_from_stage(current_stage: str, call_status_code: str) -> bool:
    stage = (current_stage or "").strip().upper()
    if stage in FIRST_PITCH_ALLOWED_STAGES:
        return True
    return _is_send_docs_reopen_from_not_interested(stage, call_status_code)


def _normalize_code(value: str) -> str:
    return value.strip().upper()


_REMARKS_FILTER_ALIASES = {
    "PAYMENT DONE SERVICE PENDING": [
        "PAYMENT DONE SERVICE PENDING",
        "Payment done but service pending",
    ],
}


def _validate_optional_datetime_range(
    from_val: Optional[datetime],
    to_val: Optional[datetime],
    *,
    field_label: str,
) -> None:
    if from_val is not None and to_val is not None and from_val > to_val:
        raise _validation_error(
            f"Invalid {field_label} range.",
            {field_label: f"{field_label}_from must be <= {field_label}_to."},
        )


def _append_timestamp_range_filter(
    where: list,
    params: list,
    column: str,
    from_val: Optional[datetime],
    to_val: Optional[datetime],
) -> None:
    if from_val is not None:
        params.append(from_val)
        where.append(f"l.{column} >= ${len(params)}")
    if to_val is not None:
        params.append(to_val)
        where.append(f"l.{column} <= ${len(params)}")


def _append_remarks_filter(where: list, params: list, remarks: Optional[str]) -> None:
    """Match crm_leads.remarks (ILIKE). Known presets match legacy remark text variants too."""
    if remarks is None:
        return
    raw = str(remarks).strip()
    if not raw:
        return
    if len(raw) < 2:
        raise _validation_error(
            "Invalid remarks filter.",
            {"remarks": "Must be at least 2 characters."},
        )
    key = raw.upper()
    aliases = _REMARKS_FILTER_ALIASES.get(key)
    if aliases:
        parts = []
        for alias in aliases:
            params.append(f"%{alias}%")
            parts.append(f"l.remarks ILIKE ${len(params)}")
        where.append(f"({' OR '.join(parts)})")
        return
    params.append(f"%{raw}%")
    where.append(f"l.remarks ILIKE ${len(params)}")


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
        if not emp_id:
            return "FALSE", [], idx
        tree = employee_report_tree_subquery(DB_SCHEMA, idx)
        sql = f"(l.rm_id IN {tree} OR l.op_id IN {tree})"
        return sql, [emp_id], idx + 1
    # Staff → CRM rows owned as RM or OP only (same idea as customer visibility).
    if not emp_id:
        return "FALSE", [], idx
    sql = f"(l.rm_id = ${idx} OR l.op_id = ${idx})"
    return sql, [emp_id], idx + 1


def _performed_by_emp_id(emp_id: int) -> Optional[int]:
    """Avoid inserting performed_by=0 (invalid FK); ADMIN may have no numeric emp in token."""
    return emp_id if emp_id > 0 else None


def _require_crm_row_context(role: str, emp_id: int) -> None:
    """Non-admin CRM APIs need a positive emp_id so visibility predicates work."""
    if role == "ADMIN":
        return
    if emp_id <= 0:
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
    entity_type: Optional[str] = None,
) -> Optional[asyncpg.Record]:
    """Single-lead fetch with the same visibility rules as list/filter (404 if not visible)."""
    params: list = [lead_id]
    where = ["l.id = $1"]
    vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, 2)
    if vis_sql:
        where.append(vis_sql)
        params.extend(vis_vals)
    if entity_type:
        params.append(_normalize_code(entity_type))
        where.append(f"upper(trim(l.entity_type)) = ${len(params)}")
    lock = " FOR UPDATE OF l" if for_update else ""
    return await conn.fetchrow(
        f"""
        SELECT l.*,
               erm.first_name AS rm_name,
               eop.first_name AS op_name
          FROM {DB_SCHEMA}.crm_leads l
          LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = l.rm_id
          LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = l.op_id
         WHERE {' AND '.join(where)}{lock}
        """,
        *params,
    )


def _crm_lead_matches_funnel_entity_type(
    lead_et: Optional[str],
    expected: str,
) -> bool:
    """
    Allow link when the row is for this funnel: ``entity_type`` unset/blank (legacy GST list)
    or matches ``expected`` (e.g. GST_REGISTRATION / INCOME_TAX).
    """
    raw = (lead_et or "").strip().upper()
    if not raw:
        return True
    return raw == (expected or "").strip().upper()


async def _crm_linked_entity_row_exists(
    conn: asyncpg.Connection,
    funnel_entity_type: str,
    entity_id: int,
) -> bool:
    """Return True if ``entity_id`` exists in the business table for this CRM funnel."""
    ft = (funnel_entity_type or "").strip().upper()
    if ft == DEFAULT_CRM_ENTITY_TYPE:
        q = f"SELECT 1 FROM {DB_SCHEMA}.gst_registration WHERE id = $1"
    elif ft == "INCOME_TAX":
        q = f"SELECT 1 FROM {DB_SCHEMA}.income_tax WHERE id = $1"
    else:
        return False
    return (await conn.fetchval(q, entity_id)) is not None


async def _fetch_valid_stage_codes(
    conn: asyncpg.Connection, entity_type: Optional[str] = None
) -> set[str]:
    """Active stage codes from crm_lead_stages for this entity_type (includes NULL legacy rows)."""
    et = _entity_type_query(entity_type)
    try:
        rows = await conn.fetch(
            f"""
            SELECT code FROM {DB_SCHEMA}.crm_lead_stages
            WHERE is_active
              AND (entity_type = $1 OR entity_type IS NULL)
            ORDER BY sort_order
            """,
            et,
        )
        if rows:
            return {r["code"] for r in rows}
    except asyncpg.UndefinedTableError:
        pass
    except asyncpg.UndefinedColumnError:
        rows = await conn.fetch(
            f"""
            SELECT code FROM {DB_SCHEMA}.crm_lead_stages
            WHERE is_active
            ORDER BY sort_order
            """
        )
        if rows:
            return {r["code"] for r in rows}
    return set(ALL_STAGES)


def _normalize_optional_upper(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str):
        s = value.strip()
        return s.upper() if s else None
    return None


def _normalize_ay(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str):
        s = value.strip()
        return s[:20] if s else None
    return None


def _parse_optional_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"", "none", "null", "na", "nan"}:
        return None
    if s in {"true", "1", "yes", "y"}:
        return True
    if s in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {v}")


def _parse_optional_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in {"none", "null", "na", "nan"}:
        return None
    return int(s)


def _csv_nullish_to_none(v):
    """Treat spreadsheet empty cells and literal 'null' / 'none' as NULL."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s.lower() in {"null", "none", "na", "nan"}:
        return None
    return v if not isinstance(v, str) else s


async def _validate_call_config(
    conn: asyncpg.Connection,
    call_type_code: str,
    call_status_code: str,
    entity_type: Optional[str] = None,
) -> None:
    et = _entity_type_query(entity_type)
    try:
        type_exists = await conn.fetchval(
            f"""
            SELECT 1 FROM {DB_SCHEMA}.crm_call_types
            WHERE code = $1 AND is_active = TRUE
              AND (entity_type = $2 OR entity_type IS NULL)
            LIMIT 1
            """,
            call_type_code,
            et,
        )
    except asyncpg.UndefinedColumnError:
        type_exists = await conn.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.crm_call_types WHERE code = $1 AND is_active = TRUE LIMIT 1",
            call_type_code,
        )
    if not type_exists:
        raise _validation_error("Invalid call type.", {"call_type_code": f"{call_type_code} is invalid/inactive."})

    try:
        status_exists = await conn.fetchval(
            f"""
            SELECT 1 FROM {DB_SCHEMA}.crm_call_statuses
            WHERE code = $1 AND is_active = TRUE
              AND (entity_type = $2 OR entity_type IS NULL)
            LIMIT 1
            """,
            call_status_code,
            et,
        )
    except asyncpg.UndefinedColumnError:
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
    entity_type: Optional[str] = None,
) -> None:
    et = _entity_type_query(entity_type)

    # Re-open from NOT_INTERESTED: code path is fixed; DB mappings may omit this combo.
    if _is_send_docs_reopen_from_not_interested(current_stage, call_status_code):
        if call_type_code != "FIRST_PITCH_CALL":
            raise _validation_error(
                "Call type does not match re-open from not interested.",
                {
                    "call_type_code": (
                        f"Expected FIRST_PITCH_CALL for SEND_DOCS from NOT_INTERESTED, got {call_type_code}."
                    ),
                },
            )
        return
    try:
        has_stage_map = await conn.fetchval(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {DB_SCHEMA}.crm_stage_status_mappings
                WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active
                  AND (entity_type = $1 OR entity_type IS NULL)
            )
            """,
            et,
        )
        has_status_map = await conn.fetchval(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {DB_SCHEMA}.crm_stage_status_mappings
                WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active
                  AND (entity_type = $1 OR entity_type IS NULL)
            )
            """,
            et,
        )
    except asyncpg.UndefinedTableError:
        has_stage_map = False
        has_status_map = False
    except asyncpg.UndefinedColumnError:
        has_stage_map = await conn.fetchval(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {DB_SCHEMA}.crm_stage_status_mappings
                WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active
            )
            """
        )
        has_status_map = await conn.fetchval(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {DB_SCHEMA}.crm_stage_status_mappings
                WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active
            )
            """
        )

    if has_stage_map:
        try:
            expected_pitch = await conn.fetchval(
                f"""
                SELECT pitch_type_code FROM {DB_SCHEMA}.crm_stage_status_mappings
                WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active AND stage = $2
                  AND (entity_type = $1 OR entity_type IS NULL)
                ORDER BY {_crm_mapping_type_precedence_sql(1)}, sort_order
                LIMIT 1
                """,
                et,
                current_stage,
            )
        except asyncpg.UndefinedColumnError:
            expected_pitch = await conn.fetchval(
                f"""
                SELECT pitch_type_code FROM {DB_SCHEMA}.crm_stage_status_mappings
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
        if call_type_code == "FIRST_PITCH_CALL" and not _allows_first_pitch_call_from_stage(
            current_stage, call_status_code
        ):
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
        try:
            allowed_rows = await conn.fetch(
                f"""
                SELECT call_status_code
                FROM (
                    SELECT DISTINCT ON (pitch_type_code, call_status_code)
                        pitch_type_code, call_status_code, sort_order
                    FROM {DB_SCHEMA}.crm_stage_status_mappings
                    WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active AND pitch_type_code = $2
                      AND (entity_type = $1 OR entity_type IS NULL)
                    ORDER BY pitch_type_code, call_status_code, {_crm_mapping_type_precedence_sql(1)}, sort_order, call_status_code
                ) picked
                ORDER BY sort_order, call_status_code
                """,
                et,
                call_type_code,
            )
        except asyncpg.UndefinedColumnError:
            allowed_rows = await conn.fetch(
                f"""
                SELECT call_status_code FROM {DB_SCHEMA}.crm_stage_status_mappings
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




# --- Shared services backing `/api/v1/crm/leads/*` common routes ---

async def _svc_get_crm_stage_pitch_mappings(
    entity_type: Optional[str] = Query(
        None,
        description="Requested CRM scope; defaults to GST_REGISTRATION. Rows with NULL entity_type apply to all types; a type-specific row overrides the global row for the same stage/pitch or pitch/status.",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
) -> CRMUIMappingsOut:
    role, emp_id = _get_user_context(current_user)
    et = _entity_type_query(entity_type)
    cache_key = build_cache_key("crm:ui_mappings:v2", entity_type=et, role=role, emp_id=emp_id)
    pool = await get_db_pool()

    async def _load_ui_mappings():
        try:
            async with pool.acquire() as conn:
                try:
                    stage_rows = await conn.fetch(
                        f"""
                        SELECT stage, pitch_type_code, sort_order, entity_type
                        FROM (
                            SELECT DISTINCT ON (stage, pitch_type_code)
                                stage, pitch_type_code, sort_order, entity_type
                            FROM {DB_SCHEMA}.crm_stage_status_mappings
                            WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active
                              AND (entity_type = $1 OR entity_type IS NULL)
                            ORDER BY stage, pitch_type_code, {_crm_mapping_type_precedence_sql(1)}, sort_order, stage
                        ) picked
                        ORDER BY sort_order, stage
                        """,
                        et,
                    )
                    status_rows = await conn.fetch(
                        f"""
                        SELECT pitch_type_code, call_status_code, sort_order, entity_type
                        FROM (
                            SELECT DISTINCT ON (pitch_type_code, call_status_code)
                                pitch_type_code, call_status_code, sort_order, entity_type
                            FROM {DB_SCHEMA}.crm_stage_status_mappings
                            WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active
                              AND (entity_type = $1 OR entity_type IS NULL)
                            ORDER BY pitch_type_code, call_status_code, {_crm_mapping_type_precedence_sql(1)}, sort_order, call_status_code
                        ) picked
                        ORDER BY pitch_type_code, sort_order, call_status_code
                        """,
                        et,
                    )
                except asyncpg.UndefinedColumnError:
                    stage_rows = await conn.fetch(
                        f"""
                        SELECT stage, pitch_type_code, sort_order
                        FROM {DB_SCHEMA}.crm_stage_status_mappings
                        WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active
                        ORDER BY sort_order, stage
                        """
                    )
                    status_rows = await conn.fetch(
                        f"""
                        SELECT pitch_type_code, call_status_code, sort_order
                        FROM {DB_SCHEMA}.crm_stage_status_mappings
                        WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active
                        ORDER BY pitch_type_code, sort_order, call_status_code
                        """
                    )
        except asyncpg.UndefinedTableError:
            logger.exception(
                "crm_stage_status_mappings table missing; see db/migrations/crm_stage_status_mappings_entity_type.sql"
            )
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
                    entity_type=_mapping_row_entity_type(r),
                )
            )

        response_model = CRMUIMappingsOut(
            entity_type=et,
            stage_to_pitch=[
                CRMUIStagePitchItem(
                    stage=row["stage"],
                    pitch_type_code=row["pitch_type_code"],
                    sort_order=row["sort_order"],
                    entity_type=_mapping_row_entity_type(row),
                )
                for row in stage_rows
            ],
            pitch_to_statuses=pitch_to_statuses,
        )
        # Store/cache as JSON object, not stringified model repr.
        return response_model.model_dump()

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_ui_mappings,
        ttl_seconds=300,
        tags=[_crm_ui_mappings_tag()],
    )


async def _svc_filter_crm_leads(
    stage: Optional[str] = None,
    stages: Optional[List[str]] = Query(None, description="Filter by multiple stages (OR logic)."),
    follow_up_status: Optional[str] = None,
    mobile: Optional[str] = None,
    full_name: Optional[str] = Query(
        None,
        description="Fuzzy match on lead full_name (~35% word match).",
    ),
    email: Optional[str] = Query(
        None,
        description="Partial match on lead email.",
    ),
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    lead_type: Optional[str] = None,
    tag: Optional[str] = None,
    lead_source: Optional[str] = None,
    remarks: Optional[str] = Query(
        None,
        description="Filter crm_leads.remarks (case-insensitive contains).",
    ),
    is_active: Optional[bool] = None,
    followup_at_from: Optional[datetime] = Query(None, description="Inclusive lower bound on crm_leads.followup_at."),
    followup_at_to: Optional[datetime] = Query(None, description="Inclusive upper bound on crm_leads.followup_at."),
    rm_assigned_at_from: Optional[datetime] = Query(None, description="Inclusive lower bound on crm_leads.rm_assigned_at."),
    rm_assigned_at_to: Optional[datetime] = Query(None, description="Inclusive upper bound on crm_leads.rm_assigned_at."),
    op_assigned_at_from: Optional[datetime] = Query(None, description="Inclusive lower bound on crm_leads.op_assigned_at."),
    op_assigned_at_to: Optional[datetime] = Query(None, description="Inclusive upper bound on crm_leads.op_assigned_at."),
    last_dailed_at_from: Optional[datetime] = Query(None, description="Inclusive lower bound on crm_leads.last_dailed_at."),
    last_dailed_at_to: Optional[datetime] = Query(None, description="Inclusive upper bound on crm_leads.last_dailed_at."),
    last_connected_at_from: Optional[datetime] = Query(None, description="Inclusive lower bound on crm_leads.last_connected_at."),
    last_connected_at_to: Optional[datetime] = Query(None, description="Inclusive upper bound on crm_leads.last_connected_at."),
    entity_type: Optional[str] = Query(None, description="Filter by crm_leads.entity_type (e.g. GST_REGISTRATION)."),
    entity_id: Optional[int] = Query(None, ge=1, description="Filter by crm_leads.entity_id."),
    ay: Optional[str] = Query(None, description="Filter by assessment year (exact match on crm_leads.ay)."),
    smart_board: bool = Query(
        False,
        description=(
            "Smart Board mode: early-funnel stages only, ordered by stage priority then "
            "call pattern (0-0, then N-0, then N-N, then other), then updated_at."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    remarks_norm = remarks.strip() if isinstance(remarks, str) and remarks.strip() else None
    if smart_board and (stage or stages):
        raise _validation_error(
            "Smart Board mode cannot combine with stage or stages filters.",
            {"smart_board": "Remove stage/stages or set smart_board=false."},
        )
    if stage and stages:
        raise _validation_error(
            "Provide either stage or stages.",
            {"stage": "Use single stage or stages list, not both."},
        )
    if (
        followup_at_from is not None
        and followup_at_to is not None
        and followup_at_from > followup_at_to
    ):
        raise _validation_error(
            "Invalid followup_at range.",
            {"followup_at_from": "followup_at_from must be <= followup_at_to."},
        )
    _validate_optional_datetime_range(rm_assigned_at_from, rm_assigned_at_to, field_label="rm_assigned_at")
    _validate_optional_datetime_range(op_assigned_at_from, op_assigned_at_to, field_label="op_assigned_at")
    _validate_optional_datetime_range(last_dailed_at_from, last_dailed_at_to, field_label="last_dailed_at")
    _validate_optional_datetime_range(last_connected_at_from, last_connected_at_to, field_label="last_connected_at")
    if stage:
        stage = _normalize_code(stage)
    stages_norm: Optional[List[str]] = None
    if smart_board:
        stages_norm = list(_smart_board_stages(entity_type))
    elif stages:
        stages_norm = []
        for s in stages:
            if not isinstance(s, str) or not s.strip():
                raise _validation_error(
                    "Invalid stages filter.",
                    {"stages": "Each stage must be a non-empty string."},
                )
            stages_norm.append(_normalize_code(s))
        # Preserve input order while removing duplicates.
        stages_norm = list(dict.fromkeys(stages_norm))
    if follow_up_status:
        follow_up_status = _normalize_code(follow_up_status)
        if follow_up_status not in FOLLOWUP_STATUSES:
            raise _validation_error(
                "Invalid follow_up_status filter.",
                {"follow_up_status": "Unsupported follow-up status value."},
            )
    mobile_exact: Optional[str] = None
    mobile_partial: Optional[str] = None
    if mobile:
        m = mobile.strip()
        digits = re.sub(r"\D", "", m)
        if len(digits) == 10:
            mobile_exact = digits
        elif len(digits) >= 4:
            mobile_partial = digits
        else:
            raise _validation_error(
                "Invalid mobile filter.",
                {"mobile": "Use a 10-digit number or at least 4 digits for partial match."},
            )
    full_name_norm = full_name.strip() if isinstance(full_name, str) and full_name.strip() else None
    email_norm = email.strip().lower() if isinstance(email, str) and email.strip() else None
    lead_type_norm = _normalize_code(lead_type) if isinstance(lead_type, str) and lead_type.strip() else None
    tag_norm = tag.strip() if isinstance(tag, str) and tag.strip() else None
    lead_source_norm = _normalize_code(lead_source) if isinstance(lead_source, str) and lead_source.strip() else None
    ay_norm = _normalize_ay(ay) if isinstance(ay, str) else None
    et_filter = _entity_type_query(entity_type) if (entity_type is not None or entity_id is not None) else None
    cache_key = build_cache_key(
        "crm:leads:filter:v3",
        stage=stage,
        stages=stages_norm,
        smart_board=smart_board,
        follow_up_status=follow_up_status,
        mobile=mobile_exact or mobile_partial,
        full_name=full_name_norm,
        email=email_norm,
        rm_id=rm_id,
        op_id=op_id,
        lead_type=lead_type_norm,
        tag=tag_norm,
        lead_source=lead_source_norm,
        remarks=remarks_norm,
        is_active=is_active,
        followup_at_from=followup_at_from,
        followup_at_to=followup_at_to,
        rm_assigned_at_from=rm_assigned_at_from,
        rm_assigned_at_to=rm_assigned_at_to,
        op_assigned_at_from=op_assigned_at_from,
        op_assigned_at_to=op_assigned_at_to,
        last_dailed_at_from=last_dailed_at_from,
        last_dailed_at_to=last_dailed_at_to,
        last_connected_at_from=last_connected_at_from,
        last_connected_at_to=last_connected_at_to,
        entity_type=et_filter or _entity_type_query(entity_type) if entity_type is not None else None,
        entity_id=entity_id,
        ay=ay_norm,
        limit=limit,
        offset=offset,
        role=role,
        emp_id=emp_id,
    )

    pool = await get_db_pool()
    async def _load_filtered_crm_leads():
        try:
            async with pool.acquire() as conn:
                if stage:
                    valid_stages = await _fetch_valid_stage_codes(conn, et_filter or DEFAULT_CRM_ENTITY_TYPE)
                    if stage not in valid_stages:
                        raise _validation_error(
                            "Invalid stage filter.",
                            {"stage": "Unsupported stage value."},
                        )
                if stages_norm:
                    valid_stages = await _fetch_valid_stage_codes(conn, et_filter or DEFAULT_CRM_ENTITY_TYPE)
                    invalid_stages = [s for s in stages_norm if s not in valid_stages]
                    if invalid_stages:
                        raise _validation_error(
                            "Invalid stages filter.",
                            {"stages": f"Unsupported stage values: {', '.join(invalid_stages)}"},
                        )
                where = ["TRUE"]
                params = []
                if stage:
                    params.append(stage)
                    where.append(f"upper(trim(l.stage)) = ${len(params)}")
                elif stages_norm:
                    params.append(stages_norm)
                    where.append(f"upper(trim(l.stage)) = ANY(${len(params)})")
                if follow_up_status:
                    params.append(follow_up_status)
                    where.append(f"l.follow_up_status = ${len(params)}")
                if mobile_exact:
                    params.append(mobile_exact)
                    where.append(f"l.mobile = ${len(params)}")
                elif mobile_partial:
                    params.append(f"%{mobile_partial}%")
                    where.append(
                        f"regexp_replace(COALESCE(l.mobile, ''), '[^0-9]', '', 'g') LIKE ${len(params)}"
                    )
                filter_idx = len(params) + 1
                if full_name_norm:
                    filter_idx = append_fuzzy_name_filter(
                        where, params, filter_idx, "l.full_name", full_name_norm
                    )
                if email_norm:
                    filter_idx = append_ilike_contains(
                        where, params, filter_idx, "lower(COALESCE(l.email, ''))", email_norm
                    )
                if rm_id is not None:
                    params.append(rm_id)
                    where.append(f"l.rm_id = ${len(params)}")
                if op_id is not None:
                    params.append(op_id)
                    where.append(f"l.op_id = ${len(params)}")
                if lead_type_norm:
                    params.append(lead_type_norm)
                    where.append(f"upper(trim(l.lead_type)) = ${len(params)}")
                if tag_norm:
                    filter_idx = len(params) + 1
                    filter_idx = append_fuzzy_name_filter(where, params, filter_idx, "l.tag", tag_norm)
                if lead_source_norm:
                    params.append(lead_source_norm)
                    where.append(f"upper(trim(l.lead_source)) = ${len(params)}")
                if ay_norm:
                    params.append(ay_norm)
                    where.append(f"trim(l.ay) = ${len(params)}")
                _append_remarks_filter(where, params, remarks_norm)
                if is_active is not None:
                    params.append(is_active)
                    where.append(f"l.is_active = ${len(params)}")
                if followup_at_from is not None:
                    params.append(followup_at_from)
                    where.append(f"l.followup_at >= ${len(params)}")
                if followup_at_to is not None:
                    params.append(followup_at_to)
                    where.append(f"l.followup_at <= ${len(params)}")
                _append_timestamp_range_filter(
                    where, params, "rm_assigned_at", rm_assigned_at_from, rm_assigned_at_to
                )
                _append_timestamp_range_filter(
                    where, params, "op_assigned_at", op_assigned_at_from, op_assigned_at_to
                )
                _append_timestamp_range_filter(
                    where, params, "last_dailed_at", last_dailed_at_from, last_dailed_at_to
                )
                _append_timestamp_range_filter(
                    where, params, "last_connected_at", last_connected_at_from, last_connected_at_to
                )
                if entity_id is not None:
                    params.append(entity_id)
                    where.append(f"l.entity_id = ${len(params)}")
                    et_val = _entity_type_query(entity_type)
                    params.append(et_val)
                    where.append(_crm_entity_type_match_sql(et_val, len(params)))
                elif entity_type is not None:
                    et_val = _entity_type_query(entity_type)
                    params.append(et_val)
                    where.append(_crm_entity_type_match_sql(et_val, len(params)))

                vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, len(params) + 1)
                if vis_sql:
                    where.append(vis_sql)
                    params.extend(vis_vals)

                count_params = list(params)
                params.extend([limit, offset])
                count_sql = f"SELECT COUNT(*) FROM {DB_SCHEMA}.crm_leads l WHERE {' AND '.join(where)}"
                if smart_board:
                    order_sql = _smart_board_order_sql(entity_type)
                else:
                    order_sql = "l.updated_at DESC NULLS LAST, l.id DESC"
                list_sql = f"""
                    SELECT l.*,
                           erm.first_name AS rm_name,
                           eop.first_name AS op_name
                    FROM {DB_SCHEMA}.crm_leads l
                    LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = l.rm_id
                    LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = l.op_id
                    WHERE {' AND '.join(where)}
                    ORDER BY {order_sql}
                    LIMIT ${len(params)-1} OFFSET ${len(params)}
                """
                total = await conn.fetchval(count_sql, *count_params)
                rows = await conn.fetch(list_sql, *params)
                return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}
        except asyncpg.PostgresError:
            logger.exception("Database error while filtering CRM leads")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_filtered_crm_leads,
        ttl_seconds=300,
        tags=[_crm_leads_filter_tag()],
    )


async def _bulk_import_crm_leads(
    payload: CRMBulkImportIn,
    current_user,
):
    role, emp_id = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can bulk import leads.")

    pool = await get_db_pool()
    request_id = generate_uuid()
    inserted_count = 0
    skipped_count = 0
    failed_count = 0
    errors = []

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                active_emp_ids = await conn.fetch(
                    f"SELECT emp_id FROM {DB_SCHEMA}.employees WHERE is_active = TRUE"
                )
                active_emp_id_set = {int(r["emp_id"]) for r in active_emp_ids}

                valid_stages_by_entity: dict[str, set[str]] = {}

                for i, row in enumerate(payload.rows, start=1):
                    try:
                        mobile = (row.mobile or "").strip()
                        if not mobile.isdigit() or len(mobile) != 10:
                            raise _validation_error("Invalid mobile.", {"mobile": "Must be a 10-digit number."})

                        entity_type = _normalize_code(str(row.entity_type))
                        stage = _normalize_optional_upper(row.stage) or "FRESH_LEAD"
                        lead_type = (_normalize_optional_upper(row.lead_type) or "")[:50]
                        tag_stripped = row.tag.strip() if isinstance(row.tag, str) else ""
                        tag = tag_stripped or None
                        lead_source = (
                            (_normalize_optional_upper(row.lead_source) or "")[:100]
                            if row.lead_source
                            else None
                        )
                        preferred_language = row.preferred_language.strip()[:50]
                        email = row.email
                        full_name_bulk = row.full_name
                        ay_val = _normalize_ay(row.ay)

                        if row.followup_at is not None and row.followup_at <= datetime.now(IST):
                            raise _validation_error(
                                "Invalid followup datetime.",
                                {"followup_at": "Must be a future datetime."},
                            )

                        if row.rm_id is not None and row.rm_id not in active_emp_id_set:
                            raise _validation_error("Invalid rm_id.", {"rm_id": "Employee not found/active."})
                        if row.op_id is not None and row.op_id not in active_emp_id_set:
                            raise _validation_error("Invalid op_id.", {"op_id": "Employee not found/active."})

                        stage_scope = entity_type
                        if stage_scope not in valid_stages_by_entity:
                            valid_stages_by_entity[stage_scope] = await _fetch_valid_stage_codes(conn, stage_scope)
                        if stage not in valid_stages_by_entity[stage_scope]:
                            raise _validation_error(
                                "Invalid stage value.",
                                {"stage": f"{stage} is not supported for {stage_scope}."},
                            )

                        existing = await conn.fetchrow(
                            f"""
                            SELECT *
                            FROM {DB_SCHEMA}.crm_leads
                            WHERE trim(mobile) = trim($1)
                              AND entity_type IS NOT DISTINCT FROM $2
                            ORDER BY id DESC
                            LIMIT 1
                            FOR UPDATE
                            """,
                            mobile,
                            entity_type,
                        )

                        if existing:
                            # Duplicate (mobile + entity_type): skip — never update existing rows.
                            skipped_count += 1
                        else:
                            if not payload.validate_only:
                                await conn.fetchval(
                                    f"""
                                    INSERT INTO {DB_SCHEMA}.crm_leads (
                                        mobile, full_name, email, entity_id, entity_type, preferred_language,
                                        stage, followup_at, rm_id, op_id, rm_assigned_at, op_assigned_at, remarks,
                                        is_active, follow_up_status, lead_type, tag, lead_source, ay,
                                        created_at, updated_at
                                    ) VALUES (
                                        $1, $2, $3, $4, $5, $6,
                                        $7, $8, $9, $10,
                                        CASE WHEN $9 IS NOT NULL THEN NOW() ELSE NULL END,
                                        CASE WHEN $10 IS NOT NULL THEN NOW() ELSE NULL END,
                                        $11,
                                        COALESCE($12, TRUE), COALESCE($13, 'PENDING'),
                                        $14, $15, $16, $17,
                                        NOW(), NOW()
                                    )
                                    RETURNING id
                                    """,
                                    mobile,
                                    full_name_bulk,
                                    email,
                                    row.entity_id,
                                    entity_type,
                                    preferred_language,
                                    stage,
                                    row.followup_at,
                                    row.rm_id,
                                    row.op_id,
                                    row.remarks,
                                    row.is_active,
                                    row.follow_up_status,
                                    lead_type,
                                    tag,
                                    lead_source,
                                    ay_val,
                                )
                            inserted_count += 1
                    except HTTPException as ex:
                        failed_count += 1
                        errors.append({"row_number": i, "detail": ex.detail})
                    except Exception as ex:
                        failed_count += 1
                        errors.append({"row_number": i, "detail": str(ex)})

        await _invalidate_crm_cache()
        total_rows = len(payload.rows)
        new_leads = inserted_count
        duplicates_found = skipped_count
        return {
            "message": (
                f"Successfully imported {new_leads} new lead(s). "
                f"{duplicates_found} duplicate(s) skipped."
            ),
            "request_id": request_id,
            "validate_only": payload.validate_only,
            "total_rows": total_rows,
            "new_leads": new_leads,
            "duplicates_found": duplicates_found,
            "duplicates_skipped": duplicates_found,
            "duplicates_updated": 0,
            "failed_count": failed_count,
            "inserted_count": inserted_count,
            "updated_count": 0,
            "skipped_count": skipped_count,
            "success_count": new_leads,
            "imported_count": new_leads,
            "stats": {
                "total_rows": total_rows,
                "new_leads": new_leads,
                "duplicates_found": duplicates_found,
                "duplicates_skipped": duplicates_found,
                "duplicates_updated": 0,
                "failed": failed_count,
            },
            "errors": errors,
        }
    except asyncpg.PostgresError:
        logger.exception("Database error during CRM bulk import")
        raise HTTPException(status_code=500, detail="Database error.")


async def _svc_get_bulk_assign_candidates(
    *,
    stages: Optional[List[str]] = None,
    rm_ids: Optional[List[int]] = None,
    op_ids: Optional[List[int]] = None,
    lead_types: Optional[List[str]] = None,
    ays: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    lead_sources: Optional[List[str]] = None,
    entity_types: List[str],
    follow_up_statuses: Optional[List[str]] = None,
    null_fields: Optional[List[str]] = None,
    not_null_fields: Optional[List[str]] = None,
    is_active: Optional[bool] = None,
    match_mode: str = "AND",
    filter_mode: str = "IN",
    limit: int = 500,
    offset: int = 0,
    current_user,
):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    mode = _normalize_code(match_mode)
    if mode not in {"AND", "OR"}:
        raise _validation_error("Invalid match_mode.", {"match_mode": "Use AND or OR."})
    filter_mode_norm = _normalize_code(filter_mode)
    if filter_mode_norm not in {"IN", "NOT_IN"}:
        raise _validation_error("Invalid filter_mode.", {"filter_mode": "Use IN or NOT_IN."})

    def norm_str_list(vals: Optional[List[str]]) -> List[str]:
        return list(
            dict.fromkeys(
                [_normalize_code(v) for v in (vals or []) if isinstance(v, str) and v.strip()]
            )
        )

    stages_n = norm_str_list(stages)
    lead_types_n = norm_str_list(lead_types)
    ays_n = list(
        dict.fromkeys(
            [_normalize_ay(v) for v in (ays or []) if isinstance(v, str) and v.strip()]
        )
    )
    ays_n = [v for v in ays_n if v]
    tags_n = norm_str_list(tags)
    lead_sources_n = norm_str_list(lead_sources)
    entity_types_n = norm_str_list(entity_types)
    if not entity_types_n:
        raise _validation_error(
            "Invalid entity_types.",
            {"entity_types": "Provide at least one non-empty entity type (e.g. GST_REGISTRATION, INCOME_TAX)."},
        )
    follow_up_statuses_n = norm_str_list(follow_up_statuses)
    null_fields_n = norm_str_list(null_fields)
    not_null_fields_n = norm_str_list(not_null_fields)

    null_field_sql = {
        "STAGE": "l.stage",
        "RM_ID": "l.rm_id",
        "OP_ID": "l.op_id",
        "LEAD_TYPE": "l.lead_type",
        "TAG": "l.tag",
        "LEAD_SOURCE": "l.lead_source",
        "ENTITY_TYPE": "l.entity_type",
        "FOLLOW_UP_STATUS": "l.follow_up_status",
        "AY": "l.ay",
    }
    allowed_null_fields = set(null_field_sql.keys())

    invalid_null_fields = [f for f in null_fields_n if f not in allowed_null_fields]
    if invalid_null_fields:
        raise _validation_error(
            "Invalid null_fields.",
            {"null_fields": f"Unsupported values: {', '.join(invalid_null_fields)}"},
        )
    invalid_not_null_fields = [f for f in not_null_fields_n if f not in allowed_null_fields]
    if invalid_not_null_fields:
        raise _validation_error(
            "Invalid not_null_fields.",
            {"not_null_fields": f"Unsupported values: {', '.join(invalid_not_null_fields)}"},
        )

    overlap = sorted(set(null_fields_n) & set(not_null_fields_n))
    if overlap:
        raise _validation_error(
            "Conflicting NULL filters.",
            {"null_fields": f"Conflicts with not_null_fields: {', '.join(overlap)}"},
        )

    for s in follow_up_statuses_n:
        if s not in FOLLOWUP_STATUSES:
            raise _validation_error("Invalid follow_up_statuses.", {"follow_up_statuses": f"{s} is not allowed."})

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            clauses = []
            params: list = []
            if stages_n:
                params.append(stages_n)
                clauses.append(
                    f"upper(trim(l.stage)) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (upper(trim(l.stage)) = ANY(${len(params)}))"
                )
            if rm_ids:
                params.append(rm_ids)
                clauses.append(
                    f"l.rm_id = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (l.rm_id = ANY(${len(params)}))"
                )
            if op_ids:
                params.append(op_ids)
                clauses.append(
                    f"l.op_id = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (l.op_id = ANY(${len(params)}))"
                )
            if lead_types_n:
                params.append(lead_types_n)
                clauses.append(
                    f"upper(trim(l.lead_type)) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (upper(trim(l.lead_type)) = ANY(${len(params)}))"
                )
            if ays_n:
                params.append(ays_n)
                clauses.append(
                    f"trim(l.ay) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (trim(l.ay) = ANY(${len(params)}))"
                )
            if tags_n:
                tag_parts = []
                for tag_item in tags_n:
                    fuzzy_idx = len(params) + 1
                    clause, clause_values, fuzzy_idx = build_fuzzy_name_clause(
                        "l.tag", tag_item, fuzzy_idx
                    )
                    if clause:
                        tag_parts.append(f"({clause})")
                        params.extend(clause_values)
                if tag_parts:
                    joined = f"({' OR '.join(tag_parts)})"
                    clauses.append(joined if filter_mode_norm == "IN" else f"NOT ({joined})")
            if lead_sources_n:
                params.append(lead_sources_n)
                clauses.append(
                    f"upper(trim(l.lead_source)) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (upper(trim(l.lead_source)) = ANY(${len(params)}))"
                )
            if entity_types_n:
                params.append(entity_types_n)
                clauses.append(
                    f"upper(trim(l.entity_type)) = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (upper(trim(l.entity_type)) = ANY(${len(params)}))"
                )
            if follow_up_statuses_n:
                params.append(follow_up_statuses_n)
                clauses.append(
                    f"l.follow_up_status = ANY(${len(params)})"
                    if filter_mode_norm == "IN"
                    else f"NOT (l.follow_up_status = ANY(${len(params)}))"
                )
            for key in null_fields_n:
                clauses.append(f"{null_field_sql[key]} IS NULL")
            for key in not_null_fields_n:
                clauses.append(f"{null_field_sql[key]} IS NOT NULL")
            if is_active is not None:
                params.append(is_active)
                clauses.append(f"l.is_active = ${len(params)}")

            where_parts = []
            if clauses:
                where_parts.append(f"({' OR '.join(clauses)})" if mode == "OR" else f"({' AND '.join(clauses)})")
            vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, len(params) + 1)
            if vis_sql:
                where_parts.append(vis_sql)
                params.extend(vis_vals)
            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            count_sql = f"SELECT COUNT(*) FROM {DB_SCHEMA}.crm_leads l {where_sql}"
            params_with_page = list(params) + [limit, offset]
            list_sql = f"""
                SELECT l.*,
                       erm.first_name AS rm_name,
                       eop.first_name AS op_name
                FROM {DB_SCHEMA}.crm_leads l
                LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = l.rm_id
                LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = l.op_id
                {where_sql}
                ORDER BY l.updated_at DESC, l.id DESC
                LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
            """
            total = await conn.fetchval(count_sql, *params)
            rows = await conn.fetch(list_sql, *params_with_page)
            return {
                "items": [dict(r) for r in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
                "match_mode": mode,
                "filter_mode": filter_mode_norm,
                "null_fields": null_fields_n,
                "not_null_fields": not_null_fields_n,
            }
    except asyncpg.PostgresError:
        logger.exception("Database error while fetching bulk assign candidates")
        raise HTTPException(status_code=500, detail="Database error.")


async def _svc_execute_bulk_assign(
    payload: CRMBulkAssignExecuteIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    role, emp_id = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can bulk assign leads.")

    unique_lead_ids = list(dict.fromkeys(payload.lead_ids))
    pool = await get_db_pool()

    if payload.selected_usernames:
        unique_usernames = list(dict.fromkeys(u.strip() for u in payload.selected_usernames if u and str(u).strip()))
        if not unique_usernames:
            raise _validation_error(
                "Invalid selected_usernames.",
                {"selected_usernames": "At least one username is required."},
            )
        role_filter = payload.assignment_role
    else:
        unique_usernames = None
        unique_emp_ids = list(dict.fromkeys(payload.selected_employee_ids or []))

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if unique_usernames is not None:
                    valid_rows = await conn.fetch(
                        f"""
                        SELECT emp_id, lower(username) AS username_key
                          FROM {DB_SCHEMA}.employees
                         WHERE is_active = TRUE
                           AND role = $1
                           AND lower(username) = ANY($2::text[])
                        """,
                        role_filter,
                        [u.lower() for u in unique_usernames],
                    )
                    username_to_emp = {r["username_key"]: int(r["emp_id"]) for r in valid_rows}
                    valid_emp_ids = []
                    for uname in unique_usernames:
                        key = uname.lower()
                        if key not in username_to_emp:
                            raise _validation_error(
                                "Invalid selected_usernames.",
                                {
                                    "selected_usernames": (
                                        f"Unknown or inactive {role_filter} username: {uname}"
                                    )
                                },
                            )
                        valid_emp_ids.append(username_to_emp[key])
                else:
                    # Enforce that every selected employee actually holds the
                    # assignment_role (RM/OP). Without this, a caller could set
                    # rm_id to an OP (or any other role) employee — the username
                    # branch above already filters by role, so mirror it here.
                    valid_rows = await conn.fetch(
                        f"""
                        SELECT emp_id FROM {DB_SCHEMA}.employees
                         WHERE is_active = TRUE
                           AND role = $1
                           AND emp_id = ANY($2::bigint[])
                        """,
                        payload.assignment_role,
                        unique_emp_ids,
                    )
                    valid_emp_ids = [int(r["emp_id"]) for r in valid_rows]
                    if len(valid_emp_ids) != len(unique_emp_ids):
                        raise _validation_error(
                            "Invalid selected_employee_ids.",
                            {
                                "selected_employee_ids": (
                                    f"One or more employees are invalid, inactive, "
                                    f"or not a {payload.assignment_role}."
                                )
                            },
                        )

                vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, 2)
                vis_clause = f" AND {vis_sql}" if vis_sql else ""
                lead_rows = await conn.fetch(
                    f"""
                    SELECT l.id
                    FROM {DB_SCHEMA}.crm_leads l
                    WHERE l.id = ANY($1::bigint[])
                    {vis_clause}
                    FOR UPDATE SKIP LOCKED
                    """,
                    unique_lead_ids,
                    *vis_vals,
                )
                lead_ids = [int(r["id"]) for r in lead_rows]
                entity_type_row = await conn.fetchval(
                    f"""
                    SELECT upper(trim(entity_type))
                    FROM {DB_SCHEMA}.crm_leads
                    WHERE id = ANY($1::bigint[])
                    LIMIT 1
                    """,
                    unique_lead_ids,
                )
                per_employee_counts = {eid: 0 for eid in valid_emp_ids}
                pool_size = len(valid_emp_ids)
                emp_cursor = int(payload.round_robin_start_index or 0) % pool_size if pool_size else 0

                for lead_id in lead_ids:
                    assigned = False
                    for _ in range(len(valid_emp_ids)):
                        assignee = valid_emp_ids[emp_cursor % len(valid_emp_ids)]
                        emp_cursor += 1
                        if payload.per_employee_limit is not None and per_employee_counts[assignee] >= payload.per_employee_limit:
                            continue
                        if payload.assignment_role == "RM":
                            await conn.execute(
                                (
                                    f"UPDATE {DB_SCHEMA}.crm_leads "
                                    f"SET rm_id = $1, "
                                    f"rm_assigned_at = CASE WHEN rm_id IS DISTINCT FROM $1 THEN NOW() ELSE rm_assigned_at END, "
                                    f"updated_at = NOW() "
                                    f"WHERE id = $2"
                                ),
                                assignee,
                                lead_id,
                            )
                        else:
                            await conn.execute(
                                (
                                    f"UPDATE {DB_SCHEMA}.crm_leads "
                                    f"SET op_id = $1, "
                                    f"op_assigned_at = CASE WHEN op_id IS DISTINCT FROM $1 THEN NOW() ELSE op_assigned_at END, "
                                    f"updated_at = NOW() "
                                    f"WHERE id = $2"
                                ),
                                assignee,
                                lead_id,
                            )
                        per_employee_counts[assignee] += 1
                        assigned = True
                        break
                    if not assigned:
                        break

        await _invalidate_crm_cache()
        result = {
            "message": "CRM bulk assignment completed.",
            "assignment_role": payload.assignment_role,
            "total_selected": len(unique_lead_ids),
            "total_assigned": sum(per_employee_counts.values()),
            "per_employee_counts": per_employee_counts,
            "round_robin_next_index": (emp_cursor % pool_size) if pool_size else 0,
        }
        if not payload.suppress_log:
            try:
                from backend.crm.crm_bulk_auto_assign import insert_bulk_assign_log

                roles_for_log: dict = dict(payload.batch_log_roles or {})
                roles_for_log[payload.assignment_role] = {
                    "total_assigned": result["total_assigned"],
                    "per_employee_counts": result["per_employee_counts"],
                }
                log_summary = {
                    "run_type": "MANUAL",
                    "assignment_role": payload.assignment_role,
                    "total_selected": result["total_selected"],
                    "total_assigned": result["total_assigned"],
                    "per_employee_counts": result["per_employee_counts"],
                    "roles": roles_for_log,
                }
                await insert_bulk_assign_log(
                    run_type="MANUAL",
                    entity_type=entity_type_row or "UNKNOWN",
                    scheduler_id=None,
                    triggered_by=emp_id,
                    summary=log_summary,
                )
            except Exception:
                logger.warning("Manual bulk-assign log insert failed", exc_info=True)
        return result
    except asyncpg.PostgresError:
        logger.exception("Database error during CRM bulk assign execute")
        raise HTTPException(status_code=500, detail="Database error.")


async def _svc_filter_crm_activities(
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
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None, ge=1),
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

    et_scope = _entity_type_query(entity_type) if (entity_type is not None or entity_id is not None) else None
    cache_key = build_cache_key(
        "crm:activities:filter",
        lead_id=lead_id,
        activity_type=activity_type,
        call_type_code=call_type_code,
        call_status_code=call_status_code,
        old_stage=old_stage,
        new_stage=new_stage,
        performed_by=performed_by,
        performed_at_from=performed_at_from.isoformat() if performed_at_from else None,
        performed_at_to=performed_at_to.isoformat() if performed_at_to else None,
        mobile=mobile,
        lead_stage=lead_stage,
        lead_is_active=lead_is_active,
        entity_type=et_scope,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
        role=role,
        emp_id=emp_id,
    )

    pool = await get_db_pool()
    async def _load_filtered_crm_activities():
        try:
            async with pool.acquire() as conn:
                valid_stages = await _fetch_valid_stage_codes(conn, et_scope or DEFAULT_CRM_ENTITY_TYPE)
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
                    where.append(f"upper(trim(a.old_stage)) = ${len(params)}")
                if new_stage is not None:
                    params.append(new_stage)
                    where.append(f"upper(trim(a.new_stage)) = ${len(params)}")
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
                    where.append(f"upper(trim(l.stage)) = ${len(params)}")
                if lead_is_active is not None:
                    params.append(lead_is_active)
                    where.append(f"l.is_active = ${len(params)}")
                if entity_id is not None:
                    params.append(entity_id)
                    where.append(f"l.entity_id = ${len(params)}")
                    et_val = _entity_type_query(entity_type)
                    params.append(et_val)
                    where.append(_crm_entity_type_match_sql(et_val, len(params)))
                elif entity_type is not None:
                    et_val = _entity_type_query(entity_type)
                    params.append(et_val)
                    where.append(_crm_entity_type_match_sql(et_val, len(params)))

                vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, len(params) + 1)
                if vis_sql:
                    where.append(vis_sql)
                    params.extend(vis_vals)

                base_from = f"""
                    FROM {DB_SCHEMA}.crm_activities a
                    INNER JOIN {DB_SCHEMA}.crm_leads l ON l.id = a.lead_id
                    LEFT JOIN {DB_SCHEMA}.employees lead_rm ON lead_rm.emp_id = l.rm_id
                    LEFT JOIN {DB_SCHEMA}.employees lead_op ON lead_op.emp_id = l.op_id
                """
                where_sql = " AND ".join(where)
                count_params = list(params)
                n = len(params)
                list_params = list(params) + [limit, offset]

                count_sql = f"SELECT COUNT(*) {base_from} WHERE {where_sql}"
                list_sql = f"""
                    SELECT a.*,
                           lead_rm.first_name AS lead_rm_name,
                           lead_op.first_name AS lead_op_name
                    {base_from}
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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_filtered_crm_activities,
        ttl_seconds=300,
        tags=[_crm_activities_filter_tag()],
    )


async def _svc_get_crm_lead_stages(
    entity_type: Optional[str] = Query(None, description="Defaults to GST_REGISTRATION."),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
) -> CRMLeadStagesOut:
    role, emp_id = _get_user_context(current_user)
    et = _entity_type_query(entity_type)
    cache_key = build_cache_key("crm:stages", entity_type=et, role=role, emp_id=emp_id)
    pool = await get_db_pool()

    async def _load_crm_stages():
        try:
            async with pool.acquire() as conn:
                try:
                    rows = await conn.fetch(
                        f"""
                        SELECT id, code, name, sort_order
                        FROM {DB_SCHEMA}.crm_lead_stages
                        WHERE is_active
                          AND (entity_type = $1 OR entity_type IS NULL)
                        ORDER BY sort_order, code
                        """,
                        et,
                    )
                except asyncpg.UndefinedColumnError:
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
            entity_type=et,
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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_crm_stages,
        ttl_seconds=300,
        tags=[_crm_stages_tag()],
    )


async def _svc_get_crm_lead_by_entity(
    entity_id: Optional[int] = Query(None, ge=1, description="crm_leads.entity_id."),
    entity_type: Optional[str] = Query(
        None,
        description="crm_leads.entity_type (e.g. GST_REGISTRATION, INCOME_TAX). When entity_id is set and this is omitted, defaults to GST_REGISTRATION.",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """Return the latest active visible CRM lead matching optional entity_id / entity_type (at least one required)."""
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    if entity_id is None and entity_type is None:
        raise _validation_error(
            "Provide entity_id and/or entity_type.",
            {
                "entity_id": "At least one of entity_id or entity_type is required.",
                "entity_type": "At least one of entity_id or entity_type is required.",
            },
        )

    et_for_cache = _entity_type_query(entity_type) if entity_type is not None else None
    if entity_id is not None and entity_type is None:
        et_for_cache = _entity_type_query(None)
    cache_key = build_cache_key(
        "crm:lead:by_entity:v2",
        entity_type=et_for_cache,
        entity_id=entity_id,
        role=role,
        emp_id=emp_id,
    )
    pool = await get_db_pool()

    async def _load_crm_lead_by_entity():
        try:
            async with pool.acquire() as conn:
                where = ["l.is_active = TRUE"]
                params: list = []
                if entity_id is not None:
                    params.append(entity_id)
                    where.append(f"l.entity_id = ${len(params)}")
                    et_val = _entity_type_query(entity_type)
                    params.append(et_val)
                    where.append(_crm_entity_type_match_sql(et_val, len(params)))
                elif entity_type is not None:
                    et_val = _entity_type_query(entity_type)
                    params.append(et_val)
                    where.append(_crm_entity_type_match_sql(et_val, len(params)))

                vis_sql, vis_vals, _ = _build_crm_visibility(role, emp_id, len(params) + 1)
                if vis_sql:
                    where.append(vis_sql)
                    params.extend(vis_vals)

                row = await conn.fetchrow(
                    f"""
                    SELECT l.*,
                           erm.first_name AS rm_name,
                           eop.first_name AS op_name
                    FROM {DB_SCHEMA}.crm_leads l
                    LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = l.rm_id
                    LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = l.op_id
                    WHERE {' AND '.join(where)}
                    ORDER BY l.updated_at DESC NULLS LAST, l.id DESC
                    LIMIT 1
                    """,
                    *params,
                )
                if not row:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")
                return dict(row)
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            logger.exception("Database error while fetching CRM lead by entity")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_crm_lead_by_entity,
        ttl_seconds=300,
        tags=[_crm_lead_by_entity_tag()],
    )




async def _svc_list_crm_lead_call_activities(
    lead_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = None,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """CALL rows only: last_dailed_at, last_connected_at, call_status_code, call_type_code, old/new stage."""
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    cache_key = build_cache_key(
        "crm:lead:calls",
        lead_id=lead_id,
        limit=limit,
        offset=offset,
        entity_type=_entity_type_query(entity_type) if entity_type else None,
        role=role,
        emp_id=emp_id,
    )
    pool = await get_db_pool()
    async def _load_crm_lead_call_activities():
        try:
            async with pool.acquire() as conn:
                lead = await _fetch_crm_lead_visible(
                    conn,
                    role,
                    emp_id,
                    lead_id,
                    entity_type=entity_type,
                )
                if not lead:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")

                sql_calls_with_ts = f"""
                    SELECT
                        a.id,
                        a.lead_id,
                        a.activity_type,
                        a.call_type_code,
                        a.call_status_code,
                        a.old_stage,
                        a.new_stage,
                        a.followup_at,
                        a.remarks,
                        a.performed_by,
                        e.first_name AS performed_by_first_name,
                        a.performed_at,
                        a.created_at,
                        a.last_dailed_at,
                        a.last_connected_at
                    FROM {DB_SCHEMA}.crm_activities a
                    LEFT JOIN {DB_SCHEMA}.employees e ON e.emp_id = a.performed_by
                    WHERE a.lead_id = $1
                      AND a.activity_type = 'CALL'
                    ORDER BY a.performed_at DESC, a.id DESC
                    LIMIT $2 OFFSET $3
                    """
                sql_calls_no_ts = f"""
                    SELECT
                        a.id,
                        a.lead_id,
                        a.activity_type,
                        a.call_type_code,
                        a.call_status_code,
                        a.old_stage,
                        a.new_stage,
                        a.followup_at,
                        a.remarks,
                        a.performed_by,
                        e.first_name AS performed_by_first_name,
                        a.performed_at,
                        a.created_at
                    FROM {DB_SCHEMA}.crm_activities a
                    LEFT JOIN {DB_SCHEMA}.employees e ON e.emp_id = a.performed_by
                    WHERE a.lead_id = $1
                      AND a.activity_type = 'CALL'
                    ORDER BY a.performed_at DESC, a.id DESC
                    LIMIT $2 OFFSET $3
                    """
                try:
                    rows = await conn.fetch(sql_calls_with_ts, lead_id, limit, offset)
                except asyncpg.UndefinedColumnError:
                    rows = await conn.fetch(sql_calls_no_ts, lead_id, limit, offset)
                    rows = [
                        {**dict(r), "last_dailed_at": None, "last_connected_at": None}
                        for r in rows
                    ]
                else:
                    rows = [dict(r) for r in rows]

                return {
                    "lead_id": lead_id,
                    "items": rows,
                    "limit": limit,
                    "offset": offset,
                }
        except asyncpg.PostgresError:
            logger.exception("Database error while fetching CRM call activities")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_crm_lead_call_activities,
        ttl_seconds=300,
        tags=[_crm_lead_calls_tag(lead_id)],
    )


async def _svc_list_crm_lead_stage_activity_history(
    lead_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = None,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """Rows where old_stage and new_stage differ (calls that moved stage, SYSTEM moves, etc.)."""
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    cache_key = build_cache_key(
        "crm:lead:stage_history",
        lead_id=lead_id,
        limit=limit,
        offset=offset,
        entity_type=_entity_type_query(entity_type) if entity_type else None,
        role=role,
        emp_id=emp_id,
    )
    pool = await get_db_pool()
    async def _load_crm_lead_stage_history():
        try:
            async with pool.acquire() as conn:
                lead = await _fetch_crm_lead_visible(
                    conn,
                    role,
                    emp_id,
                    lead_id,
                    entity_type=entity_type,
                )
                if not lead:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")

                sql_stage_with_ts = f"""
                SELECT
                    a.id,
                    a.lead_id,
                    a.activity_type,
                    a.call_type_code,
                    a.call_status_code,
                    a.old_stage,
                    a.new_stage,
                    a.followup_at,
                    a.remarks,
                    a.performed_by,
                    e.first_name AS performed_by_first_name,
                    a.performed_at,
                    a.created_at,
                    a.last_dailed_at,
                    a.last_connected_at
                FROM {DB_SCHEMA}.crm_activities a
                LEFT JOIN {DB_SCHEMA}.employees e ON e.emp_id = a.performed_by
                WHERE a.lead_id = $1
                  AND a.old_stage IS DISTINCT FROM a.new_stage
                ORDER BY a.performed_at DESC, a.id DESC
                LIMIT $2 OFFSET $3
                """
                sql_stage_no_ts = f"""
                SELECT
                    a.id,
                    a.lead_id,
                    a.activity_type,
                    a.call_type_code,
                    a.call_status_code,
                    a.old_stage,
                    a.new_stage,
                    a.followup_at,
                    a.remarks,
                    a.performed_by,
                    e.first_name AS performed_by_first_name,
                    a.performed_at,
                    a.created_at
                FROM {DB_SCHEMA}.crm_activities a
                LEFT JOIN {DB_SCHEMA}.employees e ON e.emp_id = a.performed_by
                WHERE a.lead_id = $1
                  AND a.old_stage IS DISTINCT FROM a.new_stage
                ORDER BY a.performed_at DESC, a.id DESC
                LIMIT $2 OFFSET $3
                """
                try:
                    rows = await conn.fetch(sql_stage_with_ts, lead_id, limit, offset)
                except asyncpg.UndefinedColumnError:
                    rows = await conn.fetch(sql_stage_no_ts, lead_id, limit, offset)
                    rows = [
                        {**dict(r), "last_dailed_at": None, "last_connected_at": None}
                        for r in rows
                    ]
                else:
                    rows = [dict(r) for r in rows]

                return {
                    "lead_id": lead_id,
                    "items": rows,
                    "limit": limit,
                    "offset": offset,
                }
        except asyncpg.PostgresError:
            logger.exception("Database error while fetching CRM stage activity history")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_crm_lead_stage_history,
        ttl_seconds=300,
        tags=[_crm_lead_stage_history_tag(lead_id)],
    )


async def _svc_list_crm_activities(
    lead_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = None,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    cache_key = build_cache_key(
        "crm:lead:activities",
        lead_id=lead_id,
        limit=limit,
        offset=offset,
        entity_type=_entity_type_query(entity_type) if entity_type else None,
        role=role,
        emp_id=emp_id,
    )
    pool = await get_db_pool()
    async def _load_crm_activities():
        try:
            async with pool.acquire() as conn:
                lead = await _fetch_crm_lead_visible(
                    conn,
                    role,
                    emp_id,
                    lead_id,
                    entity_type=entity_type,
                )
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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_crm_activities,
        ttl_seconds=300,
        tags=[_crm_lead_activities_tag(lead_id)],
    )




def _append_crm_followup_scope_conditions(
    conditions: list,
    values: list,
    idx: int,
    *,
    range_start: datetime,
    range_end: datetime,
    date_keys: Optional[list],
    entity_type: str,
    category: str,
    stage: Optional[str],
    role,
    emp_id,
    follow_up_status: Optional[str] = None,
) -> int:
    """Shared WHERE fragments for CRM follow-up counts, list, and alerts."""
    cat = _normalize_crm_followup_category(category)
    stage_norm = _normalize_code(stage) if isinstance(stage, str) and stage.strip() else None
    et_filter = _entity_type_query(entity_type)

    conditions.extend(
        [
            "l.followup_at IS NOT NULL",
            "l.is_active = TRUE",
            f"l.followup_at >= ${idx}",
            f"l.followup_at <= ${idx + 1}",
        ]
    )
    values.extend([range_start, range_end])
    idx += 2

    if date_keys:
        conditions.append(
            f"to_char(l.followup_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD') = ANY(${idx}::text[])"
        )
        values.append(date_keys)
        idx += 1

    if cat == "payment":
        conditions.append(f"upper(trim(l.stage)) = ANY(${idx}::text[])")
        values.append(list(CRM_PAYMENT_FOLLOWUP_STAGES))
    else:
        conditions.append(f"upper(trim(l.stage)) = ANY(${idx}::text[])")
        values.append(list(CRM_SERVICE_FOLLOWUP_STAGES))
    idx += 1

    if stage_norm:
        conditions.append(f"upper(trim(l.stage)) = ${idx}")
        values.append(stage_norm)
        idx += 1

    if follow_up_status:
        conditions.append(f"upper(trim(COALESCE(l.follow_up_status, 'PENDING'))) = ${idx}")
        values.append(follow_up_status)
        idx += 1

    values.append(et_filter)
    conditions.append(_crm_entity_type_match_sql(et_filter, idx))
    idx += 1

    vis_sql, vis_vals, idx = _build_crm_visibility(role, emp_id, idx)
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_vals)

    return idx


async def _svc_crm_followup_counts(
    *,
    followup_from: Optional[datetime],
    followup_to: Optional[datetime],
    dates: Optional[str],
    entity_type: str,
    category: str,
    stage: Optional[str],
    current_user,
):
    """Dashboard KPI counts for CRM lead follow-ups (aligned with payment/service follow-up /counts)."""
    request_id = generate_uuid()
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)

    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    range_start = followup_from if followup_from is not None else today_start
    range_end = followup_to if followup_to is not None else today_end
    if range_start > range_end:
        raise _validation_error(
            "Invalid followup range.",
            {"followup_from": "followup_from must be <= followup_to."},
        )

    date_keys = None
    if isinstance(dates, str) and dates.strip():
        date_keys = sorted({d.strip() for d in dates.split(",") if d.strip()})

    cat = _normalize_crm_followup_category(category)
    et_filter = _entity_type_query(entity_type)
    stage_norm = _normalize_code(stage) if isinstance(stage, str) and stage.strip() else None

    cache_key = build_cache_key(
        "crm:leads:followup_counts",
        role=role,
        emp_id=emp_id,
        followup_from=range_start,
        followup_to=range_end,
        dates=tuple(date_keys) if date_keys else None,
        entity_type=et_filter,
        category=cat,
        stage=stage_norm,
    )

    pool = await get_db_pool()

    async def _load_counts():
        conditions: list = []
        values: list = []
        idx = 1
        idx = _append_crm_followup_scope_conditions(
            conditions,
            values,
            idx,
            range_start=range_start,
            range_end=range_end,
            date_keys=date_keys,
            entity_type=entity_type,
            category=cat,
            stage=stage_norm,
            role=role,
            emp_id=emp_id,
        )

        where_clause = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT
                COUNT(*) AS scheduled_today,
                COUNT(*) FILTER (
                    WHERE l.followup_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                       OR l.completed_at IS NOT NULL
                ) AS evaluated_today,
                COUNT(*) FILTER (
                    WHERE l.missed_at IS NOT NULL
                      AND l.completed_at IS NULL
                ) AS overdue_pending_today,
                COUNT(*) FILTER (
                    WHERE l.missed_at IS NOT NULL
                      AND l.completed_at IS NOT NULL
                ) AS overdue_completed_today,
                COUNT(*) FILTER (
                    WHERE l.completed_at IS NOT NULL
                      AND l.missed_at IS NULL
                ) AS completed_today,
                COUNT(*) FILTER (
                    WHERE l.completed_at IS NOT NULL
                      AND l.missed_at IS NULL
                ) AS successful_today,
                COUNT(*) FILTER (
                    WHERE l.completed_at IS NULL
                      AND l.missed_at IS NULL
                      AND upper(trim(COALESCE(l.follow_up_status, 'PENDING'))) = 'PENDING'
                      AND l.followup_at IS NOT NULL
                      AND l.followup_at <= NOW()
                      AND l.followup_at > NOW() - INTERVAL '10 minutes'
                ) AS pending_today
            FROM {DB_SCHEMA}.crm_leads l
            {where_clause}
        """

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *values)
        except asyncpg.PostgresError:
            logger.exception("DB error while fetching CRM follow-up counts")
            raise HTTPException(status_code=500, detail="Database error occurred")
        except Exception:
            logger.exception("Unexpected error while fetching CRM follow-up counts")
            raise HTTPException(status_code=500, detail="Internal server error")

        res_data = dict(row)
        res_data["overdue_today"] = res_data.get("overdue_pending_today", 0)
        scheduled = res_data.get("scheduled_today", 0)
        successful = res_data.get("successful_today", 0)
        res_data["success_rate"] = (
            round((successful / scheduled) * 100) if scheduled > 0 else 100
        )
        return {"data": res_data, "request_id": request_id}

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_counts,
        ttl_seconds=CACHE_TTL_COUNTS,
        tags=[_crm_followup_counts_tag()],
    )


async def _svc_crm_followup_list(
    *,
    followup_from: Optional[datetime],
    followup_to: Optional[datetime],
    dates: Optional[str],
    entity_type: str,
    category: str,
    stage: Optional[str],
    follow_up_status: Optional[str],
    limit: int,
    offset: int,
    current_user,
):
    """Paginated CRM lead follow-ups for dashboard scheduled list (aligned with main follow-ups list)."""
    request_id = generate_uuid()
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)

    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    range_start = followup_from if followup_from is not None else today_start
    range_end = followup_to if followup_to is not None else today_end
    if range_start > range_end:
        raise _validation_error(
            "Invalid followup range.",
            {"followup_from": "followup_from must be <= followup_to."},
        )

    date_keys = None
    if isinstance(dates, str) and dates.strip():
        date_keys = sorted({d.strip() for d in dates.split(",") if d.strip()})

    cat = _normalize_crm_followup_category(category)
    et_filter = _entity_type_query(entity_type)
    stage_norm = _normalize_code(stage) if isinstance(stage, str) and stage.strip() else None
    status_norm = (
        _normalize_code(follow_up_status)
        if isinstance(follow_up_status, str) and follow_up_status.strip()
        else None
    )
    if status_norm and status_norm not in FOLLOWUP_STATUSES:
        raise _validation_error(
            "Invalid follow_up_status filter.",
            {"follow_up_status": "Unsupported follow-up status value."},
        )

    cache_key = build_cache_key(
        "crm:leads:followup_list",
        role=role,
        emp_id=emp_id,
        followup_from=range_start,
        followup_to=range_end,
        dates=tuple(date_keys) if date_keys else None,
        entity_type=et_filter,
        category=cat,
        stage=stage_norm,
        follow_up_status=status_norm,
        limit=limit,
        offset=offset,
    )

    pool = await get_db_pool()

    async def _load_list():
        conditions: list = []
        values: list = []
        idx = 1
        idx = _append_crm_followup_scope_conditions(
            conditions,
            values,
            idx,
            range_start=range_start,
            range_end=range_end,
            date_keys=date_keys,
            entity_type=entity_type,
            category=cat,
            stage=stage_norm,
            role=role,
            emp_id=emp_id,
            follow_up_status=status_norm,
        )

        where_clause = f"WHERE {' AND '.join(conditions)}"
        lim_idx = idx
        off_idx = idx + 1

        query = f"""
            SELECT
                l.*,
                erm.first_name AS rm_name,
                eop.first_name AS op_name,
                COUNT(*) OVER()::bigint AS total_count
            FROM {DB_SCHEMA}.crm_leads l
            LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = l.rm_id
            LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = l.op_id
            {where_clause}
            ORDER BY l.followup_at ASC NULLS LAST, l.id DESC
            LIMIT ${lim_idx} OFFSET ${off_idx}
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values, limit, offset)
                total = int(rows[0]["total_count"]) if rows else 0
        except asyncpg.PostgresError:
            logger.exception("DB error while listing CRM follow-ups")
            raise HTTPException(status_code=500, detail="Database error occurred")
        except Exception:
            logger.exception("Unexpected error while listing CRM follow-ups")
            raise HTTPException(status_code=500, detail="Internal server error")

        items = []
        for row in rows:
            row_dict = dict(row)
            row_dict.pop("total_count", None)
            items.append(row_dict)

        return {
            "data": items,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_list,
        ttl_seconds=CACHE_TTL_LIST,
        tags=[_crm_followup_list_tag()],
    )


async def _svc_crm_followup_alerts(
    *,
    entity_type: str,
    category: str,
    stage: Optional[str],
    current_user,
):
    """CRM lead follow-up alerts due within the next 24 hours (aligned with main /alerts)."""
    request_id = generate_uuid()
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)

    now = datetime.now(timezone.utc)
    next_24h = now + timedelta(hours=24)
    time_bucket = int(now.timestamp() // 300)

    cat = _normalize_crm_followup_category(category)
    et_filter = _entity_type_query(entity_type)
    stage_norm = _normalize_code(stage) if isinstance(stage, str) and stage.strip() else None

    cache_key = build_cache_key(
        "crm:leads:followup_alerts",
        role=role,
        emp_id=emp_id,
        entity_type=et_filter,
        category=cat,
        stage=stage_norm,
        time_bucket=time_bucket,
    )

    pool = await get_db_pool()

    async def _load_alerts():
        conditions: list = [
            "l.followup_at IS NOT NULL",
            "l.is_active = TRUE",
            "upper(trim(COALESCE(l.follow_up_status, 'PENDING'))) IN ('PENDING', 'MISSED')",
            f"l.followup_at >= ${1}",
            f"l.followup_at <= ${2}",
        ]
        values: list = [now, next_24h]
        idx = 3

        if cat == "payment":
            conditions.append(f"upper(trim(l.stage)) = ANY(${idx}::text[])")
            values.append(list(CRM_PAYMENT_FOLLOWUP_STAGES))
        else:
            conditions.append(f"upper(trim(l.stage)) = ANY(${idx}::text[])")
            values.append(list(CRM_SERVICE_FOLLOWUP_STAGES))
        idx += 1

        if stage_norm:
            conditions.append(f"upper(trim(l.stage)) = ${idx}")
            values.append(stage_norm)
            idx += 1

        values.append(et_filter)
        conditions.append(_crm_entity_type_match_sql(et_filter, idx))
        idx += 1

        vis_sql, vis_vals, idx = _build_crm_visibility(role, emp_id, idx)
        if vis_sql:
            conditions.append(vis_sql)
            values.extend(vis_vals)

        where_clause = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT
                l.*,
                erm.first_name AS rm_name,
                eop.first_name AS op_name
            FROM {DB_SCHEMA}.crm_leads l
            LEFT JOIN {DB_SCHEMA}.employees erm ON erm.emp_id = l.rm_id
            LEFT JOIN {DB_SCHEMA}.employees eop ON eop.emp_id = l.op_id
            {where_clause}
            ORDER BY l.followup_at ASC
            LIMIT 50
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values)
        except asyncpg.PostgresError:
            logger.exception("DB error while fetching CRM follow-up alerts")
            raise HTTPException(status_code=500, detail="Database error occurred")
        except Exception:
            logger.exception("Unexpected error while fetching CRM follow-up alerts")
            raise HTTPException(status_code=500, detail="Internal server error")

        return {
            "data": [dict(r) for r in rows],
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_alerts,
        ttl_seconds=CACHE_TTL_ALERTS,
        tags=[_crm_followup_alerts_tag()],
    )


router = APIRouter(prefix="/api/v1/crm/leads", tags=["CRM Leads Common"])


@router.get(
    "/followups/counts",
    summary="CRM lead follow-up dashboard counts for selected date range",
)
async def get_crm_lead_followup_counts(
    followup_from: Optional[datetime] = Query(None),
    followup_to: Optional[datetime] = Query(None),
    dates: Optional[str] = Query(
        None,
        description="Comma-separated YYYY-MM-DD keys; when set, only those calendar days are counted",
    ),
    entity_type: str = Query(...),
    category: str = Query("service", description="service or payment follow-up tab"),
    stage: Optional[str] = Query(None, description="Optional stage filter (service tab)"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_crm_followup_counts(
        followup_from=followup_from,
        followup_to=followup_to,
        dates=dates,
        entity_type=entity_type,
        category=category,
        stage=stage,
        current_user=current_user,
    )


@router.get(
    "/followups",
    summary="List CRM lead follow-ups for dashboard scheduled panel",
)
async def list_crm_lead_followups(
    followup_from: Optional[datetime] = Query(None),
    followup_to: Optional[datetime] = Query(None),
    dates: Optional[str] = Query(
        None,
        description="Comma-separated YYYY-MM-DD keys; when set, only those calendar days are included",
    ),
    entity_type: str = Query(...),
    category: str = Query("service", description="service or payment follow-up tab"),
    stage: Optional[str] = Query(None, description="Optional stage filter (service tab)"),
    follow_up_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_crm_followup_list(
        followup_from=followup_from,
        followup_to=followup_to,
        dates=dates,
        entity_type=entity_type,
        category=category,
        stage=stage,
        follow_up_status=follow_up_status,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get(
    "/followups/alerts",
    summary="CRM lead follow-up alerts (due within 24h)",
)
async def get_crm_lead_followup_alerts(
    entity_type: str = Query(...),
    category: str = Query("service", description="service or payment follow-up tab"),
    stage: Optional[str] = Query(None, description="Optional stage filter (service tab)"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_crm_followup_alerts(
        entity_type=entity_type,
        category=category,
        stage=stage,
        current_user=current_user,
    )


@router.post(
    "/marketing",
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM lead from digital marketing (public API key)",
)
async def create_crm_lead_marketing(request: Request, payload: CRMLeadMarketingCreateIn):
    """
    Inserts ``crm_leads`` only — no gst_registration or income_tax row.
    Always sets ``stage=FRESH_LEAD``, ``is_active=true``, ``follow_up_status=PENDING``, ``entity_id=NULL``.
    """
    await enforce_public_security(
        request=request,
        bucket="crm_lead_marketing_create",
        max_requests=25,
        window_seconds=60,
        block_seconds=300,
    )
    entity_norm = _normalize_code(str(payload.entity_type))
    mobile = payload.mobile.strip()
    full_name_val = payload.full_name.strip()[:200]
    lead_type_u = payload.lead_type.strip().upper()[:50]
    lead_source_u = payload.lead_source.strip().upper()[:100]
    tag_v = payload.tag.strip()[:100]
    preferred_lang = payload.preferred_language.strip()[:50]
    ay_val = _normalize_ay(payload.ay)

    remarks = payload.remarks
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            valid_stages = await _fetch_valid_stage_codes(conn, entity_norm)
            if valid_stages and "FRESH_LEAD" not in valid_stages:
                raise _validation_error(
                    "Stage configuration missing.",
                    {
                        "entity_type": (
                            f"FRESH_LEAD must be configured for {entity_norm} in crm_lead_stages."
                        )
                    },
                )
            # Dedup (mobile + entity_type): a public marketing form must not be
            # able to spawn unlimited duplicate leads for the same person. This
            # mirrors the bulk-upload path which skips duplicates. If an active
            # lead already exists we return it idempotently instead of inserting.
            async with conn.transaction():
                existing_lead = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.crm_leads
                    WHERE trim(mobile) = trim($1)
                      AND entity_type = $2
                      AND is_active = TRUE
                    ORDER BY id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    mobile,
                    entity_norm,
                )
                if existing_lead is not None:
                    lead_dict = dict(existing_lead)
                    await _invalidate_crm_cache(existing_lead["id"])
                    return {
                        "message": "CRM lead already exists.",
                        "lead_id": existing_lead["id"],
                        "lead": lead_dict,
                        "duplicate": True,
                    }
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.crm_leads (
                        mobile,
                        full_name,
                        email,
                        entity_id,
                        entity_type,
                        preferred_language,
                        stage,
                        follow_up_status,
                        rm_id,
                        op_id,
                        rm_assigned_at,
                        op_assigned_at,
                        remarks,
                        is_active,
                        lead_type,
                        tag,
                        lead_source,
                        ay,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1, $2, $3, NULL, $4, $5,
                        'FRESH_LEAD',
                        'PENDING',
                        NULL,
                        NULL,
                        NULL,
                        NULL,
                        $6,
                        TRUE,
                        $7,
                        $8,
                        $9,
                        $10,
                        NOW(),
                        NOW()
                    )
                    RETURNING *
                    """,
                    mobile,
                    full_name_val,
                    payload.email,
                    entity_norm,
                    preferred_lang,
                    remarks,
                    lead_type_u,
                    tag_v,
                    lead_source_u,
                    ay_val,
                )
    except HTTPException:
        raise
    except asyncpg.UndefinedColumnError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Database is missing CRM lead columns "
                "(expected full_name / email / preferred_language columns on crm_leads where applicable). "
                f"PostgreSQL hint: {getattr(exc, 'column_name', exc)}."
            ),
        )
    except asyncpg.PostgresError:
        logger.exception("Database error creating marketing CRM lead")
        raise HTTPException(status_code=500, detail="Database error.")

    lead_id = row["id"]
    await _invalidate_crm_cache(lead_id)

    lead_dict = dict(row)

    return {
        "message": "CRM lead created.",
        "lead_id": lead_id,
        "lead": lead_dict,
    }


@router.get("/ui-mappings", summary="CRM stage/pitch and pitch/status mappings for UI")
async def get_crm_stage_pitch_mappings(
    entity_type: str = Query(...),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_get_crm_stage_pitch_mappings(entity_type=entity_type, current_user=current_user)


@router.get("/filter", summary="Filter CRM leads")
async def filter_crm_leads(
    stage: Optional[str] = None,
    stages: Optional[List[str]] = Query(None, description="Filter by multiple stages (OR logic)."),
    follow_up_status: Optional[str] = None,
    mobile: Optional[str] = None,
    full_name: Optional[str] = Query(None, description="Fuzzy match on lead full_name."),
    email: Optional[str] = Query(None, description="Partial match on lead email."),
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    lead_type: Optional[str] = None,
    tag: Optional[str] = None,
    lead_source: Optional[str] = None,
    remarks: Optional[str] = Query(
        None,
        description="Filter crm_leads.remarks (case-insensitive contains).",
    ),
    is_active: Optional[bool] = None,
    followup_at_from: Optional[datetime] = Query(None),
    followup_at_to: Optional[datetime] = Query(None),
    rm_assigned_at_from: Optional[datetime] = Query(None),
    rm_assigned_at_to: Optional[datetime] = Query(None),
    op_assigned_at_from: Optional[datetime] = Query(None),
    op_assigned_at_to: Optional[datetime] = Query(None),
    last_dailed_at_from: Optional[datetime] = Query(None),
    last_dailed_at_to: Optional[datetime] = Query(None),
    last_connected_at_from: Optional[datetime] = Query(None),
    last_connected_at_to: Optional[datetime] = Query(None),
    entity_type: str = Query(...),
    entity_id: Optional[int] = Query(None, ge=1),
    ay: Optional[str] = Query(None, description="Filter by assessment year (exact match)."),
    smart_board: bool = Query(False, description="Smart Board stage filter and priority sort."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_filter_crm_leads(
        stage=stage,
        stages=stages,
        follow_up_status=follow_up_status,
        mobile=mobile,
        full_name=full_name,
        email=email,
        rm_id=rm_id,
        op_id=op_id,
        lead_type=lead_type,
        tag=tag,
        lead_source=lead_source,
        remarks=remarks,
        is_active=is_active,
        followup_at_from=followup_at_from,
        followup_at_to=followup_at_to,
        rm_assigned_at_from=rm_assigned_at_from,
        rm_assigned_at_to=rm_assigned_at_to,
        op_assigned_at_from=op_assigned_at_from,
        op_assigned_at_to=op_assigned_at_to,
        last_dailed_at_from=last_dailed_at_from,
        last_dailed_at_to=last_dailed_at_to,
        last_connected_at_from=last_connected_at_from,
        last_connected_at_to=last_connected_at_to,
        entity_type=entity_type,
        entity_id=entity_id,
        ay=ay,
        smart_board=smart_board,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get(
    "/smart-board",
    summary="CRM Smart Board leads (priority stage order)",
)
async def smart_board_crm_leads(
    follow_up_status: Optional[str] = None,
    mobile: Optional[str] = None,
    full_name: Optional[str] = Query(None, description="Fuzzy match on lead full_name."),
    email: Optional[str] = Query(None, description="Partial match on lead email."),
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    lead_type: Optional[str] = None,
    tag: Optional[str] = None,
    lead_source: Optional[str] = None,
    remarks: Optional[str] = Query(None),
    is_active: Optional[bool] = True,
    followup_at_from: Optional[datetime] = Query(None),
    followup_at_to: Optional[datetime] = Query(None),
    rm_assigned_at_from: Optional[datetime] = Query(None),
    rm_assigned_at_to: Optional[datetime] = Query(None),
    op_assigned_at_from: Optional[datetime] = Query(None),
    op_assigned_at_to: Optional[datetime] = Query(None),
    last_dailed_at_from: Optional[datetime] = Query(None),
    last_dailed_at_to: Optional[datetime] = Query(None),
    last_connected_at_from: Optional[datetime] = Query(None),
    last_connected_at_to: Optional[datetime] = Query(None),
    entity_type: str = Query(...),
    ay: Optional[str] = Query(None, description="Filter by assessment year (exact match)."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Early-funnel leads only. Sort: stage priority, then call tier (0-0 → N-0 → N-N → other), then recency.
    """
    return await _svc_filter_crm_leads(
        follow_up_status=follow_up_status,
        mobile=mobile,
        full_name=full_name,
        email=email,
        rm_id=rm_id,
        op_id=op_id,
        lead_type=lead_type,
        tag=tag,
        lead_source=lead_source,
        remarks=remarks,
        is_active=is_active,
        followup_at_from=followup_at_from,
        followup_at_to=followup_at_to,
        rm_assigned_at_from=rm_assigned_at_from,
        rm_assigned_at_to=rm_assigned_at_to,
        op_assigned_at_from=op_assigned_at_from,
        op_assigned_at_to=op_assigned_at_to,
        last_dailed_at_from=last_dailed_at_from,
        last_dailed_at_to=last_dailed_at_to,
        last_connected_at_from=last_connected_at_from,
        last_connected_at_to=last_connected_at_to,
        entity_type=entity_type,
        ay=ay,
        smart_board=True,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.post(
    "/bulk-import/file",
    summary="Bulk import CRM leads by CSV/XLSX upload",
)
@router.post(
    "/import",
    summary="Bulk import CRM leads by CSV/XLSX upload (CRM UI)",
    include_in_schema=True,
)
async def bulk_import_crm_leads_file(
    file: UploadFile = File(...),
    validate_only: bool = Form(False),
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    filename = (file.filename or "").lower()
    if not filename:
        raise _validation_error("Invalid file.", {"file": "Filename is required."})

    raw = await file.read()
    if not raw:
        raise _validation_error("Invalid file.", {"file": "Uploaded file is empty."})

    is_csv = filename.endswith(".csv")
    is_xlsx = filename.endswith(".xlsx")
    is_pdf = filename.endswith(".pdf")

    if is_pdf:
        raise _validation_error(
            "PDF import is not supported yet.",
            {"file": "Please convert PDF table to CSV/XLSX and re-upload."},
        )
    if not (is_csv or is_xlsx):
        raise _validation_error(
            "Unsupported file format.",
            {"file": "Only .csv and .xlsx files are supported."},
        )

    try:
        if is_csv:
            df = pd.read_csv(io.BytesIO(raw))
        else:
            df = pd.read_excel(io.BytesIO(raw))
    except Exception as ex:
        raise _validation_error("Failed to parse file.", {"file": str(ex)})

    if df.empty:
        raise _validation_error("No rows found.", {"file": "Sheet has no data rows."})

    normalized_cols = {
        str(c).strip().lower().replace(" ", "_"): c
        for c in df.columns
    }
    df = df.rename(columns={orig: norm for norm, orig in normalized_cols.items()})

    required = {
        "mobile",
        "entity_type",
        "preferred_language",
        "lead_type",
    }
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise _validation_error(
            "Missing required sheet columns.",
            {"columns": f"Missing: {', '.join(missing)}"},
        )

    allowed = {
        "mobile",
        "full_name",
        "email",
        "stage",
        "followup_at",
        "rm_id",
        "op_id",
        "remarks",
        "is_active",
        "follow_up_status",
        "entity_type",
        "entity_id",
        "preferred_language",
        "lead_type",
        "tag",
        "lead_source",
        "ay",
    }

    rows = []
    for idx, rec in enumerate(df.to_dict(orient="records"), start=1):
        try:
            row = {}
            for k, v in rec.items():
                if k not in allowed:
                    continue
                if isinstance(v, float) and pd.isna(v):
                    v = None
                elif pd.isna(v):
                    v = None
                row[k] = v

            row["mobile"] = None if row.get("mobile") is None else str(row["mobile"]).strip()
            if row["mobile"] and row["mobile"].endswith(".0") and row["mobile"][:-2].isdigit():
                row["mobile"] = row["mobile"][:-2]
            row["stage"] = None if row.get("stage") is None else str(row["stage"]).strip()
            row["followup_at"] = None if row.get("followup_at") in (None, "") else row["followup_at"]
            row["rm_id"] = _parse_optional_int(row.get("rm_id"))
            row["op_id"] = _parse_optional_int(row.get("op_id"))
            row["remarks"] = None if row.get("remarks") is None else str(row["remarks"]).strip()
            row["is_active"] = _parse_optional_bool(row.get("is_active"))
            row["follow_up_status"] = _csv_nullish_to_none(row.get("follow_up_status"))
            if row["follow_up_status"] is not None:
                row["follow_up_status"] = str(row["follow_up_status"]).strip().upper()
            row["entity_type"] = None if row.get("entity_type") is None else str(row["entity_type"]).strip()
            row["preferred_language"] = (
                None
                if row.get("preferred_language") in (None, "")
                else str(row["preferred_language"]).strip()
            )
            row["entity_id"] = _parse_optional_int(row.get("entity_id"))
            row["lead_type"] = _csv_nullish_to_none(row.get("lead_type"))
            if row["lead_type"] is not None:
                row["lead_type"] = str(row["lead_type"]).strip()
            row["tag"] = _csv_nullish_to_none(row.get("tag"))
            if row["tag"] is not None:
                row["tag"] = str(row["tag"]).strip()
            row["lead_source"] = _csv_nullish_to_none(row.get("lead_source"))
            if row["lead_source"] is not None:
                row["lead_source"] = str(row["lead_source"]).strip()
            email_raw = _csv_nullish_to_none(row.get("email"))
            row["email"] = str(email_raw).strip().lower() if email_raw is not None else None
            name_raw = _csv_nullish_to_none(row.get("full_name"))
            row["full_name"] = str(name_raw).strip()[:200] if name_raw is not None else None
            ay_raw = _csv_nullish_to_none(row.get("ay"))
            row["ay"] = _normalize_ay(str(ay_raw).strip()) if ay_raw is not None else None
            rows.append(row)
        except Exception as ex:
            raise _validation_error(
                "Invalid sheet row format.",
                {"row": f"Row {idx}: {str(ex)}"},
            )

    try:
        payload = CRMBulkImportIn(
            rows=rows,
            validate_only=validate_only,
        )
    except ValidationError as ex:
        raise _validation_error(
            "Invalid sheet data.",
            {"rows": ex.errors()},
        )
    return await _bulk_import_crm_leads(payload, current_user)


@router.get("/bulk-assign/candidates", summary="Get lead candidates for bulk assignment")
async def get_bulk_assign_candidates(
    stages: Optional[List[str]] = Query(None),
    rm_ids: Optional[List[int]] = Query(None),
    op_ids: Optional[List[int]] = Query(None),
    lead_types: Optional[List[str]] = Query(None),
    ays: Optional[List[str]] = Query(None, description="Filter by assessment year(s)."),
    tags: Optional[List[str]] = Query(None),
    lead_sources: Optional[List[str]] = Query(None),
    entity_types: List[str] = Query(...),
    follow_up_statuses: Optional[List[str]] = Query(None),
    null_fields: Optional[List[str]] = Query(None),
    not_null_fields: Optional[List[str]] = Query(None),
    is_active: Optional[bool] = None,
    match_mode: str = Query("AND", description="AND or OR across provided filters."),
    filter_mode: str = Query("IN", description="IN or NOT_IN for provided filter values."),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_get_bulk_assign_candidates(
        stages=stages,
        rm_ids=rm_ids,
        op_ids=op_ids,
        lead_types=lead_types,
        ays=ays,
        tags=tags,
        lead_sources=lead_sources,
        entity_types=entity_types,
        follow_up_statuses=follow_up_statuses,
        null_fields=null_fields,
        not_null_fields=not_null_fields,
        is_active=is_active,
        match_mode=match_mode,
        filter_mode=filter_mode,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.post("/bulk-assign/execute", summary="Assign selected leads to employees in round robin")
async def execute_bulk_assign(
    payload: CRMBulkAssignExecuteIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    return await _svc_execute_bulk_assign(payload=payload, current_user=current_user)


@router.get(
    "/bulk-assign/schedulers",
    summary="List saved auto-assign schedulers (all entities, or filter by entity_type)",
)
async def list_bulk_assign_schedulers(
    entity_type: Optional[str] = Query(
        None,
        description="Omit to list schedulers across all CRM entity types.",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    from backend.crm.crm_bulk_auto_assign import svc_list_bulk_assign_schedulers

    role, _ = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can view bulk-assign schedulers.")
    return await svc_list_bulk_assign_schedulers(entity_type)


@router.get(
    "/bulk-assign/schedulers/{scheduler_id}",
    summary="Get one auto-assign scheduler by id",
)
async def get_bulk_assign_scheduler(
    scheduler_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    from backend.crm.crm_bulk_auto_assign import svc_get_bulk_assign_scheduler

    role, _ = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can view bulk-assign schedulers.")
    return await svc_get_bulk_assign_scheduler(scheduler_id)


@router.put(
    "/bulk-assign/schedulers",
    summary="Create or update an auto-assign scheduler (omit id to add another without touching others)",
)
async def save_bulk_assign_scheduler(
    payload: CRMBulkAutoAssignConfigIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    from backend.crm.crm_bulk_auto_assign import svc_save_bulk_auto_assign_config

    role, emp_id = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can configure bulk-assign schedulers.")
    return await svc_save_bulk_auto_assign_config(payload, updated_by=emp_id)


@router.patch(
    "/bulk-assign/schedulers/{scheduler_id}/enabled",
    summary="Turn a saved auto-assign scheduler on or off",
)
async def patch_bulk_assign_scheduler_enabled(
    scheduler_id: int,
    payload: CRMBulkAutoAssignEnabledPatchIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    from backend.crm.crm_bulk_auto_assign import svc_toggle_bulk_assign_scheduler_enabled

    role, emp_id = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can configure bulk-assign schedulers.")
    return await svc_toggle_bulk_assign_scheduler_enabled(
        scheduler_id,
        enabled=payload.enabled,
        updated_by=emp_id,
    )


@router.delete(
    "/bulk-assign/schedulers/{scheduler_id}",
    summary="Remove an auto-assign scheduler (others unchanged)",
)
async def delete_bulk_assign_scheduler(
    scheduler_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    from backend.crm.crm_bulk_auto_assign import svc_delete_bulk_assign_scheduler

    role, emp_id = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can delete bulk-assign schedulers.")
    return await svc_delete_bulk_assign_scheduler(scheduler_id, updated_by=emp_id)


@router.post(
    "/bulk-assign/schedulers/{scheduler_id}/run",
    summary="Run one auto-assign scheduler immediately",
)
async def run_bulk_assign_scheduler_now(
    scheduler_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    from backend.crm.crm_bulk_auto_assign import run_auto_assign_scheduler, svc_get_bulk_assign_scheduler

    role, _ = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can trigger bulk-assign schedulers.")
    rule = await svc_get_bulk_assign_scheduler(scheduler_id)
    if not rule.get("enabled"):
        raise HTTPException(
            status_code=409,
            detail="Scheduler is disabled. Enable it and save, then run again.",
        )
    summary = await run_auto_assign_scheduler(scheduler_id, force=True)
    if summary is None:
        raise HTTPException(status_code=500, detail="Scheduler run did not produce a result.")
    rm_n = (summary.get("roles") or {}).get("RM", {}).get("total_assigned", 0)
    op_n = (summary.get("roles") or {}).get("OP", {}).get("total_assigned", 0)
    return {
        "message": f"Assigned {rm_n} as RM and {op_n} as OP from {summary.get('candidates_matched', 0)} matching leads.",
        "summary": summary,
    }


@router.get(
    "/bulk-assign/logs",
    summary="Assignment run history (AUTO + MANUAL)",
)
async def list_bulk_assign_logs(
    entity_type: Optional[str] = Query(None),
    run_type: Optional[str] = Query(None, description="AUTO or MANUAL"),
    scheduler_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    from backend.crm.crm_bulk_auto_assign import svc_list_bulk_assign_logs

    role, _ = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can view bulk-assign logs.")
    return await svc_list_bulk_assign_logs(
        entity_type=entity_type,
        run_type=run_type,
        scheduler_id=scheduler_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/bulk-assign/auto",
    summary="Legacy: first scheduler + list for entity type",
)
async def get_bulk_auto_assign_config(
    entity_type: str = Query(...),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    from backend.crm.crm_bulk_auto_assign import svc_get_bulk_auto_assign_config

    role, _ = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can view auto bulk-assign config.")
    return await svc_get_bulk_auto_assign_config(entity_type)


@router.put(
    "/bulk-assign/auto",
    summary="Legacy alias for PUT /bulk-assign/schedulers",
)
async def save_bulk_auto_assign_config(
    payload: CRMBulkAutoAssignConfigIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    from backend.crm.crm_bulk_auto_assign import svc_save_bulk_auto_assign_config

    role, emp_id = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can configure auto bulk-assign.")
    return await svc_save_bulk_auto_assign_config(payload, updated_by=emp_id)


@router.post(
    "/bulk-assign/auto/run",
    summary="Legacy: run scheduler by id or first enabled for entity_type",
)
async def run_bulk_auto_assign_now(
    entity_type: str = Query(...),
    scheduler_id: Optional[int] = Query(None, ge=1),
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    from backend.crm.crm_bulk_auto_assign import (
        run_auto_assign_for_rule,
        run_auto_assign_scheduler,
        svc_get_bulk_assign_scheduler,
    )

    role, _ = _get_user_context(current_user)
    if role not in {"ADMIN"}:
        raise HTTPException(status_code=403, detail="Only ADMIN can trigger auto bulk-assign.")
    if scheduler_id:
        rule = await svc_get_bulk_assign_scheduler(scheduler_id)
        if not rule.get("enabled"):
            raise HTTPException(status_code=409, detail="Scheduler is disabled.")
        summary = await run_auto_assign_scheduler(scheduler_id, force=True)
    else:
        summary = await run_auto_assign_for_rule(entity_type, force=True)
        if summary is None:
            raise HTTPException(
                status_code=409,
                detail="No enabled scheduler found. Save a scheduler first.",
            )
    if summary is None:
        raise HTTPException(status_code=500, detail="Auto-assign run did not produce a result.")
    rm_n = (summary.get("roles") or {}).get("RM", {}).get("total_assigned", 0)
    op_n = (summary.get("roles") or {}).get("OP", {}).get("total_assigned", 0)
    return {
        "message": f"Assigned {rm_n} as RM and {op_n} as OP from {summary.get('candidates_matched', 0)} matching leads.",
        "summary": summary,
    }


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
    entity_type: str = Query(...),
    entity_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_filter_crm_activities(
        lead_id=lead_id,
        activity_type=activity_type,
        call_type_code=call_type_code,
        call_status_code=call_status_code,
        old_stage=old_stage,
        new_stage=new_stage,
        performed_by=performed_by,
        performed_at_from=performed_at_from,
        performed_at_to=performed_at_to,
        mobile=mobile,
        lead_stage=lead_stage,
        lead_is_active=lead_is_active,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get("/stages", summary="CRM lead pipeline stages for UI")
async def get_crm_lead_stages(
    entity_type: str = Query(...),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_get_crm_lead_stages(entity_type=entity_type, current_user=current_user)


@router.get(
    "/by-entity",
    summary="Get one CRM lead by optional entity_type and/or entity_id (visible to caller)",
)
async def get_crm_lead_by_entity(
    entity_id: Optional[int] = Query(None, ge=1, description="crm_leads.entity_id."),
    entity_type: Optional[str] = Query(
        None,
        description="crm_leads.entity_type. When entity_id is omitted, returns the latest lead for this type.",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_get_crm_lead_by_entity(
        entity_id=entity_id,
        entity_type=entity_type,
        current_user=current_user,
    )


@router.get(
    "/{lead_id:int}/activities/calls",
    summary="Call log for a lead (dial/connect timestamps + outcome + stage at time of call)",
)
async def list_crm_lead_call_activities(
    lead_id: int,
    entity_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_list_crm_lead_call_activities(
        lead_id=lead_id,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get(
    "/{lead_id:int}/activities/stage-history",
    summary="Stage change timeline for a lead (from activities)",
)
async def list_crm_lead_stage_activity_history(
    lead_id: int,
    entity_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_list_crm_lead_stage_activity_history(
        lead_id=lead_id,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get("/{lead_id:int}/activities", summary="Get CRM lead activities")
async def list_crm_activities(
    lead_id: int,
    entity_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _svc_list_crm_activities(
        lead_id=lead_id,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )
