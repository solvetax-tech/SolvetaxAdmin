import React, { useState, useEffect } from 'react';
import { XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import api from '../../utils/api';
import { createCrmLead, extractCrmApiErrorMessage } from '../../utils/crmLeadApi';
import { sanitizeGovIdInput } from '../../utils/inputSanitizers';

const unwrapList = (res) => {
    const d = res?.data;
    if (Array.isArray(d)) return d;
    if (Array.isArray(d?.data)) return d.data;
    if (Array.isArray(d?.items)) return d.items;
    return [];
};

/**
 * Create a CRM lead (GST or ITR) at stage FRESH_LEAD.
 *
 * Assignment is role-based (RM + OP are required on every lead):
 *  - RM creating  -> rm is auto-set to you; you pick the OP.
 *  - OP creating  -> op is auto-set to you; you pick the RM.
 *  - Admin / Sales Manager / Op Manager -> you pick both.
 * The server enforces these rules regardless of what's sent.
 */
export default function CreateLeadModal({ entityType, currentRole, onClose, onCreated }) {
    const isItr = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
    const roleU = (currentRole || '').trim().toUpperCase();
    const isRM = roleU === 'RM';
    const isOP = roleU === 'OP';
    const isAdmin = roleU === 'ADMIN';

    const [form, setForm] = useState({
        mobile: '', full_name: '', email: '', preferred_language: '',
        lead_source: '', lead_type: '', tag: '', ay: '', remarks: '',
        rm_id: '', op_id: '',
    });
    const [rmOptions, setRmOptions] = useState([]);
    const [opOptions, setOpOptions] = useState([]);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [fieldErrors, setFieldErrors] = useState({});
    // Lead source / type / tag / remarks are advanced — collapsed by default.
    const [showMore, setShowMore] = useState(false);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [rm, op] = await Promise.all([
                    api.get('/api/v1/employees/active-rm'),
                    api.get('/api/v1/employees/active-op'),
                ]);
                if (cancelled) return;
                setRmOptions(unwrapList(rm));
                setOpOptions(unwrapList(op));
            } catch { /* selects stay empty; backend still validates */ }
        })();
        return () => { cancelled = true; };
    }, []);

    const change = (e) => {
        const { name, value } = e.target;
        // Mobile restricted to 10 digits as they type (backend requires >= 10).
        setForm((prev) => ({ ...prev, [name]: sanitizeGovIdInput(name, value) }));
        setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
    };

    const submit = async (e) => {
        e.preventDefault();
        if (saving) return;
        const errs = {};
        const mobile = form.mobile.trim();
        if (mobile.replace(/\D/g, '').length < 10) errs.mobile = 'Enter a valid mobile number (at least 10 digits).';
        if (!isRM && !form.rm_id) errs.rm_id = 'Select an RM.';   // RM's own id is auto-set
        if (!isOP && !form.op_id) errs.op_id = 'Select an OP.';   // OP's own id is auto-set
        if (Object.keys(errs).length) { setFieldErrors(errs); return; }

        setSaving(true);
        setError(null);
        try {
            const body = { mobile };
            ['full_name', 'email', 'preferred_language', 'lead_source', 'lead_type', 'tag', 'remarks'].forEach((k) => {
                const v = form[k].trim();
                if (v) body[k] = v;
            });
            if (isItr && form.ay.trim()) body.ay = form.ay.trim();
            if (!isRM) body.rm_id = Number(form.rm_id);   // managers + OP send rm_id; RM's is forced to self
            if (!isOP) body.op_id = Number(form.op_id);   // managers + RM send op_id; OP's is forced to self

            const res = await createCrmLead(entityType, body);
            const msg = res?.duplicate
                ? 'A lead with this mobile already exists for this funnel.'
                : 'Lead created.';
            window.dispatchEvent(new CustomEvent('st_show_toast', { detail: { message: msg } }));
            onCreated?.(res);
            onClose?.();
        } catch (err) {
            const fields = err?.response?.data?.detail?.error?.fields;
            if (fields && typeof fields === 'object') setFieldErrors((p) => ({ ...p, ...fields }));
            setError(extractCrmApiErrorMessage(err, 'Could not create the lead.'));
        } finally {
            setSaving(false);
        }
    };

    const fieldStyle = {
        width: '100%', boxSizing: 'border-box', background: 'var(--bg-input)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '10px 12px',
        color: 'var(--text-primary)', fontSize: '14px', outline: 'none', fontFamily: 'inherit',
    };
    const roReadonly = { ...fieldStyle, opacity: 0.7, cursor: 'not-allowed' };
    const req = <span style={{ color: 'var(--danger)' }}>*</span>;
    const moreToggleStyle = {
        display: 'inline-flex', alignItems: 'center', gap: '6px',
        background: 'transparent', border: 'none', padding: '4px 0',
        color: 'var(--accent, #8b5cf6)', fontSize: '13px', fontWeight: 600,
        cursor: 'pointer', fontFamily: 'inherit',
    };

    return (
        <div className="gst-filters-drawer-overlay" onClick={() => !saving && onClose?.()}>
            <div className="gst-filters-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header">
                    <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        New {isItr ? 'Income Tax' : 'GST'} Lead
                    </h2>
                    <button className="btn-drawer-close" onClick={() => onClose?.()} disabled={saving}><XCircle size={20} /></button>
                </div>

                <form onSubmit={submit} style={{ display: 'contents' }}>
                    <div className="drawer-content">
                        {error && <div className="error-banner" style={{ marginBottom: '14px' }}><span>{error}</span></div>}

                        <div className="filter-section-v4">
                            <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                <label>Mobile {req}</label>
                                <input type="tel" name="mobile" value={form.mobile} onChange={change} placeholder="10-digit mobile" maxLength={10} inputMode="numeric" />
                                {fieldErrors.mobile && <span className="field-error-msg">{fieldErrors.mobile}</span>}
                            </div>
                            <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                <label>Full name</label>
                                <input type="text" name="full_name" value={form.full_name} onChange={change} placeholder="Optional" maxLength={200} />
                            </div>

                            {/* Assignment — RM & OP required, role-based */}
                            <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '12px', marginBottom: '12px' }}>
                                <div className="filter-group-v4">
                                    <label>RM {isRM ? '' : req}</label>
                                    {isRM ? (
                                        <input value="You (auto-assigned)" readOnly disabled style={roReadonly} />
                                    ) : (
                                        <select name="rm_id" value={form.rm_id} onChange={change} style={fieldStyle}>
                                            <option value="">Select RM</option>
                                            {rmOptions.map((o) => <option key={o.emp_id} value={o.emp_id}>{o.username}</option>)}
                                        </select>
                                    )}
                                    {fieldErrors.rm_id && <span className="field-error-msg">{fieldErrors.rm_id}</span>}
                                </div>
                                <div className="filter-group-v4">
                                    <label>OP {isOP ? '' : req}</label>
                                    {isOP ? (
                                        <input value="You (auto-assigned)" readOnly disabled style={roReadonly} />
                                    ) : (
                                        <select name="op_id" value={form.op_id} onChange={change} style={fieldStyle}>
                                            <option value="">Select OP</option>
                                            {opOptions.map((o) => <option key={o.emp_id} value={o.emp_id}>{o.username}</option>)}
                                        </select>
                                    )}
                                    {fieldErrors.op_id && <span className="field-error-msg">{fieldErrors.op_id}</span>}
                                </div>
                            </div>

                            <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '12px', marginBottom: '12px' }}>
                                <div className="filter-group-v4">
                                    <label>Email</label>
                                    <input type="email" name="email" value={form.email} onChange={change} placeholder="Optional" maxLength={255} />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Preferred language</label>
                                    <input type="text" name="preferred_language" value={form.preferred_language} onChange={change} placeholder="Optional" maxLength={50} />
                                </div>
                            </div>

                            {/* Assessment year (ITR only) stays visible */}
                            {isItr && (
                                <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                    <label>Assessment year</label>
                                    <input type="text" name="ay" value={form.ay} onChange={change} placeholder="e.g. 2024-25 (optional)" maxLength={20} />
                                </div>
                            )}

                            {/* Advanced fields — admin only; collapsed by default, shown on demand */}
                            {isAdmin && (
                                <button type="button" onClick={() => setShowMore((v) => !v)} style={moreToggleStyle}>
                                    {showMore ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                                    {showMore ? 'Hide extra details' : 'Add more details'}
                                </button>
                            )}

                            {isAdmin && showMore && (
                                <div style={{ marginTop: '12px' }}>
                                    <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '12px', marginBottom: '12px' }}>
                                        <div className="filter-group-v4">
                                            <label>Lead source</label>
                                            <input type="text" name="lead_source" value={form.lead_source} onChange={change} placeholder="Default: MANUAL" maxLength={100} />
                                        </div>
                                        <div className="filter-group-v4">
                                            <label>Lead type</label>
                                            <input type="text" name="lead_type" value={form.lead_type} onChange={change} placeholder="Optional" maxLength={50} />
                                        </div>
                                    </div>
                                    <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                        <label>Tag</label>
                                        <input type="text" name="tag" value={form.tag} onChange={change} placeholder="Optional" maxLength={100} />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Remarks</label>
                                        <textarea name="remarks" value={form.remarks} onChange={change} rows={2} placeholder="Optional" maxLength={2000}
                                            style={{ ...fieldStyle, resize: 'vertical' }} />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="drawer-footer">
                        <button type="button" className="btn-reset-v4" onClick={() => onClose?.()} disabled={saving}>Cancel</button>
                        <button type="submit" className="btn-apply-v4" disabled={saving}>{saving ? 'Creating…' : 'Create Lead'}</button>
                    </div>
                </form>
            </div>
        </div>
    );
}
