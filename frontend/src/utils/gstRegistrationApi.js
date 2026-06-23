import api from './api';

/**
 * Structured error from FastAPI `{ detail: { error: { type, message, fields } } }`.
 * @returns {{ type?: string, message?: string, fields?: Record<string, string> } | null}
 */
export function getGstRegistrationErrorPayload(err) {
    const data = err?.response?.data ?? err?.data;
    const block = data?.detail?.error ?? data?.error ?? null;
    if (!block || typeof block !== 'object') return null;
    return {
        type: block.type,
        message: block.message,
        fields: block.fields && typeof block.fields === 'object' ? block.fields : undefined,
    };
}

/**
 * Create gst_registration and link to CRM GST lead (POST /gst-registrations/lead).
 * Pass crm_lead_id when pushing from the CRM leads table.
 */
export const createGstRegistrationLead = async (data) => {
    const res = await api.post('/api/v1/gst-registrations/lead', data);
    return res.data;
};

/** CRM entity type for all GST registration ↔ CRM links from this module. */
export const GST_CRM_ENTITY_TYPE = 'GST_REGISTRATION';

/** CRM lead stages where Schedule Payment opens with call status pre-filled. */
export const GST_CRM_SCHEDULE_PAYMENT_STAGES = new Set([
    'GST_REGISTRATION_DONE',
    'SCHEDULED_PAYMENTS',
]);

export function isGstCrmStageForSchedulePayment(stage) {
    return GST_CRM_SCHEDULE_PAYMENT_STAGES.has(String(stage || '').trim().toUpperCase());
}

/** CRM deep-link from Schedule Payment: drawer + status only on allowed lead stages. */
export const buildGstCrmLeadActionSearchParams = (gstRegistrationId, openSchedulePaymentDrawer = false) => {
    const params = new URLSearchParams({
        entity_type: GST_CRM_ENTITY_TYPE,
        entity_id: String(gstRegistrationId),
    });
    if (openSchedulePaymentDrawer) {
        params.set('target_view', 'action');
        params.set('target_call_status', 'SCHEDULED_PAYMENT');
    }
    return params;
};

/** @deprecated Use buildGstCrmLeadActionSearchParams(id, true) */
export const buildGstCrmSchedulePaymentSearchParams = (gstRegistrationId) =>
    buildGstCrmLeadActionSearchParams(gstRegistrationId, true);

/** Linked CRM GST lead for a gst_registration row (GET /crm/leads/by-entity). */
export const getCrmLeadByGstRegistrationId = async (gstRegistrationId) => {
    const res = await api.get('/api/v1/crm/leads/by-entity', {
        params: {
            entity_id: gstRegistrationId,
            entity_type: 'GST_REGISTRATION',
        },
    });
    return res.data?.data ?? res.data;
};
