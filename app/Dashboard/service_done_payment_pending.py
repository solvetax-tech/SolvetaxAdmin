"""
Dashboard: services marked done but with no payment ledger row yet.

Per-entity completion rules:
- CUSTOMER_SERVICE: service_status = PROVIDED
- GST_REGISTRATION: registration_status = APPROVED
- INCOME_TAX: filed_status = FILED
- GST_FILING: status = FILED

No matching ``payments`` row for the same ``entity_id`` + ``entity_type``
(non-cancelled, active payments only).
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.Dashboard.schemas import (
    ServiceDonePaymentPendingItem,
    ServiceDonePaymentPendingListResponse,
    ServiceDonePaymentPendingSummary,
)
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.security.rbac import require_permission
from app.payments.payments_config import resolve_entity_remaining_amount
from app.utils import (
    DB_SCHEMA,
    build_customer_service_visibility,
    build_gst_filing_visibility,
    build_gst_visibility,
    build_income_tax_visibility,
    generate_uuid,
    get_db_pool,
)

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard"],
)

_ALLOWED_ENTITY_TYPES = frozenset(
    {"GST_REGISTRATION", "GST_FILING", "INCOME_TAX", "CUSTOMER_SERVICE"}
)

_CACHE_TAG = "dashboard:service_done_payment_pending:index"

_WORD_MATCH_RATIO = 0.3


async def invalidate_service_done_payment_pending_cache() -> None:
    """Call when payments are created/updated or entity done-status changes."""
    await redis_invalidate_tag(_CACHE_TAG)


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _mobile_text_sql(column: str = "mobile") -> str:
    return f"regexp_replace(COALESCE({column}::text, ''), '[^0-9]', '', 'g')"


def _display_name_sql() -> str:
    return (
        "COALESCE(NULLIF(trim(business_name::text), ''), "
        "NULLIF(trim(display_name::text), ''), '')"
    )


def _business_name_filter_clause(
    name_expr: str,
    business_q: str,
    start_idx: int,
) -> tuple[str, list[Any], int]:
    """
    Substring match on full phrase; multi-word queries require >=30% of words
    to appear (ILIKE per word). No pg_trgm extension required.
    """
    raw = business_q.strip()
    if len(raw) < 2:
        raise HTTPException(
            status_code=400,
            detail="business_name must be at least 2 characters.",
        )

    words = [w for w in re.split(r"\s+", raw) if len(w) >= 2]
    if len(words) <= 1:
        return f"{name_expr} ILIKE ${start_idx}", [f"%{raw}%"], start_idx + 1

    min_match = max(1, math.ceil(len(words) * _WORD_MATCH_RATIO))
    parts: list[str] = []
    values: list[Any] = []
    idx = start_idx
    for word in words:
        parts.append(f"CASE WHEN {name_expr} ILIKE ${idx} THEN 1 ELSE 0 END")
        values.append(f"%{word}%")
        idx += 1

    clause = f"(({' + '.join(parts)}) >= {min_match})"
    return clause, values, idx


def _status_equals_sql(column: str, value: str) -> str:
    return f"upper(trim(coalesce({column}, ''))) = '{value}'"


def _no_payment_sql(entity_id_expr: str, entity_type_literal: str) -> str:
    return f"""
        NOT EXISTS (
            SELECT 1
              FROM {DB_SCHEMA}.payments p
             WHERE p.entity_id = {entity_id_expr}
               AND upper(trim(p.entity_type)) = '{entity_type_literal}'
               AND p.is_active IS TRUE
               AND upper(trim(coalesce(p.payment_status, ''))) <> 'CANCELLED'
        )
    """


def _serialize_row(row: asyncpg.Record) -> dict[str, Any]:
    out = dict(row)
    created = out.get("entity_created_at")
    if isinstance(created, datetime):
        out["entity_created_at"] = created.isoformat()
    fy = out.get("financial_year")
    if fy is not None and not isinstance(fy, list):
        out["financial_year"] = list(fy)
    return out


def _branch_gst_registration(role: str, emp_id: Optional[int], start_idx: int) -> tuple[str, list[Any], int]:
    conditions = [
        "g.is_active IS TRUE",
        _status_equals_sql("g.registration_status", "APPROVED"),
        _no_payment_sql("g.id", "GST_REGISTRATION"),
    ]
    values: list[Any] = []
    idx = start_idx
    vis_sql, vis_vals, idx = build_gst_visibility(role, emp_id, idx, DB_SCHEMA)
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_vals)

    sql = f"""
        SELECT
            'GST_REGISTRATION'::text AS entity_type,
            g.id AS entity_id,
            g.customer_id,
            upper(trim(g.registration_status)) AS service_status,
            COALESCE(NULLIF(trim(g.business_name), ''), NULLIF(trim(c.full_name), ''), g.client_name) AS display_name,
            g.business_name::text AS business_name,
            COALESCE(g.mobile::text, c.mobile::text) AS mobile,
            g.rm_id,
            g.created_by AS op_id,
            rm.username AS rm_username,
            op.username AS op_username,
            g.created_at AS entity_created_at,
            NULL::text AS service_code,
            NULL::text AS service_name,
            g.gstin,
            NULL::text AS pan_number,
            NULL::varchar[] AS financial_year
        FROM {DB_SCHEMA}.gst_registration g
        LEFT JOIN {DB_SCHEMA}.customers c ON c.customer_id = g.customer_id
        LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = g.rm_id
        LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = g.created_by
        WHERE {' AND '.join(conditions)}
    """
    return sql, values, idx


def _branch_gst_filing(role: str, emp_id: Optional[int], start_idx: int) -> tuple[str, list[Any], int]:
    conditions = [
        "f.is_active IS TRUE",
        _status_equals_sql("f.status", "FILED"),
        _no_payment_sql("f.id", "GST_FILING"),
    ]
    values: list[Any] = []
    idx = start_idx
    vis_sql, vis_vals, idx = build_gst_filing_visibility(role, emp_id, idx, DB_SCHEMA)
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_vals)

    sql = f"""
        SELECT
            'GST_FILING'::text AS entity_type,
            f.id AS entity_id,
            f.customer_id,
            upper(trim(f.status)) AS service_status,
            COALESCE(NULLIF(trim(f.business_name), ''), NULLIF(trim(c.full_name), '')) AS display_name,
            f.business_name::text AS business_name,
            c.mobile::text AS mobile,
            f.rm_id,
            f.op_id,
            rm.username AS rm_username,
            op.username AS op_username,
            f.created_at AS entity_created_at,
            NULL::text AS service_code,
            NULL::text AS service_name,
            f.gstin,
            NULL::text AS pan_number,
            NULL::varchar[] AS financial_year
        FROM {DB_SCHEMA}.gst_filings f
        LEFT JOIN {DB_SCHEMA}.customers c ON c.customer_id = f.customer_id
        LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = f.rm_id
        LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = f.op_id
        WHERE {' AND '.join(conditions)}
    """
    return sql, values, idx


def _branch_income_tax(role: str, emp_id: Optional[int], start_idx: int) -> tuple[str, list[Any], int]:
    conditions = [
        "i.is_active IS TRUE",
        _status_equals_sql("i.filed_status", "FILED"),
        _no_payment_sql("i.id", "INCOME_TAX"),
    ]
    values: list[Any] = []
    idx = start_idx
    vis_sql, vis_vals, idx = build_income_tax_visibility(role, emp_id, idx, DB_SCHEMA, alias="i")
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_vals)

    sql = f"""
        SELECT
            'INCOME_TAX'::text AS entity_type,
            i.id AS entity_id,
            NULL::int AS customer_id,
            upper(trim(i.filed_status)) AS service_status,
            NULLIF(trim(i.client_name), '') AS display_name,
            NULL::text AS business_name,
            i.mobile::text AS mobile,
            i.rm_id,
            i.op_id,
            rm.username AS rm_username,
            op.username AS op_username,
            i.created_at AS entity_created_at,
            NULL::text AS service_code,
            NULL::text AS service_name,
            NULL::text AS gstin,
            i.pan_number,
            i.financial_year
        FROM {DB_SCHEMA}.income_tax i
        LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = i.rm_id
        LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = i.op_id
        WHERE {' AND '.join(conditions)}
    """
    return sql, values, idx


def _branch_customer_service(role: str, emp_id: Optional[int], start_idx: int) -> tuple[str, list[Any], int]:
    conditions = [
        "cs.is_active IS TRUE",
        _status_equals_sql("cs.service_status", "PROVIDED"),
        _no_payment_sql("cs.id", "CUSTOMER_SERVICE"),
    ]
    values: list[Any] = []
    idx = start_idx
    vis_sql, vis_vals, idx = build_customer_service_visibility(role, emp_id, idx, DB_SCHEMA)
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_vals)

    sql = f"""
        SELECT
            'CUSTOMER_SERVICE'::text AS entity_type,
            cs.id AS entity_id,
            cs.customer_id,
            upper(trim(cs.service_status)) AS service_status,
            COALESCE(NULLIF(trim(sc.service_name), ''), upper(trim(cs.service_code))) AS display_name,
            c.business_name::text AS business_name,
            c.mobile::text AS mobile,
            cs.rm_id,
            cs.op_id,
            rm.username AS rm_username,
            op.username AS op_username,
            cs.created_at AS entity_created_at,
            upper(trim(cs.service_code)) AS service_code,
            sc.service_name,
            NULL::text AS gstin,
            NULL::text AS pan_number,
            NULL::varchar[] AS financial_year
        FROM {DB_SCHEMA}.customer_services cs
        JOIN {DB_SCHEMA}.customers c ON c.customer_id = cs.customer_id
        LEFT JOIN {DB_SCHEMA}.service_config sc
            ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
        LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = cs.rm_id
        LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = cs.op_id
        WHERE {' AND '.join(conditions)}
    """
    return sql, values, idx


def _build_union_query(
    *,
    entity_type_filter: Optional[str],
    role: str,
    emp_id: Optional[int],
) -> tuple[str, list[Any]]:
    branch_builders = {
        "GST_REGISTRATION": _branch_gst_registration,
        "GST_FILING": _branch_gst_filing,
        "INCOME_TAX": _branch_income_tax,
        "CUSTOMER_SERVICE": _branch_customer_service,
    }

    types_to_load = (
        [entity_type_filter]
        if entity_type_filter
        else list(branch_builders.keys())
    )

    parts: list[str] = []
    values: list[Any] = []
    idx = 1

    for et in types_to_load:
        builder = branch_builders[et]
        sql, branch_values, idx = builder(role, emp_id, idx)
        parts.append(sql.strip())
        values.extend(branch_values)

    if not parts:
        raise HTTPException(status_code=400, detail="Invalid entity_type filter.")

    union_sql = "\n        UNION ALL\n        ".join(parts)
    cte = f"""
        WITH candidates AS (
            {union_sql}
        )
    """
    return cte, values


def _candidate_search_filters(
    phone: Optional[str],
    business_name: Optional[str],
    start_idx: int,
) -> tuple[str, list[Any], int]:
    """Phone: digit-normalized substring. Business name: ILIKE with optional multi-word 30% match."""
    clauses: list[str] = []
    values: list[Any] = []
    idx = start_idx

    phone_q = phone.strip() if isinstance(phone, str) and phone.strip() else None
    if phone_q:
        phone_digits = _digits_only(phone_q)
        if not phone_digits:
            raise HTTPException(status_code=400, detail="phone must contain at least one digit.")
        mobile_digits = _mobile_text_sql("mobile")
        clauses.append(f"{mobile_digits} LIKE ${idx}")
        values.append(f"%{phone_digits}%")
        idx += 1

    business_q = (
        business_name.strip() if isinstance(business_name, str) and business_name.strip() else None
    )
    if business_q:
        name_expr = _display_name_sql()
        biz_clause, biz_vals, idx = _business_name_filter_clause(name_expr, business_q, idx)
        clauses.append(biz_clause)
        values.extend(biz_vals)

    if not clauses:
        return "", values, idx
    return " AND ".join(clauses), values, idx


def _wrap_filtered_cte(
    candidates_cte: str,
    phone: Optional[str],
    business_name: Optional[str],
    values: list[Any],
) -> tuple[str, list[Any]]:
    filter_sql, filter_vals, _ = _candidate_search_filters(
        phone, business_name, len(values) + 1
    )
    merged_values = [*values, *filter_vals]
    if filter_sql:
        return (
            f"""
        {candidates_cte},
        filtered AS (
            SELECT * FROM candidates
            WHERE {filter_sql}
        )
        """,
            merged_values,
        )
    return (
        f"""
        {candidates_cte},
        filtered AS (
            SELECT * FROM candidates
        )
        """,
        merged_values,
    )


def _summary_from_counts(rows: list[asyncpg.Record], total: int) -> ServiceDonePaymentPendingSummary:
    counts = {str(r["entity_type"]): int(r["count"]) for r in rows}
    return ServiceDonePaymentPendingSummary(
        total=total,
        gst_registration=counts.get("GST_REGISTRATION", 0),
        gst_filing=counts.get("GST_FILING", 0),
        income_tax=counts.get("INCOME_TAX", 0),
        customer_service=counts.get("CUSTOMER_SERVICE", 0),
    )


@router.get(
    "/service-done-payment-pending",
    response_model=ServiceDonePaymentPendingListResponse,
    summary="List services done with no payment row (dashboard)",
)
async def list_service_done_payment_pending(
    entity_type: Optional[str] = Query(
        None,
        description="Optional filter: GST_REGISTRATION | GST_FILING | INCOME_TAX | CUSTOMER_SERVICE",
    ),
    phone: Optional[str] = Query(
        None,
        description="Filter by mobile (substring or >=30% trigram similarity).",
    ),
    business_name: Optional[str] = Query(
        None,
        description="Filter by business/display name (contains; multi-word uses >=30% word match).",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = str(current_user.get("role") or "").strip().upper()

    entity_type_norm: Optional[str] = None
    if isinstance(entity_type, str) and entity_type.strip():
        entity_type_norm = entity_type.strip().upper()
        if entity_type_norm not in _ALLOWED_ENTITY_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "entity_type must be one of: "
                    "GST_REGISTRATION, GST_FILING, INCOME_TAX, CUSTOMER_SERVICE"
                ),
            )

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "list_service_done_payment_pending",
        },
    )

    phone_norm = phone.strip() if isinstance(phone, str) and phone.strip() else None
    business_norm = (
        business_name.strip() if isinstance(business_name, str) and business_name.strip() else None
    )

    cache_key = build_cache_key(
        "dashboard:service_done_payment_pending:v6",
        entity_type=entity_type_norm,
        phone=phone_norm,
        business_name=business_norm,
        limit=limit,
        offset=offset,
        role=role or None,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load() -> dict[str, Any]:
        candidates_cte, values = _build_union_query(
            entity_type_filter=entity_type_norm,
            role=role,
            emp_id=emp_id,
        )
        cte, values = _wrap_filtered_cte(
            candidates_cte, phone_norm, business_norm, values
        )

        lim_idx = len(values) + 1
        off_idx = len(values) + 2
        list_values = [*values, limit, offset]

        count_sql = f"{cte} SELECT COUNT(*)::bigint AS total FROM filtered"
        summary_sql = f"""
            {cte}
            SELECT entity_type, COUNT(*)::bigint AS count
              FROM filtered
             GROUP BY entity_type
        """
        list_sql = f"""
            {cte}
            SELECT *
              FROM filtered
             ORDER BY entity_created_at DESC NULLS LAST, entity_type, entity_id DESC
             LIMIT ${lim_idx} OFFSET ${off_idx}
        """

        async with pool.acquire() as conn:
            total = int(await conn.fetchval(count_sql, *values) or 0)
            summary_rows = await conn.fetch(summary_sql, *values)
            rows = await conn.fetch(list_sql, *list_values)

            data: list[ServiceDonePaymentPendingItem] = []
            for r in rows:
                item_dict = _serialize_row(r)
                item_dict["pending_amount"] = await resolve_entity_remaining_amount(
                    conn,
                    entity_id=int(item_dict["entity_id"]),
                    entity_type=str(item_dict["entity_type"]),
                    customer_id=item_dict.get("customer_id"),
                )
                data.append(ServiceDonePaymentPendingItem(**item_dict))

        summary = _summary_from_counts(summary_rows, total)

        return ServiceDonePaymentPendingListResponse(
            data=data,
            total=total,
            limit=limit,
            offset=offset,
            summary=summary,
            request_id=request_id,
        ).model_dump()

    try:
        payload = await redis_get_or_set_json(
            cache_key,
            loader=_load,
            ttl_seconds=120,
            tags=[_CACHE_TAG],
        )
        return payload
    except HTTPException:
        raise
    except asyncpg.UndefinedColumnError as exc:
        log.exception("Status column missing on an entity table: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Database schema is missing a required status column for this report.",
        )
    except asyncpg.PostgresError as exc:
        log.exception("Database error: %s", exc)
        raise HTTPException(status_code=500, detail="Database error.")
    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error.")
