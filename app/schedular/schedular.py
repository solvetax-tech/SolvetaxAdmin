import asyncio
import logging
import os
from datetime import timedelta
from typing import Optional

from app.utils import get_db_pool, DB_SCHEMA

_scheduler_task: Optional[asyncio.Task] = None


def _add_months(ts, months: int):
    year = ts.year + (ts.month - 1 + months) // 12
    month = (ts.month - 1 + months) % 12 + 1
    # keep day safe for short months
    day = min(
        ts.day,
        [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
    )
    return ts.replace(year=year, month=month, day=day)


def _shift_due(ts, months: int):
    return _add_months(ts, months) if ts is not None else None


def _lead_days_for_cadence_months(cadence_months: int) -> int:
    """Match gst_registation_filing: monthly 10d, quarterly 12d, annual 7d buffer before due."""
    if cadence_months == 1:
        return 10
    if cadence_months == 3:
        return 12
    if cadence_months == 12:
        return 7
    return 7


def _next_auto_from_due_dates(*dates, lead_days: int = 7):
    valid = [d for d in dates if d is not None]
    if not valid:
        return None
    return min(valid) - timedelta(days=lead_days)


def _build_next_row_from_source(src: dict, filing_frequency: str):
    # Keep only applicable returns as NOT_FILED, others as NULL.
    gstr1_applicable = src.get("gstr1_status") is not None or src.get("gstr1_due_date") is not None
    gstr3b_applicable = src.get("gstr3b_status") is not None or src.get("gstr3b_due_date") is not None
    gstr9_applicable = src.get("gstr9_status") is not None or src.get("gstr9_due_date") is not None
    gstr9c_applicable = src.get("gstr9c_status") is not None or src.get("gstr9c_due_date") is not None
    cmp08_applicable = src.get("cmp08_status") is not None or src.get("cmp08_due_date") is not None
    gstr4_applicable = src.get("gstr4_status") is not None or src.get("gstr4_due_date") is not None

    if gstr9_applicable or gstr9c_applicable:
        cadence_months = 12
    elif gstr4_applicable:
        cadence_months = 12
    elif cmp08_applicable:
        cadence_months = 3
    elif filing_frequency == "MONTHLY":
        cadence_months = 1
    elif filing_frequency == "QUARTERLY":
        cadence_months = 3
    else:
        cadence_months = 12

    gstr1_due = _shift_due(src.get("gstr1_due_date"), cadence_months)
    gstr3b_due = _shift_due(src.get("gstr3b_due_date"), cadence_months)
    gstr9_due = _shift_due(src.get("gstr9_due_date"), cadence_months)
    gstr9c_due = _shift_due(src.get("gstr9c_due_date"), cadence_months)
    cmp08_due = _shift_due(src.get("cmp08_due_date"), cadence_months)
    gstr4_due = _shift_due(src.get("gstr4_due_date"), cadence_months)

    lead = _lead_days_for_cadence_months(cadence_months)
    next_auto = _next_auto_from_due_dates(
        gstr1_due,
        gstr3b_due,
        gstr9_due,
        gstr9c_due,
        cmp08_due,
        gstr4_due,
        lead_days=lead,
    )

    return {
        "gstr1_status": "NOT_FILED" if gstr1_applicable else None,
        "gstr3b_status": "NOT_FILED" if gstr3b_applicable else None,
        "gstr9_status": "NOT_FILED" if gstr9_applicable else None,
        "gstr9c_status": "NOT_FILED" if gstr9c_applicable else None,
        "cmp08_status": "NOT_FILED" if cmp08_applicable else None,
        "gstr4_status": "NOT_FILED" if gstr4_applicable else None,
        "gstr1_due_date": gstr1_due,
        "gstr3b_due_date": gstr3b_due,
        "gstr9_due_date": gstr9_due,
        "gstr9c_due_date": gstr9c_due,
        "cmp08_due_date": cmp08_due,
        "gstr4_due_date": gstr4_due,
        "next_auto_generate_at": next_auto,
    }


async def _run_gst_filing_auto_generation(conn):
    """
    Forward-only return-detail chaining (does **not** create `gst_filings` rows and does **not**
    backfill historical months/quarters/years).

    Picks active return-detail rows whose `next_auto_generate_at` is due, inserts **one** new
    `gst_filing_return_details` row on the **same** `gst_filing_id` with due dates shifted forward,
    then clears `next_auto_generate_at` on the source row. Manual backlog filings use the create API;
    this job only continues an existing auto-enabled chain from the latest row.
    """
    # Lock due rows so parallel scheduler ticks/workers don't duplicate inserts.
    rows = await conn.fetch(
        f"""
        SELECT d.*, f.filing_frequency
        FROM {DB_SCHEMA}.gst_filing_return_details d
        JOIN {DB_SCHEMA}.gst_filings f
          ON f.id = d.gst_filing_id
        WHERE d.is_active = TRUE
          AND f.is_active = TRUE
          AND f.is_auto_enabled = TRUE
          AND f.gst_reg_status = 'APPROVED'
          AND d.next_auto_generate_at IS NOT NULL
          AND d.next_auto_generate_at <= NOW()
        ORDER BY d.next_auto_generate_at ASC
        FOR UPDATE OF d SKIP LOCKED
        LIMIT 100
        """
    )

    generated = 0
    for row in rows:
        src = dict(row)
        next_row = _build_next_row_from_source(src, src.get("filing_frequency") or "MONTHLY")

        await conn.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                gst_filing_id,
                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                is_auto_generated, next_auto_generate_at
            )
            VALUES (
                $1,$2,$3,$4,$5,$6,$7,
                $8,$9,$10,$11,$12,$13,
                TRUE,$14
            )
            """,
            src["gst_filing_id"],
            next_row["gstr1_status"],
            next_row["gstr3b_status"],
            next_row["gstr9_status"],
            next_row["gstr9c_status"],
            next_row["cmp08_status"],
            next_row["gstr4_status"],
            next_row["gstr1_due_date"],
            next_row["gstr3b_due_date"],
            next_row["gstr9_due_date"],
            next_row["gstr9c_due_date"],
            next_row["cmp08_due_date"],
            next_row["gstr4_due_date"],
            next_row["next_auto_generate_at"],
        )

        # Mark current source row as processed for auto-generation.
        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.gst_filing_return_details
            SET next_auto_generate_at = NULL,
                updated_at = NOW()
            WHERE id = $1
            """,
            src["id"],
        )
        generated += 1

    return generated


async def _mark_overdue_gst_return_statuses(conn) -> str:
    """
    For each return column, if due_date < NOW() and status is NOT_FILED, set status to MISSED.
    Only touches rows under active parent filings and active return-detail rows.
    """
    return await conn.execute(
        f"""
        UPDATE {DB_SCHEMA}.gst_filing_return_details AS d
        SET
            gstr1_status = CASE
                WHEN d.gstr1_due_date IS NOT NULL
                     AND d.gstr1_due_date < NOW()
                     AND d.gstr1_status = 'NOT_FILED' THEN 'MISSED'
                ELSE d.gstr1_status END,
            gstr3b_status = CASE
                WHEN d.gstr3b_due_date IS NOT NULL
                     AND d.gstr3b_due_date < NOW()
                     AND d.gstr3b_status = 'NOT_FILED' THEN 'MISSED'
                ELSE d.gstr3b_status END,
            gstr9_status = CASE
                WHEN d.gstr9_due_date IS NOT NULL
                     AND d.gstr9_due_date < NOW()
                     AND d.gstr9_status = 'NOT_FILED' THEN 'MISSED'
                ELSE d.gstr9_status END,
            gstr9c_status = CASE
                WHEN d.gstr9c_due_date IS NOT NULL
                     AND d.gstr9c_due_date < NOW()
                     AND d.gstr9c_status = 'NOT_FILED' THEN 'MISSED'
                ELSE d.gstr9c_status END,
            cmp08_status = CASE
                WHEN d.cmp08_due_date IS NOT NULL
                     AND d.cmp08_due_date < NOW()
                     AND d.cmp08_status = 'NOT_FILED' THEN 'MISSED'
                ELSE d.cmp08_status END,
            gstr4_status = CASE
                WHEN d.gstr4_due_date IS NOT NULL
                     AND d.gstr4_due_date < NOW()
                     AND d.gstr4_status = 'NOT_FILED' THEN 'MISSED'
                ELSE d.gstr4_status END,
            updated_at = NOW()
        FROM {DB_SCHEMA}.gst_filings AS f
        WHERE f.id = d.gst_filing_id
          AND f.is_active = TRUE
          AND d.is_active = TRUE
          AND (
              (d.gstr1_due_date IS NOT NULL AND d.gstr1_due_date < NOW() AND d.gstr1_status = 'NOT_FILED')
              OR (d.gstr3b_due_date IS NOT NULL AND d.gstr3b_due_date < NOW() AND d.gstr3b_status = 'NOT_FILED')
              OR (d.gstr9_due_date IS NOT NULL AND d.gstr9_due_date < NOW() AND d.gstr9_status = 'NOT_FILED')
              OR (d.gstr9c_due_date IS NOT NULL AND d.gstr9c_due_date < NOW() AND d.gstr9c_status = 'NOT_FILED')
              OR (d.cmp08_due_date IS NOT NULL AND d.cmp08_due_date < NOW() AND d.cmp08_status = 'NOT_FILED')
              OR (d.gstr4_due_date IS NOT NULL AND d.gstr4_due_date < NOW() AND d.gstr4_status = 'NOT_FILED')
          )
        """
    )


async def background_jobs():
    pool = await get_db_pool()

    while True:
        try:
            async with pool.acquire() as conn:
                logging.info("Running background scheduler...")

                # 1) Mark missed followups
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_service_followups
                    SET status = 'MISSED',
                        updated_at = NOW()
                    WHERE status = 'PENDING'
                      AND followup_at < NOW()
                      AND followup_at IS NOT NULL
                    """
                )
                logging.info("MISSED followups updated: %s", result)

                # 2) Expire session tokens
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.session_token
                    SET is_active = FALSE
                    WHERE is_active = TRUE
                      AND expires_at IS NOT NULL
                      AND expires_at < NOW()
                    """
                )

                # 3) GST return-detail: NOT_FILED -> MISSED when due date has passed
                overdue_status = await _mark_overdue_gst_return_statuses(conn)
                _n = overdue_status.split()[-1] if overdue_status else "0"
                if _n.isdigit() and int(_n) > 0:
                    logging.info(
                        "GST return-detail rows updated (NOT_FILED -> MISSED where due < now): %s",
                        overdue_status,
                    )

                # 4) Auto-generate next GST filing return detail rows
                generated = await _run_gst_filing_auto_generation(conn)
                if generated:
                    logging.info("Auto generated gst filing return-detail rows: %s", generated)

                logging.info("Scheduler completed successfully")

        except Exception as e:
            logging.error("Scheduler error: %s", e, exc_info=True)

        await asyncio.sleep(60)


def start_scheduler_if_enabled():
    global _scheduler_task
    if os.getenv("RUN_SCHEDULER", "true").lower() != "true":
        return
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(background_jobs())


async def stop_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    _scheduler_task = None
