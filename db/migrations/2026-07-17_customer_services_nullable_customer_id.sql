-- ============================================================================
-- customer_services.customer_id -> NULLable
--
-- Allows a service row to exist before it is attached to a customer (e.g. a
-- prospect/lead), and backs POST /api/v1/customer-service/create.
--
-- Run OUTSIDE a transaction is NOT required here -- these are catalog-only
-- changes and are safe inside BEGIN/COMMIT. They take an ACCESS EXCLUSIVE lock
-- on customer_services for the duration, which at 53 rows is milliseconds.
-- ============================================================================

BEGIN;

-- 1. The actual change -------------------------------------------------------
-- No table rewrite: dropping NOT NULL is a catalog update only.
ALTER TABLE solvetax.customer_services
  ALTER COLUMN customer_id DROP NOT NULL;

-- The FK stays and still works: a NULL customer_id references nothing, which
-- SQL permits. Non-NULL values are still enforced against customers.
--   fk_customer_services_customer FOREIGN KEY (customer_id)
--     REFERENCES solvetax.customers(customer_id)

-- 2. The consequence most people miss ----------------------------------------
-- uq_customer_services_customer_service_code is UNIQUE (customer_id, service_code).
-- By default Postgres treats NULLs as DISTINCT, so once customer_id can be NULL
-- this constraint stops protecting customer-less rows entirely:
--
--     (NULL, 'GST_FILING')   -- inserted
--     (NULL, 'GST_FILING')   -- inserted AGAIN, no error
--     (NULL, 'GST_FILING')   -- and again, forever
--
-- Postgres 15+ (this server is 18.4) can treat NULLs as equal, which keeps
-- "one row per service_code among unattached rows" enforced. That is almost
-- certainly what you want: without it, a retried API call silently duplicates.
DROP INDEX IF EXISTS solvetax.uq_customer_services_customer_service_code;

CREATE UNIQUE INDEX uq_customer_services_customer_service_code
  ON solvetax.customer_services (customer_id, service_code)
  NULLS NOT DISTINCT;

COMMIT;

-- ============================================================================
-- APP CHANGES -- the schema change alone is NOT enough.
--
-- Six queries INNER JOIN customers, so a row with customer_id IS NULL is
-- invisible: it will not appear in any list, will not be counted, and cannot be
-- fetched by id.
--
-- LEFT JOIN is safe: the FK guarantees every non-NULL customer_id matches a
-- customer, so results are identical for existing rows -- it only ADDS the
-- customer-less ones (with NULL customer columns). Visibility rules key off
-- cs.rm_id / cs.op_id only, so this widens nobody's access.
--
-- DONE (2026-07-17) -- the Customer Services table, which owns the Create
-- Service button, so a row created without a customer is actually visible:
--   backend/customer_service/customer_service.py   list / count / detail
--   + CustomerServiceListItemOut.customer_id and CustomerServiceDetailOut
--     .customer_id are now Optional, else pydantic rejects the NULL row.
--
-- STILL INNER JOIN -- separate surfaces, deliberately left alone. An unattached
-- service is simply absent from each; decide per surface whether that is wrong:
--   backend/Dashboard/service_done_payment_pending.py:298
--   backend/follow_ups/customer_service_followups.py:243
--   backend/follow_ups/customer_service_followups.py:846
--
-- (backend/customer_service/bulk_lead_assignment.py:238 already LEFT JOINs.)
-- ============================================================================
