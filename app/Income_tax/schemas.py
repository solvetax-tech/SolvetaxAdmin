from typing import Optional, Literal, List, Any

from pydantic import AliasChoices, BaseModel, Field, EmailStr, field_validator, model_validator

from app.Income_tax.income_tax_helpers import (
    normalize_financial_year_list,
    normalize_source_of_income_list,
)


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
    pan_number: Optional[str] = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    financial_year: List[str] = Field(..., min_length=1)
    email_id: Optional[EmailStr] = None
    state: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
    source_of_income: Optional[List[str]] = None
    filed_status: Literal["FILED", "NOT_FILED"] = "NOT_FILED"
    refund_amount: Optional[float] = Field(None, ge=0)
    referral_phone_number: Optional[str] = Field(None, pattern=r"^\d{10}$")
    remarks: Optional[str] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)

    @field_validator("financial_year", mode="before")
    @classmethod
    def validate_financial_year(cls, v: Any) -> List[str]:
        try:
            return normalize_financial_year_list(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("source_of_income", mode="before")
    @classmethod
    def validate_source_of_income(cls, v: Any) -> Optional[List[str]]:
        try:
            return normalize_source_of_income_list(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("pan_number", mode="before")
    @classmethod
    def normalize_pan(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
            return v or None
        return v

    @field_validator("priority", "filed_status", mode="before")
    @classmethod
    def normalize_upper_enum(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("language", "state", mode="before")
    @classmethod
    def normalize_upper_fields(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("mobile", "referral_phone_number", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def normalize_remarks(cls, v):
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


class IncomeTaxLeadCreateIn(BaseSchema):
    """
    ITR intake: creates income_tax and links CRM.

    - With ``crm_lead_id``: creates income_tax only and sets that lead's ``entity_id``.
    - Without ``crm_lead_id``: creates income_tax + new crm_leads row (standalone intake).

    Push from CRM: ``{ "crm_lead_id": 45 }`` (aliases ``lead_id``, ``id``). Extra CRM fields are ignored.
    """

    model_config = {
        **BaseSchema.model_config,
        "extra": "ignore",
    }

    crm_lead_id: Optional[int] = Field(
        None,
        gt=0,
        validation_alias=AliasChoices("crm_lead_id", "lead_id", "id"),
        description="Existing CRM ITR lead to link (Push from CRM table).",
    )
    mobile: Optional[str] = Field(None, pattern=r"^\d{10}$")
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    email: Optional[EmailStr] = None
    preferred_language: Optional[str] = Field(None, max_length=50)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    remarks: Optional[str] = None
    ay: Optional[str] = Field(
        None,
        max_length=20,
        description="Assessment year for CRM (e.g. 2024-25). Defaults from financial year when omitted.",
    )

    @field_validator("ay", mode="before")
    @classmethod
    def normalize_ay(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    @model_validator(mode="after")
    def require_identity_fields(self):
        if self.crm_lead_id is None:
            if not self.mobile:
                raise ValueError("mobile is required when crm_lead_id is not provided")
            if not self.full_name:
                raise ValueError("full_name is required when crm_lead_id is not provided")
        return self

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("preferred_language", mode="before")
    @classmethod
    def normalize_preferred_language(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip().lower()
            if not v or v in {"string", "null", "undefined", "none", "na", "n/a"}:
                return None
            if "@" not in v:
                return None
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def normalize_remarks(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class IncomeTaxEditIn(BaseSchema):
    """Edit payload. ``year`` is create-only and cannot be sent or updated here."""

    client_name: Optional[str] = Field(None, min_length=2, max_length=150)
    mobile: Optional[str] = Field(None, pattern=r"^\d{10}$")
    pan_number: Optional[str] = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    priority: Optional[Literal["LOW", "NORMAL", "HIGH"]] = None
    financial_year: Optional[List[str]] = Field(None, min_length=1)
    email_id: Optional[EmailStr] = None
    state: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
    source_of_income: Optional[List[str]] = None
    filed_status: Optional[Literal["FILED", "NOT_FILED"]] = None
    refund_amount: Optional[float] = Field(None, ge=0)
    referral_phone_number: Optional[str] = Field(None, pattern=r"^\d{10}$")
    remarks: Optional[str] = None
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    @field_validator("financial_year", mode="before")
    @classmethod
    def validate_financial_year(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        try:
            return normalize_financial_year_list(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("source_of_income", mode="before")
    @classmethod
    def validate_source_of_income(cls, v: Any) -> Optional[List[str]]:
        try:
            return normalize_source_of_income_list(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("pan_number", mode="before")
    @classmethod
    def normalize_pan(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("priority", "filed_status", mode="before")
    @classmethod
    def normalize_upper_enum(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("language", "state", mode="before")
    @classmethod
    def normalize_upper_fields(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("mobile", "referral_phone_number", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def normalize_remarks(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def validate_any_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self
