-- V003: WhatsApp Flows store (Workflow Builder Slice 1 CRUD)
--
-- Creates wa_flows per doc 09 §3.5 DDL.
-- ONLY wa_flows — wa_flow_runs and wa_outbox are out of scope for Slice 1 API.
--
-- created_by references solvetax.employees(emp_id) as specified in §3.5.

CREATE TABLE solvetax.wa_flows (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    trigger_type TEXT NOT NULL
                 CHECK (trigger_type IN ('inbound_keyword','scheduled_date','crm_event')),
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft','published','archived')),
    is_active    BOOLEAN NOT NULL DEFAULT true,
    draft_data   JSONB NOT NULL DEFAULT '{}',
    live_data    JSONB,            -- NULL until first publish; executor reads only this
    version      INT  NOT NULL DEFAULT 0,
    created_by   BIGINT REFERENCES solvetax.employees(emp_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
