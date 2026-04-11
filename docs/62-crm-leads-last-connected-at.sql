-- Add last_connected_at to CRM leads
ALTER TABLE solvetax.crm_leads
ADD COLUMN IF NOT EXISTS last_connected_at timestamptz NULL;

-- Optional helper index for recent connected activity queries
CREATE INDEX IF NOT EXISTS idx_crm_leads_last_connected_at
ON solvetax.crm_leads (last_connected_at)
WHERE is_active = TRUE;
