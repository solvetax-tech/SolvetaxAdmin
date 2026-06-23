import api from './api';
import { unwrapListPayload } from './apiResponse';

export const CUSTOMER_SERVICE_BASE = '/api/v1/customer-service';

/** GET /api/v1/customer-service/customer-services/filter */
export async function filterCustomerServices(params = {}, config = {}) {
    const response = await api.get(`${CUSTOMER_SERVICE_BASE}/customer-services/filter`, { params, ...config });
    const { items, total, limit, offset } = unwrapListPayload(response);
    return {
        ...response.data,
        items,
        data: items,
        total,
        limit,
        offset,
    };
}

/** GET /api/v1/customer-service/{customer_service_id} (ADMIN) */
export async function getCustomerServiceById(customerServiceId) {
    const response = await api.get(`${CUSTOMER_SERVICE_BASE}/${customerServiceId}`);
    return response.data;
}

/** PATCH /api/v1/customer-service/{id} — ADMIN (rm_id, op_id, service_status, is_active) */
export async function patchCustomerService(customerServiceId, body) {
    const response = await api.patch(`${CUSTOMER_SERVICE_BASE}/${customerServiceId}`, body);
    return response.data;
}

/** PATCH /api/v1/customer-service/{id}/service-status — EMPLOYEE WRITE */
export async function patchCustomerServiceStatus(customerServiceId, serviceStatus) {
    const response = await api.patch(
        `${CUSTOMER_SERVICE_BASE}/${customerServiceId}/service-status`,
        { service_status: serviceStatus },
    );
    return response.data;
}

/** DELETE /api/v1/customer-service/{id}/soft_delete */
export async function softDeleteCustomerService(customerServiceId) {
    const response = await api.delete(`${CUSTOMER_SERVICE_BASE}/${customerServiceId}/soft_delete`);
    return response.data;
}

/** POST /api/v1/customer-service/{id}/activate */
export async function activateCustomerService(customerServiceId) {
    const response = await api.post(`${CUSTOMER_SERVICE_BASE}/${customerServiceId}/activate`);
    return response.data;
}

/** GET /api/v1/customer-service/bulk-assign/candidates */
export async function fetchCustomerServiceBulkAssignCandidates(params = {}) {
    const response = await api.get(`${CUSTOMER_SERVICE_BASE}/bulk-assign/candidates`, {
        params,
        paramsSerializer: (p) => {
            const search = new URLSearchParams();
            Object.entries(p).forEach(([key, value]) => {
                if (value === null || value === undefined || value === '') return;
                if (Array.isArray(value)) {
                    value.forEach((entry) => {
                        if (entry !== null && entry !== undefined && entry !== '') {
                            search.append(key, String(entry));
                        }
                    });
                } else {
                    search.append(key, String(value));
                }
            });
            return search.toString();
        },
    });
    return response.data;
}

export function buildCustomerServiceBulkAssignParams(
    filters,
    { preview = false, activeKeys = null } = {},
) {
    const alwaysInclude = new Set(['match_mode', 'filter_mode', 'limit', 'offset']);
    const activeKeySet = Array.isArray(activeKeys) ? new Set(activeKeys) : null;
    const params = {};

    Object.entries(filters).forEach(([key, value]) => {
        if (key === 'offset') return;
        if (activeKeySet && !activeKeySet.has(key) && !alwaysInclude.has(key)) return;
        if (value === null || value === undefined || value === '') return;
        if (Array.isArray(value)) {
            if (value.length === 0) return;
            if (['rm_ids', 'op_ids', 'customer_ids'].includes(key)) {
                const nums = value.map((v) => Number(v)).filter((n) => Number.isFinite(n) && n > 0);
                if (nums.length === 0) return;
                params[key] = nums;
                return;
            }
            params[key] = value;
            return;
        }
        params[key] = value;
    });

    if (preview) {
        params.limit = 1;
    } else if (filters.limit) {
        params.limit = filters.limit;
    }
    params.offset = filters.offset ?? 0;
    params.match_mode = filters.match_mode || 'AND';
    params.filter_mode = filters.filter_mode || 'IN';
    return params;
}

export function unwrapCustomerServiceBulkAssignResponse(response) {
    const payload = response?.items != null
        ? response
        : response?.data?.items != null
          ? response.data
          : response?.data?.data?.items != null
            ? response.data.data
            : response || {};
    return {
        items: Array.isArray(payload.items) ? payload.items : [],
        total: Number(payload.total) || 0,
        limit: Number(payload.limit) || 0,
        offset: Number(payload.offset) || 0,
    };
}

/** POST /api/v1/customer-service/bulk-assign/execute */
export async function executeCustomerServiceBulkAssign(body) {
    const response = await api.post(`${CUSTOMER_SERVICE_BASE}/bulk-assign/execute`, body);
    return response.data;
}

/** GET /api/v1/customer-service/customer-services/progress-tracker */
export async function fetchCustomerServiceProgressTracker(params = {}) {
    const response = await api.get(`${CUSTOMER_SERVICE_BASE}/customer-services/progress-tracker`, { params });
    const payload = response.data?.data ?? response.data ?? {};
    return {
        summary: payload.summary ?? {
            tracked_customers: 0,
            completed: 0,
            in_progress: 0,
            not_started: 0,
        },
        rows: Array.isArray(payload.rows) ? payload.rows : [],
        count: Number(payload.count) || 0,
        total_count: Number(payload.total_count) || 0,
        limit: Number(payload.limit) || 0,
        offset: Number(payload.offset) || 0,
    };
}

/** GET /api/v1/customer-service/customer-services/dashboard/stats */
export async function fetchCustomerServicesDashboardStats(filterType = null) {
    const params = filterType ? { filter_type: filterType } : {};
    const response = await api.get(`${CUSTOMER_SERVICE_BASE}/customer-services/dashboard/stats`, { params });
    return response.data;
}

/** GET /api/v1/customer-service/customer-services/pending */
export async function fetchPendingCustomerServices(params = {}) {
    const response = await api.get(`${CUSTOMER_SERVICE_BASE}/customer-services/pending`, { params });
    return response.data;
}

/** POST /api/v1/customer-service-payments */
export async function createCustomerServicePayment(body) {
    const response = await api.post('/api/v1/customer-service-payments', body);
    return response.data;
}

/** DELETE /api/v1/customer-service-payments/{payment_id}/soft_delete */
export async function softDeleteCustomerServicePayment(paymentId) {
    const response = await api.delete(`/api/v1/customer-service-payments/${paymentId}/soft_delete`);
    return response.data;
}

/** POST /api/v1/customer-service-payments/{payment_id}/activate */
export async function activateCustomerServicePayment(paymentId) {
    const response = await api.post(`/api/v1/customer-service-payments/${paymentId}/activate`);
    return response.data;
}

export function recordStatusLabel(row) {
    if (row?.status) return row.status;
    if (row?.is_active === true) return 'ACTIVE';
    if (row?.is_active === false) return 'INACTIVE';
    return '-';
}

export function buildCustomerServiceFilterParams(filters, { limit, offset } = {}) {
    const params = {};
    if (filters.customer_id !== '' && filters.customer_id != null) {
        const customerId = parseInt(String(filters.customer_id).trim(), 10);
        if (!Number.isNaN(customerId) && customerId > 0) {
            params.customer_id = customerId;
        }
    }
    if (filters.service_code) params.service_code = filters.service_code;
    if (filters.service_status) params.service_status = filters.service_status;
    if (filters.status) params.status = filters.status;
    if (filters.from_date) params.from_date = filters.from_date;
    if (filters.to_date) params.to_date = filters.to_date;
    if (filters.rm_id) params.rm_id = filters.rm_id;
    if (filters.op_id) params.op_id = filters.op_id;
    if (limit != null) params.limit = limit;
    if (offset != null) params.offset = offset;
    return params;
}
