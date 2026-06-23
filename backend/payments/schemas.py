from typing import Optional

from pydantic import BaseModel, Field, condecimal


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


class RegistrationPaymentIn(BaseSchema):

    entity_id: int = Field(..., example=55)

    amount: condecimal(max_digits=12, decimal_places=2) = Field(
        ...,
        example=699.00
    )

    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=100
    )

    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=500
    )

    remarks: Optional[str] = Field(
        default=None,
        example="Advance collected"
    )


class CustomerServicePaymentIn(BaseSchema):
    """entity_id is customer_services.id; stored as payments.entity_type=CUSTOMER_SERVICE."""

    entity_id: int = Field(..., description="customer_services.id", example=101)

    amount: condecimal(max_digits=12, decimal_places=2) = Field(
        ...,
        example=699.00,
    )

    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=100,
    )

    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=500,
    )

    remarks: Optional[str] = Field(
        default=None,
        example="Advance collected",
    )


class GstFilingReturnDetailsPaymentIn(BaseSchema):
    """entity_id is gst_filing_return_details.id (per-period return row)."""

    entity_id: int = Field(..., description="gst_filing_return_details.id", example=501)

    amount: condecimal(max_digits=12, decimal_places=2) = Field(
        ...,
        example=699.00,
    )

    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=100,
    )

    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=500,
    )

    remarks: Optional[str] = Field(
        default=None,
        example="Advance collected",
    )


class FilingPaymentIn(BaseSchema):

    entity_id: int = Field(..., example=55)

    customer_id: Optional[int] = Field(
        default=None,
        gt=0,
        description=(
            "Optional. Used for INCOME_TAX payments when linking to solvetax.customers; "
            "stored on payments.customer_id. Omit or null when the ITR row has no customer."
        ),
        example=42,
    )

    amount: condecimal(max_digits=12, decimal_places=2) = Field(
        ...,
        example=699.00
    )

    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=100
    )

    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=500
    )

    remarks: Optional[str] = Field(
        default=None,
        example="Advance collected"
    )