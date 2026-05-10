from datetime import datetime
from typing import Optional, Literal, List

from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator


class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class IncomeTaxIn(BaseSchema):
    client_name: str = Field(..., min_length=2, max_length=150)
    mobile: str = Field(..., pattern=r"^\d{10}$")
    language: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    remarks: Optional[str] = None
    pan_number: Optional[str] = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    password: Optional[str] = None
    financial_year: str = Field(..., pattern=r"^[0-9]{4}-[0-9]{2}$")
    filed_status: Literal["FILED", "NOT_FILED"] = "NOT_FILED"
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[str] = Field(None, max_length=100)
    email_id: Optional[EmailStr] = None
    source_of_income: Optional[str] = Field(None, max_length=100)
    refund_amount: Optional[float] = Field(None, ge=0)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
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
    capture_language: Optional[str] = Field(None, max_length=32, description="Browser language at submit (avoid clash with ITR language).")
    timezone_offset_min: Optional[int] = None
    ingestion_source: Optional[str] = Field(None, max_length=40)

    @field_validator("pan_number", mode="before")
    @classmethod
    def normalize_pan(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
            return v or None
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("filed_status", mode="before")
    @classmethod
    def normalize_filed_status(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("language", "state", "source_of_income", "referral_entity", mode="before")
    @classmethod
    def normalize_upper_fields(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

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
    def normalize_upper_marketing(cls, v):
        if isinstance(v, str):
            s = v.strip().upper()
            return s[:200] if s else None
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("password", "remarks", mode="before")
    @classmethod
    def normalize_optional_text(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("email_id", mode="before")
    @classmethod
    def normalize_email_optional(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            return v or None
        return v


class IncomeTaxEditIn(BaseSchema):
    client_name: Optional[str] = Field(None, min_length=2, max_length=150)
    mobile: Optional[str] = Field(None, pattern=r"^\d{10}$")
    language: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=100)
    priority: Optional[Literal["LOW", "NORMAL", "HIGH"]] = None
    remarks: Optional[str] = None
    pan_number: Optional[str] = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    password: Optional[str] = None
    financial_year: Optional[str] = Field(None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    filed_status: Optional[Literal["FILED", "NOT_FILED"]] = None
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[str] = Field(None, max_length=100)
    email_id: Optional[EmailStr] = None
    source_of_income: Optional[str] = Field(None, max_length=100)
    refund_amount: Optional[float] = Field(None, ge=0)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    @field_validator("pan_number", mode="before")
    @classmethod
    def normalize_pan(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("language", "state", "source_of_income", "referral_entity", mode="before")
    @classmethod
    def normalize_upper_fields(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @model_validator(mode="after")
    def validate_any_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self


class IncomeTaxDocumentIn(BaseSchema):
    income_tax_id: int = Field(..., gt=0)
    document_type: str = Field(..., min_length=2, max_length=50)
    document_url: str = Field(..., min_length=5, max_length=1000)
    remarks: Optional[str] = None
    verified: bool = False

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class IncomeTaxDocumentEditIn(BaseSchema):
    document_type: Optional[str] = Field(None, min_length=2, max_length=50)
    document_url: Optional[str] = Field(None, min_length=5, max_length=1000)
    remarks: Optional[str] = None
    verified: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @model_validator(mode="after")
    def validate_any_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self
