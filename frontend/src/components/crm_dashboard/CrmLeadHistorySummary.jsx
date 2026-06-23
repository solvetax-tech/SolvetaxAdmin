import React from 'react';
import { Edit3, Phone, User } from 'lucide-react';
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

export default function CrmLeadHistorySummary({ lead, onCallStatus }) {
    if (!lead) return null;

    const showCallStatus = shouldShowHistoryCallStatusButton(lead);

    return (
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

            <div className="crm-history-summary-grid">
                {SUMMARY_FIELDS.map((key) => (
                    <div key={key} className="crm-history-summary-item">
                        <label>{CRM_LEAD_VIEW_FIELD_LABELS[key] || key}</label>
                        <div className="value">{formatFieldValue(key, lead[key])}</div>
                    </div>
                ))}
            </div>
        </div>
    );
}
