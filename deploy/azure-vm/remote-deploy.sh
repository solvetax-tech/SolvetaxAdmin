#!/usr/bin/env bash
# Called by GitHub Actions over SSH. Usage:
#   bash deploy/azure-vm/remote-deploy.sh dev ghcr.io/owner/repo
#   bash deploy/azure-vm/remote-deploy.sh qa ghcr.io/owner/repo
#   bash deploy/azure-vm/remote-deploy.sh prod ghcr.io/owner/repo

set -euo pipefail

TAG="${1:?Usage: remote-deploy.sh <dev|qa|prod> <ghcr-image-base>}"
IMAGE_BASE="${2:?Usage: remote-deploy.sh <dev|qa|prod> <ghcr-image-base>}"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env in $(pwd)"
  exit 1
fi

if [[ "$TAG" != "dev" && "$TAG" != "qa" && "$TAG" != "prod" ]]; then
  echo "TAG must be dev, qa, or prod"
  exit 1
fi

if [[ -n "${DEPLOY_GHCR_TOKEN:-}" ]]; then
  echo "${DEPLOY_GHCR_TOKEN}" | docker login ghcr.io -u "${DEPLOY_GHCR_USER:-github}" --password-stdin
elif [[ -n "${GITHUB_ACTIONS:-}" ]]; then
  echo "DEPLOY_GHCR_TOKEN not set in server .env; workflow should login before calling this script."
fi

export API_IMAGE="${IMAGE_BASE}:${TAG}"

echo "==> Deploying ${API_IMAGE}..."
docker compose -f docker-compose.prod.yml pull solvetax-api
docker compose -f docker-compose.prod.yml up -d --remove-orphans

if docker compose -f docker-compose.prod.yml ps nginx 2>/dev/null | grep -q Up; then
  docker compose -f docker-compose.prod.yml exec -T nginx nginx -t
  docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload || true
  curl -fsS http://127.0.0.1/health
else
  curl -fsS "http://127.0.0.1:${PORT:-8000}/health"
fi

docker compose -f docker-compose.prod.yml ps
docker image prune -f
echo "Deploy OK: ${API_IMAGE}"
