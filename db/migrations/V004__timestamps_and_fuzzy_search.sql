-- V003: Normalize the remaining naive timestamp columns to `timestamptz`.
--
-- WHY
--   Almost every timestamp column in the schema is already `timestamp with time
--   zone` (timestamptz) — an absolute instant that the app renders in IST via
--   the frontend (formatDateTimeIST). A handful of columns were still `timestamp
--   without time zone` (naive). Naive values carry no offset, so the browser
--   interprets them in its own local zone — which is where "wrong time" comes
--   from. Converting them to timestamptz makes the WHOLE schema consistent, and
--   every timestamp then displays correctly in IST like the rest.
--
-- HOW (why this does not corrupt data)
--   These columns default to CURRENT_TIMESTAMP, i.e. Postgres wrote the session-
--   local wall-clock into a naive column. Reinterpreting each value with the
--   session's OWN current timezone — `current_setting('timezone')` — reverses
--   that cast exactly and rebuilds the original absolute instant. This is correct
--   whether the database runs in UTC or Asia/Kolkata; nothing is shifted, only
--   the (already-implied) zone is attached. The existing DEFAULT CURRENT_TIMESTAMP
--   stays valid on a timestamptz column.
--
--   Assumption: the database's timezone has not changed since these rows were
--   written (true for a normal deployment). The runner wraps this in one
--   transaction, so if anything fails it rolls back cleanly — no BEGIN/COMMIT here.

ALTER TABLE solvetax.contact_support
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone'),
    ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.employee_roles
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone'),
    ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.entity_types
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone'),
    ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.features
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone'),
    ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.role_features
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone'),
    ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.roles
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone'),
    ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.session_audit_log
    ALTER COLUMN action_time TYPE timestamptz USING action_time AT TIME ZONE current_setting('timezone');

ALTER TABLE solvetax.versions
    ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE current_setting('timezone');


-- ═══════════════════════════════════════════════════════════════════════════
-- Typo-tolerant fuzzy text search (pg_trgm) for all list-endpoint text filters.
--
-- The shared text_search_filters.py now matches text/mobile columns two ways:
--   1. substring / word ILIKE   (accelerated by the gin_trgm indexes below)
--   2. word_similarity(query, column) >= 0.5  (pg_trgm typo tolerance)
--
-- This part MUST be applied BEFORE the backend that uses word_similarity()
-- restarts — otherwise those searches error with "function word_similarity does
-- not exist".
-- ═══════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Persist a 50% default for the word-similarity operators, so a later switch to
-- the index-assisted `%>` operator (or any raw pg_trgm operator use) also runs
-- at 0.5 without per-query tuning. Harmless for the explicit >= 0.5 the app uses.
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET pg_trgm.word_similarity_threshold = 0.5', current_database());
END $$;

-- gin_trgm indexes on the most-searched text columns (verified to exist in the
-- schema). These make the ILIKE substring half of every fuzzy filter fast.
CREATE INDEX IF NOT EXISTS idx_trgm_customers_full_name     ON solvetax.customers        USING gin (full_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_customers_business_name ON solvetax.customers        USING gin (business_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_customers_city          ON solvetax.customers        USING gin (city gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_trgm_crm_leads_full_name     ON solvetax.crm_leads        USING gin (full_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_crm_leads_tag           ON solvetax.crm_leads        USING gin (tag gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_crm_leads_remarks       ON solvetax.crm_leads        USING gin (remarks gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_trgm_gst_reg_business_name   ON solvetax.gst_registration USING gin (business_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_gst_reg_gstin           ON solvetax.gst_registration USING gin (gstin gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_gst_reg_pan             ON solvetax.gst_registration USING gin (pan gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_gst_reg_client_name     ON solvetax.gst_registration USING gin (client_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_trgm_contact_support_name    ON solvetax.contact_support  USING gin (your_name gin_trgm_ops);
