from datetime import datetime
from typing import Optional, Literal

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

    @model_validator(mode="after")
    def validate_has_any_field(self):
        if (
            self.stage is None
            and self.followup_at is None
            and self.rm_id is None
            and self.op_id is None
            and self.remarks is None
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


class CRMUIPitchStatusItem(CRMBaseSchema):
    call_status_code: str
    sort_order: int


class CRMUIMappingsOut(CRMBaseSchema):
    stage_to_pitch: list[CRMUIStagePitchItem]
    pitch_to_statuses: dict[str, list[CRMUIPitchStatusItem]]


class CRMLeadStageItem(CRMBaseSchema):
    id: int
    code: str
    name: str
    sort_order: int


class CRMLeadStagesOut(CRMBaseSchema):
    stages: list[CRMLeadStageItem]
