# Evolution API v2 — Built-in Integrations

Covers: Chatwoot, Typebot, OpenAI, Dify, Flowise, n8n, EvoAI, and S3/MinIO media storage.
Each section states what the integration does, the minimal setup required, and a verdict on whether SolveTax should use it.

---

## Shared Architecture

All chatbot integrations (Typebot, OpenAI, Dify, Flowise, n8n, EvoAI) share a common DTO layer and session model.

### Common Bot DTO Fields (`BaseChatbotDto`)

| Field | Type | Notes |
|---|---|---|
| `enabled` | `boolean` | |
| `description` | `string` | Required |
| `triggerType` | `"all" \| "keyword" \| "none"` | Required |
| `triggerOperator` | `"contains" \| "equals" \| "startsWith" \| "endsWith" \| "regex" \| "none"` | |
| `triggerValue` | `string` | |
| `expire` | `number` | Minutes of inactivity before session dies; 0 = no expiry |
| `keywordFinish` | `string` | Keyword that closes the session |
| `delayMessage` | `number` | Milliseconds to wait before sending reply |
| `unknownMessage` | `string` | Fallback text when bot has no answer |
| `listeningFromMe` | `boolean` | Also trigger on messages sent from this number |
| `stopBotFromMe` | `boolean` | Sending from this number pauses the bot |
| `keepOpen` | `boolean` | On expiry, close vs delete session |
| `debounceTime` | `number` | Seconds to group rapid messages before forwarding |
| `ignoreJids` | `string[]` | JIDs excluded from bot handling |
| `splitMessages` | `boolean` | Split long responses into multiple messages |
| `timePerChar` | `number` | Typing delay per character (ms) |

### Common Endpoints

All integrations mount the same route shape at `/{integration}/{instance}`:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/create` | Create bot config |
| `GET` | `/find` | List all configs |
| `GET` | `/fetch/:botId` | Get one config |
| `PUT` | `/update/:botId` | Update config |
| `DELETE` | `/delete/:botId` | Delete config |
| `POST` | `/settings` | Set instance-wide defaults and fallback |
| `GET` | `/fetchSettings` | Get current settings |
| `POST` | `/changeStatus` | `{ remoteJid, status: "opened"\|"paused"\|"closed" }` |
| `GET` | `/fetchSessions/:botId` | List active sessions |
| `POST` | `/ignoreJid` | Add/remove JID exclusions |

### Session Model (`IntegrationSession`)

Fields: `id`, `botId`, `remoteJid`, `sessionId`, `status` (`opened | paused | closed`), `awaitUser` (boolean), `context` (JSON).

---

## 1. Chatwoot

### What It Does

Creates a two-way sync between WhatsApp (via Evolution API) and a Chatwoot support inbox. Every inbound WhatsApp message appears as a Chatwoot conversation; agents reply from Chatwoot and the reply is sent back to the WhatsApp contact in real time.

**WhatsApp → Chatwoot flow:**
1. Evolution API receives a WhatsApp message event from Baileys.
2. It looks up or creates a Chatwoot contact by phone number.
3. A distributed lock (TTL 30 s, poll 300 ms) prevents duplicate conversations on concurrent messages.
4. A conversation is created or reopened (depending on `reopenConversation`).
5. Media is downloaded and forwarded as Chatwoot attachments.
6. Message IDs (`chatwootMessageId`, `chatwootConversationId`, `chatwootContactInboxSourceId`) are stored on the Evolution message record.

**Chatwoot → WhatsApp flow:**
1. Chatwoot fires a `message_created` webhook to the Evolution API instance URL.
2. Evolution API extracts the WhatsApp JID from the Chatwoot contact and sends the reply via Baileys.
3. If `signMsg: true`, the agent name is appended: `"{message}{signDelimiter}*{agentName}*"` (default delimiter: newline).

### Setup

**Option A — during instance creation** (`POST /instance/create`):

```json
{
  "instanceName": "solvetax-main",
  "chatwootAccountId": "1",
  "chatwootToken": "<admin-api-token>",
  "chatwootUrl": "https://chatwoot.yourdomain.com",
  "chatwootNameInbox": "WhatsApp Support",
  "chatwootConversationPending": true,
  "chatwootReopenConversation": false,
  "chatwootSignMsg": true,
  "chatwootImportContacts": false,
  "chatwootImportMessages": false
}
```

**Option B — on an existing instance** (`POST /chatwoot/set/{instance}`):

| Field | Type | Notes |
|---|---|---|
| `enabled` | `boolean` | |
| `accountId` | `string` | Chatwoot account ID |
| `token` | `string` | Chatwoot admin API token |
| `url` | `string` | Chatwoot base URL, no trailing slash |
| `nameInbox` | `string` | Inbox name; defaults to instance name |
| `signMsg` | `boolean` | Append agent name to outbound messages |
| `signDelimiter` | `string` | Default `"\n"` |
| `number` | `string` | WhatsApp number for this instance |
| `reopenConversation` | `boolean` | Reopen resolved convos vs create new |
| `conversationPending` | `boolean` | New convos start as `pending` |
| `autoCreate` | `boolean` | Auto-create inbox and register webhook in Chatwoot |
| `importContacts` | `boolean` | Bulk import WhatsApp contacts (batch: 3,000) |
| `importMessages` | `boolean` | Import message history (requires DB URI below) |
| `daysLimitImportMessages` | `number` | Days of history to import |
| `mergeBrazilContacts` | `boolean` | Merge Brazilian +55 number variants (not relevant for India) |
| `ignoreJids` | `string[]` | JIDs to exclude from syncing |
| `organization` | `string` | |
| `logo` | `string` | URL for contact avatar |

Inbox type created is `api` channel (not the native Meta WhatsApp Business channel type).

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CHATWOOT_ENABLED` | `false` | Enable integration |
| `CHATWOOT_MESSAGE_READ` | `true` | Mark client message as read on WhatsApp when agent replies |
| `CHATWOOT_MESSAGE_DELETE` | `true` | Delete for everyone on WhatsApp when deleted in Chatwoot |
| `CHATWOOT_BOT_CONTACT` | `true` | Create bot contact in Chatwoot for QR/status events |
| `CHATWOOT_IMPORT_DATABASE_CONNECTION_URI` | — | PostgreSQL URI to Chatwoot's DB (required for `importMessages`) |
| `CHATWOOT_IMPORT_PLACEHOLDER_MEDIA_MESSAGE` | `true` | Use placeholder text for media during history import |

### Useful for SolveTax?

**Yes — as an interim support inbox.** SolveTax has a custom CRM UI but no built-in human-agent inbox. Chatwoot fills that gap immediately: the support team gets a multi-agent, browser-based inbox for WhatsApp conversations without any custom build. Specific use cases:

- Pre-sales or onboarding queries before a lead is converted in the CRM.
- Escalations that need a human agent to take over from an automated flow.
- Audit queries from clients during filing season where response time matters.

Once SolveTax builds a native inbox inside their FastAPI/React CRM, this can be disabled. The `autoCreate: true` flag means zero manual Chatwoot configuration. Set `conversationPending: true` so new WhatsApp messages don't go unnoticed by agents.

**What to skip:** `importMessages` (requires pointing Evolution at Chatwoot's live Postgres DB — operational risk), `mergeBrazilContacts` (irrelevant for Indian numbers).

---

## 2. Typebot

### What It Does

Triggers a Typebot conversational flow from a WhatsApp message. Supports multi-turn conversations with session persistence, keyword/universal/none trigger modes, variable injection, and configurable session expiry. Each Evolution API instance can run multiple Typebot bots with different triggers.

### Endpoints (`/typebot/{instance}`)

Standard CRUD + settings + `changeStatus` + `ignoreJid`, plus:

`POST /typebot/start/{instance}` — manually start a session for a specific contact:

```json
{
  "url": "https://typebot.yourdomain.com",
  "typebot": "my-bot-public-id",
  "remoteJid": "919999999999@s.whatsapp.net",
  "startSession": true,
  "variables": [
    { "name": "clientName", "value": "Ravi Kumar" },
    { "name": "pan", "value": "ABCDE1234F" }
  ]
}
```

### DTO Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | `string` | Yes | Typebot API base URL, no trailing slash |
| `typebot` | `string` | Yes | Typebot public ID |
| `typebotIdFallback` | `string` | No | Fallback bot ID if no trigger matches (in settings DTO) |

Plus all `BaseChatbotDto` fields.

### Predefined Variables Auto-Injected

`remoteJid`, `pushName`, `instanceName`, `serverUrl`, `apiKey`, `ownerJid`. Custom variables passed via `/start` are merged with these (custom values win on conflict).

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TYPEBOT_ENABLED` | `false` | Enable integration |
| `TYPEBOT_API_VERSION` | `old` | `old` or `latest` — changes API endpoint shape; verify against current `.env.example` |
| `TYPEBOT_SEND_MEDIA_BASE64` | `false` | Send media files as base64 to Typebot instead of URL |

**`TYPEBOT_API_VERSION` impact:**
- `latest`: start → `POST {url}/api/v1/typebots/{typebot}/startChat`; continue → `POST {url}/api/v1/sessions/{sessionId}/continueChat`.
- `old`: both start and continue → `POST {url}/api/v1/sendMessage` with different body shape.

### Session Lifecycle

- Created on trigger match; `sessionId` stored with random prefix for uniqueness.
- `expire` (minutes): compared against `session.updatedAt`. On expiry with `keepOpen: false`, session is deleted and a new one starts on next message. With `keepOpen: true`, session transitions to `closed`.
- `debounceTime`: groups rapid messages into one before forwarding.

### Useful for SolveTax?

**Low priority given existing FastAPI backend.** Typebot is a no-code flow builder — useful for teams without backend engineers. SolveTax already has a FastAPI backend that can implement the same logic with full control over data, routing, and error handling.

One exception worth considering: onboarding intake flows (collect PAN, filing type, last-year return status) could be prototyped in Typebot quickly and later replaced with a FastAPI webhook handler. Use the `/start` endpoint with pre-filled variables to hand off context collected in the CRM.

If the team does evaluate Typebot, set `TYPEBOT_API_VERSION=latest` and confirm against the current `.env.example` — the `old` default is from an older API version.

---

## 3. OpenAI

### What It Does

Two functions: (1) runs AI assistant or chat-completion bots on WhatsApp conversations; (2) provides global Whisper-1 speech-to-text transcription of voice notes, available to all integrations (not just OpenAI bots).

### Endpoints (`/openai/{instance}`)

Standard CRUD + settings + `changeStatus` + `ignoreJid`, plus:

`POST /openai/creds/{instance}` — register an API key:
```json
{ "name": "solvetax-key", "apiKey": "sk-..." }
```

### Bot DTO Fields

| Field | Type | Notes |
|---|---|---|
| `openaiCredsId` | `string` | Required; references a registered credential |
| `botType` | `"assistant" \| "chatCompletion"` | Required |
| `assistantId` | `string` | OpenAI Assistant ID (assistant mode only) |
| `functionUrl` | `string` | Webhook called when assistant requires a tool action |
| `model` | `string` | e.g. `gpt-4o` (chatCompletion mode) |
| `systemMessages` | `string[]` | System prompts |
| `assistantMessages` | `string[]` | Pre-seeded assistant messages |
| `userMessages` | `string[]` | Pre-seeded user messages |
| `maxTokens` | `number` | Max response tokens |

### Bot Modes

**`assistant` mode:** Creates and reuses an OpenAI Thread per conversation. Supports tool calls via `requires_action`; Evolution API calls `functionUrl` with tool arguments and submits results back. Stateful across sessions.

**`chatCompletion` mode:** Maintains conversation history in `session.context` (last 10 messages). Assembles: system messages + predefined messages + history + current message. Simpler; no persistent thread on OpenAI side.

### Speech-to-Text (Whisper-1)

Enable via `POST /openai/settings/{instance}` with `speechToText: true`.

- Triggered when incoming message content begins with `"audioMessage|"`.
- Downloads audio from `mediaUrl` (HTTP), `base64` decode, or Baileys direct download (in that priority).
- Calls `https://api.openai.com/v1/audio/transcriptions` with `model: whisper-1`, multipart form.
- Language: defaults to `"pt"` (Portuguese) if app language contains "pt"; otherwise uses configured app language. Set `LANGUAGE=en` (or `LANGUAGE=hi` for Hindi) in the Evolution API container environment; this controls the Whisper transcription language. See 02-deployment.md Section 3 (Instance management) for the full env var reference.
- Transcribed text replaces the audio marker and flows into subsequent bot logic.
- In webhook events, the transcription appears in a `speechToText` field.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_ENABLED` | `false` | Enable integration |
| `OPENAI_API_KEY_GLOBAL` | — | Optional global key; per-instance credentials take precedence |

### Useful for SolveTax?

**Speech-to-text: yes, useful.** Indian clients frequently send WhatsApp voice notes. Enabling Whisper-1 transcription means voice notes arrive as text in webhook payloads — the FastAPI backend can process them the same as text messages, log them in the CRM, and route them appropriately without building a separate audio pipeline.

**OpenAI bot integration: evaluate carefully.** An AI assistant handling tax queries unsupervised is a compliance and accuracy risk. A more defensible use pattern: use `chatCompletion` mode for a triage bot that classifies the query type (GST / ITR / new registration / general) and hands off to a human agent via Chatwoot rather than attempting to answer. The `functionUrl` tool-call mechanism in `assistant` mode could call back into the FastAPI backend to fetch client-specific data, which is useful for an authenticated "check my filing status" flow — but requires careful security design (verify the caller is Evolution API).

---

## 4. Dify

### What It Does

Routes WhatsApp conversations to Dify AI platform flows. Supports four modes: `chatBot`, `textGenerator`, `agent`, `workflow` (workflow not yet implemented as of research date — verify against current source). Maintains a `conversationId` for stateful multi-turn sessions. Passes full message context including images and transcribed audio.

### Endpoints (`/dify/{instance}`)

Standard CRUD + settings + `changeStatus` + `fetchSessions` + `ignoreJid`.

### DTO Fields

| Field | Type | Notes |
|---|---|---|
| `botType` | `"chatBot" \| "textGenerator" \| "agent" \| "workflow"` | `workflow` not yet implemented; verify |
| `apiUrl` | `string` | Dify API base URL, no trailing slash |
| `apiKey` | `string` | Dify API key |
| `difyIdFallback` | `string` | Fallback bot ID (in settings DTO) |

### Payload to Dify

```json
{
  "inputs": {
    "remoteJid": "919999999999@s.whatsapp.net",
    "pushName": "Ravi Kumar",
    "instanceName": "solvetax-main",
    "serverUrl": "https://evo.yourdomain.com",
    "apiKey": "<instance-api-key>"
  },
  "query": "<message content>",
  "response_mode": "blocking",
  "conversation_id": "<stored ID or undefined for new>",
  "user": "<remoteJid>"
}
```

`response_mode` is `streaming` for `agent` type, `blocking` for others. Audio via Whisper transcription is prepended with `"[audio]"` in `query`.

### Useful for SolveTax?

**Skip for now.** Dify is a solid platform but adds another self-hosted service to manage alongside Evolution API, Postgres, Redis, and the existing Azure stack. The capability overlap with a direct FastAPI webhook handler or an OpenAI assistant is significant. Revisit if the team wants a visual LLM workflow builder without coding.

---

## 5. Flowise

### What It Does

Sends triggered WhatsApp messages to a Flowise LangChain flow via HTTP POST. Evolution API manages sessions and trigger logic; Flowise handles the LLM chain. The response from Flowise is sent back to the WhatsApp contact.

### Endpoints (`/flowise/{instance}`)

Standard CRUD + settings + `changeStatus` + `fetchSessions` + `ignoreJid`.

### DTO Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `apiUrl` | `string` | Yes | Full Flowise endpoint including flow ID path |
| `apiKey` | `string` | No | Flowise auth key |
| `flowiseIdFallback` | `string` | No | Fallback bot ID (in settings DTO) |

Payload sent to Flowise includes `query` (message content) and the standard context variables (`remoteJid`, `pushName`, `instanceName`, `serverUrl`, `apiKey`). Additional fields were added in v2.3.3 — verify against current source.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOWISE_ENABLED` | `false` | Enable integration |

### Useful for SolveTax?

**Skip.** Same reasoning as Dify: another service to host and maintain. Flowise is useful for teams prototyping LLM pipelines visually; SolveTax has engineers who can write the equivalent in Python. The FastAPI backend plus direct OpenAI SDK calls achieves the same outcome with fewer moving parts.

---

## 6. n8n

### What It Does

A built-in bot integration (added v2.3.x) that manages sessions and trigger logic inside Evolution API, then POSTs a structured payload to an n8n webhook URL. Distinct from passive webhook forwarding: Evolution API sends a message, waits for n8n's response, and sends that response back to the WhatsApp contact.

### Endpoints (`/n8n/{instance}`)

Standard CRUD + settings + `changeStatus` + `fetchSessions` + `ignoreJid`.

### DTO Fields

| Field | Type | Notes |
|---|---|---|
| `webhookUrl` | `string` | n8n webhook URL to POST to |
| `basicAuthUser` | `string` | HTTP Basic Auth username |
| `basicAuthPass` | `string` | HTTP Basic Auth password |

### Payload Sent to n8n

```json
{
  "chatInput": "<message text or Whisper transcription>",
  "sessionId": "<session identifier>",
  "remoteJid": "919999999999@s.whatsapp.net",
  "pushName": "Ravi Kumar",
  "keyId": "<WhatsApp message key ID>",
  "fromMe": false,
  "quotedMessage": "<quoted content if any>",
  "instanceName": "solvetax-main",
  "serverUrl": "https://evo.yourdomain.com",
  "apiKey": "<instance api key>"
}
```

`keyId` added in v2.3.1. `quotedMessage` added in v2.3.7. Audio is Whisper-transcribed (if configured) before being placed in `chatInput`, prepended with `"[audio]"`.

### Response Handling

Evolution API reads `response.data.output` or `response.data.answer` (fallback) from the n8n response and sends that text to the WhatsApp contact.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `N8N_ENABLED` | `false` | Enable integration |

### Useful for SolveTax?

**Conditionally useful if the team already runs n8n.** If SolveTax uses n8n for other automation (document generation, reminders, email triggers), connecting it to WhatsApp via this integration is low effort. The session management being inside Evolution API means n8n only needs to handle the business logic, not session state.

If n8n is not already in the stack, skip it. The FastAPI backend can receive the same events via the standard Evolution API webhook (doc 03) with more control and no additional service.

---

## 7. EvoAI

### What It Does

Connects WhatsApp to an EvoAI endpoint (Evolution Foundation's own AI agent service). Follows the same trigger-and-session pattern as all other bot integrations. Added in v2.3.0.

### Endpoints (`/evoai/{instance}`)

Standard CRUD + settings + `changeStatus` + `fetchSessions` + `ignoreJid`.

### DTO Fields

| Field | Type | Notes |
|---|---|---|
| `agentUrl` | `string` | EvoAI service endpoint, no trailing slash |
| `apiKey` | `string` | EvoAI authentication key |
| `evoaiIdFallback` | `string` | Fallback bot ID (in settings DTO) |

Context variables injected into sessions: `remoteJid`, `pushName`, `instanceName`, `serverUrl`, `apiKey`.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `EVOAI_ENABLED` | `false` | Enable integration |

### Useful for SolveTax?

**Skip for now.** EvoAI is a first-party Evolution Foundation service with limited public documentation at the time of writing. Wait for the ecosystem to mature before adopting it in a production tax-services context.

---

## 8. S3 / MinIO Media Storage

### What It Does

When enabled, all received WhatsApp media (images, audio, video, documents, stickers, voice notes) are uploaded to an S3-compatible bucket instead of being stored locally. A presigned URL (7-day default expiry) is placed in the `mediaUrl` field of every outgoing webhook event.

Without this, Evolution API stores media files on the local Docker volume and serves them from its own HTTP server — which is fragile across container restarts and scales poorly.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `S3_ENABLED` | `false` | Enable S3/MinIO storage |
| `S3_ACCESS_KEY` | — | Access key ID |
| `S3_SECRET_KEY` | — | Secret access key |
| `S3_BUCKET` | `evolution` | Bucket name |
| `S3_ENDPOINT` | — | Endpoint domain (MinIO host or AWS regional endpoint) |
| `S3_PORT` | `9000` (MinIO) / `443` (AWS) | Service port |
| `S3_REGION` | — | AWS region (e.g. `us-east-1`) |
| `S3_USE_SSL` | `false` | Enable TLS |
| `S3_SKIP_POLICY` | `false` | Skip automatic `setBucketPolicy` on startup; set `true` for providers that reject that API call |

### mediaUrl in Webhook Payloads

```json
{
  "event": "messages.upsert",
  "data": {
    "message": {
      "mediaUrl": "https://{endpoint}/{bucket}/{path/to/file.jpg}?X-Amz-...",
      "mimetype": "image/jpeg"
    }
  }
}
```

Presigned URL expiry: 7 days (604,800 seconds). URLs are generated via MinIO SDK `presignedGetObject`.

### Interaction with Chatwoot

When S3 is enabled, Chatwoot integration uses the S3 `mediaUrl` when forwarding media to agents — no local temp file download/re-upload cycle. When `CHATWOOT_IMPORT_PLACEHOLDER_MEDIA_MESSAGE=true`, historical message import skips media downloads and stores placeholder text in Chatwoot instead.

### S3-Compatible Options for SolveTax

SolveTax currently uses Azure Blob Storage. Options:

| Option | Notes |
|---|---|
| **Azure Blob Storage (S3 compat)** | Azure Blob has an S3-compatible API endpoint (`{account}.blob.core.windows.net`) available via the Azure Storage SDK; however, S3 compatibility is not 100% — test `setBucketPolicy` behavior and set `S3_SKIP_POLICY=true` if it returns 403/501. Verify against current Evolution API MinIO SDK version. |
| **MinIO (self-hosted on Azure VM)** | Add a `minio` service to the Docker Compose stack on the existing Azure VM. Full S3 API compatibility guaranteed. Adds ~200 MB memory overhead. Use a persistent volume backed by Azure Managed Disk. |
| **AWS S3** | Set `S3_ENDPOINT` to the regional endpoint (e.g. `s3.ap-south-1.amazonaws.com`), `S3_PORT=443`, `S3_USE_SSL=true`. Straightforward if the team already has an AWS account. |
| **Cloudflare R2** | S3-compatible, zero egress cost. Set `S3_SKIP_POLICY=true` (R2 rejects `setBucketPolicy`). Endpoint: `{accountId}.r2.cloudflarestorage.com`. |

**Recommendation for SolveTax:** Add a MinIO container to the existing Docker Compose stack (same Azure VM) backed by an Azure Managed Disk. This keeps all data in the same Azure region, avoids egress costs, and gives 100% S3 API compatibility with no policy quirks. If the Azure Blob S3-compat endpoint proves reliable in testing, that also works and avoids running another container.

### Example MinIO Docker Compose Snippet

```yaml
minio:
  image: minio/minio:latest
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: ${S3_ACCESS_KEY}
    MINIO_ROOT_PASSWORD: ${S3_SECRET_KEY}
  volumes:
    - minio_data:/data
  ports:
    - "9000:9000"
    - "9001:9001"   # web console; restrict access
  restart: unless-stopped

volumes:
  minio_data:
```

Corresponding Evolution API env vars:

```env
S3_ENABLED=true
S3_ACCESS_KEY=<minio-root-user>
S3_SECRET_KEY=<minio-root-password>
S3_BUCKET=evolution
S3_ENDPOINT=minio  # Docker service name; or public hostname if accessed externally
S3_PORT=9000
S3_USE_SSL=false
S3_REGION=us-east-1  # MinIO ignores this but the SDK requires a non-empty value
S3_SKIP_POLICY=false
```

### Useful for SolveTax?

**Deferred to Phase 3+ per the rollout plan (see 08-rollout-plan.md).** Without S3, media files live on the Docker container volume. A container restart, redeploy, or volume issue means broken media links in the CRM and Chatwoot. However, the phased rollout plan deliberately defers S3/MinIO until media volume justifies it, treating the local filesystem as adequate for Phase 1–2. Enable MinIO (or Azure Blob if S3 compat holds up) when Phase 3 campaign volume makes media durability a priority. The 7-day presigned URL expiry is short for CRM use — plan to re-fetch and store the actual binary in Azure Blob via FastAPI when the webhook arrives, rather than storing the presigned URL in Postgres long-term.

---

## Integration Priority Summary for SolveTax

| Integration | Priority | Rationale |
|---|---|---|
| S3 / MinIO | **Deferred to Phase 3 (see 08-rollout-plan.md)** | Local filesystem adequate for Phase 1–2; enable when media volume requires durability |
| Chatwoot | **High — use as interim support inbox** | Fills human-agent gap before native inbox is built |
| OpenAI (Whisper STT) | **Medium — enable when voice notes become common** | Low effort, high value for transcribing client voice notes |
| OpenAI (bot) | **Low — triage bot only if pursued** | Tax advice automation is high compliance risk |
| n8n | **Conditional — only if n8n already in stack** | Not worth adding another service just for this |
| Typebot | **Low** | FastAPI backend handles the same flows with more control |
| Dify | **Skip for now** | Adds hosting overhead; limited gain over direct FastAPI + OpenAI SDK |
| Flowise | **Skip** | Same reasoning as Dify |
| EvoAI | **Skip** | Limited documentation; ecosystem too new |

---

## Sources

- https://docs.evolutionfoundation.com.br/en/evolution-api/integrations/chatwoot
- https://docs.evolutionfoundation.com.br/en/evolution-api/integrations/typebot
- https://docs.evolutionfoundation.com.br/en/evolution-api/integrations/openai
- https://docs.evolutionfoundation.com.br/en/evolution-api/integrations/dify
- https://docs.evolutionfoundation.com.br/en/evolution-api/integrations/flowise
- https://docs.evolutionfoundation.com.br/en/evolution-api/integrations/evoai
- https://deepwiki.com/EvolutionAPI/evolution-api
- https://deepwiki.com/EvolutionAPI/evolution-api/1.3-configuration
- https://deepwiki.com/EvolutionAPI/evolution-api/6.2-chatwoot-crm-integration
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/.env.example
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/CHANGELOG.md
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/n8n/routes/n8n.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/n8n/dto/n8n.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/n8n/services/n8n.service.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/openai/services/openai.service.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/openai/dto/openai.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/typebot/services/typebot.service.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/typebot/dto/typebot.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/dify/dto/dify.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/dify/services/dify.service.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/flowise/dto/flowise.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/chatwoot/dto/chatwoot.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/chatwoot/services/chatwoot.service.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/chatbot/evoai/dto/evoai.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/base-chatbot.dto.ts
- https://github.com/EvolutionAPI/evolution-api/issues/1404
- https://github.com/EvolutionAPI/evolution-api/issues/1459
- https://github.com/EvolutionAPI/evolution-api/issues/1472
- https://newreleases.io/project/github/EvolutionAPI/evolution-api/release/2.3.7
- https://github.com/evolution-foundation/evolution-api
