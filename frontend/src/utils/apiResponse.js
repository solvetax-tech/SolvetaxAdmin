/**
 * Normalize GET response shapes from cached FastAPI endpoints.
 * Supports: { data: [] }, { items: [] }, { data: { data: [] } }, or raw arrays.
 */

export function unwrapListPayload(axiosResponse) {
    const payload = axiosResponse?.data ?? {};

    let items = [];
    if (Array.isArray(payload.data)) {
        items = payload.data;
    } else if (Array.isArray(payload.items)) {
        items = payload.items;
    } else if (Array.isArray(payload)) {
        items = payload;
    }

    const totalRaw = payload.total;
    const total = Number.isFinite(Number(totalRaw)) ? Number(totalRaw) : null;

    return {
        items,
        total,
        limit: payload.limit,
        offset: payload.offset ?? 0,
        requestId: payload.request_id,
        raw: payload,
    };
}

export function unwrapDataPayload(axiosResponse) {
    const payload = axiosResponse?.data ?? {};
    if (payload.data !== undefined && payload.data !== null && !Array.isArray(payload.data)) {
        return payload.data;
    }
    return payload;
}

export function unwrapCountsPayload(axiosResponse) {
    const payload = axiosResponse?.data ?? {};
    return payload.data ?? payload;
}

/** FastAPI / Pydantic errors → safe string for UI (never pass raw objects to React children). */
export function formatApiErrorDetail(detail, fallback = 'Request failed.') {
    if (detail == null || detail === '') return fallback;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        const parts = detail
            .map((item) => {
                if (typeof item === 'string') return item;
                if (item && typeof item === 'object') {
                    const loc = Array.isArray(item.loc) ? item.loc.join('.') : '';
                    const msg = item.msg || item.message || '';
                    return [loc, msg].filter(Boolean).join(': ');
                }
                return null;
            })
            .filter(Boolean);
        return parts.length ? parts.join('; ') : fallback;
    }
    if (typeof detail === 'object') {
        if (detail.error?.message) return String(detail.error.message);
        if (detail.message) return String(detail.message);
        try {
            return JSON.stringify(detail);
        } catch {
            return fallback;
        }
    }
    return String(detail);
}
