import api from './api';
import { unwrapCountsPayload, unwrapListPayload } from './apiResponse';
import { getCrmLeadsApiBase } from './crmLeadApi';
import {
    buildFollowupRangeFromDates,
    computeFollowupDashboardStats,
    formatFollowupDateKey,
    FOLLOWUP_SCHEDULE_PAGE_SIZE,
    getFollowupListMeta,
    mapCountsResponseToDashboardStats,
    resolveFollowupAlertStatus,
} from './followupsApi';

const SERVICE_STAGES = new Set([
    'FRESH_LEAD', 'FRESH_LEADS', 'NEW', 'FOLLOW_UP', 'FOLLOWUP', 'INTERESTED',
]);

export function isPaymentLead(lead) {
    const stage = (lead?.stage || '').toUpperCase();
    return stage === 'SCHEDULED_PAYMENT' || stage === 'SCHEDULED_PAYMENTS';
}

export function matchesCrmFollowupCategory(lead, category) {
    if (!lead?.followup_at) return false;
    const payment = isPaymentLead(lead);
    if (category === 'payment') return payment;
    const stageUpper = (lead.stage || '').toUpperCase();
    return !payment && SERVICE_STAGES.has(stageUpper);
}

/** True when the lead is in a service or payment follow-up stage with followup_at set. */
export function isCrmFollowupLead(lead) {
    return matchesCrmFollowupCategory(lead, 'service') || matchesCrmFollowupCategory(lead, 'payment');
}

export function canViewCrmLead(profileData, lead) {
    if (!lead) return false;
    if (!profileData?.emp_id) return true;
    const isAssignedToMe = !lead.assigned_to
        || lead.assigned_to === profileData.emp_id
        || lead.rm_id === profileData.emp_id;
    const isCreatedByMe = lead.created_by === profileData.emp_id;
    const isAdmin = String(profileData.role || '').toUpperCase() === 'ADMIN';
    return isAssignedToMe || isCreatedByMe || isAdmin;
}

/** Open follow-up tasks only (PENDING / MISSED), same semantics as main Followups alerts. */
export function resolveLeadAlertStatus(lead) {
    return resolveFollowupAlertStatus(lead);
}

export function mapLeadToAlertItem(lead) {
    const status = resolveLeadAlertStatus(lead);
    if (!status) return null;

    return {
        id: lead.id,
        followup_at: lead.followup_at,
        status,
        service_name: (lead.stage || 'CRM Lead').replace(/_/g, ' '),
        remarks: lead.remarks || lead.last_remark || '',
        customer_id: lead.id,
        full_name: lead.full_name || 'Unknown',
        mobile: lead.mobile || '',
        originalLead: lead,
    };
}

function buildCrmFollowupQueryParams({
    entityType,
    category = 'service',
    stageFilter = '',
    followup_from,
    followup_to,
    dates,
    limit,
    offset,
    status,
} = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const params = {
        entity_type: entityTypeNorm,
        category: category === 'payment' ? 'payment' : 'service',
    };
    if (followup_from) params.followup_from = followup_from;
    if (followup_to) params.followup_to = followup_to;
    if (dates) params.dates = dates;
    if (stageFilter) params.stage = stageFilter;
    if (limit != null) params.limit = limit;
    if (offset != null) params.offset = offset;
    if (status) params.status = status;
    return params;
}

/** Dashboard KPIs from CRM GET /followups/counts (6 analytics cards). */
export async function fetchCrmFollowupStats({
    entityType,
    selectedDates,
    category = 'service',
    stageFilter = '',
    profileData,
} = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const { dateKeys, followup_from, followup_to } = buildFollowupRangeFromDates(selectedDates);
    const params = buildCrmFollowupQueryParams({
        entityType: entityTypeNorm,
        category,
        stageFilter,
        followup_from,
        followup_to,
        dates: dateKeys.join(','),
    });

    const base = getCrmLeadsApiBase(entityTypeNorm);
    try {
        const res = await api.get(`${base}/followups/counts`, { params });
        return mapCountsResponseToDashboardStats(unwrapCountsPayload(res));
    } catch (err) {
        console.warn('[crmLeadsAlerts] followups/counts failed, falling back to client stats:', err?.message);
        const items = await fetchCrmDashboardStatsLeads({
            entityType,
            profileData,
            category: params.category,
            dateKeys,
            stageFilter,
        });
        return computeFollowupDashboardStats(items, dateKeys);
    }
}

export async function getCrmLeadFollowupAlerts({
    entityType,
    category = 'service',
    stageFilter = '',
} = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const params = buildCrmFollowupQueryParams({
        entityType: entityTypeNorm,
        category,
        stageFilter,
    });
    const response = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/followups/alerts`, { params });
    const rows = unwrapListPayload(response).items;
    return {
        ...response,
        data: {
            ...response.data,
            data: rows,
        },
    };
}

/**
 * CRM lead follow-up alerts (backend /followups/alerts; client fallback on leads/filter).
 */
export async function fetchCrmLeadAlerts({
    entityType,
    profileData,
    category = 'service',
    stageFilter = '',
} = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();

    try {
        const alertsRes = await getCrmLeadFollowupAlerts({
            entityType: entityTypeNorm,
            category,
            stageFilter,
        });
        return (alertsRes.data?.data || [])
            .filter((lead) => canViewCrmLead(profileData, lead))
            .map(mapLeadToAlertItem)
            .filter(Boolean)
            .sort((a, b) => new Date(a.followup_at) - new Date(b.followup_at));
    } catch (err) {
        console.warn('[crmLeadsAlerts] followups/alerts failed, falling back to filter:', err?.message);
    }

    const now = new Date();
    const from = new Date(now);
    from.setDate(from.getDate() - 30);
    from.setHours(0, 0, 0, 0);
    const to = new Date(now);
    to.setDate(to.getDate() + 14);
    to.setHours(23, 59, 59, 999);

    const res = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/filter`, {
        params: {
            limit: 200,
            is_active: true,
            entity_type: entityTypeNorm,
            followup_at_from: from.toISOString(),
            followup_at_to: to.toISOString(),
        },
    });

    return unwrapListPayload(res).items
        .filter((lead) => matchesCrmFollowupCategory(lead, category))
        .filter((lead) => canViewCrmLead(profileData, lead))
        .map(mapLeadToAlertItem)
        .filter(Boolean)
        .filter((item) => item.status === 'PENDING' || item.status === 'MISSED')
        .sort((a, b) => new Date(a.followup_at) - new Date(b.followup_at));
}

export async function listCrmFollowups(params = {}) {
    const entityTypeNorm = (params.entity_type || params.entityType || '').trim().toUpperCase();
    const query = buildCrmFollowupQueryParams({
        entityType: entityTypeNorm,
        category: params.category,
        stageFilter: params.stage,
        followup_from: params.followup_from,
        followup_to: params.followup_to,
        dates: params.dates,
        limit: params.limit,
        offset: params.offset,
        status: params.status,
    });

    const response = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/followups`, { params: query });
    const meta = getFollowupListMeta(response, query.limit || FOLLOWUP_SCHEDULE_PAGE_SIZE);
    return {
        ...response,
        data: {
            ...response.data,
            data: meta.rows,
            total: meta.total,
            limit: query.limit,
            offset: query.offset,
        },
    };
}

function mapListParamsFromDateKeys(dateKeys = []) {
    const keys = dateKeys?.length ? dateKeys : [formatFollowupDateKey(new Date())];
    const { followup_from, followup_to } = buildFollowupRangeFromDates(keys);
    return {
        dateKeys: keys,
        followup_from,
        followup_to,
        dates: keys.join(','),
    };
}

/** Paginated scheduled follow-ups for CRM dashboard (GET /followups). */
export async function fetchCrmScheduledFollowupsPage({
    entityType,
    profileData,
    category = 'service',
    dateKeys = [],
    stageFilter = '',
    page = 1,
    pageSize = FOLLOWUP_SCHEDULE_PAGE_SIZE,
} = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const { followup_from, followup_to, dates } = mapListParamsFromDateKeys(dateKeys);
    const limit = pageSize > 0 ? pageSize : FOLLOWUP_SCHEDULE_PAGE_SIZE;
    const offset = Math.max(0, (page - 1) * limit);

    try {
        const res = await listCrmFollowups({
            entity_type: entityTypeNorm,
            category,
            stage: stageFilter,
            followup_from,
            followup_to,
            dates,
            limit,
            offset,
        });
        const meta = getFollowupListMeta(res, limit);
        const items = meta.rows.filter((lead) => canViewCrmLead(profileData, lead));
        return {
            items,
            total: meta.total,
            hasMore: meta.hasMore,
            offset,
            limit,
        };
    } catch (err) {
        console.warn('[crmLeadsAlerts] followups list failed, falling back to filter:', err?.message);
    }

    const params = {
        limit,
        offset,
        is_active: true,
        entity_type: entityTypeNorm,
        followup_at_from: followup_from,
        followup_at_to: followup_to,
    };
    if (stageFilter) {
        params.stage = stageFilter;
    }

    const res = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/filter`, { params });
    const { items: apiItems, total: apiTotal } = unwrapListPayload(res);

    const items = apiItems
        .filter((lead) => matchesCrmFollowupCategory(lead, category))
        .filter((lead) => canViewCrmLead(profileData, lead));

    const total = Number.isFinite(apiTotal) && apiTotal >= 0 ? apiTotal : null;
    const hasMore = total != null
        ? offset + apiItems.length < total
        : apiItems.length >= limit;

    return { items, total, hasMore, offset, limit };
}

/** Fetch CRM follow-up rows for KPI fallback / calendar (paginated). */
export async function fetchCrmDashboardStatsLeads({
    entityType,
    profileData,
    category = 'service',
    dateKeys = [],
    stageFilter = '',
    maxRows = 2000,
} = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const { followup_from, followup_to, dates } = mapListParamsFromDateKeys(dateKeys);
    const pageSize = 200;
    let offset = 0;
    const all = [];

    while (all.length < maxRows) {
        try {
            const res = await listCrmFollowups({
                entity_type: entityTypeNorm,
                category,
                stage: stageFilter,
                followup_from,
                followup_to,
                dates,
                limit: pageSize,
                offset,
            });
            const meta = getFollowupListMeta(res, pageSize);
            const rows = meta.rows.filter((lead) => canViewCrmLead(profileData, lead));
            all.push(...rows);
            if (meta.total != null) {
                if (offset + meta.rows.length >= meta.total) break;
            } else if (meta.rows.length < pageSize) {
                break;
            }
            offset += pageSize;
        } catch (err) {
            console.warn('[crmLeadsAlerts] followups list pagination failed:', err?.message);
            break;
        }
    }

    if (all.length > 0) {
        return all;
    }

    const params = {
        limit: Math.min(maxRows, 200),
        offset: 0,
        is_active: true,
        entity_type: entityTypeNorm,
        followup_at_from: followup_from,
        followup_at_to: followup_to,
    };
    if (stageFilter) {
        params.stage = stageFilter;
    }

    const res = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/filter`, { params });
    return unwrapListPayload(res).items
        .filter((lead) => matchesCrmFollowupCategory(lead, category))
        .filter((lead) => canViewCrmLead(profileData, lead));
}

/** Leads with follow-ups in the visible calendar month (for day dots). */
export async function fetchCrmCalendarMonthLeads({
    entityType,
    profileData,
    category = 'service',
    year,
    monthIndex = 0,
    stageFilter = '',
    maxRows = 2000,
} = {}) {
    const month = monthIndex + 1;
    const lastDay = new Date(year, month, 0).getDate();
    const firstKey = `${year}-${String(month).padStart(2, '0')}-01`;
    const lastKey = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
    return fetchCrmDashboardStatsLeads({
        entityType,
        profileData,
        category,
        dateKeys: [firstKey, lastKey],
        stageFilter,
        maxRows,
    });
}
