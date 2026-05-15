"""Pydantic schemas for customer **service** rows (`customer_services`). Follow-ups stay out of this module."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CustomerServiceBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class CustomerServiceBulkAssignExecuteIn(CustomerServiceBaseSchema):
    """Round-robin assignment of RM or OP on selected `customer_services` rows (ADMIN only, CRM parity)."""

    customer_service_ids: List[int] = Field(..., min_length=1, max_length=10000)
    selected_employee_ids: List[int] = Field(..., min_length=1, max_length=500)
    assignment_role: Literal["RM", "OP"] = Field(
        ...,
        description=(
            "RM updates rm_id; OP updates op_id. "
            "Employee pools: GET /api/v1/employees/active-rm and /api/v1/employees/active-op."
        ),
        examples=["RM", "OP"],
    )
    per_employee_limit: Optional[int] = Field(default=None, ge=1, le=10000)

    @field_validator("assignment_role", mode="before")
    @classmethod
    def normalize_assignment_role(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class CustomerServicePatchIn(CustomerServiceBaseSchema):
    """Service-level fields only (no follow-up columns)."""

    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    service_status: Optional[Literal["PENDING", "PROVIDED"]] = None
    is_active: Optional[bool] = None


class CustomerServiceStatusPatchIn(CustomerServiceBaseSchema):
    """Update only `service_status` (staff with EMPLOYEE WRITE; visibility rules apply)."""

    service_status: Literal["PENDING", "PROVIDED"]

    @field_validator("service_status", mode="before")
    @classmethod
    def upper_service_status(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class CustomerServiceDetailOut(CustomerServiceBaseSchema):
    """Subset of row + joined labels for GET detail."""

    id: int
    customer_id: int
    service_code: str
    service_status: str
    provided_at: Optional[datetime] = None
    is_active: bool
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    service_name: Optional[str] = None
    rm_first_name: Optional[str] = None
    op_first_name: Optional[str] = None


class CustomerServiceListItemOut(CustomerServiceBaseSchema):
    id: int
    customer_id: int
    service_code: str
    service_status: str
    provided_at: Optional[datetime] = None
    is_active: bool
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    service_name: Optional[str] = None

    @field_validator("service_code", mode="before")
    @classmethod
    def upper_service_code(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class CustomerServiceBulkAssignCandidatesOut(CustomerServiceBaseSchema):
    items: List[dict]
    total: int
    limit: int
    offset: int


# --- service_config dropdown (migrated from customer_registration/service_config) ---


class ServiceConfigDropdownRow(CustomerServiceBaseSchema):
    id: int
    service_category: Optional[str] = None
    service_code: str
    service_name: Optional[str] = None
    description: Optional[str] = None


class ServiceConfigDropdownResponse(CustomerServiceBaseSchema):
    data: List[ServiceConfigDropdownRow]
    count: int
    request_id: str
