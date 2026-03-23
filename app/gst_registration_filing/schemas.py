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
class GSTFilingIn(BaseSchema):
    """
    Create GST Filing
    -------------------
    • Supports BOTH:
        - Internal GST (gst_registration_id)
        - External GST (gstin)
    • Strict validation
    """

    # ----------------------------
    # REQUIRED
    # ----------------------------
    customer_id: int = Field(..., gt=0)

    filing_type: Annotated[str, Field(..., max_length=20)]
    filing_period: Annotated[str, Field(..., max_length=20)]
    due_date: datetime

    # ----------------------------
    # GST LINK (ONE REQUIRED)
    # ----------------------------
    gst_registration_id: Optional[int] = Field(None, gt=0)
    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    # ----------------------------
    # OPTIONAL SYSTEM
    # ----------------------------
    customer_service_id: Optional[int] = Field(None, gt=0)  # ⚠️ deprecated (kept)
    service_id: Optional[int] = Field(None, gt=0)

    filing_category: Optional[str] = Field(None, max_length=20)

    status: Literal[
        "PENDING",
        "DATA_PENDING",
        "DATA_RECEIVED",
        "IN_PROGRESS",
        "FILED",
        "FAILED",
    ] = "PENDING"

    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"

    remarks: Optional[str] = Field(None, max_length=500)

    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)

    # ✅ KEEP ONLY THIS
    is_auto_enabled: bool = True

    # =====================================================
    # NORMALIZATION
    # =====================================================

    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        if v:
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("filing_type", "filing_category", mode="before")
    @classmethod
    def normalize_upper(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("filing_period", mode="before")
    @classmethod
    def normalize_period(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v

    # =====================================================
    # BUSINESS VALIDATION
    # =====================================================

    @model_validator(mode="after")
    def validate_gst_reference(self):

        if not self.gst_registration_id and not self.gstin:
            raise ValueError(
                "Either gst_registration_id or gstin must be provided"
            )

        return self

    # ✅ ADDED (IMPORTANT)
    @model_validator(mode="after")
    def validate_logic(self):

        # Prevent invalid due_date (past date safety optional)
        if self.due_date and self.due_date.year < 2000:
            raise ValueError("Invalid due_date")

        return self

class GSTFilingEditIn(BaseSchema):
    """
    Edit GST Filing
    -------------------
    • Partial updates allowed
    • Workflow-safe
    """

    filing_type: Optional[str] = Field(None, max_length=20)
    filing_category: Optional[str] = Field(None, max_length=20)
    filing_period: Optional[str] = Field(None, max_length=20)

    due_date: Optional[datetime] = None

    gst_registration_id: Optional[int] = Field(None, gt=0)
    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    service_id: Optional[int] = Field(None, gt=0)
    customer_service_id: Optional[int] = Field(None, gt=0)

    status: Optional[
        Literal[
            "PENDING",
            "DATA_PENDING",
            "DATA_RECEIVED",
            "IN_PROGRESS",
            "FILED",
            "FAILED",
        ]
    ] = None

    priority: Optional[Literal["LOW", "NORMAL", "HIGH"]] = None

    remarks: Optional[str] = Field(None, max_length=500)

    filed_at: Optional[datetime] = None

    is_active: Optional[bool] = None

    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)

    # ✅ ADDED
    is_auto_enabled: Optional[bool] = None

    # =====================================================
    # NORMALIZATION
    # =====================================================

    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        if v:
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("filing_type", "filing_category", mode="before")
    @classmethod
    def normalize_upper(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return v.upper()
        return v

    @field_validator("filing_period", mode="before")
    @classmethod
    def normalize_period(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        if isinstance(v, str):
            return html.escape(v.strip())
        return v

    # =====================================================
    # BUSINESS VALIDATION
    # =====================================================

    @model_validator(mode="after")
    def validate_logic(self):

        # If status is FILED → filed_at required
        if self.status == "FILED" and not self.filed_at:
            raise ValueError("filed_at is required when status is FILED")

        return self

    # ✅ ADDED (CRITICAL)
    @model_validator(mode="after")
    def validate_gst_reference_update(self):

        # Prevent removing both references during update
        if self.gst_registration_id is None and self.gstin is None:
            return self  # partial update allowed

        if not self.gst_registration_id and not self.gstin:
            raise ValueError(
                "Either gst_registration_id or gstin must remain present"
            )

        return self