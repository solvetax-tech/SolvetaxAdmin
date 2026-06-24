# Solvetax CI/CD — dev + prod (from scratch)

> **Setting up dev first?** Step-by-step: **[DEV-SETUP.md](./DEV-SETUP.md)** (secrets, VM, networking, deploy).

Monorepo: **FastAPI backend + React (Vite) frontend** → one Docker image → **nginx + HTTPS** on each Azure VM.

| Branch | CI | CD | Image tag | Server |
|--------|----|----|-----------|--------|
| `dev` | ✅ | Auto deploy | `:dev` | Dev VM |
| `qa` | ✅ | Auto deploy | `:qa` | QA VM (staging) |
| `main` / `prod` | ✅ | Auto deploy* | `:prod`, `:latest` | Prod VM |
| PR → `dev`/`main` | ✅ build only | — | — | — |

\*Add **required reviewers** on GitHub Environment `production` to approve prod deploys.

Workflows:

| File | Trigger |
|------|---------|
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | PR + push (build check) |
| [`.github/workflows/cd-dev.yml`](../.github/workflows/cd-dev.yml) | Push to `dev` |
| [`.github/workflows/cd-qa.yml`](../.github/workflows/cd-qa.yml) | Push to `qa` |
| [`.github/workflows/cd-prod.yml`](../.github/workflows/cd-prod.yml) | Push to `main` or `prod` |

---

## Architecture

```text
Developer → git push
         → GitHub Actions (build frontend + backend in Docker)
         → GHCR (ghcr.io/<owner>/<repo>:dev | :prod)
         → SSH to Azure VM
         → docker compose pull + up
         → nginx (443) → solvetax-api → Postgres / Redis / Blob
```

**One image** contains backend + built `frontend/dist`. No separate frontend container.

---

## Part A — One-time setup (you do once)

### A1. GitHub repository

1. Create repo on GitHub (or push existing code).
2. Create branches:
   ```bash
   git checkout -b dev
   git push -u origin dev
   git checkout main   # or prod
   git push -u origin main
   ```
3. **Settings → Actions → General** → Workflow permissions: **Read and write**.

### A2. GitHub Environments

**Settings → Environments** → create two:

| Environment | Purpose |
|-------------|---------|
| `development` | Dev VM deploy |
| `production` | Prod VM deploy (optional: **Required reviewers**) |

Each environment gets its **own secrets** (same names, different values).

### A3. GitHub secrets (per environment)

**Settings → Environments → development → Add secret**

| Secret | Example / notes |
|--------|-----------------|
| `DEPLOY_HOST` | Dev VM public IP |
| `DEPLOY_USER` | `azureuser` |
| `DEPLOY_SSH_KEY` | Full private PEM key |
| `DEPLOY_PATH` | `/opt/slovetax` |
| `DEPLOY_GHCR_TOKEN` | GitHub PAT with `read:packages` |
| `VITE_API_URL` | Usually **empty** (same origin) |
| `VITE_PUBLIC_API_KEY` | Public marketing key (optional) |

Repeat the **same secret names** under **production** with **prod VM** values.

`GITHUB_TOKEN` is automatic for pushing images to GHCR.

### A4. Azure — two VMs (recommended)

| | Dev VM | Prod VM |
|--|--------|---------|
| Size | B2s (2 vCPU, 4 GB) | B2s or larger |
| OS | Ubuntu 22.04 | Ubuntu 22.04 |
| Ports | 22, 80, 443 | 22, 80, 443 |
| DNS | `dev.yourdomain.com` | `app.yourdomain.com` |

**Why two VMs:** dev experiments never break production.

### A5. Azure Postgres / Redis / Blob

| | Dev | Prod |
|--|-----|------|
| Database | Dev server or separate schema | Production DB |
| Firewall | Allow **dev VM IP** | Allow **prod VM IP** |
| Redis | Dev instance | Prod instance |

App **cannot start** without valid `DB_*` and `REDIS_*` in server `.env`.

### A6. Prepare each VM (repeat for dev + prod)

SSH into VM:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out and back in

sudo apt-get update
sudo apt-get install -y git gettext-base

sudo mkdir -p /opt/slovetax
sudo chown $USER:$USER /opt/slovetax
cd /opt/slovetax
git clone https://github.com/YOUR_USER/slovetax-1.git .
```

Create `.env` (never commit):

```bash
cp .env.example .env
nano .env
```

**Required in `.env` on every server:**

```env
GHCR_IMAGE=ghcr.io/YOUR_GITHUB_USER/slovetax-1

# Backend (use dev or prod Azure resources)
DB_HOST=...
DB_PASSWORD=...
REDIS_HOST=...
JWT_SECRET=...
AZURE_STORAGE_CONNECTION_STRING=...
# ... see .env.example

# SSL (after DNS points to this VM)
DOMAIN=dev.yourdomain.com          # or app.yourdomain.com on prod
CERTBOT_EMAIL=admin@yourdomain.com

RUN_SCHEDULER=true                 # set false on dev if you want
```

First-time stack (HTTP):

```bash
bash deploy/azure-vm/setup-prod.sh
```

HTTPS (after DNS A record → VM IP):

```bash
bash deploy/azure-vm/init-letsencrypt.sh
```

Cron for cert renewal:

```bash
crontab -e
# 0 3 * * * cd /opt/slovetax && bash deploy/azure-vm/ssl-renew.sh >> /var/log/solvetax-ssl-renew.log 2>&1
```

### A7. DNS

| Type | Name | Value |
|------|------|--------|
| A | `dev` | Dev VM IP |
| A | `app` | Prod VM IP |

### A8. GHCR package access

After first CI run, image appears under **Packages**.

- **Public package:** VM can pull without login.
- **Private:** PAT in `DEPLOY_GHCR_TOKEN` (Actions logs in over SSH before pull).

---

## Part B — Day-to-day development flow

```text
feature branch → PR to dev → CI runs (build test)
              → merge to dev → CD Dev: build :dev → deploy dev VM
              → test on https://dev.yourdomain.com
              → PR dev → main → CI runs
              → merge to main → CD Prod: build :prod → deploy prod VM
```

### Commands locally before pushing

```bash
# Backend + frontend dev (no Docker)
python -m backend.main          # :8000
cd frontend && npm run dev      # :5174

# Or full stack in Docker
docker compose up --build
curl http://localhost:8000/health
```

### Push to dev (auto deploy)

```bash
git checkout dev
git add .
git commit -m "feat: something"
git push origin dev
```

GitHub → **Actions** → **CD Dev** → should be green → check dev site.

### Push to prod

```bash
git checkout main
git merge dev
git push origin main
```

GitHub → **Actions** → **CD Prod** → deploys prod (or waits for approval if configured).

Manual prod deploy without merge:

**Actions → CD Prod → Run workflow** (uncheck “skip deploy” if you add that option).

---

## Part C — What each workflow does

### CI (`ci.yml`)

- Runs on PR and push to `dev`, `main`, `prod`
- `npm ci` + `npm run build` (frontend)
- `docker build` (no push) — validates Dockerfile

### CD Dev (`cd-dev.yml`)

- Trigger: push to **`dev`**
- Builds image with `VITE_*` from **development** secrets
- Pushes `ghcr.io/.../slovetax-1:dev` and `:dev-<sha>`
- SSH → dev server → `remote-deploy.sh dev`

### CD Prod (`cd-prod.yml`)

- Trigger: push to **`main`** or **`prod`**
- Builds with **production** secrets
- Pushes `:prod`, `:latest`, `:<sha>`
- SSH → prod server → `remote-deploy.sh prod`

---

## Part D — Manual deploy on server

```bash
cd /opt/slovetax
echo YOUR_PAT | docker login ghcr.io -u YOUR_USER --password-stdin
bash deploy/azure-vm/deploy-from-ghcr.sh dev    # or prod
```

---

## Part E — Checklist

### GitHub

- [ ] Branches `dev` and `main` (or `prod`) exist
- [ ] Environments `development` and `production` created
- [ ] All deploy secrets set **per environment**
- [ ] Actions enabled with read/write packages
- [ ] (Optional) Required reviewers on `production`

### Azure

- [ ] Dev VM + Prod VM running
- [ ] NSG: 22, 80, 443 open
- [ ] Postgres + Redis firewalls include both VM IPs
- [ ] DNS for dev + prod domains
- [ ] `.env` on each VM with correct DB/Redis/secrets
- [ ] SSL initialized on both VMs

### First deploy

- [ ] Push to `dev` → CI green → CD Dev green → `https://dev.../health` OK
- [ ] Merge to `main` → CD Prod green → `https://app.../health` OK
- [ ] Login + one CRM flow on each environment

---

## Part F — Troubleshooting

| Problem | Fix |
|---------|-----|
| CI fails on frontend build | Run `cd frontend && npm run build` locally |
| CD fails SSH | Check `DEPLOY_HOST`, key, user, VM port 22 |
| `pull` denied | Set `DEPLOY_GHCR_TOKEN`; make package public or login |
| App crash on start | Wrong `DB_HOST` / firewall on Postgres |
| Old UI after deploy | Hard refresh; verify new `:dev` / `:prod` tag pulled |
| Prod deploy too automatic | Add required reviewers on `production` environment |

---

## Part G — Build-time vs runtime env

| Variable | When | Where |
|----------|------|--------|
| `VITE_API_URL`, `VITE_PUBLIC_API_KEY` | Docker **build** | GitHub Environment secrets |
| `DB_*`, `JWT_*`, `REDIS_*`, Blob, SMTP | Container **run** | VM `.env` only |

Changing DB password → restart container.  
Changing `VITE_PUBLIC_API_KEY` → push to branch (new image build).
