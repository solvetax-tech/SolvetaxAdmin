/**
 * @file GSTPeopleDocuments.jsx
 * @description Combined "People & Documents" screen for GST registration.
 * One person row now carries their documents inline (see the
 * person_document_details table), so the RM enters a person's details AND
 * uploads all their documents in a single save. The OP views/downloads them
 * (each file named by its document type) and updates the registration status.
 *
 * Backend: /api/v1/person-document-details/*  (replaces gst-people + gst-documents)
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
    Plus, Search, X, Eye, Pencil, Trash2, Upload, Download, FileText,
    Star, RotateCcw, Loader2, AlertCircle, CheckCircle2,
} from 'lucide-react';
import api from '../../utils/api';
import Button from '../ui/Button';
import StatusPill from '../ui/StatusPill';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import Toast from '../common/Toast';
import Pagination from '../common/Pagination';
import { canManageRmOpRecords } from '../../utils/rmOpAssignmentFields';
import { extractErrorMessage, extractFieldErrors } from '../../utils/apiErrors';
import './GSTPeopleDocuments.css';

const EMPTY_PERSON = {
    gst_registration_id: '',
    full_name: '',
    designation: '',
    phone: '',
    email: '',
    pan: '',
    aadhaar: '',
    is_primary: false,
};

const prettyType = (t) => String(t || '').replace(/_/g, ' ');

export const GSTPeopleDocuments = ({ isAdmin, profileData, onRenderToolbar }) => {
    const canWrite = canManageRmOpRecords(profileData, isAdmin);

    // ---- list ----
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [page, setPage] = useState(1);
    const rowsPerPage = 20;
    const [regFilter, setRegFilter] = useState('');
    const [appliedReg, setAppliedReg] = useState('');
    const [toast, setToast] = useState(null);

    // ---- drawers ----
    const [showCreate, setShowCreate] = useState(false);
    const [detailPerson, setDetailPerson] = useState(null);
    const [detailEditMode, setDetailEditMode] = useState(false);

    const abortRef = useRef(null);

    const fetchRows = useCallback(async () => {
        if (abortRef.current) abortRef.current.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            if (appliedReg) params.append('gst_registration_id', appliedReg);
            params.append('limit', rowsPerPage);
            params.append('offset', (page - 1) * rowsPerPage);
            const res = await api.get(
                `/api/v1/person-document-details/dynamic_filter?${params.toString()}`,
                { signal: controller.signal },
            );
            setRows(Array.isArray(res.data?.data) ? res.data.data : []);
        } catch (err) {
            if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return;
            setError(extractErrorMessage(err, 'Failed to load people & documents.'));
        } finally {
            if (!controller.signal.aborted) setLoading(false);
        }
    }, [appliedReg, page]);

    useEffect(() => { fetchRows(); return () => abortRef.current?.abort(); }, [fetchRows]);

    // Toolbar (create button + registration filter) rendered into the parent header.
    useEffect(() => {
        if (!onRenderToolbar) return;
        onRenderToolbar(
            <div className="gst-action-buttons">
                <div className="pdd-reg-filter">
                    <Search size={13} />
                    <input
                        type="text"
                        value={regFilter}
                        placeholder="Registration ID…"
                        onChange={(e) => setRegFilter(e.target.value.replace(/\D/g, ''))}
                        onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); setAppliedReg(regFilter); } }}
                    />
                    {appliedReg && (
                        <button className="pdd-reg-clear" onClick={() => { setRegFilter(''); setAppliedReg(''); setPage(1); }}>
                            <X size={13} />
                        </button>
                    )}
                </div>
                <Button variant="secondary" size="sm" icon={<RotateCcw size={13} />} onClick={fetchRows}>
                    Refresh
                </Button>
                {canWrite && (
                    <Button variant="primary" size="sm" icon={<Plus size={13} />} onClick={() => setShowCreate(true)}>
                        Create Person
                    </Button>
                )}
            </div>
        );
        return () => onRenderToolbar(null);
    }, [onRenderToolbar, regFilter, appliedReg, canWrite, fetchRows]);

    const openDetail = (person, edit = false) => { setDetailEditMode(edit); setDetailPerson(person); };

    // Download one document straight from its chip (named by its document type).
    const downloadDoc = async (personId, documentType) => {
        try {
            const res = await api.get(
                `/api/v1/person-document-details/${personId}/documents/${encodeURIComponent(documentType)}/download`,
            );
            if (res.data?.download_url) window.open(res.data.download_url, '_blank', 'noopener');
        } catch (err) {
            setToast({ message: extractErrorMessage(err, 'Could not open document.'), type: 'error' });
        }
    };

    return (
        <div className="pdd-container">
            {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

            <div className="gst-table-wrapper gst-table-wrapper--portal">
              <div className="gst-table-container gst-table-container--portal">
                <div className="filings-ledger-header pdd-ledger-grid-template">
                    <div className="filings-ledger-header-cell pdd-col-left">Person</div>
                    <div className="filings-ledger-header-cell">Reg. ID</div>
                    <div className="filings-ledger-header-cell">Designation</div>
                    <div className="filings-ledger-header-cell">Phone</div>
                    <div className="filings-ledger-header-cell">PAN</div>
                    <div className="filings-ledger-header-cell">Aadhaar</div>
                    <div className="filings-ledger-header-cell pdd-col-left">Documents</div>
                    <div className="filings-ledger-header-cell">Primary</div>
                    <div className="filings-ledger-header-cell">Active</div>
                    <div className="filings-ledger-header-cell pdd-actions-cell">Actions</div>
                </div>

                {loading ? (
                    <div className="pdd-msg"><Loader2 size={22} className="pdd-spin" /> Loading…</div>
                ) : error ? (
                    <div className="pdd-msg pdd-msg--error"><AlertCircle size={22} /> {error}</div>
                ) : rows.length === 0 ? (
                    <div className="pdd-msg"><Search size={22} /> No people found.</div>
                ) : (
                    <div className="filings-ledger-body">
                        {rows.map((p) => {
                            const docs = Array.isArray(p.documents) ? p.documents : [];
                            return (
                                <div key={p.person_id} className="filings-ledger-row pdd-ledger-grid-template">
                                    <div className="filings-ledger-cell pdd-col-left pdd-person-cell">
                                        <div className="pdd-person-name">{p.full_name || '-'}</div>
                                        <div className="pdd-person-sub">{p.email || '—'}</div>
                                    </div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{p.gst_registration_id}</span></div>
                                    <div className="filings-ledger-cell">{p.designation || '-'}</div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{p.phone || '-'}</span></div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{p.pan || '-'}</span></div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{p.aadhaar || '-'}</span></div>
                                    <div className="filings-ledger-cell pdd-col-left">
                                        {docs.length === 0 ? (
                                            <span className="pdd-muted">None</span>
                                        ) : (
                                            <div className="pdd-doc-chips">
                                                {docs.slice(0, 3).map((d) => (
                                                    <button
                                                        key={d.document_type}
                                                        type="button"
                                                        className="pdd-doc-chip"
                                                        title={`Download ${prettyType(d.document_type)}`}
                                                        onClick={(e) => { e.stopPropagation(); downloadDoc(p.person_id, d.document_type); }}
                                                    >
                                                        <Download size={11} /> {prettyType(d.document_type)}
                                                    </button>
                                                ))}
                                                {docs.length > 3 && (
                                                    <button
                                                        type="button"
                                                        className="pdd-doc-chip pdd-doc-chip--more"
                                                        title="View all documents"
                                                        onClick={() => setDetailPerson(p)}
                                                    >
                                                        +{docs.length - 3}
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    <div className="filings-ledger-cell">
                                        {p.is_primary ? <Star size={15} className="pdd-primary-star" /> : <span className="pdd-muted">—</span>}
                                    </div>
                                    <div className="filings-ledger-cell">
                                        <StatusPill tone={p.is_active ? 'success' : 'danger'}>{p.is_active ? 'Active' : 'Inactive'}</StatusPill>
                                    </div>
                                    <div className="filings-ledger-cell pdd-actions-cell">
                                        <Button variant="ghost" icon={<Eye size={14} />} title="View / documents" onClick={() => openDetail(p, false)} />
                                        {canWrite && (
                                            <Button variant="ghost" icon={<Pencil size={14} />} title="Edit" onClick={() => openDetail(p, true)} />
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
              </div>
            </div>

            <Pagination currentPage={page} onPageChange={setPage} hasMore={rows.length >= rowsPerPage} loading={loading} />

            {showCreate && (
                <CreatePersonDrawer
                    onClose={() => setShowCreate(false)}
                    onSuccess={() => { setShowCreate(false); setToast({ message: 'Person & documents saved ✨', type: 'success' }); fetchRows(); }}
                />
            )}

            {detailPerson && (
                <PersonDetailDrawer
                    person={detailPerson}
                    canWrite={canWrite}
                    isAdmin={isAdmin}
                    initialEditing={detailEditMode}
                    onClose={() => setDetailPerson(null)}
                    onChanged={() => { fetchRows(); }}
                    setToast={setToast}
                />
            )}
        </div>
    );
};

// ======================================================================= //
// Shared: document-type options for a registration's ownership category
// ======================================================================= //
function useDocumentTypes(gstId) {
    const [ownership, setOwnership] = useState(null);
    const [docTypes, setDocTypes] = useState([]);
    const [designations, setDesignations] = useState([]);

    useEffect(() => {
        let cancelled = false;
        if (!gstId) { setDocTypes([]); setDesignations([]); setOwnership(null); return; }
        (async () => {
            try {
                const dRes = await api.get(`/api/v1/person-document-details/gst-registration/${gstId}/designations`);
                if (cancelled) return;
                const cat = dRes.data?.ownership_category || null;
                setOwnership(cat);
                setDesignations(dRes.data?.designations || []);
                if (cat) {
                    const cfg = await api.get(
                        `/api/v1/document-config/document-config-all?registration=GST_REGISTRATION&ownership_category=${encodeURIComponent(cat)}&is_active=true`,
                    );
                    if (cancelled) return;
                    const list = Array.isArray(cfg.data?.data) ? cfg.data.data : [];
                    setDocTypes(list.map((c) => ({ value: c.value, label: c.display_name || prettyType(c.value) })));
                } else {
                    setDocTypes([]);
                }
            } catch {
                if (!cancelled) { setDocTypes([]); setDesignations([]); }
            }
        })();
        return () => { cancelled = true; };
    }, [gstId]);

    return { ownership, docTypes, designations };
}

async function uploadToBlob(file) {
    const fd = new FormData();
    fd.append('file', file);
    const res = await api.post('/api/v1/gst-blob/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
    return res.data?.blob_url;
}

// ======================================================================= //
// Create person + documents (single save)
// ======================================================================= //
const CreatePersonDrawer = ({ onClose, onSuccess }) => {
    const [form, setForm] = useState(EMPTY_PERSON);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [fieldErrors, setFieldErrors] = useState({});

    // registration search
    const [query, setQuery] = useState('');
    const [results, setResults] = useState([]);
    const [showResults, setShowResults] = useState(false);
    const skipSearch = useRef(false);

    const { docTypes, designations } = useDocumentTypes(form.gst_registration_id);

    // documents being staged for this person: [{ document_type, document_url, fileName, uploading }]
    const [docs, setDocs] = useState([]);

    useEffect(() => {
        const t = setTimeout(async () => {
            if (skipSearch.current) { skipSearch.current = false; return; }
            if (!query) { setResults([]); setShowResults(false); return; }
            try {
                const params = new URLSearchParams();
                if (/^\d+$/.test(query)) params.append('gst_registration_id', query);
                else params.append('gstin', query);
                const res = await api.get(`/api/v1/gst-registrations/dynamic_filter?${params.toString()}&limit=5`);
                const items = Array.isArray(res.data) ? res.data : (res.data?.data || []);
                setResults(items); setShowResults(true);
            } catch { setResults([]); }
        }, 450);
        return () => clearTimeout(t);
    }, [query]);

    const selectReg = (r) => {
        const gstId = r.id || r.gst_registration_id;
        if (!gstId) return;
        skipSearch.current = true;
        setForm((p) => ({ ...p, gst_registration_id: gstId, pan: p.pan || r.pan || '', email: p.email || r.email || '' }));
        setQuery(String(gstId));
        setShowResults(false);
    };

    const setField = (name, value) => {
        setForm((p) => ({ ...p, [name]: value }));
        setFieldErrors((p) => (p[name] ? { ...p, [name]: undefined } : p));
    };

    const addDocRow = () => setDocs((d) => [...d, { document_type: '', document_url: '', fileName: '', uploading: false }]);
    const setDocType = (i, v) => setDocs((d) => d.map((row, idx) => (idx === i ? { ...row, document_type: v } : row)));
    const removeDocRow = (i) => setDocs((d) => d.filter((_, idx) => idx !== i));

    const onFilePick = async (i, file) => {
        if (!file) return;
        setDocs((d) => d.map((row, idx) => (idx === i ? { ...row, uploading: true, fileName: file.name } : row)));
        try {
            const url = await uploadToBlob(file);
            setDocs((d) => d.map((row, idx) => (idx === i ? { ...row, document_url: url, uploading: false } : row)));
        } catch (err) {
            setDocs((d) => d.map((row, idx) => (idx === i ? { ...row, uploading: false, fileName: '' } : row)));
            setError(extractErrorMessage(err, 'File upload failed.'));
        }
    };

    // Document types already used in the staged list (so the dropdown can dedupe).
    const usedTypes = new Set(docs.map((d) => d.document_type).filter(Boolean));

    const validate = () => {
        const e = {};
        if (!form.gst_registration_id) e.gst_registration_id = 'Select a registration.';
        if (!form.full_name || form.full_name.trim().length < 2) e.full_name = 'Enter the full name.';
        if (!form.designation) e.designation = 'Select a designation.';
        if (form.phone && !/^\d{10}$/.test(form.phone)) e.phone = '10 digits.';
        if (form.pan && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(form.pan)) e.pan = 'Format: ABCDE1234F';
        if (form.aadhaar && !/^\d{12}$/.test(form.aadhaar)) e.aadhaar = '12 digits.';
        for (const d of docs) {
            if (d.document_url && !d.document_type) { e._docs = 'Every uploaded file needs a document type.'; break; }
            if (d.document_type && !d.document_url) { e._docs = 'Every document type needs a file.'; break; }
        }
        setFieldErrors(e);
        return Object.keys(e).length === 0;
    };

    const save = async () => {
        if (!validate() || saving) return;
        setSaving(true);
        setError('');
        try {
            const payload = {
                gst_registration_id: Number(form.gst_registration_id),
                full_name: form.full_name.trim(),
                designation: form.designation,
                phone: form.phone || null,
                email: form.email || null,
                pan: form.pan || null,
                aadhaar: form.aadhaar || null,
                is_primary: !!form.is_primary,
                documents: docs
                    .filter((d) => d.document_type && d.document_url)
                    .map((d) => ({ document_type: d.document_type, document_url: d.document_url })),
            };
            await api.post('/api/v1/person-document-details', payload);
            onSuccess();
        } catch (err) {
            setError(extractErrorMessage(err, 'Save failed.'));
            setFieldErrors(extractFieldErrors(err) || {});
        } finally {
            setSaving(false);
        }
    };

    const anyUploading = docs.some((d) => d.uploading);

    return (
        <div className="gst-filters-drawer-overlay" onClick={() => !saving && onClose()}>
            <div className="gst-filters-drawer pdd-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header-v4">
                    <h2><Plus size={18} /> Create Person &amp; Documents</h2>
                    <button className="btn-drawer-close" onClick={onClose}><X size={18} /></button>
                </div>

                <div className="drawer-content-v4 pdd-form">
                    {error && <div className="pdd-banner pdd-banner--error">{error}</div>}

                    {/* Registration */}
                    <div className="pdd-section-label">Registration</div>
                    <div className="pdd-reg-search">
                        <Search size={14} />
                        <input
                            type="text"
                            value={query}
                            placeholder="Search by Registration ID or GSTIN…"
                            onChange={(e) => setQuery(e.target.value)}
                            onFocus={() => results.length && setShowResults(true)}
                        />
                        {form.gst_registration_id && (
                            <button className="pdd-reg-clear" onClick={() => { setForm((p) => ({ ...p, gst_registration_id: '' })); setQuery(''); }}>
                                <X size={14} />
                            </button>
                        )}
                        {showResults && results.length > 0 && (
                            <div className="pdd-reg-results">
                                {results.map((r) => (
                                    <button key={r.id || r.gst_registration_id} className="pdd-reg-result" onClick={() => selectReg(r)}>
                                        <span className="ui-num">#{r.id || r.gst_registration_id}</span>
                                        <span>{r.business_name || r.gstin || r.legal_name || '—'}</span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    {fieldErrors.gst_registration_id && <div className="pdd-err">{fieldErrors.gst_registration_id}</div>}

                    {/* Person */}
                    <div className="pdd-section-label">Person details</div>
                    <div className="pdd-grid-2">
                        <Field label="Full name" error={fieldErrors.full_name}>
                            <input value={form.full_name} onChange={(e) => setField('full_name', e.target.value)} placeholder="Full name" />
                        </Field>
                        <Field label="Designation" error={fieldErrors.designation}>
                            <FormCustomSelect
                                name="designation"
                                value={form.designation}
                                onChange={(e) => setField('designation', e.target.value)}
                                options={optionsFromPairs([{ value: '', label: designations.length ? 'Select…' : 'Select a registration first' },
                                    ...designations.map((d) => ({ value: d.value, label: d.display_name || d.value }))])}
                                placeholder="Designation"
                                ariaLabel="Designation"
                            />
                        </Field>
                        <Field label="Phone" error={fieldErrors.phone}>
                            <input value={form.phone} onChange={(e) => setField('phone', e.target.value.replace(/\D/g, '').slice(0, 10))} placeholder="10-digit phone" />
                        </Field>
                        <Field label="Email" error={fieldErrors.email}>
                            <input value={form.email} onChange={(e) => setField('email', e.target.value)} placeholder="name@company.com" />
                        </Field>
                        <Field label="PAN" error={fieldErrors.pan}>
                            <input value={form.pan} onChange={(e) => setField('pan', e.target.value.toUpperCase().slice(0, 10))} placeholder="ABCDE1234F" />
                        </Field>
                        <Field label="Aadhaar" error={fieldErrors.aadhaar}>
                            <input value={form.aadhaar} onChange={(e) => setField('aadhaar', e.target.value.replace(/\D/g, '').slice(0, 12))} placeholder="12 digits" />
                        </Field>
                    </div>
                    <label className="pdd-check">
                        <input type="checkbox" checked={form.is_primary} onChange={(e) => setField('is_primary', e.target.checked)} />
                        <span>Primary member <em>(proprietary → yes; partnership / company → usually no)</em></span>
                    </label>

                    {/* Documents */}
                    <div className="pdd-section-label pdd-section-label--row">
                        Documents
                        <button className="pdd-add-doc" onClick={addDocRow} disabled={!form.gst_registration_id} type="button">
                            <Plus size={13} /> Add document
                        </button>
                    </div>
                    {!form.gst_registration_id && <div className="pdd-hint">Select a registration to load its document types.</div>}
                    {fieldErrors._docs && <div className="pdd-err">{fieldErrors._docs}</div>}

                    {docs.map((d, i) => (
                        <div key={i} className="pdd-doc-row">
                            <FormCustomSelect
                                name={`doc_type_${i}`}
                                value={d.document_type}
                                onChange={(e) => setDocType(i, e.target.value)}
                                options={optionsFromPairs([{ value: '', label: 'Document type…' },
                                    ...docTypes.filter((t) => t.value === d.document_type || !usedTypes.has(t.value))])}
                                placeholder="Document type"
                                ariaLabel="Document type"
                            />
                            <label className={`pdd-file ${d.document_url ? 'pdd-file--done' : ''}`}>
                                {d.uploading ? <Loader2 size={13} className="pdd-spin" />
                                    : d.document_url ? <CheckCircle2 size={13} /> : <Upload size={13} />}
                                <span>{d.fileName || 'Choose file'}</span>
                                <input type="file" accept="application/pdf,image/jpeg,image/png" hidden
                                    onChange={(e) => onFilePick(i, e.target.files?.[0])} />
                            </label>
                            <button className="pdd-doc-remove" onClick={() => removeDocRow(i)} type="button"><Trash2 size={14} /></button>
                        </div>
                    ))}
                </div>

                <div className="drawer-footer-v4">
                    <button className="btn-reset-v4" onClick={onClose} disabled={saving}>Cancel</button>
                    <button className="btn-apply-v4" onClick={save} disabled={saving || anyUploading}>
                        {saving ? 'Saving…' : anyUploading ? 'Uploading…' : 'Save person & documents'}
                    </button>
                </div>
            </div>
        </div>
    );
};

// ======================================================================= //
// View / edit a person + manage their documents
// ======================================================================= //
const PersonDetailDrawer = ({ person, canWrite, isAdmin, initialEditing = false, onClose, onChanged, setToast }) => {
    const [p, setP] = useState(person);
    const [editing, setEditing] = useState(initialEditing);
    const [form, setForm] = useState(person);
    const [busy, setBusy] = useState(false);
    const { docTypes } = useDocumentTypes(p.gst_registration_id);
    const docs = Array.isArray(p.documents) ? p.documents : [];
    const usedTypes = new Set(docs.map((d) => d.document_type));

    const refreshPerson = async () => {
        try {
            const res = await api.get(`/api/v1/person-document-details/${p.person_id}`);
            setP(res.data);
            onChanged();
        } catch { /* ignore */ }
    };

    const saveEdit = async () => {
        setBusy(true);
        try {
            await api.post(`/api/v1/person-document-details/${p.person_id}/edit`, {
                full_name: form.full_name,
                designation: form.designation,
                phone: form.phone || null,
                email: form.email || null,
                pan: form.pan || null,
                aadhaar: form.aadhaar || null,
                is_primary: !!form.is_primary,
            });
            setEditing(false);
            setToast({ message: 'Person updated.', type: 'success' });
            await refreshPerson();
        } catch (err) {
            setToast({ message: extractErrorMessage(err, 'Update failed.'), type: 'error' });
        } finally { setBusy(false); }
    };

    const downloadDoc = async (documentType) => {
        try {
            const res = await api.get(`/api/v1/person-document-details/${p.person_id}/documents/${encodeURIComponent(documentType)}/download`);
            if (res.data?.download_url) window.open(res.data.download_url, '_blank', 'noopener');
        } catch (err) {
            setToast({ message: extractErrorMessage(err, 'Could not open document.'), type: 'error' });
        }
    };

    const removeDoc = async (documentType) => {
        setBusy(true);
        try {
            const res = await api.delete(`/api/v1/person-document-details/${p.person_id}/documents/${encodeURIComponent(documentType)}`);
            setP(res.data);
            onChanged();
            setToast({ message: 'Document removed.', type: 'success' });
        } catch (err) {
            setToast({ message: extractErrorMessage(err, 'Remove failed.'), type: 'error' });
        } finally { setBusy(false); }
    };

    const addDoc = async (documentType, file) => {
        if (!documentType || !file) return;
        setBusy(true);
        try {
            const url = await uploadToBlob(file);
            const res = await api.post(`/api/v1/person-document-details/${p.person_id}/documents`, { document_type: documentType, document_url: url });
            setP(res.data);
            onChanged();
            setToast({ message: 'Document added.', type: 'success' });
        } catch (err) {
            setToast({ message: extractErrorMessage(err, 'Add failed.'), type: 'error' });
        } finally { setBusy(false); }
    };

    return (
        <div className="gst-filters-drawer-overlay" onClick={() => !busy && onClose()}>
            <div className="gst-filters-drawer pdd-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header-v4">
                    <h2><FileText size={18} /> {p.full_name}</h2>
                    <button className="btn-drawer-close" onClick={onClose}><X size={18} /></button>
                </div>

                <div className="drawer-content-v4 pdd-form">
                    <div className="pdd-section-label pdd-section-label--row">
                        Person details
                        {canWrite && !editing && (
                            <button className="pdd-add-doc" onClick={() => { setForm(p); setEditing(true); }} type="button">
                                <Pencil size={13} /> Edit
                            </button>
                        )}
                    </div>

                    {!editing ? (
                        <div className="pdd-kv">
                            <div><span>Registration</span><b className="ui-num">#{p.gst_registration_id}</b></div>
                            <div><span>Designation</span><b>{p.designation || '-'}</b></div>
                            <div><span>Phone</span><b className="ui-num">{p.phone || '-'}</b></div>
                            <div><span>Email</span><b>{p.email || '-'}</b></div>
                            <div><span>PAN</span><b>{p.pan || '-'}</b></div>
                            <div><span>Aadhaar</span><b>{p.aadhaar || '-'}</b></div>
                            <div><span>Primary</span><b>{p.is_primary ? 'Yes' : 'No'}</b></div>
                        </div>
                    ) : (
                        <>
                            <div className="pdd-grid-2">
                                <Field label="Full name"><input value={form.full_name || ''} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
                                <Field label="Designation"><input value={form.designation || ''} onChange={(e) => setForm({ ...form, designation: e.target.value })} /></Field>
                                <Field label="Phone"><input value={form.phone || ''} onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/\D/g, '').slice(0, 10) })} /></Field>
                                <Field label="Email"><input value={form.email || ''} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
                                <Field label="PAN"><input value={form.pan || ''} onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase().slice(0, 10) })} /></Field>
                                <Field label="Aadhaar"><input value={form.aadhaar || ''} onChange={(e) => setForm({ ...form, aadhaar: e.target.value.replace(/\D/g, '').slice(0, 12) })} /></Field>
                            </div>
                            <label className="pdd-check">
                                <input type="checkbox" checked={!!form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
                                <span>Primary member</span>
                            </label>
                            <div className="pdd-inline-actions">
                                <button className="btn-reset-v4" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
                                <button className="btn-apply-v4" onClick={saveEdit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                            </div>
                        </>
                    )}

                    <div className="pdd-section-label">Documents</div>
                    {canWrite && (
                        <AddDocInline docTypes={docTypes} usedTypes={usedTypes} onAdd={addDoc} disabled={busy} />
                    )}
                    {docs.length === 0 ? (
                        <div className="pdd-hint">No documents uploaded yet.</div>
                    ) : (
                        <div className="pdd-doc-list">
                            {docs.map((d) => (
                                <div key={d.document_type} className="pdd-doc-item">
                                    <span className="pdd-doc-item-name"><FileText size={14} /> {prettyType(d.document_type)}</span>
                                    <div className="pdd-doc-item-actions">
                                        <button title="Download" onClick={() => downloadDoc(d.document_type)}><Download size={14} /></button>
                                        {canWrite && <button title="Remove" className="pdd-danger" onClick={() => removeDoc(d.document_type)} disabled={busy}><Trash2 size={14} /></button>}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

// Add-document widget: pick a file → SEE a preview (image thumbnail or a file
// icon for PDFs) with its name → choose the document type → Save. The staged
// file is shown in the drawer body so you can look at it before tagging a type.
const AddDocInline = ({ docTypes, usedTypes, onAdd, disabled }) => {
    const [type, setType] = useState('');
    const [file, setFile] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null);
    const fileRef = useRef(null);
    const options = docTypes.filter((t) => !usedTypes.has(t.value));

    const pickFile = (f) => {
        setFile(f || null);
        setPreviewUrl(f && f.type?.startsWith('image/') ? URL.createObjectURL(f) : null);
    };
    const reset = () => {
        setType(''); setFile(null); setPreviewUrl(null);
        if (fileRef.current) fileRef.current.value = '';
    };
    const save = () => { if (type && file) { onAdd(type, file); reset(); } };

    // Free the object URL when it changes or the widget unmounts.
    useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

    return (
        <div className="pdd-add-doc-wrap">
            <input
                ref={fileRef}
                type="file"
                hidden
                accept="application/pdf,image/jpeg,image/png"
                onChange={(e) => pickFile(e.target.files?.[0])}
            />

            {!file ? (
                <button type="button" className="pdd-add-doc-btn" disabled={disabled} onClick={() => fileRef.current?.click()}>
                    <Upload size={14} /> Choose a file to add…
                </button>
            ) : (
                <div className="pdd-staged">
                    <div className="pdd-staged-preview">
                        {previewUrl ? <img src={previewUrl} alt={file.name} /> : <FileText size={56} />}
                    </div>
                    <div className="pdd-staged-body">
                        <div className="pdd-staged-name" title={file.name}>{file.name}</div>
                        <select
                            className="pdd-staged-select"
                            value={type}
                            disabled={disabled}
                            onChange={(e) => setType(e.target.value)}
                        >
                            <option value="">Select document type…</option>
                            {options.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                        </select>
                        <div className="pdd-staged-actions">
                            <button type="button" className="pdd-staged-change" onClick={() => fileRef.current?.click()} disabled={disabled}>
                                Change file
                            </button>
                            <span style={{ flex: 1 }} />
                            <button type="button" className="btn-reset-v4" onClick={reset} disabled={disabled}>Cancel</button>
                            <button type="button" className="btn-apply-v4" onClick={save} disabled={disabled || !type}>Save</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

const Field = ({ label, error, children }) => (
    <div className="pdd-field">
        <label>{label}</label>
        {children}
        {error && <div className="pdd-err">{error}</div>}
    </div>
);

export default GSTPeopleDocuments;
