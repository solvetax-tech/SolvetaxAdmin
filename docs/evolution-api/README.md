# Evolution API Integration Docs

**Status:** Planning docs only — no code written yet.
**Research date:** 2026-07-23
**Scope:** Self-hosted WhatsApp gateway adding WhatsApp as a new client-communications channel to SolvetaxAdmin (the codebase currently has no outbound client messaging capability).

---

## Document Index

| # | File | Title / Purpose |
|---|------|-----------------|
| 01 | [01-overview.md](./01-overview.md) | **What It Is and Why We Care** — Explains what Evolution API is (open-source REST gateway over WhatsApp/Baileys), its feature set (REST, webhooks, built-in UI, bot integrations), and why it is being evaluated as a Twilio alternative for SolveTax. |
| 02 | [02-deployment.md](./02-deployment.md) | **Self-Hosting Evolution API for SolveTax** — Docker image pinning, Compose configuration, environment variables, PostgreSQL/Redis wiring, Azure VM sizing, TLS setup, and first-run checklist. |
| 03 | [03-api-reference.md](./03-api-reference.md) | **Feature Reference** — Endpoint catalog for instance management, messaging (text, media, templates), contact/group operations, and authentication scopes. Based on v2.3.7 stable; v2.4.0-rc2 differences noted. |
| 04 | [04-events-webhooks.md](./04-events-webhooks.md) | **Events, Webhooks, and Real-Time Transports** — Full event catalog, JSON payload reference, HTTP webhook wiring, alternative transports (WebSocket, RabbitMQ, Kafka, SQS, NATS, Pusher), delivery semantics, and transport recommendation for SolveTax. |
| 05 | [05-integrations.md](./05-integrations.md) | **Built-in Integrations** — Covers Chatwoot, Typebot, OpenAI, Dify, Flowise, n8n, EvoAI, and S3/MinIO media storage: what each does, minimal setup, and a go/no-go verdict for SolveTax. |
| 06 | [06-solvetax-integration-architecture.md](./06-solvetax-integration-architecture.md) | **Integration Architecture for SolvetaxAdmin** — How Evolution API wires into the existing FastAPI + Postgres + Redis stack: service boundaries, webhook receiver, message dispatch flow, CRM event hooks, and data model notes. All references to current codebase modules; no code prescribed. |
| 07 | [07-risks-compliance.md](./07-risks-compliance.md) | **Risks, Bans, and Compliance** — Honest assessment of Baileys-mode ban risk in production, consent obligations, DPDP Act 2023 requirements for an Indian business, official WhatsApp Cloud API as the compliant fallback, and operational pitfalls with mitigations. |
| 08 | [08-rollout-plan.md](./08-rollout-plan.md) | **Phased Rollout Plan** — Illustrative phases from sandbox standup through production cutover; each phase gates on a `/plan-eng-review` before build. Timelines adjust to team capacity and ban-risk appetite. |
| 09 | [09-node-workflow-builder.md](./09-node-workflow-builder.md) | **Node-Based WhatsApp Workflow Builder** — Visual flow composer for staff: requirement analysis, two flow shapes (sequence vs. conversation), data model, backend execution engine, UI component design, and integration points with the existing CRM and webhook pipeline. |

---

## How to Use These Docs

1. Start with **01-overview** for context and the decision to evaluate Evolution API.
2. Read **07-risks-compliance** early — the ban-risk and DPDP obligations are decision-gating.
3. Use **02-deployment** and **03-api-reference** as implementation references when a build phase is approved.
4. **06-solvetax-integration-architecture** is the primary handoff document from planning to engineering.
5. **08-rollout-plan** drives sprint planning; each phase must pass eng review before work begins.
6. **09-node-workflow-builder** is the design reference for the visual flow composer; read after 06 and 08.

No document in this folder prescribes code changes or migration steps. All build work requires a separate `/plan-eng-review` pass.
