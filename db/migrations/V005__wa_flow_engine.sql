-- V004: WhatsApp Flow Engine runtime tables (Workflow Builder Slice 1)
--
-- Creates wa_flow_runs and wa_outbox per doc 09 §3.5 DDL.
--
-- wa_flow_runs: one row per customer per run instance; holds the node graph
--   snapshot (context.__flow_def) so in-flight runs are unaffected by
--   subsequent publishes (doc 09 §3.6 versioning).
--
-- wa_outbox: decouples Evolution API HTTP calls from the scheduler tick.
--   Primary idempotency and retry layer.  Producer supplies idempotency_key:
--   flow sends use '{flow_run_id}:{node_id}'; direct sends use a caller-built
--   key.  Body is final at enqueue time (tokens resolved at enqueue, not send;
--   the stored body is the audit record).

-- ---------------------------------------------------------------------------
-- wa_flow_runs
-- ---------------------------------------------------------------------------

CREATE TABLE solvetax.wa_flow_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_id         UUID NOT NULL REFERENCES solvetax.wa_flows(id),
    flow_version    INT  NOT NULL,          -- snapshot of wa_flows.version at run start
    customer_id     BIGINT NOT NULL REFERENCES solvetax.customers(customer_id),
    phone           TEXT NOT NULL,          -- 10-digit, denormalised for webhook lookup
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','waiting','completed','failed','cancelled')),
    current_node_id TEXT NOT NULL,
    context         JSONB NOT NULL DEFAULT '{}',
    -- context keys:
    --   CRM snapshot fields (customer_name, gst_number, filing_status, ...)
    --   __flow_def: full live_data JSONB snapshot at run creation
    --   __source_row_id: PK of the triggering source row (e.g. gst_filing_return_details.id)
    --                    captured at enrollment; anchors Condition live re-reads
    --   __error: set by stale-run reaper or handler exceptions
    wait_type       TEXT CHECK (wait_type IN ('delay','reply')),
    wake_at         TIMESTAMPTZ,
    heartbeat_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fast tick query: claims runnable runs (running or delay-wait past wake_at)
CREATE INDEX idx_wa_flow_runs_tick
    ON solvetax.wa_flow_runs (status, wake_at NULLS FIRST)
    WHERE status IN ('running','waiting');

-- Prevents a customer from being enrolled twice in the same flow simultaneously.
-- ON CONFLICT DO NOTHING on INSERT uses this index.
CREATE UNIQUE INDEX idx_wa_flow_runs_active
    ON solvetax.wa_flow_runs (flow_id, customer_id)
    WHERE status IN ('running','waiting');

-- ---------------------------------------------------------------------------
-- wa_outbox
-- ---------------------------------------------------------------------------

CREATE TABLE solvetax.wa_outbox (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_run_id      UUID REFERENCES solvetax.wa_flow_runs(id),   -- NULL for direct/non-flow sends
    node_id          TEXT NOT NULL,
    phone            TEXT NOT NULL,
    body             TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','sending','sent','failed','cancelled')),
    retry_count      INT  NOT NULL DEFAULT 0,
    next_retry_at    TIMESTAMPTZ,
    evolution_msg_id TEXT,
    instance_name    TEXT,                  -- stamped at dispatch time
    -- Producer supplies idempotency_key:
    --   flow sends use '{flow_run_id}:{node_id}'
    --   direct sends use '{category}:{entity_id}:{IST-date}'
    idempotency_key  TEXT NOT NULL UNIQUE,
    -- DPDP Act data minimisation: message bodies purged after 30 days
    purge_after      TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '30 days'),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at          TIMESTAMPTZ
);

-- Dispatcher poll: pending rows with no retry or retry due now
CREATE INDEX idx_wa_outbox_dispatch
    ON solvetax.wa_outbox (status, next_retry_at NULLS FIRST)
    WHERE status = 'pending';

-- Activity log panel: last N outbox rows for any customer/flow
CREATE INDEX idx_wa_outbox_activity ON solvetax.wa_outbox (created_at DESC);
