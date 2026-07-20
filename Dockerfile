# syntax=docker/dockerfile:1
#
# One image, two jobs: it builds the React app AND runs the FastAPI server that
# serves it. See backend/frontend_static.py — FastAPI hands out frontend/dist as
# the SPA, so there is no separate frontend container and no CORS between them.
#
# Two stages:
#   1. frontend-build — Node builds frontend/ into static files (dist/)
#   2. runtime        — Python runs the API and serves those static files
# Node never ships in the final image; only the built dist/ is copied across.

# ---- Stage 1: build the React/Vite bundle -------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend

# Copy ONLY the manifests first. Docker caches layers; if these two files don't
# change, the slow `npm ci` below is reused from cache instead of re-running.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Now the source (changes often → comes AFTER the cached install step).
COPY frontend/ ./

# Vite bakes VITE_* into the JS text at build time, so the values must exist NOW.
# These come from GitHub Actions build-args (see .github/workflows/deploy-develop.yml).
#   - VITE_API_URL is left EMPTY on purpose: FastAPI serves this bundle, so the
#     browser is same-origin and relative "/api" calls hit the right server.
#     (Your local frontend/.env sets it to localhost for dev — that file is kept
#     OUT of this build by .dockerignore, so it can never leak into production.)
#   - VITE_PUBLIC_API_KEY is public by nature (visible in the browser); it's a
#     soft gate that must match the backend's PUBLIC_API_KEY.
ARG VITE_API_URL=
ARG VITE_PUBLIC_API_KEY=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_PUBLIC_API_KEY=$VITE_PUBLIC_API_KEY
RUN npm run build          # produces /app/frontend/dist


# ---- Stage 2: the image we actually ship --------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# no .pyc files; flush logs immediately (so Azure's live log stream shows them);
# don't keep pip's cache in the layer. HOST/PORT/WORKERS are read only by the
# __main__ block in main.py — the CMD below bypasses that, but they're harmless
# and document intent. WORKERS=1: the in-process scheduler (RUN_SCHEDULER) must
# not run in multiple worker processes or jobs fire twice.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WORKERS=1

WORKDIR /app

# System libraries the Python wheels need at RUNTIME:
#   - curl        → used by the HEALTHCHECK below
#   - libpq5      → psycopg (Postgres driver) links against it
#   - libfreetype6, libpng16-16 → matplotlib (used by report/chart code)
# Clean apt lists in the SAME layer or the deleted files still ship.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        libfreetype6 \
        libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

# Deps before source, so backend code edits don't re-run this slow pip install.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

# Migration runner + SQL. The entrypoint runs these at container start, before
# the API boots. Kept out of the image before; now load-bearing (see
# .dockerignore, which un-ignores db/ for exactly this).
COPY db ./db

# CRITICAL PATH: frontend_static.py computes dist as
#   Path(__file__).parent.parent / "frontend" / "dist"
# backend/ lives at /app/backend, so its parent is /app → dist MUST land here.
# Get this path wrong and mount_frontend() silently does nothing → the UI 404s.
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Entrypoint runs DB migrations, then execs the CMD below (the API server).
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

# Azure restarts the container if this fails. start-period is generous because
# the app opens DB + Redis pools on boot. /health is defined in backend/main.py.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Entrypoint applies migrations, then `exec "$@"` runs this CMD — so uvicorn
# still ends up as PID 1 and receives SIGTERM directly for clean stops.
#   --host 0.0.0.0  : listen on all interfaces so Azure's proxy can reach it
#   --proxy-headers + --forwarded-allow-ips * : trust Azure's front-end proxy so
#     the app sees the real client IP/scheme (https), not the proxy's.
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
