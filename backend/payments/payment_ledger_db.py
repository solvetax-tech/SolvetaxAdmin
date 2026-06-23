"""Shared DB helpers for entity-level payment ledger (all payment routers)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import asyncpg

from backend.payments.payment_ledger import (
    PaymentLedgerError,
    compute_entity_balance,
    compute_payment_ledger,
    ledger_error_to_http,
    money,
)

__all__ = [
    "EntityPaymentTotals",
    "fetch_entity_payment_totals",
    "lock_entity_payment_rows",
    "has_completed_payment",
    "insert_payment_from_ledger",
    "resolve_ledger_for_create",
    "ledger_error_to_http",
]


@dataclass(frozen=True)
class EntityPaymentTotals:
    original_amount: float
    total_discount_prior: float
    total_paid_prior: float


def _entity_where(param_customer: str = "$1") -> str:
    return f"""
        customer_id IS NOT DISTINCT FROM {param_customer}
        AND entity_id = $2
        AND entity_type = $3
        AND is_active = TRUE
        AND payment_status != 'CANCELLED'
    """


async def lock_entity_payment_rows(
    conn: asyncpg.Connection,
    schema: str,
    customer_id: Optional[int],
    entity_id: int,
    entity_type: str,
) -> None:
    await conn.fetch(
        f"""
        SELECT id
          FROM {schema}.payments
         WHERE {_entity_where()}
         FOR UPDATE
        """,
        customer_id,
        entity_id,
        entity_type,
    )


async def has_completed_payment(
    conn: asyncpg.Connection,
    schema: str,
    customer_id: Optional[int],
    entity_id: int,
    entity_type: str,
) -> bool:
    row = await conn.fetchrow(
        f"""
        SELECT 1
          FROM {schema}.payments
         WHERE {_entity_where()}
           AND payment_status = 'PAID'
         LIMIT 1
        """,
        customer_id,
        entity_id,
        entity_type,
    )
    return row is not None


async def fetch_entity_payment_totals(
    conn: asyncpg.Connection,
    schema: str,
    customer_id: Optional[int],
    entity_id: int,
    entity_type: str,
    *,
    first_payment_amount: float,
) -> EntityPaymentTotals:
    """
    Load totals for an entity before inserting a new payment row.

    - amount: first row's list price (or first_payment_amount when none)
    - total_discount_prior: SUM(discount) — each row must store incremental discount
    - total_paid_prior: SUM(paid_amount)
    """
    base_row = await conn.fetchrow(
        f"""
        SELECT
            (
                SELECT amount
                  FROM {schema}.payments
                 WHERE {_entity_where()}
                 ORDER BY created_at ASC, id ASC
                 LIMIT 1
            ) AS original_amount,
            COALESCE(SUM(discount), 0) AS total_discount
          FROM {schema}.payments
         WHERE {_entity_where()}
        """,
        customer_id,
        entity_id,
        entity_type,
    )

    if not base_row or base_row["original_amount"] is None:
        original_amount = money(first_payment_amount)
        total_discount_prior = 0.0
    else:
        original_amount = money(base_row["original_amount"])
        total_discount_prior = money(base_row["total_discount"] or 0)

    paid_row = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(paid_amount), 0) AS total_paid
          FROM {schema}.payments
         WHERE {_entity_where()}
        """,
        customer_id,
        entity_id,
        entity_type,
    )
    total_paid_prior = money(paid_row["total_paid"] or 0)

    return EntityPaymentTotals(
        original_amount=original_amount,
        total_discount_prior=total_discount_prior,
        total_paid_prior=total_paid_prior,
    )


def resolve_ledger_for_create(
    totals: EntityPaymentTotals,
    *,
    new_discount: float,
    paid_amount: float,
) -> dict[str, Any]:
    """Validate and compute row values for INSERT."""
    return compute_payment_ledger(
        original_amount=totals.original_amount,
        total_discount_prior=totals.total_discount_prior,
        total_paid_prior=totals.total_paid_prior,
        new_discount=new_discount,
        paid_amount=paid_amount,
    )


async def insert_payment_from_ledger(
    conn: asyncpg.Connection,
    schema: str,
    *,
    customer_id: Optional[int],
    entity_id: int,
    entity_type: str,
    ledger: dict[str, Any],
    remarks: Optional[str],
) -> asyncpg.Record:
    """
    Persist one payment row.

    Columns:
      amount          — list price (constant per entity)
      discount        — increment this installment only
      paid_amount     — cash this installment only
      net_amount      — amount - sum(all discounts including this row)
      remaining_amount — net - sum(all paid including this row)
    """
    return await conn.fetchrow(
        f"""
        INSERT INTO {schema}.payments (
            transaction_id,
            customer_id,
            entity_id,
            entity_type,
            amount,
            discount,
            paid_amount,
            net_amount,
            remaining_amount,
            payment_status,
            remarks,
            created_at,
            updated_at
        )
        VALUES (
            NULL, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), NOW()
        )
        RETURNING *
        """,
        customer_id,
        entity_id,
        entity_type,
        ledger["original_amount"],
        ledger["row_discount"],
        ledger["paid_amount"],
        ledger["net_amount"],
        ledger["remaining_amount"],
        ledger["payment_status"],
        remarks,
    )
