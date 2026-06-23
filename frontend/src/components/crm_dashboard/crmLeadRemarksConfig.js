import { formatPitchLabel, ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS } from './crmLeadPitchUtils';

/** Preset remark for ITR CRM early pipeline stages (call_status drawer). */
export const ITR_PRESET_REMARK = 'Payment done but service pending';

/** Default remarks when call status is PAYMENT_DONE_SERVICE_PENDING. */
export const PAYMENT_PENDING_DEFAULT_REMARK = formatPitchLabel(
    ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS
);

export const STAGES_WITH_ITR_REMARKS_DROPDOWN = new Set([
    'FRESH_LEAD',
    'FRESH_LEADS',
    'FOLLOW_UP',
    'FOLLOWUP',
    'INTERESTED',
]);

/** Internal select value only — never sent to the API. */
export const CRM_REMARKS_OTHER = '__OTHER__';

export function normalizeCrmStage(stage) {
    return (stage || '').trim().toUpperCase();
}

export function usesPaymentPendingPlainRemarks(callStatusCode) {
    return (callStatusCode || '').trim().toUpperCase() === ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS;
}

export function usesItrRemarksDropdown(entityType, stage, callStatusCode) {
    if (usesPaymentPendingPlainRemarks(callStatusCode)) return false;
    return (
        (entityType || '').trim().toUpperCase() === 'INCOME_TAX'
        && STAGES_WITH_ITR_REMARKS_DROPDOWN.has(normalizeCrmStage(stage))
    );
}

export function isPresetItrRemark(value) {
    return value === ITR_PRESET_REMARK;
}

/** Lead list filter drawer — remarks dropdown options (sent to GET /crm/leads/filter). */
export const CRM_REMARKS_FILTER_OPTIONS = [
    { value: '', label: 'Any remarks' },
    {
        value: PAYMENT_PENDING_DEFAULT_REMARK,
        label: PAYMENT_PENDING_DEFAULT_REMARK,
    },
];
