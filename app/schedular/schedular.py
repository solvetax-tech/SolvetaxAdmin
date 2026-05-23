import asyncio
import logging
import os
from datetime import timedelta
from typing import Optional, Tuple

from app.utils import get_db_pool, DB_SCHEMA
from app.gst_registration_filing.gst_filing_auto_policy import (
    disable_gst_filings_auto_over_missed_threshold,
)
from app.crm.crm_leads_common import _invalidate_crm_cache
from app.payments.payment_scheduler import sync_settled_payment_entities
from app.redis_cache import invalidate_tag as redis_invalidate_tag

ITR_CRM_ENTITY_TYPE = "INCOME_TAX"

# Cap rows touched per scheduler tick so one run cannot scan/update the whole table.
SCHEDULER_SQL_BATCH_LIMIT = 500

_scheduler_task: Optional[asyncio.Task] = None

# Month lengths for `_add_months` (February adjusted per year in-line).
_DAYS_NON_LEAP = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return _DAYS_NON_LEAP[month - 1]


def _add_months(ts, months: int):
    year = ts.year + (ts.month - 1 + months) // 12
    month = (ts.month - 1 + months) % 12 + 1
    # keep day safe for short months
    day = min(ts.day, _days_in_month(year, month))
    return ts.replace(year=year, month=month, day=day)


def _shift_due(ts, months: int):
    return _add_months(ts, months) if ts is not None else None


def _lead_days_for_cadence_months(cadence_months: int) -> int:
    """Match gst_registration_filing: monthly 10d, quarterly 12d, annual 7d buffer before due."""
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


def _build_next_row_from_source(
    src: dict,
    filing_frequency: str,
    parent_turnover_details: Optional[str] = None,
):
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

    td = (parent_turnover_details or "").strip().upper() if parent_turnover_details else ""
    if td == "MORE_THAN_5CR" and gstr9_due is not None and gstr9c_due is None:
        gstr9c_due = gstr9_due
        gstr9c_applicable = True

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


def _parse_cmd_rowcount(tag: str) -> int:
    if not tag:
        return 0
    parts = tag.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0


async def _sync_gstr9c_with_parent_turnover(conn) -> Tuple[int, int]:
    """
    Align YEARLY return-detail GSTR-9C with gst_filings.turnover_details (edit / data fixes).

    Returns (rows_9c_added, rows_9c_cleared).
    """
    lim = SCHEDULER_SQL_BATCH_LIMIT
    add_sql = f"""
        UPDATE {DB_SCHEMA}.gst_filing_return_details AS d
        SET
            gstr9c_due_date = d.gstr9_due_date,
            gstr9c_status = CASE
                WHEN d.gstr9_due_date < NOW() THEN 'MISSED'
                ELSE 'NOT_FILED'
            END,
            next_auto_generate_at = d.gstr9_due_date - INTERVAL '7 days',
            updated_at = NOW()
        FROM {DB_SCHEMA}.gst_filings AS f
        WHERE f.id = d.gst_filing_id
          AND f.is_active = TRUE
          AND d.is_active = TRUE
          AND d.is_current = TRUE
          AND d.filing_frequency = 'YEARLY'
          AND d.gstr9_due_date IS NOT NULL
          AND d.gstr9_status IS NOT NULL
          AND COALESCE(UPPER(TRIM(f.turnover_details)), '') = 'MORE_THAN_5CR'
          AND UPPER(TRIM(f.filing_category)) = 'RETURN'
          AND UPPER(TRIM(f.taxpayer_type)) = 'REGULAR'
          AND d.gstr9c_due_date IS NULL
          AND (d.gstr9c_status IS NULL OR TRIM(COALESCE(d.gstr9c_status, '')) = '')
          AND d.id IN (
              SELECT d2.id
              FROM {DB_SCHEMA}.gst_filing_return_details d2
              INNER JOIN {DB_SCHEMA}.gst_filings f2 ON f2.id = d2.gst_filing_id
              WHERE f2.is_active = TRUE
                AND d2.is_active = TRUE
                AND d2.is_current = TRUE
                AND d2.filing_frequency = 'YEARLY'
                AND d2.gstr9_due_date IS NOT NULL
                AND COALESCE(UPPER(TRIM(f2.turnover_details)), '') = 'MORE_THAN_5CR'
                AND UPPER(TRIM(f2.filing_category)) = 'RETURN'
                AND UPPER(TRIM(f2.taxpayer_type)) = 'REGULAR'
                AND d2.gstr9c_due_date IS NULL
              ORDER BY d2.id ASC
              LIMIT {lim}
          )
        """
    clear_sql = f"""
        UPDATE {DB_SCHEMA}.gst_filing_return_details AS d
        SET
            gstr9c_due_date = NULL,
            gstr9c_status = NULL,
            next_auto_generate_at = d.gstr9_due_date - INTERVAL '7 days',
            updated_at = NOW()
        FROM {DB_SCHEMA}.gst_filings AS f
        WHERE f.id = d.gst_filing_id
          AND f.is_active = TRUE
          AND d.is_active = TRUE
          AND d.is_current = TRUE
          AND d.filing_frequency = 'YEARLY'
          AND d.gstr9_due_date IS NOT NULL
          AND COALESCE(UPPER(TRIM(f.turnover_details)), '') <> 'MORE_THAN_5CR'
          AND UPPER(TRIM(f.filing_category)) = 'RETURN'
          AND UPPER(TRIM(f.taxpayer_type)) = 'REGULAR'
          AND d.gstr9c_due_date IS NOT NULL
          AND d.gstr9c_status IN ('NOT_FILED', 'MISSED')
          AND d.id IN (
              SELECT d2.id
              FROM {DB_SCHEMA}.gst_filing_return_details d2
              INNER JOIN {DB_SCHEMA}.gst_filings f2 ON f2.id = d2.gst_filing_id
              WHERE f2.is_active = TRUE
                AND d2.is_active = TRUE
                AND d2.is_current = TRUE
                AND d2.filing_frequency = 'YEARLY'
                AND d2.gstr9c_due_date IS NOT NULL
                AND d2.gstr9c_status IN ('NOT_FILED', 'MISSED')
                AND COALESCE(UPPER(TRIM(f2.turnover_details)), '') <> 'MORE_THAN_5CR'
                AND UPPER(TRIM(f2.filing_category)) = 'RETURN'
                AND UPPER(TRIM(f2.taxpayer_type)) = 'REGULAR'
              ORDER BY d2.id ASC
              LIMIT {lim}
          )
        """
    r1 = await conn.execute(add_sql)
    r2 = await conn.execute(clear_sql)
    return _parse_cmd_rowcount(r1), _parse_cmd_rowcount(r2)


async def _run_gst_filing_auto_generation(conn):
    """
    Forward-only return-detail chaining (does **not** create `gst_filings` rows and does **not**
    backfill historical months/quarters/years).

    Picks active return-detail rows whose `next_auto_generate_at` is due, inserts **one** new
    `gst_filing_return_details` row on the **same** `gst_filing_id` with due dates shifted forward,
    then clears `next_auto_generate_at` on the source row. Manual backlog filings use the create API;
    this job only continues an existing auto-enabled chain from the latest row.
    """
    insert_sql = f"""
            INSERT INTO {DB_SCHEMA}.gst_filing_return_details (
                gst_filing_id,
                gstr1_status, gstr3b_status, gstr9_status, gstr9c_status, cmp08_status, gstr4_status,
                gstr1_due_date, gstr3b_due_date, gstr9_due_date, gstr9c_due_date, cmp08_due_date, gstr4_due_date,
                is_auto_generated, next_auto_generate_at, is_current
            )
            VALUES (
                $1,$2,$3,$4,$5,$6,$7,
                $8,$9,$10,$11,$12,$13,
                TRUE,$14,TRUE
            )
            """
    update_sql = f"""
            UPDATE {DB_SCHEMA}.gst_filing_return_details
            SET next_auto_generate_at = NULL,
                updated_at = NOW()
            WHERE id = $1
            """

    # One transaction: keep FOR UPDATE locks until inserts + updates complete (avoids races);
    # executemany cuts client↔server round-trips vs per-row execute.
    async with conn.transaction():
        rows = await conn.fetch(
            f"""
            SELECT d.*, f.filing_frequency, f.turnover_details AS filing_turnover_details
            FROM {DB_SCHEMA}.gst_filing_return_details d
            JOIN {DB_SCHEMA}.gst_filings f
              ON f.id = d.gst_filing_id
            WHERE d.is_active = TRUE
              AND d.is_current = TRUE
              AND f.is_active = TRUE
              AND f.is_auto_enabled = TRUE
              AND (
                    (f.gst_registration_id IS NOT NULL AND f.gst_reg_status = 'APPROVED')
                    OR (f.gst_registration_id IS NULL)
                  )
              AND d.next_auto_generate_at IS NOT NULL
              AND d.next_auto_generate_at <= NOW()
            ORDER BY d.next_auto_generate_at ASC
            FOR UPDATE OF d SKIP LOCKED
            LIMIT {SCHEDULER_SQL_BATCH_LIMIT}
            """
        )

        if not rows:
            return 0

        insert_args = []
        update_args = []
        for row in rows:
            src = dict(row)
            next_row = _build_next_row_from_source(
                src,
                src.get("filing_frequency") or "MONTHLY",
                src.get("filing_turnover_details"),
            )
            insert_args.append(
                (
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
            )
            update_args.append((src["id"],))

        await conn.executemany(insert_sql, insert_args)
        await conn.executemany(update_sql, update_args)

    return len(rows)


async def _mark_overdue_gst_return_statuses(conn) -> str:
    """
    For each return column, if due_date < NOW() and status is NOT_FILED, set status to MISSED.
    Only touches rows under active parent filings and active return-detail rows.
    """
    lim = SCHEDULER_SQL_BATCH_LIMIT
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
          AND d.is_current = TRUE
          AND d.id IN (
            SELECT d2.id
            FROM {DB_SCHEMA}.gst_filing_return_details d2
            INNER JOIN {DB_SCHEMA}.gst_filings f2 ON f2.id = d2.gst_filing_id
            WHERE f2.is_active = TRUE
              AND d2.is_active = TRUE
              AND d2.is_current = TRUE
              AND (
                  (d2.gstr1_due_date IS NOT NULL AND d2.gstr1_due_date < NOW() AND d2.gstr1_status = 'NOT_FILED')
                  OR (d2.gstr3b_due_date IS NOT NULL AND d2.gstr3b_due_date < NOW() AND d2.gstr3b_status = 'NOT_FILED')
                  OR (d2.gstr9_due_date IS NOT NULL AND d2.gstr9_due_date < NOW() AND d2.gstr9_status = 'NOT_FILED')
                  OR (d2.gstr9c_due_date IS NOT NULL AND d2.gstr9c_due_date < NOW() AND d2.gstr9c_status = 'NOT_FILED')
                  OR (d2.cmp08_due_date IS NOT NULL AND d2.cmp08_due_date < NOW() AND d2.cmp08_status = 'NOT_FILED')
                  OR (d2.gstr4_due_date IS NOT NULL AND d2.gstr4_due_date < NOW() AND d2.gstr4_status = 'NOT_FILED')
              )
            LIMIT {lim}
          )
        """
    )


async def _sync_itr_crm_subscribed_when_filed_and_paid(conn) -> int:
    """
    Catch-up for INCOME_TAX when payment was PAID before ITR was FILED.

    Triggers handle each event separately (ITR_DONE on file, payment stage on pay).
    This job promotes to SUBSCRIBED only when both are true and the lead is not already closed.
    Does not change GST or other entity types.
    """
    lim = SCHEDULER_SQL_BATCH_LIMIT
    rows = await conn.fetch(
        f"""
        SELECT l.id AS lead_id, l.stage AS old_stage
          FROM {DB_SCHEMA}.crm_leads l
          INNER JOIN {DB_SCHEMA}.income_tax i
                  ON i.id = l.entity_id
         WHERE l.is_active = TRUE
           AND l.entity_id IS NOT NULL
           AND upper(btrim(l.entity_type::text)) = $1
           AND l.stage NOT IN ('SUBSCRIBED', 'NOT_INTERESTED')
           AND i.is_active = TRUE
           AND upper(btrim(i.filed_status::text)) = 'FILED'
           AND EXISTS (
               SELECT 1
                 FROM {DB_SCHEMA}.payments p
                WHERE p.entity_id = l.entity_id
                  AND upper(btrim(p.entity_type::text)) = $1
                  AND p.is_active = TRUE
                  AND p.payment_status = 'PAID'
           )
         ORDER BY l.id ASC
         LIMIT {lim}
         FOR UPDATE OF l SKIP LOCKED
        """,
        ITR_CRM_ENTITY_TYPE,
    )
    if not rows:
        return 0

    activity_remarks = (
        "Scheduler: income tax FILED and payment PAID — stage set to SUBSCRIBED."
    )
    async with conn.transaction():
        for row in rows:
            lead_id = int(row["lead_id"])
            old_stage = row["old_stage"]
            updated = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.crm_leads
                   SET stage = 'SUBSCRIBED',
                       updated_at = NOW()
                 WHERE id = $1
                   AND is_active = TRUE
                   AND stage NOT IN ('SUBSCRIBED', 'NOT_INTERESTED')
                 RETURNING id, stage
                """,
                lead_id,
            )
            if not updated:
                continue
            if old_stage == updated["stage"]:
                continue
            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.crm_activities (
                    lead_id,
                    entity_type,
                    activity_type,
                    old_stage,
                    new_stage,
                    remarks,
                    performed_by,
                    performed_at,
                    created_at
                )
                VALUES ($1, $2, 'SYSTEM', $3, 'SUBSCRIBED', $4, NULL, NOW(), NOW())
                """,
                lead_id,
                ITR_CRM_ENTITY_TYPE,
                old_stage,
                activity_remarks,
            )
            await _invalidate_crm_cache(lead_id)

    return len(rows)


async def _expire_customer_otps(conn) -> str:
    lim = SCHEDULER_SQL_BATCH_LIMIT
    return await conn.execute(
        f"""
        UPDATE {DB_SCHEMA}.customer_otp_verify
        SET is_active = FALSE
        WHERE id IN (
            SELECT id
            FROM {DB_SCHEMA}.customer_otp_verify
            WHERE is_active = TRUE
              AND expires_at IS NOT NULL
              AND expires_at < NOW()
            LIMIT {lim}
        )
        """
    )


async def background_jobs():
    pool = await get_db_pool()

    while True:
        try:
            async with pool.acquire() as conn:
                logging.info("Running background scheduler...")

                lim = SCHEDULER_SQL_BATCH_LIMIT

                # 1) customer_services: overdue PENDING follow-ups (>10 min past followup_at) → MISSED (+ missed_at)
                #    Matches trg_followup_missed_if_overdue; catches rows that never get an API UPDATE.
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                    SET followup_status = 'MISSED',
                        missed_at = COALESCE(missed_at, NOW())
                    WHERE id IN (
                        SELECT id
                        FROM {DB_SCHEMA}.customer_services
                        WHERE is_active IS TRUE
                          AND followup_status = 'PENDING'
                          AND followup_at IS NOT NULL
                          AND NOW() > followup_at + INTERVAL '10 minutes'
                        LIMIT {lim}
                    )
                    """
                )
                logging.info("customer_services follow-ups marked MISSED (overdue): %s", result)

                # 2) customer_services: MISSED rows still missing missed_at (edge cases)
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_services
                    SET missed_at = NOW()
                    WHERE id IN (
                        SELECT id
                        FROM {DB_SCHEMA}.customer_services
                        WHERE is_active IS TRUE
                          AND followup_status = 'MISSED'
                          AND missed_at IS NULL
                          AND followup_at IS NOT NULL
                          AND followup_at <= (NOW() - INTERVAL '10 minutes')
                        LIMIT {lim}
                    )
                    """
                )
                logging.info("customer_services stamped missed_at: %s", result)

                # 2b) payments: overdue PENDING follow-ups (>10 min past followup_at) → MISSED (+ missed_at)
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.payments
                       SET followup_status = 'MISSED',
                           missed_at = COALESCE(missed_at, NOW()),
                           updated_at = NOW()
                     WHERE id IN (
                        SELECT id
                          FROM {DB_SCHEMA}.payments
                         WHERE is_active IS TRUE
                           AND entity_type IN ('GST_FILING', 'GST_FILING_RETURN_DETAILS', 'CUSTOMER_SERVICE')
                           AND payment_status = 'PENDING'
                           AND followup_status = 'PENDING'
                           AND followup_at IS NOT NULL
                           AND NOW() > followup_at + INTERVAL '10 minutes'
                         LIMIT {lim}
                    )
                    """
                )
                logging.info("payments follow-ups marked MISSED (overdue): %s", result)

                # 2c) payments: MISSED rows still missing missed_at (edge cases)
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.payments
                       SET missed_at = NOW(),
                           updated_at = NOW()
                     WHERE id IN (
                        SELECT id
                          FROM {DB_SCHEMA}.payments
                         WHERE is_active IS TRUE
                           AND entity_type IN ('GST_FILING', 'GST_FILING_RETURN_DETAILS', 'CUSTOMER_SERVICE')
                           AND payment_status = 'PENDING'
                           AND followup_status = 'MISSED'
                           AND missed_at IS NULL
                           AND followup_at IS NOT NULL
                           AND followup_at <= (NOW() - INTERVAL '10 minutes')
                         LIMIT {lim}
                    )
                    """
                )
                logging.info("payments stamped missed_at: %s", result)

                # 3) Mark overdue CRM lead followups as MISSED
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.crm_leads
                    SET follow_up_status = 'MISSED',
                        updated_at = NOW()
                    WHERE id IN (
                        SELECT id
                        FROM {DB_SCHEMA}.crm_leads
                        WHERE is_active = TRUE
                          AND follow_up_status = 'PENDING'
                          AND followup_at IS NOT NULL
                          AND followup_at < NOW()
                        LIMIT {lim}
                    )
                    """
                )
                logging.info("CRM leads marked MISSED by followup time: %s", result)

                # 4) Stamp missed_at for MISSED CRM lead followups after 10 minutes
                result = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.crm_leads
                    SET missed_at = NOW(),
                        updated_at = NOW()
                    WHERE id IN (
                        SELECT id
                        FROM {DB_SCHEMA}.crm_leads
                        WHERE is_active = TRUE
                          AND follow_up_status = 'MISSED'
                          AND missed_at IS NULL
                          AND followup_at IS NOT NULL
                          AND followup_at <= (NOW() - INTERVAL '10 minutes')
                        LIMIT {lim}
                    )
                    """
                )
                logging.info("CRM leads stamped missed_at: %s", result)

                # 5) Expire session tokens
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.session_token
                    SET is_active = FALSE
                    WHERE id IN (
                        SELECT id
                        FROM {DB_SCHEMA}.session_token
                        WHERE is_active = TRUE
                          AND expires_at IS NOT NULL
                          AND expires_at < NOW()
                        LIMIT {lim}
                    )
                    """
                )

                # 6) Expire customer OTPs
                otp_expired = await _expire_customer_otps(conn)
                _otp_n = otp_expired.split()[-1] if otp_expired else "0"
                if _otp_n.isdigit() and int(_otp_n) > 0:
                    logging.info("Customer OTPs expired by scheduler: %s", otp_expired)

                # 7) GST return-detail: NOT_FILED -> MISSED when due date has passed
                overdue_status = await _mark_overdue_gst_return_statuses(conn)
                _n = overdue_status.split()[-1] if overdue_status else "0"
                if _n.isdigit() and int(_n) > 0:
                    logging.info(
                        "GST return-detail rows updated (NOT_FILED -> MISSED where due < now): %s",
                        overdue_status,
                    )

                # 8) Turn off auto-generation when MISSED-period thresholds are exceeded
                disabled_ids = await disable_gst_filings_auto_over_missed_threshold(conn, lim)
                if disabled_ids:
                    logging.info(
                        "GST filings auto-disabled (MISSED threshold): count=%s ids=%s",
                        len(disabled_ids),
                        disabled_ids,
                    )

                # 9) GSTR-9C on YEARLY rows ↔ parent filing turnover_details (post-edit / data drift)
                n9c_add, n9c_clear = await _sync_gstr9c_with_parent_turnover(conn)
                if n9c_add or n9c_clear:
                    logging.info(
                        "GST GSTR-9C turnover sync: rows_with_9c_added=%s rows_with_9c_cleared=%s",
                        n9c_add,
                        n9c_clear,
                    )

                # 10) Auto-generate next GST filing return detail rows
                generated = await _run_gst_filing_auto_generation(conn)
                if generated:
                    logging.info("Auto generated gst filing return-detail rows: %s", generated)

                # 11) ITR: FILED + PAID → SUBSCRIBED (pay-first-then-file catch-up; triggers unchanged)
                itr_subscribed = await _sync_itr_crm_subscribed_when_filed_and_paid(conn)
                if itr_subscribed:
                    logging.info(
                        "CRM ITR leads promoted to SUBSCRIBED (filed + paid): count=%s",
                        itr_subscribed,
                    )

                # 12) Payments: close superseded PENDING rows when entity is PAID
                pay_sync = await sync_settled_payment_entities(conn, batch_limit=lim)
                if any(pay_sync.values()):
                    await redis_invalidate_tag("registration_payments:filter:index")
                    await redis_invalidate_tag("payments_config:get_amount:index")
                    logging.info(
                        "Payment entity settlement sync: duplicate_paid_demoted=%s "
                        "latest_promoted_to_paid=%s superseded_pending_closed=%s",
                        pay_sync["duplicate_paid_demoted"],
                        pay_sync["latest_promoted_to_paid"],
                        pay_sync["superseded_pending_closed"],
                    )

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
