"""Scheduler jobs for payment ledger hygiene (entity-level settlement)."""

from __future__ import annotations

import logging

from backend.payments.crm_lead_sync import sync_crm_leads_from_promoted_payments
from backend.utils import DB_SCHEMA

logger = logging.getLogger(__name__)


async def sync_settled_payment_entities(conn, *, batch_limit: int = 500) -> dict[str, int]:
    """
    Keep payment list/filters aligned with entity settlement.

    Rules (per customer_id + entity_id + entity_type):
    1. Only one active PAID row — demote older duplicate PAIDs to PENDING.
    2. Latest row with remaining_amount <= 0 → PAID (if not already).
    3. When an active PAID row exists, superseded active PENDING installment rows
       are soft-closed (is_active=FALSE, remaining=0). We cannot mark them PAID
       because of uq_payments_paid (one PAID per entity).
    """
    stats = {
        "duplicate_paid_demoted": 0,
        "latest_promoted_to_paid": 0,
        "superseded_pending_closed": 0,
        "synced_crm_lead_ids": [],
    }

    # 1) Duplicate active PAID → PENDING (keep newest PAID only)
    demoted = await conn.execute(
        f"""
        UPDATE {DB_SCHEMA}.payments p
           SET payment_status = 'PENDING',
               updated_at = NOW()
         WHERE p.is_active IS TRUE
           AND p.payment_status = 'PAID'
           AND p.id IN (
               SELECT p2.id
                 FROM {DB_SCHEMA}.payments p2
                WHERE p2.is_active IS TRUE
                  AND p2.payment_status = 'PAID'
                  AND p2.id <> (
                      SELECT p3.id
                        FROM {DB_SCHEMA}.payments p3
                       WHERE p3.customer_id IS NOT DISTINCT FROM p2.customer_id
                         AND p3.entity_id = p2.entity_id
                         AND p3.entity_type = p2.entity_type
                         AND p3.is_active IS TRUE
                         AND p3.payment_status = 'PAID'
                       ORDER BY p3.created_at DESC, p3.id DESC
                       LIMIT 1
                  )
                LIMIT {batch_limit}
           )
        """
    )
    stats["duplicate_paid_demoted"] = _parse_update_count(demoted)

    # 2) Latest row fully settled but still PENDING → PAID
    promoted_rows = await conn.fetch(
        f"""
        UPDATE {DB_SCHEMA}.payments p
           SET payment_status = 'PAID',
               payment_date = COALESCE(p.payment_date, NOW()),
               updated_at = NOW()
         WHERE p.id IN (
               SELECT l.id
                 FROM (
                       SELECT DISTINCT ON (customer_id, entity_id, entity_type)
                              id,
                              remaining_amount,
                              payment_status
                         FROM {DB_SCHEMA}.payments
                        WHERE is_active IS TRUE
                          AND payment_status <> 'CANCELLED'
                        ORDER BY customer_id, entity_id, entity_type, created_at DESC, id DESC
                      ) l
                WHERE l.payment_status = 'PENDING'
                  AND COALESCE(l.remaining_amount, 0) <= 0
                LIMIT {batch_limit}
           )
         RETURNING p.*
        """
    )
    stats["latest_promoted_to_paid"] = len(promoted_rows)
    if promoted_rows:
        synced_ids = await sync_crm_leads_from_promoted_payments(conn, promoted_rows)
        stats["synced_crm_lead_ids"] = sorted(synced_ids)

    # 3) Entity already has PAID → soft-close other active PENDING rows (installment history)
    closed = await conn.execute(
        f"""
        UPDATE {DB_SCHEMA}.payments p
           SET is_active = FALSE,
               remaining_amount = 0,
               updated_at = NOW(),
               remarks = CASE
                   WHEN COALESCE(trim(p.remarks), '') = '' THEN
                       'Auto-closed: entity fully paid (scheduler).'
                   WHEN p.remarks ILIKE '%Auto-closed: entity fully paid%' THEN
                       p.remarks
                   ELSE
                       p.remarks || ' | Auto-closed: entity fully paid (scheduler).'
               END
         WHERE p.is_active IS TRUE
           AND p.payment_status = 'PENDING'
           AND EXISTS (
               SELECT 1
                 FROM {DB_SCHEMA}.payments paid
                WHERE paid.customer_id IS NOT DISTINCT FROM p.customer_id
                  AND paid.entity_id = p.entity_id
                  AND paid.entity_type = p.entity_type
                  AND paid.is_active IS TRUE
                  AND paid.payment_status = 'PAID'
           )
           AND p.id IN (
               SELECT id
                 FROM {DB_SCHEMA}.payments
                WHERE is_active IS TRUE
                  AND payment_status = 'PENDING'
                LIMIT {batch_limit}
           )
        """
    )
    stats["superseded_pending_closed"] = _parse_update_count(closed)

    return stats


def _parse_update_count(result: str) -> int:
    # asyncpg returns "UPDATE N"
    parts = (result or "").split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0
