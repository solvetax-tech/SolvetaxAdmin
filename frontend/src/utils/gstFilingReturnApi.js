import api from './api';
import { GST_RETURN_FORM_STATUS_FIELDS } from './gstFilingStatusConstants';

/** Find the return-detail row that owns a given form for a customer + period. */
export async function resolveReturnDetailIdForForm({ customerId, period, formKey }) {
    const statusField = GST_RETURN_FORM_STATUS_FIELDS[formKey];
    if (!statusField || !customerId || !period) return null;
    const dueField = statusField.replace('_status', '_due_date');
    const response = await api.get('/api/v1/gst-filings/table/return-details', {
        params: {
            customer_id: customerId,
            filing_period: period,
            include_details: true,
            limit: 50,
        },
    });
    const rows = response.data?.data || [];
    const match = rows.find((row) => row[dueField] != null || row[statusField] != null);
    return match?.id ?? null;
}

/** PATCH return-detail form statuses (gstr1_status, gstr3b_status, …). */
export async function patchReturnDetailStatus(returnDetailId, payload) {
    const response = await api.patch(
        `/api/v1/gst-filings/${returnDetailId}/returns/status`,
        payload,
    );
    return response.data;
}
export async function getGstFilingReturnDetailById(returnDetailId) {
    const response = await api.get('/api/v1/gst-filings/table/return-details', {
        params: {
            id: returnDetailId,
            include_inactive: true,
            include_details: true,
            limit: 1,
        },
    });
    const rows = response.data?.data || [];
    return rows[0] || null;
}

/** POST /api/v1/gst-filing-return-details-payments */
export async function createGstFilingReturnDetailPayment(body) {
    const response = await api.post('/api/v1/gst-filing-return-details-payments', body);
    return response.data;
}

/** DELETE /api/v1/gst-filing-return-details-payments/{payment_id}/soft_delete */
export async function softDeleteGstFilingReturnDetailPayment(paymentId) {
    const response = await api.delete(
        `/api/v1/gst-filing-return-details-payments/${paymentId}/soft_delete`,
    );
    return response.data;
}

/** POST /api/v1/gst-filing-return-details-payments/{payment_id}/activate */
export async function activateGstFilingReturnDetailPayment(paymentId) {
    const response = await api.post(
        `/api/v1/gst-filing-return-details-payments/${paymentId}/activate`,
    );
    return response.data;
}
