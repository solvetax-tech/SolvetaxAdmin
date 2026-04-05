import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone, timedelta
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_service_visibility
from app.security.rbac import require_permission
from app.logger import logger

router = APIRouter(
    prefix="/api/v1/filing-followups",
    tags=["GST Filing Followups"],
)


# --------------------------------------------------
# SCHEMA
# --------------------------------------------------


class CreateFilingFollowupRequest(BaseModel):
    customer_service_id: int
    followup_at: datetime
    remarks: Optional[str] = None
    assigned_to: Optional[int] = Field(
        None,
        description="Ignored when JWT role is RM or OP; assigned_to is set to current emp_id.",
    )


class CreateFilingFollowupResponse(BaseModel):
    id: int
    message: str


class UpdateFilingFollowupRequest(BaseModel):
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = None
    assigned_to: Optional[int] = Field(
        None,
        description="If JWT role is RM or OP, API sets assigned_to to current emp_id.",
    )
    status: Optional[str] = None  # PENDING / COMPLETED / CANCELLED


class UpdateFilingFollowupResponse(BaseModel):
    id: int
    message: str


# List / filter manual GST filing followups:
# GET /api/v1/Followups/customer-service-followups/filter
#   with entity_type=GST_FILING and mode=MANUAL (same query shape as filter_followups).


# --------------------------------------------------
# CREATE FOLLOWUP (MANUAL — GST FILING)
# --------------------------------------------------


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateFilingFollowupResponse,
    summary="Create GST Filing Manual Followup",
)
async def create_filing_followup(
    payload: CreateFilingFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_filing_followup"},
    )

    log.info("Create filing followup request received")

    # --------------------------------------------------
    # STEP 0: NORMALIZE DATETIME
    # --------------------------------------------------

    if payload.followup_at.tzinfo is None:
        followup_at = payload.followup_at.replace(tzinfo=timezone.utc)
    else:
        followup_at = payload.followup_at.astimezone(timezone.utc)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    if followup_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Invalid followup time",
                    "fields": {
                        "followup_at": "Followup must be in future",
                    },
                },
            },
        )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # --------------------------------------------------
                # STEP 1: FETCH CUSTOMER SERVICE
                # --------------------------------------------------

                cs_row = await conn.fetchrow(
                    f"""
                    SELECT
                        cs.id,
                        cs.rm_id,
                        cs.op_id,
                        cs.service_status,
                        cs.status,
                        cs.entity_type,
                        cs.entity_id,
                        cs.service_id,
                        sc.followup_mode
                    FROM {DB_SCHEMA}.customer_services cs
                    JOIN {DB_SCHEMA}.service_config sc
                        ON sc.id = cs.service_id
                    WHERE cs.id = $1
                    """,
                    payload.customer_service_id,
                )

                if not cs_row:
                    raise HTTPException(404, "Customer service not found")

                if cs_row["entity_type"] != "GST_FILING":
                    raise HTTPException(400, "Followup allowed only for GST filing services")

                if cs_row["status"] != "ACTIVE":
                    raise HTTPException(400, "Service is not active")

                if cs_row["service_status"] == "PROVIDED":
                    raise HTTPException(400, "Service already completed")

                mode = "MANUAL"

                # --------------------------------------------------
                # STEP 2: VISIBILITY CHECK
                # --------------------------------------------------

                visibility_sql, visibility_values, _ = build_customer_service_visibility(
                    role,
                    emp_id,
                    1,
                    DB_SCHEMA,
                )

                if visibility_sql:
                    allowed = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            FROM {DB_SCHEMA}.customer_services cs
                            WHERE cs.id = $1 AND {visibility_sql}
                        )
                        """,
                        payload.customer_service_id,
                        *visibility_values,
                    )

                    if not allowed:
                        raise HTTPException(403, "Not allowed")

                # --------------------------------------------------
                # STEP 3: ASSIGNMENT LOGIC
                # --------------------------------------------------

                if role in ("RM", "OP"):
                    assigned_to = emp_id
                else:
                    assigned_to = (
                        payload.assigned_to
                        or cs_row["rm_id"]
                        or emp_id
                    )

                if assigned_to:
                    valid_assignee = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1 FROM {DB_SCHEMA}.employees
                            WHERE emp_id = $1 AND is_active = TRUE
                        )
                        """,
                        assigned_to,
                    )
                    if not valid_assignee:
                        raise HTTPException(400, "Invalid assigned_to")

                # --------------------------------------------------
                # STEP 4: DUPLICATE CHECK
                # --------------------------------------------------

                exists = await conn.fetchval(
                    f"""
                    SELECT EXISTS(
                        SELECT 1
                        FROM {DB_SCHEMA}.customer_service_followups
                        WHERE customer_service_id = $1
                        AND followup_at = $2
                        AND status = 'PENDING'
                    )
                    """,
                    payload.customer_service_id,
                    followup_at,
                )

                if exists:
                    raise HTTPException(409, "Duplicate followup")

                # --------------------------------------------------
                # STEP 5: INSERT FOLLOWUP
                # --------------------------------------------------

                new_id = await conn.fetchval(
                    f"""
                    INSERT INTO {DB_SCHEMA}.customer_service_followups
                    (
                        customer_service_id,
                        mode,
                        followup_at,
                        status,
                        remarks,
                        assigned_to,
                        created_by,
                        entity_type,
                        entity_id,
                        service_id,
                        reminder_count
                    )
                    VALUES ($1,$2,$3,'PENDING',$4,$5,$6,$7,$8,$9,$10)
                    RETURNING id
                    """,
                    payload.customer_service_id,
                    mode,
                    followup_at,
                    payload.remarks,
                    assigned_to,
                    emp_id,
                    cs_row["entity_type"],
                    cs_row["entity_id"],
                    cs_row["service_id"],
                    0,
                )

        log.info(
            "Filing followup created | id=%s | cs_id=%s | assigned=%s",
            new_id,
            payload.customer_service_id,
            assigned_to,
        )

        return CreateFilingFollowupResponse(
            id=new_id,
            message="GST filing followup created successfully",
        )

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")


# --------------------------------------------------
# UPDATE FOLLOWUP (PATCH + STATUS)
# --------------------------------------------------


@router.post(
    "/{followup_id}",
    response_model=UpdateFilingFollowupResponse,
    summary="Update GST Filing Manual Followup",
)
async def update_filing_followup(
    followup_id: int,
    payload: UpdateFilingFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "update_filing_followup"},
    )

    log.info("Update filing followup request received | id=%s", followup_id)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    if not any([
        payload.followup_at,
        payload.remarks,
        payload.assigned_to is not None,
        payload.status,
    ]):
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update",
        )

    valid_status = {"PENDING", "COMPLETED", "CANCELLED"}
    if payload.status and payload.status not in valid_status:
        raise HTTPException(400, "Invalid status value")

    if payload.status == "COMPLETED" and payload.followup_at:
        raise HTTPException(400, "Cannot change followup time while completing")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # --------------------------------------------------
                # STEP 1: FETCH FOLLOWUP + SERVICE (LOCK FOR UPDATE)
                # --------------------------------------------------

                row = await conn.fetchrow(
                    f"""
                    SELECT
                        f.*,
                        cs.rm_id,
                        cs.op_id,
                        cs.entity_type AS cs_entity_type
                    FROM {DB_SCHEMA}.customer_service_followups f
                    JOIN {DB_SCHEMA}.customer_services cs
                        ON cs.id = f.customer_service_id
                    WHERE f.id = $1
                    FOR UPDATE
                    """,
                    followup_id,
                )

                if not row:
                    raise HTTPException(404, "Followup not found")

                if row["cs_entity_type"] != "GST_FILING":
                    raise HTTPException(400, "This followup does not belong to GST filing")

                if row["status"] in ["CANCELLED", "COMPLETED"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Finalized followup cannot be modified",
                    )

                # --------------------------------------------------
                # STEP 2: ROLE VISIBILITY CHECK
                # --------------------------------------------------

                visibility_sql, visibility_values, _ = build_customer_service_visibility(
                    role,
                    emp_id,
                    2,
                    DB_SCHEMA,
                )

                if visibility_sql:
                    allowed = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            FROM {DB_SCHEMA}.customer_services cs
                            WHERE cs.id = $1 AND {visibility_sql}
                        )
                        """,
                        row["customer_service_id"],
                        *visibility_values,
                    )

                    if not allowed:
                        raise HTTPException(
                            status_code=403,
                            detail="Not allowed to update this followup",
                        )

                # --------------------------------------------------
                # STEP 3: FOLLOWUP TIME VALIDATION
                # --------------------------------------------------

                if payload.followup_at:
                    if payload.followup_at.tzinfo is None:
                        followup_at = payload.followup_at.replace(tzinfo=timezone.utc)
                    else:
                        followup_at = payload.followup_at.astimezone(timezone.utc)

                    if followup_at < datetime.now(timezone.utc):
                        raise HTTPException(400, "Followup must be in future")

                    if followup_at > datetime.now(timezone.utc) + timedelta(days=60):
                        raise HTTPException(400, "Followup cannot be scheduled beyond 60 days")
                else:
                    followup_at = row["followup_at"]

                # --------------------------------------------------
                # STEP 4: ASSIGNMENT VALIDATION
                # --------------------------------------------------

                if payload.assigned_to is not None:
                    if role in ("RM", "OP"):
                        assigned_to = emp_id
                    else:
                        assigned_to = payload.assigned_to

                    valid = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1 FROM {DB_SCHEMA}.employees
                            WHERE emp_id = $1 AND is_active = TRUE
                        )
                        """,
                        assigned_to,
                    )

                    if not valid:
                        raise HTTPException(400, "Invalid assigned_to")
                else:
                    assigned_to = row["assigned_to"]

                # --------------------------------------------------
                # STEP 5: DUPLICATE CHECK
                # --------------------------------------------------

                if payload.followup_at:
                    exists = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            FROM {DB_SCHEMA}.customer_service_followups
                            WHERE customer_service_id = $1
                            AND followup_at = $2
                            AND id != $3
                            AND status = 'PENDING'
                        )
                        """,
                        row["customer_service_id"],
                        followup_at,
                        followup_id,
                    )

                    if exists:
                        raise HTTPException(409, "Another followup already exists at this time")

                # --------------------------------------------------
                # STEP 6: BUILD UPDATE
                # --------------------------------------------------

                updates = []
                values = []
                idx = 1

                if payload.followup_at:
                    updates.append(f"followup_at = ${idx}")
                    values.append(followup_at)
                    idx += 1

                    updates.append("reminder_sent = FALSE")
                    updates.append("reminder_count = 0")

                if payload.remarks is not None:
                    updates.append(f"remarks = ${idx}")
                    values.append(payload.remarks)
                    idx += 1

                if payload.assigned_to is not None:
                    updates.append(f"assigned_to = ${idx}")
                    values.append(assigned_to)
                    idx += 1

                # --------------------------------------------------
                # STATUS LOGIC
                # --------------------------------------------------

                if payload.status:
                    updates.append(f"status = ${idx}")
                    values.append(payload.status)
                    idx += 1

                    if payload.status in ["COMPLETED", "CANCELLED"]:
                        updates.append("completed_at = NOW()")

                    elif payload.status == "PENDING":
                        updates.append("completed_at = NULL")

                if not updates:
                    raise HTTPException(400, "Nothing to update")

                # --------------------------------------------------
                # STEP 7: EXECUTE UPDATE
                # --------------------------------------------------

                values.append(followup_id)

                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_service_followups
                    SET {", ".join(updates)}
                    WHERE id = ${idx}
                    """,
                    *values,
                )

        log.info("Filing followup updated successfully | id=%s", followup_id)

        return UpdateFilingFollowupResponse(
            id=followup_id,
            message="GST filing followup updated successfully",
        )

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")
