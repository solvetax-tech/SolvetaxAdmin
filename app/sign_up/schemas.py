from pydantic import BaseModel, EmailStr, HttpUrl, constr, validator, root_validator, model_validator, Field
from typing import Optional, Dict, Annotated
import re
from datetime import datetime

class SignupRequest(BaseModel):
    first_name: Optional[Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)]] = Field(None, description="User's first name")
    last_name: Optional[Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)]] = Field(None, description="User's last name")
    email: EmailStr = Field(..., description="User's email address")
    username: Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=50)] = Field(..., description="Desired username")
    password: Annotated[str, constr(min_length=8)] = Field(..., description="User's password (must be strong)")
    phone_number: Optional[str] = Field(
        None, description="Optional phone number in E.164 format (e.g., +1234567890)"
    )
    role: Optional[str] = Field("customer", description="User role (default: customer)")

    @validator("phone_number")
    def validate_phone(cls, v):
        if v is not None:
            # E.164 format: +[country][number], e.g., +1234567890
            if not re.fullmatch(r"\+[1-9]\d{1,14}", v):
                raise ValueError("Invalid E.164 phone number format")
        return v

class SignupResponse(BaseModel):
    emp_id: int
    message: str

class ErrorResponse(BaseModel):
    error: str
    fields: Optional[Dict[str, str]] = None

class SendOTPRequest(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

    @model_validator(mode="after")
    def check_email_or_phone(self):
        if not self.email and not self.phone_number:
            raise ValueError('One of email or phone_number must be provided')
        return self

# Forgot password schemas

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ForgotPasswordVerify(BaseModel):
    email: EmailStr
    otp: Annotated[
        str,
        constr(min_length=4, max_length=4, pattern="^[0-9]{4}$")
    ]
    new_password: Annotated[
        str,
        constr(min_length=8)
    ]

class ForgotPasswordResponse(BaseModel):
    message: str

class EmployeeEditIn(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    employee_image_url: Optional[str] = None


# EmployeeOut schema for response
class EmployeeOut(BaseModel):
    emp_id: int
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    employee_image_url: Optional[str] = None
    message: Optional[str] = None