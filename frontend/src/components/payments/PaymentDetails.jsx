import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
    Loader2,
    ArrowLeft,
    CreditCard,
    AlertCircle,
    CheckCircle2,
    Tag,
    IndianRupee,
    Wallet,
    MessageSquare,
    Edit2,
    Trash2,
    X,
    Calendar,
    Hash
} from 'lucide-react';
import api from '../../utils/api';
import './PaymentDetails.css';
import '../common/AppSideDrawer.css';
import {
    AppDrawerModalFooter,
    AppDrawerBtnDelete,
} from '../common/AppDrawerEditFooter';

const PaymentDetails = ({ onLogout, selectedId, onClose }) => {
    const { paymentId: paramId } = useParams();
    const paymentId = selectedId || paramId;
    const navigate = useNavigate();

    const [payment, setPayment] = useState(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [message, setMessage] = useState({ type: '', text: '' });
    const [isAdmin, setIsAdmin] = useState(false);
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteConfirmText, setDeleteConfirmText] = useState('');

    // Helper to extract user-friendly error message from structured backend responses
    const getErrorMessage = (err, fallback = "An unexpected error occurred.") => {
        const detail = err.response?.data?.detail;
        if (typeof detail === 'string') return detail;
        if (detail?.error?.message) return detail.error.message;
        if (detail?.message) return detail.message;
        if (Array.isArray(detail)) {
            return detail.map(d => d.msg).join(', ') || fallback;
        }
        return err.response?.data?.error || err.message || fallback;
    };

    const [formData, setFormData] = useState({
        discount: 0,
        paid_amount: 0,
        remarks: ''
    });
    const editMode = false;

    const fetchPaymentDetails = useCallback(async () => {
        if (!paymentId) return;
        setLoading(true);
        setError(null);
        try {
            const response = await api.get(`/api/v1/payments/dynamic_filter?payment_id=${paymentId}&include_inactive=true`);
            const paymentData = response.data.data?.[0];

            if (!paymentData) {
                throw new Error("Payment record not found.");
            }

            setPayment(paymentData);
            setFormData({
                discount: paymentData.discount || 0,
                paid_amount: paymentData.paid_amount || 0,
                remarks: paymentData.remarks || ''
            });
        } catch (err) {
            console.error("Failed to fetch payment details:", err);
            setError(getErrorMessage(err, "Failed to load payment details."));
        } finally {
            setLoading(false);
        }
    }, [paymentId]);

    const checkAdminStatus = useCallback(async () => {
        try {
            const token = localStorage.getItem('session_token');
            if (!token) return;

            const payload = JSON.parse(window.atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
            const selfEmpId = payload.sub;

            if (selfEmpId) {
                const response = await api.get(`/api/v1/employees/employee/${selfEmpId}`);
                setIsAdmin(response.data?.role === 'ADMIN');
            }
        } catch (err) {
            console.error('Failed to check admin status:', err);
        }
    }, []);

    useEffect(() => {
        fetchPaymentDetails();
        checkAdminStatus();
    }, [fetchPaymentDetails, checkAdminStatus]);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleSave = (event) => {
        if (event?.preventDefault) event.preventDefault();
    };

    const handleDelete = async () => {
        setSubmitting(true);
        setMessage({ type: '', text: '' });

        try {
            const isFiling = payment?.entity_type === 'GST_FILING';
            const isITR = payment?.entity_type === 'INCOME_TAX';
            const endpoint = isFiling ? `/api/v1/filing-payments/${paymentId}/soft_delete` : 
                             isITR ? `/api/v1/income-tax-payments/${paymentId}/soft_delete` :
                             `/api/v1/payments/${paymentId}/soft_delete`;

            await api.delete(endpoint);
            setMessage({ type: 'success', text: 'Payment deleted successfully.' });
            setShowDeleteModal(false);
            fetchPaymentDetails(); // Refresh to show updated status
        } catch (err) {
            console.error("Delete failed:", err);
            setMessage({ type: 'error', text: getErrorMessage(err, "Failed to delete payment.") });
            setSubmitting(false);
            setShowDeleteModal(false);
        }
    };

    const handleActivate = async () => {
        setSubmitting(true);
        setMessage({ type: '', text: '' });

        try {
            const isFiling = payment?.entity_type === 'GST_FILING';
            const isITR = payment?.entity_type === 'INCOME_TAX';
            const endpoint = isFiling ? `/api/v1/filing-payments/${paymentId}/activate` : 
                             isITR ? `/api/v1/income-tax-payments/${paymentId}/activate` :
                             `/api/v1/payments/${paymentId}/activate`;

            await api.post(endpoint);
            setMessage({ type: 'success', text: 'Payment activated successfully.' });
            fetchPaymentDetails();
        } catch (err) {
            console.error("Activation failed:", err);
            setMessage({ type: 'error', text: getErrorMessage(err, "Failed to activate payment.") });
        } finally {
            setSubmitting(false);
        }
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try {
            return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
        } catch {
            return dtStr;
        }
    };

    const handleClose = () => {
        if (onClose) onClose();
        else navigate('/dashboard?tab=payments');
    };

    const adminFooter = isAdmin && payment ? (
        <AppDrawerModalFooter
            leading={
                payment.is_active === false ? (
                    <button
                        type="button"
                        className="app-drawer-btn-save glow-green"
                        onClick={handleActivate}
                        disabled={submitting}
                    >
                        {submitting ? <Loader2 size={14} className="spin" /> : null}
                        Activate Payment
                    </button>
                ) : (
                    <AppDrawerBtnDelete
                        onClick={() => {
                            setDeleteConfirmText('');
                            setShowDeleteModal(true);
                        }}
                        disabled={submitting}
                        label="Delete Payment"
                    />
                )
            }
        />
    ) : null;

    const drawerShell = (bodyContent, footer = null) => (
        <>
            <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={handleClose}>
                <div
                    className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel payment-details-drawer view-mode"
                    onClick={(e) => e.stopPropagation()}
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="payment-details-drawer-title"
                >
                    <div className="drawer-header">
                        <div>
                            <h2 id="payment-details-drawer-title" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                                Payment Details
                            </h2>
                            <p style={{ margin: '6px 0 0', fontSize: '13px', color: 'var(--text-primary)' }}>
                                {payment?.id ?? paymentId ?? '—'}
                                {payment?.customer_id != null ? ` · Customer ${payment.customer_id}` : ''}
                            </p>
                        </div>
                        <button type="button" className="btn-drawer-close" onClick={handleClose} aria-label="Close">
                            <X size={20} />
                        </button>
                    </div>
                    {bodyContent}
                    {footer}
                </div>
            </div>

            {showDeleteModal && (
                <div className="premium-filter-overlay show payment-delete-confirm-overlay" onClick={() => setShowDeleteModal(false)}>
                    <div className="premium-edit-modal-v4 delete-confirm-modal destructive-v4" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '400px' }}>
                        <div className="edit-modal-header-v4">
                            <div className="header-brand-icon-v4">
                                <AlertCircle size={24} />
                            </div>
                            <div className="header-text-content-v4">
                                <h3>Confirm Delete</h3>
                                <p>Action cannot be undone</p>
                            </div>
                        </div>
                        <div className="edit-modal-body-v4">
                            <p style={{ color: 'var(--text-muted)', marginBottom: '20px', fontSize: '14px' }}>
                                To confirm deletion, please type <b style={{ color: 'var(--text-primary)' }}>DELETE</b> in the input field below.
                            </p>
                            <div className="input-group-v4">
                                <div className="input-wrapper-v4">
                                    <input
                                        type="text"
                                        placeholder="Type DELETE here..."
                                        value={deleteConfirmText}
                                        onChange={(e) => setDeleteConfirmText(e.target.value)}
                                        autoFocus
                                    />
                                </div>
                            </div>
                        </div>
                        <div className="edit-modal-footer-v4">
                            <button
                                className="btn-cancel-v4"
                                onClick={() => setShowDeleteModal(false)}
                                disabled={submitting}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn-delete-v4"
                                style={{
                                    background: deleteConfirmText === 'DELETE' ? '#ef4444' : 'rgba(239, 68, 68, 0.1)',
                                    color: deleteConfirmText === 'DELETE' ? 'var(--text-primary)' : 'rgba(239, 68, 68, 0.5)',
                                    opacity: deleteConfirmText === 'DELETE' ? 1 : 0.6,
                                    cursor: deleteConfirmText === 'DELETE' ? 'pointer' : 'not-allowed',
                                    border: 'none',
                                }}
                                disabled={deleteConfirmText !== 'DELETE' || submitting}
                                onClick={handleDelete}
                            >
                                {submitting ? 'Deleting...' : 'Confirm Delete'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );

    const paymentForm = (
        <div className="drawer-content gst-reg-details-scroll">
            {message.text && (
                <div
                    className={`modal-global-error-banner ${message.type === 'success' ? 'success-banner' : ''}`}
                    style={{
                        marginBottom: '20px',
                        background: message.type === 'success' ? 'rgba(46, 184, 122, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                        color: message.type === 'success' ? '#2eb87a' : '#ef4444',
                    }}
                >
                    <span>{message.text}</span>
                </div>
            )}

            <form id="paymentDetailsForm" onSubmit={handleSave} className="premium-edit-grid-v4 payment-details-grid">
                <div className="input-group-v4">
                    <label><Hash size={14} /> Payment ID</label>
                    <div className="input-wrapper-v4">
                        <input type="text" value={payment?.id ?? ''} disabled />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><Tag size={14} /> Entity ID</label>
                    <div className="input-wrapper-v4">
                        <input type="text" value={payment?.entity_id ?? ''} disabled />
                    </div>
                </div>

                <div className="input-group-v4 full">
                    <label><CreditCard size={14} /> Transaction ID</label>
                    <div className="input-wrapper-v4">
                        <input type="text" value={payment?.transaction_id || 'N/A'} disabled />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><IndianRupee size={14} /> Base Amount</label>
                    <div className="input-wrapper-v4">
                        <input type="text" value={payment?.amount ?? ''} disabled />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><IndianRupee size={14} /> Net Amount</label>
                    <div className="input-wrapper-v4">
                        <input type="text" value={payment?.net_amount ?? ''} disabled style={{ color: '#2eb87a', fontWeight: '700' }} />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><Tag size={14} /> Discount</label>
                    <div className="input-wrapper-v4">
                        <input
                            type="number"
                            name="discount"
                            value={formData.discount}
                            onChange={handleChange}
                            disabled={!editMode}
                            step="0.01"
                            min="0"
                        />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><Wallet size={14} /> Paid Amount</label>
                    <div className="input-wrapper-v4">
                        <input
                            type="number"
                            name="paid_amount"
                            value={formData.paid_amount}
                            onChange={handleChange}
                            disabled={!editMode}
                            step="0.01"
                            min="0"
                            style={!editMode ? { color: payment?.is_active === false ? '#ef4444' : '#2eb87a', fontWeight: '700' } : {}}
                        />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><CheckCircle2 size={14} /> Payment Status</label>
                    <div className="input-wrapper-v4">
                        <input
                            type="text"
                            value={payment?.is_active === false ? 'DELETED' : (payment?.payment_status ?? '')}
                            disabled
                            className={payment?.is_active === false ? 'status-text-failed' : `status-text-${(payment?.payment_status || '').toLowerCase()}`}
                        />
                    </div>
                </div>

                <div className="input-group-v4">
                    <label><Calendar size={14} /> Created At</label>
                    <div className="input-wrapper-v4">
                        <input type="text" value={formatDateTime(payment?.created_at)} disabled />
                    </div>
                </div>

                <div className="input-group-v4 full">
                    <label><MessageSquare size={14} /> Remarks</label>
                    <div className="input-wrapper-v4">
                        <textarea
                            name="remarks"
                            value={formData.remarks}
                            onChange={handleChange}
                            disabled={!editMode}
                            rows="3"
                            placeholder="Add any internal remarks here..."
                        />
                    </div>
                </div>
            </form>
        </div>
    );

    if (loading) {
        return drawerShell(
            <div className="drawer-content gst-reg-details-scroll">
                <div className="modal-inner-loading-overlay">
                    <Loader2 size={40} className="spin" />
                    <p>Loading payment details...</p>
                </div>
            </div>,
        );
    }

    if (error) {
        return drawerShell(
            <div className="drawer-content gst-reg-details-scroll payment-drawer-error-state">
                <AlertCircle size={48} color="#ef4444" />
                <h2>Error Loading Payment</h2>
                <p>{error}</p>
            </div>,
        );
    }

    return drawerShell(paymentForm, adminFooter);
};

export default PaymentDetails;
