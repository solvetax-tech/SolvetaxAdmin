"""Sync CRM ITR leads when income_tax rows change (replaces DB trigger)."""

from typing import Any, Mapping, Optional

import asyncpg

from backend.Income_tax.income_tax_helpers import INCOME_TAX_CRM_ENTITY_TYPE
from backend.utils import DB_SCHEMA

ITR_DONE_STAGE = "ITR_DONE"
SUBSCRIBED_STAGE = "SUBSCRIBED"


async def sync_crm_lead_from_income_tax(
    conn: asyncpg.Connection,
    income_tax_row: Mapping[str, Any],
) -> Optional[int]:
    """
    Mirror ``solvetax.fn_sync_crm_lead_from_income_tax``.

    Updates the active CRM lead linked to this income tax record and logs a SYSTEM
    activity when stage changes. Returns ``crm_leads.id`` when a lead was found,
    else ``None``.
    """
    income_tax_id = income_tax_row["id"]
    filed_status = str(income_tax_row.get("filed_status") or "").strip().upper()
    filed = filed_status == "FILED"

    lead_row = await conn.fetchrow(
        f"""
        SELECT l.id, l.stage
          FROM {DB_SCHEMA}.crm_leads l
         WHERE l.entity_type = $1
           AND l.entity_id = $2
           AND l.is_active = TRUE
         ORDER BY l.id DESC
         LIMIT 1
         FOR UPDATE
        """,
        INCOME_TAX_CRM_ENTITY_TYPE,
        income_tax_id,
    )

    if not lead_row:
        return None

    lead_id = lead_row["id"]
    old_stage = lead_row["stage"]

    if old_stage == SUBSCRIBED_STAGE:
        return lead_id

    new_stage = ITR_DONE_STAGE if filed else old_stage

    updated = await conn.fetchrow(
        f"""
        UPDATE {DB_SCHEMA}.crm_leads l
           SET mobile = $1,
               entity_id = $2,
               entity_type = $3,
               is_active = $4,
               stage = CASE
                         WHEN l.stage = $5 THEN l.stage
                         ELSE $6
                       END,
               updated_at = NOW()
         WHERE l.id = $7
         RETURNING l.stage
        """,
        income_tax_row.get("mobile"),
        income_tax_id,
        INCOME_TAX_CRM_ENTITY_TYPE,
        income_tax_row.get("is_active"),
        SUBSCRIBED_STAGE,
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
            INCOME_TAX_CRM_ENTITY_TYPE,
            old_stage,
            final_stage,
            "Auto stage sync from income tax update",
        )

    return lead_id
