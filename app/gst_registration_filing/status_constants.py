"""Canonical GST filing and return-detail status values (aligned with DB CHECK constraints)."""

from typing import List, Literal, Optional, Tuple

GST_FILING_STATUSES: Tuple[str, ...] = (
    "DATA_PENDING",
    "DATA_RECEIVED",
    "IN_PREPARATION",
    "PENDING_OTP",
    "READY_TO_FILE",
    "FILED",
    "OVERDUE",
)

GST_RETURN_DETAIL_STATUSES: Tuple[str, ...] = GST_FILING_STATUSES + ("NOT_FILED", "MISSED")

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

GstFilingStatusLiteral = Literal[
    "DATA_PENDING",
    "DATA_RECEIVED",
    "IN_PREPARATION",
    "PENDING_OTP",
    "READY_TO_FILE",
    "FILED",
    "OVERDUE",
]

GstReturnDetailStatusLiteral = Literal[
    "DATA_PENDING",
    "DATA_RECEIVED",
    "IN_PREPARATION",
    "PENDING_OTP",
    "READY_TO_FILE",
    "FILED",
    "OVERDUE",
    "NOT_FILED",
    "MISSED",
]


def normalize_gst_filing_status(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().upper()
    if normalized not in GST_FILING_STATUSES:
        allowed = ", ".join(GST_FILING_STATUSES)
        raise ValueError(f"Invalid filing status '{normalized}'. Allowed: {allowed}")
    return normalized


def normalize_return_detail_status(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().upper()
    if normalized not in GST_RETURN_DETAIL_STATUSES:
        allowed = ", ".join(GST_RETURN_DETAIL_STATUSES)
        raise ValueError(f"Invalid return status '{normalized}'. Allowed: {allowed}")
    return normalized


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
