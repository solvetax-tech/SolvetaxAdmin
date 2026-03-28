import logging
import uuid
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import constr, validator, BaseModel
from typing import Optional, List
from datetime import datetime
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import require_permission
from app.logger import logger
from app.utils import mask_sensitive_data,generate_uuid,build_customer_service_visibility
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(
    prefix="/api/v1/Followups",
    tags=["Followups"]
)
@router.get(
    "/customer-service-followups/filter",
    summary="Filter Customer Service Followups (Dynamic + Advanced Filters)",
    responses={
        200: {"description": "Followups fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def filter_followups(

    # --------------------------------------------------
    # PRIMARY FILTERS
    # --------------------------------------------------
    id: Optional[int] = None,
    customer_service_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    service_id: Optional[int] = None,

    # --------------------------------------------------
    # STATUS / MODE
    # --------------------------------------------------
    status: Optional[str] = None,
    statuses: Optional[List[str]] = Query(None),
    mode: Optional[str] = None,

    # --------------------------------------------------
    # USER FILTERS
    # --------------------------------------------------
    assigned_to: Optional[int] = None,
    created_by: Optional[int] = None,

    # --------------------------------------------------
    # DATE FILTERS
    # --------------------------------------------------
    followup_from: Optional[datetime] = None,
    followup_to: Optional[datetime] = None,

    completed_from: Optional[datetime] = None,
    completed_to: Optional[datetime] = None,

    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,

    # --------------------------------------------------
    # SPECIAL FILTERS
    # --------------------------------------------------
    is_overdue: Optional[bool] = None,
    is_completed_on_time: Optional[bool] = None,
    is_upcoming: Optional[bool] = None,
    today_only: Optional[bool] = None,

    reminder_sent: Optional[bool] = None,

    # 🔥 ENTITY FILTERS
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    high_reminder: Optional[bool] = None,

    # --------------------------------------------------
    # PAGINATION
    # --------------------------------------------------
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cursor: Optional[datetime] = None,

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_followups"},
    )

    log.info("Followups filter request received")

    # --------------------------------------------------
    # VALIDATIONS
    # --------------------------------------------------

    if followup_from and followup_to and followup_from > followup_to:
        raise HTTPException(400, "Invalid followup date range")

    if completed_from and completed_to and completed_from > completed_to:
        raise HTTPException(400, "Invalid completed date range")

    if created_from and created_to and created_from > created_to:
        raise HTTPException(400, "Invalid created date range")

    if status and statuses:
        raise HTTPException(400, "Use either status or statuses, not both")

    valid_status = {"PENDING", "COMPLETED", "MISSED", "CANCELLED"}
    if status and status not in valid_status:
        raise HTTPException(400, "Invalid status")

    if statuses:
        invalid = [s for s in statuses if s not in valid_status]
        if invalid:
            raise HTTPException(400, f"Invalid statuses: {invalid}")

    valid_modes = {"MANUAL", "AUTO"}
    if mode and mode not in valid_modes:
        raise HTTPException(400, "Invalid mode")

    if entity_id and not entity_type:
        raise HTTPException(400, "entity_type required when entity_id is provided")

    if is_overdue and is_upcoming:
        raise HTTPException(400, "Cannot use is_overdue and is_upcoming together")

    if today_only and (followup_from or followup_to):
        raise HTTPException(400, "today_only cannot be used with date filters")

    # --------------------------------------------------
    # TIMEZONE NORMALIZATION
    # --------------------------------------------------

    def normalize(dt):
        if dt and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    followup_from = normalize(followup_from)
    followup_to = normalize(followup_to)
    completed_from = normalize(completed_from)
    completed_to = normalize(completed_to)
    created_from = normalize(created_from)
    created_to = normalize(created_to)
    cursor = normalize(cursor)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    try:

        conditions = []
        values = []
        idx = 1

        # --------------------------------------------------
        # BASIC FILTERS
        # --------------------------------------------------

        if id is not None:
            conditions.append(f"f.id = ${idx}")
            values.append(id)
            idx += 1

        if customer_service_id is not None:
            conditions.append(f"f.customer_service_id = ${idx}")
            values.append(customer_service_id)
            idx += 1

        if customer_id is not None:
            conditions.append(f"cs.customer_id = ${idx}")
            values.append(customer_id)
            idx += 1

        if service_id is not None:
            conditions.append(f"cs.service_id = ${idx}")
            values.append(service_id)
            idx += 1

        if mode:
            conditions.append(f"f.mode = ${idx}")
            values.append(mode)
            idx += 1

        # --------------------------------------------------
        # STATUS FILTERS
        # --------------------------------------------------

        if status:
            conditions.append(f"f.status = ${idx}")
            values.append(status)
            idx += 1

        if statuses:
            cleaned = [s for s in statuses if s]
            if cleaned:
                conditions.append(f"f.status = ANY(${idx})")
                values.append(cleaned)
                idx += 1

        # --------------------------------------------------
        # ENTITY FILTERS
        # --------------------------------------------------

        if entity_type:
            conditions.append(f"f.entity_type = ${idx}")
            values.append(entity_type)
            idx += 1

        if entity_id:
            conditions.append(f"f.entity_id = ${idx}")
            values.append(entity_id)
            idx += 1

        # --------------------------------------------------
        # USER FILTERS
        # --------------------------------------------------

        if assigned_to is not None:
            conditions.append(f"f.assigned_to = ${idx}")
            values.append(assigned_to)
            idx += 1

        if created_by is not None:
            conditions.append(f"f.created_by = ${idx}")
            values.append(created_by)
            idx += 1

        # --------------------------------------------------
        # DATE FILTERS
        # --------------------------------------------------

        if followup_from:
            conditions.append(f"f.followup_at >= ${idx}")
            values.append(followup_from)
            idx += 1

        if followup_to:
            conditions.append(f"f.followup_at <= ${idx}")
            values.append(followup_to)
            idx += 1

        if completed_from:
            conditions.append(f"f.completed_at >= ${idx}")
            values.append(completed_from)
            idx += 1

        if completed_to:
            conditions.append(f"f.completed_at <= ${idx}")
            values.append(completed_to)
            idx += 1

        if created_from:
            conditions.append(f"f.created_at >= ${idx}")
            values.append(created_from)
            idx += 1

        if created_to:
            conditions.append(f"f.created_at <= ${idx}")
            values.append(created_to)
            idx += 1

        # --------------------------------------------------
        # SPECIAL FILTERS
        # --------------------------------------------------

        if is_overdue is True:
            conditions.append("(f.status = 'PENDING' AND f.followup_at < NOW())")

        if is_overdue is False:
            conditions.append("(f.status = 'PENDING' AND f.followup_at >= NOW())")

        if is_completed_on_time is True:
            conditions.append("(f.status = 'COMPLETED' AND f.completed_at <= f.followup_at)")

        if is_completed_on_time is False:
            conditions.append("(f.status = 'COMPLETED' AND f.completed_at > f.followup_at)")

        if is_upcoming:
            conditions.append("(f.status = 'PENDING' AND f.followup_at >= NOW())")

        if today_only:
            conditions.append("DATE(f.followup_at) = CURRENT_DATE")

        if reminder_sent is not None:
            conditions.append(f"f.reminder_sent = ${idx}")
            values.append(reminder_sent)
            idx += 1

        if high_reminder:
            conditions.append("(f.reminder_count >= 3)")

        # --------------------------------------------------
        # CURSOR
        # --------------------------------------------------

        if cursor:
            conditions.append(f"f.created_at < ${idx}")
            values.append(cursor)
            idx += 1

        # --------------------------------------------------
        # VISIBILITY
        # --------------------------------------------------

        visibility_sql, visibility_values, idx = build_customer_service_visibility(
            role,
            emp_id,
            idx,
            DB_SCHEMA
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.customer_service_followups f
            JOIN {DB_SCHEMA}.customer_services cs
                ON cs.id = f.customer_service_id
            {where_clause}
        """

        # --------------------------------------------------
        # PAGINATION
        # --------------------------------------------------

        if cursor:
            pagination_sql = f"LIMIT ${idx}"
            values_with_pagination = values + [limit]
        else:
            pagination_sql = f"LIMIT ${idx} OFFSET ${idx+1}"
            values_with_pagination = values + [limit, offset]

        # --------------------------------------------------
        # MAIN QUERY
        # --------------------------------------------------

        main_sql = f"""
            SELECT
                f.*,

                (f.followup_at < NOW() AND f.status = 'PENDING') AS is_overdue_flag,
                (f.followup_at >= NOW() AND f.status = 'PENDING') AS is_upcoming_flag,

                cs.customer_id,
                cs.service_id,
                cs.rm_id,
                cs.op_id,

                c.full_name,

                s.service_code,
                s.service_name,

                rm.first_name AS rm_name,
                op.first_name AS op_name,

                assignee.first_name AS assigned_to_name,
                creator.first_name AS created_by_name

            FROM {DB_SCHEMA}.customer_service_followups f

            JOIN {DB_SCHEMA}.customer_services cs
                ON cs.id = f.customer_service_id

            JOIN {DB_SCHEMA}.customers c
                ON c.customer_id = cs.customer_id

            JOIN {DB_SCHEMA}.service_config s
                ON s.id = cs.service_id

            LEFT JOIN {DB_SCHEMA}.employees rm
                ON rm.emp_id = cs.rm_id

            LEFT JOIN {DB_SCHEMA}.employees op
                ON op.emp_id = cs.op_id

            LEFT JOIN {DB_SCHEMA}.employees assignee
                ON assignee.emp_id = f.assigned_to

            LEFT JOIN {DB_SCHEMA}.employees creator
                ON creator.emp_id = f.created_by

            {where_clause}

            ORDER BY f.created_at DESC, f.id DESC
            {pagination_sql}
        """

        async with pool.acquire() as conn:

            total_count = None
            if not cursor:
                total_count = await conn.fetchval(count_sql, *values)

            rows = await conn.fetch(main_sql, *values_with_pagination)

        next_cursor = rows[-1]["created_at"] if rows else None

        return {
            "data": [dict(row) for row in rows],
            "next_cursor": next_cursor,
            "count": total_count
        }

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")
# --------------------------------------------------
# SCHEMA
# --------------------------------------------------

class CreateFollowupRequest(BaseModel):
    customer_service_id: int
    followup_at: datetime
    remarks: Optional[str] = None
    assigned_to: Optional[int] = None


class CreateFollowupResponse(BaseModel):
    id: int
    message: str


# --------------------------------------------------
# CREATE FOLLOWUP (MANUAL - GST)
# --------------------------------------------------

@router.post(
    "/customer-service-followups",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateFollowupResponse,
    summary="Create Customer Service Followup",
)
async def create_followup(
    payload: CreateFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_followup"},
    )

    log.info("Create followup request received")

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
                        "followup_at": "Followup must be in future"
                    }
                }
            }
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
                    payload.customer_service_id
                )

                if not cs_row:
                    raise HTTPException(404, "Customer service not found")

                if cs_row["status"] != "ACTIVE":
                    raise HTTPException(400, "Service is not active")

                if cs_row["service_status"] == "PROVIDED":
                    raise HTTPException(400, "Service already completed")

                # 👉 FORCE MANUAL (your requirement)
                mode = "MANUAL"

                # --------------------------------------------------
                # STEP 2: VISIBILITY CHECK
                # --------------------------------------------------

                visibility_sql, visibility_values, _ = build_customer_service_visibility(
                    role,
                    emp_id,
                    1,
                    DB_SCHEMA
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
                        *visibility_values
                    )

                    if not allowed:
                        raise HTTPException(403, "Not allowed")

                # --------------------------------------------------
                # STEP 3: ASSIGNMENT LOGIC
                # --------------------------------------------------

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
                        assigned_to
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
                    followup_at
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
                    0
                )

        log.info(
            "Followup created | id=%s | cs_id=%s | assigned=%s",
            new_id,
            payload.customer_service_id,
            assigned_to
        )

        return CreateFollowupResponse(
            id=new_id,
            message="Followup created successfully"
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
# SCHEMA
# --------------------------------------------------

class UpdateFollowupRequest(BaseModel):
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = None
    assigned_to: Optional[int] = None
    status: Optional[str] = None  # COMPLETED / CANCELLED


class UpdateFollowupResponse(BaseModel):
    id: int
    message: str


# --------------------------------------------------
# UPDATE FOLLOWUP (PATCH + STATUS)
# --------------------------------------------------

@router.post(
    "/customer-service-followups/{followup_id}",
    response_model=UpdateFollowupResponse,
    summary="Update Customer Service Followup",
)
async def update_followup(
    followup_id: int,
    payload: UpdateFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "update_followup"},
    )

    log.info("Update followup request received | id=%s", followup_id)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    if not any([
        payload.followup_at,
        payload.remarks,
        payload.assigned_to is not None,
        payload.status
    ]):
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update"
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
                # STEP 1: FETCH FOLLOWUP + SERVICE (LOCK FOR UPDATE 🔥)
                # --------------------------------------------------

                row = await conn.fetchrow(
                    f"""
                    SELECT
                        f.*,
                        cs.rm_id,
                        cs.op_id
                    FROM {DB_SCHEMA}.customer_service_followups f
                    JOIN {DB_SCHEMA}.customer_services cs
                        ON cs.id = f.customer_service_id
                    WHERE f.id = $1
                    FOR UPDATE
                    """,
                    followup_id
                )

                if not row:
                    raise HTTPException(404, "Followup not found")

                # ❌ Prevent modifying finalized followups
                if row["status"] in ["CANCELLED", "COMPLETED" ]:
                    raise HTTPException(
                        status_code=400,
                        detail="Finalized followup cannot be modified"
                    )

                # --------------------------------------------------
                # STEP 2: ROLE VISIBILITY CHECK
                # --------------------------------------------------

                visibility_sql, visibility_values, _ = build_customer_service_visibility(
                    role,
                    emp_id,
                    2,
                    DB_SCHEMA
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
                        *visibility_values
                    )

                    if not allowed:
                        raise HTTPException(
                            status_code=403,
                            detail="Not allowed to update this followup"
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

                    assigned_to = payload.assigned_to

                    valid = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1 FROM {DB_SCHEMA}.employees
                            WHERE emp_id = $1 AND is_active = TRUE
                        )
                        """,
                        assigned_to
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
                        followup_id
                    )

                    if exists:
                        raise HTTPException(409, "Another followup already exists at this time")

                # --------------------------------------------------
                # STEP 6: BUILD UPDATE
                # --------------------------------------------------

                updates = []
                values = []
                idx = 1

                # FOLLOWUP TIME
                if payload.followup_at:
                    updates.append(f"followup_at = ${idx}")
                    values.append(followup_at)
                    idx += 1

                    updates.append("reminder_sent = FALSE")
                    updates.append("reminder_count = 0")

                # REMARKS
                if payload.remarks is not None:
                    updates.append(f"remarks = ${idx}")
                    values.append(payload.remarks)
                    idx += 1

                # ASSIGNMENT
                if payload.assigned_to is not None:
                    updates.append(f"assigned_to = ${idx}")
                    values.append(assigned_to)
                    idx += 1

                # --------------------------------------------------
                # STATUS LOGIC (MERGED 🔥)
                # --------------------------------------------------

                if payload.status:

                    updates.append(f"status = ${idx}")
                    values.append(payload.status)
                    idx += 1

                    # COMPLETED / CANCELLED
                    if payload.status in ["COMPLETED", "CANCELLED"]:
                        updates.append("completed_at = NOW()")

                    # RESET TO PENDING
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
                    *values
                )

        log.info("Followup updated successfully | id=%s", followup_id)

        return UpdateFollowupResponse(
            id=followup_id,
            message="Followup updated successfully"
        )

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")