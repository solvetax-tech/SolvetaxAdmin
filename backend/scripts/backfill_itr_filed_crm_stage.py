"""
One-off backfill (safe to re-run): advance CRM leads to ITR_DONE when their
linked income-tax record is already FILED but the lead never moved out of its
pre-completion stage — i.e. records filed *before* the ITR-filed auto-sync landed.

Mirror of backfill_gst_approved_crm_stage for the ITR funnel. Reuses the exact
production path, ``advance_crm_lead_stage_system``, so every fixed lead also gets
its SYSTEM ``crm_activities`` row (NULL remark) and its follow-up closed.
Forward-only; leads already further along the funnel are untouched. Idempotent.

Run from the project root (``.env`` loads automatically via backend.utils):

    python -m backend.scripts.backfill_itr_filed_crm_stage
"""
import asyncio
from typing import List

from backend.utils import get_db_pool, DB_SCHEMA
from backend.crm.crm_leads_common import (
    advance_crm_lead_stage_system,
    _invalidate_crm_cache,
)
from backend.redis_cache import is_redis_configured

_ITR_FROM_STAGES = ("FRESH_LEAD", "PENDING_ITR_DATA", "FOLLOW_UP", "INTERESTED")


async def main() -> None:
    pool = await get_db_pool()
    synced_ids: List[int] = []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT i.id
              FROM {DB_SCHEMA}.income_tax i
              JOIN {DB_SCHEMA}.crm_leads cl
                ON cl.entity_id = i.id
               AND upper(trim(cl.entity_type)) = 'INCOME_TAX'
             WHERE i.is_active = TRUE
               AND i.filed_status = 'FILED'
               AND cl.is_active = TRUE
               AND cl.stage = ANY($1::text[])
             ORDER BY i.id
            """,
            list(_ITR_FROM_STAGES),
        )
        print(
            f"Found {len(rows)} FILED income-tax record(s) with a linked CRM lead "
            f"not yet at ITR_DONE."
        )
        for row in rows:
            itr_id = int(row["id"])
            async with conn.transaction():
                ids = await advance_crm_lead_stage_system(
                    conn,
                    entity_id=itr_id,
                    entity_type="INCOME_TAX",
                    from_stages=_ITR_FROM_STAGES,
                    to_stage="ITR_DONE",
                )
            for lid in ids:
                print(
                    f"  income_tax_id={itr_id} -> lead_id={lid} "
                    f"advanced to ITR_DONE (+ SYSTEM activity)"
                )
            synced_ids.extend(ids)

    # Cache invalidation runs after commits so readers repopulate fresh data.
    for lid in synced_ids:
        await _invalidate_crm_cache(lid)

    if not is_redis_configured():
        print(
            "WARNING: Redis is not configured in this environment — the stale "
            "Leads-list cache was NOT cleared. Run this where the app's Redis is "
            "reachable, or the UI will keep showing the cached stage."
        )
    else:
        await _invalidate_crm_cache()
        print("Cleared global CRM list caches (Leads UI will repopulate from DB).")

    print(f"Done. {len(synced_ids)} CRM lead(s) advanced to ITR_DONE.")


if __name__ == "__main__":
    asyncio.run(main())
