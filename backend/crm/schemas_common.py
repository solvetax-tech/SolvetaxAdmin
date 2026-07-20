"""Schemas for shared CRM routes (marketing, bulk import/assign, UI mappings, pipeline stages)."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CRM_MARKETING_ENTITY_TYPES = Literal["GST_REGISTRATION", "INCOME_TAX"]


class CRMBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class CRMLeadEntityIdPatchIn(CRMBaseSchema):
    """
    Link ``crm_leads.entity_id`` to a concrete registration row, or clear it.

    Body must include ``entity_id``: a positive integer, or JSON ``null`` to clear the link.

    Must match the lead funnel: GST routes → ``gst_registration.id``; ITR routes → ``income_tax.id``.
    """

    entity_id: Optional[int] = Field(
        ...,
        description="Primary key to link, or JSON null to clear entity_id.",
    )

    @field_validator("entity_id")
    @classmethod
    def entity_id_positive_when_set(cls, v: Optional[int]):
        if v is not None and v < 1:
            raise ValueError("entity_id must be >= 1 when set")
        return v


class CRMLeadCreateIn(CRMBaseSchema):
    """Internal (authenticated) manual lead intake, used by the CRM "Create Lead"
    button. ``entity_type`` and ``stage`` are set server-side (stage=FRESH_LEAD),
    so they are NOT accepted from the client. Only ``mobile`` is required — a rep
    can create a lead from just a phone number and fill the rest later.
    """

    mobile: str = Field(..., min_length=10, max_length=20)
    full_name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=255)
    preferred_language: Optional[str] = Field(default=None, max_length=50)
    lead_type: Optional[str] = Field(default=None, max_length=50)
    tag: Optional[str] = Field(default=None, max_length=100)
    lead_source: Optional[str] = Field(default=None, max_length=100)
    remarks: Optional[str] = Field(default=None, max_length=2000)
    ay: Optional[str] = Field(default=None, max_length=20, description="Assessment year (ITR only, e.g. 2024-25).")
    # Assignment. Server enforces the rules by role: an RM's rm_id is forced to
    # self, an OP's op_id to self; managers pick both. Both end up required.
    rm_id: Optional[int] = Field(default=None, gt=0, description="Assigned RM emp_id.")
    op_id: Optional[int] = Field(default=None, gt=0, description="Assigned OP emp_id.")

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("full_name", "email", "preferred_language", "lead_type", "tag", "lead_source", "remarks", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v


class CRMLeadMarketingCreateIn(CRMBaseSchema):
    """
    External / digital-marketing intake: persists only ``crm_leads`` (no gst_registration / income_tax row).
    ``stage``, ``is_active``, and ``follow_up_status`` are set server-side.
    """

    mobile: str = Field(..., min_length=10, max_length=20)
    full_name: str = Field(..., min_length=1, max_length=200)
    entity_type: CRM_MARKETING_ENTITY_TYPES
    preferred_language: str = Field(..., min_length=1, max_length=50)
    lead_type: str = Field(..., min_length=1, max_length=50)
    tag: str = Field(..., min_length=1, max_length=100)
    lead_source: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(default=None, max_length=255)
    remarks: Optional[str] = Field(default=None, max_length=2000)
    ay: Optional[str] = Field(default=None, max_length=20, description="Assessment year (e.g. 2024-25).")

    @field_validator("ay", mode="before")
    @classmethod
    def normalize_ay_marketing(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s[:20] if s else None
        return v

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name_marketing(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("entity_type", mode="before")
    @classmethod
    def normalize_entity_type(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator(
        "preferred_language",
        "lead_type",
        "tag",
        "lead_source",
        mode="before",
    )
    @classmethod
    def strip_nonempty_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_optional(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip().lower()
            return s if s else None
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def normalize_remarks_optional(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    @model_validator(mode="after")
    def validate_mobile_digits(self):
        if not self.mobile.isdigit() or len(self.mobile) != 10:
            raise ValueError("mobile must be a 10-digit number")
        return self


class CRMBulkImportRowIn(CRMBaseSchema):
    """
    Bulk row aligned with ``CRMLeadMarketingCreateIn``: required capture fields per row.
    Inserts/updates operate on ``crm_leads`` only (no gst_registration / income_tax writes).
    ``entity_id`` is optional on each row (stored on insert). Duplicate detection for
    update/skip uses ``mobile`` + ``entity_type`` only (latest row by ``id`` wins).
    """

    mobile: str = Field(..., min_length=10, max_length=20)
    entity_type: CRM_MARKETING_ENTITY_TYPES
    preferred_language: str = Field(..., min_length=1, max_length=50)
    lead_type: str = Field(..., min_length=1, max_length=50)
    tag: Optional[str] = Field(default=None, max_length=100)
    lead_source: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=200)

    stage: Optional[str] = Field(default=None, max_length=40)
    followup_at: Optional[datetime] = None
    rm_id: Optional[int] = Field(default=None, gt=0)
    op_id: Optional[int] = Field(default=None, gt=0)
    remarks: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = True
    follow_up_status: Optional[Literal["PENDING", "COMPLETED", "MISSED"]] = "PENDING"
    entity_id: Optional[int] = Field(default=None, gt=0)
    ay: Optional[str] = Field(default=None, max_length=20, description="Assessment year (e.g. 2024-25).")

    @field_validator("ay", mode="before")
    @classmethod
    def normalize_ay_bulk(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in {"null", "none", "na", "nan"}:
                return None
            return s[:20]
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("entity_type", mode="before")
    @classmethod
    def normalize_entity_type(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("preferred_language", "lead_type", mode="before")
    @classmethod
    def strip_required_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("tag", "lead_source", mode="before")
    @classmethod
    def normalize_optional_tag_source(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in {"null", "none", "na", "nan"}:
                return None
            return s
        return v

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper() if s else None
        return v

    @field_validator("follow_up_status", mode="before")
    @classmethod
    def normalize_follow_up_status(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip().upper()
            if not s or s in {"NULL", "NONE", "NA", "NAN"}:
                return None
            return s
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_optional(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip().lower()
            if not s or s in {"null", "none", "na", "nan"}:
                return None
            return s
        return v

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name_bulk_optional(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in {"null", "none", "na", "nan"}:
                return None
            return s[:200]
        return v

    @model_validator(mode="after")
    def validate_mobile_digits(self):
        if not self.mobile.isdigit() or len(self.mobile) != 10:
            raise ValueError("mobile must be a 10-digit number")
        return self


class CRMBulkImportIn(CRMBaseSchema):
    rows: List[CRMBulkImportRowIn] = Field(..., min_length=1, max_length=5000)
    validate_only: bool = False


class CRMBulkImportStatsOut(CRMBaseSchema):
    """Summary returned by CSV/XLSX bulk import (``POST /crm/leads/import``)."""

    total_rows: int
    new_leads: int
    duplicates_found: int
    duplicates_skipped: int
    duplicates_updated: int
    failed_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int


class CRMBulkAssignExecuteIn(CRMBaseSchema):
    lead_ids: List[int] = Field(..., min_length=1, max_length=10000)
    selected_employee_ids: Optional[List[int]] = Field(default=None, min_length=1, max_length=500)
    selected_usernames: Optional[List[str]] = Field(default=None, min_length=1, max_length=500)
    assignment_role: Literal["RM", "OP"]
    per_employee_limit: Optional[int] = Field(default=None, ge=1, le=10000)
    round_robin_start_index: Optional[int] = Field(
        default=None,
        ge=0,
        description="Auto-assign: resume round-robin from this index in selected_usernames order.",
    )
    suppress_log: bool = Field(
        default=False,
        description="When true, skip writing assignment history (use with batch_log_roles on final chained call).",
    )
    batch_log_roles: Optional[dict] = Field(
        default=None,
        description="Optional prior role results for one combined MANUAL log row (RM+OP in one action).",
    )

    @model_validator(mode="after")
    def _require_assignees(self):
        has_ids = bool(self.selected_employee_ids)
        has_usernames = bool(self.selected_usernames)
        if has_ids == has_usernames:
            raise ValueError("Provide exactly one of selected_employee_ids or selected_usernames.")
        return self


class CRMBulkAutoAssignFiltersIn(CRMBaseSchema):
    """Same filter shape as GET /bulk-assign/candidates (stored for scheduler replay)."""

    stages: List[str] = Field(default_factory=list)
    rm_ids: List[int] = Field(default_factory=list)
    op_ids: List[int] = Field(default_factory=list)
    lead_types: List[str] = Field(default_factory=list)
    ays: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    lead_sources: List[str] = Field(default_factory=list)
    entity_types: List[str] = Field(default_factory=list)
    follow_up_statuses: List[str] = Field(default_factory=list)
    null_fields: List[str] = Field(default_factory=list)
    not_null_fields: List[str] = Field(default_factory=list)
    is_active: Optional[bool] = None
    match_mode: Literal["AND", "OR"] = "AND"
    filter_mode: Literal["IN", "NOT_IN"] = "IN"
    limit: int = Field(default=500, ge=1, le=5000)


class CRMBulkAutoAssignEnabledPatchIn(CRMBaseSchema):
    """Quick on/off for a saved scheduler without resubmitting full config."""

    enabled: bool


class CRMBulkAutoAssignConfigIn(CRMBaseSchema):
    """Create or update one auto bulk-assign scheduler (multiple per entity_type allowed)."""

    id: Optional[int] = Field(default=None, ge=1, description="Set to update; omit to create a new scheduler.")
    name: str = Field(default="Scheduler", min_length=1, max_length=120)
    enabled: bool = False
    entity_type: str = Field(..., min_length=1, max_length=64)
    filters: CRMBulkAutoAssignFiltersIn
    assign_rm: bool = False
    assign_op: bool = False
    selected_rm_usernames: List[str] = Field(default_factory=list)
    selected_op_usernames: List[str] = Field(default_factory=list)
    per_employee_limit_rm: Optional[int] = Field(default=None, ge=1, le=10000)
    per_employee_limit_op: Optional[int] = Field(default=None, ge=1, le=10000)
    assign_unassigned_only: bool = Field(
        default=True,
        description="When true, only leads with rm_id/op_id NULL are updated for that role.",
    )
    interval_minutes: int = Field(default=5, ge=1, le=1440)

    @model_validator(mode="after")
    def _validate_assignees(self):
        if self.enabled:
            if not self.assign_rm and not self.assign_op:
                raise ValueError("Enable at least one of assign_rm or assign_op when auto-assign is on.")
            if self.assign_rm and not self.selected_rm_usernames:
                raise ValueError("selected_rm_usernames required when assign_rm is enabled.")
            if self.assign_op and not self.selected_op_usernames:
                raise ValueError("selected_op_usernames required when assign_op is enabled.")
        et = (self.filters.entity_types or []) + [self.entity_type]
        if not any(isinstance(x, str) and x.strip() for x in et):
            raise ValueError("filters.entity_types or entity_type must be set.")
        return self


class CRMUIStagePitchItem(CRMBaseSchema):
    stage: str
    pitch_type_code: str
    sort_order: int
    entity_type: Optional[str] = Field(
        default=None,
        description="NULL in DB = mapping applies to all entity types.",
    )


class CRMUIPitchStatusItem(CRMBaseSchema):
    call_status_code: str
    sort_order: int
    entity_type: Optional[str] = Field(
        default=None,
        description="NULL in DB = mapping applies to all entity types.",
    )


class CRMUIMappingsOut(CRMBaseSchema):
    entity_type: str
    stage_to_pitch: list[CRMUIStagePitchItem]
    pitch_to_statuses: dict[str, list[CRMUIPitchStatusItem]]


class CRMLeadStageItem(CRMBaseSchema):
    id: int
    code: str
    name: str
    sort_order: int


class CRMLeadStagesOut(CRMBaseSchema):
    entity_type: str
    stages: list[CRMLeadStageItem]
