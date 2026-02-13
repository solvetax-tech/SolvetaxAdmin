from pydantic import (BaseModel,EmailStr,Field,HttpUrl,constr,field_validator,model_validator)
from typing import Optional, Dict, Annotated
from datetime import datetime
import html
import re


# =========================================================
# Base Schema (Global Config)
# =========================================================

class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",              # Reject unknown fields
        "str_strip_whitespace": True,   # Auto trim strings
        "validate_assignment": True,    # Validate on update
        "from_attributes": True,        # ORM safe
    }


# =========================================================
# Signup Request
# =========================================================

class SignupRequest(BaseSchema):
    username: Annotated[str, constr(min_length=1, max_length=100)]
    email: EmailStr
    password: Annotated[str, constr(min_length=8)]
    first_name: Optional[Annotated[str, constr(min_length=1, max_length=100)]] = None
    last_name: Optional[Annotated[str, constr(min_length=1, max_length=100)]] = None
    phone_number: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    role: Annotated[str, constr(max_length=50)] = "SE"
    is_active: bool = True
    manager_emp_id: Optional[int] = Field(None, gt=0)

    # ----------------------------
    # Normalize Email
    # ----------------------------
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    # ----------------------------
    # Sanitize Strings (Basic XSS)
    # ----------------------------
    @field_validator("username", "first_name", "last_name", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v

    # ----------------------------
    # Strong Password Rule
    # ----------------------------
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        if (
            not re.search(r"[A-Z]", v)
            or not re.search(r"[a-z]", v)
            or not re.search(r"\d", v)
        ):
            raise ValueError(
                "Password must contain uppercase, lowercase, and a number"
            )
        return v


# =========================================================
# Signup Response
# =========================================================

class SignupResponse(BaseSchema):
    emp_id: int
    username: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    manager_emp_id: Optional[int] = None
    message: str


# =========================================================
# Error Response
# =========================================================

class ErrorResponse(BaseSchema):
    error: str
    fields: Optional[Dict[str, str]] = None


# =========================================================
# Send OTP
# =========================================================

class SendOTPRequest(BaseSchema):
    username: str
    email: Optional[EmailStr] = None
    phone_number: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None

    @model_validator(mode="after")
    def check_email_or_phone(self):
        if not self.email and not self.phone_number:
            raise ValueError("Either email or phone_number must be provided")
        return self


# =========================================================
# Forgot Password
# =========================================================

class ForgotPasswordRequest(BaseSchema):
    email: EmailStr


class ForgotPasswordVerify(BaseSchema):
    email: EmailStr
    otp: Annotated[str, constr(min_length=4, max_length=4, pattern=r"^\d{4}$")]
    new_password: Annotated[str, constr(min_length=8)]

    @field_validator("new_password")
    @classmethod
    def validate_new_password_strength(cls, v):
        if (
            not re.search(r"[A-Z]", v)
            or not re.search(r"[a-z]", v)
            or not re.search(r"\d", v)
        ):
            raise ValueError(
                "Password must contain uppercase, lowercase, and a number"
            )
        return v


class ForgotPasswordResponse(BaseSchema):
    message: str


# =========================================================
# Employee Edit Schema (Dynamic Update)
# =========================================================

class EmployeeEditIn(BaseSchema):
    username: Optional[Annotated[str, constr(min_length=1, max_length=100)]] = None
    email: Optional[EmailStr] = None
    first_name: Optional[Annotated[str, constr(min_length=1, max_length=100)]] = None
    last_name: Optional[Annotated[str, constr(min_length=1, max_length=100)]] = None
    phone_number: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    role: Optional[Annotated[str, constr(max_length=50)]] = None
    is_active: Optional[bool] = None
    manager_emp_id: Optional[int] = Field(None, gt=0)
    employee_image_url: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v


# =========================================================
# Employee Response
# =========================================================

class EmployeeOut(BaseSchema):
    emp_id: int
    username: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    manager_emp_id: Optional[int] = None
    employee_image_url: Optional[HttpUrl] = None
    message: Optional[str] = None
