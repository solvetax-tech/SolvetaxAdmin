import React, { useState, useEffect, useCallback, useRef } from 'react';
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
import { optionsFromConfigOnly } from '../common/selectOptionUtils';

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
    // Hoisted State
    setCurrentDocsPage,
    currentDocsPage,
    setDocsHasMore,
    docsHasMore,
    docsLoading,
    setDocsLoading
}) => {
    const [docsData, setDocsData] = useState([]);
    const [formLoading, setFormLoading] = useState(false);
    const [isSearchingFiling, setIsSearchingFiling] = useState(false);
    const [filingSearchResults, setFilingSearchResults] = useState([]);
    const [isFilingDropdownOpen, setIsFilingDropdownOpen] = useState(false);
    const [fieldErrors, setFieldErrors] = useState({});

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



    // Create Document Form State (Capsulated inside module)
    const [createDocForm, setCreateDocForm] = useState({
        gst_filing_id: '',
        document_type: 'WORKING_SHEET',
        document_url: '',
        gstin: '',
        remarks: '',
        verified: false
    });

    // 🔥 Track internal updates to prevent double-searching when an ID is selected from dropdown
    const isInternalUpdate = useRef(false);
    const lastSearchedId = useRef('');

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

    const handleFilingIdSearch = useCallback(async (id) => {
        if (!id) {
            setFilingSearchResults([]);
            setIsFilingDropdownOpen(false);
            return;
        }

        setIsSearchingFiling(true);
        try {
            // 🔥 Use include_details=false to avoid the backend ID collision bug with return details.
            // This ensures results are unique and 'id' refers to the actual Filing ID.
            const response = await api.get(`/api/v1/gst-filings/table/filings?id=${id}`);
            const filings = response.data.data || [];
            lastSearchedId.current = id.toString();
            setFilingSearchResults(filings);
            // 🔥 Keep dropdown open even if 0 results so we can show "No results found"
            setIsFilingDropdownOpen(true);
        } catch (err) {
            console.error("Error searching filing:", err);
            setFilingSearchResults([]);
        } finally {
            setIsSearchingFiling(false);
        }
    }, []);

    useEffect(() => {
        const delayDebounceFn = setTimeout(() => {
            const currentId = createDocForm.gst_filing_id?.toString();

            // Skip search if it was updated by selecting from the result list
            if (isInternalUpdate.current) {
                isInternalUpdate.current = false;
                return;
            }

            // Skip if we just searched this ID or if it's empty
            if (currentId && currentId !== lastSearchedId.current) {
                handleFilingIdSearch(currentId);
            } else if (!currentId) {
                setFilingSearchResults([]);
                setIsFilingDropdownOpen(false);
            }
        }, 500);

        return () => clearTimeout(delayDebounceFn);
    }, [createDocForm.gst_filing_id, handleFilingIdSearch]);

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

    const handleCreateDocSubmit = async (e) => {
        e.preventDefault();
        setFormLoading(true);
        setFieldErrors({}); // Reset previous modal errors
        setError(null);    // 🔥 Clear global dashboard errors at start of submission
        try {
            const payload = { ...createDocForm };
            if (payload.gst_filing_id) payload.gst_filing_id = parseInt(payload.gst_filing_id);

            await api.post('/api/v1/gst-filings-docs', payload);
            setSuccessConfig({
                message: "Document Linked Successfully",
                subMessage: `Linked to GST Filing ID ${payload.gst_filing_id}`
            });
            setTimeout(() => setSuccessConfig(null), 3000);
            
            setShowCreateDocModal(false); 
            setCreateDocForm({
                gst_filing_id: '',
                document_type: 'WORKING_SHEET',
                document_url: '',
                gstin: '',
                remarks: '',
                verified: false
            });
            fetchFilingDocuments();
        } catch (err) {
            console.error("Error creating document:", err);
            let errorMessage = "Failed to create document link.";
            const newFieldErrors = {};

            const errorData = err.response?.data;
            const detail = errorData?.detail || errorData?.message || errorData?.error;

            if (err.response?.status === 422 && Array.isArray(detail)) {
                detail.forEach(error => {
                    if (error.loc && error.loc.length > 1) {
                        const fieldName = error.loc[1];
                        newFieldErrors[fieldName] = error.msg;
                    }
                });
                if (detail.length > 0) {
                    errorMessage = detail[0].msg || "Validation error occurred.";
                }
            } else if (err.response?.status === 400 || err.response?.status === 404) {
                // Handle business logic errors like "GST filing not found"
                const msg = typeof detail === 'string' ? detail : (detail?.msg || detail?.message || "Bad Request");
                errorMessage = msg;

                // Map filing-related errors to the Filing ID field
                if (msg.toLowerCase().includes("filing")) {
                    newFieldErrors.gst_filing_id = msg;
                }
            } else if (err.response?.status === 409) {
                // Handle duplicate document errors (Conflict)
                const msg = typeof detail === 'string' ? detail : (detail?.msg || detail?.message || detail?.error || "Conflict");
                errorMessage = msg;
                newFieldErrors.document_type = msg;
                newFieldErrors.gst_filing_id = "Check if this doc type already exists for this ID";
            } else {
                errorMessage = typeof detail === 'string' ? detail : (detail?.msg || "An unexpected error occurred.");
            }

            setFieldErrors(newFieldErrors);
            // 🔥 User Request: Only show field-level errors in the modal, avoid global dashboard alerts for validation
            if (!Object.keys(newFieldErrors).length) {
                setError(errorMessage);
            }
        } finally {
            setFormLoading(false);
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
                                    <div className="filings-ledger-cell filings-docs-col-3" style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
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

            {/* Documents Creation Modal (Standard High-Fidelity - Now inside module via Portal) */}
            {showCreateDocModal && createPortal(
                <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={() => {
                    setShowCreateDocModal(false);
                    setError(null);
                    setFieldErrors({});
                }}>
                    <div className="gst-modal-card-v4 wide-modal app-drawer-panel gst-reg-side-drawer-shell" onClick={e => e.stopPropagation()}>
                        <div className="modal-header-v4">
                            <div className="header-content-v4">
                                <div className="header-icon-box-v4">
                                    <FilePlus size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <h2>Add Document Link</h2>
                                    <p className="modal-subtitle-v4">Link a working sheet or summary sheet to a filing</p>
                                </div>
                            </div>
                            <button className="btn-drawer-close" onClick={() => {
                                setShowCreateDocModal(false);
                                setError(null); // 🔥 Ensure global errors are cleared when closing modal
                                setFieldErrors({});
                            }}><X size={20} /></button>
                        </div>

                        <form onSubmit={handleCreateDocSubmit} className="modal-form-v4">
                            <div className="form-scroll-container">
                                {/* SECTION 1: LINK METADATA */}
                                <div className="form-section-group">
                                    <h3 className="section-title">1. Link Metadata</h3>
                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Filing ID*</label>
                                            <div style={{ position: 'relative', zIndex: isFilingDropdownOpen ? 3000 : 1 }}>
                                                <input
                                                    type="number"
                                                    className={`modal-input-v4 ${fieldErrors.gst_filing_id ? 'input-error-v4' : ''}`}
                                                    required
                                                    placeholder="e.g. 101"
                                                    value={createDocForm.gst_filing_id}
                                                    onChange={e => {
                                                        const val = e.target.value;
                                                        setCreateDocForm(prev => ({ ...prev, gst_filing_id: val }));
                                                        setFieldErrors(prev => ({ ...prev, gst_filing_id: null }));
                                                        if (!val) {
                                                            setFilingSearchResults([]);
                                                            setIsFilingDropdownOpen(false);
                                                        }
                                                    }}
                                                    onFocus={() => {
                                                        if (filingSearchResults.length > 0) setIsFilingDropdownOpen(true);
                                                    }}
                                                />
                                                {isSearchingFiling && (
                                                    <div style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--emerald-success)' }}>
                                                        <Loader2 size={16} className="refresh-spin" />
                                                    </div>
                                                )}

                                                {/* Filing Search Dropdown */}
                                                {isFilingDropdownOpen && createDocForm.gst_filing_id && (
                                                    <div className="searchable-dropdown" style={{ top: '100%', left: 0, right: 0, marginTop: '8px' }}>
                                                        <div className="results-section">
                                                            <div className="results-header">Matching Filing</div>
                                                            {filingSearchResults.length > 0 ? (
                                                                filingSearchResults.map(f => (
                                                                    <div
                                                                        key={`filing-res-${f.id}`}
                                                                        className="dropdown-item"
                                                                        onMouseDown={(e) => {
                                                                            e.preventDefault();
                                                                            e.stopPropagation();
                                                                            const selectedGstin = f.gstin || '';
                                                                            const selectedFilingId = f.id;

                                                                            // 🔥 Mark as internal update so useEffect skips the redundant search
                                                                            isInternalUpdate.current = true;

                                                                            setCreateDocForm(prev => ({
                                                                                ...prev,
                                                                                gst_filing_id: selectedFilingId,
                                                                                gstin: selectedGstin
                                                                            }));
                                                                            setFieldErrors(prev => ({ ...prev, gst_filing_id: null, gstin: null }));

                                                                            // Small timeout to ensure state settles before closing dropdown
                                                                            setTimeout(() => {
                                                                                setIsFilingDropdownOpen(false);
                                                                            }, 50);
                                                                        }}
                                                                    >
                                                                        <div className="item-main">
                                                                            <span className="item-id">{f.id}</span>
                                                                            <span className="item-name">{f.filing_period}</span>
                                                                        </div>
                                                                        <div className="item-sub" style={{ paddingLeft: '40px' }}>
                                                                            GSTIN: <span style={{ color: 'var(--info)', fontWeight: '700' }}>{f.gstin || 'N/A'}</span>
                                                                        </div>
                                                                    </div>
                                                                ))
                                                            ) : !isSearchingFiling ? (
                                                                <div className="dropdown-no-results" style={{ padding: '20px', textAlign: 'center', fontSize: '11px', color: 'var(--text-primary)' }}>
                                                                    No filings found for ID "{createDocForm.gst_filing_id}"
                                                                </div>
                                                            ) : null}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                            {fieldErrors.gst_filing_id && <p className="error-text-v4">{fieldErrors.gst_filing_id}</p>}
                                            {isFilingDropdownOpen && (
                                                <div
                                                    className="dropdown-backdrop"
                                                    onClick={() => setIsFilingDropdownOpen(false)}
                                                    style={{ zIndex: 2050 }}
                                                />
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Document Type*</label>
                                            <FormCustomSelect
                                                name="document_type"
                                                value={createDocForm.document_type}
                                                onChange={(e) => setCreateDocForm((prev) => ({ ...prev, document_type: e.target.value }))}
                                                options={optionsFromConfigOnly([
                                                    { value: 'WORKING_SHEET', label: 'Working Sheet' },
                                                    { value: 'SUMMARY_SHEET', label: 'Summary Sheet' },
                                                    { value: 'RECON_SHEET', label: 'Reconciliation Sheet' },
                                                    { value: 'MISC_SHEET', label: 'Miscellaneous Sheet' },
                                                ])}
                                                placeholder="Document type"
                                                ariaLabel="Document type"
                                            />
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 2: ACCESS & VERIFICATION */}
                                <div className="form-section-group">
                                    <h3 className="section-title">2. Access & Verification</h3>
                                    <div className="form-group-v4 full-width" style={{ marginBottom: '24px', width: '100%' }}>
                                        <label className="modal-label-caps">Spreadsheet URL*</label>
                                        <input
                                            type="url"
                                            className={`modal-input-v4 ${fieldErrors.document_url ? 'input-error-v4' : ''}`}
                                            required
                                            placeholder="Google Sheets or OneDrive Excel link"
                                            value={createDocForm.document_url}
                                            onChange={e => {
                                                setCreateDocForm(prev => ({ ...prev, document_url: e.target.value }));
                                                setFieldErrors(prev => ({ ...prev, document_url: null }));
                                            }}
                                        />
                                        {fieldErrors.document_url ? (
                                            <p className="error-text-v4">{fieldErrors.document_url}</p>
                                        ) : (
                                            <p className="field-hint">Required: Must be a direct Excel (.xlsx), CSV, or Google Sheets link starting with http/https</p>
                                        )}
                                    </div>

                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">GSTIN (Optional)</label>
                                            <input
                                                type="text"
                                                className={`modal-input-v4 ${fieldErrors.gstin ? 'input-error-v4' : ''}`}
                                                placeholder="15-digit GSTIN"
                                                value={createDocForm.gstin}
                                                onChange={e => {
                                                    setCreateDocForm(prev => ({ ...prev, gstin: e.target.value }));
                                                    setFieldErrors(prev => ({ ...prev, gstin: null }));
                                                }}
                                            />
                                            {fieldErrors.gstin && <p className="error-text-v4">{fieldErrors.gstin}</p>}
                                        </div>

                                        <div className="form-group-v4">
                                            <div className="verification-field-v4" style={{ marginTop: '22px', padding: '12px', background: 'rgba(var(--fg-rgb),0.02)', borderRadius: '10px', border: '1px solid rgba(var(--fg-rgb),0.05)' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                                                    <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>I have manually verified this document</span>

                                                    <label className="toggle-switch-v4" style={{ cursor: 'pointer' }}>
                                                        <input
                                                            type="checkbox"
                                                            checked={createDocForm.verified}
                                                            onChange={() => setCreateDocForm({ ...createDocForm, verified: !createDocForm.verified })}
                                                            style={{ display: 'none' }}
                                                        />
                                                        <div className={`switch-track-v4 ${createDocForm.verified ? 'active' : ''}`}>
                                                            <div className="switch-thumb-v4"></div>
                                                        </div>
                                                    </label>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 3: CONTEXT */}
                                <div className="form-section-group">
                                    <h3 className="section-title">3. Context</h3>
                                    <div className="form-group-v4 full-width" style={{ width: '100%' }}>
                                        <label className="modal-label-caps">Remarks</label>
                                        <textarea
                                            className="modal-input-v4"
                                            style={{ minHeight: '120px', resize: 'vertical', lineHeight: '1.6' }}
                                            placeholder="Add any context for this sheet..."
                                            value={createDocForm.remarks}
                                            onChange={e => setCreateDocForm({ ...createDocForm, remarks: e.target.value })}
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer-v4">
                                <div className="footer-actions-v4">
                                    <button type="button" className="dark-outline" onClick={() => {
                                        setShowCreateDocModal(false);
                                        setError(null);
                                        setFieldErrors({});
                                    }}>Cancel</button>
                                    <button
                                        type="submit"
                                        className="minimal-btn"
                                        style={{
                                            background: 'var(--emerald-success)',
                                            color: 'var(--text-primary)',
                                            border: 'none',
                                            borderRadius: '100px',
                                            fontWeight: '700',
                                            cursor: formLoading ? 'not-allowed' : 'pointer',
                                            opacity: formLoading ? 0.7 : 1,
                                            padding: '10px 24px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            gap: '8px',
                                            transition: 'all 0.2s ease'
                                        }}
                                        disabled={formLoading}
                                    >
                                        {formLoading ? (
                                            <>
                                                <Loader2 size={16} className="refresh-spin" />
                                                Linking...
                                            </>
                                        ) : 'Link Document'}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>,
                document.body
            )}
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
