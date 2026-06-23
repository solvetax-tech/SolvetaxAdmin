/**
 * CRM dashboard follow-up KPI rules (6 analytics cards only).
 * Aligned with main follow-ups /counts via normalizeFollowupStatusFields(useCountsSemantics).
 */
import {
    computeFollowupDashboardStats,
    formatFollowupDateKey,
    normalizeFollowupStatusFields,
} from './followupsApi';

/** Whether a lead counts toward Scheduled for the selected date(s). */
export function isScheduledFollowupForDates(item, dateKeys = null) {
    if (!item?.followup_at) return false;
    if (!dateKeys?.length) return true;
    const key = formatFollowupDateKey(item.followup_at);
    return dateKeys.includes(key);
}

/**
 * Aggregate the 6 CRM dashboard KPI metrics from lead rows (client fallback).
 * Uses the same rules as computeFollowupDashboardStats in followupsApi.js.
 */
export function computeCrmFollowupKpiStats(items, dateKeys = null) {
    return computeFollowupDashboardStats(items, dateKeys);
}

/** Stat-card list filter (analytics cards only). */
export function matchesCrmFollowupKpiFilter(item, filter) {
    if (!filter || filter === 'ALL' || filter === 'SCHEDULED') return true;

    const m = normalizeFollowupStatusFields(item, { useCountsSemantics: true });

    if (filter === 'COMPLETED') return m.isOnTimeCompleted;
    if (filter === 'OVERDUE_PENDING') return m.isOverduePending;
    if (filter === 'OVERDUE_COMPLETED') return m.isOverdueCompleted;
    if (filter === 'PENDING') return m.isPending;
    if (filter === 'OVERDUE') {
        return m.isOverduePending || m.isMissedOpen || m.isOverdueCompleted;
    }
    return true;
}
