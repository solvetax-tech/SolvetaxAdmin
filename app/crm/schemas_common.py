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
    tag: str = Field(..., min_length=1, max_length=100)
    lead_source: str = Field(..., min_length=1, max_length=100)
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
        "lead_source",
        mode="before",
    )
    @classmethod
    def strip_nonempty_strings_upper_codes(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper() if s else None
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

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name_bulk_optional(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip()
            return s[:200] if s else None
        return v

    @model_validator(mode="after")
    def validate_mobile_digits(self):
        if not self.mobile.isdigit() or len(self.mobile) != 10:
            raise ValueError("mobile must be a 10-digit number")
        return self


class CRMBulkImportIn(CRMBaseSchema):
    rows: List[CRMBulkImportRowIn] = Field(..., min_length=1, max_length=5000)
    update_if_exists: bool = True
    validate_only: bool = False


class CRMBulkAssignExecuteIn(CRMBaseSchema):
    lead_ids: List[int] = Field(..., min_length=1, max_length=10000)
    selected_employee_ids: List[int] = Field(..., min_length=1, max_length=500)
    assignment_role: Literal["RM", "OP"]
    per_employee_limit: Optional[int] = Field(default=None, ge=1, le=10000)


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
