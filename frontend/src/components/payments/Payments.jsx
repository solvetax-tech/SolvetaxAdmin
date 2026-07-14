import React, { useState, useEffect, useCallback } from 'react';
import { useListLoading } from '../../hooks/useListLoading';
import { useNavigate, useLocation } from 'react-router-dom';
import {
    Search,
    Plus,
    Filter,
    Edit2,
    Trash2,
    CreditCard,
    ChevronLeft,
    ChevronRight,
    Loader2,
    RotateCcw,
    X,
    Eye,
    Clock,
} from 'lucide-react';
import './Payments.css';
import '../customers/CustomerServices.css';
import '../employees/employee.css';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import Button from '../ui/Button';
import StatusPill from '../ui/StatusPill';
import api from '../../utils/api';
import { fetchIncomeTaxPaymentsFilter } from '../../utils/incomeTaxApi';
import LoadingOverlay from '../common/LoadingOverlay';
import Pagination from '../common/Pagination';
import PaymentDetails from './PaymentDetails';
import PaymentFollowupManager from './PaymentFollowupManager';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';

const formatCurrency = (value) => {
    const num = typeof value === 'number' ? value : (value ? Number(value) : 0);
    if (Number.isNaN(num)) return '0.00';
    return num.toFixed(2);
};

const PAYMENT_FOLLOWUP_ENTITY_TYPES = new Set([
    'GST_FILING',
    'GST_FILING_RETURN_DETAILS',
    'CUSTOMER_SERVICE',
]);

function canSchedulePaymentFollowup(payment) {
    if (!payment) return false;
    if (payment.is_active === false) return false;
    if (String(payment.payment_status || '').toUpperCase() !== 'PENDING') return false;
    return PAYMENT_FOLLOWUP_ENTITY_TYPES.has(String(payment.entity_type || '').toUpperCase());
}

function getPaymentFollowupTitle(payment) {
    if (!payment) return '';
    const typeLabel = (payment.entity_type || 'Payment').replace(/_/g, ' ');
    const remaining = payment.remaining_amount ?? payment.net_amount;
    return remaining != null ? `${typeLabel} · ₹${formatCurrency(remaining)} remaining` : typeLabel;
}

/** Normalize list payloads from dynamic_filter vs income-tax-payments/filter */
function normalizePaymentsPayload(payload) {
    if (!payload || typeof payload !== 'object') return { rows: [], total: 0 };
    let rows = payload.data;
    let total = payload.total;
    if (rows && typeof rows === 'object' && !Array.isArray(rows) && Array.isArray(rows.data)) {
        total = rows.total ?? total;
        rows = rows.data;
    }
    if (!Array.isArray(rows)) rows = [];
    const n = typeof total === 'number' ? total : parseInt(total, 10);
    return { rows, total: Number.isFinite(n) ? n : rows.length };
}

export const Payments = ({ handleLogout, isAdmin, onNewPayment }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [payments, setPayments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [page, setPage] = useState(1);
    const [limit] = useState(20);
    const [showFilterModal, setShowFilterModal] = useState(false);
    const [hasFetched, setHasFetched] = useState(false);
    const { wrapFetch } = useListLoading();
    const [globalSearch, setGlobalSearch] = useState('');
    const [selectedPaymentId, setSelectedPaymentId] = useState(null);
    const [activeFollowupId, setActiveFollowupId] = useState(null);
    const [followupPaymentData, setFollowupPaymentData] = useState(null);

    // Filters
    const [filterInputs, setFilterInputs] = useState({
        paymentId: '',
        customerId: '',
        entityId: '',
        entityType: '',
        status: '',
        fromDate: '',
        toDate: ''
    });

    const [appliedFilters, setAppliedFilters] = useState({
        paymentId: '',
        customerId: '',
        entityId: '',
        entityType: '',
        status: '',
        fromDate: '',
        toDate: ''
    });

    const fetchPayments = useCallback(async () => {
        await wrapFetch(setLoading, async () => {
        setError(null);
        try {
            const offset = (page - 1) * limit;
            const params = new URLSearchParams();
            params.append('offset', String(offset));
            params.append('limit', String(limit));
            params.append('include_inactive', 'true');

            if (appliedFilters.paymentId) params.append('payment_id', appliedFilters.paymentId);
            if (appliedFilters.customerId) params.append('customer_id', appliedFilters.customerId);
            if (appliedFilters.entityId) params.append('entity_id', appliedFilters.entityId);
            if (appliedFilters.status) params.append('payment_status', appliedFilters.status);
            if (appliedFilters.fromDate) params.append('from_date', new Date(appliedFilters.fromDate).toISOString());
            if (appliedFilters.toDate) params.append('to_date', new Date(appliedFilters.toDate).toISOString());

            const queryObject = Object.fromEntries(params.entries());

            let response;
            if (appliedFilters.entityType === 'INCOME_TAX') {
                try {
                    response = await fetchIncomeTaxPaymentsFilter(queryObject);
                } catch {
                    const fb = new URLSearchParams(params);
                    fb.append('entity_type', 'INCOME_TAX');
                    response = await api.get(`/api/v1/payments/dynamic_filter?${fb.toString()}`);
                }
            } else {
                response = await api.get(`/api/v1/payments/dynamic_filter?${params.toString()}`);
            }

            const { rows } = normalizePaymentsPayload(response.data);
            setPayments(rows);
            setHasFetched(true);
        } catch (err) {
            console.error("Failed to fetch payments:", err);
            setError(err.response?.data?.detail || "Failed to load payments.");
            if (err.response?.status === 401) handleLogout();
        }
        });
    }, [page, limit, appliedFilters, handleLogout, wrapFetch]);

    useEffect(() => {
        fetchPayments();
    }, [fetchPayments]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const paymentId = params.get('payment_id') || '';
        const entityType = params.get('entity_type') || '';
        setFilterInputs((prev) => ({ ...prev, paymentId, entityType }));
        setAppliedFilters((prev) => ({ ...prev, paymentId, entityType }));
        setPage(1);
    }, [location.search]);

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
                paymentId: '',
                customerId: '',
                entityId: '',
                entityType: '',
                status: '',
                fromDate: '',
                toDate: ''
            };

            if (val) {
                // Heuristic: If it looks like a customer ID (often starts with 'C' or just number)
                // We'll prioritize paymentId, then customerId. Let's just map purely numeric to paymentId as primary if we can't tell, or just entityId.
                // We'll put it in paymentId for now.
                newFilters.paymentId = val;
            }

            setFilterInputs(newFilters);
            setAppliedFilters(newFilters);
            setPage(1);
        }
    };

    const clearFilters = () => {
        const empty = {
            paymentId: '',
            customerId: '',
            entityId: '',
            entityType: '',
            status: '',
            fromDate: '',
            toDate: ''
        };
        setGlobalSearch('');
        setFilterInputs(empty);
        setAppliedFilters(empty);
        setPage(1);
        navigate('/dashboard?tab=payments', { replace: true });
    };

    const handleDelete = async (id) => {
        if (!window.confirm("Are you sure you want to delete this payment?")) return;
        try {
            await api.delete(`/api/v1/payments/${id}/soft_delete`);
            fetchPayments();
        } catch (err) {
            alert(err.response?.data?.detail || "Delete failed");
        }
    };

    const renderFilterChips = () => {
        const labels = {
            paymentId: 'Payment ID',
            customerId: 'Customer ID',
            entityId: 'Entity ID',
            entityType: 'Service',
            status: 'Status',
            fromDate: 'From',
            toDate: 'To'
        };

        return Object.entries(appliedFilters)
            .filter(([, value]) => value !== '')
            .map(([key, value]) => (
                <div key={key} className="filter-chip">
                    <span className="filter-chip-label">{labels[key] || key}:</span>
                    <span className="filter-chip-value">{key === 'entityType' ? String(value).replace(/_/g, ' ') : value}</span>
                    <button className="btn-remove-chip" onClick={() => {
                        setFilterInputs(prev => ({ ...prev, [key]: '' }));
                        setAppliedFilters(prev => ({ ...prev, [key]: '' }));
                        setPage(1);
                        if (key === 'entityType') {
                            const p = new URLSearchParams(location.search);
                            p.delete('entity_type');
                            const qs = p.toString();
                            navigate(qs ? `/dashboard?${qs}` : '/dashboard?tab=payments', { replace: true });
                        }
                    }}>
                        <X size={12} />
                    </button>
                </div>
            ));
    };

    const getEntityTypeBadge = (type) => {
        if (!type) return '-';
        const formatted = type.replace('_', ' ');
        let colorClass = 'default';
        if (type.includes('GST')) colorClass = 'gst';
        if (type.includes('INCOME_TAX')) colorClass = 'income-tax';
        if (type.includes('COMPANY')) colorClass = 'company';
        return <span className={`entity-type-badge ${colorClass}`}>{formatted}</span>;
    };

    return (
        <div className="payments-container">
            <div className="gst-action-bar-v2">
                <div className="global-quick-search" style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '7px 10px', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--bg-input)' }}>
                    <Search size={14} style={{ opacity: 0.55, flexShrink: 0 }} />
                    <input
                        type="text"
                        value={globalSearch}
                        onChange={(e) => setGlobalSearch(e.target.value)}
                        onKeyDown={handleGlobalSearchKeydown}
                        placeholder="Payment ID… ↵"
                        aria-label="Quick search payments by ID"
                        style={{ border: 'none', outline: 'none', background: 'transparent', color: 'inherit', fontSize: '13px', width: '140px' }}
                    />
                </div>
                <div className="active-filters-container" style={{ flex: 1, display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {renderFilterChips()}
                </div>

                <div className="gst-action-buttons">
                    {(Object.values(appliedFilters).some(v => v !== '')) && (
                        <Button variant="ghost" size="sm" icon={<RotateCcw size={14} />} onClick={clearFilters}>
                            Reset Filters
                        </Button>
                    )}
                    <Button variant="secondary" size="sm" icon={<Filter size={13} />} onClick={() => setShowFilterModal(true)}>
                        Filters
                    </Button>
                    <Button variant="primary" size="sm" icon={<Plus size={13} />} onClick={onNewPayment}>
                        New Payment
                    </Button>
                </div>
            </div>

            {/* Unified Filter Drawer */}
            {showFilterModal && (
                <div className="gst-filters-drawer-overlay" onClick={() => setShowFilterModal(false)}>
                    <div className="gst-filters-drawer" onClick={e => e.stopPropagation()}>
                        <div className="drawer-header">
                            <h2 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)' }}>Filter Payments</h2>
                            <button className="btn-drawer-close" onClick={() => setShowFilterModal(false)}><X size={20} /></button>
                        </div>
                        
                        <div className="drawer-content">
                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Identifier Details</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Payment ID</label>
                                        <input type="text" name="paymentId" value={filterInputs.paymentId} onChange={handleFilterChange} placeholder="Enter ID..." />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Customer ID</label>
                                        <input type="text" name="customerId" value={filterInputs.customerId} onChange={handleFilterChange} placeholder="Enter ID..." />
                                    </div>
                                </div>
                                <div className="filter-row-v4" style={{ marginTop: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Entity ID</label>
                                        <input type="text" name="entityId" value={filterInputs.entityId} onChange={handleFilterChange} placeholder="Enter ID..." />
                                    </div>
                                </div>
                                <div className="filter-row-v4" style={{ marginTop: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Service type</label>
                                        <FormCustomSelect
                                            name="entityType"
                                            value={filterInputs.entityType}
                                            onChange={handleFilterChange}
                                            options={optionsFromPairs([
                                                { value: '', label: 'All services' },
                                                { value: 'INCOME_TAX', label: 'Income Tax (ITR)' },
                                            ])}
                                            placeholder="All services"
                                            ariaLabel="Service type"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Filing Attributes</h4>
                                <div className="filter-row-v4">
                                    <div className="filter-group-v4">
                                        <label>Payment Status</label>
                                        <FormCustomSelect
                                            name="status"
                                            value={filterInputs.status}
                                            onChange={handleFilterChange}
                                            options={optionsFromPairs([
                                                { value: '', label: 'All Status' },
                                                { value: 'PAID', label: 'Paid' },
                                                { value: 'PENDING', label: 'Pending' },
                                                { value: 'PARTIAL_PAID', label: 'Partial' },
                                                { value: 'FAILED', label: 'Failed' },
                                            ])}
                                            placeholder="All Status"
                                            ariaLabel="Payment status"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Timeline Context</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
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
                        </div>

                        <div className="drawer-footer">
                            <button className="btn-reset-v4" onClick={clearFilters}>Reset All</button>
                            <button className="btn-apply-v4" onClick={() => { handleSearch(); setShowFilterModal(false); }}>
                                {loading ? 'Searching...' : 'Apply Filters'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <div className="payments-ledger-container">
                        <div className="payments-ledger-row payments-ledger-header">
                            <div className="payments-ledger-cell pay-ledger-sticky-id pay-ledger-sticky-col-1">ID</div>
                            <div className="payments-ledger-cell pay-ledger-sticky-id pay-ledger-sticky-col-2">Cust ID</div>
                            <div className="payments-ledger-cell pay-ledger-sticky-id pay-ledger-sticky-col-3">Entity ID</div>
                            <div className="payments-ledger-cell">Type</div>
                            <div className="payments-ledger-cell justify-end">Amount</div>
                            <div className="payments-ledger-cell justify-end">Discount</div>
                            <div className="payments-ledger-cell justify-end">Net</div>
                            <div className="payments-ledger-cell justify-end">Paid</div>
                            <div className="payments-ledger-cell justify-end">Remaining</div>
                            <div className="payments-ledger-cell">Payment Date</div>
                            <div className="payments-ledger-cell justify-center">Status</div>
                            <div className="payments-ledger-cell justify-center">Follow-up</div>
                            <div className="payments-ledger-cell justify-center">Active</div>
                            <div className="payments-ledger-cell pay-ledger-actions-sticky justify-center">Actions</div>
                        </div>

                        {loading ? (
                            Array(limit).fill(0).map((_, i) => (
                                <div key={`skeleton-${i}`} className="payments-ledger-row skeleton-row-v2">
                                    {Array(14).fill(0).map((_, j) => {
                                        let stickyClass = '';
                                        if (j === 0) stickyClass = 'pay-ledger-sticky-id pay-ledger-sticky-col-1';
                                        if (j === 1) stickyClass = 'pay-ledger-sticky-id pay-ledger-sticky-col-2';
                                        if (j === 2) stickyClass = 'pay-ledger-sticky-id pay-ledger-sticky-col-3';
                                        if (j === 13) stickyClass = 'pay-ledger-actions-sticky';
                                        return (
                                            <div key={j} className={`payments-ledger-cell ${stickyClass}`}>
                                                <div className="skeleton-item-v2 skeleton-pulse-v2" />
                                            </div>
                                        );
                                    })}
                                </div>
                            ))
                        ) : error ? (
                            <div className="payments-ledger-row" style={{ gridTemplateColumns: '1fr', width: '100%' }}>
                                <div className="payments-ledger-cell justify-center" style={{ color: 'var(--danger)' }}>Error: {error}</div>
                            </div>
                        ) : (payments.length === 0 && hasFetched) ? (
                            <div className="payments-ledger-row" style={{ gridTemplateColumns: '1fr', width: '100%' }}>
                                <div className="payments-ledger-cell justify-center" style={{ color: 'var(--text-primary)' }}>No payments found matching filters.</div>
                            </div>
                        ) : (
                            payments.map((p) => (
                                <div
                                    key={p.id}
                                    className={`payments-ledger-row${selectedPaymentId === p.id || activeFollowupId === p.id ? ' active-drawer-row' : ''}`}
                                >
                                    <div className="payments-ledger-cell pay-ledger-sticky-id pay-ledger-sticky-col-1 pay-col-id"><span className="ui-num" style={{ fontWeight: 600 }}>{p.id}</span></div>
                                    <div className="payments-ledger-cell pay-ledger-sticky-id pay-ledger-sticky-col-2 pay-col-id"><span className="ui-num">{p.customer_id}</span></div>
                                    <div className="payments-ledger-cell pay-ledger-sticky-id pay-ledger-sticky-col-3 pay-col-id"><span className="ui-num">{p.entity_id}</span></div>
                                    <div className="payments-ledger-cell">{getEntityTypeBadge(p.entity_type)}</div>
                                    <div className="payments-ledger-cell pay-col-amount justify-end"><span className="ui-num">₹{formatCurrency(p.amount)}</span></div>
                                    <div className="payments-ledger-cell pay-col-discount justify-end"><span className="ui-num">₹{formatCurrency(p.discount)}</span></div>
                                    <div className="payments-ledger-cell pay-col-amount justify-end"><span className="ui-num">₹{formatCurrency(p.net_amount)}</span></div>
                                    <div className="payments-ledger-cell pay-col-amount justify-end"><span className="ui-num">₹{formatCurrency(p.paid_amount)}</span></div>
                                    <div className="payments-ledger-cell pay-col-amount justify-end"><span className="ui-num" style={{ color: p.remaining_amount > 0 ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: p.remaining_amount > 0 ? 600 : 400 }}>₹{formatCurrency(p.remaining_amount)}</span></div>
                                    <div className="payments-ledger-cell pay-col-date"><span className="ui-num" style={{ color: 'var(--text-primary)' }}>{p.payment_date ? new Date(p.payment_date).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '-'}</span></div>
                                    <div className="payments-ledger-cell justify-center">
                                        <StatusPill value={p.payment_status} />
                                    </div>
                                    <div className="payments-ledger-cell justify-center">
                                        {canSchedulePaymentFollowup(p) ? (
                                            <Button
                                                variant={activeFollowupId === p.id ? 'primary' : 'secondary'}
                                                size="sm"
                                                icon={<Plus size={14} />}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setSelectedPaymentId(null);
                                                    setActiveFollowupId(p.id);
                                                    setFollowupPaymentData(p);
                                                }}
                                            >
                                                Create
                                            </Button>
                                        ) : (
                                            <span className="cs-followup-na">—</span>
                                        )}
                                    </div>
                                    <div className="payments-ledger-cell justify-center">
                                        <StatusPill tone={p.is_active ? 'success' : 'neutral'}>
                                            {p.is_active ? 'Active' : 'Inactive'}
                                        </StatusPill>
                                    </div>
                                    <div className="payments-ledger-cell pay-ledger-actions-sticky">
                                        <div className="table-actions-combined">
                                            <Button
                                                variant="ghost"
                                                icon={<Eye size={16} />}
                                                title="View payment"
                                                aria-label="View payment"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setSelectedPaymentId(p.id);
                                                }}
                                            />
                                            {isAdmin && (
                                                <Button
                                                    variant="ghost"
                                                    icon={<Trash2 size={16} />}
                                                    title="Delete payment"
                                                    aria-label="Delete payment"
                                                    style={{ color: 'var(--danger)' }}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleDelete(p.id);
                                                    }}
                                                />
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))
                        )}
            </div>

            <Pagination
                currentPage={page}
                onPageChange={setPage}
                hasMore={payments.length >= limit}
                loading={loading}
            />

            {selectedPaymentId && (
                    <PaymentDetails
                        selectedId={selectedPaymentId}
                        onClose={() => setSelectedPaymentId(null)}
                        onLogout={handleLogout}
                    />
            )}

            <div className={`followup-drawer-overlay ${activeFollowupId ? 'show' : ''}`} onClick={() => {
                setActiveFollowupId(null);
                setFollowupPaymentData(null);
            }}>
                <div className={`followup-drawer-panel ${activeFollowupId ? 'show' : ''}`} onClick={e => e.stopPropagation()}>
                    <div className="drawer-header">
                        <div className="drawer-title">
                            <Clock size={14} />
                            <div>
                                <h3>Follow-up Management</h3>
                                <div className="drawer-task-identity">
                                    <span className="task-id-pill">{followupPaymentData?.id}</span>
                                    <span className="task-service-text">{getPaymentFollowupTitle(followupPaymentData)}</span>
                                </div>
                            </div>
                        </div>
                        <button type="button" className="btn-close-drawer" onClick={() => {
                            setActiveFollowupId(null);
                            setFollowupPaymentData(null);
                        }}>&times;</button>
                    </div>

                    <div className="drawer-body" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 100px)', overflow: 'visible' }}>
                        {activeFollowupId && (
                            <PaymentFollowupManager
                                paymentId={activeFollowupId}
                                paymentData={followupPaymentData}
                                rmUsername={followupPaymentData?.rm_name || followupPaymentData?.rm_username || '-'}
                                onFollowupCreated={() => {
                                    setActiveFollowupId(null);
                                    setFollowupPaymentData(null);
                                    fetchPayments();
                                }}
                            />
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
