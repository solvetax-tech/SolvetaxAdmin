#!/usr/bin/env bash
# Run on Ubuntu Azure VM (as user with sudo):
#   curl -fsSL https://get.docker.com | sudo sh
#   sudo usermod -aG docker "$USER"   # then log out/in
#   cd /opt/slovetax && cp .env.example .env && nano .env
#   docker compose up -d --build

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill Azure DB/Redis/Blob secrets."
  exit 1
fi

docker compose build --no-cache
docker compose up -d
docker compose ps
echo "Health: curl -s http://127.0.0.1:${PORT:-8000}/health"
