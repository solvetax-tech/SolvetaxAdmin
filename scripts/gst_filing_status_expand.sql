-- Expand gst_filing_return_details status CHECK constraints to accept
-- all parent gst_filings workflow statuses plus NOT_FILED and MISSED.
-- Parent gst_filings.chk_status already allows the 7 workflow values.

BEGIN;

-- gst_filing_return_details: gstr1_status
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_gstr1_status;
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_gstr1_status CHECK (
    (gstr1_status)::text = ANY (ARRAY[
      'FILED'::text, 'NOT_FILED'::text, 'MISSED'::text,
      'DATA_PENDING'::text, 'DATA_RECEIVED'::text, 'IN_PREPARATION'::text,
      'PENDING_OTP'::text, 'READY_TO_FILE'::text, 'OVERDUE'::text
    ])
  );

-- gstr3b_status
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_gstr3b_status;
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_gstr3b_status CHECK (
    (gstr3b_status)::text = ANY (ARRAY[
      'FILED'::text, 'NOT_FILED'::text, 'MISSED'::text,
      'DATA_PENDING'::text, 'DATA_RECEIVED'::text, 'IN_PREPARATION'::text,
      'PENDING_OTP'::text, 'READY_TO_FILE'::text, 'OVERDUE'::text
    ])
  );

-- gstr9_status
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_gstr9_status;
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_gstr9_status CHECK (
    (gstr9_status)::text = ANY (ARRAY[
      'FILED'::text, 'NOT_FILED'::text, 'MISSED'::text,
      'DATA_PENDING'::text, 'DATA_RECEIVED'::text, 'IN_PREPARATION'::text,
      'PENDING_OTP'::text, 'READY_TO_FILE'::text, 'OVERDUE'::text
    ])
  );

-- gstr9c_status
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_gstr9c_status;
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_gstr9c_status CHECK (
    (gstr9c_status)::text = ANY (ARRAY[
      'FILED'::text, 'NOT_FILED'::text, 'MISSED'::text,
      'DATA_PENDING'::text, 'DATA_RECEIVED'::text, 'IN_PREPARATION'::text,
      'PENDING_OTP'::text, 'READY_TO_FILE'::text, 'OVERDUE'::text
    ])
  );

-- cmp08_status
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_cmp08_status;
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_cmp08_status CHECK (
    (cmp08_status)::text = ANY (ARRAY[
      'FILED'::text, 'NOT_FILED'::text, 'MISSED'::text,
      'DATA_PENDING'::text, 'DATA_RECEIVED'::text, 'IN_PREPARATION'::text,
      'PENDING_OTP'::text, 'READY_TO_FILE'::text, 'OVERDUE'::text
    ])
  );

-- gstr4_status
ALTER TABLE solvetax.gst_filing_return_details
  DROP CONSTRAINT IF EXISTS chk_gstr4_status;
ALTER TABLE solvetax.gst_filing_return_details
  ADD CONSTRAINT chk_gstr4_status CHECK (
    (gstr4_status)::text = ANY (ARRAY[
      'FILED'::text, 'NOT_FILED'::text, 'MISSED'::text,
      'DATA_PENDING'::text, 'DATA_RECEIVED'::text, 'IN_PREPARATION'::text,
      'PENDING_OTP'::text, 'READY_TO_FILE'::text, 'OVERDUE'::text
    ])
  );

COMMIT;
