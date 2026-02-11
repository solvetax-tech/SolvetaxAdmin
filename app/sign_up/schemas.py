from pydantic import BaseModel, EmailStr, HttpUrl, constr, validator, root_validator, model_validator, Field
from typing import Optional, Dict, Annotated
import re
from datetime import datetime

class SignupRequest(BaseModel):
    username: Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)] = Field(..., description="Desired username")
    email: EmailStr = Field(..., description="User's email address")
    password: Annotated[str, constr(min_length=8)] = Field(..., description="User's password (must be strong)")
    first_name: Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)] = Field(None, description="User's first name")
    last_name: Annotated[str, constr(strip_whitespace=True, min_length=1, max_length=100)] = Field(None, description="User's last name")
    phone_number: Annotated[str, Field(pattern=r'^\d{10}$')] = Field(None, description="Phone number must be exactly 10 digits")
    role:Annotated[str, constr(max_length=50)] = Field("SE", description="User role (default: SE)")
    is_active: Annotated[bool, Field(default=True, description="Is user active")] = True
    manager_emp_id:Annotated[int, Field(description="Manager employee ID")] = None


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

from pydantic import HttpUrl

class EmployeeEditIn(BaseModel):
    emp_id: Optional[int] = Field(None, description="Employee ID")
    username: Optional[str] = Field(None, description="Username")
    email: Optional[EmailStr] = Field(None, description="Email address")
    first_name: Optional[str] = Field(None, description="First name")
    last_name: Optional[str] = Field(None, description="Last name")
    phone_number: Optional[Annotated[str, Field(pattern=r'^\d{10}$')]] = Field(None, description="Phone number must be exactly 10 digits")
    role: Optional[str] = Field(None, description="User role")
    is_active: Optional[bool] = Field(None, description="Is user active")
    manager_emp_id: Optional[int] = Field(None, description="Manager employee ID")
    employee_image_url: Optional[HttpUrl] = Field(None, description="URL to employee image")

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
