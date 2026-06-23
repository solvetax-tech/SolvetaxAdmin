import React, { useState, useEffect, useCallback } from 'react';
import {
    History,
    Search,
    Filter,
    RotateCcw,
    X,
    User,
    Activity,
    Calendar,
    ChevronLeft,
    ChevronRight,
    Loader2,
    Database,
    Clock,
    FileText,
    PlusCircle,
    Edit3,
    Trash2,
    Zap,
    Info,
    ArrowRight
} from 'lucide-react';
import api from '../../utils/api';
import './Version.css';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import LoadingOverlay from '../common/LoadingOverlay';
import Pagination from '../common/Pagination';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';

const Version = ({ handleLogout, isAdmin, headerStart = null }) => {
    const [versions, setVersions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [limit] = useState(50);
    const [showFilterDrawer, setShowFilterDrawer] = useState(false);
    const [selectedVersion, setSelectedVersion] = useState(null);
    const [showDiffModal, setShowDiffModal] = useState(false);
    const [hasFetched, setHasFetched] = useState(false);
    const [globalSearch, setGlobalSearch] = useState('');

    // Filter states
    const [filterInputs, setFilterInputs] = useState({
        id: '',
        empId: '',
        entityType: '',
        entityId: '',
        customerId: '',
        action: '',
        fromDate: '',
        toDate: ''
    });

    const [appliedFilters, setAppliedFilters] = useState({
        id: '',
        empId: '',
        entityType: '',
        entityId: '',
        customerId: '',
        action: '',
        fromDate: '',
        toDate: ''
    });

    const fetchVersions = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            params.append('offset', (page - 1) * limit);
            params.append('limit', limit);

            if (appliedFilters.id) params.append('id', appliedFilters.id);
            if (appliedFilters.empId) params.append('emp_id', appliedFilters.empId);
            if (appliedFilters.entityType) params.append('entity_type', appliedFilters.entityType);
            if (appliedFilters.entityId) params.append('entity_id', appliedFilters.entityId);
            if (appliedFilters.customerId) params.append('customer_id', appliedFilters.customerId);
            if (appliedFilters.action) params.append('action', appliedFilters.action);
            if (appliedFilters.fromDate) params.append('from_date', appliedFilters.fromDate);
            if (appliedFilters.toDate) params.append('to_date', appliedFilters.toDate);

            const response = await api.get(`/api/v1/version/dynamic_filter?${params.toString()}`);
            setVersions(response.data.data || []);
            setTotal(response.data.total_count || 0);
            setHasFetched(true);
        } catch (err) {
            console.error("Failed to fetch version history:", err);
            setError(err.response?.data?.detail || "Failed to load audit logs.");
            if (err.response?.status === 401) handleLogout();
        } finally {
            setLoading(false);
        }
    }, [page, limit, appliedFilters, handleLogout]);

    useEffect(() => {
        fetchVersions();
    }, [fetchVersions]);

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const handleSearch = () => {
        setPage(1);
        setAppliedFilters({ ...filterInputs });
    };

    const handleGlobalSearchKeydown = (e) => {
        if (e.key === 'Enter') {
            const val = globalSearch.trim();
            const newFilters = {
                id: '', empId: '', entityType: '', entityId: '', customerId: '', action: '', fromDate: '', toDate: ''
            };

            if (val) {
                // Heuristic: mapping to entityId by default if numeric.
                if (/^\d+$/.test(val)) {
                    newFilters.entityId = val;
                } else {
                    // Try mapping to action or entityType by capitalizing
                    newFilters.entityType = val.toUpperCase();
                }
            }

            setFilterInputs(newFilters);
            setAppliedFilters(newFilters);
            setPage(1);
        }
    };

    const clearFilters = () => {
        const empty = { id: '', empId: '', entityType: '', entityId: '', customerId: '', action: '', fromDate: '', toDate: '' };
        setGlobalSearch('');
        setFilterInputs(empty);
        setAppliedFilters(empty);
        setPage(1);
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try {
            return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
        } catch {
            return dtStr;
        }
    };

    const renderFilterChips = () => {
        const labels = {
            id: 'Audit ID',
            empId: 'Employee ID',
            entityType: 'Entity Type',
            entityId: 'Entity ID',
            customerId: 'Customer ID',
            action: 'Action',
            fromDate: 'From',
            toDate: 'To'
        };

        return Object.entries(appliedFilters)
            .filter(([_, value]) => value !== '')
            .map(([key, value]) => (
                <div key={key} className="filter-chip">
                    <span className="filter-chip-label">{labels[key] || key}:</span>
                    <span className="filter-chip-value">{value}</span>
                    <button className="btn-remove-chip" onClick={() => {
                        setFilterInputs(prev => ({ ...prev, [key]: '' }));
                        setAppliedFilters(prev => ({ ...prev, [key]: '' }));
                        setPage(1);
                    }}>
                        <X size={12} />
                    </button>
                </div>
            ));
    };

    const JsonDiffViewer = ({ before, after }) => {
        const bObj = before && typeof before === 'string' ? JSON.parse(before) : (before || {});
        const aObj = after && typeof after === 'string' ? JSON.parse(after) : (after || {});

        const allKeys = Array.from(new Set([...Object.keys(bObj), ...Object.keys(aObj)]));
        const changedKeys = allKeys.filter(key => JSON.stringify(bObj[key]) !== JSON.stringify(aObj[key]));
        const unchangedKeys = allKeys.filter(key => JSON.stringify(bObj[key]) === JSON.stringify(aObj[key]));

        const formatValue = (val, prefix = '') => {
            if (val === null || val === undefined || val === '-') return <span className="val-null">{prefix}-</span>;

            let content;
            if (typeof val === 'string') content = val;
            else if (typeof val === 'number') content = val;
            else if (typeof val === 'boolean') content = val.toString();
            else if (Array.isArray(val)) content = '[Array]';
            else if (typeof val === 'object') content = Object.keys(val).length > 0 ? '{...}' : '{}';
            else content = String(val);

            const className = typeof val === 'object' ? 'val-complex' :
                typeof val === 'number' ? 'val-number' :
                    typeof val === 'boolean' ? 'val-bool' : 'val-string';

            return <span className={className}>{prefix}{content}</span>;
        };

        return (
            <div className="audit-comparison-container">
                <div className="comparison-section">
                    <div className="comparison-header-v5">
                        <Zap size={14} className="icon-zap" />
                        <span>Updated Fields</span>
                        {changedKeys.length > 0 && <span className="count-pill">{changedKeys.length}</span>}
                    </div>
                    {changedKeys.length > 0 ? (
                        <div className="comparison-table-wrapper">
                            <table className="comparison-table">
                                <thead>
                                    <tr>
                                        <th>Property</th>
                                        <th>Original State</th>
                                        <th>Updated State</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {changedKeys.map(key => (
                                        <tr key={key}>
                                            <td className="prop-name">{key}</td>
                                            <td className="state-cell state-original">{formatValue(bObj[key], '- ')}</td>
                                            <td className="state-cell state-updated">{formatValue(aObj[key], '+ ')}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="no-changes-msg">No fields were updated in this event.</div>
                    )}
                </div>

                <div className="comparison-section unchanged-section">
                    <div className="comparison-header-v5">
                        <Database size={14} className="icon-db" />
                        <span>Unchanged Fields</span>
                        {unchangedKeys.length > 0 && <span className="count-pill gray">{unchangedKeys.length}</span>}
                    </div>
                    {unchangedKeys.length > 0 ? (
                        <div className="unchanged-grid">
                            {unchangedKeys.map(key => (
                                <div key={key} className="unchanged-item">
                                    <span className="unchanged-key">{key}</span>
                                    <span className="unchanged-val">{formatValue(bObj[key])}</span>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="no-changes-msg">No unchanged fields found.</div>
                    )}
                </div>
            </div>
        );
    };

    const AuditLogTableSkeleton = () => (
        <div className="audit-ledger-body">
            {[...Array(12)].map((_, i) => (
                <div key={i} className="audit-ledger-row audit-ledger-grid-template">
                    <div className="audit-ledger-cell audit-ledger-sticky-id">
                        <div className="filings-ledger-skeleton-bar" style={{ width: '40px' }} />
                    </div>
                    {[...Array(7)].map((_, j) => (
                        <div key={j} className="audit-ledger-cell">
                            <div className="filings-ledger-skeleton-bar" />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );

    return (
        <div className="version-tab-v2">
            <div className="tab-header-v2 version-audit-action-bar">
                {headerStart ? (
                    <div className="version-audit-header-start">{headerStart}</div>
                ) : null}

                <div className="active-filters-container">
                    {renderFilterChips()}
                </div>

                <div className="version-audit-filter-actions">
                    <button className="btn-filter-trigger" onClick={() => setShowFilterDrawer(true)}>
                        <Filter size={14} /> Filters
                    </button>
                    {(Object.values(appliedFilters).some(v => v !== '')) && (
                        <button className="btn-clear-v2" onClick={clearFilters}>
                            <RotateCcw size={16} /> Reset Filters
                        </button>
                    )}
                </div>
            </div>

            {/* Filter Drawer */}
            <div className={`premium-drawer-overlay ${showFilterDrawer ? 'show' : ''}`} onClick={() => setShowFilterDrawer(false)}>
                <div className="premium-drawer-right" onClick={e => e.stopPropagation()}>
                    <div className="drawer-header-v4">
                        <h2><Filter size={20} /> Filter Audit Log</h2>
                        <button className="btn-drawer-close" onClick={() => setShowFilterDrawer(false)}><X size={18} /></button>
                    </div>

                    <div className="drawer-content-v4">
                        <div className="drawer-filter-grid">
                            <div className="filter-group-v4">
                                <label>Audit ID</label>
                                <input type="number" name="id" value={filterInputs.id} onChange={handleFilterChange} placeholder="Search by ID..." />
                            </div>
                            <div className="filter-group-v4">
                                <label>Employee ID</label>
                                <input type="number" name="empId" value={filterInputs.empId} onChange={handleFilterChange} placeholder="Search by Emp ID..." />
                            </div>
                            <div className="filter-group-v4">
                                <label>Entity Type</label>
                                <FormCustomSelect
                                    name="entityType"
                                    value={filterInputs.entityType}
                                    onChange={handleFilterChange}
                                    options={optionsFromPairs([
                                        { value: '', label: 'All Types' },
                                        { value: 'EMPLOYEE', label: 'Employee' },
                                        { value: 'CUSTOMER', label: 'Customer' },
                                        { value: 'GST_REGISTRATION', label: 'GST Registration' },
                                        { value: 'REGISTRATION_PAYMENT', label: 'Payment' },
                                    ])}
                                    placeholder="All Types"
                                    ariaLabel="Entity type"
                                />
                            </div>
                            <div className="filter-group-v4">
                                <label>Entity ID</label>
                                <input type="number" name="entityId" value={filterInputs.entityId} onChange={handleFilterChange} placeholder="ID of entity..." />
                            </div>
                            <div className="filter-group-v4">
                                <label>Customer ID</label>
                                <input type="number" name="customerId" value={filterInputs.customerId} onChange={handleFilterChange} placeholder="Search by Cust ID..." />
                            </div>
                            <div className="filter-group-v4">
                                <label>Action</label>
                                <FormCustomSelect
                                    name="action"
                                    value={filterInputs.action}
                                    onChange={handleFilterChange}
                                    options={optionsFromPairs([
                                        { value: '', label: 'All Actions' },
                                        { value: 'CREATE', label: 'CREATE' },
                                        { value: 'UPDATE', label: 'UPDATE' },
                                        { value: 'DELETE', label: 'DELETE' },
                                        { value: 'ACTIVATE', label: 'ACTIVATE' },
                                    ])}
                                    placeholder="All Actions"
                                    ariaLabel="Action"
                                />
                            </div>
                            <div className="filter-group-v4">
                                <label>From Date</label>
                                <FilterDateInput name="fromDate" value={filterInputs.fromDate} onChange={handleFilterChange} ariaLabel="From date" />
                            </div>
                            <div className="filter-group-v4">
                                <label>To Date</label>
                                <FilterDateInput name="toDate" value={filterInputs.toDate} onChange={handleFilterChange} ariaLabel="To date" />
                            </div>
                        </div>
                    </div>

                    <div className="drawer-footer-v4">
                        <button className="btn-reset-v4" onClick={clearFilters}>Reset</button>
                        <button className="btn-apply-v4" onClick={() => { handleSearch(); setShowFilterDrawer(false); }}>
                            Apply Filters
                        </button>
                    </div>
                </div>
            </div>

            <div className="version-table-wrapper">
                <div className="audit-ledger-scroll-root">
                    <div className="audit-ledger-inner-wrapper">
                        <div className="version-table-container">
                            <div className="audit-ledger-header audit-ledger-grid-template">
                                <div className="audit-ledger-header-cell audit-ledger-sticky-id">ID</div>
                                <div className="audit-ledger-header-cell">Timestamp</div>
                                <div className="audit-ledger-header-cell">Action</div>
                                <div className="audit-ledger-header-cell">Entity Type</div>
                                <div className="audit-ledger-header-cell">Entity ID</div>
                                <div className="audit-ledger-header-cell">Customer ID</div>
                                <div className="audit-ledger-header-cell">Employee</div>
                                <div className="audit-ledger-header-cell" style={{ textAlign: 'center' }}>Action</div>
                            </div>

                            <div className="audit-ledger-body">
                                {loading ? (
                                    <AuditLogTableSkeleton />
                                ) : error ? (
                                    <div className="table-error-row" style={{ padding: '40px', textAlign: 'center', color: '#f44336' }}>Error: {error}</div>
                                ) : (versions.length === 0 && hasFetched) ? (
                                    <div className="table-msg-row" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-primary)' }}>No audit records found.</div>
                                ) : (
                                    versions.map((v) => (
                                        <div key={v.id} className="audit-ledger-row audit-ledger-grid-template">
                                            <div className="audit-ledger-cell audit-ledger-sticky-id">
                                                <button
                                                    className="id-link id-text"
                                                    onClick={() => { setSelectedVersion(v); setShowDiffModal(true); }}
                                                >
                                                    {v.id}
                                                </button>
                                            </div>
                                            <div className="audit-ledger-cell">
                                                <div className="timestamp-group">
                                                    <span className="main-time">{formatDateTime(v.created_at).split(',')[1]}</span>
                                                    <span className="sub-date">{formatDateTime(v.created_at).split(',')[0]}</span>
                                                </div>
                                            </div>
                                            <div className="audit-ledger-cell">
                                                <span className={`action-badge badge-${v.action?.toLowerCase()}`}>
                                                    {v.action}
                                                </span>
                                            </div>
                                            <div className="audit-ledger-cell">
                                                <span className="entity-type-badge">
                                                    {v.entity_type}
                                                </span>
                                            </div>
                                            <div className="audit-ledger-cell">
                                                <span className="mono-id">{v.entity_id}</span>
                                            </div>
                                            <div className="audit-ledger-cell">
                                                <span className="mono-id">{v.customer_id ? `${v.customer_id}` : '-'}</span>
                                            </div>
                                            <div className="audit-ledger-cell">
                                                <div className="emp-id-group">
                                                    <div className="emp-icon-wrapper">
                                                        <User size={14} />
                                                    </div>
                                                    <span className="emp-id-text" title={v.emp_name || (v.emp_id != null ? String(v.emp_id) : '')}>{v.emp_name || v.emp_id || '-'}</span>
                                                </div>
                                            </div>
                                            <div className="audit-ledger-cell" style={{ textAlign: 'center' }}>
                                                <button className="btn-view-diff" onClick={() => { setSelectedVersion(v); setShowDiffModal(true); }}>
                                                    <Activity size={14} /> View Diff
                                                </button>
                                            </div>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    </div>
                </div>

                <Pagination
                    currentPage={page}
                    onPageChange={setPage}
                    hasMore={versions.length >= limit}
                    loading={loading}
                />
            </div>

            {/* Diff Viewer Modal */}
            {showDiffModal && selectedVersion && (
                <div className="premium-filter-overlay show" onClick={() => setShowDiffModal(false)}>
                    <div className="premium-filter-modal diff-modal-wide" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <div className="flex-col">
                                <h3>Audit Event Details</h3>
                                <p style={{ fontSize: '12px', color: 'var(--text-primary)' }}>ID: {selectedVersion.id}</p>
                            </div>
                            <button className="btn-close-modal" onClick={() => setShowDiffModal(false)}>&times;</button>
                        </div>
                        <div className="modal-body-scroll">
                            <JsonDiffViewer
                                before={
                                    selectedVersion.action === 'CREATE' || selectedVersion.action === 'ACTIVATE' ? null :
                                        selectedVersion.action === 'DELETE' ? selectedVersion.updated_json :
                                            selectedVersion.json
                                }
                                after={
                                    selectedVersion.action === 'DELETE' ? null :
                                        selectedVersion.action === 'CREATE' ? selectedVersion.json :
                                            selectedVersion.updated_json
                                }
                            />
                        </div>
                        <div className="modal-footer">
                            <button className="btn-modal-clear" onClick={() => setShowDiffModal(false)}>Close</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Version;
