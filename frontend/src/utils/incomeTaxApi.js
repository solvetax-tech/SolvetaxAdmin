import api from './api';

/** Normalize list payloads from GET /income-tax/filter (array or { items } / { data }). */
export const extractIncomeTaxList = (data) => {
    if (Array.isArray(data)) return data;
    if (Array.isArray(data?.items)) return data.items;
    if (Array.isArray(data?.data)) return data.data;
    return [];
};

/** `{ items, total, limit, offset }` from filter response. */
export const extractIncomeTaxListMeta = (data) => {
    const items = extractIncomeTaxList(data);
    const total = typeof data?.total === 'number' ? data.total : null;
    const limit = typeof data?.limit === 'number' ? data.limit : null;
    const offset = typeof data?.offset === 'number' ? data.offset : null;
    return { items, total, limit, offset };
};

/** Flat row from GET detail/create/edit (`data` wrapper supported). */
export function unwrapIncomeTaxRecord(raw) {
    if (!raw || typeof raw !== 'object') return null;
    if (raw.data != null && typeof raw.data === 'object' && !Array.isArray(raw.data)) {
        return raw.data;
    }
    if (raw.income_tax != null && typeof raw.income_tax === 'object') {
        return raw.income_tax;
    }
    return raw;
}

/**
 * Structured error from FastAPI `{ detail: { error: { type, message, fields, existing_income_tax_id } } }`.
 * @returns {{
 *   type?: string,
 *   message?: string,
 *   guidance?: string,
 *   recordYear?: number,
 *   fields?: Record<string, string>,
 *   existingIncomeTaxId?: number,
 * } | null}
 */
export function getIncomeTaxErrorPayload(err) {
    const data = err?.response?.data ?? err?.data;
    const block = data?.detail?.error ?? data?.error ?? null;
    if (!block || typeof block !== 'object') return null;
    const id = block.existing_income_tax_id ?? block.existingIncomeTaxId;
    const recordYear = block.record_year ?? block.recordYear;
    return {
        type: block.type,
        message: block.message,
        guidance: block.guidance,
        recordYear: recordYear != null ? Number(recordYear) : undefined,
        fields: block.fields && typeof block.fields === 'object' ? block.fields : {},
        existingIncomeTaxId: id != null ? Number(id) : undefined,
    };
}

/** Serialize filter arrays as repeated query keys (FastAPI List[str] style). */
function incomeTaxFilterParamsSerializer(params) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === '' || value === null || value === undefined) return;
        if (Array.isArray(value)) {
            value.forEach((item) => {
                if (item !== '' && item != null) search.append(key, String(item));
            });
            return;
        }
        search.append(key, String(value));
    });
    return search.toString();
}

export const fetchIncomeTaxes = async (params = {}) => {
    return api.get('/api/v1/income-tax/filter', {
        params,
        paramsSerializer: incomeTaxFilterParamsSerializer,
    });
};

export const fetchIncomeTaxById = async (incomeTaxId) => {
    return api.get(`/api/v1/income-tax/${incomeTaxId}`);
};

export const createIncomeTax = async (data) => {
    return api.post('/api/v1/income-tax', data);
};

/**
 * Create income_tax and link to CRM ITR lead (POST /income-tax/lead).
 * Pass crm_lead_id when pushing from the CRM leads table.
 */
export const createIncomeTaxLead = async (data) => {
    const res = await api.post('/api/v1/income-tax/lead', data);
    return res.data;
};

export const editIncomeTax = async (incomeTaxId, data) => {
    return api.post(`/api/v1/income-tax/${incomeTaxId}/edit`, data);
};

/** Activate or deactivate via POST /income-tax/{id}/edit (replaces soft_delete + activate). */
export const setIncomeTaxActive = async (incomeTaxId, isActive) => {
    return editIncomeTax(incomeTaxId, { is_active: !!isActive });
};

/** List ITR payments via the unified payments ledger endpoint scoped to INCOME_TAX.
 * (There is no dedicated /income-tax-payments/filter route — that 404'd and fell
 * back to this same call, wasting a request per load.) */
export const fetchIncomeTaxPaymentsFilter = async (params = {}) => {
    return api.get('/api/v1/payments/dynamic_filter', {
        params: { ...params, entity_type: 'INCOME_TAX' },
    });
};

/** CRM entity type for income tax ↔ CRM links from this module. */
export const INCOME_TAX_CRM_ENTITY_TYPE = 'INCOME_TAX';

/** CRM lead stages where Schedule Payment opens with call status pre-filled. */
export const ITR_CRM_SCHEDULE_PAYMENT_STAGES = new Set([
    'ITR_DONE',
    'SCHEDULED_PAYMENTS',
]);

export function isItrCrmStageForSchedulePayment(stage) {
    return ITR_CRM_SCHEDULE_PAYMENT_STAGES.has(String(stage || '').trim().toUpperCase());
}

/** CRM deep-link from Schedule Payment: drawer + status only on allowed lead stages. */
export const buildIncomeTaxCrmLeadActionSearchParams = (incomeTaxId, openSchedulePaymentDrawer = false) => {
    const params = new URLSearchParams({
        entity_type: INCOME_TAX_CRM_ENTITY_TYPE,
        entity_id: String(incomeTaxId),
    });
    if (openSchedulePaymentDrawer) {
        params.set('target_view', 'action');
        params.set('target_call_status', 'SCHEDULED_PAYMENT');
    }
    return params;
};

/** Linked CRM ITR lead for an income_tax row. */
export const getCrmLeadByIncomeTaxId = async (incomeTaxId) => {
    const entityTypeParam = encodeURIComponent(INCOME_TAX_CRM_ENTITY_TYPE);
    const query = `entity_id=${encodeURIComponent(incomeTaxId)}&limit=1&entity_type=${entityTypeParam}`;
    const bases = ['/api/v1/crm/leads'];
    for (const apiBase of bases) {
        try {
            const res = await api.get(`${apiBase}/filter?${query}`);
            const lead = res.data?.items?.[0];
            if (lead) return lead;
        } catch {
            /* try next base */
        }
    }
    return null;
};

/** @deprecated Use buildIncomeTaxCrmLeadActionSearchParams(id, true) */
export const buildIncomeTaxCrmSchedulePaymentSearchParams = (incomeTaxId) =>
    buildIncomeTaxCrmLeadActionSearchParams(incomeTaxId, true);
