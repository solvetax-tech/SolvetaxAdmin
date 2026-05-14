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
# Customer service follow-ups — stored on `customer_services`
# (followup_at, followup_status, followup_remarks, completed_at, missed_at)
# Router: app/follow_ups/customer_service_followups.py
# Prefix: /api/v1/customer-service-followups
# =========================================================


class CreateCustomerServiceFollowupRequest(FollowupBaseSchema):
    customer_service_id: int = Field(..., gt=0)
    followup_at: datetime
    remarks: Optional[str] = Field(None, max_length=2000)


class CreateCustomerServiceFollowupResponse(FollowupBaseSchema):
    id: int
    message: str


class UpdateCustomerServiceFollowupRequest(FollowupBaseSchema):
    followup_at: Optional[datetime] = None
    remarks: Optional[str] = Field(None, max_length=2000)
    status: Optional[Literal["PENDING", "COMPLETED", "MISSED"]] = Field(
        None,
        description="Maps to customer_services.followup_status",
    )


class UpdateCustomerServiceFollowupResponse(FollowupBaseSchema):
    id: int
    message: str


class CustomerServiceFollowupListItem(FollowupBaseSchema):
    """One scheduled follow-up row (customer_services with followup_at set) plus display fields."""

    id: int
    customer_service_id: int
    customer_id: int
    service_code: str
    service_status: str
    followup_at: datetime
    followup_status: Optional[str] = None
    remarks: Optional[str] = None
    completed_at: Optional[datetime] = None
    missed_at: Optional[datetime] = None
    provided_at: Optional[datetime] = None
    is_active: bool = True
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    service_name: Optional[str] = None
    rm_first_name: Optional[str] = None
    op_first_name: Optional[str] = None


class CustomerServiceFollowupListResponse(FollowupBaseSchema):
    data: list[CustomerServiceFollowupListItem]
    total: int
    limit: int
    offset: int
    request_id: str
