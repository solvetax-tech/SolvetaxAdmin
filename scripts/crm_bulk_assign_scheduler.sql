-- =============================================================================
-- CRM bulk assign: schedulers + logs (run ENTIRE file in DBeaver — do not
-- highlight a single column; use Execute SQL Script / Alt+X on full selection)
-- =============================================================================

-- 1) Schedulers (multiple rules per entity_type; leads still live in crm_leads)
CREATE TABLE IF NOT EXISTS solvetax.crm_bulk_assign_schedulers (
    id bigserial PRIMARY KEY,
    name varchar(120) NOT NULL,
    entity_type varchar(64) NOT NULL,
    enabled bool NOT NULL DEFAULT false,
    filters jsonb NOT NULL DEFAULT '{}'::jsonb,
    assign_rm bool NOT NULL DEFAULT false,
    assign_op bool NOT NULL DEFAULT false,
    selected_rm_usernames jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_op_usernames jsonb NOT NULL DEFAULT '[]'::jsonb,
    per_employee_limit_rm int NULL,
    per_employee_limit_op int NULL,
    assign_unassigned_only bool NOT NULL DEFAULT true,
    interval_minutes int NOT NULL DEFAULT 5,
    rr_state jsonb NOT NULL DEFAULT '{"RM": 0, "OP": 0}'::jsonb,
    last_run_at timestamptz NULL,
    is_active bool NOT NULL DEFAULT true,
    created_by int8 NULL,
    updated_by int8 NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_assign_schedulers_entity
    ON solvetax.crm_bulk_assign_schedulers (entity_type, enabled)
    WHERE is_active = true;

-- 2) Logs (AUTO scheduler runs + MANUAL bulk assign from UI)
CREATE TABLE IF NOT EXISTS solvetax.crm_bulk_assign_logs (
    id bigserial PRIMARY KEY,
    scheduler_id int8 NULL REFERENCES solvetax.crm_bulk_assign_schedulers (id) ON DELETE SET NULL,
    run_type varchar(10) NOT NULL,
    entity_type varchar(64) NOT NULL,
    triggered_by int8 NULL,
    candidates_matched int NOT NULL DEFAULT 0,
    total_assigned_rm int NOT NULL DEFAULT 0,
    total_assigned_op int NOT NULL DEFAULT 0,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_crm_bulk_assign_run_type CHECK (run_type IN ('AUTO', 'MANUAL'))
);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_assign_logs_created
    ON solvetax.crm_bulk_assign_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_assign_logs_entity
    ON solvetax.crm_bulk_assign_logs (entity_type, run_type);

-- Verify (optional):
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'solvetax' AND table_name LIKE 'crm_bulk_assign%';
