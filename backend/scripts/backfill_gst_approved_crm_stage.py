"""
One-off backfill (safe to re-run): advance CRM leads whose linked GST
registration is already APPROVED but whose stage never got synced to
GST_REGISTRATION_DONE — i.e. registrations approved *before* the edit-endpoint
auto-sync landed.

It reuses the exact production code path, ``_sync_crm_leads_on_gst_approval``,
so every fixed lead also gets its SYSTEM ``crm_activities`` row, identical to a
live approval. Forward-only: leads already further along the funnel
(GST_REGISTRATION_DONE / SCHEDULED_PAYMENTS / SUBSCRIBED / NOT_INTERESTED) are
left untouched. Idempotent — a second run finds nothing to do.

Run from the project root (``.env`` loads automatically via backend.utils):

    python -m backend.scripts.backfill_gst_approved_crm_stage
"""
import asyncio
from typing import List

from backend.utils import get_db_pool, DB_SCHEMA
from backend.gst_registration.gst_registration import _sync_crm_leads_on_gst_approval
from backend.gst_registration.gst_registration_helpers import GST_CRM_ENTITY_TYPE
from backend.crm.crm_leads_common import _invalidate_crm_cache
from backend.redis_cache import is_redis_configured


async def main() -> None:
    pool = await get_db_pool()
    synced_ids: List[int] = []

    async with pool.acquire() as conn:
        gst_rows = await conn.fetch(
            f"""
            SELECT DISTINCT g.id
              FROM {DB_SCHEMA}.gst_registration g
              JOIN {DB_SCHEMA}.crm_leads cl
                ON cl.entity_id = g.id
               AND (cl.entity_type = $1 OR cl.entity_type IS NULL)
             WHERE g.is_active = TRUE
               AND g.registration_status = 'APPROVED'
               AND cl.is_active = TRUE
               AND cl.stage IN (
                   'FRESH_LEAD',
                   'PENDING_REGISTRATION_DATA',
                   'FOLLOW_UP',
                   'INTERESTED'
               )
             ORDER BY g.id
            """,
            GST_CRM_ENTITY_TYPE,
        )
        print(
            f"Found {len(gst_rows)} APPROVED GST registration(s) "
            f"with a linked CRM lead still in a pre-completion stage."
        )

        for row in gst_rows:
            gst_id = int(row["id"])
            async with conn.transaction():
                ids = await _sync_crm_leads_on_gst_approval(conn, gst_id)
            for lid in ids:
                print(
                    f"  gst_id={gst_id} -> lead_id={lid} "
                    f"advanced to GST_REGISTRATION_DONE (+ SYSTEM activity)"
                )
            synced_ids.extend(ids)

    # Cache invalidation runs after commits so readers repopulate fresh data.
    for lid in synced_ids:
        await _invalidate_crm_cache(lid)

    # Always clear the GLOBAL CRM list caches too — even when nothing was synced
    # this run. This refreshes the Leads UI for any lead whose stage was fixed
    # out-of-band (a direct DB UPDATE, which bypasses the app's cache
    # invalidation), so a stale PENDING_REGISTRATION_DATA no longer sticks.
    if not is_redis_configured():
        print(
            "WARNING: Redis is not configured in this environment — the stale "
            "Leads-list cache was NOT cleared. Run this where the app's Redis is "
            "reachable, or the UI will keep showing the cached stage."
        )
    else:
        await _invalidate_crm_cache()
        print("Cleared global CRM list caches (Leads UI will repopulate from DB).")

    print(f"Done. {len(synced_ids)} CRM lead(s) advanced.")


if __name__ == "__main__":
    asyncio.run(main())
