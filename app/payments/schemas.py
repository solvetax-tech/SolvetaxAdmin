from pydantic import BaseModel, condecimal, Field
from typing import Optional
from decimal import Decimal

from pydantic import Field, condecimal
from typing import Optional
from decimal import Decimal


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

    ownership_category: str = Field(
        ...,
        example="PROPRIETOR",
        description="Ownership category selected from UI (value from payment_config table)"
    )

    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=200.00
    )

    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = Field(
        default=0,
        example=500.00
    )

    remarks: Optional[str] = Field(
        default=None,
        example="Advance collected"
    )
    
class RegistrationPaymentEditIn(BaseSchema):
    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = None
    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = None
    remarks: Optional[str] = None