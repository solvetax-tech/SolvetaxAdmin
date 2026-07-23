# 08 — Phased Rollout Plan

> **Audience:** SolveTax engineering and product leads.
> **Scope:** Planning-only document. No code is prescribed here; each phase requires a `/plan-eng-review` before build begins. Timelines are illustrative; adjust to actual team capacity and ban-risk appetite.
>
> **Prerequisite reading:** `07-risks-compliance.md`. Understand the ToS position, 68% Indian ban rate, DPDP Act obligations, and known operational bugs before committing to any phase.

---

## Standing Prerequisites (All Phases)

These must be in place before any phase starts:

1. **Dedicated WhatsApp number** — a fresh SIM used only for business automation, separate from any personal or previously-used number. Register it under the SolveTax business identity.
2. **Consent records in the main DB** — a `wa_consent` table (or column on the client record) storing: client ID, phone number, consent timestamp, consent source (form URL + version), purposes consented to (transactional / promotional separately), and opt-out flag. No outbound send may fire unless `revoked_at IS NULL`.
3. **DLT registration** — register SolveTax as a Principal Entity on a TRAI DLT platform (BSNL DLT, Videocon DLT, or similar). Required by TRAI TCCCPR February 2025 amendment for bulk WhatsApp messaging from Indian businesses.
4. **DPDP baseline** — before any client WhatsApp data touches the Evolution API Postgres schema: disable `DATABASE_SAVE_DATA_NEW_MESSAGE` (set to `false`) unless there is a documented legal basis for message-content retention; implement scheduled hard-delete jobs; encrypt phone number columns at rest. See `07-risks-compliance.md §8`.
5. **Evolution API version pinned at v2.3.7** — do not upgrade to v2.4.0 until it is tagged stable and the mandatory license-server activation behavior is confirmed. Pin `evoapicloud/evolution-api:2.3.7` in all deployment configs.

---

## Phase 0 — Sandbox and Baseline Validation

### Goals

- Deploy Evolution API as a standalone service (separate from SolvetaxAdmin's main FastAPI container).
- Confirm basic connectivity: QR scan, instance state, manual message send.
- Validate the Manager UI and REST API against the team's Azure environment.
- Establish deployment artifacts (container config, env vars, health check) before any client data is involved.

### Prerequisites

- Azure Container Instance (or App Service) provisioned with at least 2 GB RAM (4 GB recommended) and a persistent volume for session storage.
- A dedicated Postgres database (or separate schema in an existing non-production instance) for Evolution API's Prisma schema. Do not share with the main SolvetaxAdmin DB schema.
- Redis instance (can share the existing managed Redis if namespace-isolated). Alternatively, run without Redis initially (`REDIS_ENABLED=false`) to avoid the false-duplicate-suppression bug (GitHub #2110) during initial testing — verify against current docs whether this setting is available in v2.3.7.
- A test phone number (not a client-facing number) to scan QR with.
- **No client phone numbers at this stage.**

### Key Activities

1. Deploy `evoapicloud/evolution-api:2.3.7` with minimal env config:
   ```
   SERVER_TYPE=http
   AUTHENTICATION_API_KEY=<strong-random-key>
   DATABASE_PROVIDER=postgresql
   DATABASE_CONNECTION_URI=<postgres-dsn>
   DATABASE_SAVE_DATA_NEW_MESSAGE=false
   DATABASE_SAVE_DATA_HISTORIC=false
   DATABASE_SAVE_DATA_CONTACTS=false
   DATABASE_SAVE_DATA_CHATS=false
   WEBHOOK_RETRY_MAX_ATTEMPTS=3
   WEBHOOK_RETRY_INITIAL_DELAY_SECONDS=5
   WEBHOOK_RETRY_USE_EXPONENTIAL_BACKOFF=true
   WEBHOOK_RETRY_MAX_DELAY_SECONDS=60
   ```
2. Access Manager UI at `/manager`. Create one instance via UI and via REST (`POST /instance/create`).
3. Scan QR code (do not use pairing code — GitHub #2215, pairing code login receives no events).
4. Verify `GET /instance/connectionState/{name}` returns `open`.
5. Send a test text message to the test number via `POST /message/sendText/{instance}`. Confirm delivery.
6. Verify Prisma migrations ran cleanly (`npx prisma migrate status` inside container).
7. Send test webhook events to a local `requestbin` or `ngrok` tunnel; confirm payload shape matches the documented `MESSAGES_UPSERT` schema (fields: `key.id`, `key.remoteJid`, `key.fromMe`, `pushName`, `messageType`, `messageTimestamp`, `instanceId`).
8. Simulate a 15-minute container restart; confirm session re-attaches without QR re-scan (persistent volume working).

### Exit Criteria

- [ ] Instance connects and holds connection for 24 hours without manual intervention.
- [ ] Manual send and receive work end-to-end.
- [ ] Webhook delivers to a test endpoint with correct payload shape.
- [ ] Container restart recovers session from persistent volume without QR re-scan.
- [ ] Prisma migrations show no pending items.
- [ ] Manager UI accessible and instance visible.
- [ ] Memory headroom confirmed: monitor container memory usage over 24 hours; Evolution API container must stay below 1.2 GB peak to leave headroom for the main FastAPI container on B1 (1.75 GB total). If peak exceeds 1.2 GB, escalate to Azure Container Instance (ACI) before proceeding to Phase 1.

### Rollback

Delete the Azure Container Instance. The main SolvetaxAdmin app is untouched. No client data has been processed.

---

## Phase 1 — One-Way Transactional Notifications

### Goals

- Replace or supplement manual staff follow-up with automated WhatsApp reminders for filing deadlines, payment due dates, and document receipt confirmations.
- Send only to clients who have explicitly consented via a form or in-app opt-in captured in the `wa_consent` table.
- Do not ingest any inbound replies yet (no webhook receiver in the main app).

### Prerequisites

- Phase 0 exit criteria met.
- `wa_consent` table implemented and populated with at least pilot-batch consent records (start with 20–50 clients maximum, all of whom have consented explicitly).
- Number has been in active manual use for at least 7 days (partial warm-up).
- A `/plan-eng-review` has been run on the integration design before build begins.
- Rate-limiting is enforced with asyncio.create_task() per outbound send, with await asyncio.sleep(delay) between tasks. No separate worker process or queue library is needed — WORKERS=1 means all sends run in the same asyncio event loop. Track last-sent timestamp per instance in Redis to enforce the inter-message delay across scheduler ticks.
- The Evolution API container URL is injected into SolvetaxAdmin via an environment variable (e.g., `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`). No hardcoded URLs.

### Architecture

```
SolvetaxAdmin backend (FastAPI + asyncpg)
  └── follow_up / scheduler trigger (existing asyncio loop, 60s tick)
        └── checks wa_consent, opt-out flag, last_notified_at
              └── enqueues message task to Redis queue
                    └── worker sends POST /message/sendText/{instance} to Evolution API
                          └── Evolution API → WhatsApp
```

The existing scheduler loop already runs every 60 seconds with a Redis distributed lock. Extend it to check for due follow-up or reminder records and enqueue outbound messages — do not send inline from the scheduler tick.

### Key Activities

1. Add `wa_consent` fields to the client record or a linked table (migration via the existing Python runner + YAML manifest).
2. Add opt-in capture to the client onboarding form (unchecked checkbox, explicit language for transactional WhatsApp messages).
3. Implement a `WhatsAppQueue` worker that reads from Redis queue and calls Evolution API with rate-limiting enforced.
4. Message types for Phase 1: plain text only (`POST /message/sendText/{instance}`). No rich media, buttons, or lists in this phase (buttons/lists are broken in v2.3.7 Baileys — GitHub issue, closed as "not planned").
5. Log each send attempt with: client ID (not phone number in the log), message type, send timestamp, Evolution API response status, and the `key.id` returned. Store in the `wa_messages` table with `evolution_message_id TEXT UNIQUE` set to the `key.id` returned by Evolution API. Insert outbound rows using `ON CONFLICT (evolution_message_id) DO NOTHING` on retry to ensure idempotency. The `wa_messages` table created here (outbound rows only) is extended in Phase 2 to add inbound rows — no rename, no separate table.
6. Implement a per-instance daily send counter backed by Redis. Block sends when the daily cap is reached (cap: 50 during weeks 1–2, then increase per the warm-up table in `07-risks-compliance.md §5`).
7. Do not call `POST /chat/whatsappNumbers/{instance}` in bulk to validate numbers — this triggers bans (GitHub #2228). Validate only at the point of opt-in, one number at a time, with a minimum 30-second delay between checks if batching is needed.

### What We Deliberately Defer (YAGNI)

- Inbound message handling (Phase 2).
- Two-way conversation UI (Phase 2).
- Template-based messages or interactive components (Phase 3 or official API migration).
- Voice note transcription (Phase 4).
- Chatwoot or any CRM inbox integration (Phase 2+).
- Campaign/broadcast to unengaged clients (Phase 3).
- Multiple WhatsApp instances / numbers (only if Phase 1 volume demands it; re-evaluate then).

### Exit Criteria

- [ ] 50+ transactional messages sent to consented clients over at least 2 weeks with zero ban events.
- [ ] Daily send counter enforced; no sends above cap.
- [ ] Per-send log persisted with status and `key.id`.
- [ ] Opt-out honored: zero sends to clients with `revoked_at IS NOT NULL`.
- [ ] Queue worker recovers after Evolution API restart without duplicate sends (idempotency on `key.id`).
- [ ] No webhook floods observed on the Evolution API container logs (verify retry env vars are set).

### Rollback

Disable the queue worker (feature flag or env var `WHATSAPP_ENABLED=false`). No client-facing UI is affected. The Evolution API container can remain running or be stopped.

---

## Phase 2 — Inbound + Two-Way CRM Chat

### Goals

- Receive client WhatsApp replies and surface them inside the SolvetaxAdmin CRM dashboard for staff to respond to.
- Enable staff to send replies from within SolvetaxAdmin (not just automated triggers).
- Begin building a conversation thread view attached to the client record.

### Prerequisites

- Phase 1 running stably for at least 4 weeks with no ban events.
- Number has been active for 6+ weeks; daily send volume is well within the mature-account cap.
- A `/plan-eng-review` on the inbound webhook architecture and conversation data model before build.
- Decision made on whether to integrate Chatwoot (built-in Evolution API integration, creates a Chatwoot inbox automatically) or build a lightweight native conversation UI in SolvetaxAdmin. Chatwoot is the lower-effort path for true two-way agent-facing chat; a native UI is higher effort but stays in-product. This decision should be made at planning time, not deferred to build.
- Conversation thread updates use client-side polling at 5-second intervals against `GET /api/v1/whatsapp/conversations/{phone}`. SSE is not viable without dedicated infrastructure changes (WORKERS=1 means one long-lived connection blocks a worker slot under concurrent requests). Polling is sufficient for the expected staff-count (10–20 concurrent users). Revisit SSE only if polling latency is measurably unacceptable after Phase 2 is live.

> **DECISION REQUIRED before any Phase 2 build: Chatwoot integration or native UI.** Chatwoot path: Evolution API native integration handles all message routing; SolvetaxAdmin embeds the Chatwoot UI via iframe or Chatwoot JS SDK; no `wa_messages` table in SolvetaxAdmin; no webhook receiver in SolvetaxAdmin; estimated effort: 2–3 days. Native path: all components in this section apply; estimated effort: 3–4 weeks. If Chatwoot is chosen, replace this entire section with a short Chatwoot integration spec. Do not start any build in this section before this decision is recorded in the project task tracker.

### Architecture (Native UI path — no Chatwoot)

```
Evolution API
  └── POST webhook to SolvetaxAdmin /api/v1/whatsapp/webhook
        └── FastAPI route (new, protected by Evolution API webhook secret header)
              └── idempotency: Redis NX fast-reject (fail-open) + DB ON CONFLICT guard (see §2.2 of doc 06)
                    └── write to wa_messages table (client_id, direction, content_type, body, timestamp, read_at)
                          └── push to frontend via client-side polling (5-second interval, GET /api/v1/whatsapp/conversations/{phone})

Staff reply:
SolvetaxAdmin CRM UI → POST /api/whatsapp/send/{client_id}
  └── validates consent + opt-out
        └── enqueues to WhatsAppQueue (same rate-limited worker as Phase 1)
```

### Key Activities

1. Add an inbound webhook route to SolvetaxAdmin: `POST /api/v1/whatsapp/webhook`. Authenticate using a shared secret (custom `X-Webhook-Secret` header set on the Evolution API instance via `POST /webhook/set/{instance}` `headers` field).
2. Implement the two-layer idempotency strategy defined in `06-solvetax-integration-architecture.md §2.2` (conversation_service.py responsibilities): Redis SET NX `wa:msg:{key.id}` EX 300 as a fast-reject (fail-open), followed by `INSERT ON CONFLICT (evolution_message_id) DO NOTHING` as the authoritative guard. Do not rely on Redis NX alone — it will not deduplicate under a Redis outage. Drop duplicates silently (log at DEBUG, not ERROR — duplicates are expected given GitHub #1325).
3. Add periodic health-check job: `GET /webhook/find/{instance}` every 15 minutes. Alert if the expected events array has changed (webhook self-disabling bug, GitHub #1559). Re-set if needed. Implementation: track last webhook health-check timestamp in Redis under key `wa:webhook_health_check:{instance_name}` with a 14-minute TTL (SETEX). In the scheduler tick, check if this key exists; if it does, skip the job. If it is missing (key expired), run the check and re-set the key. This requires no scheduler refactor and adds one Redis GET per tick.
4. Extend the `wa_messages` table (created in Phase 1 for outbound rows) to add inbound columns via migration: `instance_name`, `remote_jid`, `direction` (inbound/outbound), `content_type`, `body_text`, `media_url`, `timestamp`, `read_at`, `deleted_at` (soft). No rename, no separate table — the same `wa_messages` table now tracks both outbound and inbound rows.
5. Surface conversation thread in the CRM client detail view. Show last N messages (paginated). Allow staff to type and send a reply.
6. Enable `MESSAGES_UPSERT` and `MESSAGES_UPDATE` webhook events on the instance. No group-message events (`GROUP_UPSERT`, `GROUP_UPDATE`) — do not add the business number to groups (webhook loop risk, GitHub #1746).
7. Implement read-receipt send: after staff opens a conversation, call `POST /chat/markMessageAsRead/{instance}` with body `{ "readMessages": [{ "remoteJid": "<jid>", "fromMe": false, "id": "<key.id>" }] }` to mark the client's messages as read (governs `read receipts` setting on the instance). Make this optional and staff-controlled; do not auto-mark as read.

### What We Deliberately Defer (YAGNI)

- Automated chatbot/triage responses (Phase 4).
- OpenAI Whisper voice note transcription (Phase 4).
- Multi-agent assignment or Chatwoot-style queue management (evaluate post-Phase 2).
- Campaign broadcasts (Phase 3).
- WhatsApp group management endpoints (not applicable to tax-firm client communications).

### Exit Criteria

- [ ] Inbound messages from consented clients appear in the CRM within 30 seconds of receipt.
- [ ] Staff can reply from the CRM; reply appears on client's WhatsApp within 30 seconds.
- [ ] Duplicate webhook events do not create duplicate DB rows (idempotency verified in load test).
- [ ] Webhook health-check job fires and detects a simulated self-disabling event.
- [ ] No ban events over 2 weeks of two-way operation.
- [ ] `wa_messages` retention-period hard-delete job runs correctly (test with a manually back-dated row).

### Rollback

Disable the webhook route (return 200 immediately without processing) via feature flag. Staff reply sends fall back to Phase 1 queue. No data loss; messages persist in `wa_messages` table.

---

## Workflow Builder Phases (Slices 0–3)

> **Detail:** All phase definitions, node types, engine design, and full exit-criteria checklists are in `09-node-workflow-builder.md`. This section records rollout position and abbreviated criteria only.

The workflow builder is additive to the phases above. Slices 0–1 can overlap with Phase 2 build work if a second developer is available; Slice 3 requires the Phase 2 webhook receiver to be live.

### Workflow Builder Slice 0 — Prerequisites (3–5 days, after Phase 0)

**Goals:** Shared infrastructure before any engine work: `wa_consent` migration (shared with Phase 1 if not already landed), `wa_instance_config` migration + seed row (`daily_send_cap=50`), `create_task_for_emp()` extracted as an internal service function from `employee_tasks/employee_tasks.py` (system-generated task calls satisfy NOT NULL columns with a synthetic single slot — see doc 09 §5), `send_service.py` with consent re-check, quiet-hours enforcement, and Redis rate counter. Also: `pytest` + `pytest-asyncio` scaffolding with asyncpg transaction-rollback fixture and CI step failing the build on test failure (see doc 09 §5).

**Prerequisites:** Phase 0 exit criteria met.

**Exit criteria:** `send_service.send()` raises `ConsentError`, `QuietHoursError`, and `RateLimitError` correctly — verified in unit tests using `DryRunSink`. No Evolution API calls made by any test.

**Rollback:** No runtime change; migrations can be applied without activating any scheduling steps.

### Workflow Builder Slice 1 — Engine Without Canvas (10–12 days, 1 backend developer; can overlap with Phase 2)

**Goals:** `wa_flows`, `wa_flow_runs`, `wa_outbox` migrations; `flow_engine.py` with the 6 handlers the proving journey exercises (see doc 09 §3.3); scheduler steps 14a–14c; simulation endpoint; flow CRUD API (`/validate` endpoint included). Validate end-to-end with a seeded GSTR-3B 7-day journey against 2–3 internal test numbers.

**Prerequisites:** Workflow Builder Slice 0 exit criteria met; Phase 1 exit criteria met. HARD gate: consent capture built (owner: founder; decided 2026-07-23 — multiple mechanisms, `wa_consent.source` enum: `STAFF_RECORDED` / `OPT_IN_LINK` / `ONBOARDING_FORM`, staff-recorded surface first) — Slice 1 does not ship to production before first real `wa_consent` rows exist.

**Exit criteria:** GSTR-3B 7-day journey runs end-to-end to a test number; Wait node resumes after `wake_at`; outbox idempotency key prevents duplicate rows; stale-run reaper marks timed-out runs `failed`; consent gate and quiet-hours tests pass; cycle detection rejects a back-edge flow; simulation returns `{trace, would_send}` without persisting rows. Also: same-period dedupe, live-Condition re-read, stuck-`'sending'` re-queue, instance-resolution (0/1/2 active rows), and enrollment-query timing gate. See doc 09 §5 for the full checklist.

**Rollback:** Remove scheduler steps 14a–14c from `schedular.py`. Migrations stay in place (tables remain empty).

### Workflow Builder Slice 2 — React Canvas (10–14 days, 1 frontend developer; can overlap with Slice 1)

**Goals:** `@xyflow/react` v12 installed; `/whatsapp-flows` route with `FlowList.jsx` and `FlowEditor.jsx`; 9 node components with config drawers; variable picker (static dropdown per trigger type); 6 client-side publish-gate checks with "Jump to node" buttons; simulate button with trace visualisation; `is_active` toggle; activity log tab in `/dashboard`.

**Prerequisites:** Workflow Builder Slice 1 exit criteria met (API must exist for the canvas to call).

**Exit criteria:** Staff can create, edit, publish, and activate a flow without developer assistance; publish gate blocks a disconnected `Condition` node, a missing `EndFlow`, and a cycle; auto-save recovers in-progress edits after a browser refresh. See doc 09 §5 for the full checklist.

**Rollback:** Remove the `/whatsapp-flows` route from `App.jsx` and the nav item. Backend API and DB tables are unaffected.

### Workflow Builder Slice 3 — Inbound Bot Flows (5–7 days, after Slice 2 and Phase 2)

**Goals:** implement `InboundKeyword` and `Wait(reply)` handlers in `flow_engine.py` (deferred from Slice 1); wire `InboundKeyword` trigger to the Phase 2 webhook receiver; add fromMe/group-JID discard filter (see doc 09 §3.5); reply-Wait resume logic in the webhook handler; first inbound bot (keyword "GST" → `SendMessage` → `Wait (reply, 24h)` → `Condition` → `AssignTask` or reply → `EndFlow`).

**Prerequisites:** Workflow Builder Slice 2 exit criteria met; Phase 2 exit criteria met (webhook receiver live).

**Exit criteria:** Inbound "GST" message creates a `wa_flow_runs` row and bot replies within 60 seconds; reply-Wait resumes on the next client message within the timeout window; `on_timeout` branch fires when no reply arrives within `timeout_hours`. See doc 09 §5 for the full checklist.

**Rollback:** Disable the `InboundKeyword` enrollment path in the webhook handler via feature flag; existing conversation handling is unaffected.

---

## Phase 3 — Campaigns at Scale

### Goals

- Enable structured broadcast campaigns to segmented client lists (e.g., "all clients with pending ITR for FY 2025–26 and no filing appointment scheduled").
- Implement warm-up-aware rate limiting for higher-volume sends.

> **Warning:** The existing SolvetaxAdmin "campaign" module is a UTM/device-analytics capture pipeline, not a messaging campaign system (see codebase research summary). A new campaign entity is needed. Do not reuse the analytics `d_customer_session` table for messaging campaigns.

### Prerequisites

- Phase 2 running stably for at least 4 weeks.
- Business number is 3+ months old with consistent daily send history.
- Consent records cover the full target segment; no sends to clients without explicit promotional opt-in (separate from transactional consent).
- DLT registration confirmed active for the sending entity.
- A `/plan-eng-review` on the campaign data model and scheduling architecture before build.
- Decision on official API migration: if campaign volume targets exceed 500 messages/day or include marketing-category content, evaluate switching to the official WhatsApp Business API. At that volume and ToS exposure, the official API's utility pricing (~₹0.115/message) is cost-effective and eliminates ban risk. Run the business case at this decision point.

### Architecture

```
CRM campaign UI
  └── staff creates campaign: name, segment query, message template(s), scheduled_at
        └── POST /api/campaigns → saves to campaigns + campaign_recipients tables
              └── scheduler picks up at scheduled_at
                    └── iterates recipients with enforced inter-message delay
                          └── WhatsAppQueue worker → Evolution API → WhatsApp
                                └── delivery status webhooks update campaign_recipients.status
```

### Key Activities

1. New DB entities: `wa_campaigns` (id, name, segment_filters JSONB, status, scheduled_at, created_by, created_at), `wa_campaign_recipients` (id, campaign_id, client_id, status, sent_at, delivered_at, read_at, error). The campaign scheduler reads `segment_filters`, passes them to the existing CRM filter query in `crm_leads_common.py`, and gets back a recipient list. Never store SQL strings in data columns — use the structured filter model already in crm_leads_common.py.
2. Campaign scheduler: reads due campaigns, builds recipient list, enqueues to WhatsAppQueue with campaign-level rate cap (start at 80 messages/day for the account at this age, increase per warm-up table in `07-risks-compliance.md §5`).
3. Send one message per campaign. Manually review message tone and length before each campaign (checklist item in the pre-send approval flow). If ban events occur and are attributed to identical-message detection, add template rotation at that point. Do not build rotation logic speculatively.
4. Batch pacing: between every 50 messages, use `await asyncio.sleep(600)` inside the async send loop. In this codebase (asyncio, WORKERS=1), `await asyncio.sleep()` is non-blocking — it yields to the event loop while waiting. No separate queue-pause mechanism is needed. Caution: do not use synchronous `time.sleep()`, which would block the entire event loop.
5. Delivery status tracking: ingest `MESSAGES_UPDATE` webhook events to update `wa_campaign_recipients.status`. Build a campaign report view in the CRM showing sent/delivered/read/failed counts.
6. Unsubscribe handling: if a client replies "STOP" or any variant, set `revoked_at = NOW()` on the consent record immediately. Implement keyword detection in the inbound webhook handler (Phase 2 deliverable must already exist).

### What We Deliberately Defer (YAGNI)

- A/B testing framework for message templates.
- Automated campaign scheduling from ML-predicted optimal send times.
- Multi-number rotation to increase throughput (this increases ban risk via Layer 4 shared-infrastructure detection and requires re-evaluating the entire deployment architecture).
- WhatsApp template approval workflows (only relevant after official API migration).

### Exit Criteria

- [ ] Campaign of 200 messages sends over 4+ hours with all rate limits enforced.
- [ ] No ban events during or after the campaign.
- [ ] Delivery/read status updates correctly in the campaign report within 5 minutes.
- [ ] STOP keyword unsubscribes the client and suppresses further sends from the same campaign.
- [ ] Campaign can be paused and resumed without duplicate sends.

### Rollback

Pause all pending campaigns (status = `paused`). The WhatsAppQueue worker continues to serve Phase 1 and Phase 2 sends unaffected.

---

## Phase 4 — Optional: Voice Note Transcription and Chatbot Triage

### Goals

- Transcribe inbound WhatsApp voice notes (clients often send audio instead of typing) to text for staff review.
- Optionally triage inbound messages with a simple keyword-based or LLM-based classifier before routing to staff.

> This phase is entirely optional. Evaluate after Phase 3 is stable and staff have expressed demand. Do not build speculatively.

### Prerequisites

- Phase 2 and Phase 3 running stably.
- A `/plan-eng-review` before any build. Voice note transcription (OpenAI Whisper via Evolution API's built-in OpenAI integration) introduces a new external dependency and per-transcription cost.
- OpenAI API key and cost budget approved.
- Chatbot triage (if pursued) requires a separate `/plan-eng-review` and an explicit decision on scope: keyword-based (low complexity, no LLM cost) vs. LLM-based (higher quality, per-call cost, latency).

### Key Activities (Voice Transcription)

1. Enable Evolution API's built-in OpenAI integration: set `OPENAI_ENABLED=true` and configure an OpenAI instance via `POST /openai/{instance}` with `triggerType: all` and Whisper settings. This routes incoming voice note audio through OpenAI's Whisper-1 model.
2. The transcription result arrives in the `MESSAGES_UPSERT` webhook payload (verify exact field name against current docs at docs.evolutionfoundation.com.br). Write the transcript alongside the message record in `whatsapp_message.transcription_text`.
3. Surface transcript text in the CRM conversation view alongside the audio player.

### Key Activities (Chatbot Triage — if pursued)

1. Decide on integration path: Evolution API's built-in Typebot integration (low-code, routes within Evolution API), or a custom webhook-based classifier in the SolvetaxAdmin backend (more control, more code).
2. Keyword-based triage (preferred for first iteration): match inbound message body against a keyword list (e.g., "GST", "ITR", "payment", "refund", "document") and auto-tag the conversation in the CRM. No LLM required. Staff still handle all replies.
3. LLM-based triage (if keyword matching is insufficient): call the Claude API from the SolvetaxAdmin backend on each inbound message. Tag + suggest a reply draft. Do not auto-reply without staff review.

### What We Deliberately Defer (YAGNI)

- Fully automated reply bots (high ban risk from zero reply-ratio pattern; also requires explicit Meta authorization for chatbots post-October 2025 ToS amendment).
- WhatsApp Flows or interactive form features (Cloud API-only; not available in Baileys mode).
- Multi-language support beyond English and Hindi.

### Exit Criteria

- [ ] Voice notes from at least 10 test messages transcribed correctly with <5 second additional latency.
- [ ] Transcript persisted and visible in CRM conversation view.
- [ ] (If chatbot triage built) At least 80% of test messages correctly tagged by keyword/classifier.
- [ ] No increase in ban events attributable to Whisper/OpenAI integration.

### Rollback

Set `OPENAI_ENABLED=false` on the Evolution API instance. Inbound messages continue to route to staff unchanged.

---

## What We Deliberately Defer Across All Phases

The following are excluded from this rollout plan. Revisit only with explicit product/business justification and a `/plan-eng-review`:

| Deferred Item | Reason |
|---|---|
| Multiple WhatsApp numbers / instances | Increases Layer 4 ban risk; adds operational complexity. Evaluate only if single-number volume ceiling is provably hit. |
| WhatsApp group management | Not applicable to tax-firm client comms model; webhook loop risk (GitHub #1746). |
| Status broadcasts (sendStatus) | Endpoint hangs indefinitely on all payload variants in v2.3.7 (closed as "not planned"). |
| Buttons and list messages (Baileys) | Broken in v2.3.7 — returns 201, never delivers (closed as "not planned"). |
| Official API template management UI | Only relevant after official API migration decision is made. |
| Chatbot auto-reply without staff review | ToS violation (October 2025 Meta amendment); ban risk from zero-reply pattern. |
| S3/MinIO media storage | Not needed until media volume justifies it. Default local filesystem is adequate for Phase 1–2. See 05-integrations.md §8 for setup options and compatibility notes when this becomes necessary. |
| n8n / Typebot / Flowise built-in integrations | Formally rejected in favour of BUILD-MINIMAL after architecture evaluation (doc 09 §2); extra dependencies not needed given SolvetaxAdmin's existing backend. |
| Pusher / Kafka / SQS transports | Webhook HTTP is sufficient for Phase 1–3 volumes. |
| Evolution API Manager UI exposed publicly | Keep behind internal/private network. Manager UI is for admin use only. |

---

## When to Abandon Evolution API and Migrate to Official API

Trigger any one of these conditions to initiate migration:

1. First number ban.
2. Sustained daily volume exceeds 500 messages/day (ban risk increases substantially; official API utility cost becomes economically comparable to operational disruption cost of a ban).
3. Marketing-category campaigns are needed (template approval required; no compliant path via Baileys).
4. Any DPDP Act regulatory inquiry or audit notice related to WhatsApp data.
5. A regulatory clarification that DLT registration alone does not provide a safe harbor for unofficial API use.

Migration path: provision an official WhatsApp Business account via a BSP (see `07-risks-compliance.md §7`), switch the Evolution API instance integration from `BAILEYS` to `WHATSAPP-BUSINESS-CLOUD` (Meta Cloud API mode), update templates, and deprecate any Baileys-only message types from the send queue.

---

## Phase Gate: /plan-eng-review Requirement

Every phase must receive a `/plan-eng-review` before implementation begins. The brief for each review should include:

- The specific Evolution API endpoints being integrated (with exact route patterns from `docs.evolutionfoundation.com.br`).
- The data model changes (new tables, columns, migrations).
- The queue/rate-limiting design.
- The idempotency strategy for webhook consumers.
- The rollback procedure.
- The DPDP compliance checklist for any new personal data fields being stored.

Do not skip this step for "small" phases. Integration points with external services accumulate hidden complexity.

---

## Sources

- https://github.com/EvolutionAPI/evolution-api
- https://github.com/evolution-foundation/evolution-api
- https://github.com/evolution-foundation/evolution-api/releases
- https://github.com/EvolutionAPI/evolution-api/blob/main/.env.example
- https://github.com/EvolutionAPI/evolution-api/blob/main/CHANGELOG.md
- https://github.com/evolution-foundation/evolution-api/issues/2538
- https://github.com/evolution-foundation/evolution-api/issues/2534
- https://github.com/EvolutionAPI/evolution-api/issues/2228
- https://github.com/EvolutionAPI/evolution-api/issues/2110
- https://github.com/evolution-foundation/evolution-api/issues/1746
- https://github.com/evolution-foundation/evolution-api/issues/1325
- https://github.com/EvolutionAPI/evolution-api/issues/1911
- https://github.com/EvolutionAPI/evolution-api/blob/main/LICENSE
- https://docs.evolutionfoundation.com.br/en/evolution-api
- https://docs.evolutionfoundation.com.br/licensing/faq
- https://evolutionapi-evolution-api-90.mintlify.app/whatsapp/baileys
- https://deepwiki.com/EvolutionAPI/evolution-api/1.3-configuration
- https://blog.kraya-ai.com/whatsapp-automation-ban-risk
- https://wasenderapi.com/blog/how-to-use-evolution-api-without-getting-banned-on-whatsapp-2026-guide
- https://wasenderapi.com/blog/stop-getting-banned-the-ultimate-whatsapp-anti-ban-strategy-for-unofficial-apis-in-2025
- https://wasenderapi.com/blog/evolution-api-problems-2025-issues-errors-best-alternative-wasenderapi
- https://wasenderapi.com/blog/evolution-api-in-production-architecture-guide-for-scaling-multi-tenant-saas
- https://www.ojiva.ai/blogs/whatsapp-business-api-pricing-india/
- https://www.dpdpa.com/blogs/whatsapp_business_dpdpa_compliance_messaging_apps.html
- https://www.whatsapp.com/legal/terms-of-service
- https://developers.facebook.com/documentation/business-messaging/whatsapp/policy-enforcement
- https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform
- https://secureprivacy.ai/blog/india-dpdp-act-phase-1
- https://wa.expert/pages/whatsapp-opt-in-compliance-india
