import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
    Users,
    Filter,
    CheckCircle2,
    AlertCircle,
    Loader2,
    UserPlus,
    Check,
    X,
    ChevronDown,
    Activity,
    ArrowRight,
} from 'lucide-react';
import SearchableDropdown from '../crm_dashboard/crm_history/SearchableDropdown';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfigOnly, optionsFromPairs } from '../common/selectOptionUtils';
import {
    fetchCustomerServiceBulkAssignCandidates,
    executeCustomerServiceBulkAssign,
    buildCustomerServiceBulkAssignParams,
    unwrapCustomerServiceBulkAssignResponse,
} from '../../utils/customerServiceApi';
import { fetchStaffServiceConfig } from '../../utils/staffServiceConfigApi';
import {
    fetchActiveRmEmployees,
    fetchActiveOpEmployees,
} from '../../utils/activeEmployees';
import '../crm_dashboard/crm_history/BulkAssign.css';
import '../settings/SettingsTab.css';

const NULL_FIELD_OPTIONS = [
    'RM_ID',
    'OP_ID',
    'SERVICE_CODE',
    'SERVICE_STATUS',
    'PROVIDED_AT',
    'CUSTOMER_ID',
];

const SERVICE_STATUS_OPTIONS = ['PENDING', 'PROVIDED'];

const AVAILABLE_FILTER_OPTIONS = [
    { key: 'service_codes', label: 'Service Codes' },
    { key: 'service_statuses', label: 'Service Status' },
    { key: 'customer_ids', label: 'Customer ID' },
    { key: 'rm_ids', label: 'RM' },
    { key: 'op_ids', label: 'OP' },
    { key: 'null_fields', label: 'Null Fields' },
    { key: 'not_null_fields', label: 'Not Null Fields' },
    { key: 'is_active', label: 'Is Active' },
];

const DEFAULT_FILTERS = {
    service_codes: [],
    service_statuses: [],
    customer_ids: [],
    rm_ids: [],
    op_ids: [],
    null_fields: [],
    not_null_fields: [],
    is_active: null,
    match_mode: 'AND',
    filter_mode: 'IN',
    limit: 500,
    offset: 0,
};

const FILTER_DEFAULTS_BY_KEY = {
    service_codes: [],
    service_statuses: [],
    customer_ids: [],
    rm_ids: [],
    op_ids: [],
    null_fields: [],
    not_null_fields: [],
    is_active: null,
};

function empIdDropdownOptions(employees) {
    return (employees || [])
        .filter((emp) => emp?.emp_id)
        .map((emp) => ({
            value: String(emp.emp_id),
            label: emp.username || `Employee ${emp.emp_id}`,
        }));
}

const CustomerServiceBulkAssign = ({ setToastMessage }) => {
    const [loading, setLoading] = useState(false);
    const [candidates, setCandidates] = useState([]);
    const [selectedServiceIds, setSelectedServiceIds] = useState([]);
    const [rmEmployees, setRmEmployees] = useState([]);
    const [opEmployees, setOpEmployees] = useState([]);
    const [assigneesLoading, setAssigneesLoading] = useState(false);
    const [selectedRmIds, setSelectedRmIds] = useState([]);
    const [selectedOpIds, setSelectedOpIds] = useState([]);
    const [assignLoading, setAssignLoading] = useState(false);
    const [status, setStatus] = useState(null);
    const [candidateTotal, setCandidateTotal] = useState(0);
    const [activeFilterKeys, setActiveFilterKeys] = useState([
        'service_statuses',
        'null_fields',
        'rm_ids',
    ]);
    const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
    const [currentStep, setCurrentStep] = useState(1);
    const [previewCount, setPreviewCount] = useState(0);
    const [isCountLoading, setIsCountLoading] = useState(false);
    const filterDropdownRef = useRef(null);
    const [serviceCodeOptions, setServiceCodeOptions] = useState([]);
    const [filters, setFilters] = useState({ ...DEFAULT_FILTERS });
    const [assignmentRoles, setAssignmentRoles] = useState({ RM: true, OP: false });
    const [perEmployeeLimits, setPerEmployeeLimits] = useState({ RM: '', OP: '' });

    const rmEmployeeOptions = useMemo(() => empIdDropdownOptions(rmEmployees), [rmEmployees]);
    const opEmployeeOptions = useMemo(() => empIdDropdownOptions(opEmployees), [opEmployees]);

    const parsePerEmployeeLimit = (value) => {
        if (value === '' || value == null) return null;
        const parsed = parseInt(String(value).trim(), 10);
        return Number.isFinite(parsed) && parsed >= 1 ? parsed : null;
    };

    const setRolePerEmployeeLimit = (role, value) => {
        setPerEmployeeLimits((prev) => ({ ...prev, [role]: value }));
    };

    const toggleAssignmentRole = (role) => {
        setAssignmentRoles((prev) => {
            const next = { ...prev, [role]: !prev[role] };
            if (!next.RM && !next.OP) return prev;
            return next;
        });
    };

    const canExecuteAssign = useMemo(() => {
        if (selectedServiceIds.length === 0) return false;
        if (assignmentRoles.RM && selectedRmIds.length === 0) return false;
        if (assignmentRoles.OP && selectedOpIds.length === 0) return false;
        return assignmentRoles.RM || assignmentRoles.OP;
    }, [assignmentRoles, selectedServiceIds.length, selectedRmIds.length, selectedOpIds.length]);

    const fetchActiveRmOpLists = useCallback(async () => {
        setAssigneesLoading(true);
        try {
            const [rms, ops] = await Promise.all([
                fetchActiveRmEmployees(),
                fetchActiveOpEmployees(),
            ]);
            setRmEmployees(rms);
            setOpEmployees(ops);
        } catch (err) {
            setStatus({
                type: 'error',
                message: err.response?.data?.detail || 'Failed to load RM/OP lists.',
            });
        } finally {
            setAssigneesLoading(false);
        }
    }, []);

    const fetchMetadata = useCallback(async () => {
        try {
            const services = await fetchStaffServiceConfig();
            const options = (services || [])
                .filter((svc) => svc?.service_code)
                .map((svc) => ({
                    value: svc.service_code,
                    label: svc.service_name || svc.service_code,
                }));
            setServiceCodeOptions(options);
        } catch (err) {
            console.error('CustomerServiceBulkAssign: service config fetch failed:', err);
        }
    }, []);

    useEffect(() => {
        fetchMetadata();
        fetchActiveRmOpLists();
    }, [fetchMetadata, fetchActiveRmOpLists]);

    useEffect(() => {
        if (currentStep === 2) fetchActiveRmOpLists();
    }, [currentStep, fetchActiveRmOpLists]);

    useEffect(() => {
        if (currentStep !== 1) return;

        const timer = setTimeout(async () => {
            setIsCountLoading(true);
            try {
                const params = buildCustomerServiceBulkAssignParams(filters, {
                    preview: true,
                    activeKeys: activeFilterKeys,
                });
                const response = await fetchCustomerServiceBulkAssignCandidates(params);
                const { total } = unwrapCustomerServiceBulkAssignResponse(response);
                setPreviewCount(total);
            } catch (err) {
                console.error('CustomerServiceBulkAssign: count preview failed:', err);
                setPreviewCount(0);
            } finally {
                setIsCountLoading(false);
            }
        }, 500);

        return () => clearTimeout(timer);
    }, [filters, currentStep, activeFilterKeys]);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (filterDropdownRef.current && !filterDropdownRef.current.contains(event.target)) {
                setIsFilterDropdownOpen(false);
            }
        };
        if (isFilterDropdownOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isFilterDropdownOpen]);

    const fetchCandidates = async () => {
        setLoading(true);
        setStatus(null);
        try {
            const params = buildCustomerServiceBulkAssignParams(filters, {
                activeKeys: activeFilterKeys,
            });
            const response = await fetchCustomerServiceBulkAssignCandidates(params);
            const { items, total } = unwrapCustomerServiceBulkAssignResponse(response);
            setCandidates(items);
            setCandidateTotal(total);
            setSelectedServiceIds(items.map((row) => row.id).filter(Boolean));

            if (items.length === 0) {
                setStatus({ type: 'info', message: 'No customer services found matching these filters.' });
            } else {
                setStatus({
                    type: 'success',
                    message: `Successfully loaded ${items.length} services for assignment.`,
                });
                setCurrentStep(2);
            }
        } catch (err) {
            console.error('Customer service bulk assign fetch failed:', err);
            const detail = err?.response?.data?.detail;
            setStatus({
                type: 'error',
                message: typeof detail === 'string' ? detail : 'Failed to fetch candidates.',
            });
        } finally {
            setLoading(false);
        }
    };

    const handleExecuteAssign = async () => {
        setAssignLoading(true);
        try {
            const assignments = [];
            if (assignmentRoles.RM) {
                assignments.push({
                    role: 'RM',
                    empIds: selectedRmIds.map(Number).filter((n) => Number.isFinite(n) && n > 0),
                    perEmployeeLimit: parsePerEmployeeLimit(perEmployeeLimits.RM),
                });
            }
            if (assignmentRoles.OP) {
                assignments.push({
                    role: 'OP',
                    empIds: selectedOpIds.map(Number).filter((n) => Number.isFinite(n) && n > 0),
                    perEmployeeLimit: parsePerEmployeeLimit(perEmployeeLimits.OP),
                });
            }

            let totalAssigned = 0;
            const roleSummaries = [];

            for (const { role, empIds, perEmployeeLimit } of assignments) {
                const response = await executeCustomerServiceBulkAssign({
                    customer_service_ids: selectedServiceIds,
                    selected_employee_ids: empIds,
                    assignment_role: role,
                    per_employee_limit: perEmployeeLimit,
                });
                const assigned = response?.total_assigned ?? 0;
                totalAssigned += assigned;
                roleSummaries.push(`${assigned} as ${role}`);
            }

            const summary =
                assignments.length > 1
                    ? `Successfully assigned services (${roleSummaries.join(', ')}).`
                    : `Successfully assigned ${totalAssigned} services.`;

            setStatus({ type: 'success', message: summary });
            setToastMessage?.({ type: 'success', text: summary });
            setCandidates([]);
            setSelectedServiceIds([]);
            setSelectedRmIds([]);
            setSelectedOpIds([]);
            setPerEmployeeLimits({ RM: '', OP: '' });
            setCurrentStep(1);
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setStatus({
                type: 'error',
                message: typeof detail === 'string' ? detail : 'Assignment failed.',
            });
        } finally {
            setAssignLoading(false);
        }
    };

    const handleFilterChange = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }));

    const toggleFilterKey = (key) => {
        setActiveFilterKeys((prev) => {
            const isRemoving = prev.includes(key);
            if (isRemoving && Object.prototype.hasOwnProperty.call(FILTER_DEFAULTS_BY_KEY, key)) {
                handleFilterChange(key, FILTER_DEFAULTS_BY_KEY[key]);
            }
            return isRemoving ? prev.filter((k) => k !== key) : [...prev, key];
        });
    };

    return (
        <div className="bulk-assign-container expanded cs-bulk-assign-page">
            <div className="bulk-assign-header">
                <div className="header-title">
                    <Users size={20} className="icon" />
                    <span>Advanced Bulk Assignment</span>
                </div>
            </div>

            <div className="bulk-assign-body">
                {currentStep === 1 && (
                    <>
                        <div className="swagger-layout" style={{ gridTemplateColumns: '1fr' }}>
                            <div className="filters-list-col" style={{ gridColumn: 'span 2', maxWidth: 'none' }}>
                                <div className="logic-controls-row">
                                    <div className="logic-inputs-group" style={{ display: 'flex', gap: '16px', alignItems: 'flex-end' }}>
                                        <div className="logic-box-container">
                                            <span className="logic-title">Match Mode</span>
                                            <FormCustomSelect
                                                className="logic-dropdown-box"
                                                name="match_mode"
                                                value={filters.match_mode}
                                                onChange={(e) => handleFilterChange('match_mode', e.target.value)}
                                                options={optionsFromConfigOnly([
                                                    { value: 'AND', label: 'AND' },
                                                    { value: 'OR', label: 'OR' },
                                                ])}
                                                placeholder="Match mode"
                                                ariaLabel="Match mode"
                                                portal={false}
                                            />
                                        </div>

                                        <div className="logic-box-container">
                                            <span className="logic-title">Filter Mode</span>
                                            <FormCustomSelect
                                                className="logic-dropdown-box"
                                                name="filter_mode"
                                                value={filters.filter_mode}
                                                onChange={(e) => handleFilterChange('filter_mode', e.target.value)}
                                                options={optionsFromConfigOnly([
                                                    { value: 'IN', label: 'IN' },
                                                    { value: 'NOT_IN', label: 'NOT IN' },
                                                ])}
                                                placeholder="Filter mode"
                                                ariaLabel="Filter mode"
                                                portal={false}
                                            />
                                        </div>

                                        <div className="logic-box-container">
                                            <span className="logic-title">Fetch Limit</span>
                                            <input
                                                type="number"
                                                className="logic-dropdown-box"
                                                style={{ width: '80px', textAlign: 'center' }}
                                                value={filters.limit}
                                                onChange={(e) =>
                                                    handleFilterChange('limit', parseInt(e.target.value, 10) || 500)
                                                }
                                            />
                                        </div>

                                        <div
                                            className="logic-box-container dropdown-wrapper"
                                            style={{ position: 'relative' }}
                                            ref={filterDropdownRef}
                                        >
                                            <button
                                                type="button"
                                                className="logic-dropdown-box filter-trigger-btn"
                                                onClick={() => setIsFilterDropdownOpen(!isFilterDropdownOpen)}
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '8px',
                                                    cursor: 'pointer',
                                                    background: 'rgba(var(--accent-rgb), 0.1)',
                                                    borderColor: 'rgba(var(--accent-rgb), 0.3)',
                                                    color: 'var(--accent)',
                                                }}
                                            >
                                                <Filter size={14} />
                                                <span>Filters</span>
                                                <ChevronDown
                                                    size={14}
                                                    style={{
                                                        transform: isFilterDropdownOpen ? 'rotate(180deg)' : 'none',
                                                        transition: 'transform 0.2s',
                                                    }}
                                                />
                                            </button>

                                            {isFilterDropdownOpen && (
                                                <div className="filter-selection-dropdown">
                                                    {AVAILABLE_FILTER_OPTIONS.map((opt) => (
                                                        <div
                                                            key={opt.key}
                                                            className={`filter-opt-item ${activeFilterKeys.includes(opt.key) ? 'selected' : ''}`}
                                                            onClick={() => toggleFilterKey(opt.key)}
                                                        >
                                                            <span>{opt.label}</span>
                                                            {activeFilterKeys.includes(opt.key) && <Check size={14} />}
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="filter-divider" />

                                <div className="active-filters-workspace">
                                    {activeFilterKeys.includes('service_codes') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <SearchableDropdown
                                                label="Service Codes"
                                                options={serviceCodeOptions}
                                                selected={filters.service_codes}
                                                onChange={(val) => handleFilterChange('service_codes', val)}
                                                placeholder="Add service code"
                                            />
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('service_codes')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('service_statuses') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <SearchableDropdown
                                                label="Service Status"
                                                options={SERVICE_STATUS_OPTIONS.map((s) => ({ value: s, label: s }))}
                                                selected={filters.service_statuses}
                                                onChange={(val) => handleFilterChange('service_statuses', val)}
                                                placeholder="Add status"
                                            />
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('service_statuses')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('customer_ids') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <div className="searchable-dropdown-container">
                                                <label className="dropdown-label">Customer ID</label>
                                                <input
                                                    type="text"
                                                    className="dropdown-box"
                                                    placeholder="Comma-separated customer IDs"
                                                    value={filters.customer_ids.join(', ')}
                                                    onChange={(e) =>
                                                        handleFilterChange(
                                                            'customer_ids',
                                                            e.target.value
                                                                .split(',')
                                                                .map((part) => part.trim())
                                                                .filter(Boolean),
                                                        )
                                                    }
                                                />
                                            </div>
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('customer_ids')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('rm_ids') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <SearchableDropdown
                                                label="RM"
                                                options={rmEmployeeOptions}
                                                selected={filters.rm_ids}
                                                onChange={(val) => handleFilterChange('rm_ids', val)}
                                                placeholder="Select RM"
                                            />
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('rm_ids')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('op_ids') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <SearchableDropdown
                                                label="OP"
                                                options={opEmployeeOptions}
                                                selected={filters.op_ids}
                                                onChange={(val) => handleFilterChange('op_ids', val)}
                                                placeholder="Select OP"
                                            />
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('op_ids')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('null_fields') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <SearchableDropdown
                                                label="Null Fields"
                                                options={NULL_FIELD_OPTIONS.map((f) => ({
                                                    value: f,
                                                    label: f.replace(/_/g, ' '),
                                                }))}
                                                selected={filters.null_fields}
                                                onChange={(val) => handleFilterChange('null_fields', val)}
                                                placeholder="Add null field"
                                            />
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('null_fields')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('not_null_fields') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <SearchableDropdown
                                                label="Not Null Fields"
                                                options={NULL_FIELD_OPTIONS.map((f) => ({
                                                    value: f,
                                                    label: f.replace(/_/g, ' '),
                                                }))}
                                                selected={filters.not_null_fields}
                                                onChange={(val) => handleFilterChange('not_null_fields', val)}
                                                placeholder="Add not-null field"
                                            />
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('not_null_fields')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}

                                    {activeFilterKeys.includes('is_active') && (
                                        <div className="dynamic-filter-row" style={{ position: 'relative' }}>
                                            <div className="searchable-dropdown-container">
                                                <label className="dropdown-label">Is Active</label>
                                                <FormCustomSelect
                                                    className="dropdown-box"
                                                    name="is_active"
                                                    value={filters.is_active === null ? '' : String(filters.is_active)}
                                                    onChange={(e) =>
                                                        handleFilterChange(
                                                            'is_active',
                                                            e.target.value === '' ? null : e.target.value === 'true',
                                                        )
                                                    }
                                                    options={optionsFromPairs([
                                                        { value: '', label: '--' },
                                                        { value: 'true', label: 'True' },
                                                        { value: 'false', label: 'False' },
                                                    ])}
                                                    placeholder="--"
                                                    ariaLabel="Is active"
                                                    portal={false}
                                                />
                                            </div>
                                            <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('is_active')}>
                                                <X size={16} />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '32px' }}>
                            <div className="matching-leads-preview">
                                {isCountLoading ? (
                                    <>
                                        <Loader2 className="spin" size={14} />
                                        <span>Updating count...</span>
                                    </>
                                ) : (
                                    <>
                                        <Filter size={14} />
                                        <span>
                                            <strong>{previewCount}</strong> services matching current filters
                                        </span>
                                    </>
                                )}
                            </div>
                            <button
                                type="button"
                                className="btn-fetch"
                                onClick={fetchCandidates}
                                disabled={loading}
                                style={{
                                    width: '160px',
                                    height: '48px',
                                    borderRadius: '12px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                }}
                            >
                                {loading ? <Loader2 className="spin" size={18} /> : <ArrowRight size={18} />}
                                <span>Next</span>
                            </button>
                        </div>
                    </>
                )}

                {status && (
                    <div className={`status-alert ${status.type}`}>
                        {status.type === 'success' ? (
                            <CheckCircle2 size={18} />
                        ) : status.type === 'error' ? (
                            <AlertCircle size={18} />
                        ) : (
                            <Activity size={18} />
                        )}
                        <span>{status.message}</span>
                    </div>
                )}

                {currentStep === 2 && candidates.length > 0 && (
                    <div className="assignment-workbench">
                        <div className="workbench-header-row">
                            <button
                                type="button"
                                onClick={() => setCurrentStep(1)}
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    color: 'var(--text-primary)',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    fontSize: '14px',
                                }}
                            >
                                <X size={16} />
                                <span>Back to Filters</span>
                            </button>
                        </div>

                        <div className="workbench-single-col">
                            <div className="count-display-card">
                                <div className="count-value">{candidateTotal}</div>
                                <div className="count-label">Services matching your filters</div>
                                <div className="count-subtext">Ready to be distributed among selected employees</div>
                            </div>

                            <div className="assignment-config-section">
                                <div className="config-header">
                                    <UserPlus size={18} />
                                    <h4>Assignment Configuration</h4>
                                </div>

                                <div className="config-grid">
                                    <div className="config-item">
                                        <label>1. Assign Services As:</label>
                                        <div className="toggle-group mini toggle-group--multi">
                                            <button
                                                type="button"
                                                className={assignmentRoles.RM ? 'active' : ''}
                                                onClick={() => toggleAssignmentRole('RM')}
                                            >
                                                RM
                                            </button>
                                            <button
                                                type="button"
                                                className={assignmentRoles.OP ? 'active' : ''}
                                                onClick={() => toggleAssignmentRole('OP')}
                                            >
                                                OP
                                            </button>
                                        </div>
                                    </div>

                                    {assignmentRoles.RM && (
                                        <div className="config-item config-item--role-block">
                                            <label>2. Select RMs:</label>
                                            <SearchableDropdown
                                                placeholder={
                                                    assigneesLoading
                                                        ? 'Loading RMs...'
                                                        : rmEmployeeOptions.length
                                                          ? 'Select RMs...'
                                                          : 'No active RMs found'
                                                }
                                                options={rmEmployeeOptions}
                                                selected={selectedRmIds}
                                                onChange={setSelectedRmIds}
                                            />
                                            <label className="limit-sublabel">Max services per RM (optional)</label>
                                            <input
                                                type="number"
                                                min={1}
                                                className="crm-input-field role-limit-input"
                                                placeholder="No limit (round-robin)"
                                                value={perEmployeeLimits.RM}
                                                onChange={(e) => setRolePerEmployeeLimit('RM', e.target.value)}
                                            />
                                        </div>
                                    )}

                                    {assignmentRoles.OP && (
                                        <div className="config-item config-item--role-block">
                                            <label>{assignmentRoles.RM ? '3. Select OPs:' : '2. Select OPs:'}</label>
                                            <SearchableDropdown
                                                placeholder={
                                                    assigneesLoading
                                                        ? 'Loading OPs...'
                                                        : opEmployeeOptions.length
                                                          ? 'Select OPs...'
                                                          : 'No active OPs found'
                                                }
                                                options={opEmployeeOptions}
                                                selected={selectedOpIds}
                                                onChange={setSelectedOpIds}
                                            />
                                            <label className="limit-sublabel">Max services per OP (optional)</label>
                                            <input
                                                type="number"
                                                min={1}
                                                className="crm-input-field role-limit-input"
                                                placeholder="No limit (round-robin)"
                                                value={perEmployeeLimits.OP}
                                                onChange={(e) => setRolePerEmployeeLimit('OP', e.target.value)}
                                            />
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>

                        <div className="execution-row">
                            <div className="execution-summary">
                                Distributing <strong>{selectedServiceIds.length}</strong> services
                                {assignmentRoles.RM && (
                                    <> to <strong>{selectedRmIds.length}</strong> RM{selectedRmIds.length === 1 ? '' : 's'}</>
                                )}
                                {assignmentRoles.OP && (
                                    <> to <strong>{selectedOpIds.length}</strong> OP{selectedOpIds.length === 1 ? '' : 's'}</>
                                )}
                            </div>
                            <button
                                type="button"
                                className="btn-execute-assign"
                                onClick={handleExecuteAssign}
                                disabled={assignLoading || !canExecuteAssign}
                            >
                                {assignLoading ? (
                                    <Loader2 className="spin" size={18} />
                                ) : (
                                    <>
                                        <CheckCircle2 size={18} />
                                        <span>Confirm & Execute Distribution</span>
                                    </>
                                )}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default CustomerServiceBulkAssign;
