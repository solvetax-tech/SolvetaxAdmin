-- CRM UI mappings: one table for stage->pitch and pitch->allowed call statuses.
-- Requires solvetax.crm_call_types / crm_call_statuses.

CREATE TABLE IF NOT EXISTS solvetax.crm_ui_mappings (
  id bigserial PRIMARY KEY,
  mapping_kind varchar(30) NOT NULL CHECK (mapping_kind IN ('STAGE_TO_PITCH', 'PITCH_TO_STATUS')),
  stage varchar(40) NULL,
  pitch_type_code varchar(40) NOT NULL,
  call_status_code varchar(50) NULL,
  sort_order int NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chk_crm_ui_mapping_fields CHECK (
    (mapping_kind = 'STAGE_TO_PITCH' AND stage IS NOT NULL AND call_status_code IS NULL)
    OR (mapping_kind = 'PITCH_TO_STATUS' AND call_status_code IS NOT NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_ui_stage_pitch
  ON solvetax.crm_ui_mappings (mapping_kind, stage, pitch_type_code)
  WHERE mapping_kind = 'STAGE_TO_PITCH' AND is_active = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_ui_pitch_status
  ON solvetax.crm_ui_mappings (mapping_kind, pitch_type_code, call_status_code)
  WHERE mapping_kind = 'PITCH_TO_STATUS' AND is_active = true;

CREATE INDEX IF NOT EXISTS idx_crm_ui_mappings_kind_pitch
  ON solvetax.crm_ui_mappings (mapping_kind, pitch_type_code)
  WHERE is_active = true;

-- New status for first-pitch "send documents" -> stage PENDING_REGISTRATION_DATA in app logic
INSERT INTO solvetax.crm_call_statuses (code, name, is_active)
VALUES ('SEND_DOCS', 'Send Documents', true)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = EXCLUDED.is_active;

-- Replace seed rows only (idempotent re-run)
DELETE FROM solvetax.crm_ui_mappings WHERE mapping_kind = 'STAGE_TO_PITCH';
INSERT INTO solvetax.crm_ui_mappings (mapping_kind, stage, pitch_type_code, sort_order, is_active)
VALUES
  ('STAGE_TO_PITCH', 'FRESH_LEAD', 'FIRST_PITCH_CALL', 10, true),
  ('STAGE_TO_PITCH', 'FOLLOW_UP', 'FIRST_PITCH_CALL', 20, true),
  ('STAGE_TO_PITCH', 'INTERESTED', 'FIRST_PITCH_CALL', 30, true),
  ('STAGE_TO_PITCH', 'GST_REGISTRATION_DONE', 'FINAL_PITCH_CALL', 40, true),
  ('STAGE_TO_PITCH', 'SCHEDULED_PAYMENTS', 'FINAL_PITCH_CALL', 50, true);

DELETE FROM solvetax.crm_ui_mappings WHERE mapping_kind = 'PITCH_TO_STATUS';
INSERT INTO solvetax.crm_ui_mappings (mapping_kind, stage, pitch_type_code, call_status_code, sort_order, is_active)
VALUES
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'CALL_NOT_ANSWERED', 10, true),
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'CALL_NOT_CONNECTED', 20, true),
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'CALL_BUSY', 30, true),
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'CALL_BACK', 40, true),
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'CONNECTED_AND_SCHEDULED', 50, true),
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'SEND_DOCS', 55, true),
  ('PITCH_TO_STATUS', NULL, 'FIRST_PITCH_CALL', 'NOT_INTERESTED', 60, true),
  ('PITCH_TO_STATUS', NULL, 'FINAL_PITCH_CALL', 'CALL_NOT_ANSWERED', 10, true),
  ('PITCH_TO_STATUS', NULL, 'FINAL_PITCH_CALL', 'CALL_NOT_CONNECTED', 20, true),
  ('PITCH_TO_STATUS', NULL, 'FINAL_PITCH_CALL', 'CALL_BUSY', 30, true),
  ('PITCH_TO_STATUS', NULL, 'FINAL_PITCH_CALL', 'CALL_BACK', 40, true),
  ('PITCH_TO_STATUS', NULL, 'FINAL_PITCH_CALL', 'SCHEDULED_PAYMENT', 50, true);
