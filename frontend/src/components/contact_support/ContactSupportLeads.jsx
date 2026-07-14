import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2, Pencil, RotateCcw, Search, X } from 'lucide-react';
import Pagination from '../common/Pagination';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import {
    buildRmOpIdSelectOptions,
    fetchActiveRmEmployees,
    fetchActiveOpEmployees,
} from '../../utils/activeEmployees';
import {
    LEAD_BUCKET_CONTACT,
    LEAD_BUCKET_REFERRAL,
    createContactSupportLead,
    fetchContactSupportLeads,
    fetchContactSupportOptions,
    editContactSupportLead,
} from '../../utils/contactSupportApi';
import '../common/Filters.css';
import './ContactSupportLeads.css';

const ROWS_PER_PAGE = 25;
const TAB_CONTACT = 'contact_support';
const TAB_REFERRAL = 'referral';

function normalizeServiceList(values) {
    const source = Array.isArray(values) ? values : (values ? [values] : []);
    return Array.from(
        new Set(
            source
                .map((v) => String(v || '').trim().toUpperCase())
                .filter(Boolean),
        ),
    );
}

function normalizeReferralPhones(values) {
    const source = Array.isArray(values) ? values : (values ? [values] : []);
    return Array.from(
        new Set(
            source
                .map((v) => String(v || '').replace(/\D/g, ''))
                .filter((v) => v.length === 10),
        ),
    );
}

function normalizeSingleReferralPhone(value) {
    return String(value || '').replace(/\D/g, '');
}

function getApiErrorMessage(err, fallback = 'Request failed') {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail?.error?.message) return detail.error.message;
    if (detail?.message) return detail.message;
    return err?.message || fallback;
}

const ContactSupportLeads = () => {
    const navigate = useNavigate();
    const location = useLocation();

    const initialSub = new URLSearchParams(location.search).get('sub') || TAB_CONTACT;
    const [activeTab, setActiveTab] = useState(
        initialSub === TAB_REFERRAL ? TAB_REFERRAL : TAB_CONTACT,
    );

    const [rows, setRows] = useState([]);
    const [total, setTotal] = useState(0);
    const [counts, setCounts] = useState({ contact_support: 0, referral: 0 });
    const [serviceOptions, setServiceOptions] = useState([]);
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [page, setPage] = useState(1);

    const [filterInputs, setFilterInputs] = useState({
        phone_number: '',
        service_required: [],
        is_resolved: '',
    });
    const [appliedFilters, setAppliedFilters] = useState({
        phone_number: '',
        service_required: [],
        is_resolved: '',
    });

    const [editRow, setEditRow] = useState(null);
    const [editForm, setEditForm] = useState({});
    const [editSaving, setEditSaving] = useState(false);
    const [editError, setEditError] = useState(null);
    const [editReferralInput, setEditReferralInput] = useState('');
    const [editReferralInputError, setEditReferralInputError] = useState('');
    const [inlinePreview, setInlinePreview] = useState(null);
    const [createOpen, setCreateOpen] = useState(false);
    const [createSaving, setCreateSaving] = useState(false);
    const [createError, setCreateError] = useState(null);
    const [createReferralInput, setCreateReferralInput] = useState('');
    const [createReferralInputError, setCreateReferralInputError] = useState('');
    const [createForm, setCreateForm] = useState({
        your_name: '',
        phone_number: '',
        email_address: '',
        service_required: [],
        referal_phone_number: [],
        your_message: '',
    });

    const leadBucket = activeTab === TAB_REFERRAL ? LEAD_BUCKET_REFERRAL : LEAD_BUCKET_CONTACT;

    const loadOptions = useCallback(async () => {
        try {
            const data = await fetchContactSupportOptions();
            setServiceOptions(normalizeServiceList(data.service_required));
            setCounts(data.counts || { contact_support: 0, referral: 0 });
        } catch (err) {
            console.warn('Contact support options failed', err);
        }
    }, []);

    const loadRows = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = {
                lead_bucket: leadBucket,
                limit: ROWS_PER_PAGE,
                offset: (page - 1) * ROWS_PER_PAGE,
            };
            if (appliedFilters.phone_number?.trim()) {
                params.phone_number = appliedFilters.phone_number.trim();
            }
            if (appliedFilters.service_required?.length) {
                params.service_required = appliedFilters.service_required;
            }
            if (appliedFilters.is_resolved === 'true') params.is_resolved = true;
            if (appliedFilters.is_resolved === 'false') params.is_resolved = false;

            const result = await fetchContactSupportLeads(params);
            setRows(result.items || []);
            setTotal(result.total || 0);
        } catch (err) {
            setError(getApiErrorMessage(err, 'Failed to load leads'));
            setRows([]);
            setTotal(0);
        } finally {
            setLoading(false);
        }
    }, [leadBucket, page, appliedFilters, activeTab]);

    useEffect(() => {
        loadOptions();
    }, [loadOptions]);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [rms, ops] = await Promise.all([
                    fetchActiveRmEmployees(),
                    fetchActiveOpEmployees(),
                ]);
                if (cancelled) return;
                setActiveRMs(rms || []);
                setActiveOps(ops || []);
            } catch (err) {
                console.warn('Failed to load RM/OP lists', err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        loadRows();
    }, [loadRows]);

    useEffect(() => {
        const sub = new URLSearchParams(location.search).get('sub');
        if (sub === TAB_REFERRAL || sub === TAB_CONTACT) {
            setActiveTab(sub);
        }
    }, [location.search]);

    const switchTab = (tab) => {
        setActiveTab(tab);
        setPage(1);
        const params = new URLSearchParams(location.search);
        params.set('tab', 'contact-leads');
        params.set('sub', tab);
        navigate(`/dashboard?${params.toString()}`);
    };

    const handleApplyFilters = () => {
        setAppliedFilters({
            phone_number: filterInputs.phone_number,
            service_required: normalizeServiceList(filterInputs.service_required),
            is_resolved: filterInputs.is_resolved,
        });
        setPage(1);
    };

    const handleClearFilters = () => {
        const empty = {
            phone_number: '',
            service_required: [],
            is_resolved: '',
        };
        setFilterInputs(empty);
        setAppliedFilters({
            phone_number: '',
            service_required: [],
            is_resolved: '',
        });
        setPage(1);
    };

    const openEdit = (row) => {
        setEditRow(row);
        setEditError(null);
        setEditForm({
            your_name: row.your_name || '',
            phone_number: row.phone_number || '',
            email_address: row.email_address || '',
            service_required: normalizeServiceList(row.service_required),
            referal_phone_number: normalizeReferralPhones(row.referal_phone_number),
            your_message: row.your_message || '',
            is_service_provided: Boolean(row.is_service_provided),
            is_resolved: Boolean(row.is_resolved),
            rm_id: row.rm_id ?? '',
            op_id: row.op_id ?? '',
        });
        setEditReferralInput('');
    };

    const closeEdit = () => {
        setEditRow(null);
        setEditError(null);
        setEditReferralInput('');
        setEditReferralInputError('');
    };

    const handleEditChange = (e) => {
        const { name, value, type, checked } = e.target;
        setEditForm((prev) => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value,
        }));
    };

    const toggleEditService = (serviceCode) => {
        const code = String(serviceCode || '').trim().toUpperCase();
        if (!code) return;
        setEditForm((prev) => {
            const current = Array.isArray(prev.service_required) ? prev.service_required : [];
            const next = current.includes(code)
                ? current.filter((v) => v !== code)
                : [...current, code];
            return { ...prev, service_required: next };
        });
    };

    const addEditReferralPhones = () => {
        const onePhone = normalizeSingleReferralPhone(editReferralInput);
        if (!onePhone) return;
        if (onePhone.length !== 10) {
            setEditReferralInputError('Referral phone must be exactly 10 digits.');
            return;
        }
        setEditForm((prev) => ({
            ...prev,
            referal_phone_number: normalizeReferralPhones([...(prev.referal_phone_number || []), onePhone]),
        }));
        setEditReferralInput('');
        setEditReferralInputError('');
    };

    const removeEditReferralPhone = (phone) => {
        setEditForm((prev) => ({
            ...prev,
            referal_phone_number: (prev.referal_phone_number || []).filter((v) => v !== phone),
        }));
    };

    const openCreate = () => {
        setCreateError(null);
        setCreateReferralInput('');
        setCreateReferralInputError('');
        setCreateForm({
            your_name: '',
            phone_number: '',
            email_address: '',
            service_required: [],
            referal_phone_number: [],
            your_message: '',
        });
        setCreateOpen(true);
    };

    const closeCreate = () => {
        setCreateOpen(false);
        setCreateError(null);
        setCreateReferralInput('');
        setCreateReferralInputError('');
    };

    const handleCreateChange = (e) => {
        const { name, value } = e.target;
        setCreateForm((prev) => ({ ...prev, [name]: value }));
    };

    const toggleCreateService = (serviceCode) => {
        const code = String(serviceCode || '').trim().toUpperCase();
        if (!code) return;
        setCreateForm((prev) => {
            const current = Array.isArray(prev.service_required) ? prev.service_required : [];
            const next = current.includes(code)
                ? current.filter((v) => v !== code)
                : [...current, code];
            return { ...prev, service_required: next };
        });
    };

    const addCreateReferralPhone = () => {
        const onePhone = normalizeSingleReferralPhone(createReferralInput);
        if (!onePhone) return;
        if (onePhone.length !== 10) {
            setCreateReferralInputError('Referral phone must be exactly 10 digits.');
            return;
        }
        setCreateForm((prev) => ({
            ...prev,
            referal_phone_number: normalizeReferralPhones([...(prev.referal_phone_number || []), onePhone]),
        }));
        setCreateReferralInput('');
        setCreateReferralInputError('');
    };

    const removeCreateReferralPhone = (phone) => {
        setCreateForm((prev) => ({
            ...prev,
            referal_phone_number: (prev.referal_phone_number || []).filter((v) => v !== phone),
        }));
    };

    const openListPreview = (rowId, title, items) => {
        const safeItems = Array.isArray(items)
            ? items.map((v) => String(v || '').trim()).filter(Boolean)
            : [];
        setInlinePreview((prev) => {
            if (prev && prev.rowId === rowId && prev.title === title) return null;
            return { rowId, title, items: safeItems };
        });
    };

    const handleEditSave = async (e) => {
        e.preventDefault();
        if (!editRow?.id) return;
        setEditSaving(true);
        setEditError(null);
        try {
            const payload = {
                your_name: editForm.your_name?.trim(),
                phone_number: String(editForm.phone_number || '').replace(/\D/g, ''),
                email_address: editForm.email_address?.trim() || null,
                service_required: normalizeServiceList(editForm.service_required),
                your_message: editForm.your_message?.trim() || null,
                is_service_provided: editForm.is_service_provided,
                is_resolved: editForm.is_resolved,
                referal_phone_number: normalizeReferralPhones(editForm.referal_phone_number),
            };
            if (editForm.rm_id !== '') payload.rm_id = Number(editForm.rm_id);
            if (editForm.op_id !== '') payload.op_id = Number(editForm.op_id);

            await editContactSupportLead(editRow.id, payload);
            closeEdit();
            await Promise.all([loadRows(), loadOptions()]);
        } catch (err) {
            setEditError(getApiErrorMessage(err, 'Update failed'));
        } finally {
            setEditSaving(false);
        }
    };

    const handleCreateSave = async (e) => {
        e.preventDefault();
        setCreateSaving(true);
        setCreateError(null);
        try {
            const payload = {
                your_name: createForm.your_name?.trim(),
                phone_number: String(createForm.phone_number || '').replace(/\D/g, ''),
                email_address: createForm.email_address?.trim() || null,
                service_required: normalizeServiceList(createForm.service_required),
                referal_phone_number: normalizeReferralPhones(createForm.referal_phone_number),
                your_message: createForm.your_message?.trim() || null,
            };
            await createContactSupportLead(payload);
            closeCreate();
            await Promise.all([loadRows(), loadOptions()]);
        } catch (err) {
            setCreateError(getApiErrorMessage(err, 'Create failed'));
        } finally {
            setCreateSaving(false);
        }
    };

    const resolvedFilterOptions = optionsFromPairs([
        { value: '', label: 'All statuses' },
        { value: 'false', label: 'Open' },
        { value: 'true', label: 'Resolved' },
    ]);

    const rmSelectOptions = optionsFromPairs(
        buildRmOpIdSelectOptions(
            activeRMs,
            editRow?.rm_id != null && editRow?.rm_id !== ''
                ? { id: editRow.rm_id, label: editRow.rm_name }
                : null,
        ),
        'Unassigned',
    );

    const opSelectOptions = optionsFromPairs(
        buildRmOpIdSelectOptions(
            activeOps,
            editRow?.op_id != null && editRow?.op_id !== ''
                ? { id: editRow.op_id, label: editRow.op_name }
                : null,
        ),
        'Unassigned',
    );

    const hasFilters = Boolean(
        appliedFilters.phone_number?.trim()
        || appliedFilters.service_required?.length
        || appliedFilters.is_resolved,
    );

    return (
        <div className="cs-leads-page progress-tracker-page">
            <div className="service-records-shell-v5 progress-shell">
                <div className="progress-content-layout">
                    <div className="progress-main-column">
                        <div className="cs-leads-toolbar">
                            <div className="cs-leads-tabs" role="tablist" aria-label="Lead source">
                                <button
                                    type="button"
                                    role="tab"
                                    aria-selected={activeTab === TAB_CONTACT}
                                    className={`cs-leads-tab ${activeTab === TAB_CONTACT ? 'is-active' : ''}`}
                                    onClick={() => switchTab(TAB_CONTACT)}
                                >
                                    <span className="cs-leads-tab-count">{counts.contact_support ?? '—'}</span>
                                    Contact Support
                                </button>
                                <button
                                    type="button"
                                    role="tab"
                                    aria-selected={activeTab === TAB_REFERRAL}
                                    className={`cs-leads-tab cs-leads-tab--referral ${activeTab === TAB_REFERRAL ? 'is-active' : ''}`}
                                    onClick={() => switchTab(TAB_REFERRAL)}
                                >
                                    <span className="cs-leads-tab-count">{counts.referral ?? '—'}</span>
                                    Referral
                                </button>
                            </div>

                            <div className="cs-leads-filters">
                                <div className="cs-leads-filter-field">
                                    <label htmlFor="cs-phone">Phone</label>
                                    <input
                                        id="cs-phone"
                                        name="phone_number"
                                        value={filterInputs.phone_number}
                                        onChange={(e) => setFilterInputs((p) => ({ ...p, phone_number: e.target.value }))}
                                        placeholder="10-digit mobile"
                                        onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
                                    />
                                </div>
                                {activeTab === TAB_REFERRAL && null}
                                <div className="cs-leads-filter-field">
                                    <label>Status</label>
                                    <FormCustomSelect
                                        name="is_resolved"
                                        value={filterInputs.is_resolved}
                                        onChange={(e) => setFilterInputs((p) => ({ ...p, is_resolved: e.target.value }))}
                                        options={resolvedFilterOptions}
                                        placeholder="All statuses"
                                        ariaLabel="Filter by resolved"
                                    />
                                </div>
                                <div className="sdpp-filter-actions">
                                    <button type="button" className="btn-clear-v2" onClick={openCreate}>
                                        + Create
                                    </button>
                                    <button type="button" className="btn-filter-trigger" onClick={handleApplyFilters}>
                                        <Search size={14} /> Apply
                                    </button>
                                    {hasFilters && (
                                        <button type="button" className="btn-clear-v2" onClick={handleClearFilters}>
                                            <RotateCcw size={14} /> Reset
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>

                        <div className="progress-tracker-container-v4">
                            <div className={`filings-ledger-header cs-leads-grid ${activeTab === TAB_REFERRAL ? 'cs-leads-grid--referral' : ''}`}>
                                <div className="filings-ledger-header-cell">ID</div>
                                <div className="filings-ledger-header-cell">Name</div>
                                <div className="filings-ledger-header-cell">Phone</div>
                                {activeTab === TAB_REFERRAL && (
                                    <div className="filings-ledger-header-cell">Referral Phone</div>
                                )}
                                <div className="filings-ledger-header-cell">Email</div>
                                <div className="filings-ledger-header-cell">Service</div>
                                <div className="filings-ledger-header-cell">RM</div>
                                <div className="filings-ledger-header-cell">OP</div>
                                <div className="filings-ledger-header-cell">Provided</div>
                                <div className="filings-ledger-header-cell">Status</div>
                                <div className="filings-ledger-header-cell">Action</div>
                            </div>

                            {loading ? (
                                <div className="filings-ledger-body" style={{ padding: 24, textAlign: 'center' }}>
                                    <Loader2 size={24} className="spin" />
                                </div>
                            ) : error ? (
                                <div className="employee-table-error" style={{ padding: 24 }}>{error}</div>
                            ) : (
                                <div className="filings-ledger-body">
                                    {rows.length === 0 ? (
                                        <div className="no-data-v4">No leads match the current filters.</div>
                                    ) : (
                                        rows.map((row) => {
                                            const serviceItems = normalizeServiceList(row.service_required).map((s) => s.replace(/_/g, ' '));
                                            const referralItems = normalizeReferralPhones(row.referal_phone_number);
                                            const isServiceOpen = inlinePreview?.rowId === row.id && inlinePreview?.title === 'Services';
                                            const isReferralOpen = inlinePreview?.rowId === row.id && inlinePreview?.title === 'Referral phones';
                                            const previewOpen = inlinePreview?.rowId === row.id;
                                            return (
                                                <React.Fragment key={row.id}>
                                                    <div
                                                        className={`filings-ledger-row cs-leads-grid ${activeTab === TAB_REFERRAL ? 'cs-leads-grid--referral' : ''}`}
                                                    >
                                                        <div className="filings-ledger-cell">
                                                            <span className="customer-id-green-v4">{row.id}</span>
                                                        </div>
                                                        <div className="filings-ledger-cell">{row.your_name || '—'}</div>
                                                        <div className="filings-ledger-cell">{row.phone_number || '—'}</div>
                                                        {activeTab === TAB_REFERRAL && (
                                                            <div className="filings-ledger-cell">
                                                                <button
                                                                    type="button"
                                                                    className={`cs-list-view-btn ${isReferralOpen ? 'is-open' : ''}`}
                                                                    onClick={() => openListPreview(row.id, 'Referral phones', referralItems)}
                                                                >
                                                                    View ({referralItems.length})
                                                                </button>
                                                            </div>
                                                        )}
                                                        <div className="filings-ledger-cell">{row.email_address || '—'}</div>
                                                        <div className="filings-ledger-cell">
                                                            <button
                                                                type="button"
                                                                className={`cs-list-view-btn ${isServiceOpen ? 'is-open' : ''}`}
                                                                onClick={() => openListPreview(row.id, 'Services', serviceItems)}
                                                            >
                                                                View ({serviceItems.length})
                                                            </button>
                                                        </div>
                                                        <div className="filings-ledger-cell">{row.rm_name || row.rm_id || '—'}</div>
                                                        <div className="filings-ledger-cell">{row.op_name || row.op_id || '—'}</div>
                                                        <div className="filings-ledger-cell">
                                                            {row.is_service_provided ? 'Yes' : 'No'}
                                                        </div>
                                                        <div className="filings-ledger-cell">
                                                            <span className={`cs-status-pill ${row.is_resolved ? 'resolved' : 'open'}`}>
                                                                {row.is_resolved ? 'Resolved' : 'Open'}
                                                            </span>
                                                        </div>
                                                        <div className="filings-ledger-cell">
                                                            <button
                                                                type="button"
                                                                className="cs-row-action"
                                                                title="Edit lead"
                                                                aria-label="Edit lead"
                                                                onClick={() => openEdit(row)}
                                                            >
                                                                <Pencil size={14} />
                                                            </button>
                                                        </div>
                                                    </div>
                                                    {previewOpen && (
                                                        <div className={`filings-ledger-row cs-leads-grid ${activeTab === TAB_REFERRAL ? 'cs-leads-grid--referral' : ''} cs-inline-preview-row`}>
                                                            <div className="filings-ledger-cell cs-inline-preview-cell">
                                                                <div className="cs-inline-preview-title">{inlinePreview.title}</div>
                                                                <div className="cs-inline-preview-items">
                                                                    {inlinePreview.items?.length ? inlinePreview.items.map((item) => (
                                                                        <span key={item} className="cs-chip-tag static">{item}</span>
                                                                    )) : <span className="cs-chip-empty">--</span>}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    )}
                                                </React.Fragment>
                                            );
                                        })
                                    )}
                                </div>
                            )}
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

            {editRow && (
                <div className="premium-filter-overlay show" onClick={closeEdit}>
                    <div className="premium-edit-modal-v4" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
                        <button type="button" className="btn-close-modal-v4" onClick={closeEdit} aria-label="Close">
                            <X size={20} />
                        </button>
                        <div className="edit-modal-header-v4">
                            <h3>Edit lead {editRow.id}</h3>
                            <p>{activeTab === TAB_REFERRAL ? 'Referral lead' : 'Contact support lead'}</p>
                        </div>
                        <form onSubmit={handleEditSave} className="edit-modal-body-v4 premium-edit-grid-v4">
                            <div className="input-group-v4 full">
                                <label>Name</label>
                                <input name="your_name" value={editForm.your_name} onChange={handleEditChange} required />
                            </div>
                            <div className="input-group-v4">
                                <label>Phone</label>
                                <input name="phone_number" value={editForm.phone_number} onChange={handleEditChange} maxLength={10} required />
                            </div>
                            <div className="input-group-v4">
                                <label>Email</label>
                                <input name="email_address" type="email" value={editForm.email_address} onChange={handleEditChange} />
                            </div>
                            <div className="input-group-v4">
                                <label>Service required</label>
                                <div className="cs-multi-chip-wrap">
                                    {serviceOptions.map((s) => {
                                        const selected = (editForm.service_required || []).includes(s);
                                        return (
                                            <button
                                                key={s}
                                                type="button"
                                                className={`cs-chip-btn ${selected ? 'is-active' : ''}`}
                                                onClick={() => toggleEditService(s)}
                                            >
                                                {s.replace(/_/g, ' ')}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                            {activeTab === TAB_REFERRAL && (
                                <div className="input-group-v4">
                                    <label>Referral phone</label>
                                    <div className="cs-ref-input-row">
                                        <input
                                            name="referal_phone_input"
                                            value={editReferralInput}
                                            onChange={(e) => {
                                                setEditReferralInput(normalizeSingleReferralPhone(e.target.value).slice(0, 10));
                                                if (editReferralInputError) setEditReferralInputError('');
                                            }}
                                            placeholder="Add one 10-digit phone"
                                            maxLength={10}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    e.preventDefault();
                                                    addEditReferralPhones();
                                                }
                                            }}
                                        />
                                        <button type="button" className="btn-clear-v2" onClick={addEditReferralPhones}>Add</button>
                                    </div>
                                    {editReferralInputError && (
                                        <div className="input-error-text">{editReferralInputError}</div>
                                    )}
                                    <div className="cs-chip-list">
                                        {(editForm.referal_phone_number || []).length === 0 ? (
                                            <span className="cs-chip-empty">--</span>
                                        ) : (editForm.referal_phone_number || []).map((phone) => (
                                            <button key={phone} type="button" className="cs-chip-tag" onClick={() => removeEditReferralPhone(phone)}>
                                                {phone} <span>x</span>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <div className="input-group-v4">
                                <label>RM</label>
                                <FormCustomSelect
                                    name="rm_id"
                                    value={editForm.rm_id != null ? String(editForm.rm_id) : ''}
                                    onChange={handleEditChange}
                                    options={rmSelectOptions}
                                    placeholder="Unassigned"
                                    ariaLabel="Relationship manager"
                                />
                            </div>
                            <div className="input-group-v4">
                                <label>OP</label>
                                <FormCustomSelect
                                    name="op_id"
                                    value={editForm.op_id != null ? String(editForm.op_id) : ''}
                                    onChange={handleEditChange}
                                    options={opSelectOptions}
                                    placeholder="Unassigned"
                                    ariaLabel="Operations personnel"
                                />
                            </div>
                            <div className="input-group-v4 full">
                                <label>Message</label>
                                <textarea name="your_message" value={editForm.your_message} onChange={handleEditChange} rows={3} />
                            </div>
                            <div className="input-group-v4">
                                <label>
                                    <input type="checkbox" name="is_service_provided" checked={editForm.is_service_provided} onChange={handleEditChange} />
                                    {' '}Service provided
                                </label>
                            </div>
                            <div className="input-group-v4">
                                <label>
                                    <input type="checkbox" name="is_resolved" checked={editForm.is_resolved} onChange={handleEditChange} />
                                    {' '}Resolved
                                </label>
                            </div>
                            {editError && (
                                <div className="input-group-v4 full" style={{ color: 'var(--danger)', fontSize: 13 }}>{editError}</div>
                            )}
                            <div className="edit-modal-footer-v4 cs-sticky-drawer-footer" style={{ gridColumn: '1 / -1' }}>
                                <button type="button" className="btn-cancel-v4" onClick={closeEdit}>Cancel</button>
                                <button type="submit" className="btn-save-v4" disabled={editSaving}>
                                    {editSaving ? 'Saving…' : 'Save'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {createOpen && (
                <div className="premium-filter-overlay show" onClick={closeCreate}>
                    <div className="premium-edit-modal-v4" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
                        <button type="button" className="btn-close-modal-v4" onClick={closeCreate} aria-label="Close">
                            <X size={20} />
                        </button>
                        <div className="edit-modal-header-v4">
                            <h3>Create contact/referral lead</h3>
                            <p>Add a new request</p>
                        </div>
                        <form onSubmit={handleCreateSave} className="edit-modal-body-v4 premium-edit-grid-v4">
                            <div className="input-group-v4 full">
                                <label>Name</label>
                                <input name="your_name" value={createForm.your_name} onChange={handleCreateChange} required />
                            </div>
                            <div className="input-group-v4">
                                <label>Phone</label>
                                <input name="phone_number" value={createForm.phone_number} onChange={handleCreateChange} maxLength={10} required />
                            </div>
                            <div className="input-group-v4">
                                <label>Email</label>
                                <input name="email_address" type="email" value={createForm.email_address} onChange={handleCreateChange} />
                            </div>
                            <div className="input-group-v4">
                                <label>Service required</label>
                                <div className="cs-multi-chip-wrap">
                                    {serviceOptions.map((s) => {
                                        const selected = (createForm.service_required || []).includes(s);
                                        return (
                                            <button
                                                key={s}
                                                type="button"
                                                className={`cs-chip-btn ${selected ? 'is-active' : ''}`}
                                                onClick={() => toggleCreateService(s)}
                                            >
                                                {s.replace(/_/g, ' ')}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                            <div className="input-group-v4">
                                <label>Referral phone</label>
                                <div className="cs-ref-input-row">
                                    <input
                                        name="create_referal_phone_input"
                                        value={createReferralInput}
                                        onChange={(e) => {
                                            setCreateReferralInput(normalizeSingleReferralPhone(e.target.value).slice(0, 10));
                                            if (createReferralInputError) setCreateReferralInputError('');
                                        }}
                                        placeholder="Add one 10-digit phone"
                                        maxLength={10}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') {
                                                e.preventDefault();
                                                addCreateReferralPhone();
                                            }
                                        }}
                                    />
                                    <button type="button" className="btn-clear-v2" onClick={addCreateReferralPhone}>Add</button>
                                </div>
                                {createReferralInputError && (
                                    <div className="input-error-text">{createReferralInputError}</div>
                                )}
                                <div className="cs-chip-list">
                                    {(createForm.referal_phone_number || []).length === 0 ? (
                                        <span className="cs-chip-empty">--</span>
                                    ) : (createForm.referal_phone_number || []).map((phone) => (
                                        <button key={phone} type="button" className="cs-chip-tag" onClick={() => removeCreateReferralPhone(phone)}>
                                            {phone} <span>x</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div className="input-group-v4 full">
                                <label>Message</label>
                                <textarea name="your_message" value={createForm.your_message} onChange={handleCreateChange} rows={3} />
                            </div>
                            {createError && (
                                <div className="input-group-v4 full" style={{ color: 'var(--danger)', fontSize: 13 }}>{createError}</div>
                            )}
                            <div className="edit-modal-footer-v4 cs-sticky-drawer-footer" style={{ gridColumn: '1 / -1' }}>
                                <button type="button" className="btn-cancel-v4" onClick={closeCreate}>Cancel</button>
                                <button type="submit" className="btn-save-v4" disabled={createSaving}>
                                    {createSaving ? 'Saving…' : 'Save'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

        </div>
    );
};

export default ContactSupportLeads;
