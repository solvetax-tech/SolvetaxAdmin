import React, { useState } from 'react';
import { Edit3, Phone, User, CreditCard } from 'lucide-react';
import AddPayment from '../payments/AddPayment';
import { CRM_LEAD_VIEW_FIELD_LABELS, formatCrmLeadDateTime } from './crmLeadTableConfig';
import { shouldShowHistoryCallStatusButton } from './crmLeadPitchUtils';

function formatDisplayMobile(mobile) {
    const digits = String(mobile || '').replace(/\D/g, '');
    if (digits.length === 10) return `+91 ${digits}`;
    return mobile || '—';
}

function formatFieldValue(key, value) {
    if (value == null || value === '') return '—';
    if (key === 'stage') {
        return (
            <span className={`stage-badge ${String(value).toLowerCase()}`}>
                {String(value).replace(/_/g, ' ')}
            </span>
        );
    }
    if (key.endsWith('_at') || key === 'followup_at') {
        return formatCrmLeadDateTime(value);
    }
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'object') return '—';
    return String(value);
}

const SUMMARY_FIELDS = [
    'id',
    'mobile',
    'full_name',
    'stage',
    'entity_id',
    'preferred_language',
    'rm_name',
    'op_name',
    'call_attempted_count',
    'call_connected_count',
    'followup_at',
    'follow_up_status',
    'lead_source',
    'remarks',
];

export default function CrmLeadHistorySummary({ lead, onCallStatus, onPaymentRecorded }) {
    // Record the payment INLINE (AddPayment renders its own modal overlay) so the
    // RM stays inside the CRM instead of being thrown to the main dashboard.
    const [showPayment, setShowPayment] = useState(false);
    if (!lead) return null;

    const showCallStatus = shouldShowHistoryCallStatusButton(lead);
    // Record Payment is available once the lead is linked to a record (entity_id)
    // and not already fully paid (SUBSCRIBED). service_type mirrors the funnel:
    // GST_REGISTRATION (NULL entity_type is treated as GST) or INCOME_TAX.
    const paymentServiceType = String(lead.entity_type || 'GST_REGISTRATION').toUpperCase();
    const showRecordPayment =
        Boolean(lead.entity_id) && String(lead.stage || '').toUpperCase() !== 'SUBSCRIBED';

    return (
        <>
        <div className="crm-history-summary">
            <div className="crm-history-summary-header">
                <div className="crm-history-summary-title">
                    <User size={20} />
                    <div>
                        <h4>Lead details</h4>
                        <p className="crm-history-summary-phone">
                            <Phone size={14} />
                            Phone: {formatDisplayMobile(lead.mobile)}
                        </p>
                    </div>
                </div>
                <div className="crm-history-summary-actions" style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    {showRecordPayment && (
                        <button
                            type="button"
                            className="btn-primary-action crm-history-call-status-btn"
                            onClick={() => setShowPayment(true)}
                            title="Record a payment for this record"
                        >
                            <CreditCard size={14} />
                            <span>Record Payment</span>
                        </button>
                    )}
                    {showCallStatus && onCallStatus && (
                        <button
                            type="button"
                            className="btn-primary-action crm-history-call-status-btn"
                            onClick={onCallStatus}
                            title="Update call status"
                        >
                            <Edit3 size={14} />
                            <span>Update Call Status</span>
                        </button>
                    )}
                </div>
            </div>

            <div className="crm-history-summary-grid">
                {SUMMARY_FIELDS.map((key) => (
                    <div key={key} className="crm-history-summary-item">
                        <label>{CRM_LEAD_VIEW_FIELD_LABELS[key] || key}</label>
                        <div className="value">{formatFieldValue(key, lead[key])}</div>
                    </div>
                ))}
            </div>
        </div>
        {showPayment && (
            <AddPayment
                initialServiceType={paymentServiceType}
                initialEntityId={lead.entity_id}
                onBack={() => {
                    setShowPayment(false);
                    // AddPayment auto-closes on success, so refresh the lead here
                    // to reflect the new stage (e.g. SUBSCRIBED after full payment).
                    onPaymentRecorded?.();
                }}
            />
        )}
        </>
    );
}
