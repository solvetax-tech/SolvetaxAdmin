# Environment variables & secrets map (dev)

## Azure VM — SSH section (when creating VM)

You only see **Generate new key pair** — that is OK:

| Field | Value |
|-------|--------|
| Authentication type | **SSH public key** |
| Username | `azureuser` |
| SSH public key source | **Generate new key pair** |
| SSH Key Type | **Ed25519** |
| Key pair name | `solvetaxadmindev_key` |
| Inbound ports | **22, 80, 443** |

When you click **Create**, Azure downloads **`solvetaxadmindev_key.pem`**.

Save that file — you need it for:
- SSH: `ssh -i solvetaxadmindev_key.pem azureuser@VM_IP`
- GitHub secret **`DEPLOY_SSH_KEY`**: paste full `.pem` contents

---

## Three places for config

| Place | What |
|-------|------|
| **VM `/opt/slovetax/.env`** | All backend runtime vars (copy from project `.env`) |
| **GitHub Environment `development`** | Deploy + build secrets only (7 keys) |
| **`frontend/.env`** | Local dev only (not on VM) |

---

## GitHub → Environments → `development` secrets

| Secret | Value source |
|--------|----------------|
| `DEPLOY_HOST` | Dev VM **public IP** (after VM created) |
| `DEPLOY_USER` | `azureuser` |
| `DEPLOY_PATH` | `/opt/slovetax` |
| `DEPLOY_SSH_KEY` | Full **`solvetaxadmindev_key.pem`** file |
| `DEPLOY_GHCR_TOKEN` | GitHub PAT with `read:packages` |
| `VITE_API_URL` | *(empty)* |
| `VITE_PUBLIC_API_KEY` | Same as `PUBLIC_API_KEY` in `.env` |

---

## Project `.env` — status for dev VM

### Already filled (copy as-is to VM)

- PostgreSQL: `DB_*`
- Redis: `REDIS_*`
- Auth: `JWT_*`, `PUBLIC_API_KEY`
- Blob: `AZURE_STORAGE_*`
- SMTP: `SMTP_*`
- OpenAI: `AZURE_OPENAI_*`
- App: `HOST`, `PORT`, `WORKERS`, `RUN_SCHEDULER`
- Docker: `GHCR_IMAGE`

### You must set / verify

| Variable | Action |
|----------|--------|
| `DOMAIN` | Set to your dev hostname, e.g. `dev.solvetax.in` — **DNS A record → VM IP** before SSL |
| `CERTBOT_EMAIL` | Email for Let's Encrypt (set in `.env`) |

### Optional / dummy (OK for dev)

| Variable | Status |
|----------|--------|
| `MSG91_*` | Dummy values — SMS won't work until real keys |

---

## After VM is running

```bash
# On VM
cd /opt/slovetax
nano .env          # paste same content as project .env
bash deploy/azure-vm/setup-prod.sh
# After DNS:
bash deploy/azure-vm/init-letsencrypt.sh
```

```powershell
# On PC — trigger deploy
git push origin dev
```
