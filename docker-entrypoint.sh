#!/bin/sh
# Container entrypoint: bring the database schema up to date, THEN start the app.
#
# The migration runner is fail-closed — if a migration errors it exits non-zero,
# `set -e` stops the script, the container never serves, /health fails, and the
# deploy is caught by the workflow's smoke test. A Postgres advisory lock inside
# the runner makes this safe even if several instances boot at once.
#
# DB_* come from the environment (Azure App Service settings), the same way the
# app reads them — so this works unchanged in DEV and PROD.
set -e

echo "[entrypoint] applying database migrations..."
python db/migrate/run_migrations.py

echo "[entrypoint] migrations up to date; starting API..."
exec "$@"
