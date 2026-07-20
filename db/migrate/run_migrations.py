#!/usr/bin/env python3
"""Lightweight forward-only migration runner (YAML manifest + SQL + tracking table).

It does NOT diff schemas. It compares the ordered migrations in
db/migrations/migrations.yaml against what each database records in
solvetax.schema_migration_history, and applies whatever is missing, in order.

Connection comes from the same env the app uses (DB_HOST/PORT/NAME/USER/PASSWORD,
DB_SCHEMA), so it works unchanged in DEV and PROD containers.

Usage:
    python db/migrate/run_migrations.py                 # apply pending migrations
    python db/migrate/run_migrations.py --dry-run       # show pending, change nothing
    python db/migrate/run_migrations.py --baseline V001 # mark up to V001 as SUCCESS
                                                        #   WITHOUT running (for a DB
                                                        #   that already has that schema)

Exit code is non-zero on any failure so a container entrypoint / CI step stops
the deploy (fail-closed).
"""
import argparse
import asyncio
import hashlib
import os
import ssl
import sys
from pathlib import Path

import asyncpg
import yaml

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MANIFEST = MIGRATIONS_DIR / "migrations.yaml"
SCHEMA = os.getenv("DB_SCHEMA", "solvetax")
HISTORY = f"{SCHEMA}.schema_migration_history"
# Arbitrary constant: serializes concurrent runners (e.g. multiple App Service
# instances booting at once) so only one migrates at a time.
LOCK_KEY = 918273645


def log(msg):
    print(f"[migrate] {msg}", flush=True)


def die(msg):
    print(f"[migrate] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest():
    if not MANIFEST.exists():
        die(f"manifest not found: {MANIFEST}")
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    migs = data.get("migrations") or []
    seen = set()
    for m in migs:
        for key in ("version", "name", "script"):
            if not m.get(key):
                die(f"manifest entry missing '{key}': {m}")
        if m["version"] in seen:
            die(f"duplicate version in manifest: {m['version']}")
        seen.add(m["version"])
        if not (MIGRATIONS_DIR / m["script"]).exists():
            die(f"script file missing: {MIGRATIONS_DIR / m['script']}")
        m.setdefault("transactional", True)
    return migs


async def connect():
    host = os.environ.get("DB_HOST")
    name = os.environ.get("DB_NAME")
    user = os.environ.get("DB_USER")
    if not (host and name and user):
        die("DB_HOST / DB_NAME / DB_USER must be set")
    ctx = ssl.create_default_context()
    if os.getenv("DB_SSL_INSECURE") == "1":  # local docker testing only
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    ssl_arg = False if os.getenv("DB_SSL", "require") == "disable" else ctx
    return await asyncpg.connect(
        host=host, port=int(os.getenv("DB_PORT", "5432")),
        database=name, user=user, password=os.environ.get("DB_PASSWORD"),
        ssl=ssl_arg,
    )


async def ensure_history(conn):
    # On a brand-new database the app schema doesn't exist yet (V001 creates it),
    # so make sure it's there before the tracking table lands in it.
    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {HISTORY} (
            version         varchar(50) PRIMARY KEY,
            migration_name  varchar(255) NOT NULL,
            script_name     varchar(255) NOT NULL,
            checksum        varchar(64)  NOT NULL,
            status          varchar(20)  NOT NULL,
            started_at      timestamptz  NOT NULL DEFAULT now(),
            completed_at    timestamptz,
            error_message   text
        )
        """
    )


async def load_applied(conn):
    rows = await conn.fetch(f"SELECT version, checksum, status FROM {HISTORY}")
    return {r["version"]: (r["checksum"], r["status"]) for r in rows}


async def _mark(conn, m, status, err=None, completed=False):
    await conn.execute(
        f"""
        INSERT INTO {HISTORY} (version, migration_name, script_name, checksum, status, error_message, completed_at)
        VALUES ($1, $2, $3, $4, $5, $6, {'now()' if completed else 'NULL'})
        ON CONFLICT (version) DO UPDATE
           SET migration_name = EXCLUDED.migration_name,
               script_name    = EXCLUDED.script_name,
               checksum       = EXCLUDED.checksum,
               status         = EXCLUDED.status,
               error_message  = EXCLUDED.error_message,
               started_at     = now(),
               completed_at   = {'now()' if completed else 'NULL'}
        """,
        m["version"], m["name"], m["script"], m["_checksum"], status, err,
    )


def check_drift(migs, applied):
    for m in migs:
        v = m["version"]
        if v in applied and applied[v][1] == "SUCCESS" and applied[v][0] != m["_checksum"]:
            die(f"{v} ({m['script']}) is already applied but the file changed on disk "
                f"(checksum drift). Never edit an applied migration — add a new version.")


async def do_baseline(conn, migs, applied, target):
    versions = [m["version"] for m in migs]
    if target not in versions:
        die(f"--baseline {target} is not in the manifest ({versions})")
    upto = versions.index(target) + 1
    for m in migs[:upto]:
        if applied.get(m["version"], (None, None))[1] == "SUCCESS":
            log(f"{m['version']} already SUCCESS — skip")
            continue
        await _mark(conn, m, "SUCCESS", completed=True)
        log(f"{m['version']} baseline-marked SUCCESS (not executed)")
    log("baseline complete")


async def apply_pending(conn, migs, applied, dry_run):
    pending = [m for m in migs if applied.get(m["version"], (None, None))[1] != "SUCCESS"]
    if not pending:
        log("no pending migrations — database is up to date")
        return
    log(f"pending: {[m['version'] for m in pending]}")
    if dry_run:
        log("dry-run: nothing applied")
        return
    for m in pending:
        v = m["version"]
        sql = (MIGRATIONS_DIR / m["script"]).read_text(encoding="utf-8")
        log(f"applying {v} ({m['script']}) transactional={m['transactional']} ...")
        try:
            if m["transactional"]:
                # Migration + its SUCCESS row commit together, or neither does.
                async with conn.transaction():
                    await conn.execute(sql)
                    await _mark(conn, m, "SUCCESS", completed=True)
            else:
                # Cannot wrap (e.g. CREATE INDEX CONCURRENTLY): record, run, mark.
                await _mark(conn, m, "IN_PROGRESS")
                await conn.execute(sql)
                await _mark(conn, m, "SUCCESS", completed=True)
            log(f"{v} SUCCESS")
        except Exception as exc:  # noqa: BLE001
            # The transaction (if any) already rolled back; record FAILED separately.
            try:
                await _mark(conn, m, "FAILED", err=str(exc)[:4000])
            except Exception:  # noqa: BLE001
                pass
            die(f"{v} FAILED — stopping deploy. {exc}")
    log("all migrations applied")


async def main():
    ap = argparse.ArgumentParser(description="Run pending DB migrations.")
    ap.add_argument("--baseline", metavar="VERSION",
                    help="mark migrations up to VERSION as SUCCESS without running them")
    ap.add_argument("--dry-run", action="store_true", help="show pending, change nothing")
    args = ap.parse_args()

    migs = load_manifest()
    for m in migs:
        m["_checksum"] = checksum(MIGRATIONS_DIR / m["script"])

    conn = await connect()
    try:
        await conn.execute(f"SELECT pg_advisory_lock({LOCK_KEY})")
        try:
            await ensure_history(conn)
            applied = await load_applied(conn)
            check_drift(migs, applied)
            if args.baseline:
                await do_baseline(conn, migs, applied, args.baseline)
            else:
                await apply_pending(conn, migs, applied, args.dry_run)
        finally:
            await conn.execute(f"SELECT pg_advisory_unlock({LOCK_KEY})")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
