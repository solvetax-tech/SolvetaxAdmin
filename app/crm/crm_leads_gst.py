"""GST-registration funnel CRM: GST-only stage transitions + single-lead APIs."""

import logging
from datetime import datetime
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from app.crm.crm_leads_common import (
    CLOSED_STAGES,
    FINAL_PITCH_CONNECTED,
    FIRST_PITCH_CONNECTED,
    FOLLOWUP_STATUSES,
    IST,
    DEFAULT_CRM_ENTITY_TYPE,
    _FIRST_PITCH_CONNECTED_STAGES,
    _STATUSES_NO_STAGE_CHANGE,
    _crm_lead_by_id_tag,
    _crm_lead_matches_funnel_entity_type,
    _crm_linked_entity_row_exists,
    _entity_type_query,
    _fetch_crm_lead_visible,
    _get_user_context,
    _invalidate_crm_cache,
    _normalize_code,
    _performed_by_emp_id,
    _require_crm_row_context,
    _closed_stage_blocks_call_update,
    _validate_call_config,
    _validate_crm_call_against_mappings,
    _validation_error,
)
from app.crm.schemas_common import CRMLeadEntityIdPatchIn
from app.crm.schemas_gst import CRMCallUpdateIn, CRMFollowupStatusUpdateIn, CRMLeadEditIn
from app.logger import logger
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/crm/leads", tags=["CRM Leads GST"])

# --- GST funnel call transitions ---

def _transition_stage(current_stage: str, call_type_code: str, call_status_code: str) -> Optional[str]:
    """
    Map call outcome to the next CRM stage.

    **FINAL_PITCH_CALL** (stage is ``GST_REGISTRATION_DONE`` or ``SCHEDULED_PAYMENTS`` upstream):
    only ``SCHEDULED_PAYMENT`` sets ``stage`` to ``SCHEDULED_PAYMENTS``. All other outcomes
    (incl. ``CALL_BACK``, ``NOT_INTERESTED``, no-connect, ``CALL_DONE``) leave ``stage`` unchanged.

    **FIRST_PITCH_CALL** (early funnel): ``CALL_BACK`` → ``FOLLOW_UP``; ``NOT_INTERESTED`` →
    ``NOT_INTERESTED``; ``SEND_DOCS`` from FRESH_LEAD / FOLLOW_UP / INTERESTED / NOT_INTERESTED →
    ``PENDING_REGISTRATION_DATA``; ``CONNECTED_AND_SCHEDULED`` → ``INTERESTED`` as before;
    ``CALL_NOT_*`` / ``CALL_DONE`` → no change.
    """
    ctc = (call_type_code or "").strip().upper()

    if ctc == "FINAL_PITCH_CALL":
        if call_status_code == "SCHEDULED_PAYMENT":
            if current_stage in {"GST_REGISTRATION_DONE", "SCHEDULED_PAYMENTS"}:
                return "SCHEDULED_PAYMENTS"
            raise _validation_error(
                "Invalid stage for SCHEDULED_PAYMENT.",
                {
                    "stage": (
                        f"SCHEDULED_PAYMENT applies only from GST_REGISTRATION_DONE or SCHEDULED_PAYMENTS; "
                        f"current is {current_stage}."
                    )
                },
            )
        return None

    if ctc != "FIRST_PITCH_CALL":
        raise _validation_error(
            "Unsupported call_type_code for stage transition.",
            {"call_type_code": str(call_type_code)},
        )

    if call_status_code in _STATUSES_NO_STAGE_CHANGE:
        return None

    if call_status_code == "CALL_BACK":
        if current_stage == "FOLLOW_UP":
            return None
        return "FOLLOW_UP"

    if call_status_code == "CONNECTED_AND_SCHEDULED":
        if current_stage not in _FIRST_PITCH_CONNECTED_STAGES:
            raise _validation_error(
                "Invalid stage for CONNECTED_AND_SCHEDULED.",
                {
                    "stage": (
                        f"CONNECTED_AND_SCHEDULED applies only from FRESH_LEAD, FOLLOW_UP, or INTERESTED; "
                        f"current is {current_stage}."
                    )
                },
            )
        if current_stage == "INTERESTED":
            return None
        return "INTERESTED"

    if call_status_code == "NOT_INTERESTED":
        return "NOT_INTERESTED"

    if call_status_code == "SEND_DOCS":
        if current_stage in {"FRESH_LEAD", "FOLLOW_UP", "INTERESTED", "NOT_INTERESTED"}:
            return "PENDING_REGISTRATION_DATA"
        raise _validation_error(
            "Invalid stage for SEND_DOCS.",
            {
                "stage": (
                    "SEND_DOCS applies only from FRESH_LEAD, FOLLOW_UP, INTERESTED, or NOT_INTERESTED; "
                    f"current is {current_stage}."
                )
            },
        )

    raise _validation_error(
        "Invalid status for call type.",
        {
            "call_status_code": f"{call_status_code} is not allowed for {call_type_code}.",
        },
    )


async def _crm_apply_call_update(
    conn: asyncpg.Connection,
    role: str,
    emp_id: int,
    lead_id: int,
    lead: asyncpg.Record,
    payload: CRMCallUpdateIn,
    log: logging.LoggerAdapter,
) -> dict:
    """Apply call outcome: updates crm_leads + inserts crm_activities with dial/contact timestamps."""
    call_type_code = _normalize_code(payload.call_type_code)
    call_status_code = _normalize_code(payload.call_status_code)

    et_ref = _entity_type_query(lead.get("entity_type"))

    await _validate_call_config(conn, call_type_code, call_status_code, et_ref)

    if not lead["is_active"]:
        raise _validation_error("Inactive lead cannot be updated via call flow.")

    current_stage = lead["stage"]
    if _closed_stage_blocks_call_update(current_stage, call_status_code):
        raise _validation_error(
            "Lead is closed; stage updates are not allowed.",
            {"stage": f"Current stage is {current_stage}."},
        )
    await _validate_crm_call_against_mappings(
        conn, current_stage, call_type_code, call_status_code, et_ref
    )

    if payload.followup_at is not None and payload.followup_at <= datetime.now(IST):
        raise _validation_error("Invalid followup datetime.", {"followup_at": "Must be a future datetime."})
    if call_status_code in {"CALL_BACK", "SCHEDULED_PAYMENT"} and payload.followup_at is None:
        raise _validation_error("followup_at is required.", {"followup_at": f"Required for {call_status_code}."})

    target_stage = _transition_stage(current_stage, call_type_code, call_status_code)
    connected_inc = int(
        (call_type_code == "FIRST_PITCH_CALL" and call_status_code in FIRST_PITCH_CONNECTED)
        or (call_type_code == "FINAL_PITCH_CALL" and call_status_code in FINAL_PITCH_CONNECTED)
    )
    new_stage = target_stage or current_stage

    et_for_activity = _entity_type_query(lead.get("entity_type"))

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
            rm_assigned_at = CASE
                WHEN $6 = 'RM' AND rm_id IS DISTINCT FROM $7 THEN NOW()
                ELSE rm_assigned_at
            END,
            op_assigned_at = CASE
                WHEN $6 = 'OP' AND op_id IS DISTINCT FROM $7 THEN NOW()
                ELSE op_assigned_at
            END,
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
            lead_id, entity_type, activity_type, call_type_code, call_status_code,
            old_stage, new_stage, followup_at, remarks, performed_by,
            last_dailed_at, last_connected_at,
            performed_at, created_at
        )
        VALUES (
            $1, $2, 'CALL', $3, $4, $5, $6, $7, $8, $9,
            NOW(),
            CASE WHEN $10 = 1 THEN NOW() ELSE NULL END,
            NOW(), NOW()
        )
        RETURNING id
        """,
        lead_id,
        et_for_activity,
        call_type_code,
        call_status_code,
        current_stage,
        new_stage,
        payload.followup_at,
        payload.remarks,
        _performed_by_emp_id(emp_id),
        connected_inc,
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


async def _crm_apply_followup_status(
    conn: asyncpg.Connection,
    emp_id: int,
    lead_id: int,
    lead: asyncpg.Record,
    payload: CRMFollowupStatusUpdateIn,
    follow_up_status: str,
    log: logging.LoggerAdapter,
) -> dict:
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
            lead_id, entity_type, activity_type, remarks, performed_by, performed_at, created_at
        )
        VALUES ($1, $2, 'FOLLOWUP_STATUS_UPDATE', $3, $4, NOW(), NOW())
        RETURNING id
        """,
        lead_id,
        _entity_type_query(lead.get("entity_type")),
        (
            f"follow_up_status: {old_status or 'NULL'} -> {follow_up_status}"
            if payload.remarks is None
            else f"{payload.remarks} | follow_up_status: {old_status or 'NULL'} -> {follow_up_status}"
        ),
        _performed_by_emp_id(emp_id),
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


@router.post(
    "/{lead_id:int}/entity-id",
    summary="Link or clear GST entity_id for a CRM lead",
    description=(
        "Sets crm_leads.entity_id to gst_registration.id (or JSON null to clear). "
        "Same visibility as call updates (RM/OP/managers with EMPLOYEE WRITE). "
        "INCOME_TAX leads must use /api/v1/crm/itr/leads/{lead_id}/entity-id."
    ),
)
async def patch_crm_lead_entity_id_gst(
    lead_id: int,
    payload: CRMLeadEntityIdPatchIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)

    new_eid = payload.entity_id

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                lead = await _fetch_crm_lead_visible(conn, role, emp_id, lead_id, for_update=True)
                if not lead:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")
                if not _crm_lead_matches_funnel_entity_type(
                    lead.get("entity_type"),
                    DEFAULT_CRM_ENTITY_TYPE,
                ):
                    raise _validation_error(
                        "This lead does not belong to the GST registration funnel.",
                        {
                            "entity_type": (
                                "Expected GST_REGISTRATION or unset entity_type; "
                                "use /api/v1/crm/itr/leads/{lead_id}/entity-id for INCOME_TAX."
                            )
                        },
                    )
                if new_eid is not None:
                    exists = await _crm_linked_entity_row_exists(
                        conn,
                        DEFAULT_CRM_ENTITY_TYPE,
                        new_eid,
                    )
                    if not exists:
                        raise _validation_error(
                            "entity_id is not a valid GST registration id.",
                            {"entity_id": "No gst_registration row with this id."},
                        )
                updated = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.crm_leads
                    SET entity_id = $1,
                        updated_at = NOW()
                    WHERE id = $2
                    RETURNING *
                    """,
                    new_eid,
                    lead_id,
                )
                if not updated:
                    raise HTTPException(
                        status_code=409,
                        detail="Lead could not be updated; it may have changed. Retry after refresh.",
                    )
        await _invalidate_crm_cache(lead_id)
        return {
            "message": "entity_id updated successfully.",
            "lead_id": lead_id,
            "entity_id": updated["entity_id"],
            "lead": dict(updated),
        }
    except asyncpg.exceptions.UniqueViolationError:
        raise _validation_error(
            "Cannot link: unique constraint violated.",
            {"entity_id": "This registration may already be linked to another CRM lead."},
        )
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise _validation_error(
            "Foreign key violation when setting entity_id.",
            {"entity_id": "Invalid reference for this database policy."},
        )
    except asyncpg.PostgresError:
        logger.exception("Database error while updating CRM lead entity_id (GST)")
        raise HTTPException(status_code=500, detail="Database error.")


@router.get("/{lead_id:int}", summary="Get CRM lead by id")
async def get_crm_lead(lead_id: int, current_user=Depends(require_permission("EMPLOYEE", "READ"))):
    role, emp_id = _get_user_context(current_user)
    _require_crm_row_context(role, emp_id)
    cache_key = build_cache_key("crm:lead:by_id", lead_id=lead_id, role=role, emp_id=emp_id)
    pool = await get_db_pool()
    async def _load_crm_lead():
        try:
            async with pool.acquire() as conn:
                row = await _fetch_crm_lead_visible(conn, role, emp_id, lead_id)
                if not row:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")
                return dict(row)
        except asyncpg.PostgresError:
            logger.exception("Database error while fetching CRM lead")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_crm_lead,
        ttl_seconds=300,
        tags=[_crm_lead_by_id_tag(lead_id)],
    )


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
                if "rm_id" in update_data and update_data["rm_id"] != old_row["rm_id"]:
                    update_data["rm_assigned_at"] = datetime.now(IST) if update_data["rm_id"] is not None else None
                if "op_id" in update_data and update_data["op_id"] != old_row["op_id"]:
                    update_data["op_assigned_at"] = datetime.now(IST) if update_data["op_id"] is not None else None

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
                result = {"message": "CRM lead updated successfully.", "lead": dict(new_row)}
            await _invalidate_crm_cache(lead_id)
            return result
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise _validation_error("Invalid foreign key reference.", {"rm_id/op_id": "Referenced employee not found."})
    except asyncpg.exceptions.CheckViolationError as e:
        raise _validation_error("Constraint validation failed.", {"constraint": getattr(e, "constraint_name", "unknown")})
    except asyncpg.PostgresError:
        logger.exception("Database error while editing CRM lead")
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
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "crm_followup_status_update"},
    )

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

                result = await _crm_apply_followup_status(
                    conn, emp_id, lead_id, lead, payload, follow_up_status, log
                )
            await _invalidate_crm_cache(lead_id)
            return result
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

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                lead = await _fetch_crm_lead_visible(
                    conn, role, emp_id, lead_id, for_update=True
                )
                if not lead:
                    raise HTTPException(status_code=404, detail="CRM lead not found.")

                result = await _crm_apply_call_update(conn, role, emp_id, lead_id, lead, payload, log)
            await _invalidate_crm_cache(lead_id)
            return result
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise _validation_error("Invalid foreign key reference.", {"performed_by": "Employee reference invalid."})
    except asyncpg.exceptions.CheckViolationError as e:
        raise _validation_error("Constraint validation failed.", {"constraint": getattr(e, "constraint_name", "unknown")})
    except asyncpg.PostgresError:
        logger.exception("Database error while applying CRM call update")
        raise HTTPException(status_code=500, detail="Database error.")
