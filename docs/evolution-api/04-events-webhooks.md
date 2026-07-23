# Events, Webhooks, and Real-Time Transports

Evolution API v2 delivers every WhatsApp event over one or more transports: HTTP webhook, WebSocket (Socket.IO), RabbitMQ, Kafka, SQS, NATS, or Pusher. All transports use the same event set and the same JSON envelope. This document covers the full event catalog, webhook wiring, the annotated payload reference, delivery semantics, alternative transports, and a concrete recommendation for SolveTax.

---

## Event Catalog

Events appear in two forms:
- **ENV / array form** — `UPPER_SNAKE_CASE`, used in `.env` flags and in the `events` array of per-instance API calls.
- **Wire name** — dot-notation lowercase, the value of the `"event"` field inside the delivered payload.

### Instance / Connection Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `APPLICATION_STARTUP` | `application.startup` | API server process starts | Confirm Evolution API is alive after a deploy or VM reboot |
| `INSTANCE_CREATE` | `instance.create` | A new WhatsApp instance is created (RabbitMQ/Kafka only) | Audit trail if multiple staff instances are provisioned |
| `INSTANCE_DELETE` | `instance.delete` | An instance is deleted (RabbitMQ/Kafka only) | Alert if an instance is accidentally removed |
| `QRCODE_UPDATED` | `qrcode.updated` | QR code is generated or regenerated | Relay the QR to the staff member who needs to scan it; `count` tells you how many attempts remain |
| `CONNECTION_UPDATE` | `connection.update` | WhatsApp connection state changes: `connecting`, `open`, `close` | Critical — trigger reconnect alerts and suppress outbound sends when state is not `open` |
| `REMOVE_INSTANCE` | `remove.instance` | Instance removed from the system | Housekeeping; remove from your instance registry |
| `LOGOUT_INSTANCE` | `logout.instance` | Instance explicitly logged out | Trigger re-auth flow |

### Message Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `MESSAGES_SET` | `messages.set` / `messaging-history.set` | Bulk history sync on startup; high volume | **Disable in production** (`WEBHOOK_EVENTS_MESSAGES_SET=false`) unless backfilling chat history; use `isLatest=true` flag to detect sync completion |
| `MESSAGES_UPSERT` | `messages.upsert` | New inbound or outbound message | **Primary event** — create/update conversation records, trigger staff notifications |
| `MESSAGES_EDITED` | `messages.edited` | A sent message is edited (v2 only) | Update stored message body |
| `MESSAGES_UPDATE` | `messages.update` | Delivery and read receipts, reactions | Track read status on outbound client messages; surface "client has read" in CRM timeline |
| `MESSAGES_DELETE` | `messages.delete` | Message deleted | Soft-delete or tombstone the record |
| `SEND_MESSAGE` | `send.message` | Message sent outbound via API (local event) | Confirm sends completed; log for billing/audit |
| `SEND_MESSAGE_UPDATE` | `send.message.update` | Sent-message status update (v2 only) | Supplement `MESSAGES_UPDATE` for messages sent via the API |

### Contact / Presence Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `CONTACTS_SET` | `contacts.set` | Bulk contact sync on startup; high volume | Disable in production; use only for initial import |
| `CONTACTS_UPSERT` | `contacts.upsert` | New or updated contact | Sync WhatsApp display names into the CRM contact record |
| `CONTACTS_UPDATE` | `contacts.update` | Contact profile changes | Keep display name / avatar current |
| `PRESENCE_UPDATE` | `presence.update` | Contact online/offline or typing indicator | Optional: show typing indicator in staff chat UI |

### Chat Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `CHATS_SET` | `chats.set` | Bulk chat list sync on startup; high volume | Disable in production |
| `CHATS_UPSERT` | `chats.upsert` | New chat opened | Create conversation thread in CRM |
| `CHATS_UPDATE` | `chats.update` | Mute, pin, archive, unread count changes | Reflect archive/unread state in admin UI |
| `CHATS_DELETE` | `chats.delete` | Chat deleted | Soft-delete conversation thread |

### Group Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `GROUPS_UPSERT` | `groups.upsert` | Group created or group info received | Register group if SolveTax uses WhatsApp groups for bulk advisories |
| `GROUPS_UPDATE` | `groups.update` | Group subject, description, or settings changed | Keep group metadata current |
| `GROUP_PARTICIPANTS_UPDATE` | `group-participants.update` | Participant added, removed, promoted, or demoted | Manage group membership records |

### Label Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `LABELS_EDIT` | `labels.edit` | Label created, renamed, or deleted | Sync WhatsApp labels with CRM tags |
| `LABELS_ASSOCIATION` | `labels.association` | Label applied to or removed from a chat | Mirror label-to-chat mapping |

### Other Events

| Event | Wire name | When it fires | Why SolveTax cares |
|---|---|---|---|
| `CALL` | `call` | Incoming voice or video call | Log call attempts; alert staff member |
| `TYPEBOT_START` | `typebot.start` | Typebot session initiated | Relevant only if Typebot integration is used |
| `TYPEBOT_CHANGE_STATUS` | `typebot.change.status` | Typebot session status changes | Same as above |
| `ERRORS` | `errors` | Internal delivery error (webhook-only; defaults `false`) | Enable during debugging; disable in production |

> **v2.3.7 addition:** `messaging-history.set` is an alias for `MESSAGES_SET`. It carries `isLatest: true` and a `progress` percentage; consumers can use `isLatest` to know when history sync has completed.

---

## Webhook Configuration

### Per-Instance Setup

```
POST /webhook/set/{instanceName}
GET  /webhook/find/{instanceName}
```

Required header: `apikey: <your-api-key>`

Returns HTTP 201 on success with the stored configuration.

**Request body:**

```json
{
  "enabled": true,
  "url": "https://api.solvetax.in/whatsapp/webhook",
  "byEvents": true,
  "base64": false,
  "headers": {
    "Authorization": "Bearer <solvetax-webhook-secret>"
  },
  "events": [
    "QRCODE_UPDATED",
    "CONNECTION_UPDATE",
    "MESSAGES_UPSERT",
    "MESSAGES_UPDATE",
    "MESSAGES_DELETE",
    "SEND_MESSAGE",
    "CONTACTS_UPSERT",
    "CONTACTS_UPDATE",
    "CHATS_UPSERT",
    "CHATS_UPDATE",
    "CALL"
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `enabled` | boolean | `false` disables the webhook without deleting the config |
| `url` | string | Base URL; Evolution API appends event-name suffixes when `byEvents: true` |
| `byEvents` | boolean | Route each event to a separate path under `url` (see URL-suffix routing below). Joi schema name is `byEvents`; `webhookByEvents` is an accepted alias |
| `base64` | boolean | Encode media payloads as base64 data URIs inline. Accepted alias: `webhookBase64`. Keep `false` unless the receiver cannot handle binary references |
| `headers` | object | Custom HTTP headers sent with every delivery — use for auth tokens |
| `events` | string[] | Subset of `UPPER_SNAKE_CASE` event names. Omit the array to receive all globally-enabled events |

### byEvents URL-Suffix Routing

When `byEvents: true`, the API appends a kebab-case path segment derived from the event name (underscores replaced with hyphens, lowercased):

| Event | Path appended |
|---|---|
| `MESSAGES_UPSERT` | `/messages-upsert` |
| `MESSAGES_UPDATE` | `/messages-update` |
| `CONNECTION_UPDATE` | `/connection-update` |
| `QRCODE_UPDATED` | `/qrcode-updated` |
| `SEND_MESSAGE` | `/send-message` |
| `GROUP_PARTICIPANTS_UPDATE` | `/group-participants-update` |

**Example** — base URL `https://api.solvetax.in/whatsapp/webhook`:

```
POST https://api.solvetax.in/whatsapp/webhook/messages-upsert
POST https://api.solvetax.in/whatsapp/webhook/connection-update
POST https://api.solvetax.in/whatsapp/webhook/qrcode-updated
```

This lets you mount each event on a dedicated FastAPI route handler rather than routing inside a single handler.

### Global Webhook Environment Variables

These apply to all instances when no per-instance override exists, or when `WEBHOOK_GLOBAL_ENABLED=true`.

```dotenv
# Global webhook
WEBHOOK_GLOBAL_ENABLED=false
WEBHOOK_GLOBAL_URL=
WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS=false

# Delivery tuning
WEBHOOK_REQUEST_TIMEOUT_MS=30000
WEBHOOK_RETRY_MAX_ATTEMPTS=10
WEBHOOK_RETRY_INITIAL_DELAY_SECONDS=5
WEBHOOK_RETRY_USE_EXPONENTIAL_BACKOFF=true
WEBHOOK_RETRY_MAX_DELAY_SECONDS=300
WEBHOOK_RETRY_JITTER_FACTOR=0.2
WEBHOOK_RETRY_NON_RETRYABLE_STATUS_CODES=400,401,403,404,422
```

### Per-Event Global Enable/Disable Flags

All flags are `WEBHOOK_EVENTS_<EVENT_NAME>`. Representative defaults:

```dotenv
WEBHOOK_EVENTS_APPLICATION_STARTUP=false
WEBHOOK_EVENTS_QRCODE_UPDATED=true
WEBHOOK_EVENTS_CONNECTION_UPDATE=true
WEBHOOK_EVENTS_MESSAGES_SET=true        # set false in production
WEBHOOK_EVENTS_MESSAGES_UPSERT=true
WEBHOOK_EVENTS_MESSAGES_EDITED=true
WEBHOOK_EVENTS_MESSAGES_UPDATE=true
WEBHOOK_EVENTS_MESSAGES_DELETE=true
WEBHOOK_EVENTS_SEND_MESSAGE=true
WEBHOOK_EVENTS_SEND_MESSAGE_UPDATE=true
WEBHOOK_EVENTS_CONTACTS_SET=true        # set false in production
WEBHOOK_EVENTS_CONTACTS_UPSERT=true
WEBHOOK_EVENTS_CONTACTS_UPDATE=true
WEBHOOK_EVENTS_PRESENCE_UPDATE=true
WEBHOOK_EVENTS_CHATS_SET=true           # set false in production
WEBHOOK_EVENTS_CHATS_UPSERT=true
WEBHOOK_EVENTS_CHATS_UPDATE=true
WEBHOOK_EVENTS_CHATS_DELETE=true
WEBHOOK_EVENTS_GROUPS_UPSERT=true
WEBHOOK_EVENTS_GROUPS_UPDATE=true
WEBHOOK_EVENTS_GROUP_PARTICIPANTS_UPDATE=true
WEBHOOK_EVENTS_LABELS_EDIT=true
WEBHOOK_EVENTS_LABELS_ASSOCIATION=true
WEBHOOK_EVENTS_CALL=true
WEBHOOK_EVENTS_REMOVE_INSTANCE=false
WEBHOOK_EVENTS_LOGOUT_INSTANCE=false
WEBHOOK_EVENTS_TYPEBOT_START=false
WEBHOOK_EVENTS_TYPEBOT_CHANGE_STATUS=false
WEBHOOK_EVENTS_ERRORS=false
```

---

## Webhook Payload Reference

### Universal Envelope

Every POST body — regardless of event type or transport — uses this wrapper:

```json
{
  "event": "messages.upsert",
  "instance": "my-instance-name",
  "data": {},
  "destination": "https://api.solvetax.in/whatsapp/webhook",
  "date_time": "2025-11-26T14:45:04.495Z",
  "sender": "5511943238000@s.whatsapp.net",
  "server_url": "https://evolution.solvetax.in",
  "apikey": "uuid-or-api-key-string"
}
```

| Field | Notes |
|---|---|
| `event` | Wire name of the event (dot-notation) |
| `instance` | Name of the Evolution API instance that emitted the event |
| `data` | Event-specific payload (see below) |
| `destination` | The webhook URL this was sent to |
| `date_time` | ISO 8601 timestamp from the Evolution API server |
| `sender` | JID of the WhatsApp account bound to this instance |
| `server_url` | Origin Evolution API server |
| `apikey` | API key or instance UUID — use for multi-tenant routing, not for auth verification |

### MESSAGES_UPSERT — Annotated Example

This is the highest-volume and most important event for SolveTax.

```json
{
  "event": "messages.upsert",
  "instance": "solvetax-main",
  "data": {
    "key": {
      "remoteJid": "5511966662222@s.whatsapp.net",
      "remoteJidAlt": "232134862233733@lid",
      "fromMe": false,
      "id": "AC412D8403E76D920E62FB7B63F3CF39",
      "participant": "",
      "addressingMode": "pn"
    },
    "pushName": "Ramesh Kumar",
    "status": "SERVER_ACK",
    "message": {
      "conversation": "Hello, I have a question about my GST return."
    },
    "contextInfo": {
      "mentionedJid": [],
      "groupMentions": [],
      "stanzaId": "A507F13EEC05FFCB8692DB0A8856F91A",
      "participant": "5511966662222@s.whatsapp.net",
      "quotedMessage": {
        "conversation": "Previous message being replied to"
      }
    },
    "messageType": "conversation",
    "messageTimestamp": 1764253714,
    "instanceId": "54608597-bc77-4fa4-afb0-0d0ea3fc45a2",
    "source": "web"
  },
  "destination": "https://api.solvetax.in/whatsapp/webhook/messages-upsert",
  "date_time": "2025-11-27T11:28:35.080Z",
  "sender": "919876543210@s.whatsapp.net",
  "server_url": "https://evolution.solvetax.in",
  "apikey": "54608597-bc77-4fa4-afb0-0d0ea3fc45a2"
}
```

**Field-by-field breakdown:**

| Field | Type | Description |
|---|---|---|
| `data.key.remoteJid` | string | JID of the other party. Format: `<phone>@s.whatsapp.net` for 1:1, `<id>@g.us` for groups, `<id>@lid` for Meta Ads traffic |
| `data.key.fromMe` | boolean | `true` = sent by this instance (outbound); `false` = received (inbound) |
| `data.key.id` | string | Unique message ID — **use this as your idempotency key**; duplicates arrive on retries |
| `data.key.participant` | string | In group messages, the JID of the actual sender within the group (group itself is in `remoteJid`) |
| `data.key.addressingMode` | string | `"pn"` = phone-number addressing; other values indicate LID-mode (Meta Ads) |
| `data.key.remoteJidAlt` | string | Alternative LID identifier; may be absent on non-Meta-Ads messages |
| `data.pushName` | string / null | WhatsApp display name of the sender; `null` for some Meta Ads–sourced messages |
| `data.status` | string | Current message status: `SERVER_ACK`, `DELIVERY_ACK`, `READ`, `PLAYED` |
| `data.message.conversation` | string | Plain-text message body for simple text messages |
| `data.message.extendedTextMessage.text` | string | Rich text body with link preview; mutually exclusive with `conversation` |
| `data.message.imageMessage` | object | Present for image messages; contains `caption`, `url`, `mimetype`, `fileLength` |
| `data.message.audioMessage` | object | Present for voice notes / audio |
| `data.message.videoMessage` | object | Present for video messages |
| `data.message.documentMessage` | object | Present for file attachments (PDFs, etc.) |
| `data.message.stickerMessage` | object | Present for stickers |
| `data.message.reactionMessage` | object | Present for emoji reactions; contains `key` of the reacted-to message and `text` (the emoji) |
| `data.messageType` | string | Discriminator: `"conversation"`, `"extendedTextMessage"`, `"imageMessage"`, `"audioMessage"`, `"videoMessage"`, `"documentMessage"`, `"stickerMessage"`, `"reactionMessage"`, etc. Use this to branch your parser |
| `data.messageTimestamp` | number | Unix timestamp in **seconds** (not milliseconds) — multiply by 1000 for JS `Date()` |
| `data.instanceId` | string | UUID of the Evolution API instance (v2 only; replaces the `owner` field from v1) |
| `data.source` | string | Client platform that sent the message: `"web"`, `"android"`, `"ios"` |
| `data.contextInfo` | object | Present when a message is a reply. `quotedMessage` holds the original text; `stanzaId` is the ID of the quoted message; `mentionedJid` lists any @-mentioned JIDs |

**To extract the plain text body safely in Python:**

```python
msg = data.get("message", {})
text = (
    msg.get("conversation")
    or msg.get("extendedTextMessage", {}).get("text")
    or msg.get("imageMessage", {}).get("caption")
    or msg.get("videoMessage", {}).get("caption")
    or msg.get("documentMessage", {}).get("caption")
    or ""
)
```

### CONNECTION_UPDATE — Data Block

```json
{
  "state": "open",
  "statusReason": 200
}
```

| `state` | Meaning |
|---|---|
| `connecting` | Attempting to establish session |
| `open` | Fully authenticated and connected |
| `close` | Disconnected |

| `statusReason` | Meaning |
|---|---|
| 200 | Success |
| 401 | Unauthorized (re-auth required) |
| 403 | Banned number |
| 408 | Timeout |
| 428 | Conflict (another client connected) |
| 440 | Session replaced by another device |
| 515 | Stream error |

### QRCODE_UPDATED — Data Block

```json
{
  "qrcode": {
    "base64": "data:image/png;base64,iVBORw0KGgo...",
    "code": "2@XYZ...",
    "count": 1
  }
}
```

`count` increments on each regeneration. The instance disconnects after a configured maximum (typically 3–5 attempts). Deliver the `base64` string directly to an `<img src>` tag in your admin UI.

### MESSAGES_UPDATE — Data Block (receipt/status)

```json
{
  "key": {
    "remoteJid": "5511966662222@s.whatsapp.net",
    "fromMe": true,
    "id": "3EB0BF8072876BE899FE20"
  },
  "update": {
    "status": "READ"
  }
}
```

Match `key.id` to a stored message record and update its delivery status. Use this to show "client has read the document request" in the CRM timeline.

---

## Delivery Semantics

### Retry Behavior

- **Model:** At-least-once. The same event will be delivered more than once if the receiver does not respond with HTTP 200 promptly.
- **Timeout:** 30 s per attempt (`WEBHOOK_REQUEST_TIMEOUT_MS`).
- **Max attempts:** 10 (`WEBHOOK_RETRY_MAX_ATTEMPTS`).
- **Backoff:** Exponential starting at 5 s (`WEBHOOK_RETRY_INITIAL_DELAY_SECONDS`), capped at 300 s (`WEBHOOK_RETRY_MAX_DELAY_SECONDS`), with ±20% jitter (`WEBHOOK_RETRY_JITTER_FACTOR=0.2`) to prevent thundering herd.
- **Abort conditions:** HTTP 400, 401, 403, 404, or 422 stops retries immediately (`WEBHOOK_RETRY_NON_RETRYABLE_STATUS_CODES`). A 500 or timeout will retry.

### Ordering

Webhooks carry **no ordering guarantee** across events. Events from the same conversation may arrive out of sequence. Use `data.messageTimestamp` for display ordering in the CRM, not arrival time.

### Duplicates

Because the model is at-least-once, duplicates are expected. **Deduplicate using `data.key.id`** (message ID), which is stable across redeliveries. Store processed IDs in Redis with a short TTL (e.g., 24 h) and drop any event whose `key.id` you have already seen.

### Receiver Contract

1. **Return HTTP 200 immediately** — before any database writes or downstream calls. A slow response triggers unnecessary retries.
2. **Enqueue to a task queue** (Celery, ARQ, or equivalent) for actual processing.
3. **Validate the `Authorization` header** using the `headers.Authorization` value you set during `/webhook/set`.
4. **Log the raw payload** before enqueuing — useful for replay if a bug is found later.

```python
# FastAPI example — fast ack, async processing
@router.post("/whatsapp/webhook/messages-upsert")
async def handle_messages_upsert(
    request: Request,
    background_tasks: BackgroundTasks,
):
    auth = request.headers.get("Authorization")
    if auth != f"Bearer {settings.WHATSAPP_WEBHOOK_SECRET}":
        raise HTTPException(status_code=403)
    payload = await request.json()
    background_tasks.add_task(process_message_upsert, payload)
    return {"status": "ok"}
```

---

## Alternative Transports

All transports share the same event set and envelope. Per-instance configuration follows the pattern:

```
POST /{transport}/set/{instanceName}
GET  /{transport}/find/{instanceName}
```

Where `{transport}` is one of: `webhook`, `rabbitmq`, `sqs`, `kafka`, `nats`, `websocket`, `pusher`.

### Delivery Guarantee Summary

| Transport | Guarantee | Retry | Ordering |
|---|---|---|---|
| Webhook | At-least-once | Exponential backoff, max 10 attempts | None |
| RabbitMQ | At-least-once | Quorum queue redelivery | FIFO per routing key |
| Kafka | At-least-once | Producer idempotence | FIFO per partition |
| SQS | At-least-once | FIFO with deduplication | FIFO per group |
| WebSocket | At-most-once | None | None |
| NATS | At-most-once | None | None |
| Pusher | At-most-once | None | None |

### RabbitMQ

Added in v1.5.0; global mode added in v1.8.0.

**Per-instance body:**
```json
{ "enabled": true, "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"] }
```

**Environment variables:**

```dotenv
RABBITMQ_ENABLED=false
RABBITMQ_URI=amqp://user:pass@rabbitmq:5672
RABBITMQ_EXCHANGE_NAME=evolution_exchange
RABBITMQ_GLOBAL_ENABLED=false
RABBITMQ_PREFIX_KEY=
RABBITMQ_FRAME_MAX=8192
```

All event flags are `RABBITMQ_EVENTS_<EVENT>`, all default `false`. Enable selectively.

**When to prefer:** You already run RabbitMQ in your stack, or you need durable at-least-once delivery with FIFO ordering per conversation (use `remoteJid` as the routing key).

### Amazon SQS

Added in v1.6.0.

**Per-instance body:**
```json
{ "enabled": true, "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"] }
```

**Environment variables:**

```dotenv
SQS_ENABLED=false
SQS_ACCESS_KEY_ID=
SQS_SECRET_ACCESS_KEY=
SQS_ACCOUNT_ID=
SQS_REGION=ap-south-1
SQS_MAX_PAYLOAD_SIZE=1048576
SQS_GLOBAL_ENABLED=false
SQS_GLOBAL_FORCE_SINGLE_QUEUE=false
SQS_GLOBAL_PREFIX_NAME=global
```

**S3 overflow:** When a payload exceeds `SQS_MAX_PAYLOAD_SIZE` (1 MB, e.g., base64 media), Evolution API offloads to S3 and places only the S3 reference URL in the SQS message.

All event flags are `SQS_GLOBAL_<EVENT>`, all default `false`.

**When to prefer:** Your infrastructure is AWS-native and you want managed durability without running a broker.

### Apache Kafka

Added in v2.3.4 (December 2024).

**Per-instance body:**
```json
{ "enabled": true, "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"] }
```

**Environment variables:**

```dotenv
KAFKA_ENABLED=false
KAFKA_CLIENT_ID=evolution-api
KAFKA_BROKERS=localhost:9092
KAFKA_CONNECTION_TIMEOUT=3000
KAFKA_REQUEST_TIMEOUT=30000
KAFKA_GLOBAL_ENABLED=false
KAFKA_CONSUMER_GROUP_ID=evolution-api-consumers
KAFKA_TOPIC_PREFIX=evolution
KAFKA_NUM_PARTITIONS=1
KAFKA_REPLICATION_FACTOR=1
KAFKA_AUTO_CREATE_TOPICS=false
KAFKA_SASL_ENABLED=false
KAFKA_SASL_MECHANISM=plain
KAFKA_SASL_USERNAME=
KAFKA_SASL_PASSWORD=
KAFKA_SSL_ENABLED=false
KAFKA_SSL_REJECT_UNAUTHORIZED=true
KAFKA_SSL_CA=
KAFKA_SSL_KEY=
KAFKA_SSL_CERT=
```

All event flags are `KAFKA_EVENTS_<EVENT>`, all default `false`. Kafka also supports `INSTANCE_CREATE` and `INSTANCE_DELETE` which are not available to webhooks.

**When to prefer:** High-throughput multi-consumer scenarios, or when you need replay from an offset. Overkill for SolveTax at current scale.

### NATS

Added in v2.3.0 (June 2024).

**Per-instance body:**
```json
{ "enabled": true, "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"] }
```

**Environment variables:**

```dotenv
NATS_ENABLED=false
NATS_URI=nats://localhost:4222
NATS_EXCHANGE_NAME=evolution_exchange
NATS_GLOBAL_ENABLED=false
NATS_PREFIX_KEY=
```

**Delivery model:** At-most-once (fire-and-forget, no retry). Do not use NATS for events where losing a message is unacceptable.

**When to prefer:** Low-latency internal fan-out where loss is tolerable (e.g., presence indicators in a dashboard). Not appropriate for message ingestion.

### WebSocket (Socket.IO)

Added in v1.5.0; wildcard host support added in v2.3.7.

**Per-instance body:**
```json
{ "enabled": true, "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"] }
```

**Environment variables:**

```dotenv
WEBSOCKET_ENABLED=false
WEBSOCKET_GLOBAL_EVENTS=false
WEBSOCKET_ALLOWED_HOSTS=*
```

**Connection:**
```
ws://evolution.solvetax.in/socket.io?apikey=<apiKey>
```

Clients join the instance namespace: `socket.of('/solvetax-main')`. When `WEBSOCKET_GLOBAL_EVENTS=true`, all events are also broadcast on the root namespace.

**Delivery model:** At-most-once (no retry). Use only for live UI updates — not as the primary ingestion path.

**When to prefer:** Real-time push to a browser-based staff chat UI. Run alongside the primary webhook receiver, not as a replacement.

### Pusher

**Per-instance body:**
```json
{
  "enabled": true,
  "events": ["MESSAGES_UPSERT"],
  "appId": "your-app-id",
  "key": "your-key",
  "secret": "your-secret",
  "cluster": "mt1",
  "useTLS": true
}
```

**Global environment variables:** `PUSHER_ENABLED`, `PUSHER_GLOBAL_ENABLED`, `PUSHER_GLOBAL_APP_ID`, `PUSHER_GLOBAL_KEY`, `PUSHER_GLOBAL_SECRET`, `PUSHER_GLOBAL_CLUSTER`, `PUSHER_GLOBAL_USE_TLS`.

Channel naming: `{instanceName}:{eventType}` per-instance; `global:{eventType}` in global mode.

**When to prefer:** You use Pusher Channels already and need push to browser/mobile without managing a WebSocket server. At-most-once; adds a third-party dependency and cost.

---

## Recommendation for SolveTax

### Transport Choice

**Use HTTP webhooks into FastAPI.** SolveTax runs FastAPI + Postgres + Redis on a single Azure VM. Adding RabbitMQ or Kafka to the compose stack solely for Evolution API events is unnecessary complexity at current scale. Webhooks into FastAPI backed by Celery or ARQ (whichever you already use for background tasks) are sufficient and easy to debug.

Enable WebSocket in addition to webhooks only if you build a real-time chat UI in the admin frontend — use it for browser push only, never as the primary record of events.

### Events to Subscribe First

Configure `/webhook/set/{instanceName}` with this minimal events array on day one:

| Priority | Event | Reason |
|---|---|---|
| P0 | `MESSAGES_UPSERT` | All inbound client messages and outbound confirmations |
| P0 | `CONNECTION_UPDATE` | Know when the WhatsApp session drops; suppress sends; alert staff |
| P0 | `QRCODE_UPDATED` | Deliver QR to the staff member during initial auth and re-auth |
| P1 | `MESSAGES_UPDATE` | Track delivery and read receipts on outbound messages |
| P1 | `SEND_MESSAGE` | Confirm that API-triggered sends completed; log for audit |

Add after initial rollout, once the core flow is stable:

- `MESSAGES_DELETE` — tombstone deleted messages in the CRM
- `CONTACTS_UPSERT` / `CONTACTS_UPDATE` — sync WhatsApp display names
- `CHATS_UPSERT` / `CHATS_UPDATE` — manage conversation threads
- `CALL` — log missed call attempts

**Do not subscribe to these in production:**

- `MESSAGES_SET`, `CONTACTS_SET`, `CHATS_SET` — bulk history sync on every reconnect; will flood your receiver
- `PRESENCE_UPDATE` — continuous noise unless you display live typing indicators

### `byEvents` Routing

Set `byEvents: true`. Map each event to its own FastAPI route for clarity and to isolate failure modes:

```python
router.add_api_route("/messages-upsert", handle_messages_upsert, methods=["POST"])
router.add_api_route("/messages-update", handle_messages_update, methods=["POST"])
router.add_api_route("/connection-update", handle_connection_update, methods=["POST"])
router.add_api_route("/qrcode-updated", handle_qrcode_updated, methods=["POST"])
router.add_api_route("/send-message", handle_send_message, methods=["POST"])
```

### Idempotency

Store `data.key.id` in Redis with a 24-hour TTL on first processing. On each incoming webhook, check Redis before enqueuing. This handles both retry duplicates from Evolution API and any double-delivery from upstream WhatsApp.

---

## Sources

- https://github.com/evolution-foundation/evolution-api
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/.env.example
- https://github.com/EvolutionAPI/evolution-api/blob/main/CHANGELOG.md
- https://github.com/evolution-foundation/evolution-api/releases
- https://evolutionapi-evolution-api-90.mintlify.app/concepts/webhooks
- https://deepwiki.com/EvolutionAPI/evolution-api/5.1-event-types-and-lifecycle
- https://deepwiki.com/EvolutionAPI/evolution-api/5.2-webhook-integration
- https://deepwiki.com/EvolutionAPI/evolution-api/5.4-real-time-integrations
- https://deepwiki.com/EvolutionAPI/evolution-api/7.5-integration-configuration-api
- https://deepwiki.com/EvolutionAPI/evolution-api/1.3-configuration
- https://github.com/EvolutionAPI/evolution-api/issues/2267
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/event/event.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/event/webhook/webhook.schema.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/integrations/event/webhook/webhook.controller.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/abstract/abstract.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/routes/index.router.ts
- https://docs.evolutionfoundation.com.br/en/evolution-api/configuration/webhooks
- https://gist.github.com/dantetesta/b8b7e7e2d6196beae968c8b0a61afb7a
- https://github.com/EvolutionAPI/evolution-client-python/blob/main/README.md
