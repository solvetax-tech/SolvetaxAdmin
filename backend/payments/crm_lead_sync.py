"""Sync CRM leads when registration/ITR payments become PAID (replaces DB trigger)."""

from typing import Any, Mapping, Optional, Set

import asyncpg

from backend.utils import DB_SCHEMA

SUBSCRIBED_STAGE = "SUBSCRIBED"
NOT_INTERESTED_STAGE = "NOT_INTERESTED"
GST_REGISTRATION_ENTITY = "GST_REGISTRATION"
INCOME_TAX_ENTITY = "INCOME_TAX"
GST_ELIGIBLE_STAGES = frozenset({"GST_REGISTRATION_DONE", "SCHEDULED_PAYMENTS"})
ITR_ELIGIBLE_STAGES = frozenset({"ITR_DONE", "SCHEDULED_PAYMENTS"})


async def sync_crm_lead_from_payment_paid(
    conn: asyncpg.Connection,
    payment_row: Mapping[str, Any],
    *,
    old_payment_status: Optional[str] = None,
) -> Optional[int]:
    """
    Mirror ``solvetax.fn_sync_payment_paid_to_crm``.

    When ``payment_status`` becomes ``PAID`` for ``GST_REGISTRATION`` or ``INCOME_TAX``,
    move the linked CRM lead to ``SUBSCRIBED`` when stage rules allow.
    Returns ``crm_leads.id`` when a lead was found, else ``None``.
    """
    payment_status = str(payment_row.get("payment_status") or "").strip().upper()
    if payment_status != "PAID":
        return None

    if old_payment_status is not None:
        old_norm = str(old_payment_status).strip().upper()
        if old_norm == "PAID":
            return None

    entity_type_norm = str(payment_row.get("entity_type") or "").strip().upper()
    if entity_type_norm not in (GST_REGISTRATION_ENTITY, INCOME_TAX_ENTITY):
        return None

    entity_id = payment_row.get("entity_id")
    if entity_id is None:
        return None

    lead_row = await conn.fetchrow(
        f"""
        SELECT l.id, l.stage
          FROM {DB_SCHEMA}.crm_leads l
         WHERE upper(trim(l.entity_type::text)) = $1
           AND l.entity_id = $2
           AND l.is_active = TRUE
         ORDER BY l.id DESC
         LIMIT 1
         FOR UPDATE
        """,
        entity_type_norm,
        entity_id,
    )

    if not lead_row:
        return None

    lead_id = lead_row["id"]
    old_stage = lead_row["stage"]

    if old_stage in (SUBSCRIBED_STAGE, NOT_INTERESTED_STAGE):
        return lead_id

    if entity_type_norm == GST_REGISTRATION_ENTITY and old_stage not in GST_ELIGIBLE_STAGES:
        return lead_id

    if entity_type_norm == INCOME_TAX_ENTITY and old_stage not in ITR_ELIGIBLE_STAGES:
        return lead_id

    new_stage = SUBSCRIBED_STAGE

    updated = await conn.fetchrow(
        f"""
        UPDATE {DB_SCHEMA}.crm_leads
           SET stage = $1,
               updated_at = NOW()
         WHERE id = $2
         RETURNING stage
        """,
        new_stage,
        lead_id,
    )

    if not updated:
        return lead_id

    final_stage = updated["stage"]
    if old_stage != final_stage:
        await conn.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.crm_activities (
                lead_id,
                entity_type,
                activity_type,
                old_stage,
                new_stage,
                remarks,
                performed_by,
                performed_at,
                created_at
            )
            VALUES ($1, $2, 'SYSTEM', $3, $4, $5, NULL, NOW(), NOW())
            """,
            lead_id,
            entity_type_norm,
            old_stage,
            final_stage,
            "Auto moved to SUBSCRIBED on payment_status=PAID",
        )

    return lead_id


async def sync_crm_leads_from_promoted_payments(
    conn: asyncpg.Connection,
    promoted_rows: list[Mapping[str, Any]],
) -> Set[int]:
    """Run CRM sync for scheduler-promoted payment rows; returns affected lead ids."""
    lead_ids: set[int] = set()
    for row in promoted_rows:
        lead_id = await sync_crm_lead_from_payment_paid(
            conn,
            row,
            old_payment_status="PENDING",
        )
        if lead_id is not None:
            lead_ids.add(int(lead_id))
    return lead_ids
