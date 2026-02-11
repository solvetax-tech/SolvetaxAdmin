from pydantic import BaseModel, EmailStr, validator, Field, constr
from typing import Optional, Annotated
from datetime import datetime
import re

class CustomerIn(BaseModel):
    full_name: str = Field(..., description="Customer full name")
    email: Optional[EmailStr] = Field(None, description="Customer email address")
    mobile: Annotated[str, Field(pattern=r'^\d{10}$')] = Field(None, description="Phone number must be exactly 10 digits")
    business_name: Optional[str] = Field(None, description="Business name")
    business_description: Optional[str] = Field(None, description="Business description")
    business_image_url: Optional[str] = Field(None, description="Business image URL")
    business_type: Optional[str] = Field(None, description="Business type")
    state: Optional[str] = Field(None, description="State")
    city: Optional[str] = Field(None, description="City")
    remark: Optional[str] = Field(None, description="Remark")
    rm_id: Optional[int] = Field(None, description="RM ID")
    op_id: Optional[int] = Field(None, description="OP ID")
    referral_id: Optional[int] = Field(None, description="Referral ID")

class CustomerEditIn(BaseModel):
    full_name: Optional[str] = Field(None, description="Customer full name")
    email: Optional[EmailStr] = Field(None, description="Customer email address")
    mobile: Annotated[str, Field(pattern=r'^\d{10}$')] = Field(None, description="Phone number must be exactly 10 digits")
    business_name: Optional[str] = Field(None, description="Business name")
    business_description: Optional[str] = Field(None, description="Business description")
    business_image_url: Optional[str] = Field(None, description="Business image URL")
    business_type: Optional[str] = Field(None, description="Business type")
    state: Optional[str] = Field(None, description="State")
    city: Optional[str] = Field(None, description="City")
    remark: Optional[str] = Field(None, description="Remark")
    rm_id: Optional[int] = Field(None, description="RM ID")
    op_id: Optional[int] = Field(None, description="OP ID")
    referral_id: Optional[int] = Field(None, description="Referral ID")
    is_active: Optional[bool] = Field(None, description="Is user active")


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
    referral_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None
