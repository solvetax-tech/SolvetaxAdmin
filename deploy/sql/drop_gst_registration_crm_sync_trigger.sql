-- Move CRM sync from DB trigger to application code (backend/gst_registration/crm_lead_sync.py).
-- Run after deploying backend that calls sync_crm_lead_from_gst_registration on GST writes.

DROP TRIGGER IF EXISTS trg_aaa_crm_sync_gst_reg ON solvetax.gst_registration;

-- Optional: drop function when no other callers remain.
-- DROP FUNCTION IF EXISTS solvetax.fn_sync_crm_lead_from_gst_registration();
