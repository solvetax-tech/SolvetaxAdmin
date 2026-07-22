import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import api from '../../utils/api';
import { X, Loader2, FilePlus, AlertCircle } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfigOnly } from '../common/selectOptionUtils';

const EMPTY_FORM = {
    gst_filing_id: '',
    document_type: 'WORKING_SHEET',
    document_url: '',
    gstin: '',
    remarks: '',
    verified: false,
};

const DOC_TYPE_OPTIONS = [
    { value: 'WORKING_SHEET', label: 'Working Sheet' },
    { value: 'SUMMARY_SHEET', label: 'Summary Sheet' },
    { value: 'RECON_SHEET', label: 'Reconciliation Sheet' },
    { value: 'MISC_SHEET', label: 'Miscellaneous Sheet' },
];

/**
 * Self-contained "Add Document Link" drawer.
 *
 * Owns its form state and the POST so it can be rendered from anywhere the user
 * happens to be — the Documents tab, the GST Filings table, or the dashboard
 * matrix — without navigating them somewhere else first.
 */
export default function AddDocumentLinkModal({
    isOpen,
    onClose,
    presetFilingId = null,
    presetGstin = '',
    onCreated,
}) {
    const [form, setForm] = useState(EMPTY_FORM);
    const [fieldErrors, setFieldErrors] = useState({});
    const [generalError, setGeneralError] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [filingSearchResults, setFilingSearchResults] = useState([]);
    const [isSearchingFiling, setIsSearchingFiling] = useState(false);
    const [isFilingDropdownOpen, setIsFilingDropdownOpen] = useState(false);

    // Suppresses the debounced lookup when the ID was set by us rather than typed.
    const isInternalUpdate = useRef(false);
    const lastSearchedId = useRef('');
    const seededRef = useRef(false);

    const handleFilingIdSearch = useCallback(async (id) => {
        if (!id) {
            setFilingSearchResults([]);
            setIsFilingDropdownOpen(false);
            return;
        }
        setIsSearchingFiling(true);
        try {
            const response = await api.get(`/api/v1/gst-filings/table/filings?id=${id}`);
            const filings = response.data.data || [];
            lastSearchedId.current = id.toString();
            setFilingSearchResults(filings);
            // Kept open on 0 results so the "no filings found" hint shows.
            setIsFilingDropdownOpen(true);
        } catch (err) {
            console.error('Error searching filing:', err);
            setFilingSearchResults([]);
        } finally {
            setIsSearchingFiling(false);
        }
    }, []);

    // Seed once per open: preset from a row action, otherwise a clean form.
    useEffect(() => {
        if (!isOpen) {
            seededRef.current = false;
            return;
        }
        if (seededRef.current) return;
        seededRef.current = true;

        setFieldErrors({});
        setGeneralError(null);
        setFilingSearchResults([]);
        setIsFilingDropdownOpen(false);

        if (presetFilingId) {
            const presetId = String(presetFilingId);
            isInternalUpdate.current = true;
            lastSearchedId.current = presetId;
            setForm({ ...EMPTY_FORM, gst_filing_id: presetId, gstin: presetGstin || '' });
        } else {
            lastSearchedId.current = '';
            setForm(EMPTY_FORM);
        }
    }, [isOpen, presetFilingId, presetGstin]);

    useEffect(() => {
        if (!isOpen) return undefined;
        const timer = setTimeout(() => {
            const currentId = form.gst_filing_id?.toString();
            if (isInternalUpdate.current) {
                isInternalUpdate.current = false;
                return;
            }
            if (currentId && currentId !== lastSearchedId.current) {
                handleFilingIdSearch(currentId);
            } else if (!currentId) {
                setFilingSearchResults([]);
                setIsFilingDropdownOpen(false);
            }
        }, 500);
        return () => clearTimeout(timer);
    }, [isOpen, form.gst_filing_id, handleFilingIdSearch]);

    const close = () => {
        setFieldErrors({});
        setGeneralError(null);
        onClose?.();
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setFieldErrors({});
        setGeneralError(null);
        try {
            const payload = { ...form };
            if (payload.gst_filing_id) payload.gst_filing_id = parseInt(payload.gst_filing_id, 10);

            await api.post('/api/v1/gst-filings-docs', payload);
            onCreated?.({ filingId: payload.gst_filing_id });
            close();
        } catch (err) {
            console.error('Error creating document:', err);
            let errorMessage = 'Failed to create document link.';
            const newFieldErrors = {};

            const errorData = err.response?.data;
            const detail = errorData?.detail || errorData?.message || errorData?.error;

            if (err.response?.status === 422 && Array.isArray(detail)) {
                detail.forEach((error) => {
                    if (error.loc && error.loc.length > 1) {
                        newFieldErrors[error.loc[1]] = error.msg;
                    }
                });
                if (detail.length > 0) {
                    errorMessage = detail[0].msg || 'Validation error occurred.';
                }
            } else if (err.response?.status === 400 || err.response?.status === 404) {
                const msg = typeof detail === 'string' ? detail : (detail?.msg || detail?.message || 'Bad Request');
                errorMessage = msg;
                if (msg.toLowerCase().includes('filing')) {
                    newFieldErrors.gst_filing_id = msg;
                }
            } else if (err.response?.status === 409) {
                const msg = typeof detail === 'string' ? detail : (detail?.msg || detail?.message || detail?.error || 'Conflict');
                errorMessage = msg;
                newFieldErrors.document_type = msg;
                newFieldErrors.gst_filing_id = 'Check if this doc type already exists for this ID';
            } else {
                errorMessage = typeof detail === 'string' ? detail : (detail?.msg || 'An unexpected error occurred.');
            }

            setFieldErrors(newFieldErrors);
            if (!Object.keys(newFieldErrors).length) {
                setGeneralError(errorMessage);
            }
        } finally {
            setSubmitting(false);
        }
    };

    if (!isOpen) return null;

    const modal = (
        <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={close}>
            <div
                className="gst-modal-card-v4 wide-modal app-drawer-panel gst-reg-side-drawer-shell"
                onClick={(e) => e.stopPropagation()}
            >
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
                    <button className="btn-drawer-close" onClick={close}><X size={20} /></button>
                </div>

                <form onSubmit={handleSubmit} className="modal-form-v4">
                    <div className="form-scroll-container">
                        {generalError && (
                            <div className="form-section-group">
                                <p className="error-text-v4" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <AlertCircle size={14} /> {generalError}
                                </p>
                            </div>
                        )}

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
                                            value={form.gst_filing_id}
                                            onChange={(e) => {
                                                const val = e.target.value;
                                                setForm((prev) => ({ ...prev, gst_filing_id: val }));
                                                setFieldErrors((prev) => ({ ...prev, gst_filing_id: null }));
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

                                        {isFilingDropdownOpen && form.gst_filing_id && (
                                            <div className="searchable-dropdown" style={{ top: '100%', left: 0, right: 0, marginTop: '8px' }}>
                                                <div className="results-section">
                                                    <div className="results-header">Matching Filing</div>
                                                    {filingSearchResults.length > 0 ? (
                                                        filingSearchResults.map((f) => (
                                                            <div
                                                                key={`filing-res-${f.id}`}
                                                                className="dropdown-item"
                                                                onMouseDown={(e) => {
                                                                    e.preventDefault();
                                                                    e.stopPropagation();
                                                                    isInternalUpdate.current = true;
                                                                    setForm((prev) => ({
                                                                        ...prev,
                                                                        gst_filing_id: f.id,
                                                                        gstin: f.gstin || '',
                                                                    }));
                                                                    setFieldErrors((prev) => ({ ...prev, gst_filing_id: null, gstin: null }));
                                                                    setTimeout(() => setIsFilingDropdownOpen(false), 50);
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
                                                            No filings found for ID "{form.gst_filing_id}"
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
                                        value={form.document_type}
                                        onChange={(e) => setForm((prev) => ({ ...prev, document_type: e.target.value }))}
                                        options={optionsFromConfigOnly(DOC_TYPE_OPTIONS)}
                                        placeholder="Document type"
                                        ariaLabel="Document type"
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="form-section-group">
                            <h3 className="section-title">2. Access & Verification</h3>
                            <div className="form-group-v4 full-width" style={{ marginBottom: '24px', width: '100%' }}>
                                <label className="modal-label-caps">Spreadsheet URL*</label>
                                <input
                                    type="url"
                                    className={`modal-input-v4 ${fieldErrors.document_url ? 'input-error-v4' : ''}`}
                                    required
                                    placeholder="Google Sheets or OneDrive Excel link"
                                    value={form.document_url}
                                    onChange={(e) => {
                                        setForm((prev) => ({ ...prev, document_url: e.target.value }));
                                        setFieldErrors((prev) => ({ ...prev, document_url: null }));
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
                                        value={form.gstin}
                                        onChange={(e) => {
                                            setForm((prev) => ({ ...prev, gstin: e.target.value }));
                                            setFieldErrors((prev) => ({ ...prev, gstin: null }));
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
                                                    checked={form.verified}
                                                    onChange={() => setForm((prev) => ({ ...prev, verified: !prev.verified }))}
                                                    style={{ display: 'none' }}
                                                />
                                                <div className={`switch-track-v4 ${form.verified ? 'active' : ''}`}>
                                                    <div className="switch-thumb-v4"></div>
                                                </div>
                                            </label>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="form-section-group">
                            <h3 className="section-title">3. Context</h3>
                            <div className="form-group-v4 full-width" style={{ width: '100%' }}>
                                <label className="modal-label-caps">Remarks</label>
                                <textarea
                                    className="modal-input-v4"
                                    style={{ minHeight: '120px', resize: 'vertical', lineHeight: '1.6' }}
                                    placeholder="Add any context for this sheet..."
                                    value={form.remarks}
                                    onChange={(e) => setForm((prev) => ({ ...prev, remarks: e.target.value }))}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="modal-footer-v4">
                        <div className="footer-actions-v4">
                            <button type="button" className="dark-outline" onClick={close}>Cancel</button>
                            <button
                                type="submit"
                                className="minimal-btn"
                                style={{
                                    background: 'var(--emerald-success)',
                                    color: 'var(--text-primary)',
                                    border: 'none',
                                    borderRadius: '100px',
                                    fontWeight: '700',
                                    cursor: submitting ? 'not-allowed' : 'pointer',
                                    opacity: submitting ? 0.7 : 1,
                                    padding: '10px 24px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    transition: 'all 0.2s ease',
                                }}
                                disabled={submitting}
                            >
                                {submitting ? (
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
        </div>
    );

    return typeof document !== 'undefined' ? createPortal(modal, document.body) : modal;
}
