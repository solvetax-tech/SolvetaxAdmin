# Deploy Docker container to Azure App Service (no VM)

Use **Azure App Service (Linux + Docker)** instead of a VM. App Service runs your **same GHCR image** — no nginx, no SSH, no docker-compose on a server.

Repo image: `ghcr.io/solvetax-tech/solvetaxadmin:dev`

---

## Architecture

```text
git push dev
  → GitHub Actions builds image → GHCR :dev
  → App Service pulls image → runs container on port 8000
  → Azure gives you HTTPS URL: https://solvetaxadmin-dev.azurewebsites.net
  → App talks to Postgres (Canada) + Redis (India) via outbound IPs
```

**You do NOT need:** VM, nginx, certbot, SSH keys for deploy (for this path).

---

## Part 1 — Create App Service (Portal)

### 1.1 Create Web App

1. Azure Portal → **App Services** → **+ Create** → **Web App** (first option only)
2. Fill in:

| Field | Dev value |
|-------|-----------|
| **Subscription** | Subscription 1 |
| **Resource group** | `solvetaxadmin-dev-rg` (same as before or new) |
| **Name** | `solvetaxadmin-dev` (must be globally unique → URL becomes `solvetaxadmin-dev.azurewebsites.net`) |
| **Publish** | **Docker Container** |
| **Operating System** | **Linux** |
| **Region** | **Canada Central** (near Postgres) |

3. **App Service Plan** → Create new:

| Field | Value |
|-------|--------|
| Name | `solvetaxadmin-dev-plan` |
| Pricing tier | **Basic B1** (~$13–15/mo) or **Premium v3 P0v3** if you need more RAM |

4. Click **Review + create** → **Create**

---

### 1.2 Point App Service to your Docker image

After the Web App is created:

1. Open **solvetaxadmin-dev** → **Deployment Center** (or **Settings → Deployment Center**)
2. **Source:** Container Registry
3. **Registry type:** **Other** (for GHCR)
4. Set:

| Field | Value |
|-------|--------|
| **Registry URL** | `https://ghcr.io` |
| **Image and tag** | `solvetax-tech/solvetaxadmin:dev` |
| **Username** | `solvetax-tech` |
| **Password** | GitHub PAT with `read:packages` |

5. **Save** — App Service pulls the image and starts the container.

> **First time:** Push to `dev` branch once so `:dev` image exists in GHCR (CI/CD Dev workflow already builds it).

---

### 1.3 Required App Service settings

**Settings → Environment variables** (Application settings) → add:

#### Container (required)

| Name | Value |
|------|--------|
| `WEBSITES_PORT` | `8000` |
| `WEBSITES_CONTAINER_START_TIME_LIMIT` | `600` |

#### From your project `.env` (copy each)

| Name | Your value |
|------|------------|
| `DB_HOST` | `solvetaxdbrestore1.postgres.database.azure.com` |
| `DB_PORT` | `5432` |
| `DB_NAME` | `postgres` |
| `DB_USER` | `solvetaxadmin` |
| `DB_PASSWORD` | *(your password)* |
| `DB_SCHEMA` | `solvetax` |
| `REDIS_HOST` | `solvetax-redi-s.redis.cache.windows.net` |
| `REDIS_PORT` | `6380` |
| `REDIS_PASSWORD` | *(no quotes)* |
| `JWT_SECRET` | *(your secret)* |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_EXPIRE_MINUTES` | `60` |
| `PUBLIC_API_KEY` | *(your key)* |
| `AZURE_STORAGE_CONNECTION_STRING` | *(your string)* |
| `AZURE_STORAGE_CONTAINER` | `gst-documents` |
| `AZURE_STORAGE_CONTAINER1` | `business-images` |
| `SMTP_SERVER` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_EMAIL` | *(your email)* |
| `SMTP_PASSWORD` | *(app password)* |
| `RUN_SCHEDULER` | `true` |
| `WORKERS` | `1` |
| `HOST` | `0.0.0.0` |
| `PORT` | `8000` |

Add OpenAI / MSG91 vars if you use them.

Click **Save** → App Service restarts.

---

### 1.4 Firewall — allow App Service to reach DB & Redis

App Service outbound IPs are **not** the same as a VM IP.

1. **App Service → Properties → Outbound IP addresses**
2. Copy **all** listed IPs (and note "Additional outbound IPs" if shown)
3. **PostgreSQL (Canada)** → Networking → add **each** outbound IP
4. **Redis (India)** → Firewall → add **each** outbound IP

Without this, the container starts then crashes (DB/Redis connection failed).

---

### 1.5 Test

Open:

```text
https://solvetaxadmin-dev.azurewebsites.net/health
```

Expected: `{"status":"ok"}`

**Logs if it fails:** App Service → **Log stream** or **Monitoring → Logs**

---

## Part 2 — GitHub Actions auto-deploy (optional)

After App Service exists, add GitHub secrets under environment **`development`**:

| Secret | Value |
|--------|--------|
| `AZURE_WEBAPP_NAME` | `solvetaxadmin-dev` |
| `AZURE_WEBAPP_PUBLISH_PROFILE` | Download from App Service → **Get publish profile** (full XML file contents) |

Use workflow: `.github/workflows/cd-dev-appservice.yml` (deploys container after build).

Or keep using **Deployment Center** — it can watch GHCR for new `:dev` tags.

---

## Part 3 — QA and Prod (later)

| Env | Web App name | Image tag | GitHub environment |
|-----|--------------|-----------|-------------------|
| Dev | `solvetaxadmin-dev` | `:dev` | `development` |
| QA | `solvetaxadmin-qa` | `:qa` | `staging` |
| Prod | `solvetaxadmin-prod` | `:prod` | `production` |

Create **3 separate Web Apps** (or 3 slots on Premium plan). Each gets its own env vars and outbound IP firewall rules.

---

## VM vs App Service (what you skip)

| VM approach | App Service |
|-------------|-------------|
| Create VM, Docker, nginx, SSL | Azure handles HTTPS |
| SSH + `.env` on server | Portal **Environment variables** |
| `DEPLOY_SSH_KEY`, etc. | **Publish profile** or Deployment Center |
| `docker-compose.prod.yml` | Single container only |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Application Error 503 | Check Log stream; usually DB/Redis firewall |
| Container didn't start | Set `WEBSITES_PORT=8000` |
| Slow cold start | Normal on B1; increase plan or `WEBSITES_CONTAINER_START_TIME_LIMIT` |
| Pull failed | GHCR credentials in Deployment Center |
| Old UI | Restart app after new image push |

---

## Quick checklist

```
[ ] Create Web App → Docker Container → Linux → Canada Central
[ ] Deployment Center → GHCR image solvetax-tech/solvetaxadmin:dev
[ ] Environment variables (WEBSITES_PORT + all .env values)
[ ] Postgres + Redis firewall: all App Service outbound IPs
[ ] Open https://YOUR-APP.azurewebsites.net/health
[ ] git push origin dev (rebuild image if needed)
```
