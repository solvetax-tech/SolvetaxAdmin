"""Shared AND/OR filter rule parsing for GST filings UI."""

from __future__ import annotations

from datetime import date
from typing import Callable, List, Optional, Tuple

from fastapi import HTTPException

from app.gst_registration_filing.status_constants import (
    normalize_gst_filing_status,
    normalize_return_detail_status,
    normalize_return_form_key,
    RETURN_FORM_TO_STATUS_COLUMN,
)

ReturnFormDueColumnMap = {
    "GSTR1": "gstr1_due_date",
    "GSTR3B": "gstr3b_due_date",
    "GSTR9": "gstr9_due_date",
    "GSTR9C": "gstr9c_due_date",
    "CMP08": "cmp08_due_date",
    "GSTR4": "gstr4_due_date",
}

FILING_ATTRIBUTE_FIELDS = {
    "STATUS": "f.status",
    "PRIORITY": "f.priority",
    "FILING_CATEGORY": "f.filing_category",
    "FILING_FREQUENCY": "f.filing_frequency",
    "TAXPAYER_TYPE": "f.taxpayer_type",
    "STATE": "upper(trim(COALESCE(f.state, r.state)))",
}

DOCUMENT_FILTER_FIELDS = {
    "DOCUMENT_TYPE": "d.document_type",
    "VERIFIED": "d.verified",
}

PRIORITY_VALUES = frozenset({"LOW", "NORMAL", "HIGH"})
CATEGORY_VALUES = frozenset({"RETURN", "ANNUAL"})
FREQUENCY_VALUES = frozenset({"MONTHLY", "QUARTERLY", "YEARLY"})
TAXPAYER_VALUES = frozenset({"REGULAR", "COMPOSITION"})
DOCUMENT_TYPE_VALUES = frozenset({
    "WORKING_SHEET",
    "SUMMARY_SHEET",
    "RECON_SHEET",
    "MISC_SHEET",
})
VERIFIED_VALUES = frozenset({"VERIFIED", "UNVERIFIED"})


def normalize_match_mode(value: Optional[str], *, default: str = "AND") -> str:
    mode = (value or default).strip().upper()
    if mode not in {"AND", "OR"}:
        raise ValueError("Filter match mode must be AND or OR.")
    return mode


def _parse_rule_pair(raw: str, *, label: str) -> Tuple[str, str]:
    if not isinstance(raw, str) or ":" not in raw:
        raise ValueError(f"Each {label} entry must look like FIELD:VALUE.")
    left, right = raw.split(":", 1)
    field = (left or "").strip().upper()
    value = (right or "").strip()
    if not field or not value:
        raise ValueError(f"Each {label} entry must include both field and value.")
    return field, value


def _normalize_filing_attribute_value(field: str, value: str) -> str:
    if field == "STATUS":
        normalized = normalize_gst_filing_status(value)
        return normalized or value
    if field == "PRIORITY":
        token = value.strip().upper()
        if token not in PRIORITY_VALUES:
            raise ValueError(f"Invalid priority '{value}'.")
        return token
    if field == "FILING_CATEGORY":
        token = value.strip().upper()
        if token not in CATEGORY_VALUES:
            raise ValueError(f"Invalid filing category '{value}'.")
        return token
    if field == "FILING_FREQUENCY":
        token = value.strip().upper()
        if token not in FREQUENCY_VALUES:
            raise ValueError(f"Invalid filing frequency '{value}'.")
        return token
    if field == "TAXPAYER_TYPE":
        token = value.strip().upper()
        if token not in TAXPAYER_VALUES:
            raise ValueError(f"Invalid taxpayer type '{value}'.")
        return token
    if field == "STATE":
        token = value.strip().upper()
        if not token:
            raise ValueError("State value is required.")
        return token
    raise ValueError(f"Unsupported filing attribute field '{field}'.")


def parse_filing_attribute_rules(rules: Optional[List[str]]) -> List[Tuple[str, str]]:
    if not rules:
        return []
    parsed: List[Tuple[str, str]] = []
    for raw in rules:
        field, value = _parse_rule_pair(raw, label="filing_filter_rules")
        if field not in FILING_ATTRIBUTE_FIELDS:
            allowed = ", ".join(sorted(FILING_ATTRIBUTE_FIELDS))
            raise ValueError(f"Invalid filing filter field '{field}'. Allowed: {allowed}")
        sql_expr = FILING_ATTRIBUTE_FIELDS[field]
        parsed.append((sql_expr, _normalize_filing_attribute_value(field, value)))
    return parsed


def parse_return_status_rules_list(rules: Optional[List[str]]) -> List[Tuple[str, str]]:
    if not rules:
        return []
    parsed: List[Tuple[str, str]] = []
    for raw in rules:
        if not isinstance(raw, str) or ":" not in raw:
            raise ValueError("Each return_status_rules entry must look like GSTR1:MISSED.")
        form_part, status_part = raw.split(":", 1)
        form_key = normalize_return_form_key(form_part)
        status = normalize_return_detail_status(status_part)
        if not form_key or not status:
            continue
        column = RETURN_FORM_TO_STATUS_COLUMN[form_key]
        parsed.append((column, status))
    return parsed


def _parse_iso_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD.") from exc


def parse_due_date_rules(rules: Optional[List[str]]) -> List[Tuple[str, Optional[date], Optional[date]]]:
    """Parse ``GSTR1:2024-01-01:2024-03-31`` (form:from[:to])."""
    if not rules:
        return []
    parsed: List[Tuple[str, Optional[date], Optional[date]]] = []
    for raw in rules:
        if not isinstance(raw, str) or raw.count(":") < 2:
            raise ValueError(
                "Each due_date_rules entry must look like GSTR1:2024-01-01:2024-03-31."
            )
        form_part, from_part, to_part = raw.split(":", 2)
        form_key = normalize_return_form_key(form_part)
        if not form_key:
            continue
        column = ReturnFormDueColumnMap[form_key]
        from_d = _parse_iso_date(from_part, label="Due date from") if from_part.strip() else None
        to_d = _parse_iso_date(to_part, label="Due date to") if to_part.strip() else None
        if not from_d and not to_d:
            raise ValueError("Each due date rule needs at least a from or to date.")
        parsed.append((column, from_d, to_d))
    return parsed


def _normalize_document_filter_value(field: str, value: str):
    if field == "DOCUMENT_TYPE":
        token = value.strip().upper()
        if token not in DOCUMENT_TYPE_VALUES:
            raise ValueError(f"Invalid document type '{value}'.")
        return token
    if field == "VERIFIED":
        token = value.strip().upper()
        if token not in VERIFIED_VALUES:
            raise ValueError(f"Invalid verified status '{value}'.")
        return token == "VERIFIED"
    raise ValueError(f"Unsupported document filter field '{field}'.")


def parse_document_filter_rules(rules: Optional[List[str]]) -> List[Tuple[str, object]]:
    if not rules:
        return []
    parsed: List[Tuple[str, object]] = []
    for raw in rules:
        field, value = _parse_rule_pair(raw, label="document_filter_rules")
        if field not in DOCUMENT_FILTER_FIELDS:
            allowed = ", ".join(sorted(DOCUMENT_FILTER_FIELDS))
            raise ValueError(f"Invalid document filter field '{field}'. Allowed: {allowed}")
        sql_expr = DOCUMENT_FILTER_FIELDS[field]
        parsed.append((sql_expr, _normalize_document_filter_value(field, value)))
    return parsed


def append_filing_attribute_rule_group(
    conditions: list,
    values: list,
    idx: int,
    *,
    rules: Optional[List[str]],
    match_mode: str,
) -> int:
    try:
        parsed = parse_filing_attribute_rules(rules)
        clause, idx = build_equality_rule_group(
            parsed, values=values, idx=idx, match_mode=match_mode
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if clause:
        conditions.append(clause)
    return idx


def append_document_filter_rule_group(
    conditions: list,
    values: list,
    idx: int,
    *,
    rules: Optional[List[str]],
    match_mode: str,
) -> int:
    try:
        parsed = parse_document_filter_rules(rules)
        clause, idx = build_equality_rule_group(
            parsed, values=values, idx=idx, match_mode=match_mode
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if clause:
        conditions.append(clause)
    return idx


def build_equality_rule_group(
    parsed: List[Tuple[str, object]],
    *,
    values: list,
    idx: int,
    match_mode: str,
) -> Tuple[Optional[str], int]:
    if not parsed:
        return None, idx
    mode = normalize_match_mode(match_mode)
    parts: List[str] = []
    for sql_expr, val in parsed:
        parts.append(f"{sql_expr} = ${idx}")
        values.append(val)
        idx += 1
    joiner = " AND " if mode == "AND" else " OR "
    return f"({joiner.join(parts)})", idx


def append_due_date_rule_group(
    conditions: list,
    values: list,
    idx: int,
    *,
    rules: Optional[List[str]],
    match_mode: str,
) -> int:
    try:
        parsed = parse_due_date_rules(rules)
        mode = normalize_match_mode(match_mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not parsed:
        return idx

    rule_parts: List[str] = []
    for column, from_d, to_d in parsed:
        subparts = []
        if from_d:
            subparts.append(f"d.{column}::date >= ${idx}")
            values.append(from_d)
            idx += 1
        if to_d:
            subparts.append(f"d.{column}::date <= ${idx}")
            values.append(to_d)
            idx += 1
        if subparts:
            rule_parts.append(f"({' AND '.join(subparts)})")

    if not rule_parts:
        return idx
    joiner = " AND " if mode == "AND" else " OR "
    conditions.append(f"({joiner.join(rule_parts)})")
    return idx
