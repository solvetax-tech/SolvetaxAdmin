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
    business_name: Optional[str] = Field(None, max_length=200)
    business_description: Optional[str] = None
    business_image_url: Optional[str] = None
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
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
    referral_id: Optional[int] = Field(None, gt=0)

    # -----------------------------------------------------
    # NEW SERVICE COLUMNS (DB ALIGNED)
    # -----------------------------------------------------

    service_required: List[str] = Field(default_factory=list)
    service_provided: List[str] = Field(default_factory=list)
    tag: Optional[str] = Field(None, max_length=100)
    lead_source: Optional[str] = Field(
        None,
        max_length=120,
        description="Stored on crm_leads when CRM sync runs (e.g. WEBSITE, PAID_GOOGLE, or UTM-derived code).",
    )

    utm_source: Optional[str] = Field(None, max_length=120)
    utm_medium: Optional[str] = Field(None, max_length=120)
    utm_campaign: Optional[str] = Field(None, max_length=200)
    utm_content: Optional[str] = Field(None, max_length=200)
    capture_page_path: Optional[str] = Field(None, max_length=1024)
    capture_page_url: Optional[str] = None
    capture_page_query: Optional[str] = None
    capture_referrer_url: Optional[str] = None
    platform: Optional[str] = Field(None, max_length=20)
    device_type: Optional[str] = Field(None, max_length=20)
    device_model: Optional[str] = Field(None, max_length=200)
    os_name: Optional[str] = Field(None, max_length=64)
    os_version: Optional[str] = Field(None, max_length=32)
    browser_name: Optional[str] = Field(None, max_length=64)
    browser_version: Optional[str] = Field(None, max_length=32)
    app_version: Optional[str] = Field(None, max_length=64)
    environment: Optional[str] = Field(None, max_length=32)
    release_tag: Optional[str] = Field(None, max_length=64)
    user_agent: Optional[str] = None
    viewport_width: Optional[int] = None
    viewport_height: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    capture_language: Optional[str] = Field(None, max_length=32, description="Browser language at submit.")
    timezone_offset_min: Optional[int] = None
    ingestion_source: Optional[str] = Field(None, max_length=40)

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
    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        return v.strip()

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

    @field_validator(
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "capture_language",
        "ingestion_source",
        mode="before",
    )
    @classmethod
    def normalize_upper_marketing_customer(cls, v):
        if isinstance(v, str):
            s = v.strip().upper()
            return s[:200] if s else None
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
    business_name: Optional[str]
    business_description: Optional[str]
    business_image_url: Optional[str]
    business_type: Optional[str]
    state: Optional[str]
    city: Optional[str]
    language: Optional[str]
    remark: Optional[str]
    rm_id: Optional[int]
    rm_name: Optional[str] = None
    op_id: Optional[int]
    op_name: Optional[str] = None
    referral_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None
    is_active: bool

    # -----------------------------------------------------
    # NEW SERVICE FIELDS
    # -----------------------------------------------------

    service_required: List[str] = []
    service_provided: List[str] = []


# =========================================================
# Customer Edit Schema (Safe PATCH + Services Support)
# =========================================================

class CustomerEditIn(BaseSchema):
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    email: Optional[EmailStr] = Field(None, max_length=150)
    mobile: Optional[str] = Field(None, pattern=r"^\d{10}$")
    business_name: Optional[str] = Field(None, max_length=200)
    business_description: Optional[str] = None
    business_image_url: Optional[str] = None
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
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
    referral_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    # -----------------------------------------------------
    # NEW SERVICE FIELDS
    # -----------------------------------------------------

    service_required: Optional[List[str]] = Field(
        None,
        description=(
            "Service codes to add. Merged with existing customer.service_required: "
            "only new codes are appended; order preserved; duplicates ignored (case-insensitive). "
            "Does not create income_tax rows; use income-tax API for ITR."
        ),
    )
    service_provided: Optional[List[str]] = None


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
    @field_validator("mobile", mode="before")
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
        mode="before",
    )
    @classmethod
    def sanitize_strings(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v


    
    # -----------------------------------------------------
    # Ensure At Least One Field Provided
    # -----------------------------------------------------
    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self