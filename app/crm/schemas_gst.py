"""Pydantic schemas for GST CRM lead routes (admin edit, call / follow-up payloads)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from app.crm.schemas_common import CRMBaseSchema


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
    complete_open_followup: bool = Field(
        default=False,
        description="When true, marks the lead's open follow-up (PENDING/MISSED) as COMPLETED.",
    )

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
