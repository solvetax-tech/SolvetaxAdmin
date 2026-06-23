import api from './api';
import { parseActiveUsernamesFromApi } from './activeEmployees';

const EMPTY = { states: [], activeRMs: [], activeOps: [], activeEmps: [], languages: [] };

let cached = null;
let inflight = null;

/** Session cache: one fetch shared by ITR list filters + create/edit forms. */
export async function fetchIncomeTaxConfigs() {
    if (cached) return cached;
    if (inflight) return inflight;

    inflight = Promise.all([
        api.get('/api/v1/gst-registration/config/STATE'),
        api.get('/api/v1/employees/active-rm'),
        api.get('/api/v1/employees/active-op'),
        api.get('/api/v1/employees/filter?is_active=true&limit=100'),
        api.get('/api/v1/gst-registration/config/LANGUAGE').catch(() => ({ data: [] })),
    ])
        .then(([statesRes, rmsRes, opsRes, empsRes, languagesRes]) => {
            cached = {
                states: statesRes.data || [],
                activeRMs: parseActiveUsernamesFromApi(rmsRes),
                activeOps: parseActiveUsernamesFromApi(opsRes),
                activeEmps: Array.isArray(empsRes.data)
                    ? empsRes.data
                    : (empsRes.data?.data || empsRes.data?.items || []),
                languages: languagesRes.data || [],
            };
            return cached;
        })
        .catch((err) => {
            console.error('Error fetching income tax configs:', err);
            return EMPTY;
        })
        .finally(() => {
            inflight = null;
        });

    return inflight;
}

export function clearIncomeTaxConfigsCache() {
    cached = null;
    inflight = null;
}
