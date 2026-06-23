#!/usr/bin/env bash
# Obtain Let's Encrypt certificate and switch nginx to HTTPS.
#
# Prerequisites:
#   - DOMAIN DNS A record → this VM public IP
#   - Azure NSG: inbound 80 and 443 open
#   - .env contains DOMAIN and CERTBOT_EMAIL
#
# Usage (from repo root on VM):
#   bash deploy/azure-vm/init-letsencrypt.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f docker-compose.prod.yml)
COMPOSE_TOOLS=(docker compose -f docker-compose.prod.yml --profile tools)

if [[ ! -f .env ]]; then
  echo "Missing .env — set DOMAIN and CERTBOT_EMAIL first."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

DOMAIN="${DOMAIN:-}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
CERT_NAME="${CERT_NAME:-$DOMAIN}"
STAGING="${CERTBOT_STAGING:-0}"

if [[ -z "$DOMAIN" || -z "$CERTBOT_EMAIL" ]]; then
  echo "Set DOMAIN and CERTBOT_EMAIL in .env"
  exit 1
fi

if ! command -v envsubst >/dev/null 2>&1; then
  echo "Install envsubst: sudo apt-get install -y gettext-base"
  exit 1
fi

echo "==> Starting API + nginx (HTTP bootstrap)..."
"${COMPOSE[@]}" up -d --build solvetax-api nginx

echo "==> Requesting certificate for ${DOMAIN}..."
STAGING_ARG=()
if [[ "$STAGING" == "1" ]]; then
  STAGING_ARG=(--staging)
  echo "    (Let's Encrypt STAGING — not trusted by browsers)"
fi

EXTRA_DOMAIN_ARGS=()
if [[ -n "${CERTBOT_EXTRA_DOMAINS:-}" ]]; then
  # Example in .env: CERTBOT_EXTRA_DOMAINS=-d www.yourdomain.com
  read -r -a EXTRA_DOMAIN_ARGS <<< "$CERTBOT_EXTRA_DOMAINS"
fi

"${COMPOSE_TOOLS[@]}" run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email "$CERTBOT_EMAIL" \
  --agree-tos \
  --no-eff-email \
  "${STAGING_ARG[@]}" \
  -d "$DOMAIN" \
  "${EXTRA_DOMAIN_ARGS[@]}"

export DOMAIN CERT_NAME
envsubst '${DOMAIN} ${CERT_NAME}' \
  < deploy/azure-vm/nginx/templates/app-ssl.conf.template \
  > deploy/azure-vm/nginx/conf.d/default.conf

echo "==> Reloading nginx with HTTPS config..."
"${COMPOSE[@]}" exec nginx nginx -t
"${COMPOSE[@]}" exec nginx nginx -s reload

echo ""
echo "Done. Open https://${DOMAIN}"
echo "Renew manually: bash deploy/azure-vm/ssl-renew.sh"
echo "Or enable auto-renew: docker compose -f docker-compose.prod.yml --profile renew up -d certbot-renew"
