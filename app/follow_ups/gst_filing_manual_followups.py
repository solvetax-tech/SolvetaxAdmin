import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_service_visibility
from app.security.rbac import require_permission
from app.logger import logger

router = APIRouter(
    prefix="/api/v1/filing-followups",
    tags=["GST Filing Followups"],
)


class CreateFilingFollowupRequest(BaseModel):
    customer_service_id: int
    followup_at: datetime
    remarks: Optional[str] = None
    assigned_to: Optional[int] = Field(
        None,
        description="Ignored when JWT role is RM or OP; assigned_to is set to current emp_id.",
    )


class UpdateFilingFollowupRequest(BaseModel):
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = None
    assigned_to: Optional[int] = Field(
        None,
        description="If JWT role is RM or OP, API sets assigned_to to current emp_id.",
    )
    status: Optional[str] = None  # PENDING / COMPLETED / CANCELLED


@router.get(
    "/filter",
    summary="Filter GST Filing Followups (Manual)",
)
async def filter_filing_followups(
    id: Optional[int] = None,
    customer_service_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    service_id: Optional[int] = None,
    status: Optional[str] = None,
    statuses: Optional[List[str]] = Query(None),
    assigned_to: Optional[int] = None,
    created_by: Optional[int] = None,
    followup_from: Optional[datetime] = None,
    followup_to: Optional[datetime] = None,
    completed_from: Optional[datetime] = None,
    completed_to: Optional[datetime] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    is_overdue: Optional[bool] = None,
    is_completed_on_time: Optional[bool] = None,
    is_upcoming: Optional[bool] = None,
    today_only: Optional[bool] = None,
    reminder_sent: Optional[bool] = None,
    high_reminder: Optional[bool] = None,
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
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_filing_followups"},
    )

    valid_status = {"PENDING", "COMPLETED", "MISSED", "CANCELLED"}
    if status and status not in valid_status:
        raise HTTPException(400, "Invalid status")
    if statuses:
        invalid = [s for s in statuses if s not in valid_status]
        if invalid:
            raise HTTPException(400, f"Invalid statuses: {invalid}")
    if is_overdue and is_upcoming:
        raise HTTPException(400, "Cannot use is_overdue and is_upcoming together")
    if today_only and (followup_from or followup_to):
        raise HTTPException(400, "today_only cannot be used with date filters")

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
        conditions = ["cs.entity_type = 'GST_FILING'", "f.mode = 'MANUAL'"]
        values = []
        idx = 1

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
        if status:
            conditions.append(f"f.status = ${idx}")
            values.append(status)
            idx += 1
        if statuses:
            conditions.append(f"f.status = ANY(${idx})")
            values.append([s for s in statuses if s])
            idx += 1
        if assigned_to is not None:
            conditions.append(f"f.assigned_to = ${idx}")
            values.append(assigned_to)
            idx += 1
        if created_by is not None:
            conditions.append(f"f.created_by = ${idx}")
            values.append(created_by)
            idx += 1
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
        if cursor:
            conditions.append(f"f.created_at < ${idx}")
            values.append(cursor)
            idx += 1

        visibility_sql, visibility_values, idx = build_customer_service_visibility(
            role, emp_id, idx, DB_SCHEMA
        )
        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.customer_service_followups f
            JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
            {where_clause}
        """

        if cursor:
            pagination_sql = f"LIMIT ${idx}"
            values_with_pagination = values + [limit]
        else:
            pagination_sql = f"LIMIT ${idx} OFFSET ${idx+1}"
            values_with_pagination = values + [limit, offset]

        main_sql = f"""
            SELECT
                f.*,
                (f.followup_at < NOW() AND f.status = 'PENDING') AS is_overdue_flag,
                (f.followup_at >= NOW() AND f.status = 'PENDING') AS is_upcoming_flag,
                cs.customer_id,
                cs.service_id,
                cs.entity_id,
                c.full_name,
                s.service_code,
                s.service_name,
                assignee.first_name AS assigned_to_name,
                creator.first_name AS created_by_name
            FROM {DB_SCHEMA}.customer_service_followups f
            JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
            JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
            JOIN {DB_SCHEMA}.service_config s ON s.id = cs.service_id
            LEFT JOIN {DB_SCHEMA}.employees assignee ON assignee.emp_id = f.assigned_to
            LEFT JOIN {DB_SCHEMA}.employees creator ON creator.emp_id = f.created_by
            {where_clause}
            ORDER BY f.created_at DESC, f.id DESC
            {pagination_sql}
        """

        async with pool.acquire() as conn:
            total_count = None if cursor else await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(main_sql, *values_with_pagination)

        next_cursor = rows[-1]["created_at"] if rows else None
        return {
            "data": [dict(row) for row in rows],
            "next_cursor": next_cursor,
            "count": total_count,
            "request_id": request_id,
        }
    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")
    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing Manual Followup",
)
async def create_filing_followup(
    payload: CreateFilingFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_filing_followup"},
    )

    followup_at = (
        payload.followup_at.replace(tzinfo=timezone.utc)
        if payload.followup_at.tzinfo is None
        else payload.followup_at.astimezone(timezone.utc)
    )
    if followup_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Followup must be in future")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                cs_row = await conn.fetchrow(
                    f"""
                    SELECT cs.id, cs.rm_id, cs.op_id, cs.service_status, cs.status,
                           cs.entity_type, cs.entity_id, cs.service_id
                    FROM {DB_SCHEMA}.customer_services cs
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

                visibility_sql, visibility_values, _ = build_customer_service_visibility(
                    role, emp_id, 1, DB_SCHEMA
                )
                if visibility_sql:
                    allowed = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1 FROM {DB_SCHEMA}.customer_services cs
                            WHERE cs.id = $1 AND {visibility_sql}
                        )
                        """,
                        payload.customer_service_id,
                        *visibility_values,
                    )
                    if not allowed:
                        raise HTTPException(403, "Not allowed")

                if role in ("RM", "OP"):
                    assigned_to = emp_id
                else:
                    assigned_to = payload.assigned_to or cs_row["rm_id"] or emp_id
                if assigned_to:
                    valid_assignee = await conn.fetchval(
                        f"""SELECT EXISTS(
                                SELECT 1 FROM {DB_SCHEMA}.employees
                                WHERE emp_id = $1 AND is_active = TRUE
                            )""",
                        assigned_to,
                    )
                    if not valid_assignee:
                        raise HTTPException(400, "Invalid assigned_to")

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

                new_id = await conn.fetchval(
                    f"""
                    INSERT INTO {DB_SCHEMA}.customer_service_followups
                    (
                        customer_service_id, mode, followup_at, status, remarks,
                        assigned_to, created_by, entity_type, entity_id, service_id, reminder_count
                    )
                    VALUES ($1,'MANUAL',$2,'PENDING',$3,$4,$5,$6,$7,$8,$9)
                    RETURNING id
                    """,
                    payload.customer_service_id,
                    followup_at,
                    payload.remarks,
                    assigned_to,
                    emp_id,
                    cs_row["entity_type"],
                    cs_row["entity_id"],
                    cs_row["service_id"],
                    0,
                )

        return {
            "id": new_id,
            "message": "GST filing followup created successfully",
            "request_id": request_id,
        }
    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")
    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")


@router.post(
    "/{followup_id}",
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

    if not any([payload.followup_at, payload.remarks, payload.assigned_to is not None, payload.status]):
        raise HTTPException(400, "At least one field must be provided for update")

    valid_status = {"PENDING", "COMPLETED", "CANCELLED"}
    if payload.status and payload.status not in valid_status:
        raise HTTPException(400, "Invalid status value")

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT f.*, cs.rm_id, cs.op_id, cs.entity_type
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
                if row["entity_type"] != "GST_FILING":
                    raise HTTPException(400, "This followup does not belong to GST filing")
                if row["status"] in ["CANCELLED", "COMPLETED"]:
                    raise HTTPException(400, "Finalized followup cannot be modified")

                visibility_sql, visibility_values, _ = build_customer_service_visibility(
                    role, emp_id, 2, DB_SCHEMA
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
                        raise HTTPException(403, "Not allowed to update this followup")

                if payload.followup_at:
                    followup_at = (
                        payload.followup_at.replace(tzinfo=timezone.utc)
                        if payload.followup_at.tzinfo is None
                        else payload.followup_at.astimezone(timezone.utc)
                    )
                    if followup_at < datetime.now(timezone.utc):
                        raise HTTPException(400, "Followup must be in future")
                    if followup_at > datetime.now(timezone.utc) + timedelta(days=60):
                        raise HTTPException(400, "Followup cannot be scheduled beyond 60 days")
                else:
                    followup_at = row["followup_at"]

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

                values.append(followup_id)
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_service_followups
                    SET {", ".join(updates)}
                    WHERE id = ${idx}
                    """,
                    *values,
                )

        return {
            "id": followup_id,
            "message": "GST filing followup updated successfully",
            "request_id": request_id,
        }
    except asyncpg.PostgresError:
        raise HTTPException(500, "Database error occurred")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Internal server error")
