"""Shared helpers for income tax array columns and API responses."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional, Union
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

FY_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")

INCOME_TAX_CRM_ENTITY_TYPE = "INCOME_TAX"
CRM_LEAD_STAGE_INTAKE = "FRESH_LEAD"

INCOME_SOURCE_PRESETS = frozenset({
    "SALARY",
    "BUSINESS",
    "PROFESSION",
    "CAPITAL_GAINS",
    "HOUSE_PROPERTY",
    "OTHER_SOURCES",
})

_INCOME_TAX_CACHE_RESPONSE_VER = "10"

INCOME_TAX_FILTER_DEFAULT_LIMIT = 20
INCOME_TAX_FILTER_MAX_LIMIT = 100

_INCOME_TAX_COLUMN_NAMES = (
    "id",
    "client_name",
    "mobile",
    "language",
    "state",
    "priority",
    "remarks",
    "pan_number",
    "financial_year",
    "filed_status",
    "filing_date",
    "email_id",
    "source_of_income",
    "refund_amount",
    "rm_id",
    "op_id",
    "referral_phone_number",
    "year",
    "is_active",
    "created_at",
    "updated_at",
)


def income_tax_cache_ver() -> str:
    return _INCOME_TAX_CACHE_RESPONSE_VER


def current_income_tax_year() -> int:
    """Calendar year used for mobile+year uniqueness (IST)."""
    return datetime.now(IST).year


def income_tax_select_columns(alias: str = "i") -> str:
    prefix = f"{alias}." if alias else ""
    return ",\n    ".join(f"{prefix}{name}" for name in _INCOME_TAX_COLUMN_NAMES)


def income_tax_returning_columns() -> str:
    return ", ".join(_INCOME_TAX_COLUMN_NAMES)


# `year` is set on create only — never included here.
INCOME_TAX_EDITABLE_FIELDS = frozenset({
    "client_name",
    "mobile",
    "pan_number",
    "priority",
    "financial_year",
    "email_id",
    "state",
    "language",
    "source_of_income",
    "filed_status",
    "refund_amount",
    "referral_phone_number",
    "remarks",
    "rm_id",
    "op_id",
    "is_active",
})


def normalize_query_str_list(value: Any) -> List[str]:
    """Query params: single string or repeated keys → deduped list."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    out: List[str] = []
    seen: set[str] = set()
    for raw in items:
        s = str(raw).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def default_intake_financial_year(reference: Optional[datetime] = None) -> List[str]:
    """Placeholder FY for lead intake before PAN / FY are confirmed on the ITR form."""
    max_start = _max_allowed_financial_year_start(reference)
    return [f"{max_start}-{(max_start + 1) % 100:02d}"]


def _max_allowed_financial_year_start(reference: Optional[datetime] = None) -> int:
    """Latest FY start year allowed for filing in the current calendar year (IST)."""
    when = reference or datetime.now(IST)
    return when.year - 2


def _financial_year_encoding_error(fy: str) -> Optional[str]:
    """YYYY-YY suffix must match start year + 1 (e.g. 2024-25)."""
    m = re.match(r"^(\d{4})-(\d{2})$", fy)
    if not m:
        return f"Invalid financial year format: {fy!r}. Expected YYYY-YY."
    start = int(m.group(1))
    suffix = m.group(2)
    expected = f"{(start + 1) % 100:02d}"
    if suffix != expected:
        return (
            f"Financial year should be written as {start}-{expected} "
            f"(FY {start}–{start + 1}), not {fy!r}."
        )
    return None


def _financial_year_filing_window_error(
    fy: str, reference: Optional[datetime] = None
) -> Optional[str]:
    """Only previous FYs for the current calendar year (e.g. in 2026, up to 2024-25)."""
    m = re.match(r"^(\d{4})-", fy)
    if not m:
        return None
    when = reference or datetime.now(IST)
    start = int(m.group(1))
    max_start = _max_allowed_financial_year_start(when)
    if start > max_start:
        max_label = f"{max_start}-{(max_start + 1) % 100:02d}"
        return (
            f"In {when.year}, only previous financial years can be filed "
            f"(up to {max_label}). {fy!r} is not allowed."
        )
    return None


def normalize_financial_year_list(value: Any) -> List[str]:
    if value is None:
        raise ValueError("financial_year is required")
    items = [value] if isinstance(value, str) else list(value)
    if not items:
        raise ValueError("At least one financial year is required")

    out: List[str] = []
    seen: set[str] = set()
    for raw in items:
        fy = str(raw).strip()
        if not FY_PATTERN.match(fy):
            raise ValueError(f"Invalid financial year format: {fy!r}. Expected YYYY-YY.")
        encoding_err = _financial_year_encoding_error(fy)
        if encoding_err:
            raise ValueError(encoding_err)
        window_err = _financial_year_filing_window_error(fy)
        if window_err:
            raise ValueError(window_err)
        if fy in seen:
            continue
        seen.add(fy)
        out.append(fy)
    return out


def normalize_source_of_income_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    items = [value] if isinstance(value, str) else list(value)
    if not items:
        return None

    out: List[str] = []
    seen_upper: set[str] = set()

    for raw in items:
        token = str(raw).strip()
        if not token:
            continue
        upper = token.upper()
        if upper in INCOME_SOURCE_PRESETS:
            normalized = upper
        else:
            if len(token) < 2 or len(token) > 100:
                raise ValueError(
                    "Custom income source labels must be between 2 and 100 characters."
                )
            normalized = token

        dedupe_key = normalized.upper()
        if dedupe_key in seen_upper:
            continue
        seen_upper.add(dedupe_key)
        out.append(normalized)

    return out or None


def normalize_ay_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()[:20]
        return s or None
    return str(value).strip()[:20] or None


def resolve_income_tax_ay(
    *,
    ay: Optional[str] = None,
    financial_year: Optional[List[str]] = None,
    crm_lead_ay: Optional[str] = None,
) -> Optional[str]:
    """Assessment year for CRM (defaults to primary financial year, e.g. 2024-25)."""
    explicit = normalize_ay_value(ay)
    if explicit:
        return explicit
    existing = normalize_ay_value(crm_lead_ay)
    if existing:
        return existing
    if financial_year:
        for raw in financial_year:
            fy = normalize_ay_value(raw)
            if fy and FY_PATTERN.match(fy):
                return fy
    default_fy = default_intake_financial_year()
    return default_fy[0] if default_fy else None


def income_tax_row_to_dict(row: Any) -> dict:
    data = dict(row)
    data.pop("password", None)
    if data.get("year") is None and data.get("created_at") is not None:
        created = data["created_at"]
        if hasattr(created, "astimezone"):
            data["year"] = created.astimezone(IST).year
        else:
            data["year"] = datetime.now(IST).year
    fy = data.get("financial_year")
    if fy is not None:
        data["financial_year"] = list(fy)
    src = data.get("source_of_income")
    if src is not None:
        data["source_of_income"] = list(src)
    return data
