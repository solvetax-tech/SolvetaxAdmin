from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)
from typing import Optional, Annotated
from datetime import datetime
import html

# =========================================================
# Base Schema (Global Production Config)
# =========================================================

class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",              # Reject unknown fields
        "str_strip_whitespace": True,   # Auto trim all strings
        "validate_assignment": True,    # Re-validate on update
        "from_attributes": True,        # ORM safe
    }


# =========================================================
# GST Registration - Create
# =========================================================

class GSTRegistrationIn(BaseSchema):
    customer_id: int = Field(..., gt=0)
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    pan: Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]
    gstin: Optional[Annotated[str, Field(pattern=r"^[0-9A-Z]{15}$")]] = None
    registration_type: Optional[str] = Field(
        None,
        description="NORMAL / COMPOSITION",
    )
    ownership_category: Optional[str] = Field(None, max_length=100)
    business_type: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    turnover_details: Optional[str] = Field(
        None,
        description="LESS_THAN_2CR / LESS_THAN_5CR / MORE_THAN_5CR",
    )
    created_by: Optional[int] = Field(None, gt=0)
    rm_id: Optional[int] = Field(None, gt=0)
    is_filing_needed: bool = True
    is_active: bool = True
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    email: Optional[EmailStr] = None
    secondary_email: Optional[EmailStr] = None

    # ----------------------------
    # Normalize PAN & GSTIN
    # ----------------------------

    @field_validator("pan", "gstin", mode="before")
    @classmethod
    def uppercase_ids(cls, v):
        if v:
            return v.upper()
        return v

    # ----------------------------
    # Basic XSS Protection
    # ----------------------------

    @field_validator(
        "username",
        "ownership_category",
        "business_type",
        "state",
        "turnover_details",
        mode="before",
    )
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v


# =========================================================
# GST Registration - Edit (Dynamic Update)
# =========================================================

class GSTRegistrationEditIn(BaseSchema):
    gstin: Optional[Annotated[str, Field(pattern=r"^[0-9A-Z]{15}$")]] = None
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    pan: Optional[Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]] = None
    registration_type: Optional[str] = None
    ownership_category: Optional[str] = Field(None, max_length=100)
    business_type: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    turnover_details: Optional[str] = None
    registration_status: Optional[str] = None
    suspension_reason: Optional[str] = Field(None, max_length=255)
    cancellation_reason: Optional[str] = Field(None, max_length=255)
    approved_at: Optional[datetime] = None
    is_rcm_applicable: Optional[bool] = None
    is_filing_needed: Optional[bool] = None
    is_active: Optional[bool] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    email: Optional[EmailStr] = None
    secondary_email: Optional[EmailStr] = None
    rm_id: Optional[int] = Field(None, gt=0)

    @field_validator("pan", "gstin", mode="before")
    @classmethod
    def uppercase_ids(cls, v):
        if v:
            return v.upper()
        return v


# =========================================================
# GST Registration - Response
# =========================================================

class GSTRegistrationOut(BaseSchema):
    id: int
    customer_id: int
    gstin: Optional[str]
    username: str
    pan: str
    registration_type: Optional[str]
    ownership_category: Optional[str]
    business_type: Optional[str]
    state: Optional[str]
    turnover_details: Optional[str]
    registration_status: Optional[str]
    suspension_reason: Optional[str]
    cancellation_reason: Optional[str]
    is_rcm_applicable: bool
    is_filing_needed: bool
    is_active: bool
    email: Optional[EmailStr]
    secondary_email: Optional[EmailStr]
    created_by: Optional[int]
    rm_id: Optional[int]
    approved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None


# =========================================================
# Registration Person
# =========================================================

class RegistrationPersonIn(BaseSchema):
    customer_id: Optional[int] = Field(None, gt=0)
    gstin: Annotated[str, Field(pattern=r"^[0-9A-Z]{15}$")]
    full_name: str = Field(..., min_length=2, max_length=150)
    role: str = Field(..., min_length=2, max_length=100)
    pan: Optional[Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]] = None
    aadhaar: Optional[Annotated[str, Field(pattern=r"^\d{12}$")]] = None
    email: Optional[EmailStr] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    is_primary_customer: bool = False


class RegistrationPersonEditIn(BaseSchema):
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    role: Optional[str] = Field(None, min_length=2, max_length=100)
    pan: Optional[Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]] = None
    aadhaar: Optional[Annotated[str, Field(pattern=r"^\d{12}$")]] = None
    email: Optional[EmailStr] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    is_primary_customer: Optional[bool] = None


class RegistrationPersonOut(BaseSchema):
    person_id: int
    customer_id: Optional[int]
    gstin: str
    full_name: str
    role: str
    pan: Optional[str]
    aadhaar: Optional[str]
    email: Optional[EmailStr]
    mobile: Optional[str]
    is_primary_customer: bool
    message: Optional[str] = None


# =========================================================
# Registration Documents
# =========================================================

class RegistrationDocumentIn(BaseSchema):
    gstin: Annotated[str, Field(pattern=r"^[0-9A-Z]{15}$")]
    person_id: Optional[int] = Field(None, gt=0)
    document_type: str = Field(..., min_length=2, max_length=100)
    document_url: HttpUrl
    ownership_category: Optional[str] = Field(None, max_length=100)
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None


class RegistrationDocumentEditIn(BaseSchema):
    document_type: Optional[str] = Field(None, min_length=2, max_length=100)
    document_url: Optional[HttpUrl] = None
    ownership_category: Optional[str] = Field(None, max_length=100)
    verified: Optional[bool] = None
    verified_by: Optional[int] = Field(None, gt=0)
    verified_at: Optional[datetime] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None


class RegistrationDocumentOut(BaseSchema):
    document_id: int
    gstin: str
    person_id: Optional[int]
    document_type: str
    document_url: HttpUrl
    ownership_category: Optional[str]
    verified: Optional[bool]
    verified_by: Optional[int]
    verified_at: Optional[datetime]
    uploaded_at: Optional[datetime]
    mobile: Optional[str]
