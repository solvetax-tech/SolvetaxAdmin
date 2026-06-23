import api from './api';
import { unwrapCountsPayload, unwrapListPayload } from './apiResponse';

/** Live backend routes for follow-ups (filing-followups was removed). */
export const CUSTOMER_SERVICE_FOLLOWUPS_BASE = '/api/v1/customer-service-followups';
export const PAYMENT_FOLLOWUPS_BASE = '/api/v1/payment-followups';

/** UI labels → backend entity_type for payment follow-ups. */
export const PAYMENT_ENTITY_TYPE_MAP = {
    'GST Filing Payments': 'GST_FILING',
    'GST Return Payments': 'GST_FILING_RETURN_DETAILS',
    'Service Payments': 'CUSTOMER_SERVICE',
};

/** Page size for Scheduled Followups panels (main workspace + CRM dashboard). */
export const FOLLOWUP_SCHEDULE_PAGE_SIZE = 20;

/** Grace period after followup_at before missed_at / MISSED (matches backend scheduler). */
export const FOLLOWUP_MISSED_BUFFER_MS = 10 * 60 * 1000;

/** Statuses that still represent an open, not-yet-missed follow-up slot. */
const OPEN_FOLLOWUP_PENDING_STATUSES = new Set(['PENDING', 'OVERDUE', '']);

export function readFollowUpStatus(item = {}) {
    return String(
        item.follow_up_status ?? item.followup_status ?? item.status ?? item.activity_type ?? '',
    ).trim().toUpperCase();
}

export function isOpenPendingFollowUpStatus(status) {
    const normalized = String(status ?? '').trim().toUpperCase();
    return OPEN_FOLLOWUP_PENDING_STATUSES.has(normalized);
}

export function resolvePaymentEntityTypeCode(labelOrCode) {
    if (!labelOrCode) return undefined;
    const key = String(labelOrCode).trim();
    return PAYMENT_ENTITY_TYPE_MAP[key] || key;
}

/** Parse list API payload for pagination controls. */
export function getFollowupListMeta(response, requestedLimit = FOLLOWUP_SCHEDULE_PAGE_SIZE) {
    const { items, total, offset } = unwrapListPayload(response);
    const pageLimit = requestedLimit > 0 ? requestedLimit : FOLLOWUP_SCHEDULE_PAGE_SIZE;
    const hasMoreByTotal = total != null
        ? items.length > 0 && offset + items.length < total
        : false;
    return {
        rows: items,
        total,
        hasMore: hasMoreByTotal || items.length >= pageLimit,
    };
}

/** Map list row to the shape expected by Followups UI (status, entity_id, etc.). */
export function normalizeFollowupRow(item) {
    if (!item) return item;
    const status = item.status ?? item.followup_status ?? 'PENDING';
    return {
        ...item,
        status,
        followup_status: item.followup_status ?? status,
        entity_type: item.entity_type ?? 'CUSTOMER_SERVICE',
        entity_id: item.entity_id ?? item.customer_service_id ?? item.id,
        service_name: item.service_name ?? item.service_code,
    };
}

/** filing-followups used from_date/to_date; customer-service-followups uses followup_from/followup_to. */
export function mapFollowupListParams(params = {}) {
    const out = { ...params };
    if (out.from_date != null) {
        out.followup_from = out.from_date;
        delete out.from_date;
    }
    if (out.to_date != null) {
        out.followup_to = out.to_date;
        delete out.to_date;
    }
    delete out.today_only;
    delete out.is_overdue;
    delete out.search;
    delete out.entity_type;
    return out;
}

export function mapPaymentFollowupListParams(params = {}) {
    const out = { ...params };
    if (out.from_date != null) {
        out.followup_from = out.from_date;
        delete out.from_date;
    }
    if (out.to_date != null) {
        out.followup_to = out.to_date;
        delete out.to_date;
    }
    delete out.today_only;
    delete out.is_overdue;
    delete out.search;
    delete out.dates;
    return out;
}

function serializeFollowupQueryParams(params) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return;
        if (Array.isArray(value)) {
            value.forEach((v) => search.append(key, v));
        } else {
            search.append(key, value);
        }
    });
    return search.toString();
}

export function normalizePaymentFollowupRow(item) {
    if (!item) return item;
    const status = item.status ?? item.followup_status ?? 'PENDING';
    let label = 'Payment';
    if (item.entity_type === 'GST_FILING') label = 'GST Filing Payment';
    else if (item.entity_type === 'GST_FILING_RETURN_DETAILS') label = 'GST Return Payment';
    else if (item.entity_type === 'CUSTOMER_SERVICE') label = 'Service Payment';

    const displayLabel = item.amount ? `${label} (₹${item.amount})` : label;

    return {
        ...item,
        status,
        followup_status: item.followup_status ?? status,
        service_name: displayLabel,
        assigned_to_name: item.rm_name || item.op_name || 'System',
        customer_service_id: item.entity_id || item.id,
    };
}

export async function listPaymentFollowups(params = {}) {
    const response = await api.get(PAYMENT_FOLLOWUPS_BASE, {
        params: mapPaymentFollowupListParams(params),
        paramsSerializer: { serialize: serializeFollowupQueryParams },
    });
    const { items, total, limit, offset, requestId } = unwrapListPayload(response);
    const rows = items.map(normalizePaymentFollowupRow);
    return {
        ...response,
        data: {
            ...response.data,
            data: rows,
            total,
            limit,
            offset,
            request_id: requestId,
        },
    };
}

export async function getPaymentFollowupCounts(params = {}) {
    return api.get(`${PAYMENT_FOLLOWUPS_BASE}/counts`, { params });
}

export async function getPaymentFollowupAlerts() {
    const response = await api.get(`${PAYMENT_FOLLOWUPS_BASE}/alerts`);
    const rows = unwrapListPayload(response).items.map(normalizePaymentFollowupRow);
    return {
        ...response,
        data: {
            ...response.data,
            data: rows,
        },
    };
}

export async function schedulePaymentFollowup(body) {
    return api.post(PAYMENT_FOLLOWUPS_BASE, body);
}

export async function updatePaymentFollowup(paymentId, body) {
    return api.post(`${PAYMENT_FOLLOWUPS_BASE}/${paymentId}`, body);
}

export function mapCountsResponseToDashboardStats(data) {
    const counts = data && typeof data === 'object' ? data : {};
    return {
        scheduledToday: counts.scheduled_today ?? counts.scheduled_count ?? 0,
        overduePendingToday: counts.overdue_pending_today ?? counts.overdue_today ?? 0,
        overdueCompletedToday: counts.overdue_completed_today ?? 0,
        overdueToday: counts.overdue_pending_today ?? counts.overdue_today ?? 0,
        completedToday: counts.completed_today ?? counts.completed_count ?? 0,
        pendingToday: counts.pending_today ?? counts.pending_count ?? 0,
        successRate: counts.success_rate ?? 100,
    };
}

/** Local calendar date key (YYYY-MM-DD) for follow-up_at grouping. */
export function formatFollowupDateKey(dateInput) {
    if (!dateInput) return '';
    if (typeof dateInput === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dateInput)) {
        return dateInput;
    }
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

/** Min/max followup_from / followup_to window covering all selected local dates. */
export function buildFollowupRangeFromDates(selectedDates = []) {
    const dateKeys = (selectedDates?.length ? selectedDates : [formatFollowupDateKey(new Date())])
        .map(formatFollowupDateKey)
        .filter(Boolean)
        .sort();

    const [sy, sm, sd] = dateKeys[0].split('-').map(Number);
    const [ey, em, ed] = dateKeys[dateKeys.length - 1].split('-').map(Number);

    return {
        dateKeys,
        followup_from: new Date(sy, sm - 1, sd, 0, 0, 0).toISOString(),
        followup_to: new Date(ey, em - 1, ed, 23, 59, 59, 999).toISOString(),
    };
}

/** PENDING row with a future followup_at (rescheduled next slot; stale missed_at may remain). */
export function isActiveRescheduledPendingSlot(item = {}, now = new Date()) {
    const followUpStatus = String(
        item.follow_up_status ?? item.followup_status ?? item.status ?? '',
    ).trim().toUpperCase();
    const followupAt = item.followup_at || item.performed_at;
    if (followUpStatus !== 'PENDING' || !followupAt) return false;
    const dueMs = new Date(followupAt).getTime();
    return !Number.isNaN(dueMs) && dueMs > now.getTime();
}

/** True when follow-up time has passed but the 10-minute missed_at buffer has not. */
export function isInFollowupPendingUrgentWindow(item, now = new Date()) {
    const followupAt = item?.followup_at || item?.performed_at;
    if (!followupAt) return false;
    const dueMs = new Date(followupAt).getTime();
    if (Number.isNaN(dueMs)) return false;
    const nowMs = now.getTime();
    return nowMs >= dueMs && nowMs < dueMs + FOLLOWUP_MISSED_BUFFER_MS;
}

/**
 * Overdue (Pending) KPI: PENDING, current time past followup_at, missed_at not stamped yet.
 */
export function isOverduePendingFollowup(item = {}, now = new Date()) {
    if (isActiveRescheduledPendingSlot(item, now)) return false;

    const followUpStatus = readFollowUpStatus(item);
    if (!isOpenPendingFollowUpStatus(followUpStatus)) return false;
    if (item.missed_at) return false;
    if (item.completed_at) return false;

    const followupAt = item.followup_at || item.performed_at;
    if (!followupAt) return false;

    const dueMs = new Date(followupAt).getTime();
    return !Number.isNaN(dueMs) && dueMs < now.getTime();
}

/**
 * Open follow-up alert bucket for drawers/reminders (PENDING = due/overdue before missed stamp).
 */
export function resolveFollowupAlertStatus(item = {}) {
    if (!item?.followup_at) return null;

    const followUpStatus = readFollowUpStatus(item);
    if (followUpStatus === 'COMPLETED' || item.completed_at) return null;
    if (isActiveRescheduledPendingSlot(item)) return null;

    const m = normalizeFollowupStatusFields(item);
    if (m.isMissedOpen) return 'MISSED';
    if (m.isOverduePending || m.isPending || m.inUrgentWindow) return 'PENDING';

    const followupTime = new Date(item.followup_at).getTime();
    if (!Number.isNaN(followupTime) && followupTime > Date.now()) return 'PENDING';

    return 'PENDING';
}

/**
 * Normalize follow-up status fields for KPIs, filters, and activity badges.
 * Aligns with backend /counts + scheduler (10 min buffer before missed_at).
 * @param {boolean} useCountsSemantics — true for KPI/stat filters; false for looser list badges.
 */
export function normalizeFollowupStatusFields(item = {}, { useCountsSemantics = false } = {}) {
    const followUpStatus = readFollowUpStatus(item);

    let completedAt = item.completed_at || null;
    let missedAt = item.missed_at || null;

    if (followUpStatus === 'COMPLETED' && !completedAt) {
        completedAt = item.updated_at || item.performed_at || null;
    }

    const followupAt = item.followup_at || item.performed_at;
    const rescheduledPending = isActiveRescheduledPendingSlot(item);
    const isCompleted = followUpStatus === 'COMPLETED';
    const inUrgentWindow = isInFollowupPendingUrgentWindow(item);
    const overduePending = isOverduePendingFollowup(item);
    const isMissedOpen = !isCompleted
        && (followUpStatus === 'MISSED' || (Boolean(missedAt) && !rescheduledPending));

    let isOverduePending = false;
    let isOverdueCompleted = false;
    let isOnTimeCompleted = false;
    let isPending = false;

    if (useCountsSemantics) {
        isOverduePending = overduePending;
        isOverdueCompleted = isCompleted && Boolean(missedAt);
        isOnTimeCompleted = isCompleted && !missedAt;
        isPending = !isCompleted
            && !isMissedOpen
            && inUrgentWindow
            && (followUpStatus === 'PENDING' || followUpStatus === '');
    } else {
        isOverduePending = overduePending;
        isOverdueCompleted = isCompleted && Boolean(missedAt);
        isOnTimeCompleted = isCompleted && !missedAt;
        isPending = !isCompleted
            && !isMissedOpen
            && inUrgentWindow;
    }

    return {
        missedAt,
        completedAt,
        followupAt,
        followupPast: Boolean(followupAt && new Date(followupAt) < new Date() && !isCompleted),
        inUrgentWindow,
        isOnTimeCompleted,
        isOverdueCompleted,
        isOverduePending,
        isPending,
        isOverdue: isOverduePending || isOverdueCompleted,
        isMissedOpen,
        status: isCompleted
            ? 'COMPLETED'
            : (isMissedOpen ? 'MISSED' : (isOverduePending ? 'OVERDUE' : 'PENDING')),
    };
}

/** Activity card badge (main Follow Ups + CRM scheduled list). */
export function getFollowupActivityBadge(item = {}) {
    const m = normalizeFollowupStatusFields(item);
    if (m.isOnTimeCompleted) {
        return { statusBadgeClass: 'ontime', statusTextString: 'COMPLETED (ON-TIME)' };
    }
    if (m.isOverdueCompleted) {
        return { statusBadgeClass: 'late', statusTextString: 'COMPLETED (LATE)' };
    }
    if (m.isMissedOpen) {
        return { statusBadgeClass: 'missed', statusTextString: 'MISSED' };
    }
    if (m.isOverduePending) {
        return { statusBadgeClass: 'overdue', statusTextString: 'OVERDUE (PENDING)' };
    }
    if (m.inUrgentWindow) {
        return { statusBadgeClass: 'pending', statusTextString: 'PENDING (URGENT)' };
    }
    return { statusBadgeClass: 'pending', statusTextString: 'PENDING' };
}

/** Stat-card click filter (scheduled list rows). */
export function matchesFollowupStatFilter(item, filter) {
    if (!filter || filter === 'ALL' || filter === 'SCHEDULED') return true;
    const m = normalizeFollowupStatusFields(item, { useCountsSemantics: true });
    if (filter === 'COMPLETED') return m.isOnTimeCompleted;
    if (filter === 'OVERDUE_PENDING') return m.isOverduePending;
    if (filter === 'OVERDUE_COMPLETED') return m.isOverdueCompleted;
    if (filter === 'OVERDUE') {
        return m.isOverduePending || m.isMissedOpen || m.isOverdueCompleted;
    }
    if (filter === 'PENDING') return m.isPending;
    return true;
}

/**
 * Match backend /counts rules for follow-ups within dateKeys.
 */
export function computeFollowupDashboardStats(items, dateKeys = null) {
    const dateSet = dateKeys?.length
        ? new Set(dateKeys.map(formatFollowupDateKey))
        : null;

    let scheduled = 0;
    let overduePending = 0;
    let overdueCompleted = 0;
    let completed = 0;
    let successful = 0;
    let pending = 0;

    (items || []).forEach((item) => {
        if (!item?.followup_at) return;

        const itemDate = formatFollowupDateKey(item.followup_at);
        if (dateSet && !dateSet.has(itemDate)) return;

        scheduled += 1;

        const m = normalizeFollowupStatusFields(item, { useCountsSemantics: true });

        if (m.isOverdueCompleted) {
            overdueCompleted += 1;
        } else if (m.isOverduePending) {
            overduePending += 1;
        }

        if (m.isOnTimeCompleted) {
            completed += 1;
            successful += 1;
        }

        if (m.isPending) {
            pending += 1;
        }
    });

    const successRate = scheduled > 0 ? Math.round((successful / scheduled) * 100) : 100;

    return {
        scheduledToday: scheduled,
        overduePendingToday: overduePending,
        overdueCompletedToday: overdueCompleted,
        overdueToday: overduePending,
        completedToday: completed,
        pendingToday: pending,
        successRate,
    };
}

/** @deprecated Use computeFollowupDashboardStats */
export const computeCustomerServiceFollowupStats = computeFollowupDashboardStats;

/** Fetch payment follow-up dashboard KPIs from backend /counts for selected calendar dates. */
export async function fetchPaymentFollowupStats({ selectedDates, entityType } = {}) {
    const { dateKeys, followup_from, followup_to } = buildFollowupRangeFromDates(selectedDates);

    const params = {
        followup_from,
        followup_to,
        dates: dateKeys.join(','),
    };
    const entityNorm = resolvePaymentEntityTypeCode(entityType);
    if (entityNorm) {
        params.entity_type = entityNorm;
    }

    try {
        const res = await getPaymentFollowupCounts(params);
        const data = unwrapCountsPayload(res);
        return mapCountsResponseToDashboardStats(data);
    } catch (err) {
        console.warn('[followupsApi] payment counts failed, falling back to list aggregation:', err?.message);
        const listParams = { followup_from, followup_to, limit: 200 };
        if (entityNorm) {
            listParams.entity_type = entityNorm;
        }
        const listRes = await listPaymentFollowups(listParams);
        const rows = (listRes.data?.data ?? []).filter((item) => {
            if (!item?.followup_at) return false;
            return dateKeys.includes(formatFollowupDateKey(item.followup_at));
        });
        return computeFollowupDashboardStats(rows, dateKeys);
    }
}

/** All payment follow-ups in a calendar month (for day dots); paginates until complete. */
export async function fetchPaymentFollowupMonthItems({
    year,
    monthIndex = 0,
    entityType,
    maxRows = 2000,
} = {}) {
    const month = monthIndex + 1;
    const lastDay = new Date(year, month, 0).getDate();
    const dateKeys = Array.from({ length: lastDay }, (_, i) => {
        const d = i + 1;
        return `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    });
    const { followup_from, followup_to } = buildFollowupRangeFromDates(dateKeys);
    const entityNorm = resolvePaymentEntityTypeCode(entityType);
    const pageSize = 200;
    let offset = 0;
    const all = [];

    while (all.length < maxRows) {
        const params = { followup_from, followup_to, limit: pageSize, offset };
        if (entityNorm) {
            params.entity_type = entityNorm;
        }
        const res = await listPaymentFollowups(params);
        const meta = getFollowupListMeta(res, pageSize);
        all.push(...meta.rows);
        if (meta.total != null) {
            if (offset + meta.rows.length >= meta.total) break;
        } else if (meta.rows.length < pageSize) {
            break;
        }
        offset += pageSize;
    }

    return all;
}

/** All customer-service follow-ups in a calendar month (paginated; local date range). */
export async function fetchCustomerServiceFollowupMonthItems({
    year,
    monthIndex = 0,
    serviceCode,
    maxRows = 2000,
} = {}) {
    const month = monthIndex + 1;
    const lastDay = new Date(year, month, 0).getDate();
    const dateKeys = Array.from({ length: lastDay }, (_, i) => {
        const d = i + 1;
        return `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    });
    const { followup_from, followup_to } = buildFollowupRangeFromDates(dateKeys);
    const pageSize = 200;
    let offset = 0;
    const all = [];

    while (all.length < maxRows) {
        const params = { followup_from, followup_to, limit: pageSize, offset };
        if (serviceCode) {
            params.service_code = serviceCode;
        }
        const res = await listCustomerServiceFollowups(params);
        const meta = getFollowupListMeta(res, pageSize);
        all.push(...meta.rows);
        if (meta.total != null) {
            if (offset + meta.rows.length >= meta.total) break;
        } else if (meta.rows.length < pageSize) {
            break;
        }
        offset += pageSize;
    }

    return all;
}

export async function listCustomerServiceFollowups(params = {}) {
    const response = await api.get(CUSTOMER_SERVICE_FOLLOWUPS_BASE, {
        params: mapFollowupListParams(params),
        paramsSerializer: { serialize: serializeFollowupQueryParams },
    });
    const { items, total, limit, offset, requestId } = unwrapListPayload(response);
    const rows = items.map(normalizeFollowupRow);
    return {
        ...response,
        data: {
            ...response.data,
            data: rows,
            total,
            limit,
            offset,
            request_id: requestId,
        },
    };
}

export async function getCustomerServiceFollowupCounts(params = {}) {
    return api.get(`${CUSTOMER_SERVICE_FOLLOWUPS_BASE}/counts`, { params });
}

/** Fetch dashboard KPIs from backend /counts for selected calendar dates. */
export async function fetchCustomerServiceFollowupStats({ selectedDates, serviceCode } = {}) {
    const { dateKeys, followup_from, followup_to } = buildFollowupRangeFromDates(selectedDates);

    const params = {
        followup_from,
        followup_to,
        dates: dateKeys.join(','),
    };
    if (serviceCode) {
        params.service_code = serviceCode;
    }

    try {
        const res = await getCustomerServiceFollowupCounts(params);
        const data = unwrapCountsPayload(res);
        return mapCountsResponseToDashboardStats(data);
    } catch (err) {
        console.warn('[followupsApi] counts failed, falling back to list aggregation:', err?.message);
        const listParams = { followup_from, followup_to, limit: 200 };
        if (serviceCode) {
            listParams.service_code = serviceCode;
        }
        const listRes = await listCustomerServiceFollowups(listParams);
        const rows = listRes.data?.data ?? [];
        return computeFollowupDashboardStats(rows, dateKeys);
    }
}

export async function getCustomerServiceFollowupAlerts() {
    const response = await api.get(`${CUSTOMER_SERVICE_FOLLOWUPS_BASE}/alerts`);
    const rows = unwrapListPayload(response).items.map(normalizeFollowupRow);
    return {
        ...response,
        data: {
            ...response.data,
            data: rows,
        },
    };
}

/** POST /api/v1/customer-service-followups/{customer_service_id} — update an existing follow-up only */
export async function updateCustomerServiceFollowup(customerServiceId, body) {
    const response = await api.post(
        `${CUSTOMER_SERVICE_FOLLOWUPS_BASE}/${customerServiceId}`,
        body,
    );
    return response;
}

/** POST /api/v1/customer-service-followups — schedule a new follow-up on a customer service row */
export async function scheduleCustomerServiceFollowup(customerServiceId, body = {}) {
    const response = await api.post(CUSTOMER_SERVICE_FOLLOWUPS_BASE, {
        customer_service_id: customerServiceId,
        followup_at: body.followup_at,
        remarks: body.remarks ?? null,
    });
    return response;
}

/** @deprecated Use scheduleCustomerServiceFollowup */
export const createCustomerServiceFollowup = scheduleCustomerServiceFollowup;

/** True when the service row already has an open follow-up (update endpoint required). */
export function hasOpenCustomerServiceFollowup(serviceRow, followupRows = []) {
    const rowStatus = (serviceRow?.followup_status || serviceRow?.status || '').toUpperCase();
    if (
        serviceRow?.followup_at
        && (rowStatus === 'PENDING' || rowStatus === 'MISSED' || rowStatus === '')
    ) {
        return true;
    }
    return followupRows.some((row) => {
        const status = (row?.status || row?.followup_status || '').toUpperCase();
        return Boolean(row?.followup_at) && (status === 'PENDING' || status === 'MISSED');
    });
}

/** True when the payment row already has an open collection follow-up. */
export function hasOpenPaymentFollowup(paymentRow, followupRows = []) {
    const rowStatus = (paymentRow?.followup_status || paymentRow?.status || '').toUpperCase();
    if (
        paymentRow?.followup_at
        && (rowStatus === 'PENDING' || rowStatus === 'MISSED' || rowStatus === '')
    ) {
        return true;
    }
    return followupRows.some((row) => {
        const status = (row?.status || row?.followup_status || '').toUpperCase();
        return Boolean(row?.followup_at) && (status === 'PENDING' || status === 'MISSED');
    });
}
