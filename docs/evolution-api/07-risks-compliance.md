# 07 — Risks, Bans, and Compliance

> **Audience:** SolveTax engineering and operations leads.
> **Scope:** Honest risk assessment for running Evolution API (Baileys mode) in production for an Indian tax-services business, consent obligations, data-protection requirements under DPDP Act 2023, official API as the compliant fallback, and known operational pitfalls with mitigations.

---

## 1. ToS Position — No Gray Area

Evolution API in Baileys mode reverse-engineers the WhatsApp Web WebSocket protocol. WhatsApp's Terms of Service (Acceptable Use section, current as of research date) explicitly prohibit all four of the following, each of which Baileys triggers independently:

| Prohibition | How Evolution API / Baileys Triggers It |
|---|---|
| Bulk messaging, auto-messaging | Any automated send |
| Reverse engineering the service | Baileys is a protocol RE implementation |
| Creating derivative APIs offered to third parties | Evolution API is exactly this |
| Non-personal use without authorization | Commercial tax-firm use |

October 2025: Meta amended WhatsApp Terms to additionally bar general-purpose chatbots without authorization.

**There is no compliant commercial use path for Evolution API / Baileys.** This is not a gray area to be managed with policy — it is an outright ToS violation from the moment the instance connects.

---

## 2. Ban Risk in India — Concrete Numbers

Kraya AI's analysis of 600+ Indian SMB accounts:

- **68% report at least one number ban within 12 months** of using unofficial WhatsApp automation tools.
- Typical detected lifespan before ban: **2–8 weeks** for Baileys-based tools.
- First-violation appeal success rate: **30–40%**.
- Estimated pipeline loss during a 3-week ban for a mid-size Indian team: **₹2–25 lakh**.

For a tax firm, a ban during March–July (ITR season) or the GST quarterly filing periods is operationally catastrophic.

---

## 3. WhatsApp's 4-Layer Detection System

Understanding the layers matters because most "anti-ban" advice only addresses layers 2–4. Layer 1 fires before any message is sent.

### Layer 1 — Protocol Fingerprinting (pre-message)

WhatsApp's servers analyze the WebSocket handshake and encryption key negotiation during connection. Baileys produces patterns that differ from legitimate WhatsApp clients. **Volume reduction, random delays, and spintax do not prevent Layer 1 detection.** Modified Baileys forks often get detected faster than patches can be released.

### Layer 2 — Behavioral Signals

- Fixed-interval sends (e.g., exactly 10 seconds between each message) are more dangerous than random intervals.
- Low reply ratio (messages sent vs. replies received) signals broadcast spam.

### Layer 3 — User Report Velocity

If a threshold percentage of recipients tap "Report and Block," Meta's system escalates immediately and can terminate the account without a human review step.

### Layer 4 — Shared Infrastructure

Multiple accounts on the same IP subnet can be flagged together when one instance is caught. Rotating numbers from the same VPS or Azure Container group creates correlated flags.

---

## 4. Specific Ban Triggers to Avoid

- Connecting a new SIM and sending bulk messages immediately (described in the wild as "guaranteed ban within minutes" for 1,000+ messages).
- Sending to numbers that have not explicitly opted in.
- Sending identical or near-identical messages at fixed intervals.
- Calling `POST /chat/whatsappNumbers/{instance}` (bulk number-checking endpoint) without rate limiting — GitHub issue #2228 (v2.3.4+, filed Nov 2025, no maintainer response as of research date).
- Frequent session login/logout cycles.
- Running multiple instances on the same IP simultaneously.
- Link-heavy messages with shortened URLs to new contacts.

---

## 5. Warm-Up and Send-Rate Best Practices

If proceeding with Evolution API despite the risks, these are the community-established minimums. They reduce layer 2–4 exposure; they do not address layer 1.

### Warm-Up Timeline

| Week | Activity | Max Daily Messages |
|---|---|---|
| 1 | Manual phone use only — join groups, have real conversations, receive more than you send. No automation. | 0 automated |
| 2 | Begin automated sends only to users who have previously engaged with you. | 10–20 |
| 3–4 | Increase by ~20% every few days. | 80–200 |
| 6+ months | Mature account, still use delays. | 200+ |

### Inter-Message Delays

- **15–45 second random interval** between individual messages. Never use fixed intervals.
- **10–15 minute rest period** after every 50 messages.
- Practical throughput ceiling: **10–20 messages per minute per instance** before anti-spam triggers.

### Daily Caps

| Account Age | Max Daily Messages |
|---|---|
| 0–14 days | 20–50 (manual warm-up only) |
| 2–4 weeks | 80–200 |
| 6+ months | 200+ (with delays still enforced) |

---

## 6. Opt-In and Consent Requirements

### WhatsApp Business Messaging Policy (applies regardless of which API is used)

- The client must have given SolveTax their mobile number **and** explicitly opted in to receive WhatsApp messages specifically.
- Opt-in must be traceable to a source: web form, IVR, in-app checkbox, POS.
- Pre-checked boxes do not satisfy this requirement.
- Prior SMS or email consent does not constitute WhatsApp opt-in.
- **Promotional messages require a separate, additional opt-in** distinct from transactional consent.
- Every promotional message must include an easy opt-out mechanism.

### India-Specific: TRAI TCCCPR (amended February 2025)

DLT (Distributed Ledger Technology) registration is now explicitly required for entities sending bulk messages, and the February 2025 amendments extended this mandate to cover WhatsApp messaging. Tax firms sending bulk WhatsApp reminders must register as a PE (Principal Entity) on a DLT platform.

### Consent Collection for a Tax Firm — Recommended Flow

1. On the lead intake or client onboarding form: explicit checkbox (unchecked by default) — "I agree to receive transactional updates (filing deadlines, payment reminders, document status) via WhatsApp at the mobile number provided."
2. For promotional messages (upsell, new services): a second, separate checkbox at the same form stage or at a later touchpoint.
3. Store consent timestamp, source (form URL/version), and the specific purposes consented to alongside the client record.
4. Honor opt-out requests: implement an opt-out flag on the client record and suppress all outbound sends when it is set. Fulfill within 30 days (DPDP right-to-erasure window).
5. Do not transfer consent from one channel (email list) to WhatsApp.

---

## 7. Official WhatsApp Business API — The Compliant Fallback

### When to Switch

Switch from Evolution API (Baileys) to the official API as soon as:

- Any number gets banned (ban risk is now demonstrated in your infrastructure).
- Client volume crosses 200 messages/day sustained.
- Any regulatory audit is anticipated.
- Campaign-style marketing messages (promotions, new service announcements) are required — these are banned under Baileys ToS and require template approval under the official API.

### Access Path for India

1. Facebook Business Manager account — verify business identity with GST certificate or MSME Udyam registration.
2. Dedicated business phone number (cannot be the same number used for personal WhatsApp).
3. Apply via a Meta-certified Business Solution Provider (BSP). On-premise API was deprecated October 2025; Cloud API via a BSP is the only enterprise option now.
4. WhatsApp Business account verification (Meta review, typically 2–7 business days).

### India Pricing (2026, per-message model effective July 1, 2025)

| Category | India Rate | Trigger |
|---|---|---|
| Marketing | ₹0.8631/message | Promotions, offers, re-engagement |
| Utility | ~₹0.115/message | Payment reminders, filing deadline alerts, document status |
| Authentication | ~₹0.115/message | OTPs, verification codes |
| Service | Free | Replies within 24-hour customer-initiated window |

Marketing rate increased ~10% on January 1, 2026 (from ₹0.7846). Utility and authentication rates held stable. Verify current rates against Meta's pricing page before implementation.

**Additional layers on top of Meta rates:**

- BSP platform subscription: ₹999–₹5,000/month depending on BSP.
- Per-message BSP markup: 10–30% above Meta rates.
- GST: 18% on both Meta charges and BSP fees.

**Cost modeling for SolveTax (Meta charges only, before BSP fees and GST):**

| Use case | Estimate |
|---|---|
| 5,000 clients × 1 utility message/month | ~₹575/month |
| 5,000 clients × 1 marketing message/month | ~₹4,316/month |
| 100,000 marketing messages | ~₹1,01,846 |

For a tax-services company sending primarily transactional messages (deadline alerts, payment confirmations, document receipts), utility pricing at ₹0.115/message is economically feasible and eliminates ban risk entirely. Marketing sends are economically significant; budget accordingly before enabling campaign features.

---

## 8. Data Protection — DPDP Act 2023 + Evolution API Storage

### What Evolution API Stores by Default

All flags below default to `true`:

| Env Var | Default | Stores |
|---|---|---|
| `DATABASE_SAVE_DATA_NEW_MESSAGE` | `true` | Full incoming/outgoing message content |
| `DATABASE_SAVE_MESSAGE_UPDATE` | `true` | Delivery/read-receipt status updates |
| `DATABASE_SAVE_DATA_CONTACTS` | `true` | Contact names and phone numbers |
| `DATABASE_SAVE_DATA_CHATS` | `true` | Chat metadata |
| `DATABASE_SAVE_DATA_HISTORIC` | `true` | Full message history |
| `DATABASE_SAVE_DATA_INSTANCE` | `true` | Session/instance metadata |
| `DATABASE_SAVE_IS_ON_WHATSAPP` | `true` | Number lookup results |
| `DATABASE_SAVE_IS_ON_WHATSAPP_DAYS` | `7` | Retention (days) for number lookup cache only |

Media files default to local filesystem; optionally moved to S3/MinIO via `S3_ENABLED=true`.

Cleanup env vars exist (`CLEAN_STORE_MESSAGES`, `CLEAN_STORE_CONTACTS`, `CLEAN_STORE_CHATS`, `CLEAN_STORE_CLEANING_INTERVAL`) but **there is no built-in retention-period enforcement** (e.g., "delete messages older than N days"). Operators must implement this at the database layer.

`DATABASE_DELETE_MESSAGE=true` performs a **soft/logical delete only** — records remain in the database. Physical deletion must be implemented separately.

### DPDP Act 2023 — What Applies to SolveTax

DPDP Rules 2025 were notified by MeitY on November 13–14, 2025. Phase 1 enforcement deadline: **May 13, 2027**. Penalties: up to ₹250 crore per violation.

| Requirement | What It Means for Evolution API Deployment |
|---|---|
| Explicit, purpose-specific consent before storing personal data | Generic "I agree to be contacted" is insufficient. Consent must name WhatsApp communication and each purpose (reminders, document status, etc.) separately. |
| Data minimization / purpose limitation | Storing full message content when only delivery confirmation is needed likely violates purpose limitation. Disable `DATABASE_SAVE_DATA_NEW_MESSAGE` unless there is a documented legal basis for retaining message content. |
| Phone number protection | Evolution API does not encrypt phone numbers at rest by default. Implement AES-256 encryption at the database or application layer. |
| Retention limits | DPDP-aligned guidance: transactional messages 7–30 days; customer service conversations 90–180 days. `DATABASE_SAVE_IS_ON_WHATSAPP_DAYS=7` covers only the number-lookup cache — it does not govern message retention. Implement database-level scheduled hard deletes. |
| Right to erasure (30-day window) | Soft deletes (`DATABASE_DELETE_MESSAGE=true`) do not satisfy erasure. Verify that soft-deleted records are physically purged within 30 days. |
| Access logging | DPDP compliance requires audit logs of access to personal data. Evolution API's default `LOG_LEVEL` logging does not provide access-level audit trails for stored chat data. Add this at the application or database layer. |
| Data Processing Agreement with Meta | As of early 2025, Meta has not published an India-specific DPA for DPDPA purposes. Monitor and verify. |

**Minimum required actions before any production client data flows through Evolution API:**

1. Set `DATABASE_SAVE_DATA_NEW_MESSAGE=false` unless message content retention has a documented legal basis.
2. Implement a scheduled Postgres job that hard-deletes rows older than the documented retention period from the messages, contacts, and chats tables.
3. Encrypt phone number columns at rest.
4. Build a deletion API endpoint that fulfills erasure requests end-to-end (including Evolution API's Postgres tables, not just the main SolvetaxAdmin DB).

---

## 9. Known Operational Pitfalls

### Session Drops and QR Loops

- **Trigger:** VPS / Azure Container connectivity loss for even 1–5 minutes produces `device_offline` errors.
- **Deeper trigger:** If the primary phone associated with the WhatsApp number remains offline/inactive for more than 14 days, WhatsApp automatically logs out all linked devices, including the Evolution API instance. Re-authentication via QR or pairing code is required.
- **Mitigation:** Health-check loop with automatic container restart (Azure Container Instance restart policy or an external monitor). Ensure the primary phone is used at least briefly every 14 days. Store session credentials in a persistent volume (not an ephemeral container filesystem).

### QR Loop on Pairing Code Login

- **Issue:** GitHub #2215 (open as of research date) — pairing code login connects successfully but receives no message events and no webhook callbacks; connection closes at status 401/device_removed.
- **Mitigation:** Use QR code login only until this issue is resolved.

### Memory Leaks

- **Issue:** Documented recurring memory leak in Evolution API's Baileys integration. 50–100 concurrent sessions in a single container causes "massive RAM bloat." CPU spikes during mass reconnection events.
- **Mitigation:** Minimum 4 GB RAM for any multi-instance production deployment. Schedule periodic container restarts (e.g., 03:00 daily) during low-traffic windows. Monitor memory via Azure Container metrics and alert at 80%.

### Webhook Duplicate Delivery

- **Issue:** GitHub #1325 (v2.2.3, March 2025) — the same event fires up to 10 times even when the destination server responds 200 OK. Root cause: retry logic fires regardless of confirmed delivery.
- **Mitigation:** Configure retry env vars (set on Evolution API container):
  ```
  WEBHOOK_RETRY_MAX_ATTEMPTS=3
  WEBHOOK_RETRY_INITIAL_DELAY_SECONDS=5
  WEBHOOK_RETRY_USE_EXPONENTIAL_BACKOFF=true
  WEBHOOK_RETRY_MAX_DELAY_SECONDS=60
  WEBHOOK_REQUEST_TIMEOUT_MS=30000
  ```
  **Webhook consumers in the SolvetaxAdmin backend MUST implement idempotency** keyed on the message ID from the event payload (`key.id` field in `MESSAGES_UPSERT`).

### Webhook Loop on Images in Groups

- **Issue:** GitHub #1746 (v2.3.0) — API enters an infinite loop firing the same webhook every 30 seconds for previously-received messages, particularly images in WhatsApp group/community contexts. Closed without a documented fix.
- **Mitigation:** SolveTax should not add the business number to WhatsApp groups. If group use is required, monitor webhook handler logs for repeated identical `key.id` values and implement a server-side dedup cache (Redis `SET NX EX 300`).

### Redis False-Duplicate Suppression

- **Issue:** GitHub #2110 (v2.3.5, October 2025) — Redis cache prematurely marks incoming message IDs as "already processed," causing legitimate `messages.upsert` events to be silently dropped with log line `"Duplicated ignored: [MESSAGE_ID]"`.
- **Mitigation:** If messages are silently disappearing, disable the Redis message-ID cache (`REDIS_ENABLED=false` or verify which cache flag controls this — verify against current docs). Note: disabling removes actual duplicate protection, making the idempotency logic in the webhook consumer even more important.

### Webhook Events Self-Disabling

- **Issue:** GitHub #1559 — per-instance webhook event toggles have been reported to turn themselves off without manual intervention, silently stopping webhook delivery for specific event types.
- **Mitigation:** Add a periodic health-check job that calls `GET /webhook/find/{instance}` and verifies the expected events array. Alert if any required event type is missing and re-set via `POST /webhook/set/{instance}`.

### No Built-In Rate Limiting or Message Queue

- **Issue:** GitHub #2538 (closed as "not planned") — Evolution API routes send operations directly to the instance without any centralized rate limiter or job queue.
- **Mitigation:** The SolvetaxAdmin backend must implement an external queue (BullMQ over the existing Redis instance, or a simple asyncio queue) with configurable throughput (target: 1 message per 20–30 seconds per instance during warm-up, up to 1 per 15 seconds for mature accounts). Never call `POST /message/sendText/{instance}` in a tight loop from the backend.

### Version Upgrade Breakage

| Version | Breaking Change | Action |
|---|---|---|
| v2.0.0 | MongoDB dropped; requires Postgres/MySQL via Prisma. JWT auth removed; API key only. All payloads changed snake_case → camelCase. `owner` field renamed `instanceId` in webhook payloads. | Full migration required from v1.x. |
| v2.1.0 | Webhook event payloads changed for create-instance and set-events operations. | Update webhook consumers. |
| v2.3.1 | `CONFIG_SESSION_PHONE_VERSION` env var removed. Previously caused QR failures when pinned version went stale (common on Coolify deployments). | Remove this env var on upgrade. |
| v2.4.0-rc (not yet stable) | Mandatory license activation against Evolution Foundation licensing server before the API serves any traffic. Unauthenticated deployments return HTTP 503. Headless activation via `EVOLUTION_OPERATOR_EMAIL` env var calls `/v1/register/auto` at boot (email must be pre-registered). GitHub #2534 documents breakage in CI/CD pipelines. | Do not upgrade to v2.4.0 until it is tagged stable and the licensing behavior is confirmed. Pin `evoapicloud/evolution-api:2.3.7` in production. |

### Supply Chain Risk

April 2026: the npm package `lotusbail` (marketed as an "anti-ban" Baileys fork, ~56,000 downloads) was confirmed to be exfiltrating session credentials and stealing WhatsApp messages. **Do not use any Baileys fork other than the one vendored by Evolution API itself.** Audit `package-lock.json` / `yarn.lock` inside the Evolution API container image after every upgrade.

---

## 10. License and ToS Summary

| Aspect | Position |
|---|---|
| Evolution API software license | Apache 2.0 with two additions: (1) cannot remove Evolution API logo/copyright from the Manager UI frontend; (2) must display a clear notification within any system using Evolution API that "Evolution API is being utilized," visible to system admins. Not applicable if running API-only without the Manager UI — confirm usage intent. |
| WhatsApp / Meta ToS | Clear violation on all four applicable prohibitions. Not a gray area. |
| Meta enforcement | Progressive restrictions (1/3/5/7/30-day messaging caps) → permanent termination. No guaranteed appeal path. Enforcement has become more automated since 2025. |
| TRAI TCCCPR (India, Feb 2025 amendment) | DLT registration required for bulk WhatsApp messaging by Indian businesses. |
| DPDP Act 2023 | Phase 1 enforcement deadline May 2027. Explicit per-purpose consent, data minimization, retention limits, right to erasure within 30 days, access audit logs required. |

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
