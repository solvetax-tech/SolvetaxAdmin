import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status, Query
from typing import Optional, List
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")
from datetime import datetime, timezone, timedelta

from app.follow_ups.schemas import (
    CreateFilingFollowupRequest,
    CreateFilingFollowupResponse,
    UpdateFilingFollowupRequest,
    UpdateFilingFollowupResponse,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_service_visibility
from app.security.rbac import require_permission
from app.logger import logger

router = APIRouter(
    prefix="/api/v1/filing-followups",
    tags=["GST Filing Followups"],
)


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
# --------------------------------------------------
# LIST / FILTER FOLLOWUPS
# --------------------------------------------------


@router.get(
    "/filter",
    summary="Filter GST Filing Manual Followups",
)
async def filter_filing_followups(
    statuses: Optional[List[str]] = Query(None),
    customer_service_id: Optional[int] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    id: Optional[int] = None,  # For fetching single by ID if needed
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
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

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            conditions = [
                "f.entity_type = 'GST_FILING'",
                "f.status != 'CANCELLED'"
            ]
            values = []
            idx = 1

            if id:
                conditions.append(f"f.id = ${idx}")
                values.append(id)
                idx += 1

            if statuses:
                conditions.append(f"f.status = ANY(${idx})")
                values.append(statuses)
                idx += 1

            if customer_service_id:
                conditions.append(f"f.customer_service_id = ${idx}")
                values.append(customer_service_id)
                idx += 1

            if from_date:
                conditions.append(f"f.followup_at >= ${idx}")
                values.append(from_date)
                idx += 1

            if to_date:
                conditions.append(f"f.followup_at <= ${idx}")
                values.append(to_date)
                idx += 1

            # Visibility check
            visibility_sql, visibility_values, idx = build_customer_service_visibility(
                role, emp_id, idx, DB_SCHEMA
            )
            if visibility_sql:
                # We need to join with customer_services for visibility
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            where_clause = f"WHERE {' AND '.join(conditions)}"

            query = f"""
                SELECT
                    f.*,
                    c.customer_id,
                    c.full_name,
                    c.mobile,
                    sc.service_name,
                    sc.service_code,
                    cs.rm_id as service_rm_id,
                    cs.op_id as service_op_id,
                    e.username as assigned_to_name
                FROM {DB_SCHEMA}.customer_service_followups f
                JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
                JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
                JOIN {DB_SCHEMA}.service_config sc ON sc.id = cs.service_id
                LEFT JOIN {DB_SCHEMA}.employees e ON e.emp_id = f.assigned_to
                {where_clause}
                ORDER BY f.id DESC
                LIMIT ${idx} OFFSET ${idx+1}
            """

            rows = await conn.fetch(query, *values, limit, offset)

            # Count total
            count_query = f"""
                SELECT COUNT(*)
                FROM {DB_SCHEMA}.customer_service_followups f
                JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
                {where_clause}
            """
            total = await conn.fetchval(count_query, *values)

            return {
                "data": [dict(r) for r in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
                "request_id": request_id
            }

    except Exception:
        log.exception("Error filtering filing followups")
        raise HTTPException(500, "Internal server error")


@router.get(
    "/counts",
    summary="Get GST Filing Followup Counts",
)
async def get_filing_followup_counts(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            conditions = [
                "f.entity_type = 'GST_FILING'",
                "f.status != 'CANCELLED'"
            ]
            values = []
            idx = 3

            visibility_sql, visibility_values, idx = build_customer_service_visibility(
                role, emp_id, idx, DB_SCHEMA
            )
            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            where_clause = f"WHERE {' AND '.join(conditions)}"

            query = f"""
                SELECT
                    COUNT(*) FILTER (WHERE f.followup_at >= $1 AND f.followup_at < $2) as scheduled_today,
                    COUNT(*) FILTER (WHERE f.followup_at >= $1 AND f.followup_at < $2 AND (f.followup_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes' OR f.status = 'COMPLETED')) as evaluated_today,
                    COUNT(*) FILTER (WHERE f.missed_at IS NOT NULL AND f.followup_at >= $1 AND f.followup_at < $2) as overdue_today,
                    COUNT(*) FILTER (WHERE f.status = 'COMPLETED' AND f.missed_at IS NULL AND f.followup_at >= $1 AND f.followup_at < $2) as completed_today,
                    COUNT(*) FILTER (WHERE f.status = 'COMPLETED' AND f.missed_at IS NULL AND f.followup_at >= $1 AND f.followup_at < $2) as successful_today,
                    COUNT(*) FILTER (WHERE f.completed_at IS NULL AND f.followup_at >= $1 AND f.followup_at < $2) as pending_today
                FROM {DB_SCHEMA}.customer_service_followups f
                JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
                {where_clause}
            """
            row = await conn.fetchrow(query, today_start, today_end, *values)
            res_data = dict(row)
            
            # Calculate Success Rate strictly on evaluated tasks
            evaluated = res_data.get("evaluated_today", 0)
            successful = res_data.get("successful_today", 0)
            res_data["success_rate"] = round((successful / evaluated) * 100) if evaluated > 0 else 100

            return {
                "data": res_data,
                "request_id": request_id
            }

    except Exception:
        logger.exception("Error fetching filing followup counts")
        raise HTTPException(500, "Internal server error")


@router.get(
    "/alerts",
    summary="Get GST Filing Followup Alerts",
)
async def get_filing_followup_alerts(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    # For now, alerts are just missed or upcoming follow-ups for the next 24 hours
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    now = datetime.now(timezone.utc)
    next_24h = now + timedelta(hours=24)

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            conditions = [
                "f.entity_type = 'GST_FILING'",
                "f.status IN ('PENDING', 'MISSED')",
                f"(f.followup_at < ${1} OR f.followup_at < ${2})"
            ]
            values = [now, next_24h]
            idx = 3

            visibility_sql, visibility_values, idx = build_customer_service_visibility(
                role, emp_id, idx, DB_SCHEMA
            )
            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            where_clause = f"WHERE {' AND '.join(conditions)}"

            query = f"""
                SELECT
                    f.*,
                    c.customer_id,
                    c.full_name,
                    sc.service_name
                FROM {DB_SCHEMA}.customer_service_followups f
                JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
                JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
                JOIN {DB_SCHEMA}.service_config sc ON sc.id = cs.service_id
                {where_clause}
                ORDER BY f.followup_at ASC
                LIMIT 50
            """
            rows = await conn.fetch(query, *values)

            return {
                "data": [dict(r) for r in rows],
                "request_id": request_id
            }

    except Exception:
        logger.exception("Error fetching filing followup alerts")
        raise HTTPException(500, "Internal server error")
