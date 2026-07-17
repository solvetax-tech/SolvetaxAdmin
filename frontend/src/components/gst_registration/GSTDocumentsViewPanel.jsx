import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, FileText, CheckCircle2, XCircle, AlertCircle, Loader2, Download, ExternalLink, Calendar, User, Hash, ShieldCheck } from 'lucide-react';
import api from '../../utils/api';

const GSTDocumentsViewPanel = ({ isOpen, onClose, documentId, documentData, onUpdate }) => {
    const [details, setDetails] = useState(documentData || null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try { return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }); } catch { return dtStr; }
    };

    const fetchDetails = async () => {
        if (documentData) {
            setDetails(documentData);
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const res = await api.get('/api/v1/gst-documents/dynamic_filter', {
                params: {
                    id: documentId,
                    limit: 1,
                    offset: 0
                }
            });
            
            const items = res.data?.data || res.data?.items || (Array.isArray(res.data) ? res.data : []);
            const fetchedData = items[0];
            
            if (!fetchedData) {
                const res2 = await api.get('/api/v1/gst-documents/dynamic_filter', {
                    params: {
                        document_id: documentId,
                        limit: 1,
                        offset: 0
                    }
                });
                const items2 = res2.data?.data || res2.data?.items || (Array.isArray(res2.data) ? res2.data : []);
                if (items2[0]) {
                    setDetails(items2[0]);
                } else {
                    throw new Error("No data found for this document");
                }
            } else {
                setDetails(fetchedData);
            }
        } catch (err) {
            console.error("Error fetching GST Document details:", err);
            setError("Failed to load details. The record might not exist or the server is unreachable.");
        } finally {
            setLoading(false);
        }
    };

    const handleViewFile = async () => {
        if (!details?.document_url) return;
        try {
            const response = await api.get(`/api/v1/gst-blob/view?blob_url=${encodeURIComponent(details.document_url)}`);
            if (response.data?.view_url) {
                window.open(response.data.view_url, '_blank');
            }
        } catch (err) {
            alert("Failed to generate secure view link.");
        }
    };

    const handleDownloadFile = async () => {
        if (!details?.document_url) return;
        try {
            const response = await api.get(`/api/v1/gst-blob/download?blob_url=${encodeURIComponent(details.document_url)}`);
            if (response.data?.download_url) {
                const link = document.createElement('a');
                link.href = response.data.download_url;
                link.download = `doc_${details.document_id}`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            }
        } catch (err) {
            alert("Failed to generate secure download link.");
        }
    };

    useEffect(() => {
        if (isOpen && documentId) {
            fetchDetails();
        } else {
            setDetails(null);
        }
    }, [isOpen, documentId]);

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
                    <div className="header-icon-v4" style={{ background: 'rgba(var(--success-rgb), 0.1)', color: 'var(--accent)', borderColor: 'rgba(var(--success-rgb), 0.2)' }}>
                        <FileText size={24} />
                    </div>
                    <div className="header-text-v4">
                        <h3>Compliance Document</h3>
                        <p>{details?.document_type || 'Loading details...'}</p>
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
                                <h4 className="section-title-v4" style={{ color: 'var(--accent)' }}>Core Metadata</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Document Type</label>
                                        <span style={{ fontWeight: '700', color: 'var(--text-primary)' }}>{details.document_type || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Document ID</label>
                                        <span className="mono-v4">{details.document_id || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>GSTIN</label>
                                        <span className="mono-v4" style={{ color: 'var(--text-primary)' }}>{details.gstin || '-'}</span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Person ID</label>
                                        <span className="mono-v4">{details.person_id || '-'}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">Verification Info</h4>
                                <div className="info-grid-v4">
                                    <div className="info-item-v4">
                                        <label>Status</label>
                                        <span className={`status-pill-v4 ${details.verified ? 'status-filed' : 'status-pending'}`}>
                                            {details.verified ? 'VERIFIED' : 'PENDING VERIFICATION'}
                                        </span>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Verified By</label>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <User size={12} color="var(--text-muted)" />
                                            <span>{details.verified_by_name || 'N/A'}</span>
                                        </div>
                                    </div>
                                    <div className="info-item-v4">
                                        <label>Verification Date</label>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <Calendar size={12} color="var(--text-muted)" />
                                            <span>{formatDateTime(details.verified_at)}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="details-section-v4">
                                <h4 className="section-title-v4">File Actions</h4>
                                <div style={{ display: 'flex', gap: '12px' }}>
                                    <button onClick={handleViewFile} className="btn-primary-action" style={{ background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--info)', border: '1px solid rgba(var(--info-rgb), 0.2)' }}>
                                        <ExternalLink size={14} />
                                        <span>Open Secure Link</span>
                                    </button>
                                    <button onClick={handleDownloadFile} className="btn-primary-action" style={{ background: 'rgba(var(--success-rgb), 0.1)', color: 'var(--accent)', border: '1px solid rgba(var(--success-rgb), 0.2)' }}>
                                        <Download size={14} />
                                        <span>Download File</span>
                                    </button>
                                </div>
                            </div>

                            <div className="details-footer-v4">
                                <div className="status-info-v4">
                                    <label>Record Status</label>
                                    <div className={`status-display-v4 ${details.is_active ? 'active' : 'inactive'}`}>
                                        {details.is_active ? <ShieldCheck size={16} /> : <AlertCircle size={16} />}
                                        <span>{details.is_active ? 'ACTIVE DOCUMENT' : 'INACTIVE DOCUMENT'}</span>
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

export default GSTDocumentsViewPanel;
