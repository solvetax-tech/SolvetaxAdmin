import React, { useState } from 'react';
import { XCircle } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import {
    patchIssue, ISSUE_STATUSES, ISSUE_PRIORITIES, STATUS_LABEL, PRIORITY_LABEL,
} from '../../utils/issuesApi';

const STATUS_OPTIONS = optionsFromPairs(ISSUE_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] })));
const PRIORITY_OPTIONS = optionsFromPairs(ISSUE_PRIORITIES.map((p) => ({ value: p, label: PRIORITY_LABEL[p] })));

/**
 * Edit an issue's status / priority / resolution note. Every change is an
 * explicit Save (no accidental one-click resolves). PATCHes /issue-reports/{id}.
 */
export default function EditIssueModal({ issue, onClose, onSaved }) {
    const [form, setForm] = useState({
        status: issue.status || 'OPEN',
        priority: issue.priority || 'MEDIUM',
        resolution_note: issue.resolution_note || '',
    });
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const change = (e) => {
        const { name, value } = e.target;
        setForm((prev) => ({ ...prev, [name]: value }));
    };

    const submit = async (e) => {
        e.preventDefault();
        if (saving) return;
        setSaving(true);
        setError(null);
        try {
            const body = { status: form.status, priority: form.priority };
            const note = form.resolution_note.trim();
            // Only send a note when there is one, or to clear it if it changed.
            if (note !== (issue.resolution_note || '')) body.resolution_note = note;
            await patchIssue(issue.id, body);
            onSaved?.();
            onClose?.();
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || err?.message || 'Could not update the issue.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="gst-filters-drawer-overlay" onClick={() => !saving && onClose?.()}>
            <div className="gst-filters-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header">
                    <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>Edit Issue</h2>
                    <button className="btn-drawer-close" onClick={() => onClose?.()} disabled={saving}>
                        <XCircle size={20} />
                    </button>
                </div>

                <form onSubmit={submit} style={{ display: 'contents' }}>
                    <div className="drawer-content">
                        {error && <div className="error-banner" style={{ marginBottom: '14px' }}><span>{error}</span></div>}

                        <div className="filter-section-v4">
                            <div className="filter-group-v4" style={{ marginBottom: '4px' }}>
                                <label style={{ opacity: 0.6 }}>{issue.title}</label>
                            </div>

                            <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '12px', marginBottom: '12px' }}>
                                <div className="filter-group-v4">
                                    <label>Status</label>
                                    <FormCustomSelect
                                        name="status" value={form.status} onChange={change}
                                        options={STATUS_OPTIONS} placeholder="Open" ariaLabel="Status"
                                    />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Priority</label>
                                    <FormCustomSelect
                                        name="priority" value={form.priority} onChange={change}
                                        options={PRIORITY_OPTIONS} placeholder="Medium" ariaLabel="Priority"
                                    />
                                </div>
                            </div>

                            <div className="filter-group-v4">
                                <label>Resolution / note <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(optional)</span></label>
                                <textarea
                                    name="resolution_note"
                                    value={form.resolution_note}
                                    onChange={change}
                                    placeholder="What was done, or any note for the record"
                                    rows={4}
                                    style={{
                                        width: '100%', boxSizing: 'border-box', background: 'var(--bg-input)',
                                        border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
                                        padding: '12px', color: 'var(--text-primary)', fontSize: '14px',
                                        outline: 'none', resize: 'vertical', fontFamily: 'inherit',
                                    }}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="drawer-footer">
                        <button type="button" className="btn-reset-v4" onClick={() => onClose?.()} disabled={saving}>Cancel</button>
                        <button type="submit" className="btn-apply-v4" disabled={saving}>{saving ? 'Saving…' : 'Save Changes'}</button>
                    </div>
                </form>
            </div>
        </div>
    );
}
