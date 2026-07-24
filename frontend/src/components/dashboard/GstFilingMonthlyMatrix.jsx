import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../../utils/api';
import { CheckCircle2, Copy, CreditCard, Eye, EyeOff, ExternalLink, Link2, Loader2, Pencil, RotateCcw, Search, X } from 'lucide-react';
import AddDocumentLinkModal from '../gst_filings/AddDocumentLinkModal';
import { fetchGstFilingMonthlyMatrix, parseGstFilingFocusFromSearch } from '../../utils/dashboardApi';
import { patchReturnDetailStatus, resolveReturnDetailIdForForm } from '../../utils/gstFilingReturnApi';
import { getAnchorRect, getViewportSize } from '../../utils/zoom';
import {
    GST_FILING_STATUS_LABELS,
    GST_RETURN_DETAIL_STATUSES,
    GST_RETURN_FORM_OPTIONS,
    GST_RETURN_FORM_FOLLOWUP_FIELDS,
    GST_RETURN_FORM_STATUS_FIELDS,
    getGstReturnStatusChipClass,
    gstReturnDetailEditableStatusOptions,
} from '../../utils/gstFilingStatusConstants';
import Pagination from '../common/Pagination';
import GfmFollowupDateFilter, { normalizeFollowupDateList } from './GfmFollowupDateFilter';
import GfmMonthFilter, { normalizeGfmPeriodList } from './GfmMonthFilter';
import GfmStatusFilter from './GfmStatusFilter';
import GfmFormFilter from './GfmFormFilter';
import '../common/Filters.css';
import './GstFilingMonthlyMatrix.css';

const ROWS_PER_PAGE = 25;
const MONTH_COUNT = 6;

const createEmptyFilters = () => ({
    phone: '',
    business_name: '',
    followup_dates: [],
    months: [],
    statuses: [],
    forms: [],
    followup_scheduled: false,
    remaining_payment: false,
});

const ALLOWED_RETURN_STATUSES = new Set(
    GST_RETURN_DETAIL_STATUSES.filter((value) => value !== 'OVERDUE'),
);

const ALLOWED_RETURN_FORMS = new Set(GST_RETURN_FORM_OPTIONS.map((item) => item.value));

const normalizeStatusList = (statuses = []) => (
    [...new Set(
        (Array.isArray(statuses) ? statuses : [])
            .map((value) => String(value).trim().toUpperCase())
            .filter((value) => ALLOWED_RETURN_STATUSES.has(value)),
    )]
);

const normalizeFormList = (forms = []) => (
    [...new Set(
        (Array.isArray(forms) ? forms : [])
            .map((value) => String(value).trim().toUpperCase())
            .filter((value) => ALLOWED_RETURN_FORMS.has(value)),
    )]
);

const normalizeAppliedFilters = (filters) => ({
    ...filters,
    followup_dates: normalizeFollowupDateList(filters.followup_dates),
    months: normalizeGfmPeriodList(filters.months),
    statuses: normalizeStatusList(filters.statuses),
    forms: normalizeFormList(filters.forms),
    followup_scheduled: Boolean(filters.followup_scheduled),
    remaining_payment: Boolean(filters.remaining_payment),
});

function getMatrixFilterConfig(appliedFilters) {
    const statuses = normalizeStatusList(appliedFilters?.statuses);
    const forms = normalizeFormList(appliedFilters?.forms);
    const followup_scheduled = Boolean(appliedFilters?.followup_scheduled);
    const remaining_payment = Boolean(appliedFilters?.remaining_payment);
    return {
        active: statuses.length > 0 || forms.length > 0 || followup_scheduled || remaining_payment,
        statuses,
        forms,
        followup_scheduled,
        remaining_payment,
    };
}

/**
 * A form selection narrows WHICH forms the other filters inspect (AND), rather
 * than being another OR'd term — "GSTR-1 + MISSED" means GSTR-1 that is MISSED.
 * Returns null when the group has none of the selected forms.
 */
function scopeGroupForms(groupForms, filterConfig) {
    const selected = filterConfig?.forms || [];
    if (!selected.length) return groupForms;
    const scoped = groupForms.filter((key) => selected.includes(key));
    return scoped.length ? scoped : null;
}

/** @deprecated alias — use getMatrixFilterConfig */
function getStatusFilterConfig(appliedFilters) {
    return getMatrixFilterConfig(appliedFilters);
}

function cellMatchesFollowupScheduled(cell, groupForms) {
    const forms = cell?.forms || {};
    return groupForms.some((key) => hasFormData(forms[key]) && forms[key]?.followup_at);
}

function cellMatchesReturnStatuses(cell, groupForms, statuses) {
    const forms = cell?.forms || {};
    return groupForms.some((key) => {
        const form = forms[key];
        if (!hasFormData(form)) return false;
        const status = (form?.status || '').trim().toUpperCase();
        return statuses.includes(status);
    });
}

function formMatchesMatrixFilters(form, filterConfig, { cell, groupForms } = {}) {
    if (!filterConfig?.active) return true;
    if (!hasFormData(form)) return false;

    const matches = [];
    if (filterConfig.followup_scheduled && form.followup_at) {
        matches.push(true);
    }
    if (filterConfig.remaining_payment && cell && groupForms) {
        matches.push(cellHasRemainingPayment(cell, groupForms));
    }
    if (filterConfig.statuses.length > 0) {
        const status = (form?.status || '').trim().toUpperCase();
        matches.push(filterConfig.statuses.includes(status));
    }
    // Forms picked on their own — the caller already scoped by form key.
    if (!matches.length) return true;
    return matches.some(Boolean);
}

function cellMatchesMatrixFilters(cell, groupForms, filterConfig) {
    if (!filterConfig?.active) return true;

    const scoped = scopeGroupForms(groupForms, filterConfig);
    if (!scoped) return false;

    const matches = [];
    if (filterConfig.followup_scheduled) {
        matches.push(cellMatchesFollowupScheduled(cell, scoped));
    }
    if (filterConfig.remaining_payment) {
        matches.push(cellHasRemainingPayment(cell, scoped));
    }
    if (filterConfig.statuses.length > 0) {
        matches.push(cellMatchesReturnStatuses(cell, scoped, filterConfig.statuses));
    }
    // Forms picked on their own: keep any cell carrying one of those returns.
    if (!matches.length) return cellHasDataForGroup(cell, scoped);
    return matches.some(Boolean);
}

function cellHasRemainingPayment(cell, groupForms) {
    if (!cellHasDataForGroup(cell, groupForms)) return false;
    const payment = getPaymentFieldsFromCell(cell);
    if (payment.paymentCompleted) return false;
    const remaining = Number(payment.paymentRemainingAmount);
    return Number.isFinite(remaining) && remaining > 0;
}

const FORM_ROWS = GST_RETURN_FORM_OPTIONS.map((item) => ({
    key: item.value,
    label: item.label,
}));

/** One matrix row per return family — payments tracked per row / return-detail ID. */
const GFM_RETURN_GROUPS = [
    { key: 'REGULAR', label: 'GSTR-1 / GSTR-3B', forms: ['GSTR1', 'GSTR3B'] },
    { key: 'CMP08', label: 'CMP-08', forms: ['CMP08'] },
    { key: 'ANNUAL_9', label: 'GSTR-9 / GSTR-9C', forms: ['GSTR9', 'GSTR9C'] },
    { key: 'GSTR4', label: 'GSTR-4', forms: ['GSTR4'] },
];

function getApiErrorMessage(err, fallback = 'Request failed') {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
    return err?.message || fallback;
}

function formatCurrency(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return '0.00';
    return amount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function getPaymentFieldsFromCell(cell) {
    return {
        paymentCompleted: Boolean(cell?.payment_completed),
        paymentStatus: cell?.payment_status || null,
        paymentId: cell?.payment_id ?? null,
        paymentRemainingAmount: cell?.payment_remaining_amount,
        paymentPaidAmount: cell?.payment_paid_amount,
        paymentNetAmount: cell?.payment_net_amount,
    };
}

function formatDueDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yy = d.getFullYear();
    return `${dd}/${mm}/${yy}`;
}

function formatFollowupDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const date = formatDueDate(iso);
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${date} ${hh}:${min}`;
}

function toDatetimeLocalValue(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromDatetimeLocalValue(local) {
    if (!local) return null;
    const d = new Date(local);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString();
}

function isFollowupOverdue(iso) {
    if (!iso) return false;
    const d = new Date(iso);
    return !Number.isNaN(d.getTime()) && d.getTime() < Date.now();
}

function getCellFormOptions(cell, groupForms = null) {
    const forms = cell?.forms || {};
    return FORM_ROWS
        .filter(({ key }) => (!groupForms || groupForms.includes(key)) && hasFormData(forms[key]))
        .map(({ key, label }) => ({
            key,
            label,
            followupAt: forms[key]?.followup_at || null,
            returnDetailId: forms[key]?.return_detail_id || cell?.return_detail_id || null,
        }));
}

function rowHasGroupData(row, months, groupForms) {
    return months.some((period) => cellHasDataForGroup(row.months?.[period], groupForms));
}

function expandCustomerToGroupRows(
    customerRows,
    months,
    matrixFilterConfig = null,
) {
    const expanded = [];
    for (const row of customerRows) {
        const activeGroups = GFM_RETURN_GROUPS.filter((group) => {
            if (!rowHasGroupData(row, months, group.forms)) return false;
            if (!matrixFilterConfig?.active) return true;
            return months.some((period) => (
                cellMatchesMatrixFilters(row.months?.[period], group.forms, matrixFilterConfig)
            ));
        });
        activeGroups.forEach((group, index) => {
            expanded.push({
                ...row,
                groupKey: group.key,
                groupLabel: group.label,
                groupForms: group.forms,
                isFirstGroupRow: index === 0,
                rowKey: `${row.customer_id}-${group.key}`,
            });
        });
    }
    return expanded;
}

function getRowFollowupSummary(row, months, groupForms) {
    const items = [];
    for (const period of months) {
        const cell = row.months?.[period];
        if (!cellHasDataForGroup(cell, groupForms)) continue;
        for (const { key, label } of getCellFormOptions(cell, groupForms)) {
            const followupAt = cell.forms?.[key]?.followup_at;
            if (!followupAt) continue;
            const time = new Date(followupAt).getTime();
            if (Number.isNaN(time)) continue;
            items.push({
                period,
                cell,
                formKey: key,
                formLabel: label,
                followupAt,
                returnDetailId: cell.forms?.[key]?.return_detail_id || cell.return_detail_id || null,
                time,
            });
        }
    }
    if (!items.length) return null;
    const now = Date.now();
    const upcoming = items.filter((item) => item.time >= now).sort((a, b) => a.time - b.time);
    if (upcoming.length) return upcoming[0];
    return items.sort((a, b) => b.time - a.time)[0];
}

/**
 * The filing a row's Actions column targets: the first cell carrying a filing_id
 * scanning `months`, which is ordered newest-first — so this is the most recent
 * filing in the visible range. One sheet covers all returns on a filing, so a
 * single view-or-add action per row is enough.
 */
function getRowFilingTarget(row, months) {
    for (const period of months) {
        const cell = row.months?.[period];
        if (cell?.filing_id) {
            return {
                filingId: cell.filing_id,
                documentUrl: cell.document_url || null,
                // Portal login lives on the filing; identical across its returns.
                emailId: cell.filing_email_id || '',
                username: cell.filing_username || '',
                password: cell.filing_password || '',
                mobile: row.mobile || '',
                period,
            };
        }
    }
    return null;
}

/**
 * Portal login for the row's filing, shown under the customer name.
 * Password is masked until revealed, matching the filing form's own toggle.
 */
/**
 * Editor for the portal login on one filing. PATCHes only the three credential
 * fields — GSTFilingEditIn is a partial update, so nothing else is touched.
 */
export function GfmIdentityEditor({ target, onClose, onSaved }) {
    const [form, setForm] = useState({ email_id: '', username: '', password: '' });
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [revealed, setRevealed] = useState(false);

    useEffect(() => {
        if (!target) return;
        setForm({
            email_id: target.emailId || '',
            username: target.username || '',
            password: target.password || '',
        });
        setError(null);
        setRevealed(false);
    }, [target]);

    if (!target) return null;

    const submit = async (e) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        try {
            // Dedicated endpoint: writes the filing and mirrors the same
            // credentials onto its linked GST registration in one transaction.
            // Blank values are normalised to null server-side, i.e. cleared.
            await api.patch(`/api/v1/gst-filings/${target.filingId}/portal-login`, {
                email_id: form.email_id,
                username: form.username,
                password: form.password,
            });
            onSaved?.();
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError(
                typeof detail === 'string'
                    ? detail
                    : (Array.isArray(detail) && detail[0]?.msg) || 'Failed to update portal login.',
            );
        } finally {
            setSaving(false);
        }
    };

    return createPortal(
        <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={onClose}>
            <div
                className="gst-modal-card-v4 app-drawer-panel gst-reg-side-drawer-shell"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="modal-header-v4">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4"><Pencil size={20} /></div>
                        <div className="modal-title-box">
                            <h2>Portal Login</h2>
                            <p className="modal-subtitle-v4">
                                Filing ID {target.filingId} · {target.period} · also updates the linked GST registration
                            </p>
                        </div>
                    </div>
                    <button className="btn-drawer-close" onClick={onClose}><X size={20} /></button>
                </div>

                <form onSubmit={submit} className="modal-form-v4">
                    <div className="form-scroll-container">
                        {error && <p className="error-text-v4">{error}</p>}
                        <div className="form-section-group">
                            <h3 className="section-title">Filing Identity</h3>
                            <div className="form-group-v4 full-width" style={{ width: '100%', marginBottom: '18px' }}>
                                <label className="modal-label-caps">Email ID (Portal)</label>
                                <input
                                    type="email"
                                    className="modal-input-v4"
                                    placeholder="portal@example.com"
                                    value={form.email_id}
                                    onChange={(e) => setForm((p) => ({ ...p, email_id: e.target.value }))}
                                />
                            </div>
                            <div className="form-group-v4 full-width" style={{ width: '100%', marginBottom: '18px' }}>
                                <label className="modal-label-caps">Username</label>
                                <input
                                    type="text"
                                    className="modal-input-v4"
                                    placeholder="Portal username"
                                    value={form.username}
                                    onChange={(e) => setForm((p) => ({ ...p, username: e.target.value }))}
                                />
                            </div>
                            <div className="form-group-v4 full-width" style={{ width: '100%' }}>
                                <label className="modal-label-caps">Password (Internal)</label>
                                <div style={{ position: 'relative' }}>
                                    <input
                                        type={revealed ? 'text' : 'password'}
                                        className="modal-input-v4"
                                        placeholder="Portal password"
                                        value={form.password}
                                        onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setRevealed((v) => !v)}
                                        aria-label={revealed ? 'Hide password' : 'Reveal password'}
                                        style={{
                                            position: 'absolute', right: '10px', top: '50%',
                                            transform: 'translateY(-50%)', background: 'none',
                                            border: 'none', cursor: 'pointer', color: 'var(--text-secondary)',
                                            display: 'flex', alignItems: 'center',
                                        }}
                                    >
                                        {revealed ? <EyeOff size={15} /> : <Eye size={15} />}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="modal-footer-v4">
                        <div className="footer-actions-v4">
                            <button type="button" className="dark-outline" onClick={onClose}>Cancel</button>
                            <button
                                type="submit"
                                className="minimal-btn"
                                disabled={saving}
                                style={{
                                    background: 'var(--emerald-success)', color: 'var(--text-primary)',
                                    border: 'none', borderRadius: '100px', fontWeight: '700',
                                    padding: '10px 24px', display: 'flex', alignItems: 'center',
                                    gap: '8px', cursor: saving ? 'not-allowed' : 'pointer',
                                    opacity: saving ? 0.7 : 1,
                                }}
                            >
                                {saving ? (<><Loader2 size={16} className="refresh-spin" /> Saving…</>) : 'Save'}
                            </button>
                        </div>
                    </div>
                </form>
            </div>
        </div>,
        document.body,
    );
}

function GfmFilingIdentity({ target, onEdit }) {
    if (!target) return null;
    const { emailId, username, password, mobile } = target;
    if (!emailId && !username && !password && !mobile) {
        return (
            <button
                type="button"
                className="gfm-identity-add"
                title={`Add portal login for filing ${target.filingId}`}
                onClick={() => onEdit(target)}
            >
                <Pencil size={11} /> Add login
            </button>
        );
    }

    return (
        <div className="gfm-identity">
            {emailId && (
                <span className="gfm-identity-row" title={emailId}>
                    <span className="gfm-identity-label">Email</span>
                    <span className="gfm-identity-value">{emailId}</span>
                </span>
            )}
            {mobile && (
                <span className="gfm-identity-row" title={mobile}>
                    <span className="gfm-identity-label">Mobile</span>
                    <span className="gfm-identity-value">{mobile}</span>
                </span>
            )}
            {username && (
                <span className="gfm-identity-row" title={username}>
                    <span className="gfm-identity-label">User</span>
                    <span className="gfm-identity-value">{username}</span>
                </span>
            )}
            {password && (
                <span className="gfm-identity-row">
                    <span className="gfm-identity-label">Pass</span>
                    <span className="gfm-identity-value">••••••••</span>
                    <button
                        type="button"
                        className="gfm-identity-icon-btn"
                        title="Copy password"
                        aria-label="Copy password"
                        onClick={() => navigator.clipboard?.writeText(String(password || ''))}
                    >
                        <Copy size={11} />
                    </button>
                </span>
            )}
            <button
                type="button"
                className="gfm-identity-add"
                title={`Edit portal login for filing ${target.filingId}`}
                onClick={() => onEdit(target)}
            >
                <Pencil size={11} /> Edit login
            </button>
        </div>
    );
}

function formatMonthHeader(period) {
    if (!period) return '—';
    const [mon, year] = period.split('-');
    if (!mon || !year) return period;
    return `${mon} '${String(year).slice(-2)}`;
}

function formatFormStatus(status) {
    const s = (status || '').trim().toUpperCase();
    if (s && GST_FILING_STATUS_LABELS[s]) return GST_FILING_STATUS_LABELS[s];
    return '—';
}

function hasFormData(form) {
    return Boolean(form?.due_date);
}

function cellHasDataForGroup(cell, groupForms) {
    if (!cell || !groupForms?.length) return false;
    const forms = cell.forms || {};
    return groupForms.some((key) => hasFormData(forms[key]));
}

/** One payment target per month cell per return group (GSTR-1/3B share one return-detail row). */
function getCellPaymentTarget(cell, groupForms) {
    if (!cellHasDataForGroup(cell, groupForms)) return null;

    const forms = cell.forms || {};
    const filingId = cell.filing_id ? Number(cell.filing_id) : null;
    const cellId = Number(cell.return_detail_id);

    const paymentFields = getPaymentFieldsFromCell(cell);

    if (cellId) {
        return {
            returnDetailId: cellId,
            filingId,
            ...paymentFields,
        };
    }

    for (const key of groupForms) {
        const form = forms[key];
        const formId = Number(form?.return_detail_id);
        if (hasFormData(form) && formId) {
            return {
                returnDetailId: formId,
                filingId,
                ...paymentFields,
            };
        }
    }

    return null;
}

function GfmPaymentFooter({
    returnDetailId,
    filingId,
    paymentTarget,
    compact = false,
    onRecordPayment,
}) {
    if (!paymentTarget?.returnDetailId) return null;

    const remaining = Number(paymentTarget.paymentRemainingAmount);
    const hasRemaining = Number.isFinite(remaining) && remaining > 0;
    const payTitle = hasRemaining
        ? `Pay remaining ₹${formatCurrency(remaining)} for return ID ${returnDetailId}`
        : paymentTarget.paymentStatus === 'PENDING'
            ? `Continue payment for return ID ${returnDetailId}`
            : `Record payment for return ID ${returnDetailId}`;

    return (
        <div
            className={`gfm-cell-footer${compact ? ' gfm-cell-footer--compact' : ''}${paymentTarget.paymentCompleted ? ' gfm-cell-footer--paid' : ''}`}
        >
            <div className="gfm-cell-footer-info">
                <div className="gfm-form-ids" title="Return detail ID and filing ID for payments">
                    <span className={`gfm-form-id gfm-form-id--return${paymentTarget.paymentCompleted ? ' gfm-form-id--paid' : ''}`}>
                        ID {returnDetailId}
                    </span>
                    {filingId ? (
                        <span className="gfm-form-id gfm-form-id--filing">
                            Filing {filingId}
                        </span>
                    ) : null}
                </div>
                {hasRemaining && !paymentTarget.paymentCompleted ? (
                    <span className="gfm-form-remaining" title={`₹${formatCurrency(remaining)} remaining on GST filing return payment`}>
                        ₹{formatCurrency(remaining)} remaining
                    </span>
                ) : null}
            </div>
            {paymentTarget.paymentCompleted ? (
                <span className="gfm-form-paid-badge" title="Payment completed for this period">
                    <CheckCircle2 size={12} />
                    Paid
                </span>
            ) : (
                <button
                    type="button"
                    className="gfm-form-pay-btn"
                    title={payTitle}
                    onClick={(e) => {
                        e.stopPropagation();
                        onRecordPayment(returnDetailId);
                    }}
                >
                    <CreditCard size={12} />
                    <span>Pay</span>
                </button>
            )}
        </div>
    );
}

function buildCellTitle(cell, groupForms) {
    if (!cellHasDataForGroup(cell, groupForms)) return 'No filing for this period';
    const forms = cell.forms || {};
    return FORM_ROWS
        .filter(({ key }) => groupForms.includes(key) && hasFormData(forms[key]))
        .map(({ key, label }) => {
            const f = forms[key];
            const status = formatFormStatus(f.status);
            const due = formatDueDate(f.due_date);
            return `${label}: ${status} (due ${due})`;
        })
        .join('\n');
}

function MonthCellContent({
    cell,
    period,
    customerId,
    groupForms,
    onEditForm,
    onEditFollowup,
    onRecordPayment,
    focusFormKey,
    matrixFilterConfig = null,
}) {
    const forms = cell?.forms || {};
    const scopedGroupForms = scopeGroupForms(groupForms, matrixFilterConfig) || [];
    const activeRows = FORM_ROWS.filter(({ key }) => (
        scopedGroupForms.includes(key)
        && hasFormData(forms[key])
        && formMatchesMatrixFilters(forms[key], matrixFilterConfig, { cell, groupForms: scopedGroupForms })
    ));
    const paymentTarget = getCellPaymentTarget(cell, groupForms);
    const canEdit = Boolean(paymentTarget?.returnDetailId);
    const formOptions = getCellFormOptions(cell, groupForms);

    if (!activeRows.length) {
        return <span className="gfm-cell-empty">—</span>;
    }

    return (
        <div className="gfm-cell-stack">
            {activeRows.map(({ key, label }) => {
                const f = forms[key];
                const chipClass = getGstReturnStatusChipClass(f.status);
                const due = formatDueDate(f.due_date);
                const followupOverdue = isFollowupOverdue(f.followup_at);
                const followupLabel = f.followup_at
                    ? formatFollowupDateTime(f.followup_at)
                    : 'Set follow-up';
                const isFocusedForm = focusFormKey && focusFormKey === key;
                const formReturnDetailId = f.return_detail_id
                    || paymentTarget?.returnDetailId
                    || cell.return_detail_id;
                return (
                    <div key={key} className={`gfm-form-block${isFocusedForm ? ' gfm-form-block--focused' : ''}`}>
                        <button
                            type="button"
                            className={`gfm-form-chip gfm-form-chip--${chipClass}${canEdit ? ' gfm-form-chip--editable' : ''}`}
                            title={canEdit ? `Click to change ${label} status` : undefined}
                            disabled={!canEdit}
                            onClick={(e) => {
                                e.stopPropagation();
                                if (!canEdit) return;
                                onEditForm(e, {
                                    customerId,
                                    period,
                                    formKey: key,
                                    formLabel: label,
                                    status: f.status,
                                    dueDate: f.due_date,
                                    returnDetailId: formReturnDetailId,
                                    filingId: cell.filing_id,
                                });
                            }}
                        >
                            <span className="gfm-form-label">{label}</span>
                            <span className="gfm-form-meta">
                                <span className="gfm-form-status">{formatFormStatus(f.status)}</span>
                                {due && <span className="gfm-form-due">{due}</span>}
                            </span>
                        </button>
                        {canEdit && (
                            <button
                                type="button"
                                className={`gfm-form-followup${followupOverdue ? ' gfm-form-followup--overdue' : ''}${f.followup_at ? ' gfm-form-followup--set' : ''}`}
                                title={`Set follow-up for ${label}`}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onEditFollowup(e, {
                                        customerId,
                                        period,
                                        returnDetailId: formReturnDetailId,
                                        formKey: key,
                                        formLabel: label,
                                        followupAt: f.followup_at,
                                        periodLabel: formatMonthHeader(period),
                                        formOptions,
                                    });
                                }}
                            >
                                <span className="gfm-followup-label">Follow-up</span>
                                <span className="gfm-followup-value">{followupLabel}</span>
                            </button>
                        )}
                    </div>
                );
            })}
            {paymentTarget ? (
                <GfmPaymentFooter
                    returnDetailId={paymentTarget.returnDetailId}
                    filingId={paymentTarget.filingId}
                    paymentTarget={paymentTarget}
                    onRecordPayment={onRecordPayment}
                />
            ) : null}
        </div>
    );
}

function FollowupEditorPopover({
    editor,
    saving,
    error,
    inputValue,
    selectedFormKey,
    onFormKeyChange,
    onInputChange,
    onClose,
    onSave,
    onClear,
}) {
    const popoverRef = useRef(null);

    useEffect(() => {
        const handlePointerDown = (event) => {
            if (popoverRef.current && !popoverRef.current.contains(event.target)) {
                onClose();
            }
        };
        const handleEscape = (event) => {
            if (event.key === 'Escape') onClose();
        };
        // The popover is position:fixed at coordinates captured when it opened, so
        // it doesn't track its anchor once the matrix scrolls. Close it on any
        // scroll or resize (capture phase so scrolling a nested table container is
        // caught too), but ignore scrolls inside the popover's own options list.
        const handleDismissOnScroll = (event) => {
            if (event.type === 'scroll' && popoverRef.current && popoverRef.current.contains(event.target)) return;
            onClose();
        };
        document.addEventListener('mousedown', handlePointerDown);
        document.addEventListener('keydown', handleEscape);
        window.addEventListener('scroll', handleDismissOnScroll, true);
        window.addEventListener('resize', handleDismissOnScroll);
        return () => {
            document.removeEventListener('mousedown', handlePointerDown);
            document.removeEventListener('keydown', handleEscape);
            window.removeEventListener('scroll', handleDismissOnScroll, true);
            window.removeEventListener('resize', handleDismissOnScroll);
        };
    }, [onClose]);

    if (!editor) return null;

    const formOptions = editor.formOptions || [];
    const selectedForm = formOptions.find((item) => item.key === selectedFormKey);
    const hasFollowup = Boolean(selectedForm?.followupAt);

    return (
        <div
            ref={popoverRef}
            className="gfm-status-popover gfm-followup-popover"
            style={{ top: editor.top, left: editor.left }}
            role="dialog"
            aria-label="Set filing follow-up"
        >
            <div className="gfm-status-popover-head">
                <strong>
                    {selectedForm?.label || editor.formLabel || 'Return'} follow-up
                    {editor.periodLabel ? ` · ${editor.periodLabel}` : ''}
                </strong>
                <span className="gfm-status-popover-due">Each return has its own follow-up</span>
            </div>
            {error && <div className="gfm-status-popover-error">{error}</div>}
            <label className="gfm-followup-input-label" htmlFor="gfm-followup-form">
                Return type
            </label>
            <select
                id="gfm-followup-form"
                className="gfm-followup-select"
                value={selectedFormKey}
                onChange={(e) => onFormKeyChange(e.target.value)}
                disabled={saving || formOptions.length <= 1}
            >
                {formOptions.map((item) => (
                    <option key={item.key} value={item.key}>{item.label}</option>
                ))}
            </select>
            <label className="gfm-followup-input-label" htmlFor="gfm-followup-at">
                Follow-up date &amp; time
            </label>
            <input
                id="gfm-followup-at"
                type="datetime-local"
                className="gfm-followup-input"
                value={inputValue}
                onChange={(e) => onInputChange(e.target.value)}
                disabled={saving}
            />
            <div className="gfm-followup-actions">
                <button
                    type="button"
                    className="btn-filter-trigger"
                    disabled={saving || !inputValue}
                    onClick={onSave}
                >
                    Save
                </button>
                {hasFollowup && (
                    <button
                        type="button"
                        className="btn-clear-v2"
                        disabled={saving}
                        onClick={onClear}
                    >
                        Clear
                    </button>
                )}
            </div>
            {saving && <div className="gfm-status-popover-saving">Saving…</div>}
        </div>
    );
}

function StatusEditorPopover({
    editor,
    saving,
    error,
    onClose,
    onSelectStatus,
}) {
    const popoverRef = useRef(null);

    useEffect(() => {
        const handlePointerDown = (event) => {
            if (popoverRef.current && !popoverRef.current.contains(event.target)) {
                onClose();
            }
        };
        const handleEscape = (event) => {
            if (event.key === 'Escape') onClose();
        };
        // The popover is position:fixed at coordinates captured when it opened, so
        // it doesn't track its anchor once the matrix scrolls. Close it on any
        // scroll or resize (capture phase so scrolling a nested table container is
        // caught too), but ignore scrolls inside the popover's own options list.
        const handleDismissOnScroll = (event) => {
            if (event.type === 'scroll' && popoverRef.current && popoverRef.current.contains(event.target)) return;
            onClose();
        };
        document.addEventListener('mousedown', handlePointerDown);
        document.addEventListener('keydown', handleEscape);
        window.addEventListener('scroll', handleDismissOnScroll, true);
        window.addEventListener('resize', handleDismissOnScroll);
        return () => {
            document.removeEventListener('mousedown', handlePointerDown);
            document.removeEventListener('keydown', handleEscape);
            window.removeEventListener('scroll', handleDismissOnScroll, true);
            window.removeEventListener('resize', handleDismissOnScroll);
        };
    }, [onClose]);

    if (!editor) return null;

    const due = formatDueDate(editor.dueDate);
    const options = gstReturnDetailEditableStatusOptions(false);

    return (
        <div
            ref={popoverRef}
            className="gfm-status-popover"
            style={{ top: editor.top, left: editor.left }}
            role="dialog"
            aria-label={`Update ${editor.formLabel} status`}
        >
            <div className="gfm-status-popover-head">
                <strong>{editor.formLabel}</strong>
                {due && <span className="gfm-status-popover-due">Due {due}</span>}
            </div>
            {error && <div className="gfm-status-popover-error">{error}</div>}
            <div className="gfm-status-options">
                {options.map((opt) => {
                    const chipClass = getGstReturnStatusChipClass(opt.value);
                    const isActive = String(editor.status || '').toUpperCase() === opt.value;
                    return (
                        <button
                            key={opt.value}
                            type="button"
                            className={`gfm-status-opt gfm-form-chip--${chipClass}${isActive ? ' gfm-status-opt--active' : ''}`}
                            disabled={saving}
                            onClick={() => onSelectStatus(opt.value)}
                        >
                            {opt.label}
                        </button>
                    );
                })}
            </div>
            {saving && <div className="gfm-status-popover-saving">Saving…</div>}
        </div>
    );
}

const GstFilingMonthlyMatrix = () => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const tableBodyRef = useRef(null);
    const [focusTarget, setFocusTarget] = useState(() => parseGstFilingFocusFromSearch(window.location.search));
    const [rows, setRows] = useState([]);
    const [months, setMonths] = useState([]);
    // { gst_filing_id, gstin } while the Add Document Link drawer is open.
    const [docModalPreset, setDocModalPreset] = useState(null);
    // Row filing target while the portal-login editor is open.
    const [identityEditor, setIdentityEditor] = useState(null);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [page, setPage] = useState(1);
    const [filterInputs, setFilterInputs] = useState(createEmptyFilters);
    const [appliedFilters, setAppliedFilters] = useState(createEmptyFilters);
    const [statusEditor, setStatusEditor] = useState(null);
    const [statusSaving, setStatusSaving] = useState(false);
    const [statusSaveError, setStatusSaveError] = useState('');
    const [followupEditor, setFollowupEditor] = useState(null);
    const [followupFormKey, setFollowupFormKey] = useState('');
    const [followupInput, setFollowupInput] = useState('');
    const [followupSaving, setFollowupSaving] = useState(false);
    const [followupSaveError, setFollowupSaveError] = useState('');

    const loadRows = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = {
                limit: ROWS_PER_PAGE,
                offset: (page - 1) * ROWS_PER_PAGE,
            };
            if (appliedFilters.phone?.trim()) {
                params.phone = appliedFilters.phone.trim();
            }
            if (appliedFilters.business_name?.trim()) {
                params.business_name = appliedFilters.business_name.trim();
            }
            const followupDates = normalizeFollowupDateList(appliedFilters.followup_dates);
            if (followupDates.length) {
                params.followup_dates = followupDates.join(',');
            }
            const selectedMonths = normalizeGfmPeriodList(appliedFilters.months);
            if (selectedMonths.length) {
                params.periods = selectedMonths.join(',');
            } else {
                params.months = MONTH_COUNT;
            }
            const selectedStatuses = normalizeStatusList(appliedFilters.statuses);
            if (selectedStatuses.length) {
                params.return_statuses = selectedStatuses.join(',');
            }
            const selectedForms = normalizeFormList(appliedFilters.forms);
            if (selectedForms.length) {
                params.return_forms = selectedForms.join(',');
            }
            if (appliedFilters.followup_scheduled) {
                params.followup_scheduled = true;
            }
            if (appliedFilters.remaining_payment) {
                params.has_remaining_payment = true;
            }
            if (focusTarget?.customerId) {
                params.customer_id = focusTarget.customerId;
            }
            const result = await fetchGstFilingMonthlyMatrix(params);
            setRows(result?.data || []);
            // The API returns periods oldest-first; the matrix shows newest-first
            // so a new month lands in the leftmost column, next to Follow-up.
            setMonths([...(result?.months || [])].reverse());
            setTotal(Number(result?.total) || 0);
        } catch (err) {
            setError(getApiErrorMessage(err, 'Failed to load GST filing matrix'));
            setRows([]);
            setTotal(0);
        } finally {
            setLoading(false);
        }
    }, [page, appliedFilters, focusTarget?.customerId]);

    useEffect(() => {
        loadRows();
    }, [loadRows]);

    useEffect(() => {
        const onPaymentsUpdated = () => {
            loadRows();
        };
        window.addEventListener('st_payments_updated', onPaymentsUpdated);
        return () => window.removeEventListener('st_payments_updated', onPaymentsUpdated);
    }, [loadRows]);

    useEffect(() => {
        const fromUrl = parseGstFilingFocusFromSearch(searchParams.toString());
        if (fromUrl) setFocusTarget(fromUrl);
    }, [searchParams]);

    useEffect(() => {
        const handleOpenFocus = (event) => {
            const detail = event?.detail;
            if (!detail?.customerId) return;
            setFocusTarget({
                customerId: Number(detail.customerId),
                returnDetailId: detail.returnDetailId ? Number(detail.returnDetailId) : null,
                formKey: detail.formKey || null,
                period: detail.period || null,
            });
            setPage(1);
        };
        window.addEventListener('st_open_gst_filing_followup', handleOpenFocus);
        return () => window.removeEventListener('st_open_gst_filing_followup', handleOpenFocus);
    }, []);

    useEffect(() => {
        if (loading || !focusTarget?.customerId || !rows.length) return undefined;

        const timer = window.setTimeout(() => {
            const rowEl = tableBodyRef.current?.querySelector(
                `[data-gfm-customer-id="${focusTarget.customerId}"]`,
            );
            rowEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 120);

        return () => window.clearTimeout(timer);
    }, [loading, rows, focusTarget]);

    const handleFilterInputChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs((prev) => ({ ...prev, [name]: value }));
    };

    const commitFilters = useCallback((nextFilters, resetPage = true) => {
        const normalized = normalizeAppliedFilters(nextFilters);
        setFilterInputs(normalized);
        setAppliedFilters(normalized);
        if (resetPage) setPage(1);
    }, []);

    const handleApplyFilters = () => {
        commitFilters(filterInputs);
    };

    const handleClearFilters = () => {
        commitFilters(createEmptyFilters());
    };

    const handleFollowupDatesChange = (dates) => {
        setFilterInputs((prev) => ({
            ...prev,
            followup_dates: normalizeFollowupDateList(dates),
        }));
    };

    const handleMonthsChange = (periods) => {
        setFilterInputs((prev) => ({
            ...prev,
            months: normalizeGfmPeriodList(periods),
        }));
    };

    const handleStatusFilterChange = useCallback((next) => {
        commitFilters({
            ...filterInputs,
            statuses: normalizeStatusList(next.statuses),
            followup_scheduled: Boolean(next.followup_scheduled),
            remaining_payment: Boolean(next.remaining_payment),
        });
    }, [commitFilters, filterInputs]);

    const handleFormFilterChange = useCallback((nextForms) => {
        commitFilters({
            ...filterInputs,
            forms: normalizeFormList(nextForms),
        });
    }, [commitFilters, filterInputs]);

    const matrixFilterConfig = useMemo(
        () => getMatrixFilterConfig(appliedFilters),
        [appliedFilters],
    );

    const hasActiveSearchFilters = Boolean(
        appliedFilters.phone?.trim()
        || appliedFilters.business_name?.trim()
        || normalizeFollowupDateList(appliedFilters.followup_dates).length
        || normalizeGfmPeriodList(appliedFilters.months).length
        || normalizeStatusList(appliedFilters.statuses).length
        || normalizeFormList(appliedFilters.forms).length
        || appliedFilters.followup_scheduled
        || appliedFilters.remaining_payment,
    );

    const openRecordPayment = useCallback((returnDetailId = null) => {
        const params = new URLSearchParams();
        params.set('tab', 'add-payment');
        params.set('service_type', 'GST_FILING_RETURN_DETAILS');
        params.set('return_tab', 'dashboard');
        params.set('return_sub', 'gst-filing-matrix');
        if (returnDetailId) {
            params.set('entity_id', String(returnDetailId));
        }
        navigate(`/dashboard?${params.toString()}`);
    }, [navigate]);

    // One sheet per filing: open it when linked, otherwise add the link right
    // here on the dashboard rather than sending the user to another tab.
    const openFilingDocument = useCallback((target, row) => {
        if (!target?.filingId) return;
        if (target.documentUrl) {
            window.open(target.documentUrl, '_blank', 'noopener,noreferrer');
            return;
        }
        setDocModalPreset({
            gst_filing_id: String(target.filingId),
            gstin: row?.gstin || '',
        });
    }, []);

    const periodKeys = useMemo(() => {
        if (months.length) return months;
        const sample = rows.find((row) => row.months && Object.keys(row.months).length);
        return sample ? Object.keys(sample.months) : [];
    }, [months, rows]);

    const filteredCustomerRows = useMemo(() => {
        if (!matrixFilterConfig.active) return rows;
        return rows.filter((row) => (
            GFM_RETURN_GROUPS.some((group) => (
                periodKeys.some((period) => (
                    cellMatchesMatrixFilters(row.months?.[period], group.forms, matrixFilterConfig)
                ))
            ))
        ));
    }, [rows, periodKeys, matrixFilterConfig]);

    const displayRows = useMemo(
        () => expandCustomerToGroupRows(
            filteredCustomerRows,
            periodKeys,
            matrixFilterConfig,
        ),
        [filteredCustomerRows, periodKeys, matrixFilterConfig],
    );

    const gridStyle = useMemo(() => ({
        // Login Creds | Follow-up | …months… | Actions
        gridTemplateColumns: `minmax(240px, 1.6fr) minmax(120px, 0.75fr) repeat(${months.length || MONTH_COUNT}, minmax(176px, 1.35fr)) minmax(88px, 0.5fr)`,
    }), [months.length]);

    const openStatusEditor = useCallback((event, context) => {
        // Zoom-corrected so the popover lands on its cell (see utils/zoom).
        const rect = getAnchorRect(event.currentTarget);
        const viewport = getViewportSize();
        const popoverWidth = 260;
        const popoverHeight = 320;
        let left = rect.left;
        let top = rect.bottom + 6;
        if (left + popoverWidth > viewport.width - 12) {
            left = Math.max(12, viewport.width - popoverWidth - 12);
        }
        if (top + popoverHeight > viewport.height - 12) {
            top = Math.max(12, rect.top - popoverHeight - 6);
        }
        setStatusSaveError('');
        setStatusEditor({
            ...context,
            top,
            left,
        });
    }, []);

    const closeStatusEditor = useCallback(() => {
        if (statusSaving) return;
        setStatusEditor(null);
        setStatusSaveError('');
    }, [statusSaving]);

    const openFollowupEditor = useCallback((event, context) => {
        // Zoom-corrected so the popover lands on its cell (see utils/zoom).
        const rect = getAnchorRect(event.currentTarget);
        const viewport = getViewportSize();
        const popoverWidth = 280;
        const popoverHeight = 220;
        let left = rect.left;
        let top = rect.bottom + 6;
        if (left + popoverWidth > viewport.width - 12) {
            left = Math.max(12, viewport.width - popoverWidth - 12);
        }
        if (top + popoverHeight > viewport.height - 12) {
            top = Math.max(12, rect.top - popoverHeight - 6);
        }
        setFollowupSaveError('');
        setFollowupFormKey(context.formKey);
        setFollowupInput(toDatetimeLocalValue(context.followupAt));
        setFollowupEditor({
            ...context,
            top,
            left,
        });
    }, []);

    const handleFollowupFormChange = useCallback((formKey) => {
        const selected = followupEditor?.formOptions?.find((item) => item.key === formKey);
        setFollowupFormKey(formKey);
        setFollowupInput(toDatetimeLocalValue(selected?.followupAt));
        setFollowupSaveError('');
        if (selected?.returnDetailId) {
            setFollowupEditor((prev) => (prev ? {
                ...prev,
                returnDetailId: selected.returnDetailId,
                formKey,
                formLabel: selected.label,
            } : prev));
        }
    }, [followupEditor]);

    const closeFollowupEditor = useCallback(() => {
        if (followupSaving) return;
        setFollowupEditor(null);
        setFollowupFormKey('');
        setFollowupInput('');
        setFollowupSaveError('');
    }, [followupSaving]);

    const saveFollowup = useCallback(async (followupAtIso) => {
        if (!followupFormKey) return;
        const field = GST_RETURN_FORM_FOLLOWUP_FIELDS[followupFormKey];
        if (!field) return;
        const selectedOption = followupEditor?.formOptions?.find((item) => item.key === followupFormKey);
        let returnDetailId = selectedOption?.returnDetailId || followupEditor?.returnDetailId;
        if (followupEditor?.customerId && followupEditor?.period) {
            const resolved = await resolveReturnDetailIdForForm({
                customerId: followupEditor.customerId,
                period: followupEditor.period,
                formKey: followupFormKey,
            });
            if (resolved) returnDetailId = resolved;
        }
        if (!returnDetailId) return;
        setFollowupSaving(true);
        setFollowupSaveError('');
        try {
            await patchReturnDetailStatus(returnDetailId, { [field]: followupAtIso });
            setFollowupEditor(null);
            setFollowupFormKey('');
            setFollowupInput('');
            window.dispatchEvent(new CustomEvent('st_gst_followups_updated', {
                detail: {
                    returnDetailId,
                    formKey: followupFormKey,
                },
            }));
            await loadRows();
        } catch (err) {
            setFollowupSaveError(getApiErrorMessage(err, 'Failed to update follow-up'));
        } finally {
            setFollowupSaving(false);
        }
    }, [followupEditor, followupFormKey, loadRows]);

    const handleFollowupSave = useCallback(() => {
        const iso = fromDatetimeLocalValue(followupInput);
        if (!iso) {
            setFollowupSaveError('Enter a valid follow-up date and time.');
            return;
        }
        saveFollowup(iso);
    }, [followupInput, saveFollowup]);

    const handleFollowupClear = useCallback(() => {
        saveFollowup(null);
    }, [saveFollowup]);

    const handleStatusSelect = useCallback(async (newStatus) => {
        if (!statusEditor?.returnDetailId || !statusEditor?.formKey) return;
        const field = GST_RETURN_FORM_STATUS_FIELDS[statusEditor.formKey];
        if (!field) return;
        if (String(statusEditor.status || '').toUpperCase() === newStatus) {
            closeStatusEditor();
            return;
        }

        setStatusSaving(true);
        setStatusSaveError('');
        try {
            let returnDetailId = statusEditor.returnDetailId;
            if (statusEditor.customerId && statusEditor.period) {
                const resolved = await resolveReturnDetailIdForForm({
                    customerId: statusEditor.customerId,
                    period: statusEditor.period,
                    formKey: statusEditor.formKey,
                });
                if (resolved) returnDetailId = resolved;
            }
            await patchReturnDetailStatus(returnDetailId, { [field]: newStatus });
            setStatusEditor(null);
            await loadRows();
        } catch (err) {
            setStatusSaveError(getApiErrorMessage(err, 'Failed to update status'));
        } finally {
            setStatusSaving(false);
        }
    }, [statusEditor, closeStatusEditor, loadRows]);

    return (
        <div className="gfm-page progress-tracker-page">
            <div className="service-records-shell-v5 progress-shell">
                <div className="progress-content-layout">
                    <div className="progress-main-column">
                        <div className="gfm-toolbar">
                            <div className="gfm-filter-bar">
                                <GfmStatusFilter
                                    value={{
                                        statuses: appliedFilters.statuses,
                                        followup_scheduled: appliedFilters.followup_scheduled,
                                        remaining_payment: appliedFilters.remaining_payment,
                                    }}
                                    onChange={handleStatusFilterChange}
                                />
                                <GfmFormFilter
                                    value={appliedFilters.forms}
                                    onChange={handleFormFilterChange}
                                />
                                <div className="gfm-filter-field">
                                    <label htmlFor="gfm-phone">Phone</label>
                                    <input
                                        id="gfm-phone"
                                        type="text"
                                        name="phone"
                                        value={filterInputs.phone}
                                        onChange={handleFilterInputChange}
                                        placeholder="Search mobile…"
                                        onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
                                    />
                                </div>
                                <div className="gfm-filter-field">
                                    <label htmlFor="gfm-business">Business name</label>
                                    <input
                                        id="gfm-business"
                                        type="text"
                                        name="business_name"
                                        value={filterInputs.business_name}
                                        onChange={handleFilterInputChange}
                                        placeholder="Search business name…"
                                        onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
                                    />
                                </div>
                                <GfmMonthFilter
                                    value={filterInputs.months}
                                    onChange={handleMonthsChange}
                                />
                                <GfmFollowupDateFilter
                                    value={filterInputs.followup_dates}
                                    onChange={handleFollowupDatesChange}
                                />
                                <div className="gfm-filter-actions">
                                    <button
                                        type="button"
                                        className="gfm-record-payment-btn"
                                        onClick={() => openRecordPayment()}
                                        title="Create GST filing return detail payment"
                                    >
                                        <CreditCard size={13} /> Record Payment
                                    </button>
                                    <button type="button" className="btn-filter-trigger" onClick={handleApplyFilters}>
                                        <Search size={14} /> Apply
                                    </button>
                                    {hasActiveSearchFilters && (
                                        <button type="button" className="btn-clear-v2" onClick={handleClearFilters}>
                                            <RotateCcw size={14} /> Reset
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>

                        <div className="gfm-table-wrap">
                            <div className="gfm-table">
                                <div className="gfm-table-head gfm-table-row" style={gridStyle}>
                                    <div className="gfm-table-cell gfm-table-cell--customer">Login Creds</div>
                                    <div className="gfm-table-cell gfm-table-cell--followup-col">Follow-up</div>
                                    {(months.length ? months : [...Array(MONTH_COUNT)]).map((m) => (
                                        <div key={m || Math.random()} className="gfm-table-cell gfm-table-cell--month">
                                            {m ? formatMonthHeader(m) : '…'}
                                        </div>
                                    ))}
                                    <div className="gfm-table-cell">Actions</div>
                                </div>

                                {loading ? (
                                    <div className="gfm-table-body">
                                        {[...Array(8)].map((_, i) => (
                                            <div key={i} className="gfm-table-row" style={gridStyle}>
                                                {[...Array(3 + (months.length || MONTH_COUNT))].map((__, j) => (
                                                    <div key={j} className="gfm-table-cell">
                                                        <div className="gfm-skeleton" />
                                                    </div>
                                                ))}
                                            </div>
                                        ))}
                                    </div>
                                ) : error ? (
                                    <div className="employee-table-error" style={{ padding: 24 }}>{error}</div>
                                ) : displayRows.length === 0 ? (
                                    <div className="no-data-v4 gfm-no-data">No customers match the current filters.</div>
                                ) : (
                                    <div className="gfm-table-body" ref={tableBodyRef}>
                                        {displayRows.map((row) => {
                                            const isFocusedRow = focusTarget?.customerId === row.customer_id;
                                            return (
                                            <div
                                                key={row.rowKey}
                                                className={`gfm-table-row${isFocusedRow ? ' gfm-table-row--focused' : ''}${row.isFirstGroupRow ? '' : ' gfm-table-row--group-sub'}`}
                                                style={gridStyle}
                                                data-gfm-customer-id={row.customer_id}
                                                data-gfm-group-key={row.groupKey}
                                            >
                                                <div className="gfm-table-cell gfm-table-cell--customer">
                                                    {row.isFirstGroupRow ? (() => {
                                                        const identityTarget = getRowFilingTarget(row, months);
                                                        return (
                                                            <div className="customer-info-mini-v4">
                                                                <span className="customer-name-v4">
                                                                    {row.display_name || row.business_name || '—'}
                                                                </span>
                                                                <span className="gfm-identity-meta">
                                                                    {row.gstin && <span className="customer-mobile-v4">{row.gstin}</span>}
                                                                    {identityTarget?.filingId && (
                                                                        <span className="gfm-entity-chip">ID {identityTarget.filingId}</span>
                                                                    )}
                                                                </span>
                                                                {row.mobile && (
                                                                    <span className="gfm-identity-row">
                                                                        <span className="gfm-identity-label">Mob</span>
                                                                        <span className="gfm-identity-value">{row.mobile}</span>
                                                                    </span>
                                                                )}
                                                                <GfmFilingIdentity
                                                                    target={identityTarget}
                                                                    onEdit={setIdentityEditor}
                                                                />
                                                            </div>
                                                        );
                                                    })() : (
                                                        <span className="gfm-customer-continuation" aria-hidden="true">↳</span>
                                                    )}
                                                </div>
                                                {(() => {
                                                    const summary = getRowFollowupSummary(row, months, row.groupForms);
                                                    const overdue = summary && isFollowupOverdue(summary.followupAt);
                                                    return (
                                                        <div className="gfm-table-cell gfm-table-cell--followup-col">
                                                            {summary ? (
                                                                <div className="gfm-followup-summary-wrap">
                                                                    <button
                                                                        type="button"
                                                                        className={`gfm-followup-summary${overdue ? ' gfm-followup-summary--overdue' : ''}`}
                                                                        title={`${summary.formLabel} · ${formatMonthHeader(summary.period)} · click to edit`}
                                                                        onClick={(e) => openFollowupEditor(e, {
                                                                            customerId: row.customer_id,
                                                                            period: summary.period,
                                                                            returnDetailId: summary.returnDetailId,
                                                                            formKey: summary.formKey,
                                                                            formLabel: summary.formLabel,
                                                                            followupAt: summary.followupAt,
                                                                            periodLabel: formatMonthHeader(summary.period),
                                                                            formOptions: getCellFormOptions(summary.cell, row.groupForms),
                                                                        })}
                                                                    >
                                                                        <span className="gfm-followup-summary-form">{summary.formLabel}</span>
                                                                        <span className="gfm-followup-summary-period">{formatMonthHeader(summary.period)}</span>
                                                                        <span className="gfm-followup-summary-time">{formatFollowupDateTime(summary.followupAt)}</span>
                                                                    </button>
                                                                    {summary.returnDetailId ? (
                                                                        <GfmPaymentFooter
                                                                            returnDetailId={summary.returnDetailId}
                                                                            filingId={summary.cell?.filing_id ? Number(summary.cell.filing_id) : null}
                                                                            paymentTarget={{
                                                                                returnDetailId: summary.returnDetailId,
                                                                                ...getPaymentFieldsFromCell(summary.cell),
                                                                            }}
                                                                            compact
                                                                            onRecordPayment={openRecordPayment}
                                                                        />
                                                                    ) : null}
                                                                </div>
                                                            ) : (
                                                                <span className="gfm-cell-empty">—</span>
                                                            )}
                                                        </div>
                                                    );
                                                })()}
                                                {months.map((period) => {
                                                    const cell = row.months?.[period] || { tone: 'none' };
                                                    const hasData = cellHasDataForGroup(cell, row.groupForms)
                                                        && cellMatchesMatrixFilters(cell, row.groupForms, matrixFilterConfig);
                                                    const isFocusedCell = isFocusedRow
                                                        && focusTarget?.period === period
                                                        && (!focusTarget?.formKey
                                                            || row.groupForms.includes(focusTarget.formKey))
                                                        && (!focusTarget?.returnDetailId
                                                            || focusTarget.returnDetailId === cell.return_detail_id);
                                                    const cellFocusFormKey = isFocusedCell ? focusTarget?.formKey : null;
                                                    return (
                                                        <div
                                                            key={period}
                                                            className="gfm-table-cell gfm-table-cell--status"
                                                            data-gfm-period={period}
                                                        >
                                                            <div
                                                                className={`gfm-cell ${hasData ? 'gfm-cell--active' : 'gfm-cell--empty'}${isFocusedCell ? ' gfm-cell-wrap--focused' : ''}`}
                                                                title={buildCellTitle(cell, row.groupForms)}
                                                            >
                                                                <MonthCellContent
                                                                    cell={cell}
                                                                    period={period}
                                                                    customerId={row.customer_id}
                                                                    groupForms={row.groupForms}
                                                                    focusFormKey={cellFocusFormKey}
                                                                    matrixFilterConfig={matrixFilterConfig}
                                                                    onEditForm={openStatusEditor}
                                                                    onEditFollowup={openFollowupEditor}
                                                                    onRecordPayment={openRecordPayment}
                                                                />
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                                {(() => {
                                                    const target = getRowFilingTarget(row, months);
                                                    if (!target) {
                                                        return (
                                                            <div className="gfm-table-cell gfm-cell-actions">
                                                                <span className="gfm-cell-empty">—</span>
                                                            </div>
                                                        );
                                                    }
                                                    const linked = Boolean(target.documentUrl);
                                                    return (
                                                        <div className="gfm-table-cell gfm-cell-actions">
                                                            <button
                                                                type="button"
                                                                className="gfm-doc-link-btn"
                                                                title={linked
                                                                    ? `Open sheet for filing ${target.filingId}`
                                                                    : `Add document link for filing ${target.filingId}`}
                                                                onClick={() => openFilingDocument(target, row)}
                                                            >
                                                                {linked ? <ExternalLink size={14} /> : <Link2 size={14} />}
                                                            </button>
                                                        </div>
                                                    );
                                                })()}
                                            </div>
                                        );
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <Pagination
                currentPage={page}
                onPageChange={setPage}
                hasMore={page * ROWS_PER_PAGE < total}
                loading={loading}
            />

            <GfmIdentityEditor
                target={identityEditor}
                onClose={() => setIdentityEditor(null)}
                onSaved={() => {
                    setIdentityEditor(null);
                    loadRows();
                }}
            />

            <AddDocumentLinkModal
                isOpen={Boolean(docModalPreset)}
                onClose={() => setDocModalPreset(null)}
                presetFilingId={docModalPreset?.gst_filing_id || null}
                presetGstin={docModalPreset?.gstin || ''}
                onCreated={() => {
                    setDocModalPreset(null);
                    // Refresh so the icon flips from "add link" to "open sheet".
                    loadRows();
                }}
            />

            <StatusEditorPopover
                editor={statusEditor}
                saving={statusSaving}
                error={statusSaveError}
                onClose={closeStatusEditor}
                onSelectStatus={handleStatusSelect}
            />

            <FollowupEditorPopover
                editor={followupEditor}
                saving={followupSaving}
                error={followupSaveError}
                inputValue={followupInput}
                selectedFormKey={followupFormKey}
                onFormKeyChange={handleFollowupFormChange}
                onInputChange={setFollowupInput}
                onClose={closeFollowupEditor}
                onSave={handleFollowupSave}
                onClear={handleFollowupClear}
            />
        </div>
    );
};

export default GstFilingMonthlyMatrix;
