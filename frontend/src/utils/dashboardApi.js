import api from './api';

const DASHBOARD_BASE = '/api/v1/dashboard';

/**
 * GET /api/v1/dashboard/service-done-payment-pending
 * Services done (PROVIDED/APPROVED/FILED per entity) with no payment row.
 * Optional: phone, business_name (substring or >=30% trigram similarity).
 */
export async function fetchServiceDonePaymentPending(params = {}, config = {}) {
    const response = await api.get(`${DASHBOARD_BASE}/service-done-payment-pending`, {
        params,
        ...config,
    });
    return response.data;
}

/**
 * GET /api/v1/dashboard/gst-filing-monthly-matrix
 * Customer-wise monthly GST filing heatmap (GSTR-1 / GSTR-3B).
 */
export async function fetchGstFilingMonthlyMatrix(params = {}, config = {}) {
    const response = await api.get(`${DASHBOARD_BASE}/gst-filing-monthly-matrix`, {
        params,
        ...config,
    });
    return response.data;
}

/**
 * GET /api/v1/dashboard/gst-filing-followup-alerts
 * Per-return GST filing follow-ups (not service/payment follow-ups).
 */
export async function fetchGstFilingFollowupAlerts(params = {}, config = {}) {
    const response = await api.get(`${DASHBOARD_BASE}/gst-filing-followup-alerts`, {
        params,
        ...config,
    });
    return response.data;
}

/** Deep-link into GST Filings matrix and focus a customer/return row. */
export function buildGstFilingFocusPath({
    customerId,
    returnDetailId,
    formKey,
    period,
} = {}) {
    const params = new URLSearchParams({
        tab: 'dashboard',
        sub: 'gst-filing-matrix',
    });
    if (customerId != null) params.set('focus_customer_id', String(customerId));
    if (returnDetailId != null) params.set('focus_return_detail_id', String(returnDetailId));
    if (formKey) params.set('focus_form_key', formKey);
    if (period) params.set('focus_period', period);
    return `/dashboard?${params.toString()}`;
}

export function parseGstFilingFocusFromSearch(search) {
    const params = new URLSearchParams(search || '');
    const customerId = params.get('focus_customer_id');
    const returnDetailId = params.get('focus_return_detail_id');
    const formKey = params.get('focus_form_key');
    const period = params.get('focus_period');
    if (!customerId && !returnDetailId && !formKey && !period) return null;
    return {
        customerId: customerId ? Number(customerId) : null,
        returnDetailId: returnDetailId ? Number(returnDetailId) : null,
        formKey: formKey || null,
        period: period || null,
    };
}

/** Resolve row focus from a notification/toast action (gstFocus or URL query). */
export function resolveGstFocusFromAction(action) {
    if (!action) return null;
    if (action.gstFocus?.customerId) return action.gstFocus;
    const query = String(action.path || '').split('?')[1] || '';
    const parsed = parseGstFilingFocusFromSearch(query);
    if (!parsed?.customerId) return null;
    return {
        customerId: parsed.customerId,
        returnDetailId: parsed.returnDetailId,
        formKey: parsed.formKey,
        period: parsed.period,
    };
}

/** Open GST matrix row focus — immediate + delayed so mount after navigate still receives it. */
export function dispatchGstFilingFocusOpen(gstFocus) {
    if (!gstFocus?.customerId) return;
    const open = () => {
        window.dispatchEvent(new CustomEvent('st_open_gst_filing_followup', { detail: gstFocus }));
    };
    open();
    window.setTimeout(open, 150);
}
