"""Shared DB helpers for entity-level payment ledger (all payment routers)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import asyncpg
from fastapi import HTTPException

from backend.payments.payment_ledger import (
    PaymentLedgerError,
    compute_entity_balance,
    compute_payment_ledger,
    ledger_error_to_http,
    money,
)
from backend.utils import DB_SCHEMA, build_registration_payments_visibility

__all__ = [
    "EntityPaymentTotals",
    "fetch_entity_payment_totals",
    "lock_entity_payment_rows",
    "has_completed_payment",
    "insert_payment_from_ledger",
    "resolve_ledger_for_create",
    "ledger_error_to_http",
    "assert_payment_visible",
]


async def assert_payment_visible(
    conn: asyncpg.Connection,
    role_norm: Optional[str],
    emp_id: Optional[int],
    payment_id: int,
    not_found_detail: str = "Payment not found.",
) -> None:
    """IDOR guard for by-id payment mutations.

    Verifies the caller can see the payment using the SAME COALESCE(customer →
    entity) rm/op ownership as the unified payments list. ADMIN bypasses;
    raises 404 when the payment isn't visible to the caller.
    """
    visibility_sql, visibility_values, _ = build_registration_payments_visibility(
        role_norm or "", emp_id, 2, DB_SCHEMA,
    )
    if not visibility_sql:
        return  # ADMIN → unrestricted
    visible = await conn.fetchval(
        f"""
        SELECT 1
        FROM {DB_SCHEMA}.payments rp
        LEFT JOIN {DB_SCHEMA}.customers c
               ON rp.customer_id = c.customer_id
        LEFT JOIN {DB_SCHEMA}.gst_registration g
               ON rp.entity_type = 'GST_REGISTRATION' AND rp.entity_id = g.id
        LEFT JOIN {DB_SCHEMA}.income_tax i
               ON rp.entity_type = 'INCOME_TAX' AND rp.entity_id = i.id
        LEFT JOIN {DB_SCHEMA}.gst_filings f
               ON rp.entity_type = 'GST_FILING' AND rp.entity_id = f.id
        LEFT JOIN {DB_SCHEMA}.gst_filing_return_details rd
               ON rp.entity_type = 'GST_FILING_RETURN_DETAILS' AND rp.entity_id = rd.id
        LEFT JOIN {DB_SCHEMA}.gst_filings f_rd
               ON f_rd.id = rd.gst_filing_id
        LEFT JOIN {DB_SCHEMA}.customer_services cs
               ON rp.entity_type = 'CUSTOMER_SERVICE' AND rp.entity_id = cs.id
        WHERE rp.id = $1 AND ({visibility_sql})
        LIMIT 1
        """,
        payment_id, *visibility_values,
    )
    if not visible:
        raise HTTPException(status_code=404, detail=not_found_detail)


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

    - amount: the entity's list price. It is set ONCE by the first payment and
      FIXED thereafter — later installments always reuse the first row's amount
      and the caller's requested value is ignored, so it can never change after
      the first payment.
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
        # First payment: the requested amount sets (and locks) the list price.
        original_amount = money(first_payment_amount)
        total_discount_prior = 0.0
    else:
        # Already has payments: the list price is fixed to the first row's
        # amount; ignore any requested value so it cannot change afterwards.
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
    row = await conn.fetchrow(
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
            payment_date,
            remarks,
            created_at,
            updated_at
        )
        VALUES (
            NULL, $1, $2, $3, $4, $5, $6, $7, $8, $9,
            -- Stamp the payment date only when real cash was collected this
            -- installment (paid_amount > 0). $6 is paid_amount.
            CASE WHEN $6 > 0 THEN NOW() ELSE NULL END,
            $10, NOW(), NOW()
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

    # When this installment settles the entity (remaining <= 0 ⇒ PAID), reflect
    # the completed state on every OTHER row for the entity. Otherwise an earlier
    # installment keeps its historical PENDING snapshot and the payments list
    # shows a fully-paid entity as part PENDING / part PAID. Inactive (soft-
    # deleted) rows are included on purpose — the list shows them
    # (include_inactive) and the ledger already ignores them (is_active filter),
    # so this is a display-only reconciliation with no effect on the math.
    if ledger["payment_status"] == "PAID":
        # NOTE: earlier installment rows KEEP their historical PENDING snapshot
        # in the DB. The uq_payments_paid unique index allows only ONE active
        # PAID row per entity, so we must not stamp siblings PAID here. The
        # payments list instead shows a settled entity's rows as PAID/remaining-0
        # via a display-level override (the `entity_settled` column), which keeps
        # the data model + integrity index intact while the UI reads "all paid".

        # Collecting the full amount closes any open payment-collection
        # follow-up for the entity — there is nothing left to chase. The
        # trg_payments_followup_completed_at trigger stamps completed_at when
        # followup_status flips to COMPLETED (satisfying chk_followup_completed_fields).
        await conn.execute(
            f"""
            UPDATE {schema}.payments
               SET followup_status = 'COMPLETED',
                   updated_at = NOW()
             WHERE customer_id IS NOT DISTINCT FROM $1
               AND entity_id = $2
               AND entity_type = $3
               AND is_active = TRUE
               AND followup_status IN ('PENDING', 'MISSED')
            """,
            customer_id,
            entity_id,
            entity_type,
        )

    return row
