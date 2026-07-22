import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, FileText, CheckCircle2, XCircle, AlertCircle, Loader2 } from 'lucide-react';
import api from '../../utils/api';

/**
 * Read-only detail drawer for a single GST filing.
 *
 * Mirrors GSTRegistrationViewPanel: same drawer shell/classes, and it reads
 * through the list endpoint filtered by id because there is no per-filing GET.
 */
const GSTFilingViewPanel = ({ isOpen, onClose, recordId, configs }) => {
    const [details, setDetails] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const getStatusPill = (status) => {
        const s = (status || '').toUpperCase();
        if (s === 'FILED') return <span className="status-pill-v4 status-filed">Filed</span>;
        if (s === 'DATA_PENDING') return <span className="status-pill-v4 status-pending">Data Pending</span>;
        if (s === 'MISSED' || s === 'NOT_FILED') return <span className="status-pill-v4 status-error">{s.replace('_', ' ')}</span>;
        return <span className="status-pill-v4 status-default">{s ? s.replace(/_/g, ' ') : 'UNKNOWN'}</span>;
    };

    const getEmployeeName = (empId, icon) => {
        if (!empId) return 'Unassigned';
        const match = configs?.employees?.find((e) => Number(e.emp_id) === Number(empId));
        return match?.username ? `${icon} ${match.username}` : `${icon} ID: ${empId}`;
    };

    const getStateLabel = (value) => (
        configs?.states?.find((s) => s.value === value)?.display_name || value || '-'
    );

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try { return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }); } catch { return dtStr; }
    };

    useEffect(() => {
        if (isOpen && recordId) {
            fetchDetails();
        } else {
            setDetails(null);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch only when the target record changes
    }, [isOpen, recordId]);

    const fetchDetails = async () => {
        setLoading(true);
        setError(null);
        try {
            // No per-filing GET exists; the list endpoint filtered by id is the
            // same route GstFilingDocuments uses to resolve one filing.
            const res = await api.get('/api/v1/gst-filings/table/filings', {
                params: { id: recordId, limit: 1, offset: 0 },
            });

            const items = res.data?.data || res.data?.items || (Array.isArray(res.data) ? res.data : []);
            const fetchedData = items[0];

            if (!fetchedData) {
                throw new Error('No data found for this record');
            }

            setDetails(fetchedData);
        } catch (err) {
            console.error('Error fetching GST filing details:', err);
            setError('Failed to load details. The record might not exist or the server is unreachable.');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    const panel = (
        <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={onClose}>
            <div
                className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel"
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
            >
                <div className="drawer-header gst-reg-details-header">
                    <div className="header-icon-v4">
                        <FileText size={24} />
                    </div>
                    <div className="header-text-v4">
                        <h3>GST Filing Details</h3>
                        <div className="header-chips-v4">
                            <span className="badge-chip-v4">{details?.business_name || details?.gstin || 'Filing Metadata'}</span>
                            <span className="badge-chip-v4 id-chip-v4">ID: <span className="id-value-white">{details?.id || '-'}</span></span>
                        </div>
                    </div>
                    <button type="button" className="btn-drawer-close" onClick={onClose} aria-label="Close">
                        <X size={20} />
                    </button>
                </div>

                <div className="drawer-content gst-reg-details-scroll gst-reg-details-form drawer-body-v4">
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
                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Filing & Period</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Filing Period</label>
                                        <span className="mono-v4" style={{ color: 'var(--text-primary)' }}>{details.filing_period || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Category</label>
                                        <span>{details.filing_category || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Frequency</label>
                                        <span>{details.filing_frequency || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Taxpayer Type</label>
                                        <span>{details.taxpayer_type || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Status</label>
                                        <span>{getStatusPill(details.status)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Priority</label>
                                        <span>{details.priority || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Auto Generation</label>
                                        <span>{details.is_auto_enabled ? 'Enabled' : 'Disabled'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Rule 14A</label>
                                        <span>{details.rule14a ? 'Yes' : 'No'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Business & Identity</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>GSTIN</label>
                                        <span className="mono-v4" style={{ color: 'var(--text-primary)' }}>{details.gstin || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Customer ID</label>
                                        <span>{details.customer_id ?? '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>GST Registration ID</label>
                                        <span>{details.gst_registration_id ?? '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Business Name</label>
                                        <span>{details.business_name || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Business Type</label>
                                        <span>{details.business_type || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>State</label>
                                        <span>{getStateLabel(details.state)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Turnover</label>
                                        <span>{details.turnover_details || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Rent</label>
                                        <span>{details.rent ?? '-'}</span>
                                    </div>
                                    {details.business_description && (
                                        <div className="info-item-v4" style={{ gridColumn: 'span 2' }}>
                                            <label>Business Description</label>
                                            <span>{details.business_description}</span>
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Portal Credentials</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Username</label>
                                        <span>{details.username || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Password</label>
                                        <span>{details.password || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Email</label>
                                        <span>{details.email_id || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Assignments</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Assigned RM</label>
                                        <span>{getEmployeeName(details.rm_id, '👤')}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Assigned OP</label>
                                        <span>{getEmployeeName(details.op_id, '⚙️')}</span>
                                    </div>
                                </div>
                            </div>

                            {details.remarks && (
                                <div className="details-section-v4">
                                    <h4 className="section-title-v4">Remarks</h4>
                                    <div className="info-grid-v4">
                                        <div className="info-item-v4" style={{ gridColumn: 'span 2' }}>
                                            <span>{details.remarks}</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Timestamps</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Created At</label>
                                        <span>{formatDateTime(details.created_at)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Data Received At</label>
                                        <span>{formatDateTime(details.data_received_at)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Filed At</label>
                                        <span>{formatDateTime(details.filed_at)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Updated At</label>
                                        <span>{formatDateTime(details.updated_at)}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-footer-v4" style={{ marginTop: '20px' }}>
                                <div className="status-info-v4">
                                    <label>Record Status</label>
                                    <div className={`status-display-v4 ${details.is_active ? 'active' : 'inactive'}`}>
                                        {details.is_active ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                                        <span>{details.is_active ? 'ACTIVE' : 'INACTIVE'}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    );

    return typeof document !== 'undefined'
        ? createPortal(panel, document.body)
        : panel;
};

export default GSTFilingViewPanel;
