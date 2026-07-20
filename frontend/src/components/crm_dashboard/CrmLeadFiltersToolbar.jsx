import React from 'react';
import { Filter, RotateCcw, Plus } from 'lucide-react';
import Button from '../ui/Button';
import {
    CRM_TIMESTAMP_FILTER_FIELDS,
    getTimestampFilterSummary,
    hasActiveLeadFilters,
} from './crmLeadFilters';
import './CrmLeadFiltersToolbar.css';

/**
 * Active filter pills + Reset all + Filters button (Leads, Smart Board, Pipeline).
 */
export default function CrmLeadFiltersToolbar({
    appliedFilters,
    onOpenFilters,
    onResetFilters,
    showFiltersButton = true,
    contextPill = null,
    pushFeedback = null,
    onCreateLead = null,
}) {
    const filtersActive = hasActiveLeadFilters(appliedFilters);

    if (!showFiltersButton && !filtersActive && !contextPill && !onCreateLead) {
        return null;
    }

    return (
        <div className="tab-header-v2 crm-lead-filters-toolbar">
            <div className="active-filters-display">
                {contextPill}
                {!contextPill && appliedFilters.stages?.length > 0 && (
                    <span className="filter-pill">
                        Stages: {appliedFilters.stages.length} selected
                    </span>
                )}
                {appliedFilters.rm_id && (
                    <span className="filter-pill">RM ID: {appliedFilters.rm_id}</span>
                )}
                {appliedFilters.op_id && (
                    <span className="filter-pill">OP ID: {appliedFilters.op_id}</span>
                )}
                {appliedFilters.follow_up_status && (
                    <span className="filter-pill">Status: {appliedFilters.follow_up_status}</span>
                )}
                {appliedFilters.mobile && (
                    <span className="filter-pill">Mobile: {appliedFilters.mobile}</span>
                )}
                {appliedFilters.entity_id && (
                    <span className="filter-pill">Entity ID: {appliedFilters.entity_id}</span>
                )}
                {appliedFilters.lead_source && (
                    <span className="filter-pill">Source: {appliedFilters.lead_source}</span>
                )}
                {appliedFilters.lead_type && (
                    <span className="filter-pill">Type: {appliedFilters.lead_type}</span>
                )}
                {appliedFilters.ay && (
                    <span className="filter-pill">AY: {appliedFilters.ay}</span>
                )}
                {appliedFilters.tag && (
                    <span className="filter-pill">Tag: {appliedFilters.tag}</span>
                )}
                {appliedFilters.remarks && (
                    <span className="filter-pill">Remarks: {appliedFilters.remarks}</span>
                )}
                {CRM_TIMESTAMP_FILTER_FIELDS.map(({ key, label }) => {
                    const summary = getTimestampFilterSummary(
                        appliedFilters[`${key}_mode`],
                        appliedFilters[`${key}_date`],
                        appliedFilters[`${key}_from`],
                        appliedFilters[`${key}_to`],
                    );
                    if (!summary) return null;
                    return (
                        <span key={key} className="filter-pill">
                            {label}: {summary}
                        </span>
                    );
                })}
                {filtersActive && (
                    <button
                        type="button"
                        className="btn-filter-reset-all"
                        onClick={onResetFilters}
                        title="Clear all filters"
                    >
                        <RotateCcw size={14} />
                        Reset all
                    </button>
                )}
            </div>
            {(showFiltersButton || onCreateLead) && (
                <div className="crm-lead-filters-toolbar-actions">
                    {pushFeedback && (
                        <span
                            className={`crm-push-feedback crm-push-feedback--${pushFeedback.type}`}
                            role="status"
                        >
                            {pushFeedback.text}
                        </span>
                    )}
                    {showFiltersButton && (
                        <Button variant="secondary" size="sm" icon={<Filter size={13} />} onClick={onOpenFilters}>
                            Filters
                        </Button>
                    )}
                    {onCreateLead && (
                        <Button variant="primary" size="sm" icon={<Plus size={13} />} onClick={onCreateLead}>
                            Create Lead
                        </Button>
                    )}
                </div>
            )}
        </div>
    );
}
