import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import Query

from app.follow_ups.schemas import (
    CreateFilingFollowupRequest,
    CreateFilingFollowupResponse,
    UpdateFilingFollowupRequest,
    UpdateFilingFollowupResponse,
    FilingFollowupListResponse,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_service_visibility
from app.security.rbac import require_permission
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)

router = APIRouter(
    prefix="/api/v1/filing-followups",
    tags=["GST Filing Followups"],
)


async def _invalidate_filing_followup_related_cache() -> None:
    """
    Invalidate cache tags that can be impacted by followup create/update flows.
    This keeps service list and dashboard followup-sensitive views fresh.
    """
    tags = (
        "filing_followups:filter:index",
        "customer_services:filter:index",
        "customer_services:dashboard:index",
        "customer_services:pending:index",
        "dashboard:gst_missed:gt_one:index",
        "dashboard:gst_missed:buckets:index",
        "dashboard:gst_missed:exact_one:index",
    )
    for tag in tags:
        await redis_invalidate_tag(tag)


@router.get(
    "",
    response_model=FilingFollowupListResponse,
    summary="List GST Filing Manual Followups",
)
async def list_filing_followups(
    followup_id: Optional[int] = Query(None, gt=0),
    customer_service_id: Optional[int] = Query(None, gt=0),
    assigned_to: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    mode: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None, gt=0),
    service_id: Optional[int] = Query(None, gt=0),
    followup_from: Optional[datetime] = Query(None),
    followup_to: Optional[datetime] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "list_filing_followups"},
    )

    status_norm = status_filter.strip().upper() if isinstance(status_filter, str) else None
    mode_norm = mode.strip().upper() if isinstance(mode, str) else None
    valid_status = {"PENDING", "COMPLETED", "MISSED", "CANCELLED"}
    valid_mode = {"MANUAL", "AUTO"}
    if status_norm and status_norm not in valid_status:
        raise HTTPException(status_code=400, detail="Invalid status value")
    if mode_norm and mode_norm not in valid_mode:
        raise HTTPException(status_code=400, detail="Invalid mode value")
    if followup_from and followup_to and followup_from > followup_to:
        raise HTTPException(status_code=400, detail="followup_from must be <= followup_to")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=400, detail="created_from must be <= created_to")

    cache_key = build_cache_key(
        "filing_followups:list",
        role=role,
        emp_id=emp_id,
        followup_id=followup_id,
        customer_service_id=customer_service_id,
        assigned_to=assigned_to,
        status=status_norm,
        mode=mode_norm,
        entity_id=entity_id,
        service_id=service_id,
        followup_from=followup_from,
        followup_to=followup_to,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    async def _load_filing_followups():
        conditions = ["f.entity_type = 'GST_FILING'"]
        values = []
        idx = 1

        if followup_id is not None:
            conditions.append(f"f.id = ${idx}")
            values.append(followup_id)
            idx += 1
        if customer_service_id is not None:
            conditions.append(f"f.customer_service_id = ${idx}")
            values.append(customer_service_id)
            idx += 1
        if assigned_to is not None:
            conditions.append(f"f.assigned_to = ${idx}")
            values.append(assigned_to)
            idx += 1
        if status_norm:
            conditions.append(f"f.status = ${idx}")
            values.append(status_norm)
            idx += 1
        if mode_norm:
            conditions.append(f"f.mode = ${idx}")
            values.append(mode_norm)
            idx += 1
        if entity_id is not None:
            conditions.append(f"f.entity_id = ${idx}")
            values.append(entity_id)
            idx += 1
        if service_id is not None:
            conditions.append(f"f.service_id = ${idx}")
            values.append(service_id)
            idx += 1
        if followup_from is not None:
            conditions.append(f"f.followup_at >= ${idx}")
            values.append(followup_from)
            idx += 1
        if followup_to is not None:
            conditions.append(f"f.followup_at <= ${idx}")
            values.append(followup_to)
            idx += 1
        if created_from is not None:
            conditions.append(f"f.created_at >= ${idx}")
            values.append(created_from)
            idx += 1
        if created_to is not None:
            conditions.append(f"f.created_at <= ${idx}")
            values.append(created_to)
            idx += 1

        visibility_sql, visibility_values, _ = build_customer_service_visibility(
            role,
            emp_id,
            idx,
            DB_SCHEMA,
        )
        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}"
        count_sql = f"""
            SELECT COUNT(*) AS total_count
            FROM {DB_SCHEMA}.customer_service_followups f
            JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
            {where_clause}
        """
        data_sql = f"""
            SELECT
                f.id,
                f.customer_service_id,
                f.mode,
                f.followup_at,
                f.status,
                f.remarks,
                f.assigned_to,
                f.created_by,
                f.completed_at,
                f.reminder_sent,
                f.created_at,
                f.updated_at,
                f.entity_type,
                f.entity_id,
                f.service_id,
                f.reminder_count,
                f.missed_at
            FROM {DB_SCHEMA}.customer_service_followups f
            JOIN {DB_SCHEMA}.customer_services cs ON cs.id = f.customer_service_id
            {where_clause}
            ORDER BY f.followup_at ASC, f.id DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """

        try:
            async with pool.acquire() as conn:
                total_count = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(data_sql, *(values + [limit, offset]))
        except asyncpg.PostgresError:
            log.exception("DB error while listing filing followups")
            raise HTTPException(500, "Database error occurred")
        except Exception:
            log.exception("Unexpected error while listing filing followups")
            raise HTTPException(500, "Internal server error")

        return {
            "data": [dict(row) for row in rows],
            "count": len(rows),
            "total_count": int(total_count or 0),
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_filing_followups,
        ttl_seconds=300,
        tags=["filing_followups:filter:index"],
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
        await _invalidate_filing_followup_related_cache()

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
        await _invalidate_filing_followup_related_cache()

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

