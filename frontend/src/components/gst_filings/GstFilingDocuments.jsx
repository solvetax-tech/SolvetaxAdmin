import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import api from '../../utils/api';
import {
    appendDocumentFilterRulesToParams,
} from '../../utils/gstFilterRulesConstants';
import {
    Plus,
    X,
    Search,
    ArrowRight,
    CheckCircle2,
    AlertCircle,
    ChevronDown,
    Loader2,
    ShieldCheck,
    Files,
    ExternalLink,
    FilePlus
} from 'lucide-react';
import { TableSkeleton } from './gst_filings';
import './GstFilingDocuments.css';
import FormCustomSelect from '../common/FormCustomSelect';
import AddDocumentLinkModal from './AddDocumentLinkModal';

const GstFilingDocuments = ({ 
    filters, 
    configs, 
    setAppliedDocFilters, 
    docFilterInputs, 
    setDocFilterInputs, 
    rowsPerPage, 
    setError, 
    showCreateDocModal,
    setShowCreateDocModal,
    // Seed from the GST Filings row action ({ gst_filing_id, gstin }), cleared once applied
    createDocPreset = null,
    onCreateDocPresetApplied,
    // Hoisted State
    setCurrentDocsPage,
    currentDocsPage,
    setDocsHasMore,
    docsHasMore,
    docsLoading,
    setDocsLoading
}) => {
    const [docsData, setDocsData] = useState([]);

    // --- Filter Summary Helpers ---
    const getFilterLabel = (key, value) => {
        if (!value) return null;
        if (['document_filter_rules', 'document_filter_match'].includes(key)) return null;
        switch (key) {
            case 'gst_filing_id': return { label: 'Filing ID', value: value };
            case 'gstin': return { label: 'GSTIN', value: value };
            case 'verified_by': {
                const emp = configs?.employees?.find(e => String(e.emp_id) === String(value));
                return { label: 'Auditor', value: emp ? emp.username : value };
            }
            case 'created_from': return { label: 'From', value: value };
            case 'created_to': return { label: 'To', value: value };
            default: return null;
        }
    };

    const handleClearIndividualFilter = (key) => {
        const nextFilters = { ...filters, [key]: '' };
        setAppliedDocFilters(nextFilters);
        setDocFilterInputs({ ...docFilterInputs, [key]: '' });
        setCurrentDocsPage(1);
    };

    const handleClearAllFilters = () => {
        const reset = {
            gstin: '',
            gst_filing_id: '',
            verified_by: '',
            created_from: '',
            created_to: '',
            document_filter_match: 'AND',
            document_filter_rules: [{ field: '', value: '' }],
        };
        setAppliedDocFilters(reset);
        setDocFilterInputs(reset);
        setCurrentDocsPage(1);
    };

    const activeFilters = Object.entries(filters).filter(([k, v]) => {
        if (['document_filter_rules', 'document_filter_match'].includes(k)) return false;
        return !!v;
    }).map(([k]) => k);

    // 🔥 Verification Workflow State
    const [confirmDocId, setConfirmDocId] = useState(null);
    const [manualVerifyMessage, setManualVerifyMessage] = useState(null);
    const [isVerifying, setIsVerifying] = useState(false);
    const [successConfig, setSuccessConfig] = useState(null); // { message: '', subMessage: '' }



    const fetchFilingDocuments = useCallback(async () => {
        setDocsLoading(true);
        try {
            const params = new URLSearchParams();
            
            if (filters.gstin) params.append('gstin', filters.gstin);
            if (filters.gst_filing_id) params.append('gst_filing_id', filters.gst_filing_id);
            if (filters.verified_by) params.append('verified_by', filters.verified_by);
            if (filters.created_from) params.append('created_from', filters.created_from);
            if (filters.created_to) params.append('created_to', filters.created_to);
            appendDocumentFilterRulesToParams(
                params,
                filters.document_filter_match,
                filters.document_filter_rules,
            );

            params.append('offset', (currentDocsPage - 1) * rowsPerPage);
            params.append('limit', rowsPerPage);

            const response = await api.get(`/api/v1/gst-filings-docs/gst-filing-documents/filter?${params.toString()}`);
            const result = response.data;

            setDocsData(result.data || []);
            setDocsHasMore((result.data || []).length >= rowsPerPage);
        } catch (err) {
            console.error("Error fetching documents:", err);
            setError("Failed to load documents.");
        } finally {
            setDocsLoading(false);
        }
    }, [filters, currentDocsPage, rowsPerPage, setError, setDocsLoading, setDocsHasMore]);

    useEffect(() => {
        fetchFilingDocuments();
    }, [fetchFilingDocuments]);

    const handleVerifyDocument = async (docId) => {
        try {
            await api.patch(`/api/v1/gst-filings-docs/${docId}`, { verified: true });
            fetchFilingDocuments();
        } catch (err) {
            console.error("Error verifying document:", err);
            setError("Failed to verify document.");
        }
    };


    const GstDocTableSkeleton = () => (
        <>
            {[...Array(12)].map((_, i) => (
                <div key={`skeleton-${i}`} className="filings-ledger-row filings-docs-ledger-grid-template filings-ledger-skeleton-row">
                    <div className="filings-ledger-cell filings-ledger-sticky-id filings-docs-ledger-sticky-col-1">
                        <div className="filings-ledger-skeleton-bar" style={{ width: '30px' }} />
                    </div>
                    <div className="filings-ledger-cell filings-ledger-sticky-id filings-docs-ledger-sticky-col-2">
                        <div className="filings-ledger-skeleton-bar" style={{ width: '40px' }} />
                    </div>
                    <div className="filings-ledger-cell filings-docs-col-3"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-4"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-5"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-6"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-7"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-8"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-9"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-10"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell filings-docs-col-11"><div className="filings-ledger-skeleton-bar" /></div>
                </div>
            ))}
        </>
    );

    return (
        <div className="gst-documents-module">
            <div className="filings-docs-scroll-root">
                <div className="filings-docs-inner-wrapper">
                    <div className="filings-ledger-header filings-docs-ledger-grid-template">
                        <div className="filings-ledger-header-cell filings-ledger-sticky-id filings-docs-ledger-sticky-col-1">Doc ID</div>
                        <div className="filings-ledger-header-cell filings-ledger-sticky-id filings-docs-ledger-sticky-col-2">Filing ID</div>
                        <div className="filings-ledger-header-cell filings-docs-col-3">GSTIN</div>
                        <div className="filings-ledger-header-cell filings-docs-col-4">Period</div>
                        <div className="filings-ledger-header-cell filings-docs-col-5">Type</div>
                        <div className="filings-ledger-header-cell filings-docs-col-6">Sheet Link</div>
                        <div className="filings-ledger-header-cell filings-docs-col-7">Remarks</div>
                        <div className="filings-ledger-header-cell filings-docs-col-8">Verification Status</div>
                        <div className="filings-ledger-header-cell filings-docs-col-9">Verified By</div>
                        <div className="filings-ledger-header-cell filings-docs-col-10">Verified At</div>
                        <div className="filings-ledger-header-cell filings-docs-col-11">Action</div>
                    </div>

                    <div className="filings-ledger-body">
                        {docsLoading ? (
                            <GstDocTableSkeleton />
                        ) : docsData.length > 0 ? (
                            docsData.map((doc) => (
                                <div key={doc.document_id} className="filings-ledger-row filings-docs-ledger-grid-template">
                                    <div className="filings-ledger-cell filings-ledger-sticky-id filings-docs-ledger-sticky-col-1">
                                        <span className="filings-ledger-id-text">{doc.document_id}</span>
                                    </div>
                                    <div className="filings-ledger-cell filings-ledger-sticky-id filings-docs-ledger-sticky-col-2">
                                        <span className="filings-ledger-id-text" style={{ fontWeight: '700' }}>{doc.gst_filing_id}</span>
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-3" style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontVariantNumeric: 'tabular-nums' }}>
                                        {doc.gstin || '-'}
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-4">
                                        <div className="period-tag small">{doc.filing_period || '-'}</div>
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-5">
                                        <span className="doc-type-badge">{doc.document_type}</span>
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-6">
                                        <a href={doc.document_url} target="_blank" rel="noopener noreferrer" className="doc-external-link">
                                            <ExternalLink size={12} />
                                            View
                                        </a>
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-7" style={{ fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                        {doc.remarks || '-'}
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-8">
                                        {doc.verified ? (
                                            <div className="status-badge-v4 completed" style={{ minWidth: '100px' }}>
                                                <CheckCircle2 size={10} style={{ marginRight: '4px' }} />
                                                Verified
                                            </div>
                                        ) : (
                                            <div className="status-badge-v4 overdue" style={{ minWidth: '100px' }}>
                                                Not Verified
                                            </div>
                                        )}
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-9" style={{ fontSize: '11px' }}>
                                        {doc.verified ? (doc.verified_by_name || '-') : '-'}
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-10" style={{ fontSize: '10px', opacity: 0.7 }}>
                                        {doc.verified && doc.updated_at ? (
                                            (() => {
                                                const date = new Date(doc.updated_at);
                                                const d = String(date.getDate()).padStart(2, '0');
                                                const m = String(date.getMonth() + 1).padStart(2, '0');
                                                const y = date.getFullYear();
                                                return `${d}/${m}/${y}`;
                                            })()
                                        ) : '-'}
                                    </div>
                                    <div className="filings-ledger-cell filings-docs-col-11">
                                        {!doc.verified ? (
                                            <button
                                                className="status-badge-v4"
                                                style={{ cursor: 'pointer', border: '1px solid rgba(var(--warning-rgb),0.32)', minWidth: '85px', fontSize: '9px', padding: '6px 10px', background: 'rgba(var(--warning-rgb),0.14)', color: 'var(--warning)', fontWeight: '800', borderRadius: '6px' }}
                                                onClick={() => setConfirmDocId(doc.document_id)}
                                            >
                                                Mark as Verified
                                            </button>
                                        ) : (
                                            <div className="status-badge-v4" style={{ cursor: 'not-allowed', border: 'none', minWidth: '85px', fontSize: '9px', padding: '6px 10px', background: 'rgba(var(--fg-rgb),0.05)', color: 'var(--text-primary)', fontWeight: '800', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                                VERIFIED
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))
                    ) : (
                        <div className="filings-ledger-empty-container">
                            <Files size={48} opacity={0.2} />
                            <span className="filings-ledger-empty-title">No document links found</span>
                            <span className="filings-ledger-empty-text">Try adding a new document link or adjusting filters</span>
                        </div>
                    )}
                    </div>
                </div>
            </div>

            <AddDocumentLinkModal
                isOpen={showCreateDocModal}
                onClose={() => setShowCreateDocModal(false)}
                presetFilingId={createDocPreset?.gst_filing_id || null}
                presetGstin={createDocPreset?.gstin || ''}
                onCreated={({ filingId }) => {
                    onCreateDocPresetApplied?.();
                    setSuccessConfig({
                        message: "Document Linked Successfully",
                        subMessage: `Linked to GST Filing ID ${filingId}`,
                    });
                    setTimeout(() => setSuccessConfig(null), 3000);
                    fetchFilingDocuments();
                }}
            />
            {/* Verification Confirmation Modal */}
            {confirmDocId && createPortal(
                <div className="gst-modal-overlay-v4" style={{ zIndex: 4000 }}>
                    <div className="gst-modal-card-v4" style={{ maxWidth: '400px', padding: '32px' }}>
                        {!manualVerifyMessage ? (
                            <div style={{ textAlign: 'center' }}>
                                <div className="header-icon-box-v4" style={{ margin: '0 auto 24px', background: 'rgba(var(--accent-rgb), 0.1)', color: 'var(--emerald-success)' }}>
                                    <ShieldCheck size={24} />
                                </div>
                                <h3 style={{ color: 'var(--text-primary)', marginBottom: '12px', fontSize: '18px' }}>Confirm Verification</h3>
                                <p style={{ color: 'var(--text-primary)', fontSize: '14px', lineHeight: '1.6', marginBottom: '32px' }}>
                                    Have you verified the document?
                                </p>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <button
                                        className="dark-outline"
                                        style={{ padding: '10px' }}
                                        disabled={isVerifying}
                                        onClick={() => setManualVerifyMessage("Manually verify the document first")}
                                    >
                                        No
                                    </button>
                                    <button
                                        className="minimal-btn"
                                        style={{
                                            padding: '10px',
                                            background: 'var(--emerald-success)',
                                            color: 'var(--text-inverse)',
                                            border: 'none',
                                            borderRadius: '100px',
                                            fontWeight: '700',
                                            cursor: isVerifying ? 'not-allowed' : 'pointer',
                                            opacity: isVerifying ? 0.7 : 1,
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            gap: '8px'
                                        }}
                                        disabled={isVerifying}
                                        onClick={async () => {
                                            setIsVerifying(true);
                                            try {
                                                await handleVerifyDocument(confirmDocId);
                                                setConfirmDocId(null);
                                                setSuccessConfig({
                                                    message: "Verification Complete",
                                                    subMessage: `Document ${confirmDocId} is now verified`
                                                });
                                                setTimeout(() => setSuccessConfig(null), 3000);
                                            } catch (err) {
                                                console.error("Verification failed:", err);
                                            } finally {
                                                setIsVerifying(false);
                                            }
                                        }}
                                    >
                                        {isVerifying ? (
                                            <>
                                                <Loader2 size={14} className="refresh-spin" />
                                                Verifying...
                                            </>
                                        ) : 'Yes'}
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <div style={{ textAlign: 'center' }}>
                                <div className="header-icon-box-v4" style={{ margin: '0 auto 24px', background: 'rgba(var(--warning-rgb), 0.1)', color: 'var(--warning)' }}>
                                    <AlertCircle size={24} />
                                </div>
                                <h3 style={{ color: 'var(--text-primary)', marginBottom: '12px', fontSize: '18px' }}>Action Required</h3>
                                <p style={{ color: 'var(--text-primary)', fontSize: '14px', lineHeight: '1.6', marginBottom: '32px' }}>
                                    {manualVerifyMessage}
                                </p>
                                <button
                                    className="dark-outline"
                                    style={{ width: '100%', padding: '12px' }}
                                    onClick={() => {
                                        setConfirmDocId(null);
                                        setManualVerifyMessage(null);
                                    }}
                                >
                                    Close
                                </button>
                            </div>
                        )}
                    </div>
                </div>,
                document.body
            )}

            {/* Global Success Animation Modal */}
            {successConfig && createPortal(
                <div className="success-overlay-v4" style={{ 
                    position: 'fixed',
                    inset: 0,
                    zIndex: 9999,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: 'var(--bg-overlay)',
                    WebkitBackdropFilter: 'blur(6px)',
                    backdropFilter: 'blur(6px)',
                    animation: 'fadeIn 0.3s ease'
                }}>
                    <div style={{ textAlign: 'center', animation: 'successPop 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275)' }}>
                        <div style={{ 
                            width: '80px', 
                            height: '80px', 
                            background: 'var(--emerald-success)', 
                            borderRadius: '50%', 
                            display: 'flex', 
                            alignItems: 'center', 
                            justifyContent: 'center',
                            margin: '0 auto 24px',
                            boxShadow: 'var(--shadow-lg)',
                            animation: 'scale 0.3s ease-in-out 0.9s both'
                        }}>
                            <svg className="checkmark-svg-v4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 52">
                                <circle className="checkmark-circle-v4" cx="26" cy="26" r="25" fill="none" style={{ display: 'none' }} />
                                <path className="checkmark-check-v4" fill="none" stroke="var(--text-inverse)" strokeWidth="5" d="M14.1 27.2l7.1 7.2 16.7-16.8" />
                            </svg>
                        </div>
                        <h2 style={{ color: 'var(--text-primary)', fontSize: '24px', fontWeight: '800', marginBottom: '8px' }}>
                            {successConfig.message}
                        </h2>
                        <p style={{ color: 'var(--text-primary)', fontSize: '15px' }}>
                            {successConfig.subMessage}
                        </p>
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
};

export default GstFilingDocuments;
