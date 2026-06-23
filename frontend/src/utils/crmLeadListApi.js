import api from './api';
import { getCrmLeadsApiBase } from './crmLeadApi';
import { unwrapListPayload } from './apiResponse';

/** GET CRM leads/filter with consistent list + total parsing. */
export async function fetchCrmLeadsFilter(entityType, params = {}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const response = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/filter`, { params });
    return unwrapListPayload(response);
}
