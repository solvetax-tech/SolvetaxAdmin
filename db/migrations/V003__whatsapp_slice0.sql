-- V002: WhatsApp Workflow Builder Slice 0 prerequisites
--
-- Creates two tables required before any engine or Evolution API work:
--   wa_consent        — customer opt-in records (DPDP Act compliance)
--   wa_instance_config — runtime-tunable guardrail config per Evolution API instance
--
-- Source: docs/evolution-api/09-node-workflow-builder.md §3.5 and §3.7,
--         docs/evolution-api/06-solvetax-integration-architecture.md §2.2

-- ---------------------------------------------------------------------------
-- wa_consent
-- ---------------------------------------------------------------------------
-- Stores one row per consent grant.  A customer may have at most one active
-- (revoked_at IS NULL) consent per phone number; enforced by the partial
-- unique index below.
--
-- source enum per the founder decision recorded in doc 09 §6 item 3:
--   STAFF_RECORDED  — staff records consent during a client interaction
--   OPT_IN_LINK     — client clicks an explicit opt-in link sent via SMS/email
--   ONBOARDING_FORM — client ticks the opt-in checkbox on the public onboarding form
-- Each value demonstrates its own lawful basis under the DPDP Act.
--
-- phone stores the number in the same 10-digit, no-country-prefix format used
-- by customers.mobile so direct equality joins work without normalisation.

CREATE TABLE solvetax.wa_consent (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES solvetax.customers(customer_id),
    phone       TEXT NOT NULL CHECK (phone ~ '^[0-9]{10}$'),
    source      TEXT NOT NULL CHECK (source IN ('STAFF_RECORDED','OPT_IN_LINK','ONBOARDING_FORM')),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fast lookup by phone for active consents (used in send_service and enrollment).
CREATE INDEX idx_wa_consent_phone_active
    ON solvetax.wa_consent (phone)
    WHERE revoked_at IS NULL;

-- One active consent per (customer_id, phone) pair.
-- A second opt-in from the same customer on the same number must revoke the old
-- row first, preventing double-counting of consent strength.
CREATE UNIQUE INDEX idx_wa_consent_active_unique
    ON solvetax.wa_consent (customer_id, phone)
    WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- wa_instance_config
-- ---------------------------------------------------------------------------
-- Runtime-tunable guardrail config per Evolution API instance.
-- Eliminates env-var redeploys when raising the daily_send_cap during the
-- Baileys warm-up ladder (ops does a one-row UPDATE, no code change needed).
--
-- DDL is exactly the schema specified in doc 09 §3.5.

CREATE TABLE solvetax.wa_instance_config (
    instance_name     TEXT    PRIMARY KEY,
    daily_send_cap    INT     NOT NULL DEFAULT 50,
    quiet_hours_start INT     NOT NULL DEFAULT 9,
    quiet_hours_end   INT     NOT NULL DEFAULT 21,
    is_active         BOOLEAN NOT NULL DEFAULT true
);

-- Seed row.
-- 'primary' is a documented placeholder until Phase 0 names the real Evolution
-- API instance.  daily_send_cap=50 matches the initial Baileys warm-up limit
-- (doc 07 §5).  Quiet hours 09:00–21:00 IST per the default in doc 09 §3.7.
INSERT INTO solvetax.wa_instance_config
    (instance_name, daily_send_cap, quiet_hours_start, quiet_hours_end, is_active)
VALUES
    ('primary', 50, 9, 21, true);
