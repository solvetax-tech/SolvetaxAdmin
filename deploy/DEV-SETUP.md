# Dev environment setup (do this first)

Repo: **https://github.com/solvetax-tech/SolvetaxAdmin**

Do **dev** completely before **qa** (staging) and **prod**.

---

## Branch → environment map

| Git branch | GitHub Environment | Docker tag | Server | When |
|------------|---------------------|------------|--------|------|
| `dev` | `development` | `:dev` | **Dev VM** | **Start here** |
| `qa` | `staging` | `:qa` | QA VM | After dev works |
| `main` | `production` | `:prod` | Prod VM | Last |

Workflows: `ci.yml`, `cd-dev.yml`, `cd-qa.yml`, `cd-prod.yml`

Image base: `ghcr.io/solvetax-tech/solvetaxadmin`

---

## Part 1 — GitHub (before VM)

### 1.1 Enable Actions

**Settings → Actions → General** → Workflow permissions → **Read and write**

### 1.2 Create environment: `development`

**Settings → Environments → New environment** → name: **`development`**

(No approval required for dev.)

### 1.3 Add secrets under `development`

**Settings → Environments → development → Add secret**

| Secret | Value | Notes |
|--------|--------|--------|
| `DEPLOY_HOST` | Dev VM public IP | Add **after** VM is created |
| `DEPLOY_USER` | `azureuser` | SSH username |
| `DEPLOY_SSH_KEY` | Full private key PEM | See §1.4 |
| `DEPLOY_PATH` | `/opt/slovetax` | App folder on VM |
| `DEPLOY_GHCR_TOKEN` | GitHub PAT | `read:packages` — see §1.5 |
| `VITE_API_URL` | *(empty)* | Same-origin prod |
| `VITE_PUBLIC_API_KEY` | From `frontend/.env` | Build-time only |

**Do NOT put here:** `DB_PASSWORD`, `JWT_SECRET`, `REDIS_PASSWORD` → those go on the **VM `.env` only**.

### 1.4 Generate SSH key (your PC)

```powershell
ssh-keygen -t ed25519 -C "solvetax-dev" -f $env:USERPROFILE\.ssh\solvetax_dev
```

| File | Use |
|------|-----|
| `solvetax_dev.pub` | Paste into Azure VM when creating VM |
| `solvetax_dev` (private) | GitHub secret `DEPLOY_SSH_KEY` — copy entire file |

### 1.5 Create GitHub PAT for `DEPLOY_GHCR_TOKEN`

1. GitHub profile → **Settings → Developer settings → Personal access tokens**
2. Create token with **`read:packages`**
3. Paste into **`development`** environment secret `DEPLOY_GHCR_TOKEN`

---

## Part 2 — Azure Dev VM

### 2.1 Create VM (Portal)

**Create a resource → Virtual machine**

| Field | Dev value |
|-------|-----------|
| Resource group | `solvetax-dev-rg` |
| Name | `solvetax-dev-vm` |
| Image | Ubuntu 22.04 LTS |
| Size | Standard_B2s (2 vCPU, 4 GB) |
| Auth | SSH public key → paste `solvetax_dev.pub` |
| Inbound ports | **22, 80, 443** |

After create → copy **Public IP address** → add to GitHub secret **`DEPLOY_HOST`**.

### 2.2 Networking (NSG firewall)

Azure Portal → VM → **Networking** → confirm inbound rules:

| Port | Purpose |
|------|---------|
| 22 | SSH (you + GitHub Actions deploy) |
| 80 | HTTP + Let's Encrypt |
| 443 | HTTPS users |

**Outbound:** VM must reach Azure Postgres, Redis, Blob (default allow outbound is OK).

### 2.3 Database & Redis firewall (critical)

Postgres and Redis **block all IPs by default**.

Azure Portal → **PostgreSQL** → Networking / Firewall:

- Add rule: **Dev VM public IP**

Azure Portal → **Redis** → Firewall:

- Add **Dev VM public IP**

Use a **dev database** (or separate schema). Do not point dev VM at production DB.

---

## Part 3 — Bootstrap Dev VM (SSH)

### 3.1 Connect

```powershell
ssh -i $env:USERPROFILE\.ssh\solvetax_dev azureuser@YOUR_DEV_VM_IP
```

### 3.2 Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Log out and SSH back in.

```bash
sudo apt-get update
sudo apt-get install -y git gettext-base curl
```

### 3.3 Clone repo

```bash
sudo mkdir -p /opt/slovetax
sudo chown $USER:$USER /opt/slovetax
cd /opt/slovetax
git clone https://github.com/solvetax-tech/SolvetaxAdmin.git .
```

### 3.4 Create VM `.env` (runtime secrets)

```bash
cp .env.example .env
nano .env
```

Copy values from your **local root `.env`** (backend). Set at minimum:

```env
GHCR_IMAGE=ghcr.io/solvetax-tech/solvetaxadmin

DB_HOST=...
DB_USER=...
DB_PASSWORD=...
DB_NAME=...
REDIS_HOST=...
REDIS_PASSWORD=...
JWT_SECRET=...
AZURE_STORAGE_CONNECTION_STRING=...
SMTP_SERVER=...
SMTP_EMAIL=...
SMTP_PASSWORD=...

DOMAIN=dev.yourdomain.com
CERTBOT_EMAIL=admin@yourdomain.com
RUN_SCHEDULER=true
```

Save and exit.

### 3.5 DNS (optional but recommended for HTTPS)

At your domain registrar:

| Type | Name | Value |
|------|------|--------|
| A | `dev` | Dev VM public IP |

Wait 5–30 min, then verify: `nslookup dev.yourdomain.com`

### 3.6 First start on VM

```bash
cd /opt/slovetax
bash deploy/azure-vm/setup-prod.sh
```

After DNS works:

```bash
bash deploy/azure-vm/init-letsencrypt.sh
```

### 3.7 Manual test pull (before CI deploy)

```bash
echo YOUR_PAT | docker login ghcr.io -u solvetax-tech --password-stdin
bash deploy/azure-vm/deploy-from-ghcr.sh dev
curl -fsS http://127.0.0.1/health
```

---

## Part 4 — Deploy via GitHub (dev branch)

### 4.1 Push to `dev`

On your PC:

```powershell
git checkout dev
git pull origin dev
# make changes...
git add .
git commit -m "feat: my change"
git push origin dev
```

### 4.2 What happens automatically

```text
push dev
  → CD Dev workflow
  → build image ghcr.io/solvetax-tech/solvetaxadmin:dev
  → SSH to Dev VM
  → pull + docker compose up
  → health check /health
```

Watch: **https://github.com/solvetax-tech/SolvetaxAdmin/actions** → **CD Dev**

### 4.3 Verify

- Browser: `https://dev.yourdomain.com` (or `http://VM_IP` before SSL)
- Health: `https://dev.yourdomain.com/health` → `{"status":"ok"}`

---

## Part 5 — Dev checklist

```
GitHub
[ ] Actions read/write enabled
[ ] Environment "development" created
[ ] All 7 secrets added (DEPLOY_HOST after VM)

Azure VM
[ ] Dev VM created (Ubuntu, B2s)
[ ] NSG: 22, 80, 443 open
[ ] Postgres firewall: dev VM IP
[ ] Redis firewall: dev VM IP

VM bootstrap
[ ] Docker installed
[ ] Repo at /opt/slovetax
[ ] .env filled (DB, Redis, JWT, Blob, DOMAIN)
[ ] setup-prod.sh run
[ ] (Optional) DNS + init-letsencrypt.sh

Deploy
[ ] git push origin dev
[ ] CD Dev green in Actions
[ ] Site loads + login works
```

---

## Part 6 — QA and prod (later)

When dev is stable, repeat the **same steps** with different names:

### QA (staging) — branch `qa`

| Item | QA value |
|------|----------|
| GitHub Environment | `staging` |
| Branch | `qa` |
| Image tag | `:qa` |
| VM | Separate QA VM |
| DNS | `qa.yourdomain.com` |
| Workflow | `cd-qa.yml` |

Secrets: same 7 names under **Environments → staging** (QA VM IP in `DEPLOY_HOST`).

```powershell
git checkout qa
git push origin qa
```

### Production — branch `main`

| Item | Prod value |
|------|------------|
| GitHub Environment | `production` |
| Branch | `main` |
| Image tag | `:prod` |
| VM | Separate prod VM |
| DNS | `app.yourdomain.com` |
| Workflow | `cd-prod.yml` |

Add **required reviewers** on `production` environment before going live.

---

## Troubleshooting (dev)

| Problem | Fix |
|---------|-----|
| CD Dev deploy fails SSH | Check `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` |
| `pull` denied | Set `DEPLOY_GHCR_TOKEN`; or make GHCR package public |
| Container restarts | Bad `.env` or DB/Redis firewall missing VM IP |
| SSL fails | DNS must point to VM; port 80 open |
| Old UI after deploy | Hard refresh; confirm `:dev` tag pulled |

---

## Quick command reference (dev VM)

```bash
cd /opt/slovetax
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f solvetax-api
bash deploy/azure-vm/deploy-from-ghcr.sh dev
```
