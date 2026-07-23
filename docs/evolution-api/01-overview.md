# Evolution API: What It Is and Why We Care

## What Is Evolution API

Evolution API is a production-ready, open-source REST API gateway that exposes WhatsApp messaging over HTTP. A single self-hosted container accepts standard REST calls and translates them into WhatsApp protocol operations — send messages, receive incoming events via webhook, manage contacts and groups, stream media to S3. It also ships a built-in web management UI (Evolution Manager) and native integrations for chatbot platforms (Typebot, Chatwoot, OpenAI, Dify, n8n, Flowise).

The project originated as a fork of CodeChat (which first integrated the Baileys library) and has grown into a multi-channel gateway supporting both the unofficial Baileys WebSocket protocol and Meta's official WhatsApp Cloud/Business API.

## Project Status and Maintainer

| Field | Value |
|---|---|
| Canonical repo | `github.com/evolution-foundation/evolution-api` |
| Organization | Evolution Foundation (`evolutionfoundation.com.br`) |
| Contact | suporte@evofoundation.com.br |
| GitHub stars / forks | 9,029 stars / 6,935 forks (July 2026) |
| Open issues / PRs | 105 issues / 45 PRs |
| Latest stable | **v2.3.7** (December 5, 2024) |
| Active RC | **v2.4.0-rc2** (May 17, 2026) |

> **Note on org naming:** The GitHub organization was renamed from `EvolutionAPI` to `evolution-foundation` during a 2025–2026 rebrand. GitHub maintains redirects, so `github.com/EvolutionAPI/evolution-api` still resolves correctly.

### Version History (abbreviated)

| Version | Date | Notable change |
|---|---|---|
| v2.0.0-beta | July 2024 | Foundation rebuild: MongoDB removed, Prisma + PostgreSQL |
| v2.1.0 | August 2024 | Evolution Bot, Flowise, Dify integrations |
| v2.2.0–v2.2.3 | Oct 2024–Feb 2025 | Fake calls, list/button sending, Pusher support |
| v2.3.0 | June 2024 | Kafka, NATS, EvoAI, n8n chatbot |
| v2.3.4 | September 2024 | Evolution Manager v2 open-sourced |
| v2.3.7 | December 5, 2024 | Current latest stable |
| 2.4.0-rc1 | May 6, 2026 | Mandatory license-server activation introduced |
| 2.4.0-rc2 | May 17, 2026 | Stabilization, LID bypass fix, native GIF |

### v2.4.0-rc: Mandatory License Activation

Starting with v2.4.0-rc1, every instance must register with the Evolution Foundation licensing server before serving API traffic. Until activation, all business endpoints return `HTTP 503` with error code `LICENSE_REQUIRED`. Health checks and `/manager` remain accessible.

Three activation methods:
1. Pre-existing API key set via environment variable.
2. Browser-based registration through the `/manager` UI.
3. Headless activation via `EVOLUTION_OPERATOR_EMAIL` env var.

The community tier is free — unlimited instances, unlimited messages, no feature gates. Evolution Foundation collects only instance UUID, version, aggregated usage metrics, and server IP for geolocation. No messages, contacts, or auth tokens are collected. (Community concerns about automated/Kubernetes deployments are tracked in issue #2534.)

## License

Apache License 2.0. Commercial use, modification, and redistribution are permitted. The names "Evolution Foundation," "Evolution," and "Evolution API" and associated logos are registered trademarks — forks and derivatives lose the right to use these brand assets. The `NOTICE` file must be preserved in distributions per Apache 2.0 requirements.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Evolution API  (Node.js 20 / TypeScript 5)         │
│  Express HTTP  :8080                                │
│                                                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ Baileys  │  │ WhatsApp     │  │ Evolution     │ │
│  │ channel  │  │ Business API │  │ channel       │ │
│  └──────────┘  └──────────────┘  └───────────────┘ │
│                                                     │
│  Prisma ORM ──► PostgreSQL (or MySQL)               │
│  Redis cache   S3 / MinIO media   Socket.IO         │
└─────────────────────────────────────────────────────┘
```

| Layer | Technology |
|---|---|
| Runtime | Node.js 20+ |
| Language | TypeScript 5+ (98.7% of codebase) |
| HTTP framework | Express.js, default port 8080 |
| ORM | Prisma (schema selected by `DATABASE_PROVIDER`) |
| Primary database | PostgreSQL (`evolution_api` schema namespace) |
| Alternate database | MySQL |
| Cache | Redis (preferred) or node-cache in-memory fallback |
| Media storage | S3-compatible (AWS S3 or MinIO) |
| Message queues | RabbitMQ, Apache Kafka, Amazon SQS, NATS, Pusher |
| Real-time events | Socket.IO (WebSocket) |

Database migrations run automatically at startup via `npm run db:deploy`. The Docker image uses a two-stage build: TypeScript + Prisma client generation in the builder stage, runtime-only dependencies in production.

## Connection Channels: Baileys vs Official WhatsApp Business API

Evolution API supports two primary channels. The choice is made per-instance at creation time via the `integration` field.

### Baileys (`integration: "WHATSAPP-BAILEYS"`)

Baileys is an open-source library that reverse-engineers the WhatsApp Web WebSocket protocol. No Meta approval required; connect by scanning a QR code or entering an 8-digit pairing code.

### WhatsApp Business API (`integration: "WHATSAPP-BUSINESS"`)

Uses Meta's official Graph API (`https://graph.facebook.com`, version `v20.0` by default). Requires a verified Meta Business account, an approved WhatsApp Business Account (WABA), and message template approval for outbound-initiated messages.

### Tradeoff Table

| Dimension | Baileys | WhatsApp Business API |
|---|---|---|
| **ToS compliance** | Violates WhatsApp ToS | Fully compliant |
| **Ban risk** | High — Meta's detection operates at protocol level; volume reduction alone does not eliminate risk | None when used correctly |
| **Indian business context** | 68% of users report at least one number ban within 12 months (verify against current data) | No ban risk |
| **Setup time** | Minutes — scan QR code | Days to weeks — Meta business verification + WABA approval + template review |
| **Message types** | Full: text, media, interactive buttons/lists, polls, reactions, audio, location, contacts, voice call simulation | Template messages, interactive components; limited to approved templates for outbound |
| **Inbound (customer-initiated)** | All message types | Free 24-hour service window; full message type support |
| **Pricing** | Free (self-hosted infra cost only) | Per-conversation: ~₹0.8631 marketing, ~₹0.115 utility/authentication, ₹0 for customer-initiated service replies (India 2026 rates — verify against current Meta pricing) |
| **DPDP Act compliance** | Evolution API stores messages in PostgreSQL by default; you own all data — must implement consent, retention limits, right-to-erasure | Meta handles message delivery data; your side still owns contact records and must comply |
| **Uptime / stability** | Depends on WhatsApp Web protocol stability; breaking changes possible without notice | SLA-backed Meta service |
| **Group messaging** | Full group management | Not supported via Cloud API |
| **Broadcast / status** | Supported | Not supported |
| **Cost at scale** | Infrastructure only | Scales linearly with volume |
| **Best for** | Internal bots, low-volume prototypes, tooling where ban risk is acceptable | Production customer service, regulated industries, high-volume outbound |

> **Risk callout for SolveTax:** Tax-services firms handling client financial data fall under DPDP Act obligations (Rules notified November 2025, enforcement deadline May 2027). Baileys-based connections also expose client phone numbers to ban risk, which would disrupt live engagement threads during ITR season. The official WhatsApp Business API via a Meta-certified BSP is the only ToS-compliant path for production use.

### Third Channel: Evolution (`integration: "EVOLUTION"`)

A custom internal protocol for inter-service communication within the Evolution Foundation ecosystem (e.g., Evo CRM). Not relevant for SolveTax's external client messaging use case.

## Evolution Manager UI

The embedded management UI is served at `/manager` by the Express server (static middleware). It cannot be accessed externally without exposing the Evolution API port.

| Property | Value |
|---|---|
| URL path | `/manager` |
| Tech stack | React + Vite (built assets in `manager/dist/`) |
| Source | `evolution-manager-v2` Git submodule; open-sourced in v2.3.4 |
| Disable | Set `SERVER_DISABLE_MANAGER=true` |
| Languages | English, Portuguese, Spanish, French |

**Capabilities:**
- Create, connect (QR code display), and delete instances (typed-name confirmation modal).
- Configure integrations per instance: webhooks, Chatwoot, Typebot, RabbitMQ, WebSocket, OpenAI, Dify, n8n.
- Monitor connection status in real time.
- Manage chatbot sessions: filter by name/number/status/time, bulk-status-change, pagination.
- Send messages from within session views.

A standalone legacy UI also exists (`github.com/evolution-foundation/evolution-manager`, Vue.js v3 + Vuetify), deployable separately via Docker image `atendai/evolution-manager`. The embedded v2 Manager is the recommended option for new deployments.

## How Instances Map to WhatsApp Numbers

Each **instance** is an isolated WhatsApp connection corresponding to exactly one phone number. The `WAMonitoringService` singleton manages all instances as a multi-tenant store.

Per-instance resources:
- Dedicated database record (all related tables key on `instanceId`).
- Isolated Redis cache keys (prefixed with instance name).
- Independent webhook URL and event subscription list.
- Independent integration configuration (Typebot, Chatwoot, OpenAI, etc.).
- Separate authentication state stored on filesystem, Redis, or database.

**Deployment modes:**

| Mode | `DEFAULT_MODE` | Scaling model |
|---|---|---|
| Server | `server` | Single container hosts all instances — vertical scaling |
| Container | `container` | One instance per container — horizontal scaling |

For SolveTax, server mode with a single container is the natural starting point (one primary number for client comms). Container mode becomes relevant only if separate numbers per team or per-service-line are needed.

## How This Fits SolveTax

SolveTax currently uses Twilio for client messaging. The planned Evolution API integration would replace or supplement Twilio for WhatsApp-specific flows:

- **Reminders:** Automated ITR deadline, GST filing, and document submission reminders sent from the FastAPI backend to client WhatsApp numbers.
- **Document collection:** Two-way media exchange — clients reply with photos of PAN cards, Form 16, bank statements; Evolution API webhooks deliver them to the FastAPI inbound handler.
- **Two-way CRM chat:** Incoming client messages routed into the CRM (currently in SolvetaxAdmin) as conversation threads; staff reply from within the admin UI via the Evolution API send-message endpoint.
- **Campaigns:** Bulk outreach for new-service announcements or seasonal filing prompts.

The Baileys channel can be stood up immediately with zero Meta approval lag, making it viable for internal testing and low-volume pilot flows. For production client communications — particularly anything touching financial data or regulated consent obligations under DPDP — the official WhatsApp Business API channel is the correct long-term target. These two states can coexist as separate instances within a single Evolution API deployment, allowing a phased migration from Baileys pilot to official API production without re-architecting the integration layer.

---

## Sources

- https://github.com/evolution-foundation/evolution-api
- https://github.com/evolution-foundation/evolution-api/releases
- https://github.com/EvolutionAPI/evolution-api/blob/main/.env.example
- https://github.com/EvolutionAPI/evolution-api/blob/main/CHANGELOG.md
- https://deepwiki.com/EvolutionAPI/evolution-api
- https://deepwiki.com/EvolutionAPI/evolution-api/1.3-configuration
- https://deepwiki.com/EvolutionAPI/evolution-api/3-whatsapp-integration
- https://docs.evolutionfoundation.com.br/
- https://docs.evolutionfoundation.com.br/en/evolution-api
- https://docs.evolutionfoundation.com.br/licensing
- https://github.com/evolution-foundation/evolution-api/issues/2534
- https://github.com/evolution-foundation/evolution-manager
- https://github.com/evolution-foundation/evolution-api-lite
- https://github.com/evolution-foundation/evolution-go
- https://github.com/evolution-foundation
- https://github.com/EvolutionAPI/evolution-client-python
- https://pypi.org/project/evolutionapi/
- https://www.postman.com/agenciadgcode/evolution-api/overview
- https://www.postman.com/agenciadgcode/evolution-api/collection/jn0bbzv/evolution-api-v2-2-2
- https://gurusup.com/blog/evolution-api-whatsapp
- https://newreleases.io/project/github/evolution-foundation/evolution-api/release/2.3.7
- https://hub.docker.com/r/evoapicloud/evolution-api
