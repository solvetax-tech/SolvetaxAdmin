-- Add surrogate `id` PK when `crm_lead_stages` was created with `code` as PK only
-- (older docs/65). Safe to run once; skips if column `id` already exists.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'solvetax'
      AND table_name = 'crm_lead_stages'
      AND column_name = 'id'
  ) THEN
    ALTER TABLE solvetax.crm_lead_stages DROP CONSTRAINT IF EXISTS crm_lead_stages_pkey;
    ALTER TABLE solvetax.crm_lead_stages ADD COLUMN id bigserial PRIMARY KEY;
    ALTER TABLE solvetax.crm_lead_stages
      ADD CONSTRAINT crm_lead_stages_code_key UNIQUE (code);
  END IF;
END $$;
