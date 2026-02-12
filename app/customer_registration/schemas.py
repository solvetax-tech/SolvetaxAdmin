from pydantic import (BaseModel,EmailStr,Field,HttpUrl,field_validator,model_validator)
from typing import Optional, Annotated
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
# Customer Create Schema
# =========================================================

class CustomerIn(BaseSchema):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: Optional[EmailStr] = Field(None, max_length=255)
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    business_name: Optional[str] = Field(None, max_length=150)
    business_description: Optional[str] = Field(None, max_length=500)
    business_image_url: Optional[HttpUrl] = None
    business_type: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = Field(None, max_length=500)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referral_id: Optional[int] = Field(None, gt=0)

    # Normalize email
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    # Basic XSS sanitation
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
        if isinstance(v, str):
            return html.escape(v.strip())
        return v

    # Business rule validation
    @model_validator(mode="after")
    def validate_contact_info(self):
        if not self.email and not self.mobile:
            raise ValueError("Either email or mobile must be provided")
        return self


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
    op_id: Optional[int]
    referral_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None


# =========================================================
# Customer Edit Schema (Partial Update)
# =========================================================

class CustomerEditIn(BaseSchema):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = Field(None, max_length=255)
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    business_name: Optional[str] = Field(None, max_length=150)
    business_description: Optional[str] = Field(None, max_length=500)
    business_image_url: Optional[HttpUrl] = None
    business_type: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = Field(None, max_length=500)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referral_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    # -----------------------------------------------------
    # Normalize email
    # -----------------------------------------------------
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    # -----------------------------------------------------
    # Basic XSS sanitation
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
        if isinstance(v, str):
            return html.escape(v.strip())
        return v

    # -----------------------------------------------------
    # Ensure at least one field is provided for update
    # -----------------------------------------------------
    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if not any(value is not None for value in self.__dict__.values()):
            raise ValueError("At least one field must be provided for update")
        return self
