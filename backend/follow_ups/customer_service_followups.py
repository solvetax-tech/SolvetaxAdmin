import logging
import asyncpg
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Depends, status, Query

from backend.follow_ups.schemas import (
    CreateCustomerServiceFollowupRequest,
    CreateCustomerServiceFollowupResponse,
    UpdateCustomerServiceFollowupRequest,
    UpdateCustomerServiceFollowupResponse,
    CustomerServiceFollowupListItem,
    CustomerServiceFollowupListResponse,
)
from backend.utils import (
    get_db_pool,
    DB_SCHEMA,
    generate_uuid,
    build_customer_service_visibility,
)
from backend.security.rbac import require_permission
from backend.logger import logger
from backend.redis_cache import (
    CACHE_TTL_ALERTS,
    CACHE_TTL_COUNTS,
    CACHE_TTL_LIST,
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(
    prefix="/api/v1/customer-service-followups",
    tags=["Customer Service Follow-ups"],
)


def _normalized_followup_statuses(
    status_filter: Optional[str],
    statuses: Optional[List[str]],
) -> Optional[List[str]]:
    parts: List[str] = []
    if statuses:
        for s in statuses:
            if s is None:
                continue
            u = str(s).strip().upper()
            if u:
                parts.append(u)
    if isinstance(status_filter, str) and status_filter.strip():
        parts.append(status_filter.strip().upper())
    if not parts:
        return None
    valid = {"PENDING", "COMPLETED", "MISSED"}
    out: List[str] = []
    seen = set()
    for p in parts:
        if p not in valid:
            raise HTTPException(status_code=400, detail="Invalid followup status value")
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


async def _invalidate_customer_service_followup_cache() -> None:
    tags = (
        "customer_service_followups:list:index",
        "customer_service_followups:counts:index",
        "customer_service_followups:alerts:index",
        "customer_services:filter:index",
        "customer_services:dashboard:index",
        "customer_services:pending:index",
        "customer_services:progress_tracker:index",
    )
    for tag in tags:
        await redis_invalidate_tag(tag)


@router.get(
    "",
    response_model=CustomerServiceFollowupListResponse,
    summary="List and filter customer service follow-ups",
)
async def list_customer_service_followups(
    customer_id: Optional[int] = Query(None, gt=0),
    customer_service_id: Optional[int] = Query(None, gt=0),
    rm_id: Optional[int] = Query(None),
    op_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    statuses: Optional[List[str]] = Query(None),
    service_code: Optional[str] = Query(None),
    followup_from: Optional[datetime] = Query(None),
    followup_to: Optional[datetime] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "list_customer_service_followups"},
    )

    status_list = _normalized_followup_statuses(status_filter, statuses)
    statuses_key = tuple(status_list) if status_list else None

    if followup_from and followup_to and followup_from > followup_to:
        raise HTTPException(status_code=400, detail="followup_from must be <= followup_to")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=400, detail="created_from must be <= created_to")

    sc_norm = service_code.strip().upper() if isinstance(service_code, str) and service_code.strip() else None

    cache_key = build_cache_key(
        "customer_service_followups:list",
        role=role,
        emp_id=emp_id,
        customer_id=customer_id,
        customer_service_id=customer_service_id,
        rm_id=rm_id,
        op_id=op_id,
        statuses=statuses_key,
        service_code=sc_norm,
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

    async def _load_customer_service_followups():
        conditions = [
            "cs.followup_at IS NOT NULL",
        ]
        values = []
        idx = 1

        if customer_id is not None:
            conditions.append(f"cs.customer_id = ${idx}")
            values.append(customer_id)
            idx += 1
        if customer_service_id is not None:
            conditions.append(f"cs.id = ${idx}")
            values.append(customer_service_id)
            idx += 1
        if rm_id is not None:
            conditions.append(f"cs.rm_id = ${idx}")
            values.append(rm_id)
            idx += 1
        if op_id is not None:
            conditions.append(f"cs.op_id = ${idx}")
            values.append(op_id)
            idx += 1
        if status_list:
            if len(status_list) == 1:
                conditions.append(f"cs.followup_status = ${idx}")
                values.append(status_list[0])
                idx += 1
            else:
                conditions.append(f"cs.followup_status = ANY(${idx}::text[])")
                values.append(status_list)
                idx += 1
        if sc_norm:
            conditions.append(f"upper(trim(cs.service_code)) = ${idx}")
            values.append(sc_norm)
            idx += 1
        if followup_from is not None:
            conditions.append(f"cs.followup_at >= ${idx}")
            values.append(followup_from)
            idx += 1
        if followup_to is not None:
            conditions.append(f"cs.followup_at <= ${idx}")
            values.append(followup_to)
            idx += 1
        if created_from is not None:
            conditions.append(f"cs.created_at >= ${idx}")
            values.append(created_from)
            idx += 1
        if created_to is not None:
            conditions.append(f"cs.created_at <= ${idx}")
            values.append(created_to)
            idx += 1

        role_norm = (role or "").strip().upper() or None
        visibility_sql, visibility_values, idx = build_customer_service_visibility(
            role_norm,
            emp_id,
            idx,
            DB_SCHEMA,
        )
        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}"
        lim_idx = idx
        off_idx = idx + 1

        # Single scan: window count avoids a second full pass (was ~2× latency on large tables).
        data_sql = f"""
            SELECT
                cs.id,
                cs.id AS customer_service_id,
                cs.customer_id,
                cs.service_code,
                cs.service_status,
                cs.followup_at,
                cs.followup_status,
                cs.followup_remarks AS remarks,
                cs.completed_at,
                cs.missed_at,
                cs.provided_at,
                cs.is_active,
                cs.rm_id,
                cs.op_id,
                cs.created_at,
                cs.updated_at,
                c.full_name,
                c.mobile,
                sc.service_name,
                rm.first_name AS rm_first_name,
                op.first_name AS op_first_name,
                COUNT(*) OVER()::bigint AS total_count
            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
            LEFT JOIN LATERAL (
                SELECT sc.service_name
                FROM {DB_SCHEMA}.service_config sc
                WHERE upper(trim(sc.service_code)) = upper(trim(cs.service_code))
                  AND sc.is_active IS NOT DISTINCT FROM TRUE
                LIMIT 1
            ) sc ON TRUE
            LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = cs.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = cs.op_id
            {where_clause}
            ORDER BY cs.followup_at ASC NULLS LAST, cs.id DESC
            LIMIT ${lim_idx} OFFSET ${off_idx}
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(data_sql, *values, limit, offset)
                total = int(rows[0]["total_count"]) if rows else 0
        except asyncpg.PostgresError:
            log.exception("DB error while listing customer service followups")
            raise HTTPException(500, "Database error occurred")
        except Exception:
            log.exception("Unexpected error while listing customer service followups")
            raise HTTPException(500, "Internal server error")

        items = []
        for row in rows:
            row_dict = dict(row)
            row_dict.pop("total_count", None)
            items.append(CustomerServiceFollowupListItem(**row_dict).model_dump())

        return {
            "data": items,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_customer_service_followups,
        ttl_seconds=CACHE_TTL_LIST,
        tags=["customer_service_followups:list:index"],
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateCustomerServiceFollowupResponse,
    summary="Schedule a follow-up on a customer service row",
)
async def create_customer_service_followup(
    payload: CreateCustomerServiceFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_customer_service_followup"},
    )

    log.info("Create customer service follow-up request received")

    if payload.followup_at.tzinfo is None:
        followup_at = payload.followup_at.replace(tzinfo=timezone.utc)
    else:
        followup_at = payload.followup_at.astimezone(timezone.utc)

    if followup_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Invalid followup time",
                    "fields": {"followup_at": "Followup must be in future"},
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
                cs_row = await conn.fetchrow(
                    f"""
                    SELECT
                        cs.id,
                        cs.customer_id,
                        cs.rm_id,
                        cs.op_id,
                        cs.service_status,
                        cs.is_active,
                        cs.service_code,
                        cs.followup_at,
                        cs.followup_status
                    FROM {DB_SCHEMA}.customer_services cs
                    WHERE cs.id = $1
                    FOR UPDATE
                    """,
                    payload.customer_service_id,
                )

                if not cs_row:
                    raise HTTPException(404, "Customer service not found")

                if cs_row.get("is_active") is False:
                    raise HTTPException(400, "Service is not active")

                if cs_row["service_status"] == "PROVIDED":
                    raise HTTPException(400, "Service already completed")

                if (
                    cs_row.get("followup_at") is not None
                    and str(cs_row.get("followup_status") or "").upper() == "PENDING"
                ):
                    raise HTTPException(409, "Duplicate followup")

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
                        payload.customer_service_id,
                        *visibility_values,
                    )

                    if not allowed:
                        raise HTTPException(403, "Not allowed")

                updated_id = await conn.fetchval(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                       SET followup_at = $2,
                           followup_status = 'PENDING',
                           followup_remarks = $3,
                           completed_at = NULL,
                           missed_at = NULL
                     WHERE id = $1
                     RETURNING id
                    """,
                    payload.customer_service_id,
                    followup_at,
                    payload.remarks,
                )

                if not updated_id:
                    raise HTTPException(404, "Customer service not found")

        log.info(
            "Customer service follow-up scheduled | customer_services.id=%s",
            updated_id,
        )
        await _invalidate_customer_service_followup_cache()

        return CreateCustomerServiceFollowupResponse(
            id=int(updated_id),
            message="Follow-up created successfully",
        )

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")


@router.post(
    "/{customer_service_id}",
    response_model=UpdateCustomerServiceFollowupResponse,
    summary="Update a customer service follow-up",
)
async def update_customer_service_followup(
    customer_service_id: int,
    payload: UpdateCustomerServiceFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "update_customer_service_followup"},
    )

    log.info("Update customer service follow-up | customer_service_id=%s", customer_service_id)

    if not any(
        [
            payload.followup_at,
            payload.remarks is not None,
            payload.status,
        ]
    ):
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update",
        )

    valid_status = {"PENDING", "COMPLETED", "MISSED"}
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
                row = await conn.fetchrow(
                    f"""
                    SELECT cs.*
                    FROM {DB_SCHEMA}.customer_services cs
                    WHERE cs.id = $1
                      AND cs.followup_at IS NOT NULL
                    FOR UPDATE
                    """,
                    customer_service_id,
                )

                if not row:
                    raise HTTPException(404, "Followup not found")

                if str(row.get("followup_status") or "").upper() == "COMPLETED":
                    raise HTTPException(
                        status_code=400,
                        detail="Finalized followup cannot be modified",
                    )

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
                        customer_service_id,
                        *visibility_values,
                    )

                    if not allowed:
                        raise HTTPException(
                            status_code=403,
                            detail="Not allowed to update this followup",
                        )

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

                if payload.followup_at:
                    exists = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            FROM {DB_SCHEMA}.customer_services cs
                            WHERE cs.customer_id = $1
                              AND cs.id != $2
                              AND cs.followup_at = $3
                              AND cs.followup_status = 'PENDING'
                        )
                        """,
                        row["customer_id"],
                        customer_service_id,
                        followup_at,
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

                if payload.remarks is not None:
                    updates.append(f"followup_remarks = ${idx}")
                    values.append(payload.remarks)
                    idx += 1

                if payload.status:
                    updates.append(f"followup_status = ${idx}")
                    values.append(payload.status)
                    idx += 1

                    if payload.status == "COMPLETED":
                        updates.append("completed_at = COALESCE(completed_at, NOW())")
                        # Preserve missed_at so late completions stay auditable; stamp if overdue but not yet flagged.
                        updates.append(
                            "missed_at = CASE "
                            "WHEN missed_at IS NOT NULL THEN missed_at "
                            "WHEN followup_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes' THEN NOW() "
                            "ELSE missed_at END"
                        )
                    elif payload.status == "PENDING":
                        updates.append("completed_at = NULL")
                        updates.append("missed_at = NULL")
                    elif payload.status == "MISSED":
                        updates.append("missed_at = COALESCE(missed_at, NOW())")

                if not updates:
                    raise HTTPException(400, "Nothing to update")

                values.append(customer_service_id)

                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services cs
                    SET {", ".join(updates)}
                    WHERE cs.id = ${idx}
                    """,
                    *values,
                )

        log.info("Customer service follow-up updated | customer_service_id=%s", customer_service_id)
        await _invalidate_customer_service_followup_cache()

        return UpdateCustomerServiceFollowupResponse(
            id=customer_service_id,
            message="Follow-up updated successfully",
        )

    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(500, "Database error occurred")

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(500, "Internal server error")


@router.get(
    "/counts",
    summary="Customer service follow-up counts for a follow-up date range",
)
async def get_customer_service_followup_counts(
    followup_from: Optional[datetime] = Query(None),
    followup_to: Optional[datetime] = Query(None),
    dates: Optional[str] = Query(
        None,
        description="Comma-separated YYYY-MM-DD keys; when set, only those calendar days are counted",
    ),
    service_code: Optional[str] = Query(None),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Each bound defaults independently to today's window so a lone followup_from
    # or followup_to is still honored (previously both had to be supplied).
    range_start = followup_from if followup_from is not None else today_start
    range_end = followup_to if followup_to is not None else today_end
    if range_start > range_end:
        raise HTTPException(status_code=400, detail="followup_from must be <= followup_to")

    date_keys = None
    if isinstance(dates, str) and dates.strip():
        date_keys = sorted({d.strip() for d in dates.split(",") if d.strip()})

    sc_norm = (
        service_code.strip().upper()
        if isinstance(service_code, str) and service_code.strip()
        else None
    )

    cache_key = build_cache_key(
        "customer_service_followups:counts",
        role=role,
        emp_id=emp_id,
        followup_from=range_start,
        followup_to=range_end,
        dates=tuple(date_keys) if date_keys else None,
        service_code=sc_norm,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        logger.exception("DB connection failed (customer service followup counts)")
        raise HTTPException(500, "Database connection error")

    async def _load_customer_service_followup_counts():
        conditions = [
            "cs.followup_at IS NOT NULL",
            "cs.followup_at >= $1",
            "cs.followup_at <= $2",
        ]
        values: list = [range_start, range_end]
        idx = 3

        if date_keys:
            conditions.append(
                f"to_char(cs.followup_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD') = ANY(${idx}::text[])"
            )
            values.append(date_keys)
            idx += 1

        if sc_norm:
            conditions.append(f"upper(trim(cs.service_code)) = ${idx}")
            values.append(sc_norm)
            idx += 1

        visibility_sql, visibility_values, idx = build_customer_service_visibility(
            role, emp_id, idx, DB_SCHEMA
        )
        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        query = f"""
            SELECT
                COUNT(*) AS scheduled_today,
                COUNT(*) FILTER (
                    WHERE cs.followup_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                       OR cs.completed_at IS NOT NULL
                ) AS evaluated_today,
                COUNT(*) FILTER (
                    WHERE cs.missed_at IS NOT NULL
                      AND cs.completed_at IS NULL
                ) AS overdue_pending_today,
                COUNT(*) FILTER (
                    WHERE cs.missed_at IS NOT NULL
                      AND cs.completed_at IS NOT NULL
                ) AS overdue_completed_today,
                COUNT(*) FILTER (
                    WHERE cs.completed_at IS NOT NULL
                      AND cs.missed_at IS NULL
                ) AS completed_today,
                COUNT(*) FILTER (
                    WHERE cs.completed_at IS NOT NULL
                      AND cs.missed_at IS NULL
                ) AS successful_today,
                COUNT(*) FILTER (
                    WHERE cs.completed_at IS NULL
                      AND cs.followup_status = 'PENDING'
                      AND cs.missed_at IS NULL
                      AND cs.followup_at IS NOT NULL
                      AND cs.followup_at <= NOW()
                      AND cs.followup_at > NOW() - INTERVAL '10 minutes'
                ) AS pending_today
            FROM {DB_SCHEMA}.customer_services cs
            {where_clause}
        """

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *values)
        except asyncpg.PostgresError:
            logger.exception("DB error while fetching customer service followup counts")
            raise HTTPException(500, "Database error occurred")
        except Exception:
            logger.exception("Unexpected error while fetching customer service followup counts")
            raise HTTPException(500, "Internal server error")

        res_data = dict(row)
        res_data["overdue_today"] = res_data.get("overdue_pending_today", 0)

        scheduled = res_data.get("scheduled_today", 0)
        successful = res_data.get("successful_today", 0)
        res_data["success_rate"] = (
            round((successful / scheduled) * 100) if scheduled > 0 else 100
        )

        return {
            "data": res_data,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_customer_service_followup_counts,
        ttl_seconds=CACHE_TTL_COUNTS,
        tags=["customer_service_followups:counts:index"],
    )


@router.get(
    "/alerts",
    summary="Customer service follow-up alerts (due within 24h)",
)
async def get_customer_service_followup_alerts(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = (current_user.get("role") or "").strip().upper() or None

    now = datetime.now(timezone.utc)
    next_24h = now + timedelta(hours=24)
    time_bucket = int(now.timestamp() // 300)

    cache_key = build_cache_key(
        "customer_service_followups:alerts",
        role=role,
        emp_id=emp_id,
        time_bucket=time_bucket,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        logger.exception("DB connection failed (customer service followup alerts)")
        raise HTTPException(500, "Database connection error")

    async def _load_customer_service_followup_alerts():
        conditions = [
            "cs.followup_at IS NOT NULL",
            "cs.followup_status IN ('PENDING', 'MISSED')",
            "cs.followup_at >= $1",
            "cs.followup_at <= $2",
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
                cs.*,
                c.customer_id,
                c.full_name,
                sc.service_name
            FROM {DB_SCHEMA}.customer_services cs
            JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
            LEFT JOIN {DB_SCHEMA}.service_config sc
              ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
             AND sc.is_active IS TRUE
            {where_clause}
            ORDER BY cs.followup_at ASC
            LIMIT 50
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values)
        except asyncpg.PostgresError:
            logger.exception("DB error while fetching customer service followup alerts")
            raise HTTPException(500, "Database error occurred")
        except Exception:
            logger.exception("Unexpected error while fetching customer service followup alerts")
            raise HTTPException(500, "Internal server error")

        return {
            "data": [dict(r) for r in rows],
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_customer_service_followup_alerts,
        ttl_seconds=CACHE_TTL_ALERTS,
        tags=["customer_service_followups:alerts:index"],
    )
