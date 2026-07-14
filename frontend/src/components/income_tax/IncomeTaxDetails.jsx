import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, UserCircle, Briefcase, FileText, CheckCircle2, XCircle, AlertCircle, Loader2, IndianRupee } from 'lucide-react';
import api from '../../utils/api';
import { fetchIncomeTaxById, unwrapIncomeTaxRecord, setIncomeTaxActive } from '../../utils/incomeTaxApi';
import { formatDateIST, formatDateTimeIST, formatEnumLabel } from '../../utils/formatDateTimeIST';
import IncomeSourcePills from './IncomeSourcePills';
import FinancialYearPills from './FinancialYearPills';
import RecordYearBadge from './RecordYearBadge';
import AddPayment from '../payments/AddPayment';

/** GET /income-tax/:id returns a flat row; some callers may wrap as { data } or { income_tax }. */
function unwrapIncomeTaxDetailPayload(raw) {
    if (!raw || typeof raw !== 'object') return null;
    if (raw.data != null && typeof raw.data === 'object' && !Array.isArray(raw.data)) return raw.data;
    if (raw.income_tax != null && typeof raw.income_tax === 'object') return raw.income_tax;
    return raw;
}

const IncomeTaxDetails = ({ isOpen, onClose, recordId, configs, onUpdate }) => {
    const [details, setDetails] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [statusUpdating, setStatusUpdating] = useState(false);
    const [activeTab, setActiveTab] = useState('general');
    const [payments, setPayments] = useState([]);
    const [paymentsLoading, setPaymentsLoading] = useState(false);
    const [showAddPayment, setShowAddPayment] = useState(false);
    
    const getStatusPill = (status) => {
        const s = (status || '').toUpperCase();
        if (s === 'FILED') return <span className="status-pill-v4 status-filed">Filed</span>;
        if (s === 'NOT_FILED' || s === 'PENDING') return <span className="status-pill-v4 status-pending">Not Filed</span>;
        return <span className="status-pill-v4 status-default">{s || 'UNKNOWN'}</span>;
    };

    const getRMUsername = (id, nameFromRow) => {
        if (nameFromRow) return `👤 ${nameFromRow}`;
        if (!id) return 'Unassigned';
        if (typeof id === 'string' && Number.isNaN(parseInt(id, 10))) return `👤 ${id}`;
        if (configs.activeRMs?.includes(id) || configs.activeRMs?.includes(String(id))) return `👤 ${id}`;
        return `👤 ID: ${id}`;
    };

    const getOPUsername = (id, nameFromRow) => {
        if (nameFromRow) return `⚙️ ${nameFromRow}`;
        if (!id) return 'Unassigned';
        if (typeof id === 'string' && Number.isNaN(parseInt(id, 10))) return `⚙️ ${id}`;
        if (configs.activeOps?.includes(id) || configs.activeOps?.includes(String(id))) return `⚙️ ${id}`;
        return `⚙️ ID: ${id}`;
    };

    useEffect(() => {
        if (isOpen && recordId) {
            setActiveTab('general');
            fetchDetails();
        } else {
            setDetails(null);
            setPayments([]);
        }
    }, [isOpen, recordId]);


    const fetchDetails = async () => {
        setLoading(true);
        setError(null);
        try {
            // Standardizing to the correct backend detail endpoint
            const res = await fetchIncomeTaxById(recordId);
            const fetchedData = unwrapIncomeTaxRecord(res.data);

            if (!fetchedData || (typeof fetchedData === 'object' && Object.keys(fetchedData).length === 0)) {
                throw new Error("No data found for this record");
            }

            setDetails({
                referral_phone_number: null,
                ...fetchedData,
            });
        } catch (err) {
            console.error("Error fetching ITR details:", err);
            setError("Failed to load details. The record might not exist or the server is unreachable.");
        } finally {
            setLoading(false);
        }
    };

    const fetchPayments = async () => {
        setPaymentsLoading(true);
        try {
            const res = await api.get(`/api/v1/payments/dynamic_filter?entity_id=${recordId}&entity_type=INCOME_TAX&limit=100`);
            setPayments(res.data.data || []);
        } catch (err) {
            console.error("Error fetching ITR payments:", err);
        } finally {
            setPaymentsLoading(false);
        }
    };

    const handleToggleStatus = async () => {
        setStatusUpdating(true);
        try {
            await setIncomeTaxActive(recordId, !details.is_active);
            await fetchDetails();
            if (onUpdate) onUpdate();
        } catch (err) {
            console.error(`Failed to ${details.is_active ? 'deactivate' : 'activate'}:`, err);
            const detail = err?.response?.data?.detail;
            const msg = typeof detail === 'string'
                ? detail
                : detail?.error?.message || 'Status update failed';
            alert(msg);
        } finally {
            setStatusUpdating(false);
        }
    };

    if (!isOpen) return null;

    const panel = (
        <div className={`gst-details-drawer-overlay ${isOpen ? 'open' : ''}`} onClick={onClose}>
            <div className={`gst-details-drawer itr-details-drawer app-drawer-panel ${isOpen ? 'open' : ''}`} onClick={e => e.stopPropagation()}>
                <div className="drawer-header-v4">
                    <div className="header-icon-v4">
                        <UserCircle size={24} />
                    </div>
                    <div className="header-text-v4">
                        <h3>Income Tax Details</h3>
                        <p className="itr-details-header-sub">
                            {details?.client_name || 'Loading details...'}
                            {details?.year != null && (
                                <RecordYearBadge year={details.year} className="itr-details-year-badge" />
                            )}
                        </p>
                    </div>
                    <button className="btn-close-drawer-v4" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                <div className="drawer-tabs-v4">
                    <button 
                        className={`drawer-tab-btn ${activeTab === 'general' ? 'active' : ''}`}
                        onClick={() => setActiveTab('general')}
                    >
                        General Info
                    </button>
                    <button 
                        className={`drawer-tab-btn ${activeTab === 'payments' ? 'active' : ''}`}
                        onClick={() => {
                            setActiveTab('payments');
                            fetchPayments();
                        }}
                    >
                        Payments {payments.length > 0 && <span className="tab-count">{payments.length}</span>}
                    </button>
                </div>

                <div className="drawer-body-v4">
                    {loading ? (
                        <div className="drawer-loading-box">
                            <Loader2 className="spin" size={32} />
                            <p>Fetching full record...</p>
                        </div>
                    ) : error ? (
                        <div className="drawer-error-box">
                            <AlertCircle size={24} />
                            <p>{error}</p>
                            <button onClick={fetchDetails}>Retry</button>
                        </div>
                    ) : details ? (
                        <div className="details-container-v4">
                            {activeTab === 'general' ? (
                                <>
                                    <div className="details-section-v4">
                                <h4 className="section-title-v4">Client Information</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>PAN Number</label>
                                        <span className="mono-v4">{details.pan_number || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Record year</label>
                                        <span>
                                            <RecordYearBadge year={details.year} />
                                        </span>
                                    </div>
                                    <div className="info-item-v4 info-item-v4--fy">
                                        <label>Financial years (ITR)</label>
                                        <span className="info-item-sources-wrap">
                                            <FinancialYearPills value={details.financial_year} />
                                        </span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Mobile</label>
                                        <span>{details.mobile || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Referrer phone</label>
                                        <span>{details.referral_phone_number || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Email ID</label>
                                        <span>{details.email_id || '-'}</span>
                                    </div>
                                    {details.year != null && (
                                        <div className="info-item-v4">
                                            <label>Record year</label>
                                            <span className="itr-record-year-meta">{details.year}</span>
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Tax & Filing Details</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4 info-item-v4--sources">
                                        <label>Source of Income</label>
                                        <span className="info-item-sources-wrap">
                                            <IncomeSourcePills value={details.source_of_income} />
                                        </span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Refund Amount</label>
                                        <span className="amount-v4">₹ {details.refund_amount?.toLocaleString() || '0'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Filing Status</label>
                                        <span>{getStatusPill(details.filed_status)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>State</label>
                                        <span>{details.state || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Priority</label>
                                        <span className={`priority-tag-v4 ${(details.priority || 'LOW').toLowerCase()}`}>
                                            {details.priority || 'LOW'}
                                        </span>
                                    </div>
                                    {details.filed_status === 'FILED' && (
                                        <div className="info-item-v4">
                                            <label>Filing Date</label>
                                            <span>{formatDateTimeIST(details.filing_date)}</span>
                                        </div>
                                    )}
                                </div>
                                {details.remarks && (
                                    <div className="remarks-box-v4" style={{ marginTop: '16px', padding: '12px', background: 'var(--bg-surface-2)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                                        <label style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>Internal Remarks</label>
                                        <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>{details.remarks}</p>
                                    </div>
                                )}
                            </div>

                            {(details.created_at || details.updated_at) && (
                                <div className="details-section-v4">
                                    <h4 className="section-title-v4">Record timeline</h4>
                                    <div className="info-grid-v4">
                                        {details.created_at && (
                                            <div className="info-item-v4">
                                                <label>Created at</label>
                                                <span>{formatDateTimeIST(details.created_at)}</span>
                                            </div>
                                        )}
                                        {details.updated_at && (
                                            <div className="info-item-v4">
                                                <label>Updated at</label>
                                                <span>{formatDateTimeIST(details.updated_at)}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Assignments</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Assigned RM</label>
                                        <span>{getRMUsername(details.rm_id, details.rm_name)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Assigned OP</label>
                                        <span>{getOPUsername(details.op_id, details.op_name)}</span>
                                    </div>
                                </div>
                            </div>

                                    <div className="details-footer-v4">
                                        <div className="status-info-v4">
                                            <label>Record Status</label>
                                            <div className={`status-display-v4 ${details.is_active ? 'active' : 'inactive'}`}>
                                                {details.is_active ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                                                <span>{details.is_active ? 'ACTIVE' : 'INACTIVE'}</span>
                                            </div>
                                        </div>
                                        <button 
                                            className={`btn-status-toggle-v4 ${details.is_active ? 'deactivate' : 'activate'}`}
                                            onClick={handleToggleStatus}
                                            disabled={statusUpdating}
                                        >
                                            {statusUpdating ? <Loader2 className="spin" size={14} /> : null}
                                            {statusUpdating ? 'Updating...' : details.is_active ? 'Deactivate Record' : 'Activate Record'}
                                        </button>
                                    </div>
                                </>
                            ) : (
                                <div className="payments-tab-content">
                                    <div className="payments-header-v4">
                                        <h4 className="section-title-v4">Payment History</h4>
                                        <button 
                                            className="btn-record-payment-v4"
                                            onClick={() => setShowAddPayment(true)}
                                        >
                                            Record Payment
                                        </button>
                                    </div>

                                    {paymentsLoading ? (
                                        <div className="tab-loading-v4">
                                            <Loader2 className="spin" size={24} />
                                            <p>Loading payments...</p>
                                        </div>
                                    ) : payments.length > 0 ? (
                                        <div className="payments-list-v4">
                                            {payments.map(p => (
                                                <div key={p.id} className="payment-card-v4">
                                                    <div className="payment-card-header">
                                                        <span className="payment-id">{p.id}</span>
                                                        <span className={`payment-status-badge ${p.payment_status?.toLowerCase()}`}>
                                                            {p.payment_status}
                                                        </span>
                                                    </div>
                                                    <div className="payment-card-body">
                                                        <div className="payment-row">
                                                            <label>Amount:</label>
                                                            <span className="amount">₹{p.paid_amount?.toLocaleString()}</span>
                                                        </div>
                                                        <div className="payment-row">
                                                            <label>Date:</label>
                                                            <span>{formatDateIST(p.payment_date)}</span>
                                                        </div>
                                                        <div className="payment-row">
                                                            <label>Mode:</label>
                                                            <span>{p.payment_mode || '-'}</span>
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <div className="no-payments-v4">
                                            <AlertCircle size={32} />
                                            <p>No payments found for this record.</p>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ) : null}
                </div>
            </div>

            {showAddPayment && (
                <AddPayment 
                    initialEntityId={recordId}
                    initialServiceType="INCOME_TAX"
                    onBack={() => {
                        setShowAddPayment(false);
                        fetchPayments();
                    }}
                />
            )}
        </div>
    );

    return typeof document !== 'undefined'
        ? createPortal(panel, document.body)
        : panel;
};

export default IncomeTaxDetails;

