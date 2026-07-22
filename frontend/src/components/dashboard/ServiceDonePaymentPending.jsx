import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CreditCard, RotateCcw, Search } from 'lucide-react';
import { fetchServiceDonePaymentPending } from '../../utils/dashboardApi';
import { getRmOpColumnVisibility } from '../../utils/rmOpAssignmentFields';
import Pagination from '../common/Pagination';
import '../common/Filters.css';
import './ServiceDonePaymentPending.css';

const ENTITY_TYPE_OPTIONS = [
    { key: 'ALL', label: 'All', summaryKey: 'total' },
    { key: 'GST_REGISTRATION', label: 'GST Reg', summaryKey: 'gst_registration' },
    { key: 'GST_FILING', label: 'GST Filing', summaryKey: 'gst_filing' },
    { key: 'INCOME_TAX', label: 'Income Tax', summaryKey: 'income_tax' },
    { key: 'CUSTOMER_SERVICE', label: 'Cust. Service', summaryKey: 'customer_service' },
];

const ENTITY_TYPE_LABELS = {
    GST_REGISTRATION: 'GST Registration',
    GST_FILING: 'GST Filing',
    INCOME_TAX: 'Income Tax',
    CUSTOMER_SERVICE: 'Customer Service',
};

const ROWS_PER_PAGE = 25;

function formatCurrency(value) {
    const num = typeof value === 'number' ? value : (value != null && value !== '' ? Number(value) : NaN);
    if (Number.isNaN(num)) return null;
    return num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatEntityType(type) {
    return ENTITY_TYPE_LABELS[type] || (type || '').replace(/_/g, ' ');
}

function getApiErrorMessage(err, fallback = 'Request failed') {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
    return err?.message || fallback;
}

const ServiceDonePaymentPending = () => {
    // No profileData prop this deep in the dashboard tree — the helper falls
    // back to the role on the session token.
    const rmOpCols = getRmOpColumnVisibility();
    const navigate = useNavigate();
    const [rows, setRows] = useState([]);
    const [total, setTotal] = useState(0);
    const [summary, setSummary] = useState({
        total: 0,
        gst_registration: 0,
        gst_filing: 0,
        income_tax: 0,
        customer_service: 0,
    });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [entityFilter, setEntityFilter] = useState('ALL');
    const [page, setPage] = useState(1);
    const [filterInputs, setFilterInputs] = useState({ phone: '', business_name: '' });
    const [appliedFilters, setAppliedFilters] = useState({ phone: '', business_name: '' });

    const loadRows = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = {
                limit: ROWS_PER_PAGE,
                offset: (page - 1) * ROWS_PER_PAGE,
            };
            if (entityFilter !== 'ALL') {
                params.entity_type = entityFilter;
            }
            if (appliedFilters.phone?.trim()) {
                params.phone = appliedFilters.phone.trim();
            }
            if (appliedFilters.business_name?.trim()) {
                params.business_name = appliedFilters.business_name.trim();
            }
            const result = await fetchServiceDonePaymentPending(params);
            setRows(result?.data || []);
            setTotal(Number(result?.total) || 0);
            setSummary(result?.summary || {
                total: 0,
                gst_registration: 0,
                gst_filing: 0,
                income_tax: 0,
                customer_service: 0,
            });
        } catch (err) {
            setError(getApiErrorMessage(err, 'Failed to load service done payment pending list'));
            setRows([]);
            setTotal(0);
        } finally {
            setLoading(false);
        }
    }, [entityFilter, page, appliedFilters]);

    useEffect(() => {
        loadRows();
    }, [loadRows]);

    const openRecordPayment = useCallback((e, row) => {
        e.stopPropagation();
        if (!row?.entity_id || !row?.entity_type) return;
        const params = new URLSearchParams();
        params.set('tab', 'add-payment');
        params.set('entity_id', String(row.entity_id));
        params.set('service_type', row.entity_type);
        params.set('return_tab', 'dashboard');
        params.set('return_sub', 'service-done-payment');
        navigate(`/dashboard?${params.toString()}`);
    }, [navigate]);

    const handleEntityFilterChange = (key) => {
        setEntityFilter(key);
        setPage(1);
    };

    const handleFilterInputChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs((prev) => ({ ...prev, [name]: value }));
    };

    const handleApplyFilters = () => {
        setAppliedFilters({ ...filterInputs });
        setPage(1);
    };

    const handleClearFilters = () => {
        const empty = { phone: '', business_name: '' };
        setFilterInputs(empty);
        setAppliedFilters(empty);
        setPage(1);
    };

    const hasActiveSearchFilters = Boolean(
        appliedFilters.phone?.trim() || appliedFilters.business_name?.trim(),
    );

    return (
        <div className="sdpp-page progress-tracker-page">
            <div className="service-records-shell-v5 progress-shell">
                <div className="progress-content-layout">
                    <div className="progress-main-column">
                        <div className="sdpp-toolbar">
                            <div className="sdpp-entity-pills" role="tablist" aria-label="Filter by entity type">
                                {ENTITY_TYPE_OPTIONS.map((opt) => {
                                    const count = opt.key === 'ALL'
                                        ? summary.total
                                        : (summary[opt.summaryKey] ?? 0);
                                    return (
                                        <button
                                            key={opt.key}
                                            type="button"
                                            role="tab"
                                            aria-selected={entityFilter === opt.key}
                                            className={`sdpp-entity-pill sdpp-entity-pill--${opt.key.toLowerCase()} ${entityFilter === opt.key ? 'is-active' : ''}`}
                                            onClick={() => handleEntityFilterChange(opt.key)}
                                        >
                                            <span className="sdpp-entity-pill-count">{loading ? '—' : count}</span>
                                            <span className="sdpp-entity-pill-label">{opt.label}</span>
                                        </button>
                                    );
                                })}
                            </div>

                            <div className="sdpp-filter-bar">
                                <div className="sdpp-filter-field">
                                    <label htmlFor="sdpp-phone">Phone</label>
                                    <input
                                        id="sdpp-phone"
                                        type="text"
                                        name="phone"
                                        value={filterInputs.phone}
                                        onChange={handleFilterInputChange}
                                        placeholder="Search mobile…"
                                        onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
                                    />
                                </div>
                                <div className="sdpp-filter-field">
                                    <label htmlFor="sdpp-business">Business name</label>
                                    <input
                                        id="sdpp-business"
                                        type="text"
                                        name="business_name"
                                        value={filterInputs.business_name}
                                        onChange={handleFilterInputChange}
                                        placeholder="Search business name…"
                                        onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
                                    />
                                </div>
                                <div className="sdpp-filter-actions">
                                    <button type="button" className="btn-filter-trigger" onClick={handleApplyFilters}>
                                        <Search size={14} /> Apply
                                    </button>
                                    {hasActiveSearchFilters && (
                                        <button type="button" className="btn-clear-v2" onClick={handleClearFilters}>
                                            <RotateCcw size={14} /> Reset
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>

                        <div className="sdpp-table-meta">
                            <span className="service-record-count-v5">
                                {loading ? '…' : `${total} record${total === 1 ? '' : 's'}`}
                            </span>
                        </div>

                        <div className="progress-tracker-container-v4">
                            <div className={`filings-ledger-header sdpp-ledger-grid ${rmOpCols.containerClass}`}>
                                <div className="filings-ledger-header-cell">Type</div>
                                <div className="filings-ledger-header-cell">Entity ID</div>
                                <div className="filings-ledger-header-cell">Cust. ID</div>
                                <div className="filings-ledger-header-cell">Name / Service</div>
                                <div className="filings-ledger-header-cell">Mobile</div>
                                <div className="filings-ledger-header-cell">Service Status</div>
                                <div className={`filings-ledger-header-cell ${rmOpCols.rmCellClass}`}>RM</div>
                                <div className={`filings-ledger-header-cell ${rmOpCols.opCellClass}`}>OP</div>
                                <div className="filings-ledger-header-cell sdpp-col-pending">Pending Amount</div>
                                <div className="filings-ledger-header-cell">Action</div>
                            </div>

                            {loading ? (
                                <div className="filings-ledger-body">
                                    {[...Array(8)].map((_, i) => (
                                        <div key={i} className={`filings-ledger-row sdpp-ledger-grid ${rmOpCols.containerClass}`}>
                                            {[...Array(10)].map((__, j) => (
                                                <div key={j} className={`filings-ledger-cell ${j === 6 ? rmOpCols.rmCellClass : ''}${j === 7 ? rmOpCols.opCellClass : ''}`}>
                                                    <div className="filings-ledger-skeleton-bar" />
                                                </div>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            ) : error ? (
                                <div className="employee-table-error" style={{ padding: 24 }}>{error}</div>
                            ) : (
                                <div className="filings-ledger-body">
                                    {rows.length === 0 ? (
                                        <div className="no-data-v4">No records match the current filters.</div>
                                    ) : (
                                        rows.map((row) => (
                                            <div
                                                key={`${row.entity_type}-${row.entity_id}`}
                                                className={`filings-ledger-row sdpp-ledger-grid ${rmOpCols.containerClass}`}
                                            >
                                                <div className="filings-ledger-cell">
                                                    <span className={`sdpp-entity-chip ${row.entity_type}`}>
                                                        {formatEntityType(row.entity_type)}
                                                    </span>
                                                </div>
                                                <div className="filings-ledger-cell">
                                                    <span className="customer-id-green-v4">{row.entity_id}</span>
                                                </div>
                                                <div className="filings-ledger-cell">
                                                    {row.customer_id ?? '—'}
                                                </div>
                                                <div className="filings-ledger-cell">
                                                    <div className="customer-info-mini-v4">
                                                        <span className="customer-name-v4">
                                                            {row.display_name || row.business_name || '—'}
                                                        </span>
                                                        {(row.gstin || row.pan_number || row.service_code || row.financial_year?.length) && (
                                                            <span className="customer-mobile-v4">
                                                                {[
                                                                    row.gstin,
                                                                    row.pan_number,
                                                                    row.service_code,
                                                                    row.financial_year?.length
                                                                        ? `FY ${row.financial_year.join(', ')}`
                                                                        : null,
                                                                ]
                                                                    .filter(Boolean)
                                                                    .join(' · ')}
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className="filings-ledger-cell">
                                                    {row.mobile || '—'}
                                                </div>
                                                <div className="filings-ledger-cell">
                                                    <span className="sdpp-status-chip">{row.service_status || '—'}</span>
                                                </div>
                                                <div className={`filings-ledger-cell ${rmOpCols.rmCellClass}`}>
                                                    {row.rm_username || row.rm_id || '—'}
                                                </div>
                                                <div className={`filings-ledger-cell ${rmOpCols.opCellClass}`}>
                                                    {row.op_username || row.op_id || '—'}
                                                </div>
                                                <div className="filings-ledger-cell sdpp-col-pending">
                                                    {formatCurrency(row.pending_amount) != null ? (
                                                        <span className="sdpp-pending-amount">
                                                            ₹{formatCurrency(row.pending_amount)}
                                                        </span>
                                                    ) : (
                                                        '—'
                                                    )}
                                                </div>
                                                <div className="filings-ledger-cell">
                                                    <button
                                                        type="button"
                                                        className="sdpp-row-action"
                                                        onClick={(e) => openRecordPayment(e, row)}
                                                        title="Record payment for this entity"
                                                    >
                                                        <CreditCard size={12} /> Pay
                                                    </button>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            <Pagination
                currentPage={page}
                onPageChange={setPage}
                hasMore={page * ROWS_PER_PAGE < total}
                loading={loading}
            />
        </div>
    );
};

export default ServiceDonePaymentPending;
