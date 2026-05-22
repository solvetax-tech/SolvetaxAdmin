-- gst_registration: drop referral_id / referral_entity; add client_name / referral_phone_number

ALTER TABLE solvetax.gst_registration
    DROP COLUMN IF EXISTS referral_id,
    DROP COLUMN IF EXISTS referral_entity;

ALTER TABLE solvetax.gst_registration
    ADD COLUMN IF NOT EXISTS client_name varchar(200) NULL,
    ADD COLUMN IF NOT EXISTS referral_phone_number varchar(20) NULL;

-- Optional: align PAN/GSTIN check if not applied yet
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
