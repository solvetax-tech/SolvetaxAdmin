"""
Pure helpers for GST return-detail auto-generation (scheduler chain).

Seeding lives in gst_return_details_rebuild.py; this module builds the *next* chained row.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

# Month lengths for `_add_months` (February adjusted per year in-line).
_DAYS_NON_LEAP = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# Filing categories that carry REGULAR GSTR-9 / GSTR-9C yearly return-detail rows.
_GSTR9C_SYNC_CATEGORIES = ("RETURN", "ANNUAL")


def gstr9c_sync_category_sql(column: str = "f.filing_category") -> str:
    """SQL fragment: filing category eligible for GSTR-9C turnover sync."""
    cats = ", ".join(f"'{c}'" for c in _GSTR9C_SYNC_CATEGORIES)
    return f"UPPER(TRIM({column})) IN ({cats})"


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return _DAYS_NON_LEAP[month - 1]


def _add_months(ts, months: int):
    year = ts.year + (ts.month - 1 + months) // 12
    month = (ts.month - 1 + months) % 12 + 1
    day = min(ts.day, _days_in_month(year, month))
    return ts.replace(year=year, month=month, day=day)


def _shift_due(ts, months: int):
    return _add_months(ts, months) if ts is not None else None


def lead_days_for_cadence_months(cadence_months: int) -> int:
    """Match gst_return_details_rebuild: monthly 10d, quarterly 12d, annual 7d."""
    if cadence_months == 1:
        return 10
    if cadence_months == 3:
        return 12
    return 7


def _next_auto_from_due_dates(*dates, lead_days: int = 7):
    valid = [d for d in dates if d is not None]
    if not valid:
        return None
    return min(valid) - timedelta(days=lead_days)


def _form_applicable(src: dict, status_key: str, due_key: str) -> bool:
    return src.get(status_key) is not None or src.get(due_key) is not None


def _cadence_months_for_row(src: dict, row_frequency: str) -> int:
    if _form_applicable(src, "gstr9_status", "gstr9_due_date") or _form_applicable(
        src, "gstr9c_status", "gstr9c_due_date"
    ):
        return 12
    if _form_applicable(src, "gstr4_status", "gstr4_due_date"):
        return 12
    if _form_applicable(src, "cmp08_status", "cmp08_due_date"):
        return 3
    freq = (row_frequency or "").strip().upper()
    if freq == "MONTHLY":
        return 1
    if freq == "QUARTERLY":
        return 3
    return 12


def _frequency_from_cadence(cadence_months: int) -> str:
    if cadence_months == 1:
        return "MONTHLY"
    if cadence_months == 3:
        return "QUARTERLY"
    return "YEARLY"


def chain_filing_frequency(src: dict, next_row: Optional[dict] = None) -> str:
    """Return-detail chain key: MONTHLY / QUARTERLY / YEARLY row band on one gst_filing_id."""
    if next_row and next_row.get("filing_frequency"):
        return str(next_row["filing_frequency"]).strip().upper()
    return resolve_row_filing_frequency(src)


def resolve_row_filing_frequency(src: dict) -> str:
    """
    Prefer return-detail ``filing_frequency``; fall back to parent filing frequency;
    then infer from applicable return columns (legacy auto-generated rows).
    """
    detail = (src.get("detail_filing_frequency") or "").strip().upper()
    if detail in ("MONTHLY", "QUARTERLY", "YEARLY"):
        return detail

    parent = (src.get("parent_filing_frequency") or "").strip().upper()
    if parent in ("MONTHLY", "QUARTERLY", "YEARLY"):
        cadence = _cadence_months_for_row(src, parent)
        return _frequency_from_cadence(cadence)

    gstr1 = _form_applicable(src, "gstr1_status", "gstr1_due_date")
    gstr3b = _form_applicable(src, "gstr3b_status", "gstr3b_due_date")
    gstr9 = _form_applicable(src, "gstr9_status", "gstr9_due_date")
    gstr9c = _form_applicable(src, "gstr9c_status", "gstr9c_due_date")
    cmp08 = _form_applicable(src, "cmp08_status", "cmp08_due_date")
    gstr4 = _form_applicable(src, "gstr4_status", "gstr4_due_date")

    if gstr9 or gstr9c or (gstr4 and not cmp08 and not gstr1):
        return "YEARLY"
    if cmp08 and not gstr1:
        return "QUARTERLY"
    if gstr1 or gstr3b:
        return "MONTHLY"
    return "YEARLY"


def build_next_row_from_source(
    src: dict,
    parent_turnover_details: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the next chained return-detail row from a source row.

    Keeps only applicable returns as NOT_FILED; others stay NULL.
    Sets ``filing_frequency`` to match seed templates for the row type.
    """
    gstr1_applicable = _form_applicable(src, "gstr1_status", "gstr1_due_date")
    gstr3b_applicable = _form_applicable(src, "gstr3b_status", "gstr3b_due_date")
    gstr9_applicable = _form_applicable(src, "gstr9_status", "gstr9_due_date")
    gstr9c_applicable = _form_applicable(src, "gstr9c_status", "gstr9c_due_date")
    cmp08_applicable = _form_applicable(src, "cmp08_status", "cmp08_due_date")
    gstr4_applicable = _form_applicable(src, "gstr4_status", "gstr4_due_date")

    row_frequency = resolve_row_filing_frequency(src)
    cadence_months = _cadence_months_for_row(src, row_frequency)

    gstr1_due = _shift_due(src.get("gstr1_due_date"), cadence_months)
    gstr3b_due = _shift_due(src.get("gstr3b_due_date"), cadence_months)
    gstr9_due = _shift_due(src.get("gstr9_due_date"), cadence_months)
    gstr9c_due = _shift_due(src.get("gstr9c_due_date"), cadence_months)
    cmp08_due = _shift_due(src.get("cmp08_due_date"), cadence_months)
    gstr4_due = _shift_due(src.get("gstr4_due_date"), cadence_months)

    td = (parent_turnover_details or "").strip().upper() if parent_turnover_details else ""
    if td == "MORE_THAN_5CR" and gstr9_due is not None and gstr9c_due is None:
        gstr9c_due = gstr9_due
        gstr9c_applicable = True

    lead = lead_days_for_cadence_months(cadence_months)
    next_auto = _next_auto_from_due_dates(
        gstr1_due,
        gstr3b_due,
        gstr9_due,
        gstr9c_due,
        cmp08_due,
        gstr4_due,
        lead_days=lead,
    )

    return {
        "filing_frequency": _frequency_from_cadence(cadence_months),
        "gstr1_status": "NOT_FILED" if gstr1_applicable else None,
        "gstr3b_status": "NOT_FILED" if gstr3b_applicable else None,
        "gstr9_status": "NOT_FILED" if gstr9_applicable else None,
        "gstr9c_status": "NOT_FILED" if gstr9c_applicable else None,
        "cmp08_status": "NOT_FILED" if cmp08_applicable else None,
        "gstr4_status": "NOT_FILED" if gstr4_applicable else None,
        "gstr1_due_date": gstr1_due,
        "gstr3b_due_date": gstr3b_due,
        "gstr9_due_date": gstr9_due,
        "gstr9c_due_date": gstr9c_due,
        "cmp08_due_date": cmp08_due,
        "gstr4_due_date": gstr4_due,
        "next_auto_generate_at": next_auto,
    }
