import re
import html
from datetime import datetime
from typing import Optional, Literal, Annotated

from pydantic import Field, field_validator, model_validator, BaseModel, EmailStr

from backend.common.status_constants import (
    FilingFrequencyLiteral,
    RegistrationStatusLiteral,
    TaxpayerTypeLiteral,
    TurnoverDetailsLiteral,
)
from backend.gst_registration_filing.status_constants import (
    GstFilingStatusLiteral,
    GstReturnDetailStatusLiteral,
)
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
    Create GST filing (manual first-time).
    Assignment: API sets rm_id to current emp_id when JWT role is RM and rm_id is omitted;
    op_id to current emp_id when JWT role is OP and op_id is omitted (see create_gst_filing).
    """

    # =====================================================
    # OPTIONAL — when set, must exist and be active (see create_gst_filing).
    # Customer-side `customer_services` rows come from customer registration flows.
    # =====================================================
    customer_id: Optional[int] = Field(None, gt=0)

    # =====================================================
    # GST LINK (at least one; both allowed — UI can mirror prefill; API prefers id)
    # =====================================================
    gst_registration_id: Optional[int] = Field(None, gt=0)

    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    # =====================================================
    # CORE BUSINESS INPUT
    # =====================================================
    filing_category: Literal["RETURN", "ANNUAL"]

    taxpayer_type: Optional[TaxpayerTypeLiteral] = None

    filing_frequency:Optional[FilingFrequencyLiteral] = None

    turnover_details: Optional[TurnoverDetailsLiteral] = None

    state: Optional[Annotated[str, Field(min_length=2, max_length=50)]] = None
    language: Optional[Annotated[str, Field(min_length=2, max_length=50)]] = None
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[Annotated[str, Field(min_length=2, max_length=100)]] = None
    gst_reg_status: Optional[RegistrationStatusLiteral] = None

    # =====================================================
    # 🔥 FILING PERIOD
    # =====================================================
    filing_period: Optional[str] = None

    # =====================================================
    # ASSIGNMENT
    # =====================================================
    rm_id: Optional[int] = Field(
        None,
        gt=0,
        description="Relationship manager emp_id. Omitted + JWT role RM → API sets to current emp_id.",
    )
    op_id: Optional[int] = Field(
        None,
        gt=0,
        description="Operations emp_id. Omitted + JWT role OP → API sets to current emp_id.",
    )

    # =====================================================
    # OPTIONAL BUSINESS DATA
    # =====================================================
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"

    remarks: Optional[str] = Field(None, max_length=500)

    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, max_length=100)
    business_name: Optional[str] = Field(None, max_length=150)
    business_type: Optional[str] = Field(None, max_length=50)
    business_description: Optional[str] = None

    rent: Optional[float] = Field(None, ge=0)
    email_id: Optional[EmailStr] = None
    rule14a: Optional[bool] = None
    is_auto_enabled: Optional[bool] = True
    mode: Literal["MANUAL", "AUTO"] = "MANUAL"

    # =====================================================
    # NORMALIZATION
    # =====================================================
    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        return v.strip().upper() if v else None

    @field_validator(
        "filing_category",
        "taxpayer_type",
        "filing_frequency",
        "turnover_details",
        "filing_period",
        "state",
        "language",
        "referral_entity",
        "gst_reg_status",
        "business_type",
        mode="before"
    )
    @classmethod
    def normalize_upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("username", "password", mode="before")
    @classmethod
    def sanitize_credentials(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Invalid empty value")
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator(
        "customer_id", "gst_registration_id", "referral_id", "rm_id", "op_id",
        mode="before",
    )
    @classmethod
    def empty_int_to_none(cls, v):
        # Empty form fields ("") stay optional instead of failing int parsing.
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # =====================================================
    # VALIDATION (NO MUTATION ❌)
    # =====================================================
    @model_validator(mode="after")
    def validate_logic(self):

        # GST LINK
        if not self.gst_registration_id and not self.gstin:
            raise ValueError("Provide gst_registration_id or gstin")

        # CATEGORY vs FREQUENCY
        if self.filing_category == "ANNUAL" and self.filing_frequency != "YEARLY":
            raise ValueError("ANNUAL must be YEARLY")

        if self.filing_category == "RETURN" and self.filing_frequency == "YEARLY":
            raise ValueError("YEARLY must be ANNUAL")

        # COMPOSITION
        if self.taxpayer_type == "COMPOSITION":
            if self.turnover_details == "MORE_THAN_5CR":
                raise ValueError("Invalid turnover for Composition")

        # REGULAR
        if self.taxpayer_type == "REGULAR":
            if (
                self.turnover_details == "MORE_THAN_5CR"
                and self.filing_frequency == "QUARTERLY"
            ):
                raise ValueError("Quarterly not allowed for >5CR")

        # YEARLY REQUIREMENT
        if self.filing_frequency == "YEARLY" and not self.turnover_details:
            raise ValueError("Turnover required for yearly filings")

        # ANNUAL + YEARLY (annual returns only): taxpayer type required for return-detail seeding
        if (
            self.filing_category == "ANNUAL"
            and self.filing_frequency == "YEARLY"
            and not self.taxpayer_type
        ):
            raise ValueError("taxpayer_type is required for ANNUAL YEARLY filings")
        # FILING PERIOD FORMAT
        if self.filing_period:
            if not (
                re.match(r"^[A-Z]{3}-\d{4}$", self.filing_period) or
                re.match(r"^Q[1-4]-\d{4}$", self.filing_period) or
                re.match(r"^\d{4}-\d{2}$", self.filing_period)
            ):
                raise ValueError("Invalid filing_period format")

            if self.filing_frequency == "MONTHLY" and not re.match(r"^[A-Z]{3}-\d{4}$", self.filing_period):
                raise ValueError("MONTHLY filing_frequency requires MMM-YYYY filing_period")

            if self.filing_frequency == "QUARTERLY" and not re.match(r"^Q[1-4]-\d{4}$", self.filing_period):
                raise ValueError("QUARTERLY filing_frequency requires Q[1-4]-YYYY filing_period")

            if self.filing_frequency == "YEARLY" and not re.match(r"^\d{4}-\d{2}$", self.filing_period):
                raise ValueError("YEARLY filing_frequency requires YYYY-YY filing_period")

        return self


class GSTRegistrationFilingPrefillOut(BaseSchema):
    """
    Minimal fields from `gst_registration` for the create-filing screen.
    `taxpayer_type` aligns with DB `taxpayer_type` or legacy `registration_type`;
    `filing_frequency` with DB `filing_frequency` or legacy `filing_preference`.
    """

    request_id: str
    gst_registration_id: int
    customer_id: Optional[int] = Field(
        None,
        description="Linked `customers.customer_id` from the GST registration row.",
    )
    gstin: Optional[str] = None
    is_active: bool
    username: str
    password: Optional[str] = Field(
        None,
        max_length=100,
        description="GST portal password from `gst_registration.password` (empty stored value → null).",
    )
    password_set: bool = Field(
        ...,
        description="True when a non-empty password exists on the registration record.",
    )
    taxpayer_type: Optional[str] = Field(
        None,
        description="Same meaning as GST filing `taxpayer_type` (e.g. REGULAR, COMPOSITION).",
    )
    filing_frequency: Optional[str] = Field(
        None,
        description="Same meaning as GST filing `filing_frequency` (e.g. MONTHLY, QUARTERLY).",
    )
    turnover_details: Optional[str] = None
    state: Optional[str] = None
    language: Optional[str] = None
    gst_reg_status: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    business_description: Optional[str] = None
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    email_id: Optional[str] = None



class GSTFilingYearlyIn(BaseSchema):

    customer_id: Optional[int] = Field(None, gt=0)

    gst_registration_id: Optional[int] = Field(None, gt=0)
    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    taxpayer_type: TaxpayerTypeLiteral
    turnover_details: TurnoverDetailsLiteral

    state: Optional[Annotated[str, Field(min_length=2, max_length=50)]] = None
    language: Optional[Annotated[str, Field(min_length=2, max_length=50)]] = None
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[Annotated[str, Field(min_length=2, max_length=100)]] = None
    filing_period: Optional[str] = None

    rm_id: Optional[int] = Field(
        None,
        gt=0,
        description="RM emp_id; omitted + JWT role RM → current emp_id.",
    )
    op_id: Optional[int] = Field(
        None,
        gt=0,
        description="OP emp_id; omitted + JWT role OP → current emp_id.",
    )

    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    remarks: Optional[str] = Field(None, max_length=500)
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, max_length=100)
    rent: Optional[float] = Field(None, ge=0)
    email_id: Optional[EmailStr] = None
    rule14a: Optional[bool] = None

    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        return v.strip().upper() if v else None

    @field_validator(
        "taxpayer_type",
        "turnover_details",
        "filing_period",
        "state",
        "referral_entity",
        mode="before",
    )
    @classmethod
    def normalize_upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("username", "password", mode="before")
    @classmethod
    def sanitize_credentials(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Invalid empty value")
        return v

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_logic(self):
        if not self.gst_registration_id and not self.gstin:
            raise ValueError("Provide gst_registration_id or gstin")
        if self.taxpayer_type == "COMPOSITION" and self.turnover_details == "MORE_THAN_5CR":
            raise ValueError("Invalid turnover for Composition")
        if self.filing_period:
            if not re.match(r"^\d{4}-\d{2}$", self.filing_period):
                raise ValueError("YEARLY filing_period must be YYYY-YY (e.g. 2024-25)")
        return self


class GSTFilingPortalLoginIn(BaseSchema):
    """
    Portal login for a filing. Applied to the filing and mirrored onto its
    linked GST registration (username/password/email) when one exists.

    All fields optional; only those sent are written. Send an empty string to
    clear a value.
    """

    email_id: Optional[EmailStr] = None
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, max_length=100)

    @field_validator("email_id", "username", "password", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v


class GSTFilingEditIn(BaseSchema):
    """
    Partial update for GST filing. Only sent fields are applied; assignment fields override when provided.
    """

    # =====================================================
    # CORE BUSINESS (RECALCULATION TRIGGERS)
    # =====================================================
    filing_category: Optional[Literal["RETURN", "ANNUAL"]] = None

    filing_frequency: Optional[FilingFrequencyLiteral] = None

    taxpayer_type: Optional[TaxpayerTypeLiteral] = None

    turnover_details: Optional[TurnoverDetailsLiteral] = None

    state: Optional[str] = Field(None, max_length=50)
    language: Optional[str] = Field(None, max_length=50)
    referral_id: Optional[int] = Field(None, gt=0)
    referral_entity: Optional[str] = Field(None, max_length=100)
    gst_reg_status: Optional[RegistrationStatusLiteral] = None

    # =====================================================
    # GSTIN only — gst_registration_id is fixed on the filing (not PATCHable)
    # =====================================================
    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    # =====================================================
    # WORKFLOW STATUS (parent gst_filings.status)
    # =====================================================
    status: Optional[GstFilingStatusLiteral] = None

    priority: Optional[Literal["LOW", "NORMAL", "HIGH"]] = None

    remarks: Optional[str] = Field(None, max_length=500)

    # =====================================================
    # ASSIGNMENT
    # =====================================================
    rm_id: Optional[int] = Field(
        None,
        gt=0,
        description="When set, updates filing RM; omit to leave unchanged.",
    )
    op_id: Optional[int] = Field(
        None,
        gt=0,
        description="When set, updates filing OP; omit to leave unchanged.",
    )

    # =====================================================
    # FLAGS
    # =====================================================
    is_auto_enabled: Optional[bool] = None
    is_active: Optional[bool] = None

    # =====================================================
    # LOGIN / EXTRA
    # =====================================================
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, max_length=100)
    business_name: Optional[str] = Field(None, max_length=150)
    business_type: Optional[str] = Field(None, max_length=50)
    business_description: Optional[str] = None

    rent: Optional[float] = Field(None, ge=0)
    email_id: Optional[EmailStr] = None
    rule14a: Optional[bool] = None

    # =====================================================
    # NORMALIZATION
    # =====================================================
    @field_validator(
        "filing_category",
        "filing_frequency",
        "taxpayer_type",
        "turnover_details",
        "state",
        "language",
        "referral_entity",
        "gst_reg_status",
        "business_type",
        "status",
        mode="before"
    )
    @classmethod
    def normalize_upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        return v.strip().upper() if v else None

    @field_validator("email_id", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return v.strip().lower() if v else None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        return v.strip() if v else None

    @field_validator("password", mode="before")
    @classmethod
    def normalize_password(cls, v):
        return v.strip() if v else None

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        return v.strip() if isinstance(v, str) else v

    # =====================================================
    # VALIDATION
    # =====================================================
    @model_validator(mode="after")
    def validate_logic(self):

        # -------------------------------------------------
        # CATEGORY vs FREQUENCY
        # -------------------------------------------------
        if self.filing_category == "ANNUAL" and self.filing_frequency:
            if self.filing_frequency != "YEARLY":
                raise ValueError("ANNUAL must be YEARLY")

        if self.filing_category == "RETURN" and self.filing_frequency:
            if self.filing_frequency == "YEARLY":
                raise ValueError("RETURN cannot be YEARLY")

        # -------------------------------------------------
        # COMPOSITION RULE
        # -------------------------------------------------
        if self.taxpayer_type == "COMPOSITION":
            if self.filing_frequency == "MONTHLY":
                raise ValueError("Composition cannot be MONTHLY")

        # -------------------------------------------------
        # REGULAR RULE
        # -------------------------------------------------
        if (
            self.taxpayer_type == "REGULAR"
            and self.turnover_details == "MORE_THAN_5CR"
            and self.filing_frequency == "QUARTERLY"
        ):
            raise ValueError("Quarterly not allowed for >5CR")

        return self
class GSTReturnStatusUpdateIn(BaseSchema):

    gstr1_status: Optional[GstReturnDetailStatusLiteral] = None
    gstr3b_status: Optional[GstReturnDetailStatusLiteral] = None
    gstr9_status: Optional[GstReturnDetailStatusLiteral] = None
    gstr9c_status: Optional[GstReturnDetailStatusLiteral] = None
    cmp08_status: Optional[GstReturnDetailStatusLiteral] = None
    gstr4_status: Optional[GstReturnDetailStatusLiteral] = None
    is_active: Optional[bool] = None
    gstr1_followup_at: Optional[datetime] = None
    gstr3b_followup_at: Optional[datetime] = None
    gstr9_followup_at: Optional[datetime] = None
    gstr9c_followup_at: Optional[datetime] = None
    cmp08_followup_at: Optional[datetime] = None
    gstr4_followup_at: Optional[datetime] = None
    filing_frequency: Optional[FilingFrequencyLiteral] = Field(
        None,
        description="Cadence for this return-detail row (`gst_filing_return_details.filing_frequency`).",
    )

    @field_validator("filing_frequency", mode="before")
    @classmethod
    def normalize_filing_frequency(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            u = v.strip().upper()
            return u if u else None
        return v

    @field_validator(
        "gstr1_status",
        "gstr3b_status",
        "gstr9_status",
        "gstr9c_status",
        "cmp08_status",
        "gstr4_status",
        mode="before",
    )
    @classmethod
    def normalize_return_status_fields(cls, v):
        if v is None or v == "":
            return None
        return v.strip().upper() if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_at_least_one(self):
        followup_fields = (
            "gstr1_followup_at",
            "gstr3b_followup_at",
            "gstr9_followup_at",
            "gstr9c_followup_at",
            "cmp08_followup_at",
            "gstr4_followup_at",
        )
        if any(field in self.model_fields_set for field in followup_fields):
            return self
        if not any([
            self.gstr1_status,
            self.gstr3b_status,
            self.gstr9_status,
            self.gstr9c_status,
            self.cmp08_status,
            self.gstr4_status,
            self.is_active is not None,
            self.filing_frequency is not None,
        ]):
            raise ValueError(
                "At least one status, follow-up field, is_active, or filing_frequency must be provided"
            )

        return self


class GSTReturnDetailsBulkDeleteIn(BaseSchema):
    """
    Bulk delete return-detail rows by IDs.
    Intended for deleting only MISSED rows (enforced in API query).
    """

    return_detail_ids: list[int] = Field(
        ...,
        min_length=1,
        description="One or more gst_filing_return_details.id values to delete.",
    )

    @field_validator("return_detail_ids", mode="before")
    @classmethod
    def normalize_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("return_detail_ids must be a list")
        cleaned = []
        for item in v:
            iv = int(item)
            if iv <= 0:
                raise ValueError("All return_detail_ids must be positive integers")
            cleaned.append(iv)
        # dedupe while preserving order
        return list(dict.fromkeys(cleaned))


def _is_allowed_spreadsheet_url(url: str) -> bool:
    """Accept direct file links, Google Sheets, and SharePoint/OneDrive Excel URLs."""
    low = url.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return False
    if any(ext in low for ext in (".xlsx", ".xls", ".csv")):
        return True
    if "docs.google.com/spreadsheets" in low:
        return True
    # SharePoint Excel sharing links use :x:/ (no .xlsx in the URL path)
    if "sharepoint.com" in low and ":x:" in low:
        return True
    # OneDrive Excel short / personal links
    if "1drv.ms/x/" in low:
        return True
    if "onedrive.live.com" in low and ":x:" in low:
        return True
    return False


class GSTFilingDocumentIn(BaseSchema):

    # =====================================================
    # REQUIRED
    # =====================================================
    gst_filing_id: int = Field(..., gt=0)

    document_type: Annotated[str, Field(..., max_length=50)]
    document_url: Annotated[str, Field(..., max_length=1000)]

    # =====================================================
    # OPTIONAL
    # =====================================================
    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    remarks: Optional[str] = Field(None, max_length=500)

    verified: bool = False

    # =====================================================
    # NORMALIZATION
    # =====================================================
    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_doc_type(cls, v):
        return v.strip().upper()

    @field_validator("document_url", mode="before")
    @classmethod
    def normalize_url(cls, v):
        return v.strip()

    @field_validator("document_url")
    @classmethod
    def validate_excel_link(cls, v):
        if not _is_allowed_spreadsheet_url(v):
            raise ValueError(
                "document_url must be an Excel/CSV/Google Sheets link "
                "(including SharePoint/OneDrive Excel sharing URLs)"
            )
        return v

    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        return v.strip().upper() if v else None

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v


class GSTFilingDocumentEditIn(BaseSchema):

    document_type: Optional[str] = Field(None, max_length=50)

    document_url: Optional[str] = Field(None, max_length=1000)

    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    remarks: Optional[str] = Field(None, max_length=500)

    verified: Optional[bool] = None

    is_active: Optional[bool] = None

    # ---------------- NORMALIZATION ----------------
    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v.upper() if v else None
        return v

    @field_validator("document_url", mode="before")
    @classmethod
    def normalize_document_url(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("remarks", mode="before")
    @classmethod
    def normalize_remarks(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v

    @field_validator("document_url")
    @classmethod
    def validate_excel_link(cls, v):
        if v is None:
            return v
        if not _is_allowed_spreadsheet_url(v):
            raise ValueError(
                "document_url must be an Excel/CSV/Google Sheets link "
                "(including SharePoint/OneDrive Excel sharing URLs)"
            )
        return v

    # ---------------- VALIDATION ----------------
    @model_validator(mode="after")
    def validate_logic(self):
        return self

