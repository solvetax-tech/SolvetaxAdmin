import React, { useState, useRef } from 'react';
import { XCircle, Upload, X, Loader2, Image as ImageIcon } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import { createIssue, uploadIssuePhoto, ISSUE_PRIORITIES, PRIORITY_LABEL } from '../../utils/issuesApi';
import './RaiseIssueModal.css';

const EMPTY = { title: '', description: '', priority: 'MEDIUM' };
const ALLOWED = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
const MAX_BYTES = 10 * 1024 * 1024;
const MAX_PHOTOS = 10;

const PRIORITY_OPTIONS = optionsFromPairs(
    ISSUE_PRIORITIES.map((p) => ({ value: p, label: PRIORITY_LABEL[p] })),
);

/**
 * Drawer to raise an issue. Photos upload to the backend as they're picked
 * (each returns a blob URL); create sends the collected photo_urls.
 */
export default function RaiseIssueModal({ onClose, onCreated }) {
    const [form, setForm] = useState(EMPTY);
    const [photos, setPhotos] = useState([]); // { blob_url, name }
    const [uploading, setUploading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [fieldErrors, setFieldErrors] = useState({});
    const fileRef = useRef(null);

    const change = (e) => {
        const { name, value } = e.target;
        setForm((prev) => ({ ...prev, [name]: value }));
        setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
    };

    const pickFiles = async (e) => {
        const files = Array.from(e.target.files || []);
        e.target.value = ''; // allow re-picking the same file
        if (files.length === 0) return;
        if (photos.length + files.length > MAX_PHOTOS) {
            setError(`Up to ${MAX_PHOTOS} photos.`);
            return;
        }
        setError(null);
        setUploading(true);
        try {
            for (const file of files) {
                if (!ALLOWED.includes(file.type)) {
                    setError(`"${file.name}" is not a supported image type.`);
                    continue;
                }
                if (file.size > MAX_BYTES) {
                    setError(`"${file.name}" exceeds the 10MB limit.`);
                    continue;
                }
                const blobUrl = await uploadIssuePhoto(file);
                if (blobUrl) setPhotos((prev) => [...prev, { blob_url: blobUrl, name: file.name }]);
            }
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || 'Photo upload failed.');
        } finally {
            setUploading(false);
        }
    };

    const removePhoto = (blobUrl) => setPhotos((prev) => prev.filter((p) => p.blob_url !== blobUrl));

    const submit = async (e) => {
        e.preventDefault();
        if (saving || uploading) return;

        const errs = {};
        if (form.title.trim().length < 3) errs.title = 'Enter a short title (at least 3 characters).';
        if (form.description.trim().length < 1) errs.description = 'Describe the issue.';
        if (Object.keys(errs).length) {
            setFieldErrors(errs);
            return;
        }

        setSaving(true);
        setError(null);
        try {
            await createIssue({
                title: form.title.trim(),
                description: form.description.trim(),
                priority: form.priority,
                photo_urls: photos.map((p) => p.blob_url),
            });
            onCreated?.();
            onClose?.();
        } catch (err) {
            const status = err?.response?.status;
            const detail = err?.response?.data?.detail;
            const fields = detail?.error?.fields;
            if (status === 400 && fields) {
                setFieldErrors(fields);
                setError(detail?.error?.message || 'Please check the values.');
            } else if (status === 422) {
                const first = Array.isArray(detail?.errors) ? detail.errors[0] : null;
                setError(first?.msg || 'Please check the values entered.');
            } else {
                setError((typeof detail === 'string' && detail) || err?.message || 'Failed to raise the issue.');
            }
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="gst-filters-drawer-overlay" onClick={() => !saving && !uploading && onClose?.()}>
            <div className="gst-filters-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header">
                    <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>Report an Issue</h2>
                    <button className="btn-drawer-close" onClick={() => onClose?.()} disabled={saving}>
                        <XCircle size={20} />
                    </button>
                </div>

                <form onSubmit={submit} style={{ display: 'contents' }}>
                    <div className="drawer-content">
                        {error && (
                            <div className="error-banner" style={{ marginBottom: '14px' }}><span>{error}</span></div>
                        )}

                        <div className="filter-section-v4">
                            <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                <label>Title <span style={{ color: 'var(--danger)' }}>*</span></label>
                                <input
                                    type="text"
                                    name="title"
                                    value={form.title}
                                    onChange={change}
                                    placeholder="Short summary of the issue"
                                    maxLength={200}
                                />
                                {fieldErrors.title && <span className="field-error-msg">{fieldErrors.title}</span>}
                            </div>

                            <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                <label>Priority</label>
                                <FormCustomSelect
                                    name="priority"
                                    value={form.priority}
                                    onChange={change}
                                    options={PRIORITY_OPTIONS}
                                    placeholder="Medium"
                                    ariaLabel="Priority"
                                />
                            </div>

                            <div className="filter-group-v4">
                                <label>Description <span style={{ color: 'var(--danger)' }}>*</span></label>
                                <textarea
                                    name="description"
                                    value={form.description}
                                    onChange={change}
                                    placeholder="What happened? Steps to reproduce, what you expected, etc."
                                    rows={5}
                                    style={{
                                        width: '100%', boxSizing: 'border-box', background: 'var(--bg-input)',
                                        border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
                                        padding: '12px', color: 'var(--text-primary)', fontSize: '14px',
                                        outline: 'none', resize: 'vertical', fontFamily: 'inherit',
                                    }}
                                />
                                {fieldErrors.description && <span className="field-error-msg">{fieldErrors.description}</span>}
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <div className="filter-group-v4">
                                <label>Photos <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(optional)</span></label>
                                <input
                                    ref={fileRef}
                                    type="file"
                                    accept="image/png,image/jpeg,image/webp,image/gif"
                                    multiple
                                    onChange={pickFiles}
                                    style={{ display: 'none' }}
                                />
                                <button
                                    type="button"
                                    onClick={() => fileRef.current?.click()}
                                    disabled={uploading || photos.length >= MAX_PHOTOS}
                                    style={{
                                        display: 'inline-flex', alignItems: 'center', gap: '8px', alignSelf: 'flex-start',
                                        padding: '9px 14px', background: 'transparent', border: '1px dashed var(--border-strong)',
                                        borderRadius: 'var(--radius-md)', color: 'var(--text-muted)', fontSize: '12px',
                                        fontWeight: 700, cursor: 'pointer',
                                    }}
                                >
                                    {uploading ? <Loader2 size={14} className="raise-issue-spin" /> : <Upload size={14} />}
                                    {uploading ? 'Uploading…' : 'Add photos'}
                                </button>

                                {photos.length > 0 && (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '10px' }}>
                                        {photos.map((p) => (
                                            <div key={p.blob_url} style={{
                                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                                gap: '10px', padding: '8px 10px', background: 'var(--bg-surface-2)',
                                                border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)',
                                            }}>
                                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                                                    <ImageIcon size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                                                    <span style={{ fontSize: '12px', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                                                </span>
                                                <button type="button" onClick={() => removePhoto(p.blob_url)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', flexShrink: 0 }}>
                                                    <X size={14} />
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="drawer-footer">
                        <button type="button" className="btn-reset-v4" onClick={() => onClose?.()} disabled={saving}>Cancel</button>
                        <button type="submit" className="btn-apply-v4" disabled={saving || uploading}>
                            {saving ? 'Submitting…' : 'Submit Issue'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
