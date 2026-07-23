# Self-Hosting Evolution API for SolveTax

## Contents

1. [Docker Image and Tag Pinning](#1-docker-image-and-tag-pinning)
2. [Docker Compose — SolveTax Azure VM Layout](#2-docker-compose--solvetax-azure-vm-layout)
3. [Environment Variable Reference](#3-environment-variable-reference)
4. [Nginx Reverse Proxy](#4-nginx-reverse-proxy)
5. [Resource Sizing](#5-resource-sizing)
6. [Upgrade Procedure and Prisma Migrations](#6-upgrade-procedure-and-prisma-migrations)
7. [Backup Considerations](#7-backup-considerations)
8. [SolveTax-Specific Decisions](#8-solvetax-specific-decisions)
9. [Sources](#9-sources)

---

## 1. Docker Image and Tag Pinning

### Official image

```
evoapicloud/evolution-api
```

The Docker Hub publisher is `evoapicloud`. The canonical GitHub org is `evolution-foundation`; the older `EvolutionAPI` org redirects to it. **Do not use the legacy `atendai/evolution-api` image** — it ships a hardcoded internal `.env` that silently overrides externally supplied environment variables (issue #1474); `DATABASE_PROVIDER`, `DATABASE_CONNECTION_URI`, and others are ignored, and the container falls back to localhost defaults.

### Tag strategy

| Tag | Status | Notes |
|---|---|---|
| `evoapicloud/evolution-api:v2.3.7` | **Recommended for prod** | Last stable non-rc release, December 5, 2024 |
| `evoapicloud/evolution-api:v2.4.0-rc2` | Pre-release | Adds mandatory licensing (see §6); May 17, 2026 |
| `evoapicloud/evolution-api:latest` | Tracks most recent stable build | Tag moves; avoid for reproducible deploys |
| `evoapicloud/evolution-api:homolog` | Bleeding edge / staging | Updated most frequently; do not use in prod |

**Recommendation:** pin an explicit version tag (`v2.3.7` or later stable). Record the tag in `docker-compose.yml` and in the deployment notes. Update deliberately, not via `:latest` drift.

**Architecture:** Multi-arch image supports `linux/amd64` and `linux/arm64`. Azure App Service and standard Azure VMs run `amd64`.

**Manager UI image:** `evoapicloud/evolution-manager:latest` (verify against current docs) — web dashboard exposed on port 3000. Optional; only needed if staff will use the GUI directly. Note: only the API image (`evoapicloud/evolution-api`) was confirmed on Docker Hub; confirm `evoapicloud/evolution-manager` at hub.docker.com/r/evoapicloud/evolution-manager before using this image name in deployment scripts.

---

## 2. Docker Compose — SolveTax Azure VM Layout

This compose file is written for the scenario where Evolution API runs on a dedicated Azure VM (or Azure Container Instance) separate from the main SolvetaxAdmin App Service. Postgres and Redis are dedicated to Evolution API — they do not share the SolvetaxAdmin managed DB or Redis instances (see §8 for rationale).

Evolution API binds to `127.0.0.1:8080` only; nginx (§4) terminates TLS externally.

```yaml
version: "3.8"

services:
  evolution_api:
    image: evoapicloud/evolution-api:v2.3.7
    container_name: evolution_api
    restart: always
    ports:
      - "127.0.0.1:8080:8080"
    env_file:
      - .env
    volumes:
      - evolution_instances:/evolution/instances
    depends_on:
      - evolution_postgres
      - evolution_redis
    networks:
      - evolution-net
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "1.5"

  evolution_frontend:
    image: evoapicloud/evolution-manager:latest
    container_name: evolution_frontend
    restart: always
    ports:
      - "127.0.0.1:3000:3000"
    networks:
      - evolution-net

  evolution_postgres:
    image: postgres:15
    container_name: evolution_postgres
    restart: always
    command: postgres -c max_connections=200
    environment:
      POSTGRES_USER: ${POSTGRES_USERNAME}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DATABASE}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5433:5432"   # non-standard host port avoids conflict if 5432 is in use
    networks:
      - evolution-net

  evolution_redis:
    image: redis:7-alpine
    container_name: evolution_redis
    restart: always
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes:
      - evolution_redis:/data
    ports:
      - "127.0.0.1:6380:6379"   # non-standard host port; does not conflict with SolvetaxAdmin Redis
    networks:
      - evolution-net

volumes:
  evolution_instances:
  postgres_data:
  evolution_redis:

networks:
  evolution-net:
    driver: bridge
```

### Minimum `.env` to start

Store this file alongside `docker-compose.yml`. Never commit it; add to `.gitignore`.

```dotenv
# --- Postgres credentials (passed to postgres container and DATABASE_CONNECTION_URI)
POSTGRES_USERNAME=evolution
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DATABASE=evolution_db

# --- Redis
REDIS_PASSWORD=<strong-random-password>

# --- Server
SERVER_URL=https://evo.solvetax.in         # public URL used in webhook callbacks and QR links
SERVER_PORT=8080
SERVER_TYPE=http                           # nginx handles TLS termination

# --- Auth
AUTHENTICATION_API_KEY=<long-random-api-key>

# --- Database
DATABASE_PROVIDER=postgresql
DATABASE_CONNECTION_URI=postgresql://evolution:<POSTGRES_PASSWORD>@evolution_postgres:5432/evolution_db?schema=evolution_api

# --- Redis cache
CACHE_REDIS_ENABLED=true
CACHE_REDIS_URI=redis://:${REDIS_PASSWORD}@evolution_redis:6379/6
CACHE_REDIS_PREFIX_KEY=evolution
CACHE_REDIS_SAVE_INSTANCES=false           # set true only if running multiple API pods

# --- Logging (trim for production)
LOG_LEVEL=ERROR,WARN,INFO
LOG_BAILEYS=error

# --- Instance lifecycle
DEL_INSTANCE=false
```

Replace `<strong-random-password>` values with output from `openssl rand -hex 32`. The `DATABASE_CONNECTION_URI` must contain the `?schema=evolution_api` suffix; without it Prisma defaults to the `public` schema (see §6 for migration issues this causes).

---

## 3. Environment Variable Reference

### SERVER_*

| Variable | Default | Description |
|---|---|---|
| `SERVER_NAME` | `evolution` | Identifier name shown in logs |
| `SERVER_TYPE` | `http` | `http` or `https`. Use `http` behind nginx. |
| `SERVER_PORT` | `8080` | Listening port inside the container |
| `SERVER_URL` | (required) | Full public URL used for webhook callbacks and QR code links |
| `SERVER_DISABLE_DOCS` | `false` | Set `true` to hide Swagger at `/docs` in production |
| `SERVER_DISABLE_MANAGER` | `false` | Set `true` to disable embedded Manager UI at `/manager` |
| `SSL_CONF_PRIVKEY` | — | Path to private key (only when `SERVER_TYPE=https`) |
| `SSL_CONF_FULLCHAIN` | — | Path to cert chain (only when `SERVER_TYPE=https`) |

### AUTHENTICATION_*

| Variable | Default | Description |
|---|---|---|
| `AUTHENTICATION_API_KEY` | (required) | Global API key; sent as `apikey` header on all requests |
| `AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES` | `true` | Whether `GET /instance/fetchInstances` returns per-instance API keys. Default corrected to `true` to match the official `.env.example` and Mintlify docs (see also 03-api-reference.md §Key Environment Variables). Note: the raw TypeScript evaluates `=== 'true'` so the env var must be set explicitly; the project's own example config and official docs treat `true` as the deployment default. Set to `false` to prevent API key exposure in list responses. |

### DATABASE_*

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PROVIDER` | `postgresql` | `postgresql`, `mysql`, or `psql_bouncer` |
| `DATABASE_CONNECTION_URI` | (required) | Prisma-compatible URI. Must include `?schema=evolution_api` to avoid public-schema conflicts. |
| `DATABASE_CONNECTION_CLIENT_NAME` | `evolution_exchange` | Prisma client label (cosmetic) |
| `DATABASE_BOUNCER_CONNECTION_URI` | — | Separate URI for PgBouncer when `DATABASE_PROVIDER=psql_bouncer` |
| `DATABASE_SAVE_DATA_INSTANCE` | `true` | Persist instance metadata to DB |
| `DATABASE_SAVE_DATA_NEW_MESSAGE` | `true` | Persist inbound messages |
| `DATABASE_SAVE_MESSAGE_UPDATE` | `true` | Persist message status updates (read receipts, delivery) |
| `DATABASE_SAVE_DATA_CONTACTS` | `true` | Persist WhatsApp contacts |
| `DATABASE_SAVE_DATA_CHATS` | `true` | Persist chat records |
| `DATABASE_SAVE_DATA_LABELS` | `true` | Persist WhatsApp labels |
| `DATABASE_SAVE_DATA_HISTORIC` | `true` | Persist full message history (high I/O; disable on webhook-only deployments) |
| `DATABASE_SAVE_IS_ON_WHATSAPP` | `true` | Cache number-registration status lookups |
| `DATABASE_SAVE_IS_ON_WHATSAPP_DAYS` | `7` | Retention period for registration-status cache |
| `DATABASE_DELETE_MESSAGE` | `true` | Mark messages deleted when the user deletes them in WhatsApp |

**Tip:** For SolveTax's webhook-first integration (messages consumed by the FastAPI backend), consider disabling `DATABASE_SAVE_DATA_NEW_MESSAGE`, `DATABASE_SAVE_DATA_CONTACTS`, `DATABASE_SAVE_DATA_CHATS`, and `DATABASE_SAVE_DATA_HISTORIC`. This materially reduces Postgres write volume. Keep `DATABASE_SAVE_DATA_INSTANCE=true` and `DATABASE_SAVE_MESSAGE_UPDATE=true`.

### CACHE_REDIS_*

| Variable | Default | Description |
|---|---|---|
| `CACHE_REDIS_ENABLED` | `true` | Enable Redis. Default corrected to `true` to match the official `.env.example` and Mintlify docs (see also 03-api-reference.md §Key Environment Variables). The raw code pattern `=== 'true'` technically defaults to false when unset, but all official deployment artifacts treat `true` as the default. |
| `CACHE_REDIS_URI` | (required when enabled) | `redis://:password@host:6379/6` — use DB index 6 by convention |
| `CACHE_REDIS_TTL` | `604800` | Key TTL in seconds (default 7 days) |
| `CACHE_REDIS_PREFIX_KEY` | `evolution` | Prefix for all Redis keys |
| `CACHE_REDIS_SAVE_INSTANCES` | `false` | Store WhatsApp auth state in Redis. Set `true` for horizontal scaling (multiple API pods). |

### CACHE_LOCAL_*

| Variable | Default | Description |
|---|---|---|
| `CACHE_LOCAL_ENABLED` | `false` | Enable in-process LRU memory cache |
| `CACHE_LOCAL_TTL` | `86400` | TTL in seconds (24 hours) |

**QR pairing workaround:** Some operators report that disabling Redis (`CACHE_REDIS_ENABLED=false`) and enabling local cache (`CACHE_LOCAL_ENABLED=true`) resolves QR/pairing failures caused by resource contention during Curve25519 pre-key generation. Try this if QR codes fail silently or pairing completes but no messages arrive.

### WEBHOOK_*

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_GLOBAL_ENABLED` | `false` | Send all instance events to one global URL |
| `WEBHOOK_GLOBAL_URL` | — | Target URL (e.g. `https://solvetax-admin-prod.azurewebsites.net/api/v1/whatsapp/webhook`) |
| `WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS` | `false` | Append event name to URL path |
| `WEBHOOK_REQUEST_TIMEOUT_MS` | `30000` | Per-request HTTP timeout (30 s). Matches the value documented in 04-events-webhooks.md and 07-risks-compliance.md. |
| `WEBHOOK_RETRY_MAX_ATTEMPTS` | `10` | Max retries on delivery failure |
| `WEBHOOK_RETRY_INITIAL_DELAY_SECONDS` | `5` | Seconds before first retry |
| `WEBHOOK_RETRY_USE_EXPONENTIAL_BACKOFF` | `true` | Exponential backoff between retries |
| `WEBHOOK_RETRY_MAX_DELAY_SECONDS` | `300` | Backoff cap |
| `WEBHOOK_RETRY_JITTER_FACTOR` | `0.2` | Random jitter fraction per retry interval |
| `WEBHOOK_RETRY_NON_RETRYABLE_STATUS_CODES` | `400,401,403,404,422` | HTTP codes that stop retry immediately |

#### WEBHOOK_EVENTS_* — per-event enable flags

```dotenv
# High-value for SolveTax CRM integration
WEBHOOK_EVENTS_MESSAGES_UPSERT=true        # inbound messages (most important)
WEBHOOK_EVENTS_MESSAGES_UPDATE=true        # delivery/read receipts
WEBHOOK_EVENTS_CONNECTION_UPDATE=true      # session connect/disconnect
WEBHOOK_EVENTS_QRCODE_UPDATED=true         # QR rotation events

# Disable if not needed (reduces webhook volume)
WEBHOOK_EVENTS_APPLICATION_STARTUP=false
WEBHOOK_EVENTS_MESSAGES_SET=false
WEBHOOK_EVENTS_CONTACTS_SET=false
WEBHOOK_EVENTS_CONTACTS_UPSERT=false
WEBHOOK_EVENTS_CONTACTS_UPDATE=false
WEBHOOK_EVENTS_PRESENCE_UPDATE=false
WEBHOOK_EVENTS_CHATS_SET=false
WEBHOOK_EVENTS_CHATS_UPSERT=false
WEBHOOK_EVENTS_CHATS_UPDATE=false
WEBHOOK_EVENTS_CHATS_DELETE=false
WEBHOOK_EVENTS_GROUPS_UPSERT=false
WEBHOOK_EVENTS_GROUPS_UPDATE=false
WEBHOOK_EVENTS_GROUP_PARTICIPANTS_UPDATE=false
WEBHOOK_EVENTS_REMOVE_INSTANCE=false
WEBHOOK_EVENTS_LOGOUT_INSTANCE=false
WEBHOOK_EVENTS_LABELS_EDIT=false
WEBHOOK_EVENTS_LABELS_ASSOCIATION=false
WEBHOOK_EVENTS_CALL=false
WEBHOOK_EVENTS_SEND_MESSAGE=true
WEBHOOK_EVENTS_SEND_MESSAGE_UPDATE=true
WEBHOOK_EVENTS_MESSAGES_EDITED=true
WEBHOOK_EVENTS_MESSAGES_DELETE=true
WEBHOOK_EVENTS_TYPEBOT_START=false
WEBHOOK_EVENTS_TYPEBOT_CHANGE_STATUS=false
WEBHOOK_EVENTS_ERRORS=false
```

### WEBSOCKET_*

| Variable | Default | Description |
|---|---|---|
| `WEBSOCKET_ENABLED` | `false` | Enable Socket.io server on the same port (8080) |
| `WEBSOCKET_GLOBAL_EVENTS` | `false` | Broadcast all instance events to all connected WS clients |
| `WEBSOCKET_ALLOWED_HOSTS` | `127.0.0.1,::1,::ffff:127.0.0.1` | Comma-separated allowed hosts; set `*` to allow all |

Enable WebSocket only if the SolveTax frontend will connect directly for real-time chat updates. For a webhook-first backend integration, leave this off.

### RABBITMQ_* / SQS_*

Not needed for the initial SolveTax integration. Leave all `RABBITMQ_ENABLED=false` and `SQS_ENABLED=false`. Kafka and NATS (`KAFKA_ENABLED=false`, `NATS_ENABLED=false`) likewise.

### S3_*

| Variable | Default | Description |
|---|---|---|
| `S3_ENABLED` | `false` | Enable S3-compatible media storage |
| `S3_ACCESS_KEY` | — | Access key for Azure Blob (via S3-compatible gateway) or MinIO |
| `S3_SECRET_KEY` | — | Secret key |
| `S3_BUCKET` | `evolution` | Bucket/container name |
| `S3_PORT` | `443` | Endpoint port (`9000` for MinIO default) |
| `S3_ENDPOINT` | `s3.domain.com` | Endpoint hostname |
| `S3_REGION` | `eu-west-3` | Region label; verify against current docs for Azure Blob S3 API |
| `S3_USE_SSL` | `true` | TLS for S3 connections |
| `S3_SKIP_POLICY` | `false` | Skip automatic bucket policy creation |

If SolveTax wants media files (images, audio, documents sent via WhatsApp) stored centrally, enable S3 and point it at the existing Azure Blob Storage account using its S3-compatible endpoint. Otherwise leave disabled; media arrives as base64 in webhook payloads.

### CONFIG_SESSION_PHONE_*

| Variable | Default | Description |
|---|---|---|
| `CONFIG_SESSION_PHONE_CLIENT` | `Evolution API` | Name shown in WhatsApp's "Linked Devices" list on the connected phone |
| `CONFIG_SESSION_PHONE_NAME` | `Chrome` | Browser identity declared to WhatsApp Web (`Chrome`, `Firefox`, `Edge`, `Opera`, `Safari`) |

**Known QR/pairing version issue:** Some forks and older deployment templates (including some Coolify templates) reference a `CONFIG_SESSION_PHONE_VERSION` variable set to `2.3000.1015901307`. This stale value causes silent QR generation failure or broken pairing-code flow (umbrella issue #2437). This variable is **not present in the main repo's current `.env.example`** — the WA Web version is determined by the pinned Baileys dependency. If you encounter QR failures and are using a third-party template, check whether this variable has been injected. Known-working replacement values reported by the community: `2.3000.1020885143` (mid-2025), `2.3000.1033773198` (2026). Prefer upgrading the Evolution API image to a version with an updated Baileys pin rather than patching this value manually.

### QRCODE_*

| Variable | Default | Description |
|---|---|---|
| `QRCODE_LIMIT` | `30` | Max QR codes generated per connect attempt before giving up |
| `QRCODE_COLOR` | `#175197` | Hex color for QR code modules |

### LOG_*

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `ERROR,WARN,DEBUG,INFO,LOG,VERBOSE,DARK,WEBHOOKS,WEBSOCKET` | Comma-separated levels. Reduce to `ERROR,WARN,INFO` in production. |
| `LOG_COLOR` | `true` | ANSI color in log output (disable if piping logs to a structured collector) |
| `LOG_BAILEYS` | `error` | Baileys library internal log level (`error`, `warn`, `debug`, `trace`) |

### CORS_*

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGIN` | `*` | Comma-separated allowed origins. Lock down in production (e.g. `https://solvetax-admin-prod.azurewebsites.net`). |
| `CORS_METHODS` | `GET,POST,PUT,DELETE` | Allowed HTTP methods |
| `CORS_CREDENTIALS` | `true` | Allow credentials in CORS requests |

### Instance management

| Variable | Default | Description |
|---|---|---|
| `DEL_INSTANCE` | `false` | Minutes of disconnection before auto-deleting a stale instance. `false` = never delete. Set a value (e.g. `60`) to prune sessions that have not reconnected. |
| `DEL_TEMP_INSTANCES` | `true` | Remove incomplete instances at startup. Deprecated in v2.2.0+; kept for compatibility. |
| `EVENT_EMITTER_MAX_LISTENERS` | `50` | Max Node.js event listeners per emitter |
| `LANGUAGE` | `en` | Response language: `en`, `pt`, `es`. Also governs the Whisper-1 speech-to-text transcription language; set to `en` or `hi` for SolveTax (see 05-integrations.md §3). |

### CLEAN_STORE_*

| Variable | Type | Default | Description |
|---|---|---|---|
| `CLEAN_STORE_MESSAGES` | boolean | `false` | Enable periodic purge of stored messages from the database |
| `CLEAN_STORE_CONTACTS` | boolean | `false` | Enable periodic purge of stored contacts |
| `CLEAN_STORE_CHATS` | boolean | `false` | Enable periodic purge of stored chat records |
| `CLEAN_STORE_CLEANING_INTERVAL` | integer (hours) | `7200` | How often (in hours) the cleanup job runs |

**Important for DPDP compliance:** These variables enable a periodic cleanup job but do **not** enforce a calendar-based retention period — they trigger a sweep at the configured interval without a date/age cutoff. To achieve DPDP-compliant hard deletion with a defined retention window, you must implement database-level scheduled jobs (e.g. `DELETE FROM messages WHERE created_at < NOW() - INTERVAL '90 days'`) in addition to these flags. See 07-risks-compliance.md §8 for the recommended approach.

### Telemetry / Observability

| Variable | Default | Description |
|---|---|---|
| `TELEMETRY_ENABLED` | `true` | Send anonymous usage telemetry to Evolution Foundation. Set `false` to opt out. |
| `SENTRY_DSN` | — | Sentry DSN for your own Sentry project |
| `PROMETHEUS_METRICS` | `false` | Expose `/metrics` in Prometheus format |
| `METRICS_AUTH_REQUIRED` | `true` | Require basic auth on `/metrics` |
| `METRICS_USER` | `prometheus` | Basic auth username for `/metrics` |
| `METRICS_PASSWORD` | — | Basic auth password |
| `METRICS_ALLOWED_IPS` | `127.0.0.1,...` | IPs allowed to scrape `/metrics` |

### Licensing (v2.4.0+ only)

**Does not apply to v2.3.7.** If upgrading to v2.4.0-rc1 or later:

| Variable | Default | Description |
|---|---|---|
| `EVOLUTION_OPERATOR_EMAIL` | — | Email pre-registered on the Evolution Foundation licensing portal. When set, the API calls `/v1/register/auto` at boot for headless activation. Without this, the API returns HTTP 503 on all non-health endpoints until manually activated via the browser-based flow at `/manager`. |
| `LICENSE_BASE_URL` | `https://license.evolutionfoundation.com.br` | Licensing server base URL |

The licensing server must be reachable at first boot. After initial activation, the API continues operating during outages (offline-tolerant). Issue #2534 tracks community concerns about headless/automated deployments. Verify current activation behavior against docs before upgrading to any v2.4.x release.

---

## 4. Nginx Reverse Proxy

The docker-compose above binds Evolution API to `127.0.0.1:8080` and the Manager UI to `127.0.0.1:3000`. Nginx terminates TLS and upgrades WebSocket connections (required for Socket.io and long-poll fallback).

### Upgrade map block (required)

Place this outside all `server` blocks to avoid the "unknown variable $connection_upgrade" error:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

### Evolution API virtualhost

```nginx
server {
    listen 80;
    server_name evo.solvetax.in;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name evo.solvetax.in;

    ssl_certificate     /etc/letsencrypt/live/evo.solvetax.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/evo.solvetax.in/privkey.pem;

    # Recommended TLS hardening
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_http_version 1.1;

        # WebSocket upgrade (Socket.io)
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;

        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        # Allow long-polling and large file uploads
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 100M;
    }
}
```

### Manager UI (optional, same server block or subdomain)

```nginx
location /manager/ {
    proxy_pass         http://127.0.0.1:3000/manager/;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade    $http_upgrade;
    proxy_set_header   Connection $connection_upgrade;
    proxy_set_header   Host       $host;
}
```

Or expose the manager on a separate subdomain (`manager.evo.solvetax.in`) pointing to port 3000.

### Cloudflare note

If the domain passes through Cloudflare with the proxy enabled (orange cloud), Cloudflare enforces a 100-second WebSocket timeout. QR code generation sessions can exceed this, resulting in 504 errors. Use **DNS-only mode** (grey cloud) for the Evolution API subdomain, or increase the WebSocket timeout under Cloudflare Network settings. TLS is then terminated at nginx directly.

### No nginx in current SolveTax prod

The current SolvetaxAdmin production setup has no nginx — Azure App Service's front-end proxy handles TLS for the main app. Nginx is only relevant if Evolution API is deployed on a separate Azure VM or if a future VM-based setup consolidates both services. When nginx is introduced in front of both services, update `ALLOWED_ORIGINS` in App Service settings and the `CORS_ORIGIN` env var for Evolution API to include each other's domains.

---

## 5. Resource Sizing

### Memory per WhatsApp session (Baileys channel)

Each active Baileys session maintains an open WebSocket, encryption key state, and a Node.js heap segment.

- Steady state with history sync disabled: ~25–50 MB heap per session
- Steady state with history sync enabled (`DATABASE_SAVE_DATA_HISTORIC=true`): ~80–120 MB per session
- High-traffic bursts during reconnect storms can momentarily spike 2–3x

**Known v2.3.0 bug (issue #1687):** Creating new instances could evict older instances from the in-process `waMonitor.waInstances` map, causing previously valid sessions to return 401. Fixed in v2.3.1+. Use v2.3.7 to avoid this.

### Recommended VM sizing by concurrent sessions

| Concurrent sessions | RAM | vCPUs | Notes |
|---|---|---|---|
| <5 (testing / pilot) | 1 GB | 1 | B1 equivalent; fits on existing App Service Plan |
| 5–30 (initial prod) | 2–4 GB | 2 | History sync off; webhook-only message handling |
| 30–100 | 8 GB | 4 | Consider disabling `DATABASE_SAVE_DATA_HISTORIC` |
| 100+ | 16–32 GB | 4+ | Horizontal scale; requires `CACHE_REDIS_SAVE_INSTANCES=true` and shared volume |

For SolveTax's initial deployment (1–2 WhatsApp numbers for the CRM team), the existing `solvetax-dev-plan` B1 slot has adequate headroom. A dedicated Azure Container Instance with 1–2 GB RAM is a cleaner choice to avoid competing with the main app for the B1's single vCPU.

### CPU spikes during reconnects

When WhatsApp updates its Web protocol or a network blip drops all sessions simultaneously, all Baileys instances attempt to reconnect at once ("thundering herd"). This can saturate available CPU and OOM-kill the container. Mitigations:

- Set `DEL_INSTANCE=60` (auto-delete stale sessions after 60 minutes) to reduce the session pool.
- Set resource limits in compose (as shown in §2: `memory: 2G`, `cpus: "1.5"`).
- Monitor container restart counts via `docker ps` or Azure Container metrics.

### Horizontal scaling (future)

If session count grows beyond a single container:

1. Set `CACHE_REDIS_SAVE_INSTANCES=true` — WhatsApp auth state moves to Redis instead of process memory.
2. All pods must share the same PostgreSQL database and Redis instance.
3. The `evolution_instances` Docker volume must be on shared network storage (Azure Files / NFS mount) accessible to all replicas.
4. The load balancer (nginx upstream or Azure Front Door) must use sticky sessions for WebSocket connections.

---

## 6. Upgrade Procedure and Prisma Migrations

### How migrations run

The container entrypoint runs `npx prisma migrate deploy` before starting the API server. Prisma auto-detects `DATABASE_PROVIDER` and applies any pending migrations from `prisma/postgresql/` (or `prisma/mysql/`). No manual migration step is required for normal patch upgrades.

Manual commands (for debugging or non-Docker installs):

```bash
npm run db:generate   # npx prisma generate
npm run db:deploy     # npx prisma migrate deploy
```

### Standard patch upgrade (v2.x.y to v2.x.z)

```bash
# 1. Pull new image
docker pull evoapicloud/evolution-api:v2.X.Z

# 2. Back up Postgres BEFORE bringing up the new image
docker exec evolution_postgres \
  pg_dump -U evolution evolution_db \
  > backup_pre_upgrade_$(date +%Y%m%d_%H%M%S).sql

# 3. Stop the API container (leave Postgres and Redis running)
docker-compose stop evolution_api

# 4. Update the image tag in docker-compose.yml
#    image: evoapicloud/evolution-api:v2.X.Z

# 5. Start with new image; Prisma migrations apply automatically
docker-compose up -d evolution_api

# 6. Watch logs for migration success
docker-compose logs -f evolution_api
# Look for: "All migrations have been successfully applied" or similar Prisma output
```

### Known migration issues

**v2.3.4 (issue #2069):** Migration `20250918182355_add_kafka_integration` hardcodes schema `public`. If `DATABASE_CONNECTION_URI` uses `?schema=evolution_api` (recommended), Prisma throws `P3009: relation 'public.Instance' does not exist` and the container fails to start.

- Workaround A: Pin to v2.3.3 until a fixed release is available.
- Workaround B: Use `?schema=public` in `DATABASE_CONNECTION_URI` (all Evolution data goes into the default public schema). Only viable if the Postgres database is dedicated to Evolution API — do not do this on the SolvetaxAdmin shared database.
- Always verify the migration status of the target version against the issue tracker before upgrading.

### v1 to v2 upgrade

There is no automated migration tool. v2.0.0 dropped MongoDB and introduced Prisma ORM. Steps:

1. Provision a fresh PostgreSQL database.
2. Configure `DATABASE_PROVIDER=postgresql` and `DATABASE_CONNECTION_URI`.
3. Deploy a fresh v2 container; Prisma creates the schema on first boot.
4. Recreate WhatsApp instances via the API (`POST /instance/create`).
5. Re-scan QR codes on each connected number. The `evolution_instances` volume may preserve session keys, but QR re-authentication is likely required.

---

## 7. Backup Considerations

Three assets to back up, in order of criticality:

| Asset | Docker volume | Recovery if lost |
|---|---|---|
| WhatsApp session files | `evolution_instances` | All instances must re-authenticate via QR code. **Most critical.** |
| PostgreSQL database | `postgres_data` | Message history, instance metadata, contacts lost. Re-sync on next connect. |
| Redis cache | `evolution_redis` | State rebuilt from DB on restart. Safest to lose. |

### PostgreSQL backup

```bash
# Full dump (run from host)
docker exec evolution_postgres \
  pg_dump -U evolution evolution_db \
  > /backups/evolution_db_$(date +%Y%m%d_%H%M%S).sql

# Restore
docker exec -i evolution_postgres \
  psql -U evolution evolution_db \
  < /backups/evolution_db_YYYYMMDD_HHMMSS.sql
```

### Session files backup (`evolution_instances`)

```bash
# Find volume mount path
docker volume inspect evolution_instances

# rsync to offsite or Azure Blob (example with azcopy)
azcopy sync /var/lib/docker/volumes/evolution_instances/_data \
  "https://<storage-account>.blob.core.windows.net/<container>/evolution-instances<SAS>"
```

### Redis backup

```bash
# Trigger background save
docker exec evolution_redis redis-cli -a "$REDIS_PASSWORD" BGSAVE

# Copy dump.rdb off the container
docker cp evolution_redis:/data/dump.rdb ./redis-backup-$(date +%Y%m%d).rdb
```

### Backup schedule recommendation

- `evolution_instances` volume: hourly rsync to Azure Blob. Any gap means re-QR on all sessions.
- Postgres: daily `pg_dump`, retained for 14 days.
- Redis: weekly `BGSAVE` + copy. Losing it requires only a container restart to rebuild from DB.

---

## 8. SolveTax-Specific Decisions

### Postgres: separate database, same server

Use a **separate PostgreSQL database** (not a separate schema on the SolvetaxAdmin managed database) for Evolution API.

- Rationale: Evolution API's Prisma migrations apply automatically to the `evolution_api` schema within the database; if run against the SolvetaxAdmin `solvetax` schema they would create schema-name conflicts. Keeping a dedicated `evolution_db` database provides clean access control and independent backup/restore.
- Option A (simpler): Add an `evolution_db` database to the existing Azure Database for PostgreSQL Flexible Server. Grant a separate `evolution` user access to only that database. This shares the managed Postgres SKU's compute.
- Option B (isolated): Spin up the `evolution_postgres` container in the compose file (as shown in §2). Self-managed; appropriate for an Azure VM deployment.

For the initial B1 App Service Plan deployment, Option A is preferred — no additional VM needed and backups are handled by Azure's managed Postgres.

### Redis: separate instance or dedicated DB index

The SolvetaxAdmin backend uses Redis (env vars `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`). Evolution API's Redis traffic (session state, cache) can coexist on the same Redis instance using a different **database index**.

- Current SolvetaxAdmin convention: verify which DB indices are in use in the backend code.
- Evolution API defaults to DB index 6 (`CACHE_REDIS_URI=redis://host:6379/6`). Use index 6 if unused, or pick another free index.
- Set `CACHE_REDIS_PREFIX_KEY=evolution` to namespace all keys.
- Do not share the Redis instance if you later enable `CACHE_REDIS_SAVE_INSTANCES=true` (scales horizontally) — high key volume from WhatsApp auth state could evict SolvetaxAdmin cache. In that case, use a separate Redis instance or Azure Cache for Redis tier.

### Deployment: same VM vs. separate

**Initial recommendation: separate Azure Container Instance (ACI).**

- The current SolvetaxAdmin prod runs on Azure App Service (`solvetax-dev-plan`, B1 Linux). Evolution API is a Node.js process with potentially high memory consumption.
- Adding Evolution API as a second container on the B1 plan risks starving the main FastAPI app during WhatsApp reconnect storms.
- Azure Container Instance is cheap for a single-container stateful workload; it can be attached to the same VNet for private communication.
- If budget requires sharing: add Evolution API as a second App Service on the existing `solvetax-dev-plan`. Set `WEBSITES_PORT=8080`. The two apps are isolated at the container level but share the B1's single vCPU.

### Port allocation

| Service | Internal port | Host binding |
|---|---|---|
| SolvetaxAdmin FastAPI | 8000 | Azure App Service (managed) |
| Evolution API | 8080 | `127.0.0.1:8080` (nginx terminates externally) |
| Evolution Manager UI | 3000 | `127.0.0.1:3000` (optional nginx path) |
| Evolution Postgres | 5432 (container) | `127.0.0.1:5433` (host, if VM deployment) |
| Evolution Redis | 6379 (container) | `127.0.0.1:6380` (host, if VM deployment) |

Non-standard host ports (5433, 6380) avoid conflicts if the host already runs Postgres or Redis for other services.

### Secrets handling consistent with SolvetaxAdmin `.env` pattern

SolvetaxAdmin backend env vars are injected via Azure App Service application settings (not stored in git). Follow the same pattern for Evolution API:

**If on Azure App Service:** configure all `.env` values as App Service application settings via `az webapp config appsettings set`. Use the existing `deploy/azure-appservice/build-app-settings.py` script pattern — write an equivalent script that reads `evolution.env` and outputs the JSON for `az webapp config appsettings set --settings @file`.

**If on Azure Container Instance or VM:** store the `.env` file in Azure Key Vault as a secret, pull it at deploy time via a managed identity, and write it to the host before `docker-compose up`. Never commit the `.env` to git.

**New env vars to add to SolvetaxAdmin App Service** for the backend proxy:

| Variable | Value |
|---|---|
| `EVOLUTION_API_URL` | `https://evo.solvetax.in` (or internal ACI URL) |
| `EVOLUTION_API_KEY` | Same value as `AUTHENTICATION_API_KEY` in Evolution's `.env` |

These two variables are all the SolvetaxAdmin FastAPI backend needs to proxy WhatsApp send/receive calls to Evolution API. Keep `EVOLUTION_API_KEY` in Azure Key Vault; reference it as a Key Vault reference in App Service settings.

---

## 9. Sources

- https://github.com/evolution-foundation/evolution-api
- https://github.com/EvolutionAPI/evolution-api/blob/main/.env.example
- https://hub.docker.com/r/evoapicloud/evolution-api
- https://hub.docker.com/r/evoapicloud/evolution-api/tags
- https://deepwiki.com/EvolutionAPI/evolution-api/1.3-configuration
- https://deepwiki.com/EvolutionAPI/evolution-api/1.2-installation-and-deployment
- https://evolutionapi-evolution-api-90.mintlify.app/deployment/environment-variables
- https://github.com/evolution-foundation/evolution-api/releases
- https://github.com/EvolutionAPI/evolution-api/issues/1474
- https://github.com/EvolutionAPI/evolution-api/issues/1687
- https://github.com/EvolutionAPI/evolution-api/issues/2069
- https://github.com/EvolutionAPI/evolution-api/issues/2437
- https://github.com/EvolutionAPI/evolution-api/issues/2534
- https://github.com/coollabsio/coolify/issues/5976
- https://docs.evolutionfoundation.com.br/licensing/activation
- https://docs.evolutionfoundation.com.br/en/evolution-api
- https://wasenderapi.com/blog/evolution-api-in-production-architecture-guide-for-scaling-multi-tenant-saas
- https://doc.evolution-api.com/v2/en/install/docker
- https://doc.evolution-api.com/v2/en/env
- https://doc.evolution-api.com/v2/en/install/nginx
- https://senate.sh/apps/evolution-api
- https://mintlify.wiki/EvolutionAPI/evolution-api/deployment/docker
- https://github.com/EvolutionAPI/evolution-api/blob/main/CHANGELOG.md
- https://github.com/EvolutionAPI/evolution-api/issues/1010
- https://coolify.io/docs/services/evolution-api
- https://easypanel.io/docs/templates/evolutionapi
