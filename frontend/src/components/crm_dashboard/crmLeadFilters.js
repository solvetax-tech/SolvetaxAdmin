export const CRM_TIMESTAMP_FILTER_FIELDS = [
    { key: 'rm_assigned_at', label: 'RM assigned at' },
    { key: 'op_assigned_at', label: 'OP assigned at' },
    { key: 'last_dailed_at', label: 'Last dialed at' },
    { key: 'last_connected_at', label: 'Last connected at' },
];

export const TIMESTAMP_FILTER_MODE_OPTIONS = [
    { value: '', label: 'Any' },
    { value: 'today', label: 'Today' },
    { value: 'date', label: 'On date' },
    { value: 'range', label: 'Date range' },
];

export function getIstDateKey(value = new Date()) {
    const dt = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(dt.getTime())) return '';
    return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).format(dt);
}

/** Inclusive IST calendar-day bounds as ISO strings for API query params. */
export function istDateKeyToIsoBounds(dateKey) {
    if (!dateKey || !/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) {
        return { from: '', to: '' };
    }
    const from = `${dateKey}T00:00:00+05:30`;
    const to = `${dateKey}T23:59:59.999+05:30`;
    return {
        from: new Date(from).toISOString(),
        to: new Date(to).toISOString(),
    };
}

export function resolveTimestampFilterBounds(mode, date, from, to) {
    if (!mode) return { from: undefined, to: undefined };
    if (mode === 'today') return istDateKeyToIsoBounds(getIstDateKey(new Date()));
    if (mode === 'date' && date) return istDateKeyToIsoBounds(date);
    if (mode === 'range') {
        const out = { from: undefined, to: undefined };
        if (from) out.from = istDateKeyToIsoBounds(from).from;
        if (to) out.to = istDateKeyToIsoBounds(to).to;
        return out;
    }
    return { from: undefined, to: undefined };
}

function appendTimestampFields(target, initial) {
    CRM_TIMESTAMP_FILTER_FIELDS.forEach(({ key }) => {
        target[`${key}_mode`] = initial?.[`${key}_mode`] || '';
        target[`${key}_date`] = initial?.[`${key}_date`] || '';
        target[`${key}_from`] = initial?.[`${key}_from`] || '';
        target[`${key}_to`] = initial?.[`${key}_to`] || '';
    });
}

export const buildEmptyLeadFilters = (initial) => {
    const base = {
        mobile: initial?.mobile || '',
        stages: initial?.stages ? [...initial.stages] : [],
        follow_up_status: initial?.follow_up_status || '',
        rm_id: initial?.rm_id || '',
        op_id: initial?.op_id || '',
        is_active: initial?.is_active || '',
        entity_id: initial?.entity_id || '',
        lead_source: initial?.lead_source || '',
        tag: initial?.tag || '',
        remarks: initial?.remarks || '',
        lead_type: initial?.lead_type || '',
        ay: initial?.ay || '',
        followup_at_from: initial?.followup_at_from || '',
        followup_at_to: initial?.followup_at_to || '',
    };
    appendTimestampFields(base, initial);
    return base;
};

export function countTimestampActiveFilters(filterInputs = {}) {
    return CRM_TIMESTAMP_FILTER_FIELDS.reduce((count, { key }) => (
        filterInputs[`${key}_mode`] ? count + 1 : count
    ), 0);
}

/** Count every active drawer filter (identity, status, categorization, timestamps). */
export function countActiveLeadFilters(filterInputs = {}) {
    if (!filterInputs) return 0;
    let count = 0;
    if (filterInputs.mobile?.trim()) count += 1;
    if (filterInputs.entity_id?.toString().trim()) count += 1;
    if (filterInputs.follow_up_status) count += 1;
    if (filterInputs.rm_id?.toString().trim()) count += 1;
    if (filterInputs.op_id?.toString().trim()) count += 1;
    if (filterInputs.lead_type?.trim()) count += 1;
    if (filterInputs.ay?.trim()) count += 1;
    if (filterInputs.lead_source?.trim()) count += 1;
    if (filterInputs.tag?.trim()) count += 1;
    if (filterInputs.remarks?.trim()) count += 1;
    if (filterInputs.stages?.length > 0) count += 1;
    if (filterInputs.followup_at_from || filterInputs.followup_at_to) count += 1;
    count += countTimestampActiveFilters(filterInputs);
    return count;
}

export function hasActiveLeadFilters(filterInputs = {}) {
    return countActiveLeadFilters(filterInputs) > 0;
}

export function buildCrmLeadFilterApiParams(appliedFilters = {}, extra = {}) {
    const params = {
        mobile: appliedFilters.mobile || undefined,
        follow_up_status: appliedFilters.follow_up_status || undefined,
        rm_id: appliedFilters.rm_id ? parseInt(appliedFilters.rm_id, 10) : undefined,
        op_id: appliedFilters.op_id ? parseInt(appliedFilters.op_id, 10) : undefined,
        lead_type: appliedFilters.lead_type || undefined,
        ay: appliedFilters.ay?.trim() || undefined,
        tag: appliedFilters.tag || undefined,
        remarks: appliedFilters.remarks?.trim() || undefined,
        lead_source: appliedFilters.lead_source || undefined,
        entity_id: appliedFilters.entity_id ? parseInt(appliedFilters.entity_id, 10) : undefined,
        followup_at_from: appliedFilters.followup_at_from || undefined,
        followup_at_to: appliedFilters.followup_at_to || undefined,
        ...extra,
    };

    if (appliedFilters.stages?.length > 0) {
        params.stages = appliedFilters.stages;
    }

    CRM_TIMESTAMP_FILTER_FIELDS.forEach(({ key }) => {
        const bounds = resolveTimestampFilterBounds(
            appliedFilters[`${key}_mode`],
            appliedFilters[`${key}_date`],
            appliedFilters[`${key}_from`],
            appliedFilters[`${key}_to`],
        );
        if (bounds.from) params[`${key}_from`] = bounds.from;
        if (bounds.to) params[`${key}_to`] = bounds.to;
    });

    return params;
}

export function serializeCrmLeadFilterParams(params = {}) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return;
        if (Array.isArray(value)) {
            value.forEach((v) => searchParams.append(key, v));
        } else {
            searchParams.append(key, value);
        }
    });
    return searchParams.toString();
}

export function getTimestampFilterSummary(mode, date, from, to) {
    if (!mode) return '';
    if (mode === 'today') return 'Today';
    if (mode === 'date' && date) return date;
    if (mode === 'range') {
        if (from && to) return `${from} → ${to}`;
        if (from) return `From ${from}`;
        if (to) return `Until ${to}`;
    }
    return 'Custom';
}
