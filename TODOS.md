# TODOS

Deferred work items with context. Format: What / Why / Pros / Cons / Context / Depends on.

## WhatsApp workflow builder (docs/evolution-api/09)

### 1. Shared-mobile disambiguation for webhook flow resume

- **What:** Define behavior when two `customers` rows share the same `mobile` and an inbound WhatsApp reply must resume a waiting flow run.
- **Why:** `customers.mobile` has no unique constraint (V001__baseline.sql:1687). The webhook resume query matches `wa_flow_runs` by phone; with two customers on one number, a reply could resume the wrong customer's run or match two waiting runs.
- **Pros:** Deterministic resume semantics; no cross-customer data leakage into message variables.
- **Cons:** Requires a policy decision (most-recent run wins vs. staff triage) more than code.
- **Context:** Flagged in /plan-eng-review 2026-07-23 (failure-mode analysis, doc 09 §3.5 webhook resume). v1 ships with phone-based matching; the ambiguity only bites when a shared-mobile customer is enrolled. Interim guard worth considering at enrollment: skip enrollment when the phone maps to >1 customer, log at WARN.
- **Depends on:** Workflow Builder Slice 3 (webhook resume path exists).

### 2. Multi-instance routing (second WhatsApp number)

- **What:** Per-flow or per-department instance routing once SolveTax runs more than one WhatsApp number.
- **Why:** v1 deliberately enforces exactly one active `wa_instance_config` row (eng-review Issue 7); a second number (e.g. GST vs ITR desks) needs a routing rule, per-instance caps, and canvas UI.
- **Pros:** Separates client-facing identities; halves per-number ban blast radius.
- **Cons:** Per-flow instance selection UI, split cap accounting, and warm-up ladders per number.
- **Context:** Deferred by /plan-eng-review 2026-07-23 (Issue 7, option 7A). `wa_outbox.instance_name` is already stamped per send, so history migrates cleanly. Start from doc 09 §3.5 dispatcher instance-resolution rule.
- **Depends on:** A concrete second-number requirement; Slice 2 (canvas exists to host the selector).
