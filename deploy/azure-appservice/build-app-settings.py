#!/usr/bin/env python3
"""Turn the backend .env into an Azure App Service settings file.

Backend runtime secrets (DB_PASSWORD, JWT_SECRET, storage keys, SMTP, MSG91, ...)
belong in App Service settings, NOT in GitHub. This reads .env and writes a JSON
file that `az webapp config appsettings set --settings @<file>` uploads.

Usage (from the repo root, after `az login`):

    python deploy/azure-appservice/build-app-settings.py
    az webapp config appsettings set -g solvetax-dev-rg -n solvetax-admin-dev \
        --settings @deploy/azure-appservice/app-settings.dev.json

The output file holds real secrets and is .gitignored — delete it after upload.
"""
import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV_FILE = os.path.join(REPO_ROOT, ".env")
OUT_FILE = os.path.join(os.path.dirname(__file__), "app-settings.dev.json")
WEBAPP = "solvetax-admin-dev"

# Values we set/guarantee regardless of what's in .env:
#   WEBSITES_PORT  — the port Azure forwards to (matches the Dockerfile)
#   WORKERS        — single uvicorn worker (in-process scheduler must not double-run)
#   ALLOWED_ORIGINS— CORS allow-list; add the custom domain here when you add it
FORCED = {
    "WEBSITES_PORT": "8000",
    "WORKERS": "1",
    "ALLOWED_ORIGINS": f"https://{WEBAPP}.azurewebsites.net",
}


def parse_env(path):
    settings = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # VITE_* are frontend build-time values, not backend runtime — skip.
            if not key or key.startswith("VITE_"):
                continue
            settings[key] = value
    return settings


def main():
    if not os.path.exists(ENV_FILE):
        sys.exit(f"ERROR: {ENV_FILE} not found. Run from the repo root.")

    settings = parse_env(ENV_FILE)
    settings.update(FORCED)  # forced values win over .env

    payload = [{"name": k, "value": v} for k, v in settings.items()]
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"Wrote {len(payload)} settings to:\n  {OUT_FILE}\n")
    print("Next:")
    print(f"  az webapp config appsettings set -g solvetax-dev-rg -n {WEBAPP} \\")
    print(f"      --settings @deploy/azure-appservice/app-settings.dev.json")
    print("\nThen DELETE app-settings.dev.json (it holds real secrets).")


if __name__ == "__main__":
    main()
