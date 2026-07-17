"""GST return-form column plumbing, plus re-exports of the shared status vocabularies.

The status/type value lists and their normalizers live in ``backend.common.status_constants``
(the single source of truth); they are re-exported here so existing importers keep working.
Everything defined below is GST-specific column mapping, which is deliberately NOT in the
generic constants module.
"""

from typing import List, Optional, Tuple

from backend.common.status_constants import (
    GST_FILING_STATUSES,
    GST_RETURN_DETAIL_STATUSES,
    GST_RETURN_DETAIL_SYSTEM_ONLY_STATUSES,
    GstFilingStatusLiteral,
    GstReturnDetailStatusLiteral,
    normalize_gst_filing_status,
    normalize_return_detail_status,
)

GST_RETURN_STATUS_COLUMNS: Tuple[str, ...] = (
    "gstr1_status",
    "gstr3b_status",
    "gstr9_status",
    "gstr9c_status",
    "cmp08_status",
    "gstr4_status",
)

RETURN_FORM_TO_STATUS_COLUMN: dict[str, str] = {
    "GSTR1": "gstr1_status",
    "GSTR3B": "gstr3b_status",
    "GSTR9": "gstr9_status",
    "GSTR9C": "gstr9c_status",
    "CMP08": "cmp08_status",
    "GSTR4": "gstr4_status",
}

RETURN_FORM_TO_FOLLOWUP_COLUMN: dict[str, str] = {
    "GSTR1": "gstr1_followup_at",
    "GSTR3B": "gstr3b_followup_at",
    "GSTR9": "gstr9_followup_at",
    "GSTR9C": "gstr9c_followup_at",
    "CMP08": "cmp08_followup_at",
    "GSTR4": "gstr4_followup_at",
}

RETURN_FORM_TO_DUE_DATE_COLUMN: dict[str, str] = {
    "GSTR1": "gstr1_due_date",
    "GSTR3B": "gstr3b_due_date",
    "GSTR9": "gstr9_due_date",
    "GSTR9C": "gstr9c_due_date",
    "CMP08": "cmp08_due_date",
    "GSTR4": "gstr4_due_date",
}

GST_RETURN_FOLLOWUP_COLUMNS: Tuple[str, ...] = tuple(RETURN_FORM_TO_FOLLOWUP_COLUMN.values())

__all__ = [
    # Re-exported from backend.common.status_constants
    "GST_FILING_STATUSES",
    "GST_RETURN_DETAIL_STATUSES",
    "GST_RETURN_DETAIL_SYSTEM_ONLY_STATUSES",
    "GstFilingStatusLiteral",
    "GstReturnDetailStatusLiteral",
    "normalize_gst_filing_status",
    "normalize_return_detail_status",
    # GST-specific column plumbing
    "GST_RETURN_STATUS_COLUMNS",
    "RETURN_FORM_TO_STATUS_COLUMN",
    "RETURN_FORM_TO_FOLLOWUP_COLUMN",
    "RETURN_FORM_TO_DUE_DATE_COLUMN",
    "GST_RETURN_FOLLOWUP_COLUMNS",
    "normalize_return_form_key",
    "parse_return_status_rules",
]


def normalize_return_form_key(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    token = value.strip().upper().replace("-", "").replace("_", "")
    aliases = {
        "GSTR1": "GSTR1",
        "GSTR3B": "GSTR3B",
        "GSTR9": "GSTR9",
        "GSTR9C": "GSTR9C",
        "CMP08": "CMP08",
        "GSTR4": "GSTR4",
    }
    if token not in aliases:
        allowed = ", ".join(sorted(RETURN_FORM_TO_STATUS_COLUMN.keys()))
        raise ValueError(f"Invalid return form '{value}'. Allowed: {allowed}")
    return aliases[token]


def parse_return_status_rules(
    rules: Optional[List[str]],
) -> List[Tuple[str, str]]:
    """Parse ``GSTR1:MISSED`` style rules into (column_name, status) pairs."""
    if not rules:
        return []
    parsed: List[Tuple[str, str]] = []
    for raw in rules:
        if not isinstance(raw, str) or ":" not in raw:
            raise ValueError(
                "Each return_status_rules entry must look like GSTR1:MISSED."
            )
        form_part, status_part = raw.split(":", 1)
        form_key = normalize_return_form_key(form_part)
        status = normalize_return_detail_status(status_part)
        if not form_key or not status:
            continue
        column = RETURN_FORM_TO_STATUS_COLUMN[form_key]
        parsed.append((column, status))
    return parsed
