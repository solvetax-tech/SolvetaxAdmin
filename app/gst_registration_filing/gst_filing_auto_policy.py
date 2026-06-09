"""
Rules for turning off GST return auto-generation when MISSED thresholds are exceeded,
and for blocking API re-enable until counts are back under policy.

Counting (matches how return-detail rows are seeded):
- **Regular RETURN (monthly/quarterly):** One row holds both GSTR-1 and GSTR-3B. That row counts as **one**
  periodic missed period if either return is MISSED (still one COUNT row).
  GSTR-9 / GSTR-9C on annual row(s): if only GSTR-9 is applicable, **GSTR-9 MISSED** counts; if only GSTR-9C,
  **GSTR-9C MISSED** counts; if **both** are applicable (turnover-based 9C), **both** must be MISSED (same idea as
  needing the full annual obligation missed before it counts as one annual missed period).
- **Composition RETURN:** CMP-08 rows → **periodic** bucket (>= 3 disables). GSTR-4 row(s) → **annual** (>= 1 disables).
- **ANNUAL + YEARLY only:** Regular → GSTR-9 / GSTR-9C only (annual bucket, >= 1). Composition → GSTR-4 only.
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.utils import DB_SCHEMA

# For alias `d` = gst_filing_return_details. Applicability = status or due present (matches seeded rows).
_REGULAR_ANNUAL_GSTR9_GSTR9C_MISSED_SQL = """
(
    (
        (d.gstr9_status IS NOT NULL OR d.gstr9_due_date IS NOT NULL)
        AND (d.gstr9c_status IS NOT NULL OR d.gstr9c_due_date IS NOT NULL)
        AND d.gstr9_status = 'MISSED'
        AND d.gstr9c_status = 'MISSED'
    )
    OR (
        (d.gstr9_status IS NOT NULL OR d.gstr9_due_date IS NOT NULL)
        AND NOT (d.gstr9c_status IS NOT NULL OR d.gstr9c_due_date IS NOT NULL)
        AND d.gstr9_status = 'MISSED'
    )
    OR (
        NOT (d.gstr9_status IS NOT NULL OR d.gstr9_due_date IS NOT NULL)
        AND (d.gstr9c_status IS NOT NULL OR d.gstr9c_due_date IS NOT NULL)
        AND d.gstr9c_status = 'MISSED'
    )
)
""".strip()


def should_disable_auto_for_missed_counts(
    filing_category: Optional[str],
    filing_frequency: Optional[str],
    taxpayer_type: Optional[str],
    periodic_missed: int,
    annual_missed: int,
) -> bool:
    """
    True if auto-generation should stay off / re-enable should be blocked.
    """
    cat = (filing_category or "").strip().upper()
    freq = (filing_frequency or "").strip().upper()
    ttype = (taxpayer_type or "").strip().upper()

    if cat == "ANNUAL" and freq == "YEARLY":
        return annual_missed >= 1

    if cat == "RETURN" and ttype == "REGULAR" and freq in ("MONTHLY", "QUARTERLY"):
        return periodic_missed >= 3 or annual_missed >= 1

    if cat == "RETURN" and ttype == "COMPOSITION":
        return periodic_missed >= 3 or annual_missed >= 1

    return False


async def missed_bucket_counts_for_filing(
    conn,
    filing_id: int,
    filing_category: Optional[str],
    filing_frequency: Optional[str],
    taxpayer_type: Optional[str],
) -> Tuple[int, int]:
    """
    Classify active return-detail rows into periodic vs annual MISSED buckets using the **given**
    filing profile (so PATCH can evaluate the post-update category / frequency / taxpayer_type).
    """
    cat = (filing_category or "").strip().upper()
    freq = (filing_frequency or "").strip().upper()
    ttype = (taxpayer_type or "").strip().upper()

    row = await conn.fetchrow(
        f"""
        SELECT
            COALESCE(
                COUNT(*) FILTER (
                    WHERE CASE
                        WHEN $2 = 'REGULAR' AND $3 = 'RETURN'
                             AND $4 IN ('MONTHLY', 'QUARTERLY') THEN
                            d.gstr1_status = 'MISSED' OR d.gstr3b_status = 'MISSED'
                        WHEN $2 = 'COMPOSITION' AND $3 = 'RETURN' THEN
                            d.cmp08_status = 'MISSED'
                        ELSE FALSE
                    END
                ),
                0
            )::int AS periodic_missed,
            COALESCE(
                COUNT(*) FILTER (
                    WHERE CASE
                        WHEN $2 = 'REGULAR' AND $3 = 'RETURN'
                             AND $4 IN ('MONTHLY', 'QUARTERLY') THEN
                            {_REGULAR_ANNUAL_GSTR9_GSTR9C_MISSED_SQL}
                        WHEN $2 = 'COMPOSITION' AND $3 = 'RETURN' THEN
                            d.gstr4_status = 'MISSED'
                        WHEN $2 = 'REGULAR' AND $3 = 'ANNUAL' AND $4 = 'YEARLY' THEN
                            {_REGULAR_ANNUAL_GSTR9_GSTR9C_MISSED_SQL}
                        WHEN $2 = 'COMPOSITION' AND $3 = 'ANNUAL' AND $4 = 'YEARLY' THEN
                            d.gstr4_status = 'MISSED'
                        ELSE FALSE
                    END
                ),
                0
            )::int AS annual_missed
        FROM {DB_SCHEMA}.gst_filing_return_details d
        WHERE d.gst_filing_id = $1 AND d.is_active = TRUE
        """,
        filing_id,
        ttype,
        cat,
        freq,
    )
    return int(row["periodic_missed"]), int(row["annual_missed"])


async def auto_enable_blocked_by_missed(
    conn,
    filing_id: int,
    filing_category: Optional[str],
    filing_frequency: Optional[str],
    taxpayer_type: Optional[str],
) -> bool:
    p, a = await missed_bucket_counts_for_filing(
        conn, filing_id, filing_category, filing_frequency, taxpayer_type
    )
    return should_disable_auto_for_missed_counts(
        filing_category, filing_frequency, taxpayer_type, p, a
    )


async def disable_gst_filings_auto_over_missed_threshold(conn, limit: int) -> list[int]:
    """
    Sets is_auto_enabled = FALSE on filings that exceed MISSED policy. Uses gst_filings columns
    as source of truth. Returns updated filing ids (batched).
    """
    lim = int(limit)
    rows = await conn.fetch(
        f"""
        WITH candidates AS (
            SELECT DISTINCT f.id AS filing_id
            FROM {DB_SCHEMA}.gst_filings f
            INNER JOIN {DB_SCHEMA}.gst_filing_return_details d
                ON d.gst_filing_id = f.id
            WHERE f.is_active = TRUE
              AND f.is_auto_enabled = TRUE
              AND d.is_active = TRUE
              AND (
                  d.gstr1_status = 'MISSED'
                  OR d.gstr3b_status = 'MISSED'
                  OR d.gstr9_status = 'MISSED'
                  OR d.gstr9c_status = 'MISSED'
                  OR d.cmp08_status = 'MISSED'
                  OR d.gstr4_status = 'MISSED'
              )
        ),
        filing_metrics AS (
            SELECT
                f.id AS filing_id,
                COALESCE(
                    COUNT(*) FILTER (
                        WHERE d.is_active = TRUE
                          AND CASE
                              WHEN f.taxpayer_type = 'REGULAR'
                                   AND f.filing_category = 'RETURN'
                                   AND f.filing_frequency IN ('MONTHLY', 'QUARTERLY') THEN
                                  d.gstr1_status = 'MISSED' OR d.gstr3b_status = 'MISSED'
                              WHEN f.taxpayer_type = 'COMPOSITION'
                                   AND f.filing_category = 'RETURN' THEN
                                  d.cmp08_status = 'MISSED'
                              ELSE FALSE
                          END
                    ),
                    0
                )::int AS periodic_missed,
                COALESCE(
                    COUNT(*) FILTER (
                        WHERE d.is_active = TRUE
                          AND CASE
                              WHEN f.taxpayer_type = 'REGULAR'
                                   AND f.filing_category = 'RETURN'
                                   AND f.filing_frequency IN ('MONTHLY', 'QUARTERLY') THEN
                                  {_REGULAR_ANNUAL_GSTR9_GSTR9C_MISSED_SQL}
                              WHEN f.taxpayer_type = 'COMPOSITION'
                                   AND f.filing_category = 'RETURN' THEN
                                  d.gstr4_status = 'MISSED'
                              WHEN f.filing_category = 'ANNUAL'
                                   AND f.filing_frequency = 'YEARLY'
                                   AND f.taxpayer_type = 'REGULAR' THEN
                                  {_REGULAR_ANNUAL_GSTR9_GSTR9C_MISSED_SQL}
                              WHEN f.filing_category = 'ANNUAL'
                                   AND f.filing_frequency = 'YEARLY'
                                   AND f.taxpayer_type = 'COMPOSITION' THEN
                                  d.gstr4_status = 'MISSED'
                              ELSE FALSE
                          END
                    ),
                    0
                )::int AS annual_missed
            FROM {DB_SCHEMA}.gst_filings f
            INNER JOIN candidates c ON c.filing_id = f.id
            LEFT JOIN {DB_SCHEMA}.gst_filing_return_details d ON d.gst_filing_id = f.id
            WHERE f.is_active = TRUE AND f.is_auto_enabled = TRUE
            GROUP BY f.id, f.filing_category, f.filing_frequency, f.taxpayer_type
        ),
        to_disable AS (
            SELECT fm.filing_id AS id
            FROM filing_metrics fm
            INNER JOIN {DB_SCHEMA}.gst_filings ff ON ff.id = fm.filing_id
            WHERE ff.is_active = TRUE
              AND ff.is_auto_enabled = TRUE
              AND (
                  (
                      ff.filing_category = 'ANNUAL'
                      AND ff.filing_frequency = 'YEARLY'
                      AND ff.taxpayer_type = 'REGULAR'
                      AND fm.annual_missed >= 1
                  )
                  OR (
                      ff.filing_category = 'ANNUAL'
                      AND ff.filing_frequency = 'YEARLY'
                      AND ff.taxpayer_type = 'COMPOSITION'
                      AND fm.annual_missed >= 1
                  )
                  OR (
                      ff.filing_category = 'RETURN'
                      AND ff.taxpayer_type = 'REGULAR'
                      AND ff.filing_frequency IN ('MONTHLY', 'QUARTERLY')
                      AND (fm.periodic_missed >= 3 OR fm.annual_missed >= 1)
                  )
                  OR (
                      ff.filing_category = 'RETURN'
                      AND ff.taxpayer_type = 'COMPOSITION'
                      AND (fm.periodic_missed >= 3 OR fm.annual_missed >= 1)
                  )
              )
            LIMIT {lim}
        )
        UPDATE {DB_SCHEMA}.gst_filings f
        SET is_auto_enabled = FALSE,
            updated_at = NOW()
        FROM to_disable td
        WHERE f.id = td.id
        RETURNING f.id
        """
    )
    return [int(r["id"]) for r in rows]
