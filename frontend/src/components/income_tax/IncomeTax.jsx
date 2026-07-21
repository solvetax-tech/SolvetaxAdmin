import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Plus, Filter, AlertCircle, FileText, XCircle, RotateCcw, CreditCard, Eye, Pencil, CalendarClock
} from 'lucide-react';
import {
    fetchIncomeTaxes,
    fetchIncomeTaxById,
    extractIncomeTaxListMeta,
    unwrapIncomeTaxRecord,
    buildIncomeTaxCrmLeadActionSearchParams,
    getCrmLeadByIncomeTaxId,
    isItrCrmStageForSchedulePayment,
} from '../../utils/incomeTaxApi';
import { fetchIncomeTaxConfigs } from '../../utils/incomeTaxConfigs';
import { formatDateIST, dateLocalToIstIso, formatEnumLabel } from '../../utils/formatDateTimeIST';
import IncomeSourcePills from './IncomeSourcePills';
import FinancialYearPills from './FinancialYearPills';
import RecordYearBadge from './RecordYearBadge';
import Button from '../ui/Button';
import '../gst_filings/gst_filings.css'; // Reusing the GST aesthetics
import './income_tax.css';
import Pagination from '../common/Pagination';
import IncomeTaxFormModal from './IncomeTaxFormModal';
import IncomeTaxDetails from './IncomeTaxDetails';
import { buildFinancialYearPresetOptions, INCOME_SOURCE_OPTIONS } from '../../utils/incomeTaxArrays';
import FormCustomSelect from '../common/FormCustomSelect';
import FilterDateInput from '../common/FilterDateInput';
import { optionsFromConfig, optionsFromPairs } from '../common/selectOptionUtils';
import { buildRmOpSelectOptions } from '../../utils/activeEmployees';

const FILTER_FY_OPTIONS = buildFinancialYearPresetOptions({ yearsBack: 8 });

const RECORD_YEAR_OPTIONS = (() => {
    const current = new Date().getFullYear();
    return Array.from({ length: 8 }, (_, i) => current - i);
})();

const ITRTableSkeleton = ({ rows = 12 }) => (
    <>
        {[...Array(rows)].map((_, rowIndex) => (
            <div key={`itr-skeleton-${rowIndex}`} className="itr-ledger-row itr-skeleton-row">
                {[...Array(12)].map((__, columnIndex) => (
                    <div 
                        key={`itr-skeleton-cell-${columnIndex}`} 
                        className={`itr-ledger-cell${columnIndex === 0 ? ' itr-ledger-sticky-id' : ''}${columnIndex === 11 ? ' itr-ledger-sticky-actions' : ''}`}
                    >
                        <div className="itr-skeleton-bar" />
                    </div>
                ))}
            </div>
        ))}
    </>
);

export const IncomeTax = ({ profileData }) => {
    const navigate = useNavigate();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    
    // Pagination
    const [hasMore, setHasMore] = useState(false);
    const [currentPage, setCurrentPage] = useState(1);
    const rowsPerPage = 20;

    // Filters
    const [showFilterDrawer, setShowFilterDrawer] = useState(false);
    const emptyFilters = {
        id: '',
        mobile: '',
        pan_number: '',
        year: '',
        financial_year: [],
        filed_status: '',
        priority: '',
        language: '',
        state: '',
        source_of_income: [],
        rm_id: '',
        op_id: '',
        active_filter: 'all',
        created_from: '',
        created_to: '',
    };

    /** Committed filters sent to the API (Apply / chip remove only — not on every keystroke). */
    const [appliedFilters, setAppliedFilters] = useState({ ...emptyFilters });
    /** Draft values while the filter drawer is open (GST registration pattern). */
    const [filterInputs, setFilterInputs] = useState({ ...emptyFilters });

    const hasLoadedOnceRef = useRef(false);

    const [showCreateModal, setShowCreateModal] = useState(false);
    /** Right-hand edit drawer (same shell as Filters) */
    const [showEditDrawer, setShowEditDrawer] = useState(false);
    const [editingRecord, setEditingRecord] = useState(null);

    const [duplicateEditNotice, setDuplicateEditNotice] = useState(null);

    const closeIncomeTaxForm = useCallback(() => {
        setShowCreateModal(false);
        setShowEditDrawer(false);
        setEditingRecord(null);
        setDuplicateEditNotice(null);
    }, []);
    const [viewingRecordId, setViewingRecordId] = useState(null);

    /** Row click / VIEW: details only on the right (not edit) */
    const openDetailsDrawer = useCallback(
        (item) => {
            closeIncomeTaxForm();
            setViewingRecordId(item.id);
        },
        [closeIncomeTaxForm]
    );

    const [configs, setConfigs] = useState({ states: [], activeRMs: [], activeOps: [], activeEmps: [], languages: [] });
    const [configsLoading, setConfigsLoading] = useState(false);
    const configsLoadedRef = useRef(false);

    const getRMUsername = (id, rmNameFromRow) => {
        if (rmNameFromRow) return rmNameFromRow;
        if (!id) return '-';
        if (typeof id === 'string' && Number.isNaN(parseInt(id, 10))) return id;
        if (configs.activeRMs?.includes(id) || configs.activeRMs?.includes(String(id))) return String(id);
        const pid = parseInt(id, 10);
        const match = configs.activeEmps?.find(e => parseInt(e.emp_id, 10) === pid);
        return match ? (match.username || match.first_name) : String(id);
    };

    const getOPUsername = (id, opNameFromRow) => {
        if (opNameFromRow) return opNameFromRow;
        if (!id) return '-';
        if (typeof id === 'string' && Number.isNaN(parseInt(id, 10))) return id;
        if (configs.activeOps?.includes(id) || configs.activeOps?.includes(String(id))) return String(id);
        const pid = parseInt(id, 10);
        const match = configs.activeEmps?.find(e => parseInt(e.emp_id, 10) === pid);
        return match ? (match.username || match.first_name) : String(id);
    };

    /** Load dropdown configs only when opening filter / create / edit (not on list mount). */
    const ensureConfigs = useCallback(async () => {
        if (configsLoadedRef.current) return configs;
        setConfigsLoading(true);
        try {
            const next = await fetchIncomeTaxConfigs();
            setConfigs(next);
            configsLoadedRef.current = true;
            return next;
        } finally {
            setConfigsLoading(false);
        }
    }, [configs]);

    const openEditDrawer = useCallback((item) => {
        setViewingRecordId(null);
        setEditingRecord(item);
        setShowCreateModal(false);
        setShowEditDrawer(true);
        ensureConfigs();
    }, [ensureConfigs]);

    // Schedule Payment → jump to the linked CRM lead and (when its stage allows)
    // open the SCHEDULED_PAYMENT action drawer, so the RM schedules it in the CRM.
    const handleRowSchedulePayment = useCallback(async (e, item) => {
        e.stopPropagation();
        let openSchedulePaymentDrawer = false;
        try {
            const lead = await getCrmLeadByIncomeTaxId(item.id);
            openSchedulePaymentDrawer = isItrCrmStageForSchedulePayment(lead?.stage);
        } catch (err) {
            console.warn('Could not load CRM lead for schedule payment:', err);
        }
        navigate(`/crm-dashboard?${buildIncomeTaxCrmLeadActionSearchParams(item.id, openSchedulePaymentDrawer).toString()}`);
    }, [navigate]);

    const openEditById = useCallback(async (incomeTaxId) => {
        setViewingRecordId(null);
        setShowCreateModal(false);
        try {
            const res = await fetchIncomeTaxById(incomeTaxId);
            const record = unwrapIncomeTaxRecord(res.data);
            if (!record?.id) {
                setError('Could not load the existing record. Please refresh and try again.');
                return;
            }
            setEditingRecord(record);
            setShowEditDrawer(true);
            ensureConfigs();
        } catch (err) {
            console.error('Failed to load income tax record for edit:', err);
            setError('Could not open the existing record for editing.');
        }
    }, [ensureConfigs]);

    const handleDuplicateOnCreate = useCallback((notice) => {
        setDuplicateEditNotice(notice);
    }, []);

    const openExistingFromDuplicate = useCallback(() => {
        if (!duplicateEditNotice?.existingIncomeTaxId) return;
        openEditById(duplicateEditNotice.existingIncomeTaxId);
    }, [duplicateEditNotice, openEditById]);

    const fetchIncomeTaxRecords = useCallback(async () => {
        const showBlockingLoader = !hasLoadedOnceRef.current;
        if (showBlockingLoader) setLoading(true);
        setError(null);
        try {
            const offset = (currentPage - 1) * rowsPerPage;
            const params = { limit: rowsPerPage, offset };

            Object.entries(appliedFilters).forEach(([key, value]) => {
                if (Array.isArray(value)) {
                    if (value.length === 0) return;
                    params[key] = value;
                    return;
                }
                if (value === '' || value === null || value === undefined) return;
                if (key === 'active_filter') {
                    if (value === 'active') params.is_active = true;
                    else if (value === 'inactive') params.is_active = false;
                    else if (value === 'all') params.include_inactive = true;
                    return;
                }
                if (key === 'created_from' || key === 'created_to') {
                    const iso = dateLocalToIstIso(value, { endOfDay: key === 'created_to' });
                    if (iso) params[key] = iso;
                    return;
                }
                if (key === 'id') {
                    const idNum = parseInt(value, 10);
                    if (!Number.isNaN(idNum)) params.id = idNum;
                    return;
                }
                if (key === 'year') {
                    const y = parseInt(value, 10);
                    if (!Number.isNaN(y)) params.year = y;
                    return;
                }
                if (key === 'mobile') {
                    const digits = String(value).replace(/\D/g, '').slice(0, 10);
                    if (digits) params.mobile = digits;
                    return;
                }
                if (key === 'rm_id' || key === 'op_id') {
                    const n = parseInt(value, 10);
                    if (!Number.isNaN(n)) params[key] = n;
                    return;
                }
                params[key] = value;
            });

            const res = await fetchIncomeTaxes(params);
            const { items, total, limit, offset: responseOffset } = extractIncomeTaxListMeta(res.data);

            setData(items);

            if (typeof total === 'number') {
                const pageLimit = limit ?? rowsPerPage;
                const pageOffset = responseOffset ?? offset;
                setHasMore(pageOffset + items.length < total);
            } else {
                setHasMore(items.length >= rowsPerPage);
            }
        } catch (err) {
            console.error('Failed to fetch income tax records:', err);
            const detail = err?.message
                || (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : null)
                || err?.response?.data?.error?.message;
            setError(
                detail && detail !== 'Operation failed'
                    ? detail
                    : 'Failed to load Income Tax records. Please try again.'
            );
        } finally {
            setLoading(false);
            hasLoadedOnceRef.current = true;
        }
    }, [appliedFilters, currentPage]);

    const onFormSuccess = useCallback(() => {
        closeIncomeTaxForm();
        if (currentPage === 1) {
            fetchIncomeTaxRecords();
        } else {
            setCurrentPage(1);
        }
    }, [closeIncomeTaxForm, currentPage, fetchIncomeTaxRecords]);

    useEffect(() => {
        fetchIncomeTaxRecords();
    }, [fetchIncomeTaxRecords]);

    const getStatusPill = (status) => {
        if (status === 'FILED') return <span className="status-pill-v4 status-filed">Filed</span>;
        if (status === 'NOT_FILED') return <span className="status-pill-v4 status-pending">Not Filed</span>;
        return <span className="status-pill-v4 status-default">{status || 'UNKNOWN'}</span>;
    };

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const toggleFilterFinancialYear = (fy) => {
        setFilterInputs((prev) => {
            const set = new Set(prev.financial_year);
            if (set.has(fy)) set.delete(fy);
            else set.add(fy);
            return { ...prev, financial_year: [...set] };
        });
    };

    const toggleFilterSourceOfIncome = (code) => {
        setFilterInputs((prev) => {
            const set = new Set(prev.source_of_income);
            if (set.has(code)) set.delete(code);
            else set.add(code);
            return { ...prev, source_of_income: [...set] };
        });
    };

    const openFilterDrawer = () => {
        setFilterInputs({ ...appliedFilters });
        setShowFilterDrawer(true);
        ensureConfigs();
    };

    const applyFilters = () => {
        setAppliedFilters({ ...filterInputs });
        setShowFilterDrawer(false);
        setCurrentPage(1);
    };

    const clearFilters = () => {
        setFilterInputs({ ...emptyFilters });
        setAppliedFilters({ ...emptyFilters });
        setCurrentPage(1);
    };

    const removeFilter = (key, subValue = null) => {
        setAppliedFilters((prev) => {
            if (subValue != null && Array.isArray(prev[key])) {
                return { ...prev, [key]: prev[key].filter((v) => v !== subValue) };
            }
            const cleared = Array.isArray(prev[key]) ? [] : '';
            return { ...prev, [key]: cleared };
        });
        setCurrentPage(1);
    };

    const renderFilterChips = () => {
        const labels = {
            id: 'ID',
            mobile: 'Mobile',
            pan_number: 'PAN',
            year: 'Record year',
            financial_year: 'FY',
            filed_status: 'Status',
            priority: 'Priority',
            language: 'Language',
            state: 'State',
            source_of_income: 'Source',
            rm_id: 'RM',
            op_id: 'OP',
            active_filter: 'Records',
            created_from: 'Created from',
            created_to: 'Created to',
        };

        const chipEntries = [];
        Object.entries(appliedFilters).forEach(([key, value]) => {
            if (key === 'active_filter' && value === 'all') return;
            if (Array.isArray(value)) {
                value.forEach((item) => chipEntries.push({ key, value: item, subValue: item }));
                return;
            }
            if (value !== '' && value != null) {
                chipEntries.push({ key, value, subValue: null });
            }
        });

        return chipEntries.map(({ key, value, subValue }) => {
                let displayValue = value;
                if (key === 'rm_id') displayValue = getRMUsername(value);
                if (key === 'op_id') displayValue = getOPUsername(value);
                if (key === 'filed_status') displayValue = value.replace(/_/g, ' ');
                if (key === 'priority') displayValue = formatEnumLabel(value);
                if (key === 'source_of_income') displayValue = formatEnumLabel(value);
                if (key === 'active_filter') {
                    if (value === 'active') displayValue = 'Active only';
                    else if (value === 'inactive') displayValue = 'Inactive only';
                    else displayValue = 'All records';
                }
                if (key === 'language' || key === 'state') {
                    const cfgList = key === 'language' ? configs.languages : configs.states;
                    const match = cfgList?.find((x) => (x.value || x) === value);
                    displayValue = match?.display_name || match?.name || value;
                }
                if (key === 'created_from' || key === 'created_to') {
                    displayValue = /^\d{4}-\d{2}-\d{2}$/.test(String(value))
                        ? formatDateIST(dateLocalToIstIso(value))
                        : formatDateIST(value);
                }

                const chipKey = subValue != null ? `${key}-${subValue}` : key;

                return (
                    <div key={chipKey} className="filter-chip">
                        <span className="filter-chip-label">{labels[key] || key}:</span>
                        <span className="filter-chip-value">{displayValue}</span>
                        <button type="button" className="btn-remove-chip" onClick={() => removeFilter(key, subValue)}>
                            <XCircle size={12} />
                        </button>
                    </div>
                );
            });
    };

    const hasActiveItrFilters = Object.entries(appliedFilters).some(([key, v]) => {
        if (key === 'active_filter' && v === 'all') return false;
        return Array.isArray(v) ? v.length > 0 : v !== '' && v != null;
    });

    return (
        <div className="gst-main-content itr-income-tax-page">
            <div className="itr-income-tax-top-row">
                <div className="dashboard-sub-nav-v4">
                    <button type="button" className="sub-nav-btn-v4 active">
                        <FileText size={14} />
                        <span>ITR Filings</span>
                    </button>
                </div>
                <div className="gst-action-buttons itr-income-tax-top-actions">
                        {hasActiveItrFilters && (
                            <button className="btn-reset-green-v4" onClick={clearFilters}>
                                <RotateCcw size={14} /> Reset Filters
                            </button>
                        )}
                        <button
                            className="btn-filter-trigger"
                            onClick={openFilterDrawer}
                        >
                            <Filter size={13} /> Filters
                        </button>
                        <Button
                            variant="primary"
                            size="sm"
                            icon={<Plus size={13} />}
                            onClick={() => {
                                setEditingRecord(null);
                                setShowEditDrawer(false);
                                setShowCreateModal(true);
                                ensureConfigs();
                            }}
                        >
                            New Record
                        </Button>
                </div>
            </div>

            <>
                    {hasActiveItrFilters && (
                        <div className="gst-action-bar-v2 itr-itrf-filter-chips-row">
                            <div className="active-filters-container" style={{ flex: 1, display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                {renderFilterChips()}
                            </div>
                        </div>
                    )}

                    {/* Unified Filter Drawer */}
                    {showFilterDrawer && (
                        <div className="gst-filters-drawer-overlay" onClick={() => setShowFilterDrawer(false)}>
                            <div className="gst-filters-drawer itr-side-drawer-shell itr-filter-drawer--income-tax" onClick={e => e.stopPropagation()}>
                                <div className="drawer-header">
                                    <h2 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)' }}>Filter ITR Filings</h2>
                                    <button className="btn-drawer-close" onClick={() => setShowFilterDrawer(false)}><XCircle size={20} /></button>
                                </div>
                                
                                <div className="drawer-content">
                                    <div className="filter-section-v4">
                                        <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Client Identifiers</h4>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>Record ID</label>
                                                <input
                                                    name="id"
                                                    type="number"
                                                    min="1"
                                                    value={filterInputs.id}
                                                    onChange={handleFilterChange}
                                                    placeholder="e.g. 42"
                                                />
                                            </div>
                                            <div className="filter-group-v4">
                                                <label>Mobile</label>
                                                <input
                                                    name="mobile"
                                                    value={filterInputs.mobile}
                                                    onChange={handleFilterChange}
                                                    placeholder="10-digit mobile"
                                                    maxLength={10}
                                                />
                                            </div>
                                        </div>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px', marginTop: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>PAN Number</label>
                                                <input name="pan_number" value={filterInputs.pan_number} onChange={handleFilterChange} placeholder="Enter PAN..." />
                                            </div>
                                            <div className="filter-group-v4">
                                                <label>Record year</label>
                                                <FormCustomSelect
                                                    name="year"
                                                    value={filterInputs.year}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromPairs([
                                                        { value: '', label: 'All years' },
                                                        ...RECORD_YEAR_OPTIONS.map((y) => ({ value: String(y), label: String(y) })),
                                                    ])}
                                                    placeholder="All years"
                                                    ariaLabel="Record year"
                                                />
                                            </div>
                                        </div>
                                        <div className="filter-group-v4 itr-filter-multi-field" style={{ marginTop: '12px' }}>
                                            <label>Financial Year</label>
                                            <p className="itr-filter-multi-hint">Select one or more (records matching any selected FY)</p>
                                            <div className="itr-fy-pills itr-filter-fy-pills" role="group" aria-label="Filter by financial year">
                                                {FILTER_FY_OPTIONS.map((fy) => {
                                                    const selected = filterInputs.financial_year.includes(fy);
                                                    return (
                                                        <button
                                                            key={fy}
                                                            type="button"
                                                            className={`itr-fy-pill${selected ? ' is-selected' : ''}`}
                                                            onClick={() => toggleFilterFinancialYear(fy)}
                                                            aria-pressed={selected}
                                                        >
                                                            {fy}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border)', margin: '16px 0' }} />

                                    <div className="filter-section-v4">
                                        <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Filing Attributes</h4>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>Filed Status</label>
                                                <FormCustomSelect
                                                    name="filed_status"
                                                    value={filterInputs.filed_status}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromPairs([
                                                        { value: '', label: 'Any Status' },
                                                        { value: 'FILED', label: 'Filed' },
                                                        { value: 'NOT_FILED', label: 'Not Filed' },
                                                    ])}
                                                    placeholder="Any Status"
                                                    ariaLabel="Filed status"
                                                />
                                            </div>
                                        </div>
                                        <div className="filter-group-v4 itr-filter-multi-field" style={{ marginTop: '12px' }}>
                                            <label>Income Source</label>
                                            <p className="itr-filter-multi-hint">Select one or more (records matching any selected source)</p>
                                            <div className="itr-source-grid itr-filter-source-grid" role="group" aria-label="Filter by income source">
                                                {INCOME_SOURCE_OPTIONS.map(({ value, label }) => {
                                                    const selected = filterInputs.source_of_income.includes(value);
                                                    return (
                                                        <button
                                                            key={value}
                                                            type="button"
                                                            className={`itr-source-tile${selected ? ' is-selected' : ''}`}
                                                            onClick={() => toggleFilterSourceOfIncome(value)}
                                                            aria-pressed={selected}
                                                        >
                                                            <span className="itr-source-tile__label">{label}</span>
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px', marginTop: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>Priority</label>
                                                <FormCustomSelect
                                                    name="priority"
                                                    value={filterInputs.priority}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromPairs([
                                                        { value: '', label: 'Any priority' },
                                                        { value: 'LOW', label: 'Low' },
                                                        { value: 'NORMAL', label: 'Normal' },
                                                        { value: 'HIGH', label: 'High' },
                                                    ])}
                                                    placeholder="Any priority"
                                                    ariaLabel="Priority"
                                                />
                                            </div>
                                            <div className="filter-group-v4">
                                                <label>State</label>
                                                <FormCustomSelect
                                                    name="state"
                                                    value={filterInputs.state}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromConfig(configs.states || [], 'Any state')}
                                                    placeholder="Any state"
                                                    ariaLabel="State"
                                                />
                                            </div>
                                        </div>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: '12px', marginTop: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>Language</label>
                                                <FormCustomSelect
                                                    name="language"
                                                    value={filterInputs.language}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromConfig(configs.languages || [], 'Any language')}
                                                    placeholder="Any language"
                                                    ariaLabel="Language"
                                                />
                                            </div>
                                        </div>
                                    </div>

                                    <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border)', margin: '16px 0' }} />

                                    <div className="filter-section-v4">
                                        <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Record status</h4>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>Active / inactive</label>
                                                <FormCustomSelect
                                                    name="active_filter"
                                                    value={filterInputs.active_filter}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromPairs([
                                                        { value: 'all', label: 'All records (active + inactive)' },
                                                        { value: 'active', label: 'Active only' },
                                                        { value: 'inactive', label: 'Inactive only' },
                                                    ])}
                                                    placeholder="All records"
                                                    ariaLabel="Active filter"
                                                />
                                            </div>
                                        </div>
                                    </div>

                                    <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border)', margin: '16px 0' }} />

                                    <div className="filter-section-v4">
                                        <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Assignment & Ownership</h4>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>Assignee (RM)</label>
                                                <FormCustomSelect
                                                    name="rm_id"
                                                    value={filterInputs.rm_id}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromPairs(buildRmOpSelectOptions(configs.activeRMs), 'Any RM')}
                                                    placeholder="Any RM"
                                                    ariaLabel="Assignee RM"
                                                />
                                            </div>
                                            <div className="filter-group-v4">
                                                <label>Operation (OP)</label>
                                                <FormCustomSelect
                                                    name="op_id"
                                                    value={filterInputs.op_id}
                                                    onChange={handleFilterChange}
                                                    options={optionsFromPairs(buildRmOpSelectOptions(configs.activeOps), 'Any OP')}
                                                    placeholder="Any OP"
                                                    ariaLabel="Operation OP"
                                                />
                                            </div>
                                        </div>
                                    </div>

                                    <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border)', margin: '16px 0' }} />

                                    <div className="filter-section-v4">
                                        <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Created date</h4>
                                        <div className="filter-row-v4 itr-created-date-row">
                                            <div className="filter-group-v4">
                                                <label>From</label>
                                                <FilterDateInput
                                                    name="created_from"
                                                    value={filterInputs.created_from}
                                                    onChange={handleFilterChange}
                                                    ariaLabel="Created from"
                                                />
                                            </div>
                                            <div className="filter-group-v4">
                                                <label>To</label>
                                                <FilterDateInput
                                                    name="created_to"
                                                    value={filterInputs.created_to}
                                                    onChange={handleFilterChange}
                                                    ariaLabel="Created to"
                                                />
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="drawer-footer">
                                    <button className="btn-reset-v4" onClick={clearFilters}>Reset All</button>
                                    <button type="button" className="btn-apply-v4" onClick={applyFilters}>
                                        Apply Filters
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

            {error && (
                <div className="error-banner">
                    <AlertCircle size={16} />
                    <span>{error}</span>
                </div>
            )}

            <div className="gst-table-wrapper">
                <div className="itr-ledger-body">
                    {/* Header - Always visible */}
                    <div className="itr-ledger-row itr-ledger-header">
                        <div className="itr-ledger-cell itr-ledger-sticky-id">ID</div>
                        <div className="itr-ledger-cell">Client Name</div>
                        <div className="itr-ledger-cell">Mobile</div>
                        <div className="itr-ledger-cell">PAN Number</div>
                        <div className="itr-ledger-cell">Financial Years</div>
                        <div className="itr-ledger-cell">State</div>
                        <div className="itr-ledger-cell">Income Source</div>
                        <div className="itr-ledger-cell">Status</div>
                        <div className="itr-ledger-cell">Record Year</div>
                        <div className="itr-ledger-cell">RM</div>
                        <div className="itr-ledger-cell">OP</div>
                        <div className="itr-ledger-cell itr-ledger-sticky-actions">Actions</div>
                    </div>

                    {loading && data.length === 0 ? (
                        <ITRTableSkeleton rows={12} />
                    ) : (
                        <>
                            {/* Body */}
                            {data.length > 0 ? (
                                data.map(item => (
                                    <div
                                        key={item.id}
                                        className={`itr-ledger-row ${!item.is_active ? 'inactive-row' : ''}`}
                                    >
                                        <div className="itr-ledger-cell id-cell-v4 itr-ledger-sticky-id">{item.id}</div>
                                        <div className="itr-ledger-cell itr-ledger-client-cell">
                                            <span>{item.client_name}</span>
                                            {item.is_active === false && (
                                                <span className="itr-record-status-pill itr-record-status-pill--inactive">Inactive</span>
                                            )}
                                        </div>
                                        <div className="itr-ledger-cell">{item.mobile || '-'}</div>
                                        <div className="itr-ledger-cell gstin-cell">{item.pan_number || '-'}</div>
                                        <div className="itr-ledger-cell itr-ledger-fy-cell">
                                            <FinancialYearPills value={item.financial_year} />
                                        </div>
                                        <div className="itr-ledger-cell">{item.state || '-'}</div>
                                        <div className="itr-ledger-cell itr-ledger-source-cell">
                                            <IncomeSourcePills value={item.source_of_income} />
                                        </div>
                                        <div className="itr-ledger-cell">{getStatusPill(item.filed_status)}</div>
                                        <div className="itr-ledger-cell itr-ledger-record-year-cell">
                                            <RecordYearBadge year={item.year} />
                                        </div>
                                        <div className="itr-ledger-cell">{getRMUsername(item.rm_id, item.rm_name)}</div>
                                        <div className="itr-ledger-cell">{getOPUsername(item.op_id, item.op_name)}</div>
                                        <div
                                            className="itr-ledger-cell itr-actions-cell itr-ledger-sticky-actions"
                                        >
                                            <div className="gst-action-buttons" style={{ justifyContent: 'center' }}>
                                                <button
                                                    type="button"
                                                    className="btn-view-action"
                                                    title="View Details"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        openDetailsDrawer(item);
                                                    }}
                                                >
                                                    <Eye size={14} />
                                                </button>
                                                <button
                                                    type="button"
                                                    className="btn-edit-action"
                                                    title="Edit Record"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        openEditDrawer(item);
                                                    }}
                                                >
                                                    <Pencil size={14} />
                                                </button>
                                                {/* One-time actions — only for FILED records. Record Payment
                                                    hides once fully paid; Schedule Payment hides once the CRM
                                                    lead is already scheduled/subscribed. */}
                                                {String(item.filed_status || '').toUpperCase() === 'FILED' && !item.has_paid_payment && (
                                                    <button
                                                        type="button"
                                                        className="btn-view-action"
                                                        title="Record Payment"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            navigate(`/dashboard?tab=add-payment&service_type=INCOME_TAX&entity_id=${item.id}&return_tab=income-tax`);
                                                        }}
                                                    >
                                                        <CreditCard size={14} />
                                                    </button>
                                                )}
                                                {String(item.filed_status || '').toUpperCase() === 'FILED' && !item.has_paid_payment && (
                                                    <button
                                                        type="button"
                                                        className="btn-view-action"
                                                        title="Schedule Payment (CRM)"
                                                        onClick={(e) => handleRowSchedulePayment(e, item)}
                                                    >
                                                        <CalendarClock size={14} />
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))
                            ) : (
                                <div className="no-data-v4" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>
                                    <FileText size={48} style={{ opacity: 0.2, marginBottom: '16px' }} />
                                    <p>No Income Tax records found</p>
                                </div>
                            )}
                        </>
                    )}
                </div>
                <Pagination
                    currentPage={currentPage}
                    onPageChange={setCurrentPage}
                    hasMore={hasMore}
                    loading={loading}
                />
            </div>
            </>

            <IncomeTaxFormModal 
                isOpen={showCreateModal}
                variant="modal"
                onClose={closeIncomeTaxForm}
                editingRecord={null}
                configs={configs}
                profileData={profileData}
                onSuccess={onFormSuccess}
                onDuplicateRecord={handleDuplicateOnCreate}
                duplicateNotice={duplicateEditNotice}
                onOpenExistingRecord={openExistingFromDuplicate}
            />

            <IncomeTaxFormModal 
                isOpen={showEditDrawer}
                variant="drawer"
                onClose={closeIncomeTaxForm}
                editingRecord={editingRecord}
                configs={configs}
                profileData={profileData}
                onSuccess={onFormSuccess}
                duplicateNotice={duplicateEditNotice}
            />

            <IncomeTaxDetails 
                isOpen={!!viewingRecordId}
                onClose={() => setViewingRecordId(null)}
                recordId={viewingRecordId}
                configs={configs}
                onUpdate={() => fetchIncomeTaxRecords()}
            />
        </div>
    );
};
