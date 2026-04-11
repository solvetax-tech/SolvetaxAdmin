-- Canonical CRM lead stages for UI and optional API validation.
-- GET /api/v1/crm/leads/stages reads this table.

CREATE TABLE IF NOT EXISTS solvetax.crm_lead_stages (
  id bigserial PRIMARY KEY,
  code varchar(40) NOT NULL,
  name varchar(120) NOT NULL,
  sort_order int NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT crm_lead_stages_code_key UNIQUE (code)
);

CREATE INDEX IF NOT EXISTS idx_crm_lead_stages_active_sort
  ON solvetax.crm_lead_stages (is_active, sort_order);

INSERT INTO solvetax.crm_lead_stages (code, name, sort_order, is_active) VALUES
  ('FRESH_LEAD', 'Fresh lead', 10, true),
  ('FOLLOW_UP', 'Follow-up', 20, true),
  ('INTERESTED', 'Interested', 30, true),
  ('PENDING_REGISTRATION_DATA', 'Pending registration data', 40, true),
  ('GST_REGISTRATION_DONE', 'GST registration done', 50, true),
  ('SCHEDULED_PAYMENTS', 'Scheduled payments', 60, true),
  ('SUBSCRIBED', 'Subscribed', 70, true),
  ('NOT_INTERESTED', 'Not interested', 80, true)
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name,
  sort_order = EXCLUDED.sort_order,
  is_active = EXCLUDED.is_active,
  updated_at = now();
