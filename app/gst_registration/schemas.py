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
# Base Schema (Global Config - same as customer_registration)
# =========================================================

class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",              # Reject unknown fields
        "str_strip_whitespace": True,   # Auto trim all strings
        "validate_assignment": True,    # Validate on update
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
    # Normalize email (same as customer)
    # ----------------------------
    @field_validator("email", "secondary_email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    # ----------------------------
    # Basic XSS sanitization (same as customer)
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

    @field_validator("email", "secondary_email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    @field_validator(
        "suspension_reason",
        "cancellation_reason",
        "ownership_category",
        "business_type",
        "state",
        "turnover_details",
        "registration_type",
        "registration_status",
        mode="before",
    )
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
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

    # ---------------- Normalize Email ----------------
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    # ---------------- Sanitize Strings ----------------
    @field_validator("full_name", "role", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v


# ---------------------------------------------------------
# EDIT SCHEMA (Dynamic Update)
# ---------------------------------------------------------

class RegistrationPersonEditIn(BaseSchema):
    """
    Schema for editing Registration Person (PATCH-like behavior)
    """

    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    role: Optional[str] = Field(None, min_length=2, max_length=100)
    pan: Optional[Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]] = None
    aadhaar: Optional[Annotated[str, Field(pattern=r"^\d{12}$")]] = None
    email: Optional[EmailStr] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    is_primary_customer: Optional[bool] = None
    is_active: Optional[bool] = None   # 🔥 added (since column exists)

    # ---------------- Normalize Email ----------------
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    # ---------------- Sanitize Strings ----------------
    @field_validator("full_name", "role", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v


# ---------------------------------------------------------
# OUTPUT SCHEMA
# ---------------------------------------------------------

class RegistrationPersonOut(BaseSchema):
    """
    Output schema aligned with DB structure
    """

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

    # 🔥 Audit Fields (Now Present in DB)
    created_at: datetime
    updated_at: datetime
    is_active: bool

    message: Optional[str] = None

# =========================================================
# Registration Documents
# =========================================================

class RegistrationDocumentIn(BaseSchema):
    gstin: Annotated[str, Field(pattern=r"^[0-9A-Z]{15}$")]
    person_id: Optional[int] = Field(None, gt=0)
    document_type: str = Field(..., min_length=2, max_length=50)
    document_url: HttpUrl
    ownership_category: Optional[str] = Field(None, max_length=50)
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None

    @field_validator("document_type", "ownership_category", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v


# ---------------------------------------------------------
# EDIT SCHEMA (Dynamic Update)
# ---------------------------------------------------------

class RegistrationDocumentEditIn(BaseSchema):
    document_type: Optional[str] = Field(None, min_length=2, max_length=50)
    document_url: Optional[HttpUrl] = None
    ownership_category: Optional[str] = Field(None, max_length=50)
    verified: Optional[bool] = None
    verified_by: Optional[int] = Field(None, gt=0)
    verified_at: Optional[datetime] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None
    is_active: Optional[bool] = None  # allow soft activation/deactivation via edit if needed

    @field_validator("document_type", "ownership_category", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v


# ---------------------------------------------------------
# RESPONSE SCHEMA
# ---------------------------------------------------------

class RegistrationDocumentOut(BaseSchema):
    document_id: int
    gstin: str
    person_id: Optional[int]
    document_type: str
    document_url: HttpUrl
    ownership_category: Optional[str]
    verified: bool
    verified_by: Optional[int]
    verified_at: Optional[datetime]
    mobile: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_active: bool
    message: Optional[str] = None
