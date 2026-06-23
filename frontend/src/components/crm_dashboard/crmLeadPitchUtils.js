/** CRM pitch types from stage_to_pitch / pitch_to_status mappings. */

export const PITCH_TYPES = {
    FIRST: 'FIRST_PITCH_CALL',
    FINAL: 'FINAL_PITCH_CALL',
};

/** Call statuses used when deep-linking from Schedule Payment (GST / Income Tax). */
export const SCHEDULE_PAYMENT_CALL_STATUSES = new Set([
    'SCHEDULED_PAYMENT',
    'SCHEDULE_PAYMENT',
    'SCHEDULED_PAYMENTS',
]);

export function normalizeSchedulePaymentCallStatus(code) {
    const u = (code || '').trim().toUpperCase();
    if (u === 'SCHEDULE_PAYMENT' || u === 'SCHEDULED_PAYMENTS') return 'SCHEDULED_PAYMENT';
    return u;
}

export function isSchedulePaymentCallStatus(code) {
    return SCHEDULE_PAYMENT_CALL_STATUSES.has((code || '').trim().toUpperCase());
}

/** ITR first-pitch: show PAYMENT_DONE_SERVICE_PENDING in call status dropdown (POST as-is; API aliases to SEND_DOCS). */
export const ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS = 'PAYMENT_DONE_SERVICE_PENDING';

export const ITR_STAGES_WITH_PAYMENT_PENDING_CALL_STATUS = new Set([
    'FRESH_LEAD',
    'FRESH_LEADS',
    'FOLLOW_UP',
    'FOLLOWUP',
    'INTERESTED',
    'NOT_INTERESTED',
]);

export function normalizeStage(stage) {
    return (stage || '').trim().toUpperCase();
}

/** Stages where call_status update is not shown (list actions + history summary). */
export const STAGES_HIDE_CALL_STATUS = new Set([
    'SUBSCRIBED',
    'PENDING_ITR_DATA',
    'PENDING_REGISTRATION_DATA',
]);

export function shouldShowCallStatusAction(leadStage) {
    return !STAGES_HIDE_CALL_STATUS.has(normalizeStage(leadStage));
}

/** History / notification landing: allow call update when follow-up is still open. */
export function shouldShowHistoryCallStatusButton(lead) {
    if (!lead) return false;
    if (shouldShowCallStatusAction(lead.stage)) return true;
    const fus = normalizeStage(lead.follow_up_status);
    return fus === 'MISSED' || fus === 'PENDING' || fus === 'OVERDUE';
}

const FINAL_PITCH_STAGES = new Set([
    'GST_REGISTRATION_DONE',
    'ITR_DONE',
    'SCHEDULED_PAYMENTS',
]);

/** Resolve pitch type for call-update drawer from stage_to_pitch mappings. */
export function resolvePitchTypeForCallUpdate(lead, stageToPitch = [], options = {}) {
    const { initialCallStatus } = options;
    if (initialCallStatus === 'SCHEDULED_PAYMENT') {
        return PITCH_TYPES.FINAL;
    }

    const fromMapping = getPitchTypeForLeadStage(lead, stageToPitch);
    if (fromMapping) return fromMapping;

    const stage = normalizeStage(lead?.stage);
    if (FINAL_PITCH_STAGES.has(stage)) return PITCH_TYPES.FINAL;
    return PITCH_TYPES.FIRST;
}

/** Pitch type configured for this lead's current stage (from ui-mappings). */
export function getPitchTypeForLeadStage(lead, stageToPitch = []) {
    const stage = normalizeStage(lead?.stage);
    if (!stage) return null;
    const match = stageToPitch.find(
        (m) => normalizeStage(m.stage) === stage
    );
    return match?.pitch_type_code || null;
}

export function leadSupportsPitchType(lead, stageToPitch, pitchTypeCode) {
    return getPitchTypeForLeadStage(lead, stageToPitch) === pitchTypeCode;
}

export function isIncomeTaxEntity(entityType) {
    return (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
}

export function shouldShowItrPaymentPendingCallStatus(entityType, leadStage) {
    return (
        isIncomeTaxEntity(entityType)
        && ITR_STAGES_WITH_PAYMENT_PENDING_CALL_STATUS.has(normalizeStage(leadStage))
    );
}

const FIRST_PITCH_STATUS_FALLBACK = [
    'CALL_NOT_ANSWERED',
    'CALL_NOT_CONNECTED',
    'CALL_BUSY',
    'CALL_DONE',
    'CALL_BACK',
    'CONNECTED_AND_SCHEDULED',
    'SEND_DOCS',
    'NOT_INTERESTED',
];

const FINAL_PITCH_STATUS_FALLBACK = [
    'CALL_NOT_ANSWERED',
    'CALL_NOT_CONNECTED',
    'CALL_BUSY',
    'CALL_DONE',
    'CALL_BACK',
    'SCHEDULED_PAYMENT',
    'NOT_INTERESTED',
];

export function getAvailableStatusCodes(pitchTypeCode, pitchToStatuses = {}, options = {}) {
    const { entityType, leadStage } = options;
    const statuses = pitchToStatuses[pitchTypeCode] || [];
    let codes = statuses.map((s) => s.call_status_code).filter(Boolean);

    if (pitchTypeCode === PITCH_TYPES.FIRST) {
        const allowed = [
            ...FIRST_PITCH_STATUS_FALLBACK,
            ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS,
        ];
        codes = codes.length
            ? codes.filter((c) => allowed.includes(c))
            : [...FIRST_PITCH_STATUS_FALLBACK];
        if (!codes.includes('CONNECTED_AND_SCHEDULED')) codes.push('CONNECTED_AND_SCHEDULED');
        if (!codes.includes('SEND_DOCS')) codes.push('SEND_DOCS');
        if (!codes.includes('CALL_DONE')) codes.push('CALL_DONE');
        if (shouldShowItrPaymentPendingCallStatus(entityType, leadStage)) {
            if (!codes.includes(ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS)) {
                codes.push(ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS);
            }
        } else {
            codes = codes.filter((c) => c !== ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS);
        }
    } else if (pitchTypeCode === PITCH_TYPES.FINAL) {
        const allowed = [...FINAL_PITCH_STATUS_FALLBACK];
        codes = codes.length
            ? codes.filter((c) => allowed.includes(c))
            : [...FINAL_PITCH_STATUS_FALLBACK];
        if (!codes.includes('SCHEDULED_PAYMENT')) codes.push('SCHEDULED_PAYMENT');
        if (!codes.includes('CALL_DONE')) codes.push('CALL_DONE');
    }

    return codes;
}

/** Pitch type the backend expects for this lead's current stage (ui-mappings). */
export function resolveCallTypeForLeadUpdate(lead, stageToPitch = [], options = {}) {
    return getPitchTypeForLeadStage(lead, stageToPitch)
        || resolvePitchTypeForCallUpdate(lead, stageToPitch, options);
}

export function formatPitchLabel(code) {
    return (code || '').replace(/_/g, ' ');
}

export function getCallUpdateApiPath(entityType, leadId) {
    const base = isIncomeTaxEntity(entityType)
        ? '/api/v1/crm/itr/leads'
        : '/api/v1/crm/leads';
    return `${base}/${leadId}/call-update`;
}
