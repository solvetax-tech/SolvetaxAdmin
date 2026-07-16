-- Rollback for 2026-07-16_drop_status_value_checks.sql -- restores all 26 value-list CHECKs.
--
-- Definitions are transcribed from pg_get_constraintdef() captured immediately before
-- the drop, normalised to plain `IN (...)` (the original `= ANY (ARRAY[...]::varchar[])`
-- form is what Postgres echoes back, not what was written; the predicates are equivalent).
--
-- WILL FAIL IF: rows violating a constraint were written while it was absent. That is
-- the point -- it tells you code-side enforcement leaked. To find offenders before
-- running this, use the SELECTs at the bottom of this file.

BEGIN;

ALTER TABLE solvetax.crm_leads
  ADD CONSTRAINT chk_crm_stage CHECK (stage IN (
    'FRESH_LEAD','PENDING_REGISTRATION_DATA','FOLLOW_UP','INTERESTED',
    'GST_REGISTRATION_DONE','SCHEDULED_PAYMENTS','SUBSCRIBED','NOT_INTERESTED',
    'PENDING_ITR_DATA','ITR_DONE')),
  ADD CONSTRAINT chk_crm_follow_up_status CHECK (follow_up_status IN (
    'PENDING','COMPLETED','MISSED'));

ALTER TABLE solvetax.crm_bulk_assign_logs
  ADD CONSTRAINT chk_crm_bulk_assign_run_type CHECK (run_type IN ('AUTO','MANUAL'));

ALTER TABLE solvetax.crm_stage_status_mappings
  ADD CONSTRAINT crm_ui_mappings_mapping_kind_check CHECK (mapping_kind IN (
    'STAGE_TO_PITCH','PITCH_TO_STATUS'));

ALTER TABLE solvetax.customer_otp_verify
  ADD CONSTRAINT customer_otp_verify_otp_purpose_check CHECK (otp_purpose IN (
    'customer','password_reset'));

-- Both nullable in the original definitions -- the NULL branch is load-bearing.
ALTER TABLE solvetax.customer_services
  ADD CONSTRAINT chk_customer_services_service_status CHECK (service_status IN (
    'PENDING','PROVIDED')),
  ADD CONSTRAINT chk_customer_services_followup_status CHECK (
    followup_status IS NULL OR followup_status IN ('PENDING','COMPLETED','MISSED'));

ALTER TABLE solvetax.gst_filings
  ADD CONSTRAINT chk_status CHECK (status IN (
    'DATA_PENDING','DATA_RECEIVED','IN_PREPARATION','PENDING_OTP',
    'READY_TO_FILE','FILED','OVERDUE')),
  ADD CONSTRAINT chk_filing_frequency CHECK (filing_frequency IN (
    'MONTHLY','QUARTERLY','YEARLY')),
  ADD CONSTRAINT chk_taxpayer_type CHECK (taxpayer_type IN ('REGULAR','COMPOSITION')),
  ADD CONSTRAINT chk_turnover_details CHECK (turnover_details IN (
    'LESS_THAN_2CR','BETWEEN_2CR_5CR','MORE_THAN_5CR'));

-- The six return-status columns share one vocabulary (the 7 filing statuses plus
-- NOT_FILED and MISSED). filing_frequency here is nullable; on gst_filings it is not.
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_gstr1_status CHECK (gstr1_status IN (
    'FILED','NOT_FILED','MISSED','DATA_PENDING','DATA_RECEIVED',
    'IN_PREPARATION','PENDING_OTP','READY_TO_FILE','OVERDUE')),
  ADD CONSTRAINT chk_gstr3b_status CHECK (gstr3b_status IN (
    'FILED','NOT_FILED','MISSED','DATA_PENDING','DATA_RECEIVED',
    'IN_PREPARATION','PENDING_OTP','READY_TO_FILE','OVERDUE')),
  ADD CONSTRAINT chk_gstr4_status CHECK (gstr4_status IN (
    'FILED','NOT_FILED','MISSED','DATA_PENDING','DATA_RECEIVED',
    'IN_PREPARATION','PENDING_OTP','READY_TO_FILE','OVERDUE')),
  ADD CONSTRAINT chk_gstr9_status CHECK (gstr9_status IN (
    'FILED','NOT_FILED','MISSED','DATA_PENDING','DATA_RECEIVED',
    'IN_PREPARATION','PENDING_OTP','READY_TO_FILE','OVERDUE')),
  ADD CONSTRAINT chk_gstr9c_status CHECK (gstr9c_status IN (
    'FILED','NOT_FILED','MISSED','DATA_PENDING','DATA_RECEIVED',
    'IN_PREPARATION','PENDING_OTP','READY_TO_FILE','OVERDUE')),
  ADD CONSTRAINT chk_cmp08_status CHECK (cmp08_status IN (
    'FILED','NOT_FILED','MISSED','DATA_PENDING','DATA_RECEIVED',
    'IN_PREPARATION','PENDING_OTP','READY_TO_FILE','OVERDUE')),
  ADD CONSTRAINT chk_gst_filing_return_details_filing_frequency CHECK (
    filing_frequency IS NULL OR filing_frequency IN ('MONTHLY','QUARTERLY','YEARLY'));

-- return_type is nullable; turnover_details here uses the 5Cr buckets + ALL, which is
-- a DIFFERENT vocabulary from gst_filings.turnover_details above. Not a typo.
ALTER TABLE solvetax.gst_filing_rule_engine
  ADD CONSTRAINT chk_return_type CHECK (
    return_type IS NULL OR return_type IN ('REGULAR','QRMP','COMPOSITION')),
  ADD CONSTRAINT chk_taxpayer_type CHECK (taxpayer_type IN ('REGULAR','COMPOSITION')),
  ADD CONSTRAINT chk_turnover_values CHECK (turnover_details IN (
    'LESS_THAN_5CR','MORE_THAN_5CR','ALL'));

ALTER TABLE solvetax.income_tax
  ADD CONSTRAINT chk_income_tax_filed_status CHECK (filed_status IN ('FILED','NOT_FILED')),
  ADD CONSTRAINT chk_income_tax_priority CHECK (priority IN ('LOW','NORMAL','HIGH'));

ALTER TABLE solvetax.payments
  ADD CONSTRAINT chk_payment_status CHECK (payment_status IN ('PENDING','PAID','CANCELLED')),
  ADD CONSTRAINT chk_payments_followup_status CHECK (
    followup_status IS NULL OR followup_status IN ('PENDING','COMPLETED','MISSED'));

ALTER TABLE solvetax.versions
  ADD CONSTRAINT versions_action_check CHECK (action IN (
    'CREATE','UPDATE','DELETE','ACTIVATE'));

COMMIT;

-- ---------------------------------------------------------------------------
-- Find rows that would block this rollback (run BEFORE the BEGIN above):
--
--   SELECT 'crm_leads.stage' AS col, stage AS bad, count(*) FROM solvetax.crm_leads
--    WHERE stage NOT IN ('FRESH_LEAD','PENDING_REGISTRATION_DATA','FOLLOW_UP',
--          'INTERESTED','GST_REGISTRATION_DONE','SCHEDULED_PAYMENTS','SUBSCRIBED',
--          'NOT_INTERESTED','PENDING_ITR_DATA','ITR_DONE') GROUP BY 1,2
--   UNION ALL
--   SELECT 'gst_filings.status', status, count(*) FROM solvetax.gst_filings
--    WHERE status NOT IN ('DATA_PENDING','DATA_RECEIVED','IN_PREPARATION','PENDING_OTP',
--          'READY_TO_FILE','FILED','OVERDUE') GROUP BY 1,2
--   UNION ALL
--   SELECT 'payments.payment_status', payment_status, count(*) FROM solvetax.payments
--    WHERE payment_status NOT IN ('PENDING','PAID','CANCELLED') GROUP BY 1,2;
-- ---------------------------------------------------------------------------
