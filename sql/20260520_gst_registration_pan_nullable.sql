-- GST registration: allow NULL pan (CRM push / draft intake).
-- PAN must match GSTIN only when BOTH pan and gstin are present.

ALTER TABLE solvetax.gst_registration
    ALTER COLUMN pan DROP NOT NULL;

ALTER TABLE solvetax.gst_registration
    DROP CONSTRAINT IF EXISTS chk_gstin_pan_match;

ALTER TABLE solvetax.gst_registration
    ADD CONSTRAINT chk_gstin_pan_match CHECK (
        pan IS NULL
        OR gstin IS NULL
        OR upper(TRIM(BOTH FROM pan)) = SUBSTRING(upper(TRIM(BOTH FROM gstin)) FROM 3 FOR 10)
    );
