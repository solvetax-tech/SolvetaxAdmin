-- Move CRM sync from DB trigger to application code (backend/Income_tax/crm_lead_sync.py).
-- Run ONLY after backend with sync_crm_lead_from_income_tax is deployed.

DROP TRIGGER IF EXISTS trg_crm_sync_income_tax ON solvetax.income_tax;

DROP FUNCTION IF EXISTS solvetax.fn_sync_crm_lead_from_income_tax();
