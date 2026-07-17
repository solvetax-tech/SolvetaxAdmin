"""Canonical value vocabularies for every status/type/stage column in the schema.

This module is the single source of truth. These vocabularies are enforced here in
application code, NOT by database CHECK constraints -- the value-list CHECKs were
dropped deliberately so a new status can ship without a production DDL migration.
That makes this file load-bearing: if a value is not validated here, nothing stops it
reaching the column.

Each vocabulary is declared ONCE as a ``Literal`` (for Pydantic request models) and its
runtime tuple is derived via ``get_args``, so the static type and the runtime set can
never drift apart. Use the ``Literal`` in schemas; use ``normalize_*`` on any value that
does not pass through a Pydantic model -- query-string filters, scheduler writes, and
internal callers.

The DB still enforces cross-field invariants, formats and numeric ranges; those are
deliberately left in place. Two of them also pin a vocabulary as a side effect --
``versions.chk_action_json`` pins ``versions.action`` and
``crm_stage_status_mappings.chk_crm_ui_mapping_fields`` pins ``mapping_kind`` -- so
those two lists cannot be extended without also reworking that invariant.
"""

from typing import Literal, Optional, Tuple, get_args

# --------------------------------------------------------------------------- #
# GST filings
# --------------------------------------------------------------------------- #

GstFilingStatusLiteral = Literal[
    "DATA_PENDING",
    "DATA_RECEIVED",
    "IN_PREPARATION",
    "PENDING_OTP",
    "READY_TO_FILE",
    "FILED",
    "OVERDUE",
]
GST_FILING_STATUSES: Tuple[str, ...] = get_args(GstFilingStatusLiteral)

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
GST_RETURN_DETAIL_STATUSES: Tuple[str, ...] = get_args(GstReturnDetailStatusLiteral)

# System-assigned from due dates by the scheduler; never settable via manual PATCH.
GST_RETURN_DETAIL_SYSTEM_ONLY_STATUSES = frozenset({"MISSED", "OVERDUE"})

FilingFrequencyLiteral = Literal["MONTHLY", "QUARTERLY", "YEARLY"]
FILING_FREQUENCIES: Tuple[str, ...] = get_args(FilingFrequencyLiteral)

TaxpayerTypeLiteral = Literal["REGULAR", "COMPOSITION"]
TAXPAYER_TYPES: Tuple[str, ...] = get_args(TaxpayerTypeLiteral)

# gst_filings.turnover_details -- NOT the same vocabulary as the rule engine's below.
TurnoverDetailsLiteral = Literal["LESS_THAN_2CR", "BETWEEN_2CR_5CR", "MORE_THAN_5CR"]
TURNOVER_DETAILS: Tuple[str, ...] = get_args(TurnoverDetailsLiteral)

# --------------------------------------------------------------------------- #
# GST filing rule engine (reference/config table -- seeded by DBA, not by the API)
# --------------------------------------------------------------------------- #

RuleEngineReturnTypeLiteral = Literal["REGULAR", "QRMP", "COMPOSITION"]
RULE_ENGINE_RETURN_TYPES: Tuple[str, ...] = get_args(RuleEngineReturnTypeLiteral)

# Deliberately distinct from TURNOVER_DETAILS: the rule engine buckets at 5Cr and has ALL.
RuleEngineTurnoverLiteral = Literal["LESS_THAN_5CR", "MORE_THAN_5CR", "ALL"]
RULE_ENGINE_TURNOVER_VALUES: Tuple[str, ...] = get_args(RuleEngineTurnoverLiteral)

# --------------------------------------------------------------------------- #
# GST registration
# --------------------------------------------------------------------------- #

# gst_registration.registration_status has never had a value CHECK -- it has always been
# code-only. Centralised here because the read-filter and the write-schema had drifted.
RegistrationStatusLiteral = Literal["DRAFT", "APPROVED", "SUSPENDED", "CANCELLED"]
REGISTRATION_STATUSES: Tuple[str, ...] = get_args(RegistrationStatusLiteral)

# --------------------------------------------------------------------------- #
# CRM leads
# --------------------------------------------------------------------------- #

# Union of the GST and ITR funnels. Individual funnels expose narrower Literals below;
# this is the full set the column accepts.
CrmStageLiteral = Literal[
    "FRESH_LEAD",
    "PENDING_REGISTRATION_DATA",
    "FOLLOW_UP",
    "INTERESTED",
    "GST_REGISTRATION_DONE",
    "SCHEDULED_PAYMENTS",
    "SUBSCRIBED",
    "NOT_INTERESTED",
    "PENDING_ITR_DATA",
    "ITR_DONE",
]
CRM_STAGES: Tuple[str, ...] = get_args(CrmStageLiteral)

CrmStageGstLiteral = Literal[
    "FRESH_LEAD",
    "PENDING_REGISTRATION_DATA",
    "FOLLOW_UP",
    "INTERESTED",
    "GST_REGISTRATION_DONE",
    "SCHEDULED_PAYMENTS",
    "SUBSCRIBED",
    "NOT_INTERESTED",
]
CRM_STAGES_GST: Tuple[str, ...] = get_args(CrmStageGstLiteral)

CrmStageItrLiteral = Literal[
    "FRESH_LEAD",
    "PENDING_ITR_DATA",
    "FOLLOW_UP",
    "INTERESTED",
    "ITR_DONE",
    "SCHEDULED_PAYMENTS",
    "SUBSCRIBED",
    "NOT_INTERESTED",
]
CRM_STAGES_ITR: Tuple[str, ...] = get_args(CrmStageItrLiteral)

CrmBulkAssignRunTypeLiteral = Literal["AUTO", "MANUAL"]
CRM_BULK_ASSIGN_RUN_TYPES: Tuple[str, ...] = get_args(CrmBulkAssignRunTypeLiteral)

# Pinned by crm_stage_status_mappings.chk_crm_ui_mapping_fields -- see module docstring.
CrmMappingKindLiteral = Literal["STAGE_TO_PITCH", "PITCH_TO_STATUS"]
CRM_MAPPING_KINDS: Tuple[str, ...] = get_args(CrmMappingKindLiteral)

# --------------------------------------------------------------------------- #
# Follow-ups -- one vocabulary shared by crm_leads, customer_services and payments
# --------------------------------------------------------------------------- #

FollowupStatusLiteral = Literal["PENDING", "COMPLETED", "MISSED"]
FOLLOWUP_STATUSES: Tuple[str, ...] = get_args(FollowupStatusLiteral)

# --------------------------------------------------------------------------- #
# Customer services
# --------------------------------------------------------------------------- #

ServiceStatusLiteral = Literal["PENDING", "PROVIDED"]
SERVICE_STATUSES: Tuple[str, ...] = get_args(ServiceStatusLiteral)

# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #

PaymentStatusLiteral = Literal["PENDING", "PAID", "CANCELLED"]
PAYMENT_STATUSES: Tuple[str, ...] = get_args(PaymentStatusLiteral)

# --------------------------------------------------------------------------- #
# Income tax
# --------------------------------------------------------------------------- #

FiledStatusLiteral = Literal["FILED", "NOT_FILED"]
FILED_STATUSES: Tuple[str, ...] = get_args(FiledStatusLiteral)

IncomeTaxPriorityLiteral = Literal["LOW", "NORMAL", "HIGH"]
INCOME_TAX_PRIORITIES: Tuple[str, ...] = get_args(IncomeTaxPriorityLiteral)

# --------------------------------------------------------------------------- #
# Versions (audit log)
# --------------------------------------------------------------------------- #

# Pinned by versions.chk_action_json -- see module docstring.
VersionActionLiteral = Literal["CREATE", "UPDATE", "DELETE", "ACTIVATE"]
VERSION_ACTIONS: Tuple[str, ...] = get_args(VersionActionLiteral)

# --------------------------------------------------------------------------- #
# OTP
# --------------------------------------------------------------------------- #

# Lower-case in the DB, unlike every other vocabulary here -- do not upper-case these.
OtpPurposeLiteral = Literal["customer", "password_reset"]
OTP_PURPOSES: Tuple[str, ...] = get_args(OtpPurposeLiteral)


# --------------------------------------------------------------------------- #
# Normalizers
# --------------------------------------------------------------------------- #


def _normalize(
    value: Optional[str],
    allowed: Tuple[str, ...],
    label: str,
    *,
    upper: bool = True,
    required: bool = False,
) -> Optional[str]:
    """Upper-case and validate ``value`` against ``allowed``. None/blank -> None.

    Raises ValueError naming the allowed set, so callers can surface a 400 rather than
    letting a bad value through to the column.

    ``required=True`` makes None/blank a ValueError too. Pass it when normalizing a
    value bound for a NOT NULL column: the default None return is meant for optional
    query-string filters ("no filter"), and letting it reach an INSERT turns a blank
    input into a NULL and a confusing NotNullViolation instead of a clean 400.
    """
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ValueError(f"{label} is required. Allowed: {', '.join(allowed)}")
        return None
    normalized = value.strip().upper() if upper else value.strip()
    if normalized not in allowed:
        raise ValueError(
            f"Invalid {label} '{normalized}'. Allowed: {', '.join(allowed)}"
        )
    return normalized


def normalize_gst_filing_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, GST_FILING_STATUSES, "filing status")


def normalize_return_detail_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, GST_RETURN_DETAIL_STATUSES, "return status")


def normalize_filing_frequency(value: Optional[str]) -> Optional[str]:
    return _normalize(value, FILING_FREQUENCIES, "filing frequency")


def normalize_taxpayer_type(value: Optional[str]) -> Optional[str]:
    return _normalize(value, TAXPAYER_TYPES, "taxpayer type")


def normalize_turnover_details(value: Optional[str]) -> Optional[str]:
    return _normalize(value, TURNOVER_DETAILS, "turnover details")


def normalize_registration_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, REGISTRATION_STATUSES, "registration status")


def normalize_crm_stage(value: Optional[str]) -> Optional[str]:
    return _normalize(value, CRM_STAGES, "CRM stage")


def normalize_run_type(value: Optional[str], *, required: bool = False) -> Optional[str]:
    return _normalize(value, CRM_BULK_ASSIGN_RUN_TYPES, "run type", required=required)


def normalize_mapping_kind(value: Optional[str]) -> Optional[str]:
    return _normalize(value, CRM_MAPPING_KINDS, "mapping kind")


def normalize_followup_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, FOLLOWUP_STATUSES, "follow-up status")


def normalize_service_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, SERVICE_STATUSES, "service status")


def normalize_payment_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, PAYMENT_STATUSES, "payment status")


def normalize_filed_status(value: Optional[str]) -> Optional[str]:
    return _normalize(value, FILED_STATUSES, "filed status")


def normalize_priority(value: Optional[str]) -> Optional[str]:
    return _normalize(value, INCOME_TAX_PRIORITIES, "priority")


def normalize_version_action(value: Optional[str]) -> Optional[str]:
    return _normalize(value, VERSION_ACTIONS, "version action")


def normalize_otp_purpose(value: Optional[str]) -> Optional[str]:
    return _normalize(value, OTP_PURPOSES, "OTP purpose", upper=False)
