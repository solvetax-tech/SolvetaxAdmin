"""
Dashboard: customer-wise monthly GST filing status matrix.

Per-return colours (all forms: GSTR-1, GSTR-3B, CMP-08, GSTR-4, GSTR-9, GSTR-9C):
- green: FILED
- red: MISSED / OVERDUE / past due and not filed
- yellow: not filed yet, today (IST) < due date
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.Dashboard.schemas import (
    GstFilingFollowupAlertItem,
    GstFilingFollowupAlertsResponse,
    GstFilingMatrixFormCell,
    GstFilingMatrixListResponse,
    GstFilingMatrixMonthCell,
    GstFilingMatrixRow,
)
from app.gst_registration_filing.gst_registration_filing import (
    _return_detail_effective_period_lateral,
)
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
)
from app.security.rbac import require_permission
from app.utils import (
    DB_SCHEMA,
    build_gst_filing_visibility,
    generate_uuid,
    get_db_pool,
)

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard"],
)

_IST = ZoneInfo("Asia/Kolkata")
_MONTH_ABBR = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
_TONE_PRIORITY = {"red": 3, "yellow": 2, "green": 1, "none": 0}
_WORD_MATCH_RATIO = 0.3
_CACHE_TAG = "dashboard:gst_filing_monthly_matrix:index"
_FOLLOWUP_COLUMN_PROBE = "gstr1_followup_at"
_RETURN_DETAIL_PAYMENT_TYPE = "GST_FILING_RETURN_DETAILS"


async def _per_form_followup_columns_exist(conn: asyncpg.Connection) -> bool:
    row = await conn.fetchval(
        f"""
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = $1
           AND table_name = 'gst_filing_return_details'
           AND column_name = $2
         LIMIT 1
        """,
        DB_SCHEMA,
        _FOLLOWUP_COLUMN_PROBE,
    )
    return row is not None


def _per_form_followup_select_sql(columns_exist: bool) -> str:
    if columns_exist:
        return """
                    d.gstr1_followup_at,
                    d.gstr3b_followup_at,
                    d.cmp08_followup_at,
                    d.gstr4_followup_at,
                    d.gstr9_followup_at,
                    d.gstr9c_followup_at"""
    return """
                    NULL::timestamptz AS gstr1_followup_at,
                    NULL::timestamptz AS gstr3b_followup_at,
                    NULL::timestamptz AS cmp08_followup_at,
                    NULL::timestamptz AS gstr4_followup_at,
                    NULL::timestamptz AS gstr9_followup_at,
                    NULL::timestamptz AS gstr9c_followup_at"""

# (API form key, status column, due date column, follow-up column)
RETURN_FORMS: tuple[tuple[str, str, str, str], ...] = (
    ("GSTR1", "gstr1_status", "gstr1_due_date", "gstr1_followup_at"),
    ("GSTR3B", "gstr3b_status", "gstr3b_due_date", "gstr3b_followup_at"),
    ("CMP08", "cmp08_status", "cmp08_due_date", "cmp08_followup_at"),
    ("GSTR4", "gstr4_status", "gstr4_due_date", "gstr4_followup_at"),
    ("GSTR9", "gstr9_status", "gstr9_due_date", "gstr9_followup_at"),
    ("GSTR9C", "gstr9c_status", "gstr9c_due_date", "gstr9c_followup_at"),
)
_PER_FORM_FOLLOWUP_COLUMNS = tuple(form[3] for form in RETURN_FORMS)

_FORM_LABELS = {
    "GSTR1": "GSTR-1",
    "GSTR3B": "GSTR-3B",
    "CMP08": "CMP-08",
    "GSTR4": "GSTR-4",
    "GSTR9": "GSTR-9",
    "GSTR9C": "GSTR-9C",
}

_STATUS_LABELS = {
    "DATA_PENDING": "Data Pending",
    "DATA_RECEIVED": "Data Received",
    "IN_PREPARATION": "In Preparation",
    "PENDING_OTP": "Pending OTP",
    "READY_TO_FILE": "Ready to File",
    "FILED": "Filed",
    "OVERDUE": "Overdue",
    "NOT_FILED": "Not Filed",
    "MISSED": "Missed",
}


def _empty_form_dict() -> Dict[str, Any]:
    return {
        "status": None,
        "due_date": None,
        "followup_at": None,
        "return_detail_id": None,
        "tone": "none",
    }


def _empty_period_bucket() -> Dict[str, Dict[str, Any]]:
    return {form_key: _empty_form_dict() for form_key, _, _, _ in RETURN_FORMS}


def _generate_month_columns(count: int = 6) -> List[str]:
    """Last ``count`` monthly periods ending at the previous calendar month (MON-YYYY)."""
    today = datetime.now(_IST).date()
    first_of_month = today.replace(day=1)
    anchor = first_of_month - timedelta(days=1)
    columns: List[str] = []
    year = anchor.year
    month = anchor.month
    for _ in range(count):
        columns.append(f"{_MONTH_ABBR[month - 1]}-{year}")
        month -= 1
        if month <= 0:
            month = 12
            year -= 1
    columns.reverse()
    return columns


def _to_ist_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(_IST).date()
    if isinstance(value, date):
        return value
    return None


def _format_due_date(value: Any) -> Optional[str]:
    d = _to_ist_date(value)
    if not d:
        return None
    return d.isoformat()


def _format_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(_IST).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=_IST).isoformat()
    return None


def _resolve_tone(status: Optional[str], due_date: Any, today: date) -> str:
    s = (status or "").strip().upper()
    if s == "FILED":
        return "green"
    if s in ("MISSED", "OVERDUE"):
        return "red"
    due = _to_ist_date(due_date)
    if due:
        if today < due:
            return "yellow"
        if s != "FILED":
            return "red"
    return "none"


def _worst_tone(*tones: str) -> str:
    best = "none"
    best_pri = -1
    for tone in tones:
        pri = _TONE_PRIORITY.get(tone, 0)
        if pri > best_pri:
            best_pri = pri
            best = tone
    return best


def _status_label(status: Optional[str]) -> Optional[str]:
    if not status:
        return None
    key = status.strip().upper()
    return _STATUS_LABELS.get(key, key.replace("_", " ").title())


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _mobile_text_sql(column: str = "mobile") -> str:
    return f"regexp_replace(COALESCE({column}::text, ''), '[^0-9]', '', 'g')"


def _display_name_sql() -> str:
    return (
        "COALESCE(NULLIF(trim(f.business_name::text), ''), "
        "NULLIF(trim(c.full_name::text), ''), '')"
    )


def _business_name_filter_clause(
    name_expr: str,
    business_q: str,
    start_idx: int,
) -> tuple[str, list[Any], int]:
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


def _monthly_period_filter_sql() -> str:
    return "ep.eff_period ~ '^[A-Z]{3}-[0-9]{4}$'"


def _parse_followup_dates(raw: Optional[str]) -> list[date]:
    if not raw or not str(raw).strip():
        return []
    seen: set[date] = set()
    ordered: list[date] = []
    for part in re.split(r"[,;\s]+", str(raw).strip()):
        token = part.strip()
        if not token:
            continue
        try:
            parsed = date.fromisoformat(token)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid followup_dates value '{token}'. Use YYYY-MM-DD.",
            ) from exc
        if parsed not in seen:
            seen.add(parsed)
            ordered.append(parsed)
    return ordered


def _followup_dates_customer_filter_clause(
    role: str,
    emp_id: Optional[int],
    dates_param_idx: int,
) -> tuple[str, list[Any], int]:
    followup_or = " OR ".join(
        (
            f"(d_fu.{col} IS NOT NULL "
            f"AND DATE(timezone('Asia/Kolkata', d_fu.{col})) = ANY(${dates_param_idx}::date[]))"
        )
        for col in _PER_FORM_FOLLOWUP_COLUMNS
    )
    vis_sql, vis_vals, next_idx = build_gst_filing_visibility(
        role, emp_id, dates_param_idx + 1, DB_SCHEMA
    )
    vis_clause = ""
    if vis_sql:
        vis_clause = f" AND {vis_sql.replace('f.', 'f_fu.')}"
    sql = f"""
        f.customer_id IN (
            SELECT f_fu.customer_id
              FROM {DB_SCHEMA}.gst_filings f_fu
             INNER JOIN {DB_SCHEMA}.gst_filing_return_details d_fu
                     ON d_fu.gst_filing_id = f_fu.id
             WHERE f_fu.is_active IS TRUE
               AND d_fu.is_active IS TRUE
               AND ({followup_or})
               {vis_clause}
        )
    """
    return sql, vis_vals, next_idx


def _build_base_from(role: str, emp_id: Optional[int], start_idx: int) -> tuple[str, list[Any], int]:
    conditions = [
        "f.is_active IS TRUE",
        "d.is_active IS TRUE",
        _monthly_period_filter_sql(),
        """(
            upper(trim(coalesce(f.filing_frequency, d.filing_frequency, ''))) = 'MONTHLY'
            OR d.gstr1_due_date IS NOT NULL
            OR d.gstr3b_due_date IS NOT NULL
        )""",
    ]
    values: list[Any] = []
    idx = start_idx
    vis_sql, vis_vals, idx = build_gst_filing_visibility(role, emp_id, idx, DB_SCHEMA)
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_vals)

    period_join = _return_detail_effective_period_lateral("d", "f")
    sql = f"""
        FROM {DB_SCHEMA}.gst_filings f
        INNER JOIN {DB_SCHEMA}.gst_filing_return_details d
                ON d.gst_filing_id = f.id
        LEFT JOIN {DB_SCHEMA}.customers c ON c.customer_id = f.customer_id
        LEFT JOIN {DB_SCHEMA}.employees rm ON rm.emp_id = f.rm_id
        LEFT JOIN {DB_SCHEMA}.employees op ON op.emp_id = f.op_id
        {period_join}
        WHERE {' AND '.join(conditions)}
    """
    return sql, values, idx


def _merge_form_cell(
    existing: Optional[Dict[str, Any]],
    status: Optional[str],
    due_date: Any,
    followup_at: Any,
    today: date,
    return_detail_id: Optional[int] = None,
) -> Dict[str, Any]:
    if due_date is None:
        return existing if existing else _empty_form_dict()
    tone = _resolve_tone(status, due_date, today)
    cell = {
        "status": (status or "").strip().upper() or None,
        "due_date": _format_due_date(due_date),
        "followup_at": _format_datetime(followup_at),
        "return_detail_id": return_detail_id,
        "tone": tone,
    }
    if not existing or not existing.get("due_date"):
        return cell
    if _TONE_PRIORITY.get(tone, 0) >= _TONE_PRIORITY.get(existing.get("tone", "none"), 0):
        return cell
    return existing


def _resolve_cell_return_detail_id(
    forms_raw: Dict[str, Dict[str, Any]],
    return_detail_id: Optional[int],
) -> Optional[int]:
    if return_detail_id is not None:
        return return_detail_id
    for form_key, _, _, _ in RETURN_FORMS:
        raw = forms_raw.get(form_key, _empty_form_dict())
        if raw.get("due_date") and raw.get("return_detail_id") is not None:
            return int(raw["return_detail_id"])
    return None


async def _fetch_return_detail_payment_map(
    conn: asyncpg.Connection,
    return_detail_ids: list[int],
) -> dict[int, str]:
    if not return_detail_ids:
        return {}
    rows = await conn.fetch(
        f"""
        SELECT entity_id::int AS entity_id,
               CASE
                   WHEN BOOL_OR(upper(payment_status) = 'PAID') THEN 'PAID'
                   ELSE 'PENDING'
               END AS payment_status
          FROM {DB_SCHEMA}.payments
         WHERE entity_type = $1
           AND entity_id = ANY($2::int[])
           AND is_active IS TRUE
           AND upper(payment_status) != 'CANCELLED'
         GROUP BY entity_id
        """,
        _RETURN_DETAIL_PAYMENT_TYPE,
        return_detail_ids,
    )
    return {int(row["entity_id"]): str(row["payment_status"]) for row in rows}


def _build_month_cell(
    forms_raw: Dict[str, Dict[str, Any]],
    filing_id: Optional[int],
    return_detail_id: Optional[int] = None,
    payment_status: Optional[str] = None,
) -> GstFilingMatrixMonthCell:
    form_cells: Dict[str, GstFilingMatrixFormCell] = {}
    tones: list[str] = []
    primary = _empty_form_dict()
    best_pri = -1
    for form_key, _, _, _ in RETURN_FORMS:
        raw = forms_raw.get(form_key, _empty_form_dict())
        if not raw.get("due_date"):
            continue
        form_cells[form_key] = GstFilingMatrixFormCell(**raw)
        tones.append(raw.get("tone", "none"))
        pri = _TONE_PRIORITY.get(raw.get("tone", "none"), 0)
        if pri > best_pri:
            best_pri = pri
            primary = raw

    tone = _worst_tone(*tones) if tones else "none"

    status = primary.get("status")
    resolved_return_detail_id = _resolve_cell_return_detail_id(forms_raw, return_detail_id)
    return GstFilingMatrixMonthCell(
        tone=tone,
        status=status,
        due_date=primary.get("due_date"),
        status_label=_status_label(status),
        filing_id=filing_id,
        return_detail_id=resolved_return_detail_id,
        payment_completed=payment_status == "PAID",
        payment_status=payment_status,
        forms=form_cells,
    )


@router.get(
    "/gst-filing-monthly-matrix",
    response_model=GstFilingMatrixListResponse,
    summary="Customer-wise monthly GST filing status matrix (dashboard)",
)
async def list_gst_filing_monthly_matrix(
    phone: Optional[str] = Query(
        None,
        description="Filter by mobile (substring match on digits).",
    ),
    business_name: Optional[str] = Query(
        None,
        description="Filter by business/display name (contains; multi-word uses >=30% word match).",
    ),
    customer_id: Optional[int] = Query(
        None,
        description="Filter to a single customer row (used when opening from follow-up notification).",
    ),
    followup_dates: Optional[str] = Query(
        None,
        description="Filter customers with per-form follow-ups on these IST calendar days (YYYY-MM-DD, comma-separated).",
    ),
    months: int = Query(6, ge=3, le=24, description="Number of monthly columns to show."),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = str(current_user.get("role") or "").strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "list_gst_filing_monthly_matrix",
        },
    )

    phone_norm = phone.strip() if isinstance(phone, str) and phone.strip() else None
    business_norm = (
        business_name.strip() if isinstance(business_name, str) and business_name.strip() else None
    )
    followup_dates_list = _parse_followup_dates(followup_dates)
    followup_dates_key = (
        ",".join(d.isoformat() for d in followup_dates_list) if followup_dates_list else None
    )
    month_columns = _generate_month_columns(months)
    today_ist = datetime.now(_IST).date()

    cache_key = build_cache_key(
        "dashboard:gst_filing_monthly_matrix:v12",
        phone=phone_norm,
        business_name=business_norm,
        customer_id=customer_id,
        followup_dates=followup_dates_key,
        months=months,
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
        async with pool.acquire() as probe_conn:
            followup_columns_exist = await _per_form_followup_columns_exist(probe_conn)
        followup_select = _per_form_followup_select_sql(followup_columns_exist)

        base_from, values, idx = _build_base_from(role, emp_id, 1)
        filter_clauses: list[str] = []
        if phone_norm:
            digits = _digits_only(phone_norm)
            if len(digits) < 4:
                raise HTTPException(
                    status_code=400,
                    detail="phone must contain at least 4 digits.",
                )
            filter_clauses.append(f"{_mobile_text_sql('c.mobile')} LIKE ${idx}")
            values.append(f"%{digits}%")
            idx += 1
        if business_norm:
            clause, clause_vals, idx = _business_name_filter_clause(
                _display_name_sql(), business_norm, idx
            )
            filter_clauses.append(clause)
            values.extend(clause_vals)
        if customer_id is not None:
            filter_clauses.append(f"f.customer_id = ${idx}")
            values.append(int(customer_id))
            idx += 1
        if followup_dates_list:
            if not followup_columns_exist:
                raise HTTPException(
                    status_code=400,
                    detail="Follow-up date filter is not available until per-form follow-up columns are migrated.",
                )
            clause, vis_vals, idx = _followup_dates_customer_filter_clause(
                role, emp_id, idx
            )
            filter_clauses.append(clause)
            values.append(followup_dates_list)
            values.extend(vis_vals)

        month_idx = idx
        values.append(month_columns)
        idx += 1

        extra_where = ""
        if filter_clauses:
            extra_where = " AND " + " AND ".join(filter_clauses)

        customers_cte = f"""
            WITH filing_rows AS (
                SELECT
                    f.customer_id,
                    f.id AS filing_id,
                    f.gstin,
                    {_display_name_sql()} AS display_name,
                    f.business_name::text AS business_name,
                    c.mobile::text AS mobile,
                    rm.username AS rm_username,
                    op.username AS op_username,
                    upper(trim(ep.eff_period)) AS eff_period,
                    d.id AS return_detail_id,
                    d.gstr1_status,
                    d.gstr1_due_date,
                    d.gstr3b_status,
                    d.gstr3b_due_date,
                    d.cmp08_status,
                    d.cmp08_due_date,
                    d.gstr4_status,
                    d.gstr4_due_date,
                    d.gstr9_status,
                    d.gstr9_due_date,
                    d.gstr9c_status,
                    d.gstr9c_due_date,{followup_select}
                {base_from}
                  AND upper(trim(ep.eff_period)) = ANY(${month_idx})
                  {extra_where}
            ),
            customers AS (
                SELECT
                    customer_id,
                    MAX(display_name) AS display_name,
                    MAX(business_name) AS business_name,
                    MAX(mobile) AS mobile,
                    MAX(gstin) AS gstin,
                    MAX(rm_username) AS rm_username,
                    MAX(op_username) AS op_username
                FROM filing_rows
                WHERE customer_id IS NOT NULL
                GROUP BY customer_id
            )
        """

        lim_idx = len(values) + 1
        off_idx = len(values) + 2
        list_values = [*values, limit, offset]

        count_sql = f"{customers_cte} SELECT COUNT(*)::bigint FROM customers"
        list_sql = f"""
            {customers_cte}
            SELECT *
              FROM customers
             ORDER BY display_name NULLS LAST, customer_id
             LIMIT ${lim_idx} OFFSET ${off_idx}
        """
        cells_sql = f"""
            {customers_cte},
            page_customers AS (
                SELECT customer_id FROM customers
                 ORDER BY display_name NULLS LAST, customer_id
                 LIMIT ${lim_idx} OFFSET ${off_idx}
            )
            SELECT fr.*
              FROM filing_rows fr
             INNER JOIN page_customers pc ON pc.customer_id = fr.customer_id
        """

        async with pool.acquire() as conn:
            total = int(await conn.fetchval(count_sql, *values) or 0)
            customer_rows = await conn.fetch(list_sql, *list_values)
            if not customer_rows:
                return GstFilingMatrixListResponse(
                    months=month_columns,
                    data=[],
                    total=total,
                    limit=limit,
                    offset=offset,
                    request_id=request_id,
                ).model_dump()

            cell_rows = await conn.fetch(cells_sql, *list_values)

            cells_by_customer: Dict[int, Dict[str, Dict[str, Any]]] = {}
            cell_meta_by_customer_period: Dict[tuple[int, str], Dict[str, int]] = {}

            for row in cell_rows:
                cid = int(row["customer_id"])
                period = str(row["eff_period"] or "").upper()
                if period not in month_columns:
                    continue
                bucket = cells_by_customer.setdefault(cid, {})
                period_bucket = bucket.setdefault(period, _empty_period_bucket())
                row_detail_id = int(row["return_detail_id"])
                for form_key, status_col, due_col, followup_col in RETURN_FORMS:
                    period_bucket[form_key] = _merge_form_cell(
                        period_bucket[form_key],
                        row[status_col],
                        row[due_col],
                        row[followup_col],
                        today_ist,
                        row_detail_id,
                    )
                key = (cid, period)
                has_regular_pair = (
                    row["gstr1_due_date"] is not None and row["gstr3b_due_date"] is not None
                )
                if key not in cell_meta_by_customer_period:
                    cell_meta_by_customer_period[key] = {
                        "filing_id": int(row["filing_id"]),
                        "return_detail_id": int(row["return_detail_id"]),
                        "has_regular_pair": has_regular_pair,
                    }
                elif has_regular_pair and not cell_meta_by_customer_period[key].get(
                    "has_regular_pair"
                ):
                    cell_meta_by_customer_period[key] = {
                        "filing_id": int(row["filing_id"]),
                        "return_detail_id": int(row["return_detail_id"]),
                        "has_regular_pair": True,
                    }

            detail_ids = sorted({
                int(meta["return_detail_id"])
                for meta in cell_meta_by_customer_period.values()
                if meta.get("return_detail_id") is not None
            })
            payment_map = await _fetch_return_detail_payment_map(conn, detail_ids)

            data: List[GstFilingMatrixRow] = []
            for crow in customer_rows:
                cid = int(crow["customer_id"])
                month_map: Dict[str, GstFilingMatrixMonthCell] = {}
                customer_cells = cells_by_customer.get(cid, {})
                for period in month_columns:
                    raw = customer_cells.get(period)
                    if raw:
                        meta = cell_meta_by_customer_period.get((cid, period), {})
                        resolved_id = _resolve_cell_return_detail_id(
                            raw, meta.get("return_detail_id")
                        )
                        payment_status = (
                            payment_map.get(resolved_id) if resolved_id is not None else None
                        )
                        month_map[period] = _build_month_cell(
                            raw,
                            meta.get("filing_id"),
                            meta.get("return_detail_id"),
                            payment_status,
                        )
                    else:
                        month_map[period] = GstFilingMatrixMonthCell(tone="none")

                data.append(
                    GstFilingMatrixRow(
                        customer_id=cid,
                        display_name=crow["display_name"],
                        business_name=crow["business_name"],
                        mobile=crow["mobile"],
                        gstin=crow["gstin"],
                        rm_username=crow["rm_username"],
                        op_username=crow["op_username"],
                        months=month_map,
                    )
                )

        return GstFilingMatrixListResponse(
            months=month_columns,
            data=data,
            total=total,
            limit=limit,
            offset=offset,
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
    except asyncpg.PostgresError as exc:
        log.exception("Database error: %s", exc)
        raise HTTPException(status_code=500, detail="Database error.")
    except Exception:
        log.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error.")


@router.get(
    "/gst-filing-followup-alerts",
    response_model=GstFilingFollowupAlertsResponse,
    summary="Upcoming GST return-detail follow-ups (GST Filings dashboard only)",
)
async def list_gst_filing_followup_alerts(
    followup_from: Optional[datetime] = Query(
        None,
        description="Inclusive lower bound on follow-up datetime (ISO).",
    ),
    followup_to: Optional[datetime] = Query(
        None,
        description="Inclusive upper bound on follow-up datetime (ISO).",
    ),
    limit: int = Query(100, ge=1, le=500),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = str(current_user.get("role") or "").strip().upper()

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "list_gst_filing_followup_alerts",
        },
    )

    now_ist = datetime.now(_IST)
    range_start = followup_from if followup_from is not None else now_ist - timedelta(hours=6)
    range_end = followup_to if followup_to is not None else now_ist + timedelta(hours=48)

    if range_start > range_end:
        raise HTTPException(
            status_code=400,
            detail="followup_from must be <= followup_to.",
        )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        if not await _per_form_followup_columns_exist(conn):
            return GstFilingFollowupAlertsResponse(
                data=[],
                total=0,
                request_id=request_id,
            )

        base_from, values, idx = _build_base_from(role, emp_id, 1)
        union_parts: list[str] = []
        for form_key, _, due_col, followup_col in RETURN_FORMS:
            union_parts.append(
                f"""
                SELECT
                    d.id AS return_detail_id,
                    f.id AS filing_id,
                    f.customer_id,
                    f.gstin::text AS gstin,
                    f.rm_id,
                    f.op_id,
                    {_display_name_sql()} AS display_name,
                    f.business_name::text AS business_name,
                    c.mobile::text AS mobile,
                    '{form_key}' AS form_key,
                    d.{followup_col} AS followup_at,
                    upper(trim(ep.eff_period)) AS eff_period
                {base_from}
                  AND d.{due_col} IS NOT NULL
                  AND d.{followup_col} IS NOT NULL
                  AND d.{followup_col} >= ${idx}
                  AND d.{followup_col} <= ${idx + 1}
                """
            )

        sql = f"""
            SELECT *
              FROM (
                {' UNION ALL '.join(union_parts)}
              ) alerts
             ORDER BY followup_at ASC
             LIMIT ${idx + 2}
        """
        query_values = [*values, range_start, range_end, limit]

        try:
            rows = await conn.fetch(sql, *query_values)
        except asyncpg.PostgresError as exc:
            log.exception("Database error: %s", exc)
            raise HTTPException(status_code=500, detail="Database error.")

    data = [
        GstFilingFollowupAlertItem(
            return_detail_id=int(row["return_detail_id"]),
            filing_id=int(row["filing_id"]),
            customer_id=int(row["customer_id"]) if row["customer_id"] is not None else None,
            form_key=str(row["form_key"]),
            form_label=_FORM_LABELS.get(str(row["form_key"]), str(row["form_key"])),
            period=str(row["eff_period"]) if row.get("eff_period") else None,
            followup_at=_format_datetime(row["followup_at"]) or "",
            display_name=row["display_name"],
            business_name=row["business_name"],
            gstin=row["gstin"],
            mobile=row["mobile"],
            rm_id=int(row["rm_id"]) if row["rm_id"] is not None else None,
            op_id=int(row["op_id"]) if row["op_id"] is not None else None,
        )
        for row in rows
        if row["followup_at"] is not None
    ]

    return GstFilingFollowupAlertsResponse(
        data=data,
        total=len(data),
        request_id=request_id,
    )
