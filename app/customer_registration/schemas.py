from pydantic import BaseModel, EmailStr, validator
from .validators import validate_mobile, validate_gstin, validate_pan, validate_aadhaar, validate_email
from typing import Optional
from datetime import datetime


class CustomerIn(BaseModel):
    full_name: str
    email: Optional[EmailStr] = None
    mobile: str
    business_name: Optional[str] = None
    business_description: Optional[str] = None
    business_image_url: Optional[str] = None
    business_type: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    remark: Optional[str] = None
    rm_id: Optional[int] = None
    op_id: Optional[int] = None

    @validator('mobile')
    def mobile_validator(cls, v):
        return validate_mobile(v)
    @validator('email')
    def email_validator(cls, v):
        return validate_email(v)


class CustomerEditIn(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    business_name: Optional[str] = None
    business_description: Optional[str] = None
    business_image_url: Optional[str] = None
    business_type: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    remark: Optional[str] = None
    rm_id: Optional[int] = None
    op_id: Optional[int] = None

    is_active: Optional[bool] = None

    @validator('mobile')
    def mobile_validator(cls, v):
        return validate_mobile(v)
    @validator('email')
    def email_validator(cls, v):
        return validate_email(v)


class CustomerOut(BaseModel):
    customer_id: int
    full_name: str
    email: Optional[str]
    mobile: str
    business_name: Optional[str]
    business_description: Optional[str]
    business_image_url: Optional[str]
    business_type: Optional[str]
    state: Optional[str]
    city: Optional[str]
    remark: Optional[str]
    rm_id: Optional[int] = None
    op_id: Optional[int] = None

    is_active: bool
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None
