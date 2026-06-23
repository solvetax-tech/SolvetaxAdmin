import api from './api';

const CRM_LEADS_COMMON_BASE = '/api/v1/crm/leads';
const CRM_LEADS_ITR_BASE = '/api/v1/crm/itr/leads';

function isIncomeTaxEntity(entityType) {
    return (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
}

/**
 * Shared CRM lead routes: filter, ui-mappings, stages, followups, activities, bulk-assign.
 * Always use the common router; pass entity_type as a query param.
 */
export function getCrmLeadsApiBase(_entityType) {
    return CRM_LEADS_COMMON_BASE;
}

/**
 * Per-lead mutation routes (call-update, edit, followup-status, entity-id).
 * ITR uses the dedicated ITR router; GST uses the common router.
 */
export function getCrmLeadsMutationApiBase(entityType) {
    return isIncomeTaxEntity(entityType) ? CRM_LEADS_ITR_BASE : CRM_LEADS_COMMON_BASE;
}

export function getFollowupStatusApiPath(entityType, leadId) {
    return `${getCrmLeadsMutationApiBase(entityType)}/${leadId}/followup-status`;
}

export function getCallUpdateApiPath(entityType, leadId) {
    return `${getCrmLeadsMutationApiBase(entityType)}/${leadId}/call-update`;
}

export function getLeadActivitiesApiPath(entityType, leadId) {
    return `${getCrmLeadsApiBase(entityType)}/${leadId}/activities`;
}

const OPEN_FOLLOWUP_STATUSES = new Set(['MISSED', 'PENDING', 'OVERDUE']);

function addCrmFollowupNotification(title, description, type = 'UPDATE', action = null, entityType = 'GST_REGISTRATION') {
    try {
        const newNotif = {
            id: Date.now(),
            title,
            description,
            type,
            action,
            context: 'CRM',
            entityType,
            timestamp: new Date().toISOString(),
        };
        const existing = JSON.parse(localStorage.getItem('st_crm_notifications') || '[]');
        localStorage.setItem('st_crm_notifications', JSON.stringify([newNotif, ...existing]));
        window.dispatchEvent(new Event('st_crm_notifications_updated'));
    } catch (err) {
        console.error('Failed to add CRM follow-up notification:', err);
    }
}

/** User-facing message from CRM API errors (validation, 4xx/5xx). */
export function extractCrmApiErrorMessage(err, fallback = 'Failed to update lead. Please try again.') {
    if (!err) return fallback;
    if (err.fields && typeof err.fields === 'object') {
        const parts = Object.values(err.fields).filter(Boolean);
        if (parts.length) return parts.join('\n');
    }
    if (typeof err.message === 'string' && err.message.trim() && err.message !== 'Operation failed') {
        return err.message;
    }
    const data = err.response?.data;
    if (data?.error?.message) return data.error.message;
    if (data?.detail?.error?.message) return data.detail.error.message;
    if (typeof data?.detail === 'string') return data.detail;
    return fallback;
}

/** True when the lead still has an open follow-up cycle (PENDING / MISSED / OVERDUE). */
export function shouldCompleteFollowupOnCallUpdate(lead) {
    const status = String(lead?.follow_up_status || '').trim().toUpperCase();
    return OPEN_FOLLOWUP_STATUSES.has(status);
}

/**
 * Send complete_open_followup on call-update when the user is closing out an open
 * follow-up: from dashboard follow-up/history, or when rescheduling with a new date.
 */
export function resolveCompleteOpenFollowupOnCallUpdate(lead, {
    fromFollowupContext = false,
    followupAt = null,
} = {}) {
    if (!shouldCompleteFollowupOnCallUpdate(lead)) return false;
    return fromFollowupContext || Boolean(followupAt);
}

/**
 * POST followup-status then call-update (GST or ITR base path).
 */
export async function submitCrmLeadCallUpdate({
    entityType,
    leadId,
    callPayload,
    completeFollowup = false,
}) {
    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const params = { entity_type: entityTypeNorm };

    const body = {
        ...callPayload,
        complete_open_followup: Boolean(completeFollowup),
    };

    const response = await api.post(
        getCallUpdateApiPath(entityTypeNorm, leadId),
        body,
        { params },
    );

    const leadPath = `/crm-dashboard?tab=leads&target_lead_id=${leadId}&target_view=history&entity_type=${entityTypeNorm}`;
    if (completeFollowup) {
        addCrmFollowupNotification(
            'Follow-up Completed',
            `CRM Lead #${leadId} was marked as completed.`,
            'UPDATE',
            { label: 'View Lead', path: leadPath },
            entityTypeNorm,
        );
    } else if (callPayload?.followup_at) {
        addCrmFollowupNotification(
            'Follow-up Scheduled',
            `CRM Lead #${leadId} follow-up was scheduled.`,
            'CREATE',
            { label: 'View Lead', path: leadPath },
            entityTypeNorm,
        );
    }

    window.dispatchEvent(new Event('st_followups_updated'));

    return response;
}
