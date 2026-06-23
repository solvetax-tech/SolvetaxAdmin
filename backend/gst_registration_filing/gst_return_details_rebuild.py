"""
Shared GST filing return-detail seeding (create + PATCH rebuild).

Keeps parity with create_gst_filing: ANNUAL/YEARLY, RETURN+REGULAR (periodic + optional
YEARLY companion), RETURN+COMPOSITION (CMP-08 + optional GSTR-4), explicit_filing_period.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Optional, Set
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException

from backend.utils import DB_SCHEMA

_LEAD_DAYS_MONTHLY = 10
_LEAD_DAYS_QUARTERLY = 12
_LEAD_DAYS_YEARLY_ANNUAL = 7

_ERR_REGULAR_FREQUENCY = (
    "Regular taxpayers need MONTHLY or QUARTERLY filing frequency for return schedules."
)
_ERR_TAXPAYER_RECALC = (
    "Taxpayer type must be REGULAR or COMPOSITION when return schedules are rebuilt."
)
_ERR_FILING_PERIOD = (
    "Filing period is not valid. Use formats like APR-2024, Q1-2024, or 2024-25."
)


def _lead_days_for_periodic_frequency(filing_frequency: str) -> int:
    if filing_frequency == "MONTHLY":
        return _LEAD_DAYS_MONTHLY
    if filing_frequency == "QUARTERLY":
        return _LEAD_DAYS_QUARTERLY
    return _LEAD_DAYS_YEARLY_ANNUAL


def _compute_next_auto_generate_at(*due_dates, lead_days: int = _LEAD_DAYS_YEARLY_ANNUAL):
    valid = [d for d in due_dates if d is not None]
    if not valid:
        return None
    return min(valid) - timedelta(days=lead_days)


def parse_filing_period_to_base_date(filing_period: str) -> datetime:
    fp = (filing_period or "").strip()
    if not fp:
        raise HTTPException(400, _ERR_FILING_PERIOD)
    try:
        return datetime.strptime(fp, "%b-%Y")
    except ValueError:
        pass
    if fp.upper().startswith("Q"):
        q = int(fp[1])
        year = int(fp.split("-")[1])
        return datetime(year, (q - 1) * 3 + 1, 1)
    if "-" in fp:
        year = int(fp[:4])
        return datetime(year, 4, 1)
    raise HTTPException(400, _ERR_FILING_PERIOD)


async def count_active_return_details(conn, filing_id: int) -> int:
    return int(
        await conn.fetchval(
            f"""
            SELECT COUNT(*)::int
            FROM {DB_SCHEMA}.gst_filing_return_details
            WHERE gst_filing_id = $1 AND is_active = TRUE
            """,
            filing_id,
        )
        or 0
    )


def infer_explicit_template_from_prior_row_count(
    prior_active_row_count: int,
    filing_category: str,
    taxpayer_type: str,
    filing_frequency: str,
) -> bool:
    """
    If the filing previously had a single active return-detail row, treat like create-time
    explicit filing_period (no companion YEARLY / GSTR-4 row unless frequency matches).
    """
    if prior_active_row_count != 1:
        return False
    cat = (filing_category or "").strip().upper()
    tt = (taxpayer_type or "").strip().upper()
    fq = (filing_frequency or "").strip().upper()
    if cat == "RETURN" and tt == "REGULAR" and fq in ("MONTHLY", "QUARTERLY"):
        return True
    if cat == "RETURN" and tt == "COMPOSITION" and fq in ("QUARTERLY", "YEARLY"):
        return True
    if cat == "ANNUAL" and fq == "YEARLY":
        return True
    return False


async def rebuild_return_details_for_filing(
    conn,
    *,
    filing_id: int,
    filing_category: str,
    filing_frequency: str,
    taxpayer_type: str,
    turnover_details: Optional[str],
    state: Optional[str],
    filing_period: str,
    group_2_states: Set[str],
    ist: ZoneInfo,
    now: datetime,
    explicit_filing_period: bool,
    is_auto_enabled: bool = True,
    supersede_with_is_current: bool = False,
) -> None:
    """
    Supersede prior return-detail rows for this filing, then insert new seeds.

    - Legacy mode: old active rows are marked ``is_active = FALSE``.
    - Current-chain mode: old rows stay active, but become ``is_current = FALSE``.
    - Scheduler auto-gen demotes prior rows in the same ``filing_frequency`` band only
      (MONTHLY/QUARTERLY vs YEARLY) before inserting the new current row.
    """
    if supersede_with_is_current:
        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.gst_filing_return_details
            SET is_current = FALSE,
                next_auto_generate_at = NULL,
                updated_at = NOW()
            WHERE gst_filing_id = $1
              AND is_active = TRUE
              AND is_current = TRUE
            """,
            filing_id,
        )
    else:
        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.gst_filing_return_details
            SET is_active = FALSE,
                next_auto_generate_at = NULL,
                updated_at = NOW()
            WHERE gst_filing_id = $1
              AND is_active = TRUE
            """,
            filing_id,
        )

    filing_category = (filing_category or "").strip().upper()
    filing_frequency = (filing_frequency or "").strip().upper()
    taxpayer_type = (taxpayer_type or "").strip().upper()
    td = (turnover_details or "").strip().upper() if turnover_details else None
    state_u = (state or "").strip().upper() if state else None

    base_date = parse_filing_period_to_base_date(filing_period)

    def build_due_date_safe(base_dt, month_offset: int, day: int):
        target = base_dt + relativedelta(months=month_offset)
        last_day = calendar.monthrange(target.year, target.month)[1]
        safe_day = min(day, last_day)
        return datetime(target.year, target.month, safe_day, tzinfo=ist)

    def _get_status(due):
        return "MISSED" if due and due < now else "NOT_FILED"

    # Explicit one-off filing + auto disabled => do not seed scheduler chain.
    suppress_next_auto = explicit_filing_period and (not bool(is_auto_enabled))

    def _next_auto_or_none(next_auto):
        return None if suppress_next_auto else next_auto

    if filing_category == "ANNUAL" and filing_frequency == "YEARLY":
        if taxpayer_type == "REGULAR":
            gstr9_due = build_due_date_safe(base_date, 9, 31)
            gstr9c_valid = td == "MORE_THAN_5CR"
            gstr9c_due = build_due_date_safe(base_date, 9, 31) if gstr9c_valid else None
            gstr9_status = _get_status(gstr9_due)
            gstr9c_status = _get_status(gstr9c_due) if gstr9c_valid else None
            next_auto = _compute_next_auto_generate_at(
                gstr9_due,
                gstr9c_due,
                lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
            )
            await conn.execute(
                f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                    gst_filing_id,
                    filing_frequency,
                    gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                    gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                    is_auto_generated, next_auto_generate_at, is_current
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
                filing_id,
                "YEARLY",
                None,
                None,
                gstr9_status,
                gstr9c_status,
                None,
                None,
                None,
                None,
                gstr9_due,
                gstr9c_due,
                None,
                None,
                False,
                _next_auto_or_none(next_auto),
                True,
            )
        elif taxpayer_type == "COMPOSITION":
            gstr4_due = build_due_date_safe(base_date, 9, 30)
            gstr4_status = _get_status(gstr4_due)
            next_auto = _compute_next_auto_generate_at(
                gstr4_due,
                lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
            )
            await conn.execute(
                f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                    gst_filing_id,
                    filing_frequency,
                    gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                    gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                    is_auto_generated, next_auto_generate_at, is_current
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
                filing_id,
                "YEARLY",
                None,
                None,
                None,
                None,
                None,
                gstr4_status,
                None,
                None,
                None,
                None,
                None,
                gstr4_due,
                False,
                _next_auto_or_none(next_auto),
                True,
            )
        else:
            raise HTTPException(400, _ERR_TAXPAYER_RECALC)
        return

    if taxpayer_type == "REGULAR":
        if filing_frequency == "MONTHLY":
            gstr1_due = build_due_date_safe(base_date, 1, 11)
            gstr3b_due = build_due_date_safe(base_date, 1, 20)
        elif filing_frequency == "QUARTERLY":
            gstr1_due = build_due_date_safe(base_date, 1, 13)
            due_day_3b = 24 if state_u in group_2_states else 22
            gstr3b_due = build_due_date_safe(base_date, 1, due_day_3b)
        else:
            raise HTTPException(400, _ERR_REGULAR_FREQUENCY)

        gstr1_status = _get_status(gstr1_due)
        gstr3b_status = _get_status(gstr3b_due)
        next_auto_periodic = _compute_next_auto_generate_at(
            gstr1_due,
            gstr3b_due,
            lead_days=_lead_days_for_periodic_frequency(filing_frequency),
        )
        await conn.execute(
            f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                gst_filing_id,
                filing_frequency,
                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                is_auto_generated, next_auto_generate_at, is_current
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
            filing_id,
            filing_frequency,
            gstr1_status,
            gstr3b_status,
            None,
            None,
            None,
            None,
            gstr1_due,
            gstr3b_due,
            None,
            None,
            None,
            None,
            False,
            _next_auto_or_none(next_auto_periodic),
            True,
        )

        if not explicit_filing_period:
            gstr9_due = build_due_date_safe(base_date, 9, 31)
            gstr9c_valid = td == "MORE_THAN_5CR"
            gstr9c_due = build_due_date_safe(base_date, 9, 31) if gstr9c_valid else None
            gstr9_status = _get_status(gstr9_due)
            gstr9c_status = _get_status(gstr9c_due) if gstr9c_valid else None
            next_auto_annual = _compute_next_auto_generate_at(
                gstr9_due,
                gstr9c_due,
                lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
            )
            await conn.execute(
                f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                    gst_filing_id,
                    filing_frequency,
                    gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                    gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                    is_auto_generated, next_auto_generate_at, is_current
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
                filing_id,
                "YEARLY",
                None,
                None,
                gstr9_status,
                gstr9c_status,
                None,
                None,
                None,
                None,
                gstr9_due,
                gstr9c_due,
                None,
                None,
                False,
                _next_auto_or_none(next_auto_annual),
                True,
            )
        return

    if taxpayer_type == "COMPOSITION":
        if (not explicit_filing_period) or filing_frequency != "YEARLY":
            cmp08_due = build_due_date_safe(base_date, 1, 18)
            cmp08_status = _get_status(cmp08_due)
            next_auto_cmp = _compute_next_auto_generate_at(
                cmp08_due,
                lead_days=_LEAD_DAYS_QUARTERLY,
            )
            await conn.execute(
                f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                    gst_filing_id,
                    filing_frequency,
                    gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                    gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                    is_auto_generated, next_auto_generate_at, is_current
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
                filing_id,
                "QUARTERLY",
                None,
                None,
                None,
                None,
                cmp08_status,
                None,
                None,
                None,
                None,
                None,
                cmp08_due,
                None,
                False,
                _next_auto_or_none(next_auto_cmp),
                True,
            )
        if (not explicit_filing_period) or filing_frequency == "YEARLY":
            gstr4_due = build_due_date_safe(base_date, 9, 30)
            gstr4_status = _get_status(gstr4_due)
            next_auto_g4 = _compute_next_auto_generate_at(
                gstr4_due,
                lead_days=_LEAD_DAYS_YEARLY_ANNUAL,
            )
            await conn.execute(
                f"""INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                    gst_filing_id,
                    filing_frequency,
                    gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                    gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                    is_auto_generated, next_auto_generate_at, is_current
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
                filing_id,
                "YEARLY",
                None,
                None,
                None,
                None,
                None,
                gstr4_status,
                None,
                None,
                None,
                None,
                None,
                gstr4_due,
                False,
                _next_auto_or_none(next_auto_g4),
                True,
            )
        return

    raise HTTPException(400, _ERR_TAXPAYER_RECALC)


def validate_merged_filing_business_rules(
    *,
    filing_category: Optional[str],
    filing_frequency: Optional[str],
    taxpayer_type: Optional[str],
    turnover_details: Optional[str],
    filing_period: Optional[str],
) -> None:
    """
    Cross-field checks aligned with GSTFilingIn.model_validator, for merged PATCH state.
    Raises HTTPException(400, ...) on violation.
    """
    cat = (filing_category or "").strip().upper() or None
    fq = (filing_frequency or "").strip().upper() or None
    tt = (taxpayer_type or "").strip().upper() or None
    td = (turnover_details or "").strip().upper() if turnover_details else None

    if cat == "ANNUAL" and fq and fq != "YEARLY":
        raise HTTPException(400, "ANNUAL must be YEARLY")

    if cat == "RETURN" and fq == "YEARLY":
        raise HTTPException(400, "RETURN cannot be YEARLY")

    if tt == "COMPOSITION" and fq == "MONTHLY":
        raise HTTPException(400, "Composition cannot be MONTHLY")

    if tt == "COMPOSITION" and td == "MORE_THAN_5CR":
        raise HTTPException(400, "Invalid turnover for Composition")

    if tt == "REGULAR" and td == "MORE_THAN_5CR" and fq == "QUARTERLY":
        raise HTTPException(400, "Quarterly not allowed for >5CR")

    if cat == "ANNUAL" and fq == "YEARLY" and not tt:
        raise HTTPException(400, "taxpayer_type is required for ANNUAL YEARLY filings")

    fp = filing_period
    if fp and str(fp).strip():
        fp_u = str(fp).strip().upper()
        if not (
            re.match(r"^[A-Z]{3}-\d{4}$", fp_u)
            or re.match(r"^Q[1-4]-\d{4}$", fp_u)
            or re.match(r"^\d{4}-\d{2}$", fp_u)
        ):
            raise HTTPException(
                400,
                "Filing period must look like APR-2024, Q1-2024, or 2024-25. Please correct it.",
            )
        if fq == "MONTHLY" and not re.match(r"^[A-Z]{3}-\d{4}$", fp_u):
            raise HTTPException(400, "MONTHLY filing_frequency requires MMM-YYYY filing_period")
        if fq == "QUARTERLY" and not re.match(r"^Q[1-4]-\d{4}$", fp_u):
            raise HTTPException(400, "QUARTERLY filing_frequency requires Q[1-4]-YYYY filing_period")
        if fq == "YEARLY" and not re.match(r"^\d{4}-\d{2}$", fp_u):
            raise HTTPException(400, "YEARLY filing_frequency requires YYYY-YY filing_period")
