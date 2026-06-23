# syntax=docker/dockerfile:1

# ---- Build React/Vite frontend (served by FastAPI from frontend/dist) ----
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Baked at build time (GitHub Actions build-args). Leave empty for same-origin prod.
ARG VITE_API_URL=
ARG VITE_PUBLIC_API_KEY=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_PUBLIC_API_KEY=$VITE_PUBLIC_API_KEY
RUN npm run build


# ---- Python API runtime ----
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WORKERS=1

WORKDIR /app

# matplotlib + common wheels on slim image
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libfreetype6 \
        libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Single worker: in-process scheduler (RUN_SCHEDULER) must not run in multiple processes.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
