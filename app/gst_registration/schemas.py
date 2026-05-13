from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)
from typing import Optional, Annotated, Literal, List
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



class GSTConfigOut(BaseModel):
    value: str
    display_name: str
    sort_order: int


class CustomerSnapshotForGstOut(BaseModel):
    """Customer fields from `customers` for GST registration flows (`customers.customer_id`)."""

    customer_id: int
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    state: Optional[str] = None
    language: Optional[str] = None
    op_id: Optional[int] = None
    rm_id: Optional[int] = None
    mobile: Optional[str] = None

    model_config = {"from_attributes": True}


class GSTRegistrationIn(BaseModel):

    # ----------------------------
    # Identity
    # ----------------------------
    customer_id: Optional[Annotated[int, Field(gt=0)]] = Field(
        None,
        description="Optional link to customers.customer_id. Omit for GST rows without a customer record (DB must allow NULL).",
    )

    username: Optional[Annotated[str, Field(min_length=0, max_length=100)]] = None
    password: Optional[Annotated[str, Field(min_length=0, max_length=128)]] = None

    pan: Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]
    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    # ----------------------------
    # Business
    # ----------------------------
    business_name: Annotated[str, Field(..., max_length=200)]
    registration_type: Annotated[str, Field(..., max_length=50)]
    ownership_category: Annotated[str, Field(..., max_length=100)]
    business_type: Optional[str] = Field(None, max_length=100)
    state: Annotated[str, Field(..., max_length=100)]
    language: Optional[str] = Field(None, max_length=50)
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[str] = Field(None, max_length=100)
    turnover_details: Annotated[str, Field(..., max_length=50)]

    # ----------------------------
    # Workflow Status
    # ----------------------------
    registration_status: Literal[
        "DRAFT",
        "APPROVED",
        "SUSPENDED",
        "CANCELLED",
    ] = "DRAFT"

    suspension_reason: Optional[str] = Field(None, max_length=255)
    cancellation_reason: Optional[str] = Field(None, max_length=255)

    # ----------------------------
    # Assignment
    # ----------------------------
    rm_id: Optional[int] = Field(
        None,
        gt=0,
        description="Relationship manager emp_id. Omitted + JWT role RM → API sets to current emp_id. Otherwise required if not RM.",
    )
    created_by: Optional[int] = Field(
        None,
        gt=0,
        description="Ignored on create; API sets gst_registration.created_by to current emp_id only when JWT role is OP.",
    )

    # ----------------------------
    # Flags
    # ----------------------------
    is_filing_needed: bool = True
    is_rcm_applicable: bool = False

    # ----------------------------
    # Contact
    # ----------------------------
    mobile: Annotated[str, Field(pattern=r"^\d{10}$")]
    email: Annotated[EmailStr, Field(..., max_length=150)]
    secondary_email: Optional[Annotated[EmailStr, Field(None, max_length=150)]]

    # ----------------------------
    # Filing Preference (NEW)
    # ----------------------------
    filing_preference: Optional[Literal["MONTHLY", "QUARTERLY"]] = None

    # =====================================================
    # Normalization
    # =====================================================

    @field_validator("pan", "gstin", mode="before")
    @classmethod
    def normalize_identifiers(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip().lower())
        return v

    @field_validator("business_name", mode="before")
    @classmethod
    def normalize_business_name(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v
        return v

    @field_validator(
        "registration_type",
        "ownership_category",
        "business_type",
        "state",
        "language",
        "referral_entity",
        "turnover_details",
        mode="before",
    )
    @classmethod
    def normalize_business_fields(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("email", "secondary_email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if v:
            return v.strip()
        return v

    @field_validator("filing_preference", mode="before")
    @classmethod
    def normalize_filing_preference(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    # =====================================================
    # Workflow Business Logic
    # =====================================================

    @model_validator(mode="after")
    def validate_status_logic(self):

        if self.registration_status == "SUSPENDED" and not self.suspension_reason:
            raise ValueError(
                "suspension_reason is required when status is SUSPENDED"
            )

        if self.registration_status == "CANCELLED" and not self.cancellation_reason:
            raise ValueError(
                "cancellation_reason is required when status is CANCELLED"
            )

        return self
class GSTRegistrationEditIn(BaseModel):

    customer_id: Optional[int] = Field(
        None,
        gt=0,
        description="Link to customers.customer_id; omit if unchanged. JSON null clears link when column is nullable.",
    )

    business_name: Optional[str] = Field(None, max_length=200)

    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    username: Optional[str] = Field(None, min_length=0, max_length=100)
    password: Optional[str] = Field(None, min_length=0, max_length=128)

    pan: Optional[
        Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]
    ] = None

    registration_type: Optional[str] = Field(None, max_length=50)
    ownership_category: Optional[str] = Field(None, max_length=100)
    business_type: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[str] = Field(None, max_length=100)
    turnover_details: Optional[str] = Field(None, max_length=50)

    registration_status: Optional[
        Literal["DRAFT", "APPROVED", "SUSPENDED", "CANCELLED"]
    ] = None

    suspension_reason: Optional[str] = Field(None, max_length=255)
    cancellation_reason: Optional[str] = Field(None, max_length=255)

    is_rcm_applicable: Optional[bool] = None
    is_filing_needed: Optional[bool] = None
    is_active: Optional[bool] = None

    mobile: Optional[
        Annotated[str, Field(pattern=r"^\d{10}$")]
    ] = None

    email: Optional[EmailStr] = None
    secondary_email: Optional[EmailStr] = None

    rm_id: Optional[int] = Field(None, gt=0)
    created_by: Optional[int] = Field(None, gt=0)

    # ----------------------------
    # Filing Preference (NEW)
    # ----------------------------
    filing_preference: Optional[Literal["MONTHLY", "QUARTERLY"]] = None

    # =====================================================
    # Normalization (Improved & Safe)
    # =====================================================

    @field_validator("business_name", mode="before")
    @classmethod
    def normalize_business_name(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v
        return v

    @field_validator("pan", "gstin", mode="before")
    @classmethod
    def normalize_identifiers(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.lower()
        return v

    @field_validator(
        "registration_type",
        "ownership_category",
        "business_type",
        "state",
        "language",
        "referral_entity",
        "turnover_details",
        mode="before",
    )
    @classmethod
    def normalize_business_fields(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("email", "secondary_email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.lower()
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def normalize_mobile(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v
        return v

    @field_validator("filing_preference", mode="before")
    @classmethod
    def normalize_filing_preference(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    # =====================================================
    # Workflow Validation
    # =====================================================

    @model_validator(mode="after")
    def validate_status_logic(self):

        if self.registration_status == "SUSPENDED" and not self.suspension_reason:
            raise ValueError(
                "suspension_reason is required when status is SUSPENDED"
            )

        if self.registration_status == "CANCELLED" and not self.cancellation_reason:
            raise ValueError(
                "cancellation_reason is required when status is CANCELLED"
            )

        return self
# =========================================================
# GST Registration - Response
# =========================================================

class GSTRegistrationOut(BaseSchema):
    id: int
    customer_id: Optional[int] = None
    gstin: Optional[str]
    username: Optional[str] = None
    pan: str
    mobile: Optional[str] = None
    registration_type: Optional[str]
    ownership_category: Optional[str]
    business_type: Optional[str]
    state: Optional[str]
    language: Optional[str]
    referral_id: Optional[int]
    referral_entity: Optional[str]
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
    rm_name: Optional[str] = None
    filing_preference: Optional[str] = None
    approved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None


class RegistrationPersonIn(BaseSchema):

    # ----------------------------
    # Required Mapping
    # ----------------------------
    gst_registration_id: int = Field(..., gt=0)

    full_name: str = Field(..., min_length=2, max_length=150)
    designation: str = Field(..., min_length=2, max_length=100)

    # ----------------------------
    # Identity
    # ----------------------------
    pan: Optional[str] = Field(
        None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$"
    )

    aadhaar: Optional[str] = Field(
        None, pattern=r"^\d{12}$"
    )

    # ----------------------------
    # Contact
    # ----------------------------
    email: Optional[EmailStr] = None

    mobile: Optional[str] = Field(
        None, pattern=r"^\d{10}$"
    )

    # ----------------------------
    # Flags
    # ----------------------------
    is_primary_customer: bool = False

    # =====================================================
    # 🔥 Normalization
    # =====================================================

    @field_validator("pan", mode="before")
    @classmethod
    def normalize_pan(cls, v):
        if v:
            return v.strip().upper()
        return v

    @field_validator("aadhaar", "mobile", mode="before")
    @classmethod
    def normalize_numeric(cls, v):
        if v:
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    @field_validator("full_name", "designation", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v
# =========================================================
# Registration Person - Edit (Dynamic Update)
# =========================================================

class RegistrationPersonEditIn(BaseSchema):
    """
    Edit Registration Person (Dynamic Update)
    Only editable fields are included.
    """

    # ----------------------------
    # Editable Fields
    # ----------------------------
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    designation: Optional[str] = Field(None, min_length=2, max_length=100)

    pan: Optional[Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]] = None
    aadhaar: Optional[Annotated[str, Field(pattern=r"^\d{12}$")]] = None

    email: Optional[EmailStr] = None
    mobile: Optional[Annotated[str, Field(pattern=r"^\d{10}$")]] = None

    is_primary_customer: Optional[bool] = None
    is_active: Optional[bool] = None

    # =====================================================
    # 🔥 Normalization
    # =====================================================
    @field_validator("pan", mode="before")
    @classmethod
    def normalize_upper_identifiers(cls, v):
        if v:
            return v.strip().upper()
        return v

    @field_validator("aadhaar", "mobile", mode="before")
    @classmethod
    def normalize_trim_numeric(cls, v):
        if v:
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if v:
            return v.strip().lower()
        return v

    @field_validator("full_name", "designation", mode="before")
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
    designation: str
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

# -------------------------------------------------------------------
# SCHEMA: RegistrationDocumentIn
# -------------------------------------------------------------------
class RegistrationDocumentIn(BaseSchema):
    person_id: Optional[int] = Field(..., gt=0)
    document_type: str = Field(..., min_length=2, max_length=50)
    document_url: HttpUrl
    verified: Optional[bool] = Field(False, description="Set True if document is verified on creation")

    # -----------------------------------------------------
    # Normalization
    # -----------------------------------------------------
    @classmethod
    def normalize_person_id(cls, v):
        return v

    @field_validator("document_type", mode="before")
    @classmethod
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip().upper())
        return v

class RegistrationDocumentEditIn(BaseSchema):
    document_type: Optional[str] = Field(None, min_length=2, max_length=50)
    document_url: Optional[HttpUrl] = None
    verified: Optional[bool] = None

    # -----------------------------------------------------
    # Normalization
    # -----------------------------------------------------
    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_strings(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    # -----------------------------------------------------
    # Verification Logic Validation (Patch-Safe)
    # -----------------------------------------------------
    @model_validator(mode="after")
    def validate_verification_logic(self):
        if self.verified is not None and not isinstance(self.verified, bool):
            raise ValueError("verified must be a boolean if provided")
        return self
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
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime]
    mobile: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_active: bool
    message: Optional[str] = None