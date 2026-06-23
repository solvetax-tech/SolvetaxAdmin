#!/usr/bin/env bash
# Manual deploy from VM (same as CI). Example:
#   bash deploy/azure-vm/deploy-from-ghcr.sh prod
#   bash deploy/azure-vm/deploy-from-ghcr.sh dev

set -euo pipefail

TAG="${1:-prod}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

IMAGE_BASE="${GHCR_IMAGE:-}"
if [[ -z "$IMAGE_BASE" ]]; then
  # Fallback: strip tag from API_IMAGE if set
  if [[ -n "${API_IMAGE:-}" ]]; then
    IMAGE_BASE="${API_IMAGE%:*}"
  else
    echo "Set GHCR_IMAGE=ghcr.io/owner/repo in .env"
    exit 1
  fi
fi

bash deploy/azure-vm/remote-deploy.sh "$TAG" "$IMAGE_BASE"
