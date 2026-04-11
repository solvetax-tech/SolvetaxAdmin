-- CRM leads follow-up status tracking columns
ALTER TABLE solvetax.crm_leads
ADD COLUMN IF NOT EXISTS follow_up_status varchar(20) NOT NULL DEFAULT 'PENDING';

ALTER TABLE solvetax.crm_leads
ADD COLUMN IF NOT EXISTS missed_at timestamptz NULL;

ALTER TABLE solvetax.crm_leads
ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;

-- Status validation
ALTER TABLE solvetax.crm_leads
DROP CONSTRAINT IF EXISTS chk_crm_follow_up_status;

ALTER TABLE solvetax.crm_leads
ADD CONSTRAINT chk_crm_follow_up_status
CHECK (
    follow_up_status::text = ANY (
        ARRAY['PENDING', 'COMPLETED', 'MISSED', 'CANCELLED']::text[]
    )
);

-- Keep completed_at mandatory only for COMPLETED records.
ALTER TABLE solvetax.crm_leads
DROP CONSTRAINT IF EXISTS chk_crm_followup_completed_fields;

ALTER TABLE solvetax.crm_leads
ADD CONSTRAINT chk_crm_followup_completed_fields
CHECK (
    (follow_up_status::text <> 'COMPLETED')
    OR (completed_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_crm_leads_followup_status_time
ON solvetax.crm_leads (follow_up_status, followup_at)
WHERE is_active = TRUE;

-- Trigger: set completed_at automatically when follow_up_status becomes COMPLETED
CREATE OR REPLACE FUNCTION solvetax.set_crm_lead_followup_timestamps()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.follow_up_status = 'COMPLETED' THEN
        NEW.completed_at := COALESCE(NEW.completed_at, NOW());
    ELSIF NEW.follow_up_status <> 'COMPLETED' THEN
        NEW.completed_at := NULL;
    END IF;

    IF NEW.follow_up_status <> 'MISSED' THEN
        NEW.missed_at := NULL;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_set_crm_lead_followup_timestamps
ON solvetax.crm_leads;

CREATE TRIGGER trg_set_crm_lead_followup_timestamps
BEFORE INSERT OR UPDATE OF follow_up_status, completed_at, missed_at
ON solvetax.crm_leads
FOR EACH ROW
EXECUTE FUNCTION solvetax.set_crm_lead_followup_timestamps();
