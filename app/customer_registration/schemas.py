from pydantic import (BaseModel,EmailStr,Field,HttpUrl,field_validator,model_validator)
from typing import Optional, Annotated, List
from datetime import datetime
import re
import html

# =========================================================
# Base Schema (Global Config for all schemas)
# =========================================================

class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",              # Reject unknown fields
        "str_strip_whitespace": True,   # Auto strip all strings
        "validate_assignment": True,    # Validate when updating fields
        "from_attributes": True,        # Allows ORM objects (future safe)
    }

class CustomerIn(BaseSchema):
    full_name: str = Field(..., min_length=2, max_length=150)
    email: Optional[EmailStr] = Field(None, max_length=150)
    mobile: Annotated[str, Field(pattern=r"^\d{10}$")]

    service_required: List[str] = Field(default_factory=list)
    language: Optional[str] = Field(None, max_length=50)

    business_name: Optional[str] = Field(None, max_length=200)
    business_description: Optional[str] = None
    business_image_url: Optional[str] = None
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = None
    rm_id: Optional[int] = Field(
        None,
        gt=0,
        description="Relationship manager emp_id. Omitted + JWT role RM → API sets to current emp_id.",
    )
    op_id: Optional[int] = Field(
        None,
        gt=0,
        description="Operations emp_id. Omitted + JWT role OP → API sets to current emp_id.",
    )
    referral_phone_number: Optional[str] = Field(
        None,
        pattern=r"^\d{10}$",
        description="10-digit mobile of the referring party.",
    )

    lead_source: Optional[str] = Field(
        None,
        max_length=120,
        description="Lead source on customers (e.g. WEBSITE, PAID_GOOGLE).",
    )
    tag: Optional[str] = Field(None, max_length=100)
    lead_type: Optional[str] = Field(
        None,
        max_length=100,
        description="Lead classification (e.g. INBOUND, REFERRAL).",
    )

    # -----------------------------------------------------
    # Normalize email
    # -----------------------------------------------------
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return v.strip().lower() if v else v

    # -----------------------------------------------------
    # Normalize mobile
    # -----------------------------------------------------
    @field_validator("mobile", "referral_phone_number", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if v is None:
            return None
        return str(v).strip()

    # -----------------------------------------------------
    # Sanitize text fields
    # -----------------------------------------------------
    @field_validator(
        "full_name",
        "business_name",
        "business_description",
        "business_type",
        "state",
        "city",
        "language",
        "remark",
        "tag",
        mode="before",
    )
    @classmethod
    def sanitize_strings(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v

    @field_validator("lead_source", mode="before")
    @classmethod
    def normalize_lead_source(cls, v):
        if isinstance(v, str):
            s = v.strip().upper()
            return s[:120] if s else None
        return v

    @field_validator("lead_type", mode="before")
    @classmethod
    def normalize_lead_type(cls, v):
        if isinstance(v, str):
            s = v.strip().upper()
            return s[:100] if s else None
        return v


# =========================================================
# Business description AI (POST body → configured agent URL)
# =========================================================


class BusinessDescriptionGenerateIn(BaseSchema):
    full_name: str = Field(..., min_length=2, max_length=150)
    business_name: Optional[str] = Field(None, max_length=200)
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = None
    business_url: Optional[str] = Field(
        None,
        max_length=500,
        description="Website or public business URL passed through to the AI endpoint.",
    )

    @field_validator(
        "full_name",
        "business_name",
        "business_type",
        "state",
        "city",
        "remark",
        "business_url",
        mode="before",
    )
    @classmethod
    def sanitize_strings(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v


# =========================================================
# Customer Response Schema
# =========================================================

class CustomerOut(BaseSchema):
    customer_id: int
    full_name: str
    email: Optional[str]
    mobile: Optional[str]
    service_required: List[str] = []
    language: Optional[str]
    business_name: Optional[str]
    business_description: Optional[str]
    business_image_url: Optional[str]
    business_type: Optional[str]
    state: Optional[str]
    city: Optional[str]
    remark: Optional[str]
    rm_id: Optional[int]
    rm_name: Optional[str] = None
    op_id: Optional[int]
    op_name: Optional[str] = None
    is_active: bool
    referral_phone_number: Optional[str] = None
    lead_source: Optional[str] = None
    tag: Optional[str] = None
    lead_type: Optional[str] = None

    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None


# =========================================================
# Customer Edit Schema (Safe PATCH + Services Support)
# =========================================================

class CustomerEditIn(BaseSchema):
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    email: Optional[EmailStr] = Field(None, max_length=150)
    mobile: Optional[str] = Field(None, pattern=r"^\d{10}$")
    service_required: Optional[List[str]] = Field(
        None,
        description=(
            "Service codes to add. Merged with existing customer.service_required: "
            "only new codes are appended; order preserved; duplicates ignored (case-insensitive). "
            "Does not create income_tax rows; use income-tax API for ITR."
        ),
    )
    language: Optional[str] = Field(None, max_length=50)
    business_name: Optional[str] = Field(None, max_length=200)
    business_description: Optional[str] = None
    business_image_url: Optional[str] = None
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = None
    rm_id: Optional[int] = Field(
        None,
        gt=0,
        description="When set, updates RM emp_id; omit to leave unchanged (see edit_customer handler).",
    )
    op_id: Optional[int] = Field(
        None,
        gt=0,
        description="When set, updates OP emp_id; omit to leave unchanged (see edit_customer handler).",
    )
    referral_phone_number: Optional[str] = Field(
        None,
        pattern=r"^\d{10}$",
        description="10-digit mobile of the referring party.",
    )
    lead_source: Optional[str] = Field(None, max_length=120)
    tag: Optional[str] = Field(None, max_length=100)
    lead_type: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None

    # -----------------------------------------------------
    # Normalize Email
    # -----------------------------------------------------
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    # -----------------------------------------------------
    # Normalize Mobile (Safe for int or str input)
    # -----------------------------------------------------
    @field_validator("mobile", "referral_phone_number", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if v is None:
            return None
        return str(v).strip()

    # -----------------------------------------------------
    # Sanitize Text Fields
    # -----------------------------------------------------
    @field_validator(
        "full_name",
        "business_name",
        "business_description",
        "business_type",
        "state",
        "city",
        "language",
        "remark",
        "tag",
        mode="before",
    )
    @classmethod
    def sanitize_strings(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v

    @field_validator("lead_source", mode="before")
    @classmethod
    def normalize_lead_source_edit(cls, v):
        if isinstance(v, str):
            s = v.strip().upper()
            return s[:120] if s else None
        return v

    @field_validator("lead_type", mode="before")
    @classmethod
    def normalize_lead_type_edit(cls, v):
        if isinstance(v, str):
            s = v.strip().upper()
            return s[:100] if s else None
        return v

    # -----------------------------------------------------
    # Ensure At Least One Field Provided
    # -----------------------------------------------------
    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self