"""
One-off backfill (safe to re-run): advance CRM leads to SUBSCRIBED when their
linked GST registration OR income-tax record has already been fully PAID but the
lead never moved out of its DONE / SCHEDULED_PAYMENTS stage — i.e. payments that
completed *before* the payment-completion auto-sync landed.

It reuses the exact production code path, ``advance_crm_lead_stage_system``, so
every fixed lead also gets its SYSTEM ``crm_activities`` row (old_stage ->
SUBSCRIBED, NULL remark) and its follow-up closed, identical to a live payment
completion. Forward-only; leads already SUBSCRIBED / NOT_INTERESTED are left
untouched. Idempotent.

Run from the project root (``.env`` loads automatically via backend.utils):

    python -m backend.scripts.backfill_paid_crm_subscribed
"""
import asyncio
from typing import List

from backend.utils import get_db_pool, DB_SCHEMA
from backend.crm.crm_leads_common import (
    advance_crm_lead_stage_system,
    _invalidate_crm_cache,
)
from backend.redis_cache import is_redis_configured

# (entity_type, treat NULL entity_type as this funnel?, from_stages -> SUBSCRIBED)
_FUNNELS = (
    ("GST_REGISTRATION", True, ("GST_REGISTRATION_DONE", "SCHEDULED_PAYMENTS")),
    ("INCOME_TAX", False, ("ITR_DONE", "SCHEDULED_PAYMENTS")),
)


async def main() -> None:
    pool = await get_db_pool()
    synced_ids: List[int] = []

    async with pool.acquire() as conn:
        for entity_type, null_is_this_funnel, from_stages in _FUNNELS:
            # For GST, a NULL/blank lead entity_type is treated as GST_REGISTRATION.
            null_clause = (
                " OR NULLIF(trim(cl.entity_type), '') IS NULL"
                if null_is_this_funnel
                else ""
            )
            entity_rows = await conn.fetch(
                f"""
                SELECT DISTINCT cl.entity_id
                  FROM {DB_SCHEMA}.crm_leads cl
                 WHERE (upper(trim(cl.entity_type)) = $1{null_clause})
                   AND cl.is_active = TRUE
                   AND cl.stage = ANY($2::text[])
                   AND EXISTS (
                       SELECT 1
                         FROM {DB_SCHEMA}.payments p
                        WHERE p.entity_id = cl.entity_id
                          AND p.entity_type = $1
                          AND p.is_active = TRUE
                          AND p.payment_status = 'PAID'
                   )
                 ORDER BY cl.entity_id
                """,
                entity_type,
                list(from_stages),
            )
            print(
                f"[{entity_type}] Found {len(entity_rows)} fully-PAID entity(ies) "
                f"with a linked CRM lead not yet SUBSCRIBED."
            )
            for row in entity_rows:
                entity_id = int(row["entity_id"])
                async with conn.transaction():
                    ids = await advance_crm_lead_stage_system(
                        conn,
                        entity_id=entity_id,
                        entity_type=entity_type,
                        from_stages=from_stages,
                        to_stage="SUBSCRIBED",
                    )
                for lid in ids:
                    print(
                        f"  [{entity_type}] entity_id={entity_id} -> lead_id={lid} "
                        f"advanced to SUBSCRIBED (+ SYSTEM activity)"
                    )
                synced_ids.extend(ids)

    # Cache invalidation runs after commits so readers repopulate fresh data.
    for lid in synced_ids:
        await _invalidate_crm_cache(lid)

    # Always clear the GLOBAL CRM list caches too, so re-running also refreshes
    # the Leads UI for leads fixed out-of-band (a direct DB UPDATE bypasses the
    # app's cache invalidation).
    if not is_redis_configured():
        print(
            "WARNING: Redis is not configured in this environment — the stale "
            "Leads-list cache was NOT cleared. Run this where the app's Redis is "
            "reachable, or the UI will keep showing the cached stage."
        )
    else:
        await _invalidate_crm_cache()
        print("Cleared global CRM list caches (Leads UI will repopulate from DB).")

    print(f"Done. {len(synced_ids)} CRM lead(s) advanced to SUBSCRIBED.")


if __name__ == "__main__":
    asyncio.run(main())
