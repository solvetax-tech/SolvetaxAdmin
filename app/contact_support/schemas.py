from typing import Optional

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
    service_required: Optional[str] = Field(None, max_length=150)
    referal_phone_number: Optional[str] = Field(None, pattern=r"^\d{10}$")
    your_message: Optional[str] = None

    @field_validator("your_name", "service_required", "your_message", mode="before")
    @classmethod
    def normalize_text(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("phone_number", "referal_phone_number", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class ContactSupportEditIn(BaseSchema):
    your_name: Optional[str] = Field(None, min_length=2, max_length=150)
    phone_number: Optional[str] = Field(None, pattern=r"^\d{10}$")
    email_address: Optional[EmailStr] = None
    service_required: Optional[str] = Field(None, max_length=150)
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)
    referal_phone_number: Optional[str] = Field(None, pattern=r"^\d{10}$")
    your_message: Optional[str] = None
    is_service_provided: Optional[bool] = None
    is_resolved: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("your_name", "service_required", "your_message", mode="before")
    @classmethod
    def normalize_text(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("phone_number", "referal_phone_number", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def validate_any_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self
