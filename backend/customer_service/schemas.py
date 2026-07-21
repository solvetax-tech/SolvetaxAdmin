"""Pydantic schemas for customer **service** rows (`customer_services`). Follow-ups stay out of this module."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.common.status_constants import ServiceStatusLiteral


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


class CustomerServiceCreateIn(CustomerServiceBaseSchema):
    """Create one customer_services row directly.

    The customer is attached one of three ways:

      1. `customer_id` -- attach to an existing customer.
      2. `full_name` + `mobile` (+ optional `business_name`) -- create that
         customer and attach the service to it, in one transaction. Contact
         details are NOT service columns; they only exist on a customers row,
         so this is the only way a service can carry a name/phone.
      3. neither -- an unattached service (customer_id is nullable, see
         db/migrations/2026-07-17_customer_services_nullable_customer_id.sql).
         It has no name or phone anywhere until it is attached.

    1 and 2 are mutually exclusive. Lengths mirror CustomerIn / the customers
    columns; the cross-field rules live in the endpoint so each failure comes
    back tagged with the field the form should show it on.
    """

    service_code: str = Field(..., min_length=1, max_length=50)
    customer_id: Optional[int] = Field(None, gt=0)
    service_status: Optional[ServiceStatusLiteral] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    followup_at: Optional[datetime] = None
    followup_remarks: Optional[str] = None
    is_active: Optional[bool] = None

    # --- new-customer fields (omit when customer_id is set) ---
    full_name: Optional[str] = Field(
        None, max_length=150, description="New customer's name. Requires mobile; rejects customer_id."
    )
    mobile: Optional[str] = Field(
        None, max_length=15, description="New customer's 10-digit mobile. Requires full_name; rejects customer_id."
    )
    business_name: Optional[str] = Field(
        None, max_length=200, description="New customer's business name. Optional."
    )

    @field_validator("mobile", mode="before")
    @classmethod
    def strip_mobile_separators(cls, v):
        # "98765 43210" and "98765-43210" are the same number. Reduce to digits
        # so the endpoint's 10-digit rule judges the number, not the formatting.
        if isinstance(v, str):
            digits = "".join(ch for ch in v if ch.isdigit())
            return digits or None
        return v

    @field_validator("service_code", mode="before")
    @classmethod
    def normalise_service_code(cls, v):
        # Stored as-typed, but matched against service_config with
        # upper(btrim(...)) -- normalise on the way in so the unique index
        # (customer_id, service_code) cannot be defeated by case/whitespace.
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("service_status", mode="before")
    @classmethod
    def upper_service_status(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("customer_id", "rm_id", "op_id", mode="before")
    @classmethod
    def empty_int_to_none(cls, v):
        # Empty form fields ("") stay optional instead of failing int parsing.
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class CustomerServiceCreateOut(CustomerServiceBaseSchema):
    id: int
    customer_id: Optional[int] = None
    service_code: str
    service_status: str
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    followup_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime


class CustomerServicePatchIn(CustomerServiceBaseSchema):
    """Service-level fields only (no follow-up columns)."""

    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    service_status: Optional[ServiceStatusLiteral] = None
    is_active: Optional[bool] = None


class CustomerServiceStatusPatchIn(CustomerServiceBaseSchema):
    """Update only `service_status` (staff with EMPLOYEE WRITE; visibility rules apply)."""

    service_status: ServiceStatusLiteral

    @field_validator("service_status", mode="before")
    @classmethod
    def upper_service_status(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class CustomerServiceDetailOut(CustomerServiceBaseSchema):
    """Subset of row + joined labels for GET detail."""

    id: int
    # Nullable since 2026-07-17: a service can exist before it is attached to a
    # customer, in which case the customers LEFT JOIN yields NULL labels too.
    customer_id: Optional[int] = None
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
    business_name: Optional[str] = None
    service_name: Optional[str] = None
    rm_first_name: Optional[str] = None
    op_first_name: Optional[str] = None


class CustomerServiceListItemOut(CustomerServiceBaseSchema):
    id: int
    # Nullable since 2026-07-17 -- see CustomerServiceDetailOut.
    customer_id: Optional[int] = None
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
    business_name: Optional[str] = None
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
    match_mode: Optional[str] = None
    filter_mode: Optional[str] = None
    null_fields: Optional[List[str]] = None
    not_null_fields: Optional[List[str]] = None


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


class CustomerServiceProgressRowOut(CustomerServiceBaseSchema):
    customer_id: int
    customer_name: Optional[str] = None
    business_name: Optional[str] = None
    phone_number: Optional[str] = None
    required_count: int = 0
    provided_count: int = 0
    pending_count: int = 0
    completion_percent: int = 0
    overall_status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"] = "NOT_STARTED"
    required_services: List[str] = Field(default_factory=list)
    provided_services: List[str] = Field(default_factory=list)
    pending_services: List[str] = Field(default_factory=list)
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    rm_username: Optional[str] = None
    op_username: Optional[str] = None
    latest_service_at: Optional[datetime] = None


class CustomerServiceProgressSummaryOut(CustomerServiceBaseSchema):
    tracked_customers: int = 0
    completed: int = 0
    in_progress: int = 0
    not_started: int = 0


class CustomerServiceProgressTrackerOut(CustomerServiceBaseSchema):
    summary: CustomerServiceProgressSummaryOut
    rows: List[CustomerServiceProgressRowOut]
    count: int
    total_count: int
    limit: int
    offset: int
