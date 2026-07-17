"""Verify FILING_TO_REGISTRATION_SYNC against the live schema.

Why this exists
---------------
backend/gst_registration_filing/gst_registration_filing.py builds the identity-sync
UPDATE by interpolating FILING_TO_REGISTRATION_SYNC's values directly as column
names. A value that is not a real gst_registration column raises
UndefinedColumnError at runtime, which aborts the enclosing transaction and fails
the ENTIRE filing edit with a generic 500 -- even when the user only changed
something unrelated like status.

That is not hypothetical: `taxpayer_type` and `business_description` were both
mapped to columns gst_registration does not have, so for months no filing linked
to a registration could be edited at all. Nothing caught it because the map is
only exercised when a linked filing is edited, and the error surfaced as a vague
"database error".

Usage
-----
    python db/checks/verify_gst_filing_sync_map.py

Exits 0 if every mapping is sound, 1 otherwise. Reads DB creds from .env.
"""

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from backend.gst_registration_filing.gst_registration_filing import (  # noqa: E402
    FILING_TO_REGISTRATION_SYNC,
)


async def columns_of(conn, schema: str, table: str) -> set:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        """,
        schema,
        table,
    )
    return {r["column_name"] for r in rows}


async def main() -> int:
    schema = os.getenv("DB_SCHEMA", "solvetax")
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 5432)),
        ssl="require",
    )
    try:
        filing_cols = await columns_of(conn, schema, "gst_filings")
        reg_cols = await columns_of(conn, schema, "gst_registration")
    finally:
        await conn.close()

    problems = []
    print("FILING_TO_REGISTRATION_SYNC -- %d mappings\n" % len(FILING_TO_REGISTRATION_SYNC))
    for filing_key, reg_col in FILING_TO_REGISTRATION_SYNC.items():
        errs = []
        if filing_key not in filing_cols:
            errs.append("gst_filings.%s missing" % filing_key)
        if reg_col not in reg_cols:
            errs.append("gst_registration.%s missing" % reg_col)
        status = "ok" if not errs else "BROKEN: " + "; ".join(errs)
        print("  %-22s -> %-22s %s" % (filing_key, reg_col, status))
        if errs:
            problems.append((filing_key, reg_col, errs))

    if problems:
        print(
            "\n%d broken mapping(s). Each one fails EVERY edit of a filing that is\n"
            "linked to a registration, with a generic 500." % len(problems)
        )
        return 1

    print("\nAll mappings resolve to real columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
