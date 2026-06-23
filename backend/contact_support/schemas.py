from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class ContactSupportIn(BaseSchema):
    your_name: str = Field(..., min_length=2, max_length=150)
    phone_number: str = Field(..., pattern=r"^\d{10}$")
    email_address: Optional[EmailStr] = None
    service_required: Optional[List[str]] = Field(default=None, max_length=100)
    referal_phone_number: Optional[List[str]] = Field(default=None, max_length=100)
    your_message: Optional[str] = None

    @field_validator("your_name", "your_message", mode="before")
    @classmethod
    def normalize_text(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("service_required", mode="before")
    @classmethod
    def normalize_service_required(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("service_required must be a list of strings")
        out = []
        seen = set()
        for item in v:
            if item is None:
                continue
            s = str(item).strip().upper()
            if not s:
                continue
            if len(s) > 150:
                raise ValueError("Each service_required item must be <= 150 characters")
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out or None

    @field_validator("referal_phone_number", mode="before")
    @classmethod
    def normalize_referral_phones(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("referal_phone_number must be a list of strings")
        out = []
        seen = set()
        for item in v:
            if item is None:
                continue
            s = str(item).strip()
            if not s:
                continue
            if not s.isdigit() or len(s) != 10:
                raise ValueError("Each referal_phone_number item must be a 10-digit number")
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out or None


class ContactSupportEditIn(BaseSchema):
    your_name: Optional[str] = Field(None, min_length=2, max_length=150)
    phone_number: Optional[str] = Field(None, pattern=r"^\d{10}$")
    email_address: Optional[EmailStr] = None
    service_required: Optional[List[str]] = Field(default=None, max_length=100)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referal_phone_number: Optional[List[str]] = Field(default=None, max_length=100)
    your_message: Optional[str] = None
    is_service_provided: Optional[bool] = None
    is_resolved: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("your_name", "your_message", mode="before")
    @classmethod
    def normalize_text(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("service_required", mode="before")
    @classmethod
    def normalize_service_required(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("service_required must be a list of strings")
        out = []
        seen = set()
        for item in v:
            if item is None:
                continue
            s = str(item).strip().upper()
            if not s:
                continue
            if len(s) > 150:
                raise ValueError("Each service_required item must be <= 150 characters")
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out or None

    @field_validator("referal_phone_number", mode="before")
    @classmethod
    def normalize_referral_phones(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("referal_phone_number must be a list of strings")
        out = []
        seen = set()
        for item in v:
            if item is None:
                continue
            s = str(item).strip()
            if not s:
                continue
            if not s.isdigit() or len(s) != 10:
                raise ValueError("Each referal_phone_number item must be a 10-digit number")
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out or None

    @model_validator(mode="after")
    def validate_any_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self
