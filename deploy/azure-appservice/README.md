# SolveTax Admin — Dev Deployment (Azure)

How the `dev` branch gets from your laptop to a running URL, and every Azure
piece behind it. Read top to bottom the first time; after that it's a reference.

> **No secrets live in this file.** It records resource *names* and *IDs* (which
> are identifiers, not credentials). Passwords, keys, and connection strings live
> only in GitHub Secrets and Azure App Service settings — never here, never in git.

---

## 1. The one idea that explains everything: a single container

This app is **not** a separate frontend server and backend server. It is **one
container** that does both jobs.

Why: [`backend/frontend_static.py`](../../backend/frontend_static.py) makes
FastAPI serve the built React files. So the same Python process answers both:

| Browser asks for | FastAPI returns |
| --- | --- |
| `/`, `/customers`, `/dashboard` | `index.html` (the React app) |
| `/assets/index-abc.js` | the built JS/CSS files |
| `/api/v1/...` | the real API |

```
                    ┌─────────────────────────────────────┐
   browser  ─────►  │      ONE container, port 8000        │
                    │                                       │
   /            ──► │  FastAPI ──► frontend_static ─► HTML  │
   /api/v1/...  ──► │  FastAPI ──► your API routes          │
                    └─────────────────────────────────────┘
```

**Consequence:** there is no "connect the frontend port to the backend port,"
no CORS, no cross-origin. The browser is already on the same origin as the API.
This is why the frontend's `VITE_API_URL` is left empty in production — the app
calls `/api/...` as a relative path on the same host.

---

## 2. The two `.env` files are read at completely different times

This is the most common thing people get wrong. The two env files are NOT the
same kind of thing.

```
frontend/.env   ──read by Vite during `npm run build`──►  values BAKED into the JS
                  (BUILD time, happens once in CI)          then the file is meaningless

.env (root)     ──read by Python every time app starts──►  lives in server memory only
                  (RUN time, happens on the server)         never sent to a browser
```

- **`frontend/.env` → build time.** Vite does find-and-replace:
  `import.meta.env.VITE_PUBLIC_API_KEY` literally becomes `"the-value"` inside
  the shipped JS. **Anything with a `VITE_` prefix is public** — visible in the
  browser with F12. Never put a real secret there.
  - `VITE_API_URL` — left **unset** in prod (same-origin, relative URLs work).
  - `VITE_PUBLIC_API_KEY` — needed, but it's a soft gate, not a secret.
- **`.env` (root) → run time.** `DB_PASSWORD`, `JWT_SECRET`, storage keys, SMTP,
  MSG91… the server reads these on startup via `python-dotenv`. In Azure these
  come from **App Service settings**, injected as environment variables when the
  container starts.

**The rule:**
> Browser needs it → GitHub Secret (baked at build).
> Only the server needs it → Azure App Service setting (injected at run).

That is why the backend `.env` does **not** go into GitHub — it would double the
places a secret can leak, for zero benefit.

---

## 3. The end-to-end flow (once CI exists)

```
you: git push origin develop
        │
        ▼
GitHub Actions (a fresh Ubuntu machine)  ← .github/workflows/deploy-develop.yml
  1. checkout code
  2. log in to Azure          ← GitHub Secret: AZURE_CREDENTIALS (the robot user)
  3. docker build             ← GitHub Secret: VITE_PUBLIC_API_KEY (baked into JS)
        stage 1: node  → npm run build → frontend/dist
        stage 2: python + backend/ + copy dist in
  4. docker push  → ACR       (solvetaxacrdev.azurecr.io/solvetax-admin:<git-sha>)
  5. tell the Web App to use the new image tag
        │
        ▼
App Service pulls the image from ACR   ← Web App's managed identity (AcrPull)
  starts: uvicorn backend.main:app --host 0.0.0.0 --port 8000
  reads secrets from App Service settings (NOT from the image)
        │
        ▼
browser → https://solvetax-admin-dev.azurewebsites.net   (everything, one origin)
```

---

## 4. What we created in Azure, and what each command does behind the scenes

### Resource map

| Resource | Name | What it is |
| --- | --- | --- |
| Subscription | `Subscription 1` (`b1c82378-…`) | the billing account |
| Resource group | `solvetax-dev-rg` | a folder holding it all; delete it = delete everything |
| Container registry (ACR) | `solvetaxacrdev` → `solvetaxacrdev.azurecr.io` | **stores** your Docker images |
| App Service plan | `solvetax-dev-plan` (Linux, B1) | the **VM** the container runs on |
| Web App | `solvetax-admin-dev` → `solvetax-admin-dev.azurewebsites.net` | the **running app** + its runtime settings |
| CI robot (service principal) | `gh-solvetax-dev` | identity GitHub Actions logs in as |

### The commands (in the order we ran them)

```bash
# Log in and pick the subscription
az login
az account set --subscription b1c82378-b429-4f6e-9afc-f4c13b1d4edf
```
*Behind the scenes:* stores a token locally so later commands are authenticated.

```bash
# The folder that holds everything
az group create --name solvetax-dev-rg --location centralindia
```
*Behind the scenes:* creates a logical container in Azure. No compute, no cost.

```bash
# Turn on the services this subscription will use (one-time per subscription)
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.Web
```
*Behind the scenes:* Azure subscriptions start with most services switched off.
"Registering a provider" flips the switch so you're allowed to create that
resource type. This is what fixed the `MissingSubscriptionRegistration` error.

```bash
# The image registry
az acr create --resource-group solvetax-dev-rg --name solvetaxacrdev --sku Basic
```
*Behind the scenes:* provisions a private Docker registry at
`solvetaxacrdev.azurecr.io`. `Basic` = cheapest tier, plenty for dev. It only
**stores** images — something else has to run them.

```bash
# The Linux VM the container runs on
az appservice plan create -g solvetax-dev-rg -n solvetax-dev-plan --is-linux --sku B1
```
*Behind the scenes:* reserves a small always-on Linux machine (~₹1,000/mo). This
is the compute. Nothing is deployed to it yet.

```bash
# The web app (with a throwaway placeholder image; CI replaces it)
az webapp create -g solvetax-dev-rg --plan solvetax-dev-plan -n solvetax-admin-dev \
  --deployment-container-image-name mcr.microsoft.com/appsvc/staticsite:latest
```
*Behind the scenes:* creates the app, assigns the URL
`solvetax-admin-dev.azurewebsites.net`, and points it at a public placeholder
image so it can boot before your real image exists.

```bash
# Tell App Service which port inside the container to send traffic to
az webapp config appsettings set -g solvetax-dev-rg -n solvetax-admin-dev \
  --settings WEBSITES_PORT=8000
```
*Behind the scenes:* your container listens on 8000 (Dockerfile `CMD`). Azure's
front-end proxy needs to know that. (Note: the `set` command prints values as
`null` — a display quirk; `... appsettings list` shows the real value.)

### The identity wiring (how the Web App pulls from ACR without a password)

```bash
# 1. Give the Web App its own identity
az webapp identity assign -g solvetax-dev-rg -n solvetax-admin-dev --query principalId -o tsv
#    → 55ccbbf1-e29e-4058-9046-695345c1cd51
```
*Behind the scenes:* creates a **system-assigned managed identity** — an Azure
identity tied to this web app's lifecycle. No password exists; Azure manages it.

```bash
# 2. Let that identity pull images from the ACR
az role assignment create --assignee 55ccbbf1-e29e-4058-9046-695345c1cd51 \
  --role AcrPull \
  --scope /subscriptions/b1c82378-.../registries/solvetaxacrdev
```
*Behind the scenes:* grants read/pull on the registry to that identity only.

```bash
# 3. Tell the Web App to use its identity when pulling
az webapp config set -g solvetax-dev-rg -n solvetax-admin-dev \
  --generic-configurations "{\"acrUseManagedIdentityCreds\": true}"
```
*Behind the scenes:* flips the app from "pull with a username/password" to "pull
using my managed identity." Fully passwordless. (The `\"` escaping is required in
Windows Command Prompt.)

```bash
# The CI robot (run earlier, right after ACR)
az ad sp create-for-rbac --name gh-solvetax-dev --role Contributor \
  --scopes /subscriptions/b1c82378-.../resourceGroups/solvetax-dev-rg --sdk-auth
```
*Behind the scenes:* creates a **service principal** (a robot user) scoped to the
whole dev resource group. Its JSON output (client id + secret + tenant) is what
GitHub uses to log in. Scoped to the RG so it can push to ACR **and** deploy to
the Web App with one credential.

---

## 5. Who is allowed to do what (two identities, don't confuse them)

```
  GitHub Actions ──(logs in as)──► gh-solvetax-dev  ──Contributor on RG──► push image, deploy
                                    (service principal, has a secret in GitHub)

  Running Web App ──(is)──► its managed identity     ──AcrPull on ACR──► pull image
                                    (no secret anywhere; Azure-managed)
```

- **CI robot** = pushes the image and tells the web app to update. Lives as
  `AZURE_CREDENTIALS` in GitHub.
- **Web app identity** = pulls the image at runtime. No secret stored anywhere.

---

## 6. Where each secret lives

| Secret | Lives in | Used when |
| --- | --- | --- |
| `AZURE_CREDENTIALS` (robot JSON) | GitHub Secrets | CI logs in to Azure |
| `VITE_PUBLIC_API_KEY` | GitHub Secrets | build (baked into JS) — *pending* |
| `DB_PASSWORD`, `JWT_SECRET`, storage, SMTP, MSG91, … | Azure App Service settings | app runtime — *pending upload* |

Backend `.env` → **App Service settings**, not GitHub.

---

## 7. Gotchas

### #1 — broken IPv6 (already hit)

Early on, every `az` command failed with
`ConnectionResetError(10054) 'connection forcibly closed'`.

**Cause:** the Wi-Fi advertised IPv6 but didn't route it. The PC tried the IPv6
address first (`curl` showed `Trying [2603:...]` → reset), never fell back to
IPv4. `az` has no force-IPv4 flag, so it hit the wall every time.

**Fix:** disable IPv6 on the Wi-Fi adapter
(`ncpa.cpl` → Wi-Fi → Properties → uncheck *Internet Protocol Version 6*). One
fix cleared every Azure endpoint at once. If `az` starts timing out again on a
new network, this is the first thing to check.

### #2 — `.dockerignore` must exclude `frontend/.env`

`frontend/.env` holds `VITE_API_URL=http://localhost:8000` for local dev, and
Vite bakes that value into the bundle at build time. A plain `.env` line in
`.dockerignore` matches ONLY the root `.env` — **not** `frontend/.env`. Without
the `**/.env` patterns, that localhost URL would ship in production and the
deployed app would try to call the visitor's own machine. The `**/.env` lines in
`.dockerignore` are the guardrail — do not remove them. (The original
`.dockerignore` on the old `dev` branch had this bug; it's fixed here.)

---

## 8. Status — what's done, what's left

**Done (Azure infrastructure):**
- [x] Azure CLI installed + logged in, subscription selected
- [x] Resource group `solvetax-dev-rg` (centralindia)
- [x] Providers registered (ContainerRegistry, Web)
- [x] ACR `solvetaxacrdev`
- [x] App Service plan `solvetax-dev-plan` (B1 Linux)
- [x] Web App `solvetax-admin-dev`, port 8000
- [x] Web App managed identity + AcrPull on ACR
- [x] `acrUseManagedIdentityCreds = true`
- [x] CI robot `gh-solvetax-dev` → `AZURE_CREDENTIALS` in GitHub

**Done (deploy files — on the `develop` branch):**
- [x] `Dockerfile` — two-stage (Node builds the UI → Python runs it + serves it)
- [x] `.dockerignore` — excludes **all** `.env` incl. `frontend/.env` (see gotcha #2 below)
- [x] `.github/workflows/deploy-develop.yml` — build → push to ACR → deploy, on push to `develop`

**Done — DEPLOYED & LIVE (2026-07-18):**
- [x] `VITE_PUBLIC_API_KEY` GitHub secret added
- [x] Backend `.env` uploaded to App Service settings (46 settings)
- [x] Pushed `develop` → CI built → pushed to ACR → deployed → verified healthy
- [x] Live at **https://solvetax-admin-dev.azurewebsites.net** (push to `develop` = auto-deploy)

**Left:**
- [ ] Rotate secrets exposed during setup (SP client secret + backend `.env` values)
- [ ] Lock Postgres + Redis firewalls to the app's outbound IPs (see §10)
- [ ] Delete the abandoned Canada-Central app `solvetaxadmindevweb` (+ its RG/plan)
- [ ] Custom domain (Hostinger CNAME + TXT → `hostname add` + free managed cert)
- [ ] Optional: enable Always On + HTTPS-only

---

## 9. Recommended runtime settings (add with the backend .env)

- `WORKERS=1` — `main.py` warns each worker opens its own DB pool; keep it low for
  Azure Postgres connection limits.
- `RUN_SCHEDULER` — `schedular.py` defaults it to `true`. If you ever scale past 1
  instance, every instance runs the scheduler and jobs fire twice. Keep 1 instance
  on B1, or run the scheduler separately.
- Enable **Always On** and **HTTPS Only** on the web app (both currently off).

---

## 10. Locking the DB (do this LAST, after the app is confirmed working)

```bash
# The FULL set of IPs the app can use — NOT `outboundIpAddresses` (only the current set)
az webapp show -g solvetax-dev-rg -n solvetax-admin-dev \
  --query possibleOutboundIpAddresses -o tsv
```

Add each IP to the Postgres firewall, confirm the app still connects, **then**
delete the allow-all rule. Using `possibleOutboundIpAddresses` (not
`outboundIpAddresses`) is critical — Azure rotates between the "possible" set when
it scales, and using the smaller list is the #1 way this silently breaks a week
later.

---

## 11. Two decisions baked in (why `develop`, why ACR)

**Deploy branch = `develop`.** The old `dev` branch was 12 commits behind `main`
and carried an incompatible GHCR-based deploy setup. Rather than untangle it,
`develop` was branched fresh from `main` (latest code) and given clean,
ACR-based deploy files. The pipeline triggers on push to `develop`. The old
`dev` branch is abandoned and safe to delete.

**Registry = Azure ACR (not GHCR).** The whole Azure setup — ACR, the Web App's
managed identity, AcrPull, and the `AZURE_CREDENTIALS` service principal — is
ACR-native. The workflow pushes to `solvetaxacrdev.azurecr.io` and the Web App
pulls with its managed identity. No registry password is stored anywhere. (The
old `dev` branch used GHCR + a publish profile — a different, now-unused path.)

feature → PR → develop → auto-deploy to DEV   (what we have now — keep it)
develop → PR to main → [CI gate: build + checks] → merge → deploy to PROD
