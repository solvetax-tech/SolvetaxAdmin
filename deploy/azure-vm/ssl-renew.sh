#!/usr/bin/env bash
# Renew certs and reload nginx. Add to cron on the VM:
#   0 3 * * * cd /opt/slovetax && bash deploy/azure-vm/ssl-renew.sh >> /var/log/solvetax-ssl-renew.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f docker-compose.prod.yml)
COMPOSE_TOOLS=(docker compose -f docker-compose.prod.yml --profile tools)

"${COMPOSE_TOOLS[@]}" run --rm certbot renew \
  --webroot -w /var/www/certbot \
  --quiet

"${COMPOSE[@]}" exec nginx nginx -s reload
echo "$(date -Is) certificate renew + nginx reload OK"
