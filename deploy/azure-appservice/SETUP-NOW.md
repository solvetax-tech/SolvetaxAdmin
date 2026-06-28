# Finish dev App Service setup — do this now

App: **solvetaxadmindevweb**  
URL: **https://solvetaxadmindevweb.azurewebsites.net**

---

## Checklist

```
[ ] Step 1 — Environment variables in Azure
[ ] Step 2 — Postgres firewall (outbound IPs)
[ ] Step 3 — Redis firewall (outbound IPs)
[ ] Step 4 — Restart app + test /health
[ ] Step 5 — Open site + login
```

---

## Step 1 — Environment variables (Azure Portal)

1. Azure Portal → **solvetaxadmindevweb**
2. **Settings → Environment variables**
3. **App settings** tab → **+ Add** (or **Advanced edit** for bulk paste)

### Option A — Advanced edit (fastest)

Click **Advanced edit** → paste JSON array from `app-settings.dev.env`  
Or add each key manually from that file (same folder as this doc).

**File with all values:** `deploy/azure-appservice/app-settings.dev.env`

**Must include first:**

| Name | Value |
|------|--------|
| `WEBSITES_PORT` | `8000` |
| `WEBSITES_CONTAINER_START_TIME_LIMIT` | `600` |

**Do NOT add:** `DOMAIN`, `CERTBOT_EMAIL`, `GHCR_IMAGE` (not used on App Service).

4. Click **Save** → **Continue** (app restarts)

### Option B — PowerShell + Azure CLI

```powershell
az login
cd C:\Users\bhanu\Solvetax-Internal-backend\slovetax-1
.\deploy\azure-appservice\apply-app-settings.ps1
```

---

## Step 2 — PostgreSQL firewall

1. Azure Portal → **solvetaxdbrestore1** (your Postgres server)
2. **Settings → Networking** (or Connection security)
3. **App Service outbound IPs:**
   - Open **solvetaxadmindevweb → Properties → Outbound IP addresses**
   - Copy **every** IP (including "Additional outbound IP addresses" if listed)
4. Add each IP as firewall rule on Postgres
5. **Save**

---

## Step 3 — Redis firewall

1. Azure Portal → **solvetax-redi-s** (your Redis cache)
2. **Settings → Firewall** (or Private endpoint / Networking)
3. Add the **same App Service outbound IPs**
4. **Save**

---

## Step 4 — Verify container + health

1. **solvetaxadmindevweb → Overview → Browse**
2. Or open:

```text
https://solvetaxadmindevweb.azurewebsites.net/health
```

Expected: `{"status":"ok"}`

### If it fails

| Symptom | Check |
|---------|--------|
| Application Error / 503 | **Log stream** — usually DB/Redis firewall |
| Container pull error | **Deployment Center** — GHCR credentials + `:dev` tag exists |
| Timeout on start | `WEBSITES_CONTAINER_START_TIME_LIMIT=600` |
| Wrong port | `WEBSITES_PORT=8000` |

**Logs:** Monitoring → **Log stream**

**Container:** Deployment Center → confirm image `ghcr.io/solvetax-tech/solvetaxadmin:dev`

---

## Step 5 — Open UI

```text
https://solvetaxadmindevweb.azurewebsites.net
```

Login page = UI + backend connected (same domain).

---

## GitHub secrets

**Not required** for the app to run. Add later only for auto-deploy on `git push dev`.

---

## Variable count

**38 app settings** in `app-settings.dev.env` (includes WEBSITES_*).

---

## Security note

`app-settings.dev.env` contains secrets — **never commit to Git** (listed in `.gitignore`).
