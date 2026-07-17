import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, UserCircle, Briefcase, FileText, CheckCircle2, XCircle, AlertCircle, Loader2 } from 'lucide-react';
import api from '../../utils/api';
import { getRmOpAssignmentVisibility } from '../../utils/rmOpAssignmentFields';

const GSTRegistrationViewPanel = ({ isOpen, onClose, recordId, configs, onUpdate, profileData }) => {
    const { showRmField, showOpField } = getRmOpAssignmentVisibility(profileData);
    const [details, setDetails] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    
    const getStatusPill = (status) => {
        const s = (status || '').toUpperCase();
        if (s === 'APPROVED') return <span className="status-pill-v4 status-filed">Approved</span>;
        if (s === 'SUSPENDED') return <span className="status-pill-v4 status-pending">Suspended</span>;
        if (s === 'CANCELLED') return <span className="status-pill-v4 status-error">Cancelled</span>;
        if (s === 'DRAFT') return <span className="status-pill-v4 status-default">Draft</span>;
        return <span className="status-pill-v4 status-default">{s || 'UNKNOWN'}</span>;
    };

    const getRMUsername = (record) => {
        if (!record) return 'Unassigned';
        if (record.rm_name) return `👤 ${record.rm_name}`;
        if (record.rm_username) return `👤 ${record.rm_username}`;
        const id = record.rm_id;
        if (!id) return 'Unassigned';
        if (typeof id === 'string' && Number.isNaN(parseInt(id, 10))) return `👤 ${id}`;
        if (configs?.activeRMs?.includes(id) || configs?.activeRMs?.includes(String(id))) return `👤 ${id}`;
        return `👤 ID: ${id}`;
    };

    const getOPUsername = (record) => {
        if (!record) return 'Unassigned';
        if (record.created_by_name) return `⚙️ ${record.created_by_name}`;
        if (record.op_name) return `⚙️ ${record.op_name}`;
        if (record.op_username) return `⚙️ ${record.op_username}`;
        const id = record.created_by;
        if (!id) return 'Unassigned';
        if (typeof id === 'string' && Number.isNaN(parseInt(id, 10))) return `⚙️ ${id}`;
        if (configs?.activeOps?.includes(id) || configs?.activeOps?.includes(String(id))) return `⚙️ ${id}`;
        return `⚙️ ID: ${id}`;
    };

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
    }, [isOpen, recordId]);

    const fetchDetails = async () => {
        setLoading(true);
        setError(null);
        try {
            // Using dynamic_filter with id to ensure we get the full record, matching the backend pattern
            const res = await api.get('/api/v1/gst-registrations/dynamic_filter', {
                params: {
                    id: recordId,
                    gst_registration_id: recordId,
                    limit: 1,
                    offset: 0
                }
            });
            
            const items = res.data?.data || res.data?.items || (Array.isArray(res.data) ? res.data : []);
            const fetchedData = items[0];
            
            if (!fetchedData) {
                throw new Error("No data found for this record");
            }
            
            setDetails(fetchedData);
        } catch (err) {
            console.error("Error fetching GST Reg details:", err);
            setError("Failed to load details. The record might not exist or the server is unreachable.");
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    const panel = (
        <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={onClose}>
            <div
                className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel"
                onClick={e => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
            >
                <div className="drawer-header gst-reg-details-header">
                    <div className="header-icon-v4">
                        <Briefcase size={24} />
                    </div>
                    <div className="header-text-v4">
                        <h3>GST Registration Details</h3>
                        <div className="header-chips-v4">
                            <span className="badge-chip-v4">{details?.business_name || details?.legal_name || 'Business Metadata'}</span>
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
                                <h4 className="section-title-v4">Business & Identity</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>GSTIN</label>
                                        <span className="mono-v4" style={{ color: 'var(--text-primary)' }}>{details.gstin || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>PAN Number</label>
                                        <span className="mono-v4">{details.pan || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Customer ID</label>
                                        <span>{details.customer_id || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Client Name</label>
                                        <span>{details.client_name || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Business Name</label>
                                        <span>{details.business_name || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Username</label>
                                        <span>{details.username || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Password</label>
                                        <span>{details.password || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Registration Specifications</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Reg Type</label>
                                        <span>{details.registration_type || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Ownership Cat</label>
                                        <span>{details.ownership_category || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Business Type</label>
                                        <span>{details.business_type || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>State</label>
                                        <span>{details.state || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>City</label>
                                        <span>{details.city || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Turnover</label>
                                        <span>{details.turnover_details || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Language</label>
                                        <span>{details.language || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Filing Status</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Status</label>
                                        <span>{getStatusPill(details.registration_status)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>RCM Applicable</label>
                                        <span>{details.is_rcm_applicable ? 'Yes' : 'No'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Filing Needed</label>
                                        <span>{details.is_filing_needed ? 'Yes' : 'No'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Filing Preference</label>
                                        <span>{details.filing_preference || '-'}</span>
                                    </div>
                                    {details.registration_status === 'SUSPENDED' && (
                                        <div className="info-item-v4" style={{ gridColumn: 'span 2' }}>
                                            <label>Suspension Reason</label>
                                            <span style={{ color: 'var(--danger)' }}>{details.suspension_reason || '-'}</span>
                                        </div>
                                    )}
                                    {details.registration_status === 'CANCELLED' && (
                                        <div className="info-item-v4" style={{ gridColumn: 'span 2' }}>
                                            <label>Cancellation Reason</label>
                                            <span style={{ color: 'var(--danger)' }}>{details.cancellation_reason || '-'}</span>
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Contact Information</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Mobile</label>
                                        <span>{details.mobile || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Email</label>
                                        <span>{details.email || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Secondary Email</label>
                                        <span>{details.secondary_email || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Assignments & Referral</h4>
                                <div className="info-grid-v4">
                                    {showRmField && (
                                    <div className="info-item-v4">
                                        <label>Assigned RM</label>
                                        <span>{getRMUsername(details)}</span>
                                    </div>
                                    )}
                                    {showOpField && (
                                    <div className="info-item-v4">
                                        <label>Assigned OP</label>
                                        <span>{getOPUsername(details)}</span>
                                    </div>
                                    )}
                                    <div className="info-item-v4">
                                        <label>Referral Phone</label>
                                        <span>{details.referral_phone_number || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Timestamps</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Created At</label>
                                        <span>{formatDateTime(details.created_at)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Approved At</label>
                                        <span>{formatDateTime(details.approved_at)}</span>
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

export default GSTRegistrationViewPanel;
