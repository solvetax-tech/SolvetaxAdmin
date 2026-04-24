from datetime import datetime
from typing import Optional, Literal, List

from pydantic import BaseModel, Field, field_validator, model_validator


class CRMBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class CRMLeadEditIn(CRMBaseSchema):
    stage: Optional[
        Literal[
            "FRESH_LEAD",
            "PENDING_REGISTRATION_DATA",
            "FOLLOW_UP",
            "INTERESTED",
            "GST_REGISTRATION_DONE",
            "SCHEDULED_PAYMENTS",
            "SUBSCRIBED",
            "NOT_INTERESTED",
        ]
    ] = None
    followup_at: Optional[datetime] = None
    rm_id: Optional[int] = Field(default=None, gt=0)
    op_id: Optional[int] = Field(default=None, gt=0)
    remarks: Optional[str] = Field(default=None, max_length=2000)
    lead_type: Optional[str] = Field(default=None, max_length=50)
    tag: Optional[str] = Field(default=None, max_length=100)
    lead_source: Optional[str] = Field(default=None, max_length=100)

    @field_validator("lead_type", mode="before")
    @classmethod
    def normalize_lead_type(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper() if s else None
        return v

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    @field_validator("lead_source", mode="before")
    @classmethod
    def normalize_lead_source(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper() if s else None
        return v

    @model_validator(mode="after")
    def validate_has_any_field(self):
        if (
            self.stage is None
            and self.followup_at is None
            and self.rm_id is None
            and self.op_id is None
            and self.remarks is None
            and self.lead_type is None
            and self.tag is None
            and self.lead_source is None
        ):
            raise ValueError("At least one field must be provided.")
        return self


class CRMCallUpdateIn(CRMBaseSchema):
    call_type_code: str = Field(..., max_length=40)
    call_status_code: str = Field(..., max_length=50)
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("call_type_code", "call_status_code", mode="before")
    @classmethod
    def normalize_codes(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class CRMFollowupStatusUpdateIn(CRMBaseSchema):
    follow_up_status: Literal["PENDING", "COMPLETED", "MISSED"]
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = Field(default=None, max_length=2000)


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


class CRMBulkImportRowIn(CRMBaseSchema):
    mobile: str = Field(..., min_length=10, max_length=20)
    stage: Optional[str] = Field(default=None, max_length=40)
    followup_at: Optional[datetime] = None
    rm_id: Optional[int] = Field(default=None, gt=0)
    op_id: Optional[int] = Field(default=None, gt=0)
    remarks: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = True
    follow_up_status: Optional[Literal["PENDING", "COMPLETED", "MISSED"]] = "PENDING"
    entity_type: Optional[str] = Field(default=None, max_length=64)
    entity_id: Optional[int] = Field(default=None, gt=0)
    lead_type: Optional[str] = Field(default=None, max_length=50)
    tag: Optional[str] = Field(default=None, max_length=100)
    lead_source: Optional[str] = Field(default=None, max_length=100)

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("stage", "entity_type", "lead_type", "lead_source", mode="before")
    @classmethod
    def normalize_upper_codes(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper() if s else None
        return v

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    @model_validator(mode="after")
    def validate_entity_pair(self):
        # Keep both optional and independent at schema level.
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
