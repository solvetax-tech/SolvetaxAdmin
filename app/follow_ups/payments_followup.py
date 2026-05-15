"""Payment collection follow-ups stored on ``payments`` (followup_* / completed_at / missed_at)."""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.follow_ups.schemas import (
    CreatePaymentFollowupRequest,
    CreatePaymentFollowupResponse,
    PaymentFollowupListItem,
    PaymentFollowupListResponse,
    UpdatePaymentFollowupRequest,
    UpdatePaymentFollowupResponse,
)
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.security.rbac import require_permission
from app.utils import (
    DB_SCHEMA,
    build_payment_followup_visibility,
    generate_uuid,
    get_db_pool,
)

# Follow-ups for filing-level payments, per-return-detail payments (recurring periods), and catalog services.
PAYMENT_FOLLOWUP_ENTITY_TYPES: tuple[str, ...] = (
    "GST_FILING",
    "GST_FILING_RETURN_DETAILS",
    "CUSTOMER_SERVICE",
)

router = APIRouter(
    prefix="/api/v1/payment-followups",
    tags=["Payment follow-ups"],
)


def _payments_followup_list_tag() -> str:
    return "payment_followups:list:index"


async def _invalidate_payment_followup_cache() -> None:
    await redis_invalidate_tag(_payments_followup_list_tag())
    await redis_invalidate_tag("registration_payments:filter:index")
    await redis_invalidate_tag("payments_config:get_amount:index")


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


def _payment_followup_entity_joins() -> str:
    return f"""
            FROM {DB_SCHEMA}.payments rp
            LEFT JOIN {DB_SCHEMA}.customers c ON rp.customer_id = c.customer_id
            LEFT JOIN {DB_SCHEMA}.gst_filings f
                   ON rp.entity_type = 'GST_FILING' AND rp.entity_id = f.id
            LEFT JOIN {DB_SCHEMA}.gst_filing_return_details rd
                   ON rp.entity_type = 'GST_FILING_RETURN_DETAILS' AND rp.entity_id = rd.id
            LEFT JOIN {DB_SCHEMA}.gst_filings f_rd
                   ON f_rd.id = rd.gst_filing_id
            LEFT JOIN {DB_SCHEMA}.customer_services cs
                   ON rp.entity_type = 'CUSTOMER_SERVICE' AND rp.entity_id = cs.id
            LEFT JOIN {DB_SCHEMA}.employees rm ON c.rm_id = rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees op ON c.op_id = op.emp_id
    """


def _assert_payment_followup_entity_type(entity_type: Optional[str]) -> str:
    if not isinstance(entity_type, str) or not entity_type.strip():
        raise HTTPException(
            status_code=400,
            detail="Payment follow-ups apply only to GST_FILING, GST_FILING_RETURN_DETAILS, or CUSTOMER_SERVICE payments.",
        )
    et = entity_type.strip().upper()
    if et not in PAYMENT_FOLLOWUP_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Payment follow-ups apply only to GST_FILING, GST_FILING_RETURN_DETAILS, or CUSTOMER_SERVICE payments.",
        )
    return et


@router.get(
    "",
    response_model=PaymentFollowupListResponse,
    summary="List payment collection follow-ups (GST filing + customer service; payment_status=PENDING only)",
)
async def list_payment_followups(
    payment_id: Optional[int] = Query(None, gt=0),
    customer_id: Optional[int] = Query(None, gt=0),
    entity_id: Optional[int] = Query(None, gt=0),
    entity_type: Optional[str] = Query(
        None,
        description=(
            "Optional: GST_FILING, GST_FILING_RETURN_DETAILS, or CUSTOMER_SERVICE "
            "(GST registration / ITR excluded)."
        ),
    ),
    status_filter: Optional[str] = Query(None, alias="status"),
    statuses: Optional[List[str]] = Query(None),
    followup_from: Optional[datetime] = Query(None),
    followup_to: Optional[datetime] = Query(None),
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
        {"request_id": request_id, "emp_id": emp_id, "api": "list_payment_followups"},
    )

    status_list = _normalized_followup_statuses(status_filter, statuses)
    statuses_key = tuple(status_list) if status_list else None

    if followup_from and followup_to and followup_from > followup_to:
        raise HTTPException(status_code=400, detail="followup_from must be <= followup_to")

    et_norm: Optional[str] = None
    if isinstance(entity_type, str) and entity_type.strip():
        et_norm = _assert_payment_followup_entity_type(entity_type)

    cache_key = build_cache_key(
        "payment_followups:list",
        role=role,
        emp_id=emp_id,
        payment_id=payment_id,
        customer_id=customer_id,
        entity_id=entity_id,
        entity_type=et_norm,
        statuses=statuses_key,
        followup_from=followup_from,
        followup_to=followup_to,
        limit=limit,
        offset=offset,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    async def _load_payment_followups():
        conditions = [
            "rp.followup_at IS NOT NULL",
            "rp.payment_status = 'PENDING'",
        ]
        values: list = []
        idx = 1

        if payment_id is not None:
            conditions.append(f"rp.id = ${idx}")
            values.append(payment_id)
            idx += 1
        if customer_id is not None:
            conditions.append(f"rp.customer_id = ${idx}")
            values.append(customer_id)
            idx += 1
        if entity_id is not None:
            conditions.append(f"rp.entity_id = ${idx}")
            values.append(entity_id)
            idx += 1
        if et_norm:
            conditions.append(f"upper(trim(rp.entity_type)) = ${idx}")
            values.append(et_norm)
            idx += 1
        else:
            conditions.append(f"rp.entity_type = ANY(${idx}::text[])")
            values.append(list(PAYMENT_FOLLOWUP_ENTITY_TYPES))
            idx += 1
        if status_list:
            if len(status_list) == 1:
                conditions.append(f"rp.followup_status = ${idx}")
                values.append(status_list[0])
                idx += 1
            else:
                conditions.append(f"rp.followup_status = ANY(${idx}::text[])")
                values.append(status_list)
                idx += 1
        if followup_from is not None:
            conditions.append(f"rp.followup_at >= ${idx}")
            values.append(followup_from)
            idx += 1
        if followup_to is not None:
            conditions.append(f"rp.followup_at <= ${idx}")
            values.append(followup_to)
            idx += 1

        visibility_sql, visibility_values, idx = build_payment_followup_visibility(
            str(role or "").strip().upper(),
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

        joins = _payment_followup_entity_joins()
        count_sql = f"""
            SELECT COUNT(*)::bigint
            {joins}
            {where_clause}
        """
        data_sql = f"""
            SELECT
                rp.id,
                rp.customer_id,
                rp.entity_id,
                rp.entity_type,
                rp.payment_status,
                rp.amount,
                rp.discount,
                rp.net_amount,
                rp.paid_amount,
                rp.remaining_amount,
                rp.followup_at,
                rp.followup_status,
                rp.followup_remarks AS remarks,
                rp.completed_at,
                rp.missed_at,
                rp.is_active,
                rp.created_at,
                rp.updated_at,
                c.full_name,
                c.mobile,
                c.rm_id,
                c.op_id,
                rm.first_name AS rm_name,
                op.first_name AS op_name
            {joins}
            {where_clause}
            ORDER BY rp.followup_at ASC NULLS LAST, rp.id DESC
            LIMIT ${lim_idx} OFFSET ${off_idx}
        """

        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(data_sql, *values, limit, offset)
        except asyncpg.PostgresError:
            log.exception("DB error listing payment followups")
            raise HTTPException(status_code=500, detail="Database error occurred")
        except Exception:
            log.exception("Unexpected error listing payment followups")
            raise HTTPException(status_code=500, detail="Internal server error")

        items = [PaymentFollowupListItem(**dict(row)).model_dump() for row in rows]

        return {
            "data": items,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_payment_followups,
        ttl_seconds=300,
        tags=[_payments_followup_list_tag()],
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreatePaymentFollowupResponse,
    summary="Schedule a payment collection follow-up (payment must be PENDING; GST filing or customer service only)",
)
async def create_payment_followup(
    payload: CreatePaymentFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_payment_followup"},
    )

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
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT rp.id, rp.customer_id, rp.is_active,
                           rp.followup_at, rp.followup_status, rp.entity_type,
                           rp.payment_status
                      FROM {DB_SCHEMA}.payments rp
                     WHERE rp.id = $1
                     FOR UPDATE
                    """,
                    payload.payment_id,
                )

                if not row:
                    raise HTTPException(status_code=404, detail="Payment not found")

                if row.get("is_active") is False:
                    raise HTTPException(status_code=400, detail="Payment is not active")

                if str(row.get("payment_status") or "").strip().upper() != "PENDING":
                    raise HTTPException(
                        status_code=400,
                        detail="Follow-ups are allowed only when payment_status is PENDING.",
                    )

                pet = str(row.get("entity_type") or "").strip().upper()
                if pet not in PAYMENT_FOLLOWUP_ENTITY_TYPES:
                    raise HTTPException(
                        status_code=400,
                        detail="Payment follow-ups apply only to GST_FILING, GST_FILING_RETURN_DETAILS, or CUSTOMER_SERVICE payments.",
                    )

                if (
                    row.get("followup_at") is not None
                    and str(row.get("followup_status") or "").upper() == "PENDING"
                ):
                    raise HTTPException(status_code=409, detail="Duplicate followup")

                visibility_sql, visibility_values, _ = build_payment_followup_visibility(
                    str(role or "").strip().upper(),
                    emp_id,
                    2,
                    DB_SCHEMA,
                )

                if visibility_sql:
                    allowed = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            {_payment_followup_entity_joins()}
                            WHERE rp.id = $1 AND {visibility_sql}
                        )
                        """,
                        payload.payment_id,
                        *visibility_values,
                    )
                    if not allowed:
                        raise HTTPException(status_code=403, detail="Not allowed")

                updated_id = await conn.fetchval(
                    f"""
                    UPDATE {DB_SCHEMA}.payments
                       SET followup_at = $2,
                           followup_status = 'PENDING',
                           followup_remarks = $3,
                           completed_at = NULL,
                           missed_at = NULL,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = TRUE
                       AND payment_status = 'PENDING'
                       AND entity_type = ANY($4::text[])
                     RETURNING id
                    """,
                    payload.payment_id,
                    followup_at,
                    payload.remarks,
                    list(PAYMENT_FOLLOWUP_ENTITY_TYPES),
                )

                if not updated_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot schedule follow-up: payment not found, inactive, not PENDING, or wrong entity type.",
                    )

        log.info("Payment follow-up scheduled | payments.id=%s", updated_id)
        await _invalidate_payment_followup_cache()

        return CreatePaymentFollowupResponse(
            id=int(updated_id),
            message="Follow-up created successfully",
        )

    except HTTPException:
        raise
    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(status_code=500, detail="Database error occurred")
    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{payment_id}",
    response_model=UpdatePaymentFollowupResponse,
    summary="Update a payment collection follow-up (payment must remain PENDING)",
)
async def update_payment_followup(
    payment_id: int,
    payload: UpdatePaymentFollowupRequest,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "update_payment_followup"},
    )

    if not any([payload.followup_at, payload.remarks is not None, payload.status]):
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update",
        )

    valid_status = {"PENDING", "COMPLETED", "MISSED"}
    if payload.status and payload.status not in valid_status:
        raise HTTPException(status_code=400, detail="Invalid status value")

    if payload.status == "COMPLETED" and payload.followup_at:
        raise HTTPException(status_code=400, detail="Cannot change followup time while completing")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT rp.*
                      FROM {DB_SCHEMA}.payments rp
                     WHERE rp.id = $1
                       AND rp.followup_at IS NOT NULL
                     FOR UPDATE
                    """,
                    payment_id,
                )

                if not row:
                    raise HTTPException(status_code=404, detail="Followup not found")

                pet = str(row.get("entity_type") or "").strip().upper()
                if pet not in PAYMENT_FOLLOWUP_ENTITY_TYPES:
                    raise HTTPException(
                        status_code=400,
                        detail="Payment follow-ups apply only to GST_FILING, GST_FILING_RETURN_DETAILS, or CUSTOMER_SERVICE payments.",
                    )

                if str(row.get("payment_status") or "").strip().upper() != "PENDING":
                    raise HTTPException(
                        status_code=400,
                        detail="Follow-ups can only be updated while payment_status is PENDING.",
                    )

                if str(row.get("followup_status") or "").upper() == "COMPLETED":
                    raise HTTPException(status_code=400, detail="Finalized followup cannot be modified")

                visibility_sql, visibility_values, _ = build_payment_followup_visibility(
                    str(role or "").strip().upper(),
                    emp_id,
                    2,
                    DB_SCHEMA,
                )

                if visibility_sql:
                    allowed = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            {_payment_followup_entity_joins()}
                            WHERE rp.id = $1 AND {visibility_sql}
                        )
                        """,
                        payment_id,
                        *visibility_values,
                    )
                    if not allowed:
                        raise HTTPException(status_code=403, detail="Not allowed to update this followup")

                if payload.followup_at:
                    if payload.followup_at.tzinfo is None:
                        followup_at = payload.followup_at.replace(tzinfo=timezone.utc)
                    else:
                        followup_at = payload.followup_at.astimezone(timezone.utc)

                    if followup_at < datetime.now(timezone.utc):
                        raise HTTPException(status_code=400, detail="Followup must be in future")

                    if followup_at > datetime.now(timezone.utc) + timedelta(days=60):
                        raise HTTPException(status_code=400, detail="Followup cannot be scheduled beyond 60 days")
                else:
                    followup_at = row["followup_at"]

                updates: list[str] = []
                values: list = []
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
                        updates.append("missed_at = NULL")
                    elif payload.status == "PENDING":
                        updates.append("completed_at = NULL")
                        updates.append("missed_at = NULL")
                    elif payload.status == "MISSED":
                        updates.append("missed_at = COALESCE(missed_at, NOW())")

                if not updates:
                    raise HTTPException(status_code=400, detail="Nothing to update")

                updates.append("updated_at = NOW()")
                where_ent = idx
                where_id = idx + 1
                values.append(list(PAYMENT_FOLLOWUP_ENTITY_TYPES))
                values.append(payment_id)

                updated_rid = await conn.fetchval(
                    f"""
                    UPDATE {DB_SCHEMA}.payments rp
                       SET {", ".join(updates)}
                     WHERE rp.payment_status = 'PENDING'
                       AND rp.entity_type = ANY(${where_ent}::text[])
                       AND rp.id = ${where_id}
                    RETURNING rp.id
                    """,
                    *values,
                )

                if not updated_rid:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot update follow-up: payment not PENDING, not found, or wrong entity type.",
                    )

        log.info("Payment follow-up updated | payment_id=%s", payment_id)
        await _invalidate_payment_followup_cache()

        return UpdatePaymentFollowupResponse(id=payment_id, message="Follow-up updated successfully")

    except HTTPException:
        raise
    except asyncpg.PostgresError:
        log.exception("DB error")
        raise HTTPException(status_code=500, detail="Database error occurred")
    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
