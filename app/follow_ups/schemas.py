from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# =========================================================
# Base schema (follow_ups package)
# =========================================================


class FollowupBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


# =========================================================
# GST filing manual followups — `customer_service_followups`
# Router: app/follow_ups/gst_filing_manual_followups.py
# Prefix: /api/v1/filing-followups
# =========================================================


class CreateFilingFollowupRequest(FollowupBaseSchema):
    customer_service_id: int = Field(..., gt=0)
    followup_at: datetime
    remarks: Optional[str] = Field(None, max_length=2000)
    assigned_to: Optional[int] = Field(
        None,
        gt=0,
        description="Ignored when JWT role is RM or OP; assigned_to is set to current emp_id.",
    )


class CreateFilingFollowupResponse(FollowupBaseSchema):
    id: int
    message: str


class UpdateFilingFollowupRequest(FollowupBaseSchema):
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = Field(None, max_length=2000)
    assigned_to: Optional[int] = Field(
        None,
        gt=0,
        description="If JWT role is RM or OP, API sets assigned_to to current emp_id.",
    )
    status: Optional[Literal["PENDING", "COMPLETED", "MISSED", "CANCELLED"]] = None


class UpdateFilingFollowupResponse(FollowupBaseSchema):
    id: int
    message: str
