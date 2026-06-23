import api from './api';
import { cachedGet } from './clientCache';

/** Staff dropdown — replaces legacy GET /api/v1/services-config/services */
export const STAFF_SERVICE_CONFIG_PATH = '/api/v1/customer-service/service-config/services';

export const STAFF_SERVICE_CONFIG_CACHE_KEY = 'staff-service-config:services';

const CATEGORY_DISPLAY = {
    GST: 'GST',
    INCOME_TAX: 'Income Tax',
    'INCOME TAX': 'Income Tax',
    BUSINESS: 'Business & Company',
    COMPANY: 'Business & Company',
    OTHER: 'Other Services',
};

const CATEGORY_SORT_RANK = {
    GST: 0,
    INCOME_TAX: 1,
    'INCOME TAX': 1,
    BUSINESS: 2,
    COMPANY: 2,
};

function normalizeStaffServiceRow(row, categoryOverride) {
    if (!row || typeof row !== 'object') return null;
    const code = row.service_code ?? row.code;
    if (!code) return null;
    if (row.is_active === false || row.active === false) return null;

    return {
        id: row.id ?? row.service_config_id ?? String(code),
        service_code: String(code),
        service_name: row.service_name ?? row.name ?? row.label ?? String(code),
        service_category: categoryOverride
            ?? row.service_category
            ?? row.category
            ?? row.service_type
            ?? 'OTHER',
        sort_order: Number(row.sort_order ?? row.display_order ?? 999),
    };
}

/**
 * Normalizes GET /api/v1/customer-service/service-config/services (flat list or grouped).
 */
export function unwrapStaffServiceConfigResponse(response) {
    const body = response?.data ?? response;

    if (Array.isArray(body)) {
        return body.map((row) => normalizeStaffServiceRow(row)).filter(Boolean);
    }

    const list = body?.data ?? body?.items ?? body?.services ?? body?.rows;
    if (Array.isArray(list)) {
        return list.map((row) => normalizeStaffServiceRow(row)).filter(Boolean);
    }

    if (Array.isArray(body?.categories)) {
        return body.categories.flatMap((cat) => {
            const category = cat.category
                ?? cat.service_category
                ?? cat.name
                ?? 'OTHER';
            const services = cat.services ?? cat.items ?? [];
            return services
                .map((row) => normalizeStaffServiceRow(row, category))
                .filter(Boolean);
        });
    }

    if (body && typeof body === 'object') {
        const skip = new Set(['success', 'message', 'total', 'count', 'meta']);
        const keys = Object.keys(body).filter((k) => !skip.has(k));
        if (keys.length > 0 && keys.every((k) => Array.isArray(body[k]))) {
            return keys.flatMap((k) =>
                body[k]
                    .map((row) => normalizeStaffServiceRow(row, k))
                    .filter(Boolean),
            );
        }
    }

    return [];
}

export function groupStaffServicesByCategory(services) {
    return (services || []).reduce((acc, service) => {
        const category = service.service_category || 'OTHER';
        if (!acc[category]) acc[category] = [];
        acc[category].push(service);
        return acc;
    }, {});
}

function categorySortRank(category) {
    const key = String(category || '').toUpperCase().replace(/\s+/g, '_');
    if (Object.prototype.hasOwnProperty.call(CATEGORY_SORT_RANK, key)) {
        return CATEGORY_SORT_RANK[key];
    }
    if (Object.prototype.hasOwnProperty.call(CATEGORY_SORT_RANK, category)) {
        return CATEGORY_SORT_RANK[category];
    }
    return 50;
}

/** Stable category order (GST → Income Tax → Business, then any others). */
export function sortedStaffServiceCategoryEntries(grouped) {
    return Object.keys(grouped || {})
        .sort((a, b) => {
            const rankDiff = categorySortRank(a) - categorySortRank(b);
            if (rankDiff !== 0) return rankDiff;
            return String(a).localeCompare(String(b));
        })
        .map((category) => {
            const items = [...(grouped[category] || [])].sort(
                (a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999),
            );
            return [category, items];
        });
}

export function getServiceCategoryLabel(category) {
    const raw = String(category || '').trim();
    if (!raw) return 'Other Services';
    if (CATEGORY_DISPLAY[raw]) return CATEGORY_DISPLAY[raw];
    const upper = raw.toUpperCase().replace(/\s+/g, '_');
    if (CATEGORY_DISPLAY[upper]) return CATEGORY_DISPLAY[upper];
    return raw
        .replace(/_/g, ' ')
        .toLowerCase()
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

export async function fetchStaffServiceConfig({ force = false } = {}) {
    return cachedGet(
        STAFF_SERVICE_CONFIG_CACHE_KEY,
        async () => unwrapStaffServiceConfigResponse(await api.get(STAFF_SERVICE_CONFIG_PATH)),
        { ttlMs: 300000, force }, // service config rarely changes — cache 5 min
    );
}
