-- Drop the 26 value-list CHECK constraints; enforcement moves to application code.
--
-- WHY: these constraints only enumerate legal values ("status must be one of ..."),
-- so every new business status required a production DDL migration. The vocabularies
-- now live in backend/common/status_constants.py, which is wired into the Pydantic
-- request models and the read-filter normalizers. The tuples in that module were
-- diffed against these exact constraints before this migration was written: 26/26
-- matched with zero drift.
--
-- SCOPE: value lists ONLY. Deliberately NOT dropped, because they encode rules that
-- do not churn and are cheaper to enforce in the DB than to re-derive in code:
--   * format regexes      -- PAN / GSTIN / mobile / email / Aadhaar patterns
--   * cross-field logic   -- chk_approved_logic, chk_verified_logic, chk_action_json,
--                            chk_gstin_pan_match, chk_followup_completed_fields, ...
--   * numeric ranges      -- chk_amount_positive, chk_paid_not_exceed_net, ...
--
-- KNOWN NON-EFFECTS: two vocabularies stay pinned by cross-field invariants that are
-- being kept, so dropping their value-list CHECK does not actually free them:
--   * versions.action                  -- pinned by versions.chk_action_json
--   * crm_stage_status_mappings.kind   -- pinned by chk_crm_ui_mapping_fields
-- Extending either list still needs that invariant reworked. Both are dropped anyway
-- to remove the redundant second definition.
--
-- ROLLBACK: 2026-07-16_drop_status_value_checks_rollback.sql restores all 26.
-- Safe to re-run: every statement is IF EXISTS.

BEGIN;

-- crm_leads
ALTER TABLE solvetax.crm_leads
  DROP CONSTRAINT IF EXISTS chk_crm_stage,
  DROP CONSTRAINT IF EXISTS chk_crm_follow_up_status;

-- crm_bulk_assign_logs
-- run_type was the ONLY column here with no code-side allow-list; the insert path in
-- crm_bulk_auto_assign.py is guarded by normalize_run_type() as of this change.
ALTER TABLE solvetax.crm_bulk_assign_logs
  DROP CONSTRAINT IF EXISTS chk_crm_bulk_assign_run_type;

-- crm_stage_status_mappings (see KNOWN NON-EFFECTS above)
ALTER TABLE solvetax.crm_stage_status_mappings
  DROP CONSTRAINT IF EXISTS crm_ui_mappings_mapping_kind_check;

-- customer_otp_verify
ALTER TABLE solvetax.customer_otp_verify
  DROP CONSTRAINT IF EXISTS customer_otp_verify_otp_purpose_check;

-- customer_services
ALTER TABLE solvetax.customer_services
  DROP CONSTRAINT IF EXISTS chk_customer_services_service_status,
  DROP CONSTRAINT IF EXISTS chk_customer_services_followup_status;

-- gst_filings
ALTER TABLE solvetax.gst_filings
  DROP CONSTRAINT IF EXISTS chk_status,
  DROP CONSTRAINT IF EXISTS chk_filing_frequency,
  DROP CONSTRAINT IF EXISTS chk_taxpayer_type,
  DROP CONSTRAINT IF EXISTS chk_turnover_details;

-- gst_filing_return_details
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_gstr1_status,
  DROP CONSTRAINT IF EXISTS chk_gstr3b_status,
  DROP CONSTRAINT IF EXISTS chk_gstr4_status,
  DROP CONSTRAINT IF EXISTS chk_gstr9_status,
  DROP CONSTRAINT IF EXISTS chk_gstr9c_status,
  DROP CONSTRAINT IF EXISTS chk_cmp08_status,
  DROP CONSTRAINT IF EXISTS chk_gst_filing_return_details_filing_frequency;

-- gst_filing_rule_engine
-- Reference/config table: seeded by hand, no application write path. After this drop
-- nothing validates a manual seed -- see the migration note in the PR description.
ALTER TABLE solvetax.gst_filing_rule_engine
  DROP CONSTRAINT IF EXISTS chk_return_type,
  DROP CONSTRAINT IF EXISTS chk_taxpayer_type,
  DROP CONSTRAINT IF EXISTS chk_turnover_values;

-- income_tax
ALTER TABLE solvetax.income_tax
  DROP CONSTRAINT IF EXISTS chk_income_tax_filed_status,
  DROP CONSTRAINT IF EXISTS chk_income_tax_priority;

-- payments
ALTER TABLE solvetax.payments
  DROP CONSTRAINT IF EXISTS chk_payment_status,
  DROP CONSTRAINT IF EXISTS chk_payments_followup_status;

-- versions (see KNOWN NON-EFFECTS above)
ALTER TABLE solvetax.versions
  DROP CONSTRAINT IF EXISTS versions_action_check;

COMMIT;
