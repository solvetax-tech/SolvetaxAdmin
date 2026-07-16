-- ============================================================================
-- Follow-up performance indexes
--
-- These moved out of backend/db_indexes.py, which created them at every app
-- startup via CREATE INDEX CONCURRENTLY IF NOT EXISTS. That mechanism is
-- retired: it re-ran 6 statements on every boot, and it had a permanent failure
-- mode -- a CONCURRENTLY build that dies partway leaves an INVALID index, and
-- IF NOT EXISTS then matches the name forever after, so it is never repaired.
-- That is exactly how idx_customer_services_followup_at sat INVALID on the old
-- Canada server for months: taking space, ignored by the planner, silently
-- skipped by pg_dump, and never rebuilt despite running at every boot.
--
-- They are already present on solvetaxadmindev (the startup task created them
-- after the 2026-07-16 migration), so this file is a no-op there. It exists so
-- the definitions live in version control and can be applied to any new
-- environment -- previously they existed NOWHERE except inside the live DB.
--
-- WHY THESE COLUMNS (from the original docstring, preserved):
--   * customer_services only had a PENDING-scoped partial index on followup_at.
--     The follow-up /counts and list endpoints scan ALL followup_status values
--     across a date range, so that partial index is unusable.
--   * payments has idx_payments_followup_pending scoped to
--     followup_status = 'PENDING' AND is_active = TRUE. The payment-followups
--     list filters payment_status = 'PENDING' but not is_active, so the planner
--     cannot use it. The broader partial indexes below cover that; the
--     entity_type composite helps the entity_type = ANY(...) filter.
--
-- HONEST NOTE ON VALUE (measured 2026-07-16 on solvetaxadmindev):
--   customer_services = 53 rows, payments = 24 rows. All six indexes show
--   idx_scan = 0 and the planner seq-scans instead (cost=2.33, 1 buffer,
--   0.018 ms) because reading one page beats any index lookup. They earn
--   nothing today and are kept for when these tables reach ~10k+ rows.
--
-- SAFETY
--   * CONCURRENTLY takes no long write lock, but CANNOT run inside a
--     transaction block -- do NOT wrap in BEGIN/COMMIT.
--   * After running, check for invalid indexes (a failed CONCURRENTLY build):
--       SELECT c.relname FROM pg_index i
--       JOIN pg_class c ON c.oid = i.indexrelid
--       JOIN pg_namespace n ON n.oid = c.relnamespace
--       WHERE n.nspname = 'solvetax' AND NOT i.indisvalid;
--     Any row returned must be DROPped and rebuilt -- rerunning this file will
--     NOT fix it, because IF NOT EXISTS matches the invalid index by name.
-- ============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_followup_at
  ON solvetax.customer_services (followup_at)
  WHERE followup_at IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_rm_followup
  ON solvetax.customer_services (rm_id, followup_at)
  WHERE followup_at IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_op_followup
  ON solvetax.customer_services (op_id, followup_at)
  WHERE followup_at IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_services_service_code_norm
  ON solvetax.customer_services (upper(btrim(service_code)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_followup_at
  ON solvetax.payments (followup_at)
  WHERE followup_at IS NOT NULL AND payment_status = 'PENDING';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_followup_entity_at
  ON solvetax.payments (entity_type, followup_at)
  WHERE followup_at IS NOT NULL
    AND payment_status = 'PENDING'
    AND is_active = TRUE;
