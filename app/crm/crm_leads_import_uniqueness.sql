-- =============================================================================
-- CRM leads import uniqueness: dedupe + partial unique indexes
-- Schema: solvetax.crm_leads
--
-- Rules:
--   GST_REGISTRATION  -> unique (mobile, entity_type)
--   INCOME_TAX        -> unique (mobile, entity_type, ay)  [blank/null ay = '']
--
-- Run in DBeaver/psql against solvetax. Review preview queries before DELETE.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0) Inspect existing UNIQUE indexes on crm_leads (informational)
-- -----------------------------------------------------------------------------
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'solvetax'
--   AND tablename = 'crm_leads'
--   AND indexdef ILIKE '%UNIQUE%';

-- -----------------------------------------------------------------------------
-- 1) Drop prior import-uniqueness indexes (safe to re-run)
--    Does NOT drop normal btree indexes from table DDL (idx_crm_leads_mobile, etc.)
-- -----------------------------------------------------------------------------
DROP INDEX IF EXISTS solvetax.uq_crm_leads_gst_mobile_entity;
DROP INDEX IF EXISTS solvetax.uq_crm_leads_itr_mobile_entity_ay;

-- Legacy / alternate names if created earlier
DROP INDEX IF EXISTS solvetax.uq_crm_leads_mobile_entity;
DROP INDEX IF EXISTS solvetax.uq_crm_leads_entity_mobile;
DROP INDEX IF EXISTS solvetax.uq_crm_leads_mobile_entity_type;
DROP INDEX IF EXISTS solvetax.uq_crm_leads_mobile_entity_ay;

-- -----------------------------------------------------------------------------
-- 2) Preview duplicates (run standalone first if you want to inspect)
-- -----------------------------------------------------------------------------
-- GST duplicates
-- SELECT trim(mobile) AS mobile, upper(trim(entity_type)) AS entity_type,
--        array_agg(id ORDER BY id) AS lead_ids, count(*) AS cnt
-- FROM solvetax.crm_leads
-- WHERE upper(trim(entity_type)) = 'GST_REGISTRATION'
-- GROUP BY 1, 2
-- HAVING count(*) > 1;

-- ITR duplicates
-- SELECT trim(mobile) AS mobile, upper(trim(entity_type)) AS entity_type,
--        trim(COALESCE(ay, '')) AS ay,
--        array_agg(id ORDER BY id) AS lead_ids, count(*) AS cnt
-- FROM solvetax.crm_leads
-- WHERE upper(trim(entity_type)) = 'INCOME_TAX'
-- GROUP BY 1, 2, 3
-- HAVING count(*) > 1;

-- -----------------------------------------------------------------------------
-- 3) Remove duplicate rows — keep newest (highest id) per import key
--    Deletes related crm_activities for removed lead ids first.
-- -----------------------------------------------------------------------------

-- GST_REGISTRATION
WITH gst_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY trim(mobile), upper(trim(entity_type))
               ORDER BY id DESC
           ) AS rn
    FROM solvetax.crm_leads
    WHERE upper(trim(entity_type)) = 'GST_REGISTRATION'
),
gst_dupes AS (
    SELECT id FROM gst_ranked WHERE rn > 1
)
DELETE FROM solvetax.crm_activities a
WHERE a.lead_id IN (SELECT id FROM gst_dupes);

WITH gst_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY trim(mobile), upper(trim(entity_type))
               ORDER BY id DESC
           ) AS rn
    FROM solvetax.crm_leads
    WHERE upper(trim(entity_type)) = 'GST_REGISTRATION'
)
DELETE FROM solvetax.crm_leads l
WHERE l.id IN (SELECT id FROM gst_ranked WHERE rn > 1);

-- INCOME_TAX
WITH itr_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY trim(mobile), upper(trim(entity_type)), trim(COALESCE(ay, ''))
               ORDER BY id DESC
           ) AS rn
    FROM solvetax.crm_leads
    WHERE upper(trim(entity_type)) = 'INCOME_TAX'
),
itr_dupes AS (
    SELECT id FROM itr_ranked WHERE rn > 1
)
DELETE FROM solvetax.crm_activities a
WHERE a.lead_id IN (SELECT id FROM itr_dupes);

WITH itr_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY trim(mobile), upper(trim(entity_type)), trim(COALESCE(ay, ''))
               ORDER BY id DESC
           ) AS rn
    FROM solvetax.crm_leads
    WHERE upper(trim(entity_type)) = 'INCOME_TAX'
)
DELETE FROM solvetax.crm_leads l
WHERE l.id IN (SELECT id FROM itr_ranked WHERE rn > 1);

-- -----------------------------------------------------------------------------
-- 4) Create partial unique indexes (matches app import duplicate logic)
-- -----------------------------------------------------------------------------
CREATE UNIQUE INDEX uq_crm_leads_gst_mobile_entity
    ON solvetax.crm_leads (trim(mobile), upper(trim(entity_type)))
    WHERE upper(trim(entity_type)) = 'GST_REGISTRATION';

CREATE UNIQUE INDEX uq_crm_leads_itr_mobile_entity_ay
    ON solvetax.crm_leads (
        trim(mobile),
        upper(trim(entity_type)),
        trim(COALESCE(ay, ''))
    )
    WHERE upper(trim(entity_type)) = 'INCOME_TAX';

COMMIT;

-- -----------------------------------------------------------------------------
-- Verify
-- -----------------------------------------------------------------------------
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'solvetax'
--   AND tablename = 'crm_leads'
--   AND indexname LIKE 'uq_crm_leads_%';
