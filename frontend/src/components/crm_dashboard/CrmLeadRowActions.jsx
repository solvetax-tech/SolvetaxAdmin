import React from 'react';
import { Loader2, Upload, Eye, History, Edit3 } from 'lucide-react';
import { normalizeStage, shouldShowCallStatusAction } from './crmLeadPitchUtils';

/** ITR stages where Push/Pushed is hidden (lead already linked or past push workflow). */
const ITR_STAGES_HIDE_PUSH = new Set([
    'FRESH_LEAD',
    'FRESH_LEADS',
    'FOLLOW_UP',
    'FOLLOWUP',
    'INTERESTED',
    'SUBSCRIBED',
    'ITR_DONE',
    'SCHEDULED_PAYMENT',
    'SCHEDULED_PAYMENTS',
    'NOT_INTERESTED',
]);

const GST_PUSH_STAGE = 'PENDING_REGISTRATION_DATA';

/**
 * Actions: Push (ITR / GST) + View + Call status + History.
 *
 * Icon-only — each button carries its label in `title` (hover tooltip) and
 * `aria-label` (screen readers), so dropping the visible text loses nothing.
 */
export default function CrmLeadRowActions({
    lead,
    isIncomeTaxCrm,
    isGstCrm,
    isLeadPushed,
    onPush,
    pushingLeadId,
    onView,
    onEdit,
    onHistory,
}) {
    const pushed = isLeadPushed(lead);
    const isPushing = pushingLeadId === lead.id;
    const pushBlocked = pushingLeadId != null && pushingLeadId !== lead.id;
    const stage = normalizeStage(lead.stage);
    const showPushItr = isIncomeTaxCrm && !ITR_STAGES_HIDE_PUSH.has(stage);
    const showPushGst = isGstCrm && stage === GST_PUSH_STAGE;
    const showPush = showPushItr || showPushGst;
    const showCallStatus = shouldShowCallStatusAction(stage);
    const actionCount = (showPush ? 1 : 0) + 1 + (showCallStatus ? 1 : 0) + 1;

    return (
        <div className="crm-row-actions" data-action-count={actionCount}>
            {showPush && (
                <button
                    type="button"
                    className={`btn-push-mini${pushed ? ' is-done' : ''}`}
                    onClick={onPush}
                    disabled={pushed || isPushing || pushBlocked}
                    title={
                        pushed
                            ? isGstCrm
                                ? `Linked to GST registration ${lead.entity_id}`
                                : `Linked to ITR ${lead.entity_id}`
                            : isGstCrm
                                ? 'Create GST registration and link this lead'
                                : 'Create income tax record and link this lead'
                    }
                    aria-label={pushed ? 'Pushed' : 'Push'}
                >
                    {isPushing ? (
                        <Loader2 size={14} className="spin" />
                    ) : (
                        <Upload size={14} />
                    )}
                </button>
            )}
            <button
                type="button"
                className="btn-view-mini"
                onClick={onView}
                title="View all lead fields"
                aria-label="View lead"
            >
                <Eye size={14} />
            </button>
            {showCallStatus && (
                <button
                    type="button"
                    className="btn-edit-mini"
                    onClick={onEdit}
                    title="Update call status"
                    aria-label="Update call status"
                >
                    <Edit3 size={14} />
                </button>
            )}
            <button
                type="button"
                className="btn-history-mini"
                onClick={onHistory}
                title="Call history and linked registration"
                aria-label="Call history"
            >
                <History size={14} />
            </button>
        </div>
    );
}
