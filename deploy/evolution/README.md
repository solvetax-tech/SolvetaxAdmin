# Evolution API — Phase 0 Sandbox Runbook

Deploy a local Evolution API sandbox, scan a QR code, and validate basic send/receive
before any client data is involved.

---

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2) installed and running.
- **A spare WhatsApp number on a dedicated SIM.**
  > **NEVER use the main business number or any client-facing number.**
  > WhatsApp bans are account-level and permanent on first offence (68% Indian SMB ban
  > rate within 12 months — see `docs/evolution-api/07-risks-compliance.md §2`).
  > Use a fresh SIM registered under the SolveTax business identity for all automation.
- **Cost note:** Evolution API is Apache 2.0 licensed — no software cost.
  Baileys sends are free (unofficial WhatsApp Web protocol). You only pay for:
  compute (Docker Desktop on dev machine = free; Azure Container Instance ≈ ₹500–₹1,500/month)
  and the SIM/data plan for the spare number.

---

## Steps

### 1. Copy and configure the env file

```bash
cd deploy/evolution
cp .env.example .env
```

Open `.env` in an editor and set:

- `AUTHENTICATION_API_KEY` — generate a strong random value:
  ```bash
  openssl rand -hex 32
  ```
- `POSTGRES_PASSWORD` and `REDIS_PASSWORD` — generate separately with the same command.
- Update `DATABASE_CONNECTION_URI` to use the same `POSTGRES_PASSWORD` value you set above.
- Leave `SERVER_URL=http://localhost:8080` for local sandbox use.

### 2. Start the stack

```bash
docker compose up -d
```

The first run pulls images (~500 MB). Postgres and Redis start first; the Evolution API
container waits for them and then runs Prisma migrations automatically on boot.

Watch startup:
```bash
docker compose logs -f evolution_api
```

Look for a line confirming Prisma migrations applied and the API server listening on port 8080.
Wait until there are no error lines before proceeding.

### 3. Open the Evolution Manager UI

The Manager is embedded in the API container (no separate service needed). Navigate to:
```
http://localhost:8080/manager
```

Log in with your `AUTHENTICATION_API_KEY`. If the Manager route is unavailable in your
build, use the Swagger UI at `http://localhost:8080/docs` instead.

### 4. Create an instance named `primary`

> The instance name **must be `primary`** — it matches the `instance_name` seed row in the
> `wa_instance_config` table created by migration V002.

**Via Manager UI:** click "New Instance", set name to `primary`, leave integration as
`WHATSAPP-BAILEYS`, click Create.

**Via REST (alternative):**
```bash
curl -s -X POST http://localhost:8080/instance/create \
  -H "apikey: YOUR_AUTHENTICATION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"instanceName": "primary", "integration": "WHATSAPP-BAILEYS", "qrcode": true}'
```

### 5. Scan the QR code with your spare number

In the Manager UI, click the instance and choose "Connect" — a QR code appears.

Open WhatsApp on the spare phone → Settings → Linked Devices → Link a Device → scan.

> **Use QR code only.** Do NOT use pairing code — it connects but receives no events
> (GitHub #2215, open issue). See `docs/evolution-api/07-risks-compliance.md §9`.

The QR refreshes automatically up to 30 times (≈ 45 s each). If all 30 expire, restart
the connection: PUT `http://localhost:8080/instance/restart/primary`.

### 6. Verify CONNECTION state

```bash
curl -s http://localhost:8080/instance/connectionState/primary \
  -H "apikey: YOUR_AUTHENTICATION_API_KEY" | python3 -m json.tool
```

Expected response contains `"state": "open"`. If it shows `connecting` or `close`,
wait 30 seconds and retry — Baileys may still be negotiating the session.

---

## Smoke Test

Send a text message from the `primary` instance to your own test phone number
(include country code, no `+`; e.g. Indian number: `919876543210`):

```bash
curl -s -X POST http://localhost:8080/message/sendText/primary \
  -H "apikey: YOUR_AUTHENTICATION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"number": "919876543210", "text": "Evolution API Phase 0 smoke test"}' \
  | python3 -m json.tool
```

**Expect:** HTTP 201 with a response body containing a `key.id` field.
The message should appear on the recipient phone within a few seconds.

> **Endpoint reference:** `POST /message/sendText/{instance}` — doc 03 §5 Messages Controller.
> **Auth header:** `apikey` (not `Authorization: Bearer`) — doc 03 §0 preamble.

---

## Warm-Up Warning

> **NEW NUMBERS ARE HIGH-BAN-RISK. KEEP SANDBOX SENDS TO A HANDFUL.**

The warm-up table in `docs/evolution-api/07-risks-compliance.md §5` specifies:
- **Week 1:** manual phone use only — no automation, 0 automated sends.
- **Week 2:** begin automated sends only to previously-engaged numbers; max 10–20/day.
- The app-side daily cap of 50 (enforced in Phase 1) is not active yet in the sandbox.
  In this phase, **manually limit yourself to a few test messages total.**

WhatsApp's Layer 1 detection (protocol fingerprinting) fires before any message is sent.
Volume reduction does not prevent it — see `docs/evolution-api/07-risks-compliance.md §3`.

---

## Phase 0 Exit Criteria Checklist

Before proceeding to Phase 1, confirm all of the following:

- [ ] Instance connects and holds connection for 24 hours without manual intervention.
- [ ] Manual send and receive work end-to-end.
- [ ] Webhook delivers to a test endpoint with correct payload shape
      (use `ngrok` or `requestbin` to inspect the `MESSAGES_UPSERT` event).
- [ ] Container restart recovers session from persistent volume without QR re-scan
      (`docker compose restart evolution_api` then re-check connectionState).
- [ ] Prisma migrations show no pending items
      (`docker exec evolution_api npx prisma migrate status`).
- [ ] Manager UI accessible and `primary` instance visible.
- [ ] Memory headroom confirmed: monitor via `docker stats evolution_api` over 24 hours;
      peak must stay below 1.2 GB to leave headroom on B1 App Service Plan (1.75 GB total).
      If peak exceeds 1.2 GB, move to Azure Container Instance before Phase 1.

Full exit criteria and rollback procedure in `docs/evolution-api/08-rollout-plan.md` Phase 0 section.

---

## Where This Runs

| Environment | How |
|---|---|
| Local development | Docker Desktop on macOS or Linux (this guide) |
| Azure VM | Same compose file; bind ports to `127.0.0.1`; add nginx for TLS — see doc 02 §4 |
| Azure Container Instance | Single-container ACI + managed Postgres/Redis — preferred for prod isolation |

**Prod hardening** (nginx TLS, 127.0.0.1 port bindings, resource limits, backup schedule,
Azure Key Vault for secrets) is covered in `docs/evolution-api/02-deployment.md`.
