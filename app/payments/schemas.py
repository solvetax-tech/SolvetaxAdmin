from pydantic import BaseModel, condecimal, Field
from typing import Optional
from decimal import Decimal


class RegistrationPaymentIn(BaseModel):
    customer_id: int = Field(..., example=101)
    entity_id: int = Field(..., example=55)

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





class RegistrationPaymentEditIn(BaseModel):
    discount: Optional[condecimal(max_digits=12, decimal_places=2)] = None
    paid_amount: Optional[condecimal(max_digits=12, decimal_places=2)] = None
    remarks: Optional[str] = None