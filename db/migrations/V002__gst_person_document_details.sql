-- V002__gst_person_document_details.sql
--
-- Collapse gst_registration_persons + gst_registration_documents into ONE table,
-- person_document_details: one row per person for a registration, with that
-- person's documents held inline as a JSONB array (uploaded together, saved
-- once). Fresh start — the two old tables are DROPPED WITHOUT migrating data
-- (confirmed test/throwaway data only).
--
-- Deliberately NOT stored here: gstin, ownership_category, customer_id. All are
-- read from solvetax.gst_registration via gst_registration_id. The
-- required-documents-per-ownership rules stay in solvetax.document_config
-- (keyed on ownership_category), joined through the registration.
--
-- The migration runner owns the transaction — no BEGIN/COMMIT in this script.

-- --------------------------------------------------------------------------- --
-- 1) Drop the old split tables.
--    CASCADE also clears their sequences, indexes, the verified-timestamp
--    trigger, and the documents -> persons FK. Nothing else in the schema
--    references either table.
-- --------------------------------------------------------------------------- --
DROP TABLE IF EXISTS solvetax.gst_registration_documents CASCADE;
DROP TABLE IF EXISTS solvetax.gst_registration_persons CASCADE;

-- --------------------------------------------------------------------------- --
-- 2) The unified table. person_id is the primary key; a person's documents live
--    inline, so there is no separate document id.
-- --------------------------------------------------------------------------- --
CREATE TABLE solvetax.person_document_details (
    person_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gst_registration_id  bigint NOT NULL
        REFERENCES solvetax.gst_registration (id) ON DELETE CASCADE,

    -- person (collected by the RM)
    full_name            character varying(150) NOT NULL,
    designation          character varying(100) NOT NULL,   -- dropdown
    phone                character varying(20),
    email                character varying(150),
    pan                  character varying(10),              -- auto-filled by OCR from the PAN card
    aadhaar              character varying(20),              -- auto-filled by OCR from the Aadhaar card
    is_primary           boolean NOT NULL DEFAULT false,     -- proprietary -> true, else false (set by API)

    -- this person's documents — one entry per document type. Minimal shape:
    -- {
    --   "document_type": "PAN_CARD",          -- matches document_config.value
    --   "document_url":  "https://<blob>..."   -- Azure blob URL (storage unchanged)
    -- }
    -- The document type IS the name: on download the OP receives the file named
    -- as its document type (prettified via document_config.display_name), so no
    -- document_name / verified / uploaded_by fields are stored here.
    documents            jsonb NOT NULL DEFAULT '[]'::jsonb,

    -- lifecycle / audit
    is_active            boolean NOT NULL DEFAULT true,
    created_at           timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at           timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT chk_pdd_pan_format
        CHECK (pan IS NULL OR (pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
    CONSTRAINT chk_pdd_aadhaar_format
        CHECK (aadhaar IS NULL OR (aadhaar)::text ~ '^[0-9]{12}$'),
    CONSTRAINT chk_pdd_phone_format
        CHECK (phone IS NULL OR (phone)::text ~ '^[0-9]{10}$'),
    CONSTRAINT chk_pdd_documents_is_array
        CHECK (jsonb_typeof(documents) = 'array')
);

-- --------------------------------------------------------------------------- --
-- 3) Indexes.
-- --------------------------------------------------------------------------- --
-- Primary lookup: all active persons of a registration.
CREATE INDEX ix_pdd_registration
    ON solvetax.person_document_details (gst_registration_id, is_active);

-- Query inside the documents array (e.g. "which document types this person has").
CREATE INDEX ix_pdd_documents_gin
    ON solvetax.person_document_details USING gin (documents);

-- At most one primary member per registration (carried over from the old table).
CREATE UNIQUE INDEX ux_pdd_one_primary
    ON solvetax.person_document_details (gst_registration_id)
    WHERE is_primary AND is_active;

-- No duplicate active person within the same registration (carried over).
CREATE UNIQUE INDEX ux_pdd_pan_per_reg
    ON solvetax.person_document_details (gst_registration_id, upper(btrim(pan)))
    WHERE pan IS NOT NULL AND is_active;
CREATE UNIQUE INDEX ux_pdd_aadhaar_per_reg
    ON solvetax.person_document_details (gst_registration_id, btrim(aadhaar))
    WHERE aadhaar IS NOT NULL AND is_active;
CREATE UNIQUE INDEX ux_pdd_email_per_reg
    ON solvetax.person_document_details (gst_registration_id, lower(btrim(email)))
    WHERE email IS NOT NULL AND is_active;
CREATE UNIQUE INDEX ux_pdd_phone_per_reg
    ON solvetax.person_document_details (gst_registration_id, btrim(phone))
    WHERE phone IS NOT NULL AND is_active;
