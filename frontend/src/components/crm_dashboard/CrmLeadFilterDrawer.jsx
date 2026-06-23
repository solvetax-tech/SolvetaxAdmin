import React, { useMemo, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import api from '../../utils/api';
import {
    X,
    Filter,
    Hash,
    Smartphone,
    ClipboardList,
    Users,
    Tag,
    MessageSquare,
    Clock,
} from 'lucide-react';
import { CRM_REMARKS_FILTER_OPTIONS } from './crmLeadRemarksConfig';
import {
    CRM_TIMESTAMP_FILTER_FIELDS,
    TIMESTAMP_FILTER_MODE_OPTIONS,
    countActiveLeadFilters,
} from './crmLeadFilters';
import CustomSelect from '../common/CustomSelect';
import FilterDateInput from '../common/FilterDateInput';
import { parseActiveUsernamesFromApi, toEmployeeFilterOptions } from '../../utils/activeEmployees';
import { buildFinancialYearPresetOptions } from '../../utils/incomeTaxArrays';
import './crmCallActionDrawer.css';

const AY_FILTER_PRESETS = buildFinancialYearPresetOptions({ yearsBack: 8 });

const FOLLOW_UP_STATUS_OPTIONS = [
    { value: '', label: 'Any status' },
    { value: 'PENDING', label: 'Pending' },
    { value: 'OVERDUE', label: 'Overdue' },
    { value: 'COMPLETED', label: 'Completed' },
    { value: 'MISSED', label: 'Missed' },
];

function TimestampFilterRow({ fieldKey, label, filterInputs, patch }) {
    const mode = filterInputs[`${fieldKey}_mode`] || '';
    const dateValue = filterInputs[`${fieldKey}_date`] || '';
    const fromValue = filterInputs[`${fieldKey}_from`] || '';
    const toValue = filterInputs[`${fieldKey}_to`] || '';

    const setMode = (nextMode) => {
        patch({
            [`${fieldKey}_mode`]: nextMode,
            [`${fieldKey}_date`]: '',
            [`${fieldKey}_from`]: '',
            [`${fieldKey}_to`]: '',
        });
    };

    return (
        <div className="crm-call-action-field crm-timestamp-filter-field">
            <label>
                <Clock size={13} />
                {label}
            </label>
            <CustomSelect
                value={mode}
                options={TIMESTAMP_FILTER_MODE_OPTIONS}
                onChange={setMode}
                ariaLabel={label}
                placeholder="Any"
                menuMaxHeight={200}
            />
            {mode === 'date' && (
                <div style={{ marginTop: 8 }}>
                    <FilterDateInput
                        compact
                        className="crm-timestamp-date-wrap"
                        inputClassName="crm-input-field"
                        value={dateValue}
                        onChange={(e) => patch({ [`${fieldKey}_date`]: e.target.value })}
                        ariaLabel={`${label} date`}
                    />
                </div>
            )}
            {mode === 'range' && (
                <div className="crm-call-action-field-grid" style={{ marginTop: 8 }}>
                    <FilterDateInput
                        compact
                        className="crm-timestamp-date-wrap"
                        inputClassName="crm-input-field"
                        value={fromValue}
                        onChange={(e) => patch({ [`${fieldKey}_from`]: e.target.value })}
                        ariaLabel={`${label} from`}
                    />
                    <FilterDateInput
                        compact
                        className="crm-timestamp-date-wrap"
                        inputClassName="crm-input-field"
                        value={toValue}
                        onChange={(e) => patch({ [`${fieldKey}_to`]: e.target.value })}
                        ariaLabel={`${label} to`}
                    />
                </div>
            )}
        </div>
    );
}

export default function CrmLeadFilterDrawer({
    open,
    filterInputs,
    setFilterInputs,
    stages = [],
    entityType = '',
    onClose,
    onReset,
    onApply,
    showPipelineStages = true,
}) {
    const activeCount = useMemo(() => countActiveLeadFilters(filterInputs), [filterInputs]);
    const isIncomeTaxCrm = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [employeesLoading, setEmployeesLoading] = useState(false);

    useEffect(() => {
        if (!open) return undefined;
        let cancelled = false;
        setEmployeesLoading(true);
        Promise.all([
            api.get('/api/v1/employees/active-rm'),
            api.get('/api/v1/employees/active-op'),
        ])
            .then(([rmRes, opRes]) => {
                if (cancelled) return;
                setActiveRMs(parseActiveUsernamesFromApi(rmRes));
                setActiveOps(parseActiveUsernamesFromApi(opRes));
            })
            .catch((err) => console.error('CrmLeadFilterDrawer: employee fetch failed', err))
            .finally(() => {
                if (!cancelled) setEmployeesLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [open]);

    const rmOptions = useMemo(() => toEmployeeFilterOptions(activeRMs, 'Any RM'), [activeRMs]);
    const opOptions = useMemo(() => toEmployeeFilterOptions(activeOps, 'Any OP'), [activeOps]);

    if (!open) return null;

    const patch = (updates) => setFilterInputs((prev) => ({ ...prev, ...updates }));

    const toggleStage = (code) => {
        setFilterInputs((prev) => {
            const selected = prev.stages || [];
            const nextStages = selected.includes(code)
                ? selected.filter((c) => c !== code)
                : [...selected, code];
            return { ...prev, stages: nextStages };
        });
    };

    return createPortal(
        <>
            <div
                className="crm-drawer-overlay"
                onClick={onClose}
                role="presentation"
            />
            <div
                className="crm-drawer-panel crm-call-action-drawer crm-filter-drawer"
                role="dialog"
                aria-labelledby="crm-filter-drawer-title"
                onClick={(e) => e.stopPropagation()}
            >
                <header className="crm-call-action-hero">
                    <button
                        type="button"
                        className="crm-call-action-close"
                        onClick={onClose}
                        aria-label="Close"
                    >
                        <X size={18} />
                    </button>
                    <div className="crm-call-action-hero-inner">
                        <div className="crm-call-action-avatar">
                            <Filter size={22} strokeWidth={2} />
                        </div>
                        <div className="crm-call-action-hero-text">
                            <h3 id="crm-filter-drawer-title">Filter leads</h3>
                            <p className="crm-call-action-hero-meta">Narrow your lead list</p>
                            <div className="crm-call-action-badges">
                                {activeCount > 0 ? (
                                    <span className="crm-filter-active-count">
                                        {activeCount} active filter{activeCount !== 1 ? 's' : ''}
                                    </span>
                                ) : (
                                    <span className="crm-call-action-stage">No filters applied</span>
                                )}
                            </div>
                        </div>
                    </div>
                </header>

                <div className="crm-filter-drawer-scroll" role="region" aria-label="Filter options">
                <div className="drawer-body crm-call-action-body">
                    <section>
                        <h4 className="crm-call-action-section-title">Identity</h4>
                        <div className="crm-call-action-card">
                            <div className="crm-call-action-field-grid">
                                <div className="crm-call-action-field">
                                    <label>
                                        <Hash size={13} />
                                        Entity ID
                                    </label>
                                    <input
                                        type="text"
                                        className="crm-input-field"
                                        placeholder="ID..."
                                        value={filterInputs.entity_id}
                                        onChange={(e) => patch({ entity_id: e.target.value })}
                                    />
                                </div>
                                <div className="crm-call-action-field">
                                    <label>
                                        <Smartphone size={13} />
                                        Mobile
                                    </label>
                                    <input
                                        type="text"
                                        className="crm-input-field"
                                        placeholder="Mobile..."
                                        value={filterInputs.mobile}
                                        onChange={(e) => patch({ mobile: e.target.value })}
                                    />
                                </div>
                            </div>
                        </div>
                    </section>

                    <section>
                        <h4 className="crm-call-action-section-title">Status &amp; assignment</h4>
                        <div className="crm-call-action-card">
                            <div className="crm-call-action-fields">
                                <div className="crm-call-action-field">
                                    <label>
                                        <ClipboardList size={13} />
                                        Follow status
                                    </label>
                                    <CustomSelect
                                        value={filterInputs.follow_up_status || ''}
                                        options={FOLLOW_UP_STATUS_OPTIONS}
                                        onChange={(val) => patch({ follow_up_status: val })}
                                        ariaLabel="Follow status"
                                        placeholder="Any status"
                                        menuMaxHeight={200}
                                    />
                                </div>
                                <div className="crm-call-action-field-grid">
                                    <div className="crm-call-action-field">
                                        <label>
                                            <Users size={13} />
                                            RM
                                        </label>
                                        <CustomSelect
                                            value={filterInputs.rm_id?.toString() || ''}
                                            options={rmOptions}
                                            onChange={(val) => patch({ rm_id: val })}
                                            ariaLabel="Relationship manager"
                                            placeholder={employeesLoading ? 'Loading...' : 'Any RM'}
                                            menuMaxHeight={220}
                                            disabled={employeesLoading}
                                        />
                                    </div>
                                    <div className="crm-call-action-field">
                                        <label>OP</label>
                                        <CustomSelect
                                            value={filterInputs.op_id?.toString() || ''}
                                            options={opOptions}
                                            onChange={(val) => patch({ op_id: val })}
                                            ariaLabel="Operations"
                                            placeholder={employeesLoading ? 'Loading...' : 'Any OP'}
                                            menuMaxHeight={220}
                                            disabled={employeesLoading}
                                        />
                                    </div>
                                </div>
                                <div className="crm-timestamp-filters-block">
                                    <p className="crm-timestamp-filters-hint">
                                        Assignment &amp; call timestamps (IST) — Today or pick a date.
                                    </p>
                                    <div className="crm-timestamp-filters-grid">
                                    {CRM_TIMESTAMP_FILTER_FIELDS.map(({ key, label }) => (
                                        <TimestampFilterRow
                                            key={key}
                                            fieldKey={key}
                                            label={label}
                                            filterInputs={filterInputs}
                                            patch={patch}
                                        />
                                    ))}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    <section>
                        <h4 className="crm-call-action-section-title">Categorization</h4>
                        <div className="crm-call-action-card">
                            <div className="crm-call-action-field-grid">
                                <div className="crm-call-action-field">
                                    <label>Lead type</label>
                                    <input
                                        type="text"
                                        className="crm-input-field"
                                        placeholder="Type..."
                                        value={filterInputs.lead_type}
                                        onChange={(e) => patch({ lead_type: e.target.value })}
                                    />
                                </div>
                                <div className="crm-call-action-field">
                                    <label>Lead source</label>
                                    <input
                                        type="text"
                                        className="crm-input-field"
                                        placeholder="Source..."
                                        value={filterInputs.lead_source}
                                        onChange={(e) => patch({ lead_source: e.target.value })}
                                    />
                                </div>
                                {isIncomeTaxCrm && (
                                    <div className="crm-call-action-field">
                                        <label>Assessment year (AY)</label>
                                        <input
                                            type="text"
                                            className="crm-input-field"
                                            list="crm-ay-filter-presets"
                                            placeholder="e.g. 2024-25"
                                            value={filterInputs.ay || ''}
                                            onChange={(e) => patch({ ay: e.target.value })}
                                        />
                                        <datalist id="crm-ay-filter-presets">
                                            {AY_FILTER_PRESETS.map((ay) => (
                                                <option key={ay} value={ay} />
                                            ))}
                                        </datalist>
                                    </div>
                                )}
                            </div>
                            <div className="crm-call-action-field" style={{ marginTop: 12 }}>
                                <label>
                                    <Tag size={13} />
                                    Tag
                                </label>
                                <input
                                    type="text"
                                    className="crm-input-field"
                                    placeholder="Tag..."
                                    value={filterInputs.tag}
                                    onChange={(e) => patch({ tag: e.target.value })}
                                />
                            </div>
                            <div className="crm-call-action-field" style={{ marginTop: 12 }}>
                                <label>
                                    <MessageSquare size={13} />
                                    Remarks
                                </label>
                                <CustomSelect
                                    value={filterInputs.remarks || ''}
                                    options={CRM_REMARKS_FILTER_OPTIONS}
                                    onChange={(val) => patch({ remarks: val })}
                                    ariaLabel="Remarks filter"
                                    placeholder="Any remarks"
                                    menuMaxHeight={200}
                                />
                            </div>
                        </div>
                    </section>

                    {showPipelineStages && stages.length > 0 && (
                        <section>
                            <h4 className="crm-call-action-section-title">Pipeline stages</h4>
                            <div className="crm-call-action-card">
                                <div className="crm-filter-chips-grid">
                                    <button
                                        type="button"
                                        className={`crm-filter-chip ${(filterInputs.stages || []).length === 0 ? 'active' : ''}`}
                                        onClick={() => patch({ stages: [] })}
                                    >
                                        All
                                    </button>
                                    {stages.map((s) => (
                                        <button
                                            type="button"
                                            key={s.code}
                                            className={`crm-filter-chip ${(filterInputs.stages || []).includes(s.code) ? 'active' : ''}`}
                                            onClick={() => toggleStage(s.code)}
                                        >
                                            {s.name}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </section>
                    )}
                </div>
                </div>

                <footer className="drawer-footer crm-filter-drawer-footer">
                    <button type="button" className="btn-drawer-secondary" onClick={onReset}>
                        Reset all
                    </button>
                    <button type="button" className="btn-drawer-primary" onClick={onApply}>
                        Apply filters
                    </button>
                </footer>
            </div>
        </>,
        document.body
    );
}

