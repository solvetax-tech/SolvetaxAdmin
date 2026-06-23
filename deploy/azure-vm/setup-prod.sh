#!/usr/bin/env bash
# Production stack: API behind nginx on ports 80/443.
#
#   cp .env.example .env && nano .env
#   bash deploy/azure-vm/setup-prod.sh
#   bash deploy/azure-vm/init-letsencrypt.sh   # after DNS is live

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and configure secrets + DOMAIN."
  exit 1
fi

if ! command -v envsubst >/dev/null 2>&1; then
  echo "Install envsubst: sudo apt-get install -y gettext-base"
  exit 1
fi

docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

docker compose -f docker-compose.prod.yml ps
echo ""
echo "HTTP:  http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_VM_IP)"
echo "Health (via nginx): curl -s http://127.0.0.1/health"
echo ""
echo "When DNS points here, run: bash deploy/azure-vm/init-letsencrypt.sh"
