import re
import html
from datetime import datetime
from typing import Optional, Literal, Annotated

from pydantic import Field, field_validator, model_validator, BaseModel
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
    GST Filing Input Schema (FINAL - CLEAN + API DRIVEN)
    ---------------------------------------------------
    ✔ filing_period generated in API
    ✔ due_date computed in API
    ✔ rule engine driven
    ✔ minimal but strong validation
    """

    # =====================================================
    # REQUIRED
    # =====================================================
    customer_id: int = Field(..., gt=0)

    filing_type: Literal[
        "GSTR1",
        "GSTR3B",
        "GSTR9",
        "GSTR9C",
        "CMP08",
        "GSTR4"
    ]

    # =====================================================
    # GST LINK (ONE REQUIRED)
    # =====================================================
    gst_registration_id: Optional[int] = Field(None, gt=0)

    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    # =====================================================
    # BUSINESS INPUT (USER CONTROLLED)
    # =====================================================
    filing_category: Optional[
        Literal["RETURN", "ANNUAL"]
    ] = None

    taxpayer_type: Optional[
        Literal["REGULAR", "COMPOSITION"]
    ] = None

    filing_frequency: Optional[
        Literal["MONTHLY", "QUARTERLY", "YEARLY"]
    ] = "MONTHLY"

    turnover_details: Optional[
        Literal["LESS_THAN_5CR", "MORE_THAN_5CR"]
    ] = None

    state: Optional[str] = Field(None, max_length=50)

    # =====================================================
    # STATUS
    # =====================================================
    status: Literal[
        "DATA_PENDING",
        "DATA_RECEIVED",
        "IN_PREPARATION",
        "PENDING_OTP",
        "READY_TO_FILE",
        "FILED",
        "OVERDUE",
    ] = "DATA_PENDING"

    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"

    remarks: Optional[str] = Field(None, max_length=500)

    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)

    is_auto_enabled: bool = True

    # =====================================================
    # NORMALIZATION
    # =====================================================
    @field_validator("gstin", mode="before")
    @classmethod
    def normalize_gstin(cls, v):
        return v.strip().upper() if v else None

    @field_validator(
        "filing_type",
        "filing_category",
        "taxpayer_type",
        "filing_frequency",
        "turnover_details",
        "state",
        mode="before"
    )
    @classmethod
    def normalize_upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v

    # =====================================================
    # VALIDATION (REAL-WORLD RULES)
    # =====================================================
    @model_validator(mode="after")
    def validate_logic(self):

        # -------------------------------------------------
        # GST reference validation
        # -------------------------------------------------
        if not self.gst_registration_id and not self.gstin:
            raise ValueError("Provide gst_registration_id or gstin")

        # -------------------------------------------------
        # Prevent invalid initial state
        # -------------------------------------------------
        if self.status == "FILED":
            raise ValueError("Cannot create filing as FILED")

        # -------------------------------------------------
        # QRMP Rule (VERY IMPORTANT)
        # -------------------------------------------------
        if (
            self.taxpayer_type == "REGULAR"
            and self.turnover_details == "MORE_THAN_5CR"
            and self.filing_frequency == "QUARTERLY"
        ):
            raise ValueError("Quarterly filing not allowed for turnover > 5CR")

        # -------------------------------------------------
        # Filing Type vs Frequency Rules
        # -------------------------------------------------
        if self.filing_type in ["GSTR9", "GSTR9C"]:
            if self.filing_frequency != "YEARLY":
                raise ValueError(f"{self.filing_type} must be YEARLY")

        if self.filing_type == "CMP08":
            if self.filing_frequency != "QUARTERLY":
                raise ValueError("CMP08 must be QUARTERLY")

        if self.filing_type == "GSTR4":
            if self.filing_frequency != "YEARLY":
                raise ValueError("GSTR4 must be YEARLY")

        # -------------------------------------------------
        # Composition Scheme Rules
        # -------------------------------------------------
        if self.taxpayer_type == "COMPOSITION":
            if self.filing_type not in ["CMP08", "GSTR4"]:
                raise ValueError(
                    "Composition taxpayer cannot file this return type"
                )

        return self

class GSTFilingEditIn(BaseSchema):
    """
    GST Filing Edit Schema (ENTERPRISE LEVEL)
    ----------------------------------------
    ✔ Partial updates allowed
    ✔ Workflow-safe (status transitions controlled in API)
    ✔ Rule-engine aligned
    ✔ Prevents invalid business edits
    ✔ Production-grade validations
    """

    # =====================================================
    # BUSINESS FIELDS (CONTROLLED EDIT)
    # =====================================================
    filing_category: Optional[
        Literal["RETURN", "ANNUAL"]
    ] = None

    filing_frequency: Optional[
        Literal["MONTHLY", "QUARTERLY", "YEARLY"]
    ] = None

    taxpayer_type: Optional[
        Literal["REGULAR", "COMPOSITION"]
    ] = None

    turnover_details: Optional[
        Literal["LESS_THAN_5CR", "MORE_THAN_5CR"]
    ] = None

    state: Optional[str] = Field(None, max_length=50)

    # =====================================================
    # TIME FIELDS
    # =====================================================
    due_date: Optional[datetime] = None

    # =====================================================
    # GST LINK (SAFE UPDATE)
    # =====================================================
    gst_registration_id: Optional[int] = Field(None, gt=0)

    gstin: Optional[
        Annotated[str, Field(
            pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
        )]
    ] = None

    # =====================================================
    # STATUS CONTROL
    # =====================================================
    status: Optional[
        Literal[
            "DATA_PENDING",
            "DATA_RECEIVED",
            "IN_PREPARATION",
            "PENDING_OTP",
            "READY_TO_FILE",
            "FILED",
            "OVERDUE",
        ]
    ] = None

    priority: Optional[Literal["LOW", "NORMAL", "HIGH"]] = None

    remarks: Optional[str] = Field(None, max_length=500)

    # =====================================================
    # ASSIGNMENT
    # =====================================================
    rm_id: Optional[int] = Field(None, gt=0)
    op_id: Optional[int] = Field(None, gt=0)

    # =====================================================
    # FLAGS
    # =====================================================
    is_auto_enabled: Optional[bool] = None
    is_active: Optional[bool] = None

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
        "state",
        mode="before"
    )
    @classmethod
    def normalize_upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("remarks", mode="before")
    @classmethod
    def sanitize_remarks(cls, v):
        return html.escape(v.strip()) if isinstance(v, str) else v

    # =====================================================
    # VALIDATION (ADVANCED BUSINESS RULES)
    # =====================================================
    @model_validator(mode="after")
    def validate_logic(self):

        # -------------------------------------------------
        # GST SAFETY (DO NOT REMOVE BOTH)
        # -------------------------------------------------
        if self.gst_registration_id is not None or self.gstin is not None:
            if not self.gst_registration_id and not self.gstin:
                raise ValueError(
                    "Either gst_registration_id or gstin must remain present"
                )

        # -------------------------------------------------
        # STATUS SAFETY
        # -------------------------------------------------
        if self.status == "FILED":
            # filed_at handled in DB trigger
            pass

        # -------------------------------------------------
        # PRIORITY RULE
        # -------------------------------------------------
        if self.priority and self.priority not in ["LOW", "NORMAL", "HIGH"]:
            raise ValueError("Invalid priority value")

        # -------------------------------------------------
        # QRMP RULE (CRITICAL)
        # -------------------------------------------------
        if (
            self.taxpayer_type == "REGULAR"
            and self.turnover_details == "MORE_THAN_5CR"
            and self.filing_frequency == "QUARTERLY"
        ):
            raise ValueError(
                "Quarterly filing not allowed for turnover > 5CR"
            )

        # -------------------------------------------------
        # FILING TYPE vs FREQUENCY (STRICT)
        # -------------------------------------------------
        if self.filing_frequency:
            if self.filing_frequency == "YEARLY":
                if self.filing_category == "RETURN":
                    raise ValueError(
                        "RETURN filings cannot be YEARLY"
                    )

        # -------------------------------------------------
        # COMPOSITION RULE
        # -------------------------------------------------
        if self.taxpayer_type == "COMPOSITION":
            if self.filing_frequency == "MONTHLY":
                raise ValueError(
                    "Composition taxpayer cannot have MONTHLY filing"
                )

        # -------------------------------------------------
        # DUE DATE VALIDATION
        # -------------------------------------------------
        if self.due_date:
            if self.due_date.year < 2000:
                raise ValueError("Invalid due_date")

        return self