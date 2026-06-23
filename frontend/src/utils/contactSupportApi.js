import api from './api';
import { cachedGet } from './clientCache';

export const LEAD_BUCKET_CONTACT = 'CONTACT_SUPPORT';
export const LEAD_BUCKET_REFERRAL = 'REFERRAL';

export const CONTACT_SUPPORT_OPTIONS_CACHE_KEY = 'contact-support:options';

export async function fetchContactSupportOptions({ force = false } = {}) {
    return cachedGet(
        CONTACT_SUPPORT_OPTIONS_CACHE_KEY,
        async () => {
            const res = await api.get('/api/v1/contact-support/options');
            return res.data?.data ?? res.data ?? {};
        },
        { force },
    );
}

export async function fetchContactSupportLeads(params = {}) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
        if (value == null || value === '') return;
        if (Array.isArray(value)) {
            value.forEach((v) => {
                if (v != null && v !== '') query.append(key, String(v));
            });
            return;
        }
        query.append(key, String(value));
    });
    const url = query.toString()
        ? `/api/v1/contact-support/filter?${query.toString()}`
        : '/api/v1/contact-support/filter';
    const res = await api.get(url);
    const body = res.data?.data ?? res.data ?? {};
    return {
        items: body.items || [],
        total: Number(body.total) || 0,
        limit: body.limit,
        offset: body.offset,
    };
}

export async function editContactSupportLead(contactId, payload) {
    const res = await api.post(`/api/v1/contact-support/${contactId}/edit`, payload);
    return res.data?.data ?? res.data;
}

export async function createContactSupportLead(payload) {
    const res = await api.post('/api/v1/contact-support', payload);
    return res.data?.data ?? res.data;
}

export async function softDeleteContactSupportLead(contactId) {
    const res = await api.delete(`/api/v1/contact-support/${contactId}/soft_delete`);
    return res.data?.data ?? res.data;
}

export async function activateContactSupportLead(contactId) {
    const res = await api.post(`/api/v1/contact-support/${contactId}/activate`);
    return res.data?.data ?? res.data;
}
