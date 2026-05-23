"""
Entity-level payment ledger math for solvetax.payments.

Each row stores:
- amount: original list price (same on every installment for an entity)
- discount: increment for this row only (not cumulative)
- paid_amount: cash collected on this row only
- net_amount: original - sum(all discounts including this row)
- remaining_amount: balance still owed on the entity after this row
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


class PaymentLedgerError(Exception):
    def __init__(self, code: str, message: str, **context: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


def money(value: float | int | str | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_entity_balance(
    original_amount: float,
    total_discount: float,
    total_paid: float,
) -> tuple[float, float]:
    """
    Read-side totals for an entity (e.g. payments_config get-amount).

    net_amount = amount - sum(discounts)
    remaining  = net_amount - sum(paid)
    """
    net_amount = money(original_amount - total_discount)
    remaining_amount = money(net_amount - total_paid)
    return net_amount, remaining_amount


def compute_payment_ledger(
    *,
    original_amount: float,
    total_discount_prior: float,
    total_paid_prior: float,
    new_discount: float,
    paid_amount: float,
) -> dict[str, float | str]:
    """
    Compute values to persist on a new payments row.

    Entity balance after this row:
        remaining = original - discounts_all - paid_all
    """
    original_amount = money(original_amount)
    total_discount_prior = money(total_discount_prior)
    total_paid_prior = money(total_paid_prior)
    new_discount = money(new_discount or 0)
    paid_amount = money(paid_amount or 0)

    remaining_before_discount = money(
        original_amount - total_discount_prior - total_paid_prior
    )

    if remaining_before_discount <= 0:
        raise PaymentLedgerError(
            "already_completed",
            "Payment already completed.",
        )

    if new_discount < 0:
        raise PaymentLedgerError("negative_discount", "Discount cannot be negative.")

    if new_discount > remaining_before_discount:
        raise PaymentLedgerError(
            "discount_exceeds",
            f"Discount cannot exceed remaining amount ({remaining_before_discount}).",
        )

    if paid_amount < 0:
        raise PaymentLedgerError("negative_paid", "Paid amount cannot be negative.")

    if paid_amount <= 0 and new_discount <= 0:
        raise PaymentLedgerError(
            "paid_required",
            "Provide paid_amount and/or discount for this installment.",
        )

    total_discount_after = money(total_discount_prior + new_discount)
    remaining_after_discount = money(
        original_amount - total_discount_after - total_paid_prior
    )

    if paid_amount > remaining_after_discount:
        raise PaymentLedgerError(
            "paid_exceeds",
            f"Paid amount exceeds remaining balance ({remaining_after_discount}).",
        )

    net_amount = money(original_amount - total_discount_after)
    entity_remaining = money(remaining_after_discount - paid_amount)

    # Fully settled when cash + discounts cover the original price for this entity.
    payment_status = "PAID" if entity_remaining <= 0 else "PENDING"

    return {
        "original_amount": original_amount,
        "row_discount": new_discount,
        "paid_amount": paid_amount,
        "net_amount": net_amount,
        "remaining_amount": max(0.0, entity_remaining),
        "payment_status": payment_status,
        "remaining_before_discount": remaining_before_discount,
        "remaining_after_discount": remaining_after_discount,
        "total_discount_after": total_discount_after,
    }


def ledger_error_to_http(exc: PaymentLedgerError):
    from fastapi import HTTPException

    code = exc.code
    if code == "already_completed":
        status = 409
    elif code in {"discount_exceeds", "paid_exceeds", "paid_required", "negative_discount", "negative_paid"}:
        status = 400
    else:
        status = 400
    return HTTPException(status_code=status, detail=exc.message)
