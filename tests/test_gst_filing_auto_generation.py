"""
Exhaustive unit tests for GST return-detail auto-generation helpers.

Covers every return form (GSTR-1, GSTR-3B, GSTR-9, GSTR-9C, CMP-08, GSTR-4),
all cadences (MONTHLY / QUARTERLY / YEARLY), turnover-based GSTR-9C, lead-time
buffer for next_auto_generate_at, month-end clamping, and multi-step chains.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.gst_registration_filing.gst_filing_auto_generation import (
    build_next_row_from_source,
    chain_filing_frequency,
    gstr9c_sync_category_sql,
    lead_days_for_cadence_months,
    resolve_row_filing_frequency,
)

UTC = timezone.utc


def dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


# ---------------------------------------------------------------------------
# lead_days_for_cadence_months
# ---------------------------------------------------------------------------


class TestLeadDays:
    def test_monthly_quarterly_yearly(self):
        assert lead_days_for_cadence_months(1) == 10
        assert lead_days_for_cadence_months(3) == 12
        assert lead_days_for_cadence_months(12) == 7

    @pytest.mark.parametrize("cadence", [0, 2, 6, 24, 99])
    def test_unknown_cadence_defaults_to_seven(self, cadence):
        assert lead_days_for_cadence_months(cadence) == 7


# ---------------------------------------------------------------------------
# gstr9c_sync_category_sql
# ---------------------------------------------------------------------------


class TestGstr9cSyncSql:
    def test_includes_return_and_annual(self):
        sql = gstr9c_sync_category_sql("f.filing_category")
        assert "RETURN" in sql
        assert "ANNUAL" in sql
        assert "UPPER(TRIM(f.filing_category)) IN" in sql

    def test_custom_column_alias(self):
        sql = gstr9c_sync_category_sql("f2.filing_category")
        assert "f2.filing_category" in sql


# ---------------------------------------------------------------------------
# resolve_row_filing_frequency
# ---------------------------------------------------------------------------


class TestResolveRowFilingFrequency:
    def test_detail_column_wins_over_parent(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "parent_filing_frequency": "MONTHLY",
            "gstr1_due_date": dt(2026, 4, 11),
        }
        assert resolve_row_filing_frequency(src) == "YEARLY"

    def test_parent_monthly_with_gstr1_gstr3b(self):
        src = {
            "parent_filing_frequency": "MONTHLY",
            "gstr1_status": "NOT_FILED",
            "gstr1_due_date": dt(2026, 3, 11),
            "gstr3b_due_date": dt(2026, 3, 20),
        }
        assert resolve_row_filing_frequency(src) == "MONTHLY"

    def test_parent_quarterly_with_cmp08_only(self):
        src = {
            "parent_filing_frequency": "QUARTERLY",
            "cmp08_status": "NOT_FILED",
            "cmp08_due_date": dt(2026, 2, 18),
        }
        assert resolve_row_filing_frequency(src) == "QUARTERLY"

    def test_parent_monthly_but_row_is_yearly_gstr9_band(self):
        """REGULAR RETURN: parent is MONTHLY but this row is the GSTR-9 companion."""
        src = {
            "parent_filing_frequency": "MONTHLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2026, 1, 31),
        }
        assert resolve_row_filing_frequency(src) == "YEARLY"

    def test_gstr4_composition_annual_only(self):
        src = {
            "parent_filing_frequency": "YEARLY",
            "gstr4_status": "NOT_FILED",
            "gstr4_due_date": dt(2026, 1, 30),
        }
        assert resolve_row_filing_frequency(src) == "YEARLY"

    def test_legacy_auto_row_no_filing_frequency_columns(self):
        src = {
            "gstr1_status": "MISSED",
            "gstr1_due_date": dt(2026, 5, 11),
            "gstr3b_status": "MISSED",
            "gstr3b_due_date": dt(2026, 5, 20),
        }
        assert resolve_row_filing_frequency(src) == "MONTHLY"

    def test_empty_row_defaults_yearly(self):
        assert resolve_row_filing_frequency({}) == "YEARLY"

    def test_gstr9c_only_row(self):
        src = {
            "gstr9c_status": "NOT_FILED",
            "gstr9c_due_date": dt(2026, 1, 31),
        }
        assert resolve_row_filing_frequency(src) == "YEARLY"


# ---------------------------------------------------------------------------
# chain_filing_frequency
# ---------------------------------------------------------------------------


class TestChainFilingFrequency:
    def test_prefers_next_row_frequency(self):
        src = {"detail_filing_frequency": "QUARTERLY"}
        nxt = {"filing_frequency": "MONTHLY"}
        assert chain_filing_frequency(src, nxt) == "MONTHLY"

    def test_falls_back_to_resolve_without_next_row(self):
        src = {
            "detail_filing_frequency": "QUARTERLY",
            "cmp08_due_date": dt(2026, 2, 18),
            "cmp08_status": "NOT_FILED",
        }
        assert chain_filing_frequency(src) == "QUARTERLY"


# ---------------------------------------------------------------------------
# GSTR-1 / GSTR-3B — MONTHLY
# ---------------------------------------------------------------------------


class TestMonthlyGstr1Gstr3b:
    def test_shifts_one_month_resets_status_to_not_filed(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_status": "MISSED",
            "gstr1_due_date": dt(2026, 4, 11),
            "gstr3b_status": "FILED",
            "gstr3b_due_date": dt(2026, 4, 20),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "MONTHLY"
        assert nxt["gstr1_status"] == "NOT_FILED"
        assert nxt["gstr3b_status"] == "NOT_FILED"
        assert nxt["gstr1_due_date"] == dt(2026, 5, 11)
        assert nxt["gstr3b_due_date"] == dt(2026, 5, 20)
        assert nxt["gstr9_status"] is None
        assert nxt["cmp08_status"] is None
        assert nxt["gstr4_status"] is None

    def test_next_auto_uses_earliest_due_minus_10_days(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_due_date": dt(2026, 4, 11),
            "gstr1_status": "NOT_FILED",
            "gstr3b_due_date": dt(2026, 4, 20),
            "gstr3b_status": "NOT_FILED",
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["next_auto_generate_at"] == dt(2026, 5, 11) - timedelta(days=10)

    def test_gstr1_only_row(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_status": "NOT_FILED",
            "gstr1_due_date": dt(2026, 6, 11),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr1_due_date"] == dt(2026, 7, 11)
        assert nxt["gstr3b_status"] is None
        assert nxt["gstr3b_due_date"] is None

    def test_gstr3b_only_row(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr3b_status": "OVERDUE",
            "gstr3b_due_date": dt(2026, 6, 20),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr3b_status"] == "NOT_FILED"
        assert nxt["gstr3b_due_date"] == dt(2026, 7, 20)
        assert nxt["gstr1_status"] is None

    @pytest.mark.parametrize(
        "start,expected_day,expected_month",
        [
            (dt(2026, 1, 31), 28, 2),
            (dt(2024, 1, 31), 29, 2),  # leap year
            (dt(2026, 3, 31), 30, 4),
            (dt(2026, 12, 15), 15, 1),  # year rollover
        ],
    )
    def test_month_end_and_year_rollover(self, start, expected_day, expected_month):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_status": "NOT_FILED",
            "gstr1_due_date": start,
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr1_due_date"].day == expected_day
        assert nxt["gstr1_due_date"].month == expected_month


# ---------------------------------------------------------------------------
# GSTR-1 / GSTR-3B — QUARTERLY
# ---------------------------------------------------------------------------


class TestQuarterlyGstr1Gstr3b:
    def test_shifts_three_months(self):
        src = {
            "detail_filing_frequency": "QUARTERLY",
            "gstr1_status": "FILED",
            "gstr1_due_date": dt(2026, 1, 13),
            "gstr3b_status": "NOT_FILED",
            "gstr3b_due_date": dt(2026, 1, 22),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "QUARTERLY"
        assert nxt["gstr1_due_date"] == dt(2026, 4, 13)
        assert nxt["gstr3b_due_date"] == dt(2026, 4, 22)
        assert nxt["next_auto_generate_at"] == dt(2026, 4, 13) - timedelta(days=12)


# ---------------------------------------------------------------------------
# CMP-08 — QUARTERLY
# ---------------------------------------------------------------------------


class TestQuarterlyCmp08:
    def test_shifts_three_months(self):
        src = {
            "detail_filing_frequency": "QUARTERLY",
            "cmp08_status": "MISSED",
            "cmp08_due_date": dt(2026, 2, 18),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "QUARTERLY"
        assert nxt["cmp08_status"] == "NOT_FILED"
        assert nxt["cmp08_due_date"] == dt(2026, 5, 18)
        assert nxt["gstr1_status"] is None
        assert nxt["next_auto_generate_at"] == dt(2026, 5, 18) - timedelta(days=12)


# ---------------------------------------------------------------------------
# GSTR-9 / GSTR-9C — YEARLY
# ---------------------------------------------------------------------------


class TestYearlyGstr9Gstr9c:
    def test_shifts_twelve_months(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2026, 1, 31),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "YEARLY"
        assert nxt["gstr9_due_date"] == dt(2027, 1, 31)
        assert nxt["next_auto_generate_at"] == dt(2027, 1, 31) - timedelta(days=7)

    def test_adds_gstr9c_when_turnover_more_than_5cr(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2026, 1, 31),
        }
        nxt = build_next_row_from_source(src, "MORE_THAN_5CR")
        assert nxt["gstr9c_status"] == "NOT_FILED"
        assert nxt["gstr9c_due_date"] == dt(2027, 1, 31)

    @pytest.mark.parametrize("turnover", [None, "", "UPTO_5CR", "upto_5cr", "LESS_THAN_5CR"])
    def test_no_gstr9c_when_turnover_not_high(self, turnover):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2026, 1, 31),
        }
        nxt = build_next_row_from_source(src, turnover)
        assert nxt["gstr9c_status"] is None
        assert nxt["gstr9c_due_date"] is None

    def test_turnover_case_insensitive(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2026, 1, 31),
        }
        nxt = build_next_row_from_source(src, "  more_than_5cr  ")
        assert nxt["gstr9c_status"] == "NOT_FILED"

    def test_existing_gstr9c_shifts_both_does_not_duplicate(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_status": "FILED",
            "gstr9_due_date": dt(2025, 1, 31),
            "gstr9c_status": "FILED",
            "gstr9c_due_date": dt(2025, 1, 31),
        }
        nxt = build_next_row_from_source(src, "MORE_THAN_5CR")
        assert nxt["gstr9_due_date"] == dt(2026, 1, 31)
        assert nxt["gstr9c_due_date"] == dt(2026, 1, 31)
        assert nxt["gstr9_status"] == "NOT_FILED"
        assert nxt["gstr9c_status"] == "NOT_FILED"

    def test_gstr9c_only_source_shifts(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9c_status": "NOT_FILED",
            "gstr9c_due_date": dt(2026, 1, 31),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr9c_due_date"] == dt(2027, 1, 31)
        assert nxt["gstr9_status"] is None


# ---------------------------------------------------------------------------
# GSTR-4 — YEARLY (composition)
# ---------------------------------------------------------------------------


class TestYearlyGstr4:
    def test_shifts_twelve_months(self):
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr4_status": "NOT_FILED",
            "gstr4_due_date": dt(2026, 1, 30),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "YEARLY"
        assert nxt["gstr4_due_date"] == dt(2027, 1, 30)
        assert nxt["cmp08_status"] is None
        assert nxt["next_auto_generate_at"] == dt(2027, 1, 30) - timedelta(days=7)


# ---------------------------------------------------------------------------
# Cadence isolation (GSTR-9 yearly band vs GSTR-1 monthly band)
# ---------------------------------------------------------------------------


class TestCadenceIsolation:
    def test_gstr9_row_uses_yearly_cadence_despite_parent_monthly(self):
        """Companion annual row must +12 months even when parent filing is MONTHLY."""
        src = {
            "detail_filing_frequency": "YEARLY",
            "parent_filing_frequency": "MONTHLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2025, 1, 31),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "YEARLY"
        assert nxt["gstr9_due_date"] == dt(2026, 1, 31)
        assert chain_filing_frequency(src, nxt) == "YEARLY"

    def test_monthly_row_not_affected_by_gstr9_columns(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_due_date": dt(2026, 3, 11),
            "gstr1_status": "NOT_FILED",
            "gstr3b_due_date": dt(2026, 3, 20),
            "gstr3b_status": "NOT_FILED",
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "MONTHLY"
        assert nxt["gstr1_due_date"] == dt(2026, 4, 11)


# ---------------------------------------------------------------------------
# Multi-step chains (simulate scheduler running twice)
# ---------------------------------------------------------------------------


class TestMultiStepChain:
    def test_three_monthly_hops(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_status": "NOT_FILED",
            "gstr1_due_date": dt(2026, 1, 11),
            "gstr3b_status": "NOT_FILED",
            "gstr3b_due_date": dt(2026, 1, 20),
        }
        hop1 = build_next_row_from_source(src, None)
        assert hop1["gstr1_due_date"] == dt(2026, 2, 11)

        hop1_src = {
            **src,
            "detail_filing_frequency": hop1["filing_frequency"],
            "gstr1_due_date": hop1["gstr1_due_date"],
            "gstr3b_due_date": hop1["gstr3b_due_date"],
            "gstr1_status": hop1["gstr1_status"],
            "gstr3b_status": hop1["gstr3b_status"],
        }
        hop2 = build_next_row_from_source(hop1_src, None)
        assert hop2["gstr1_due_date"] == dt(2026, 3, 11)

        hop2_src = {**hop1_src, "gstr1_due_date": hop2["gstr1_due_date"], "gstr3b_due_date": hop2["gstr3b_due_date"]}
        hop3 = build_next_row_from_source(hop2_src, None)
        assert hop3["gstr1_due_date"] == dt(2026, 4, 11)

    def test_two_quarterly_cmp08_hops(self):
        src = {
            "detail_filing_frequency": "QUARTERLY",
            "cmp08_status": "NOT_FILED",
            "cmp08_due_date": dt(2026, 2, 18),
        }
        hop1 = build_next_row_from_source(src, None)
        assert hop1["cmp08_due_date"] == dt(2026, 5, 18)

        hop1_src = {**src, "cmp08_due_date": hop1["cmp08_due_date"], "cmp08_status": hop1["cmp08_status"]}
        hop2 = build_next_row_from_source(hop1_src, None)
        assert hop2["cmp08_due_date"] == dt(2026, 8, 18)

    def test_yearly_gstr9_two_hops_with_9c_on_second(self):
        """First hop: no 9C on source. Second hop: turnover adds 9C on shifted row."""
        src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_status": "NOT_FILED",
            "gstr9_due_date": dt(2025, 1, 31),
        }
        hop1 = build_next_row_from_source(src, None)
        assert hop1["gstr9c_status"] is None

        hop1_src = {
            **src,
            "gstr9_due_date": hop1["gstr9_due_date"],
            "gstr9_status": hop1["gstr9_status"],
        }
        hop2 = build_next_row_from_source(hop1_src, "MORE_THAN_5CR")
        assert hop2["gstr9_due_date"] == dt(2027, 1, 31)
        assert hop2["gstr9c_status"] == "NOT_FILED"
        assert hop2["gstr9c_due_date"] == dt(2027, 1, 31)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_applicable_forms_all_null_no_next_auto(self):
        src = {"detail_filing_frequency": "MONTHLY"}
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr1_status"] is None
        assert nxt["gstr3b_status"] is None
        assert nxt["gstr9_status"] is None
        assert nxt["gstr9c_status"] is None
        assert nxt["cmp08_status"] is None
        assert nxt["gstr4_status"] is None
        assert nxt["next_auto_generate_at"] is None

    def test_applicable_by_due_date_only_no_status(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_due_date": dt(2026, 4, 11),
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr1_status"] == "NOT_FILED"
        assert nxt["gstr1_due_date"] == dt(2026, 5, 11)

    def test_applicable_by_status_only_no_due_shifts_none(self):
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_status": "NOT_FILED",
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["gstr1_status"] == "NOT_FILED"
        assert nxt["gstr1_due_date"] is None
        assert nxt["next_auto_generate_at"] is None

    def test_parallel_chain_keys_differ_on_same_filing(self):
        """MONTHLY GSTR-1/3B band vs YEARLY GSTR-9 band get different chain keys."""
        monthly_src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_due_date": dt(2026, 4, 11),
            "gstr1_status": "NOT_FILED",
        }
        yearly_src = {
            "detail_filing_frequency": "YEARLY",
            "gstr9_due_date": dt(2026, 1, 31),
            "gstr9_status": "NOT_FILED",
        }
        monthly_nxt = build_next_row_from_source(monthly_src, None)
        yearly_nxt = build_next_row_from_source(yearly_src, None)
        assert chain_filing_frequency(monthly_src, monthly_nxt) == "MONTHLY"
        assert chain_filing_frequency(yearly_src, yearly_nxt) == "YEARLY"

    def test_all_six_forms_present_only_matching_band_shifts(self):
        """
        Row should not exist in production with all six forms, but cadence must
        pick GSTR-9 band (+12) when GSTR-9 due is present.
        """
        src = {
            "detail_filing_frequency": "MONTHLY",
            "gstr1_due_date": dt(2026, 4, 11),
            "gstr1_status": "NOT_FILED",
            "gstr3b_due_date": dt(2026, 4, 20),
            "gstr3b_status": "NOT_FILED",
            "gstr9_due_date": dt(2026, 1, 31),
            "gstr9_status": "NOT_FILED",
            "cmp08_due_date": dt(2026, 2, 18),
            "cmp08_status": "NOT_FILED",
            "gstr4_due_date": dt(2026, 1, 30),
            "gstr4_status": "NOT_FILED",
        }
        nxt = build_next_row_from_source(src, None)
        assert nxt["filing_frequency"] == "YEARLY"
        assert nxt["gstr9_due_date"] == dt(2027, 1, 31)
        assert nxt["gstr1_due_date"] == dt(2027, 4, 11)
        assert nxt["cmp08_due_date"] == dt(2027, 2, 18)
