-- Move CRM sync from DB trigger to application code (backend/payments/crm_lead_sync.py).
-- Run ONLY after backend with sync_crm_lead_from_payment_paid is deployed.

-- If trigger name differs, run:
-- SELECT tgname FROM pg_trigger t
-- JOIN pg_class c ON c.oid = t.tgrelid
-- JOIN pg_namespace n ON n.oid = c.relnamespace
-- WHERE n.nspname = 'solvetax' AND c.relname = 'payments' AND NOT t.tgisinternal;

DROP TRIGGER IF EXISTS trg_crm_sync_payment ON solvetax.payments;
DROP TRIGGER IF EXISTS trg_sync_payment_paid_to_crm ON solvetax.payments;

DROP FUNCTION IF EXISTS solvetax.fn_sync_payment_paid_to_crm();
