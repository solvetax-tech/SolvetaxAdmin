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
    business_image_url: Optional[HttpUrl] = None
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referral_id: Optional[int] = Field(None, gt=0)

    services: List[str] = Field(default_factory=list)

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

    # -----------------------------------------------------
    # Normalize & Deduplicate Services
    # -----------------------------------------------------
    @field_validator("services", mode="before")
    @classmethod
    def normalize_services(cls, v):
        if v is None:
            return []

        if not isinstance(v, list):
            raise ValueError("services must be a list of strings")

        cleaned = []
        for service in v:
            if not isinstance(service, str):
                raise ValueError("Each service must be a string")
            s = service.strip()
            if s:
                cleaned.append(s)

        return list(dict.fromkeys(cleaned))
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
    is_active: bool

# =========================================================
# Customer Edit Schema (Safe PATCH + Services Support)
# =========================================================

class CustomerEditIn(BaseSchema):
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    email: Optional[EmailStr] = Field(None, max_length=150)
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    business_name: Optional[str] = Field(None, max_length=200)
    business_description: Optional[str] = None
    business_image_url: Optional[HttpUrl] = None
    business_type: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    remark: Optional[str] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referral_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    services: Optional[List[str]] = None

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
        return v.strip() if v else v

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

    # -----------------------------------------------------
    # Normalize Services
    # -----------------------------------------------------
    @field_validator("services", mode="before")
    @classmethod
    def normalize_services(cls, v):
        if v is None:
            return None

        if not isinstance(v, list):
            raise ValueError("services must be a list of strings")

        cleaned = []
        for service in v:
            if not isinstance(service, str):
                raise ValueError("Each service must be a string")
            s = service.strip()
            if s:
                cleaned.append(s)

        return list(dict.fromkeys(cleaned))

    # -----------------------------------------------------
    # Ensure at least one field provided
    # -----------------------------------------------------
    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self