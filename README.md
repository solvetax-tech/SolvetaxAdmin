# SolveTax (monorepo)

```
solvetax-1/
├── backend/          # FastAPI application (Python)
├── frontend/         # React + Vite UI
├── Dockerfile        # CI + production image
├── docker-compose.yml           # Local: API on :8000
├── docker-compose.prod.yml      # Prod: nginx + API (pull from GHCR)
├── deploy/DEPLOY.md             # Full deploy guide (GitHub Actions + Azure VM)
└── .env              # Backend secrets (not committed)
```

## Local development

## Production / CI-CD

Full **dev + prod branch pipeline** (GitHub Actions → GHCR → Azure VM):

→ **[deploy/GUIDE.md](deploy/GUIDE.md)** — beginner guide (DevOps terms explained).  
→ **[deploy/DEPLOY.md](deploy/DEPLOY.md)** — checklist once you understand the flow.

| Branch | Deploy target | Image tag |
|--------|---------------|-----------|
| `dev` | Dev VM (auto) | `:dev` |
| `main` / `prod` | Prod VM (auto*) | `:prod`, `:latest` |

Workflows: `.github/workflows/ci.yml`, `cd-dev.yml`, `cd-prod.yml`

\*Add required reviewers on GitHub Environment `production` to gate prod deploys.

**Backend** (port 8000):

```bash
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
python -m backend.main
```

**Frontend** (port 5174):

```bash
cd frontend && npm install && npm run dev
```

**Docker local:**

```bash
docker compose up --build
# http://localhost:8000/health
```
.