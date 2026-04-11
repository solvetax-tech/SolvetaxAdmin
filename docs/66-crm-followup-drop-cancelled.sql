-- Stop allowing follow_up_status = CANCELLED (app + DB).
-- Run after deploying API that no longer sends CANCELLED.

UPDATE solvetax.crm_leads
   SET follow_up_status = 'PENDING'
 WHERE follow_up_status = 'CANCELLED';

ALTER TABLE solvetax.crm_leads
  DROP CONSTRAINT IF EXISTS chk_crm_follow_up_status;

ALTER TABLE solvetax.crm_leads
  ADD CONSTRAINT chk_crm_follow_up_status
  CHECK (
    follow_up_status::text = ANY (
      ARRAY['PENDING', 'COMPLETED', 'MISSED']::text[]
    )
  );
