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


# =========================================================
# Customer Create Schema (DB-Aligned + Services Array)
# =========================================================

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
    remark: Optional[str] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referral_id: Optional[int] = Field(None, gt=0)

    # -----------------------------------------------------
    # NEW SERVICE COLUMNS (DB ALIGNED)
    # -----------------------------------------------------

    service_required: List[str] = Field(default_factory=list)
    service_provided: List[str] = Field(default_factory=list)

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
        "remark",
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
    remark: Optional[str] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referral_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    # -----------------------------------------------------
    # NEW SERVICE FIELDS
    # -----------------------------------------------------

    service_required: Optional[List[str]] = None
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