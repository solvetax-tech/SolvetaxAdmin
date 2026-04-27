from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ITR_STAGE_CODE = Literal[
    "FRESH_LEAD",
    "PENDING_ITR_DATA",
    "FOLLOW_UP",
    "INTERESTED",
    "ITR_DONE",
    "SCHEDULED_PAYMENTS",
    "SUBSCRIBED",
    "NOT_INTERESTED",
]


class CRMBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


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


class CRMLeadEditIn(CRMBaseSchema):
    stage: Optional[
        Literal[
            "FRESH_LEAD",
            "PENDING_ITR_DATA",
            "FOLLOW_UP",
            "INTERESTED",
            "ITR_DONE",
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


class CRMFollowupStatusUpdateIn(CRMBaseSchema):
    follow_up_status: Literal["PENDING", "COMPLETED", "MISSED"]
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = Field(default=None, max_length=2000)
