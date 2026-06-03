"""
Idempotent performance-index bootstrap.

This repo has no migration framework, so required performance indexes are ensured at
startup with ``CREATE INDEX CONCURRENTLY IF NOT EXISTS``. Each statement:
  * is a no-op once the index exists (cheap catalog check), and
  * runs CONCURRENTLY so it never takes a long write lock on a populated table.

Why this exists:

* ``customer_services`` only had a PENDING-scoped partial index on ``followup_at``. The
  follow-up ``/counts`` and list endpoints scan ALL followup_status values across a date
  range, so that partial index is unusable and Postgres fell back to a sequential scan.

* ``payments`` has ``idx_payments_followup_pending`` scoped to
  ``followup_status = 'PENDING' AND is_active = TRUE``. The payment-followups list always
  filters ``payment_status = 'PENDING'`` but did not filter ``is_active``, so the planner
  could not use that index. The broad ``payment_status`` partial index below fixes that;
  the entity_type composite helps the ``entity_type = ANY(...)`` filter.
"""
from __future__ import annotations

import logging

from app.utils import DB_SCHEMA, get_db_pool

logger = logging.getLogger(__name__)

# NOTE: CONCURRENTLY cannot run inside a transaction block; asyncpg ``execute`` runs in
# autocommit, so each statement is issued on its own.
_INDEX_STATEMENTS: tuple[str, ...] = (
    f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_followup_at
      ON {DB_SCHEMA}.customer_services (followup_at)
      WHERE followup_at IS NOT NULL
    """,
    f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_rm_followup
      ON {DB_SCHEMA}.customer_services (rm_id, followup_at)
      WHERE followup_at IS NOT NULL
    """,
    f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_op_followup
      ON {DB_SCHEMA}.customer_services (op_id, followup_at)
      WHERE followup_at IS NOT NULL
    """,
    f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_service_code_norm
      ON {DB_SCHEMA}.customer_services (upper(btrim(service_code)))
    """,
    f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_followup_at
      ON {DB_SCHEMA}.payments (followup_at)
      WHERE followup_at IS NOT NULL AND payment_status = 'PENDING'
    """,
    f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_followup_entity_at
      ON {DB_SCHEMA}.payments (entity_type, followup_at)
      WHERE followup_at IS NOT NULL
        AND payment_status = 'PENDING'
        AND is_active = TRUE
    """,
)


async def ensure_performance_indexes() -> None:
    """Best-effort, idempotent. Never raises into the caller."""
    try:
        pool = await get_db_pool()
    except Exception:
        logger.warning("ensure_performance_indexes: DB pool unavailable; skipping", exc_info=True)
        return

    for stmt in _INDEX_STATEMENTS:
        label = " ".join(stmt.split())[:120]
        try:
            async with pool.acquire() as conn:
                await conn.execute(stmt)
            logger.info("ensure_performance_indexes: ok | %s", label)
        except Exception:
            # A failed CONCURRENTLY build (or perms issue) must not crash the app.
            logger.warning("ensure_performance_indexes: failed | %s", label, exc_info=True)
