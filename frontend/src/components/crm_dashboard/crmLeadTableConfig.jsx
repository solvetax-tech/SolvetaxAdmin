import { getFollowupActivityBadge } from '../../utils/followupsApi';

/** Fixed columns for CRM lead list tables (Leads, Pipeline, Smart Board). */

const CRM_LEAD_TABLE_COLUMNS_BASE = [
    { key: 'id', label: 'Id' },
    { key: 'mobile', label: 'Mobile' },
    { key: 'full_name', label: 'Full Name' },
    { key: 'entity_id', label: 'Entity Id' },
    { key: 'preferred_language', label: 'Preferred Language' },
    { key: 'stage', label: 'Stage' },
    { key: 'call_attempted_count', label: 'Call Attempts', className: 'count-column' },
    { key: 'call_connected_count', label: 'Call Connected', className: 'count-column' },
    { key: 'remarks', label: 'Remarks', className: 'remarks-column' },
    { key: 'rm_name', label: 'RM Name' },
    { key: 'op_name', label: 'OP Name' },
];

export const CRM_LEAD_TABLE_COLUMNS = CRM_LEAD_TABLE_COLUMNS_BASE;

/** Income Tax CRM adds assessment year between entity id and preferred language. */
export function getCrmLeadTableColumns({ isIncomeTaxCrm = false } = {}) {
    if (!isIncomeTaxCrm) return CRM_LEAD_TABLE_COLUMNS_BASE;
    const cols = [...CRM_LEAD_TABLE_COLUMNS_BASE];
    const entityIdx = cols.findIndex((col) => col.key === 'entity_id');
    cols.splice(entityIdx + 1, 0, { key: 'ay', label: 'AY', className: 'crm-col-ay' });
    return cols;
}

export function formatCrmLeadDateTime(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return String(dateStr);
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    return `${d}-${m}-${y} ${hh}:${mm}`;
}

export function renderCrmLeadTableCell(lead, col, formatDateTime = formatCrmLeadDateTime) {
    const key = col.key;
    const val = lead[key];

    if (key === 'stage') {
        return (
            <span className={`stage-badge ${(val || '').toLowerCase()}`}>{val || '-'}</span>
        );
    }

    if (key === 'follow_up_status') {
        const { statusBadgeClass, statusTextString } = getFollowupActivityBadge(lead);
        return (
            <span className={`status-badge followup-status-badge ${statusBadgeClass}`}>
                {statusTextString}
            </span>
        );
    }

    const isDateColumn =
        key.endsWith('_at') || key.endsWith('_date') || key === 'followup_at';

    if (isDateColumn && val) {
        return formatDateTime(val);
    }

    if (val == null || val === '') return '-';
    if (typeof val === 'object') return '-';
    return String(val);
}

/** Labels for read-only view drawer (all lead fields). */
export const CRM_LEAD_VIEW_FIELD_LABELS = {
    id: 'Lead ID',
    mobile: 'Mobile',
    full_name: 'Full Name',
    email: 'Email',
    entity_id: 'Entity ID',
    entity_type: 'Entity Type',
    preferred_language: 'Preferred Language',
    stage: 'Stage',
    call_attempted_count: 'Call Attempts',
    call_connected_count: 'Call Connected',
    follow_up_status: 'Follow-up Status',
    followup_at: 'Follow-up At',
    rm_id: 'RM ID',
    op_id: 'OP ID',
    rm_name: 'RM Name',
    op_name: 'OP Name',
    remarks: 'Remarks',
    lead_type: 'Lead Type',
    ay: 'Assessment Year',
    tag: 'Tag',
    lead_source: 'Lead Source',
    last_dailed_at: 'Last Dialed At',
    last_connected_at: 'Last Connected At',
    completed_at: 'Completed At',
    missed_at: 'Missed At',
    is_active: 'Active',
    created_at: 'Created At',
    updated_at: 'Updated At',
};

const VIEW_SKIP_KEYS = new Set(['history']);

export function getCrmLeadViewEntries(lead) {
    if (!lead || typeof lead !== 'object') return [];
    return Object.keys(lead)
        .filter((k) => !VIEW_SKIP_KEYS.has(k))
        .sort((a, b) => {
            const order = Object.keys(CRM_LEAD_VIEW_FIELD_LABELS);
            const ia = order.indexOf(a);
            const ib = order.indexOf(b);
            if (ia === -1 && ib === -1) return a.localeCompare(b);
            if (ia === -1) return 1;
            if (ib === -1) return -1;
            return ia - ib;
        })
        .map((key) => ({
            key,
            label:
                CRM_LEAD_VIEW_FIELD_LABELS[key]
                || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            value: lead[key],
        }));
}
