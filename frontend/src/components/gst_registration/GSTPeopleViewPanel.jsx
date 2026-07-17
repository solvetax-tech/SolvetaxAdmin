import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, UserCircle, Briefcase, FileText, CheckCircle2, XCircle, AlertCircle, Loader2, User, Phone, Mail, Shield, Calendar } from 'lucide-react';
import api from '../../utils/api';

const GSTPeopleViewPanel = ({ isOpen, onClose, personId, onUpdate }) => {
    const [details, setDetails] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try { return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }); } catch { return dtStr; }
    };

    const fetchDetails = async () => {
        setLoading(true);
        setError(null);
        try {
            // Using dynamic_filter with person_id to ensure we get the full record
            const res = await api.get('/api/v1/gst-people/dynamic_filter', {
                params: {
                    person_id: personId,
                    limit: 1,
                    offset: 0
                }
            });
            
            const items = res.data?.data || res.data?.items || (Array.isArray(res.data) ? res.data : []);
            const fetchedData = items[0];
            
            if (!fetchedData) {
                throw new Error("No data found for this person");
            }
            
            setDetails(fetchedData);
        } catch (err) {
            console.error("Error fetching GST People details:", err);
            setError("Failed to load details. The record might not exist or the server is unreachable.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (isOpen && personId) {
            fetchDetails();
        } else {
            setDetails(null);
        }
    }, [isOpen, personId]);

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
                    <div className="header-icon-v4" style={{ background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--info)', borderColor: 'rgba(var(--info-rgb), 0.2)' }}>
                        <UserCircle size={24} />
                    </div>
                    <div className="header-text-v4">
                        <h3>GST Stakeholder Details</h3>
                        <p>{details?.full_name || 'Loading details...'}</p>
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
                            <button onClick={fetchDetails} className="btn-reset-v4" style={{ width: 'auto', padding: '8px 16px' }}>Retry</button>
                        </div>
                    ) : details ? (
                        <div className="details-container-v4">
                            <div className="details-section-v4">
                                <h4 className="section-title-v4" style={{ color: 'var(--info)' }}>Personal Identity</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Full Name</label>
                                        <span style={{ fontWeight: '700', color: 'var(--text-primary)' }}>{details.full_name || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Designation</label>
                                        <span className="status-pill-v4 status-filed" style={{ background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--info)', border: '1px solid rgba(var(--info-rgb), 0.2)' }}>
                                            {details.designation || '-'}
                                        </span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Person ID</label>
                                        <span className="mono-v4">{details.person_id || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>PAN Number</label>
                                        <span className="mono-v4">{details.pan || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Aadhaar Number</label>
                                        <span className="mono-v4">{details.aadhaar || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Linking & Access</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>GSTIN</label>
                                        <span className="mono-v4" style={{ color: 'var(--text-primary)' }}>{details.gstin || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Reg ID</label>
                                        <span className="mono-v4">{details.gst_registration_id || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Customer ID</label>
                                        <span className="mono-v4">{details.customer_id || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Primary Member</label>
                                        <span>{details.is_primary_customer ? '✅ Yes' : '❌ No'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Communication</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Mobile</label>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <Phone size={12} color="var(--text-muted)" />
                                            <span>{details.mobile || '-'}</span>
                                        </div>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Email Address</label>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <Mail size={12} color="var(--text-muted)" />
                                            <span style={{ fontSize: '13px' }}>{details.email || '-'}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">System Info</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Created At</label>
                                        <span>{formatDateTime(details.created_at)}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Last Updated</label>
                                        <span>{formatDateTime(details.updated_at)}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-footer-v4">
                                <div className="status-info-v4">
                                    <label>Account Status</label>
                                    <div className={`status-display-v4 ${details.is_active ? 'active' : 'inactive'}`}>
                                        {details.is_active ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                                        <span>{details.is_active ? 'ACTIVE RECORD' : 'INACTIVE RECORD'}</span>
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

export default GSTPeopleViewPanel;
