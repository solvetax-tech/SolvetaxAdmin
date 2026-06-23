import api from '../../utils/api';
import {
    extractIncomeTaxList,
    fetchIncomeTaxById,
    unwrapIncomeTaxRecord,
} from '../../utils/incomeTaxApi';

/** CRM View drawer: ITR records for a lead mobile (GET /income-tax/by-mobile). */
export async function fetchIncomeTaxByMobile(mobile) {
    const trimmed = String(mobile || '').trim();
    if (!trimmed) return [];
    const res = await api.get('/api/v1/income-tax/by-mobile', {
        params: { mobile: trimmed },
    });
    return extractIncomeTaxList(res.data);
}

/** CRM View drawer: ITR row linked on the lead (GET /income-tax/{income_tax_id}). */
export async function fetchIncomeTaxByEntityId(entityId) {
    const incomeTaxId = parseInt(entityId, 10);
    if (!incomeTaxId || Number.isNaN(incomeTaxId)) return null;
    const res = await fetchIncomeTaxById(incomeTaxId);
    return unwrapIncomeTaxRecord(res.data);
}

/** CRM View drawer: full GST registration (GET /gst-registrations/{id}/full). */
export async function fetchGstRegistrationFull(registrationId) {
    const id = parseInt(registrationId, 10);
    if (!id || Number.isNaN(id)) return null;
    const res = await api.get(`/api/v1/gst-registrations/${id}/full`);
    const data = res.data;
    if (!data) return null;
    if (data.registration) return data;
    return { registration: data };
}
