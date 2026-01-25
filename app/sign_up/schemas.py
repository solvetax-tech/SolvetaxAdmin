from pydantic import BaseModel, EmailStr, HttpUrl, constr, validator, root_validator, model_validator, Field
from typing import Optional, Dict, Annotated
import re
from datetime import datetime

class SignupRequest(BaseModel):
    emp_id: Optional[int] = Field(None, description="Employee ID (auto-generated)")
    username: Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)] = Field(..., description="Desired username")
    email: EmailStr = Field(..., description="User's email address")
    password: Annotated[str, constr(min_length=8)] = Field(..., description="User's password (must be strong)")
    first_name: Optional[Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)]] = Field(None, description="User's first name")
    last_name: Optional[Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)]] = Field(None, description="User's last name")
    phone_number: Optional[str] = Field(None, description="Phone number with max length 20")
    role: Optional[str] = Field("SE", max_length=50, description="User role (default: SE)")
    is_active: Optional[bool] = Field(True, description="Is user active")
    manager_emp_id: Optional[int] = Field(None, description="Manager employee ID")

    @validator("phone_number")
    def validate_phone(cls, v):
        if v is not None:
            # Validate phone number has exactly 10 digits
            if not re.fullmatch(r"\d{10}", v):
                raise ValueError("Phone number must be exactly 10 digits")
        return v

class SignupResponse(BaseModel):
    emp_id: int = Field(..., description="Employee ID")
    username: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    manager_emp_id: Optional[int] = None
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
    emp_id: Optional[int] = None
    username: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    manager_emp_id: Optional[int] = None
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
    manager_emp_id: Optional[int] = None
    employee_image_url: Optional[str] = None
    message: Optional[str] = None
