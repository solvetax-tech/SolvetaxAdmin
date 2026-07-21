"""
One-off backfill (safe to re-run): once an entity's payment is fully settled it
has a PAID ``payments`` row, so every OTHER active installment row for the same
(customer_id, entity_id, entity_type) should also read PAID with remaining 0.

This matches the live behaviour now in ``insert_payment_from_ledger`` and fixes
entities that were completed BEFORE that landed — where an earlier installment
kept its historical PENDING snapshot and the payments list showed the entity as
part PENDING / part PAID (e.g. entity_id 22 CUSTOMER_SERVICE).

Idempotent — rows already PAID/CANCELLED are untouched. Run from the project
root (``.env`` loads automatically via backend.utils):

    python -m backend.scripts.backfill_completed_payment_rows_paid
"""
import asyncio

from backend.utils import get_db_pool, DB_SCHEMA
from backend.payments.payment_cache_invalidation import invalidate_payment_related_caches
from backend.redis_cache import is_redis_configured


async def main() -> None:
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetch(
                f"""
                UPDATE {DB_SCHEMA}.payments p
                   SET payment_status = 'PAID',
                       remaining_amount = 0,
                       updated_at = NOW()
                 WHERE p.payment_status NOT IN ('PAID', 'CANCELLED')
                   AND EXISTS (
                       SELECT 1
                         FROM {DB_SCHEMA}.payments q
                        WHERE q.customer_id IS NOT DISTINCT FROM p.customer_id
                          AND q.entity_id = p.entity_id
                          AND q.entity_type = p.entity_type
                          AND q.is_active = TRUE
                          AND q.payment_status = 'PAID'
                   )
                RETURNING p.id, p.entity_type, p.entity_id, p.is_active
                """
            )

    for r in updated:
        state = "active" if r["is_active"] else "inactive"
        print(
            f"  reconciled payment id={r['id']} "
            f"({r['entity_type']} entity_id={r['entity_id']}, {state}) -> PAID"
        )
    print(f"Done. {len(updated)} installment row(s) marked PAID.")

    # A direct DB UPDATE bypasses the app's cache invalidation, so clear the
    # payment list + config caches (and related surfaces) here too.
    if not is_redis_configured():
        print(
            "WARNING: Redis is not configured in this environment — the stale "
            "payments-list cache was NOT cleared. Run this where the app's Redis "
            "is reachable, or the UI will keep showing the cached status."
        )
    else:
        await invalidate_payment_related_caches(
            gst_filing=True, customer_service=True, crm=True
        )
        print("Cleared payment-related caches (payments list will repopulate from DB).")


if __name__ == "__main__":
    asyncio.run(main())
