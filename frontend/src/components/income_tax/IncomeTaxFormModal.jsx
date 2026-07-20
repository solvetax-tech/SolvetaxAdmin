import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, AlertCircle, Loader2, FileText, Calendar, Wallet, Plus, CalendarClock } from 'lucide-react';
import {
    createIncomeTax,
    editIncomeTax,
    setIncomeTaxActive,
    getIncomeTaxErrorPayload,
    buildIncomeTaxCrmLeadActionSearchParams,
    getCrmLeadByIncomeTaxId,
    isItrCrmStageForSchedulePayment,
} from '../../utils/incomeTaxApi';
import {
    asStringArray,
    INCOME_SOURCE_OPTIONS,
    buildFinancialYearPresetOptions,
    getFinancialYearFormHint,
    splitSourceOfIncome,
    buildSourceOfIncomePayload,
    validateFinancialYearAllowed,
} from '../../utils/incomeTaxArrays';
import {
    getRmOpAssignmentVisibility,
    resolveRmIdForPayload,
    resolveOpIdForPayload,
} from '../../utils/rmOpAssignmentFields';
import './income_tax.css';
import {
    AppDrawerFooter,
    AppDrawerBtnCancel,
    AppDrawerBtnSave,
    AppDrawerBtnDelete,
} from '../common/AppDrawerEditFooter';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig, optionsFromConfigOnly, optionsFromPairs } from '../common/selectOptionUtils';
import { buildRmOpSelectOptions } from '../../utils/activeEmployees';

/** Info banner for 409 duplicate_record (title + short message from API). */
function DuplicateRecordNotice({ notice, onContinue, continueLabel = 'Edit existing record', loading = false }) {
    if (!notice) return null;
    const { message, existingIncomeTaxId, recordYear } = notice;

    return (
        <div className="itr-duplicate-notice" role="status">
            <div className="itr-duplicate-notice__icon">
                <AlertCircle size={22} />
            </div>
            <div className="itr-duplicate-notice__body">
                <strong className="itr-duplicate-notice__title">
                    Record already exists
                    {recordYear != null ? ` (${recordYear})` : ''}
                </strong>
                {message && <p className="itr-duplicate-notice__message">{message}</p>}
                {onContinue && existingIncomeTaxId != null && (
                    <div className="itr-duplicate-notice__actions">
                        <button
                            type="button"
                            className="itr-duplicate-notice__cta"
                            onClick={() => onContinue(existingIncomeTaxId)}
                            disabled={loading}
                        >
                            {continueLabel}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

/** Maps API field keys to labels shown in validation messages */
const FIELD_LABELS = {
    priority: 'Priority',
    financial_year: 'Financial Year',
    client_name: 'Client Name',
    pan_number: 'PAN Number',
    mobile: 'Mobile',
    email_id: 'Email',
    filed_status: 'Filing status',
    source_of_income: 'Source of income',
    language: 'Language',
    state: 'State',
    refund_amount: 'Refund amount',
    rm_id: 'Assigned RM',
    op_id: 'Assigned OP',
    referral_phone_number: 'Referral phone',
    remarks: 'Remarks',
};

function normalizePriority(value) {
    if (!value || typeof value !== 'string') return 'NORMAL';
    const u = value.toUpperCase();
    if (['LOW', 'NORMAL', 'HIGH'].includes(u)) return u;
    if (u === 'MEDIUM') return 'NORMAL';
    if (u === 'URGENT') return 'HIGH';
    return 'NORMAL';
}

function humanizeValidationMessage(msg) {
    if (!msg || typeof msg !== 'string') return 'Invalid value.';
    let s = msg.trim();
    s = s.replace(/^Value error,\s*/i, '');
    if (/previous financial year|not allowed|cannot be added|upcoming/i.test(s)) {
        return getFinancialYearFormHint();
    }
    if (/LOW.*NORMAL.*HIGH/i.test(s)) {
        return 'Choose Low, Normal, or High in the Priority field.';
    }
    if (/^Input should be\b/i.test(s)) {
        return s.replace(/^Input should be\s*/i, 'Allowed values: ');
    }
    return s;
}

function normalizeApiFieldKey(raw) {
    if (!raw) return '';
    let k = String(raw).trim();
    if (k.startsWith('body.')) k = k.slice(5);
    return k;
}

function formatFieldLabel(k) {
    if (!k) return 'Form';
    return String(k).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** FastAPI sometimes returns one string: "body.priority: …, body.financial_year: …" */
function parseConcatenatedValidationDetail(str) {
    if (!str || typeof str !== 'string') return null;
    const trimmed = str.trim();
    if (!trimmed.includes('body.')) return null;

    const chunks = trimmed.split(/\s*,\s*(?=body\.)/).map((c) => c.trim()).filter(Boolean);
    const out = [];
    for (const chunk of chunks) {
        const m = /^body\.([\w]+)\s*:\s*(.+)$/s.exec(chunk);
        if (m) out.push({ key: m[1], msg: m[2].trim() });
    }
    return out.length ? out : null;
}

/** e.g. axios joins field messages with newlines — "priority: …\\nfinancial_year: …" */
function parseMultilineValidationMessage(msg) {
    if (!msg || typeof msg !== 'string') return null;
    const lines = msg.split(/\n+/).map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return null;

    const out = [];
    for (const line of lines) {
        if (line.includes('body.')) {
            const sub = parseConcatenatedValidationDetail(line);
            if (sub) out.push(...sub);
            continue;
        }
        const idx = line.indexOf(':');
        if (idx === -1) {
            out.push({ key: '', msg: line });
            continue;
        }
        const keyPart = line.slice(0, idx).trim();
        const msgPart = line.slice(idx + 1).trim();
        out.push({ key: normalizeApiFieldKey(keyPart), msg: msgPart });
    }
    return out.length ? out : null;
}

/** @returns {{ label: string, detail: string }[]} */
function formatIncomeTaxApiErrors(err) {
    const items = [];
    const structured = getIncomeTaxErrorPayload(err);
    if (structured?.fields && Object.keys(structured.fields).length > 0) {
        for (const [key, raw] of Object.entries(structured.fields)) {
            const k = normalizeApiFieldKey(key);
            items.push({
                label: FIELD_LABELS[k] || formatFieldLabel(k),
                detail: humanizeValidationMessage(String(raw)),
            });
        }
        return items;
    }
    if (structured?.message && structured.type !== 'duplicate_record') {
        return [{ label: 'Could not save', detail: structured.message }];
    }

    const fields = err?.fields && typeof err.fields === 'object' ? err.fields : null;

    if (fields && Object.keys(fields).length > 0) {
        for (const [key, raw] of Object.entries(fields)) {
            const k = normalizeApiFieldKey(key);
            items.push({
                label: FIELD_LABELS[k] || formatFieldLabel(k),
                detail: humanizeValidationMessage(String(raw)),
            });
        }
        return items;
    }

    const detail = err?.response?.data?.detail ?? err?.data?.detail;

    if (typeof detail === 'string') {
        const parsed = parseConcatenatedValidationDetail(detail);
        if (parsed) {
            for (const { key, msg } of parsed) {
                const k = normalizeApiFieldKey(key);
                items.push({
                    label: FIELD_LABELS[k] || formatFieldLabel(k),
                    detail: humanizeValidationMessage(msg),
                });
            }
            return items;
        }
    }

    if (Array.isArray(detail)) {
        detail.forEach((entry) => {
            const loc = Array.isArray(entry?.loc) ? entry.loc : [];
            const rawKey = loc.length ? String(loc[loc.length - 1]) : '';
            const k = normalizeApiFieldKey(rawKey);
            items.push({
                label: FIELD_LABELS[k] || formatFieldLabel(k) || 'Form',
                detail: humanizeValidationMessage(entry?.msg || 'Invalid value'),
            });
        });
        if (items.length) return items;
    }

    const msg = typeof err?.message === 'string' ? err.message.trim() : '';
    if (msg) {
        let parsed = parseConcatenatedValidationDetail(msg);
        if (!parsed) parsed = parseMultilineValidationMessage(msg);
        if (parsed) {
            for (const { key, msg: part } of parsed) {
                const k = normalizeApiFieldKey(key);
                items.push({
                    label: FIELD_LABELS[k] || (k ? formatFieldLabel(k) : 'Details'),
                    detail: humanizeValidationMessage(part),
                });
            }
            return items;
        }
        return [{ label: 'Something went wrong', detail: msg }];
    }

    return [{ label: 'Save failed', detail: 'Could not save this record. Please try again.' }];
}

const IncomeTaxFormModal = ({
    isOpen,
    onClose,
    editingRecord,
    onSuccess,
    onDuplicateRecord,
    duplicateNotice = null,
    onOpenExistingRecord,
    configs,
    profileData,
    /** Center modal (new record) vs right drawer (edit from table) */
    variant = 'modal',
}) => {
    const navigate = useNavigate();
    const isEditMode = Boolean(editingRecord);
    const { showRmField, showOpField, showAssignmentSection } = getRmOpAssignmentVisibility(profileData);
    const initialState = {
        client_name: '',
        mobile: '',
        email_id: '',
        pan_number: '',
        financial_year: [],
        filed_status: 'NOT_FILED',
        source_of_income: [],
        language: '',
        state: '',
        referral_phone_number: '',
        refund_amount: '',
        rm_id: '',
        op_id: '',
        priority: 'NORMAL',
        remarks: '',
    };

    const [form, setForm] = useState(initialState);
    const [loading, setLoading] = useState(false);
    const [statusLoading, setStatusLoading] = useState(false);
    const [customFyInput, setCustomFyInput] = useState('');
    const [otherSourceInput, setOtherSourceInput] = useState('');
    const [otherSourceServices, setOtherSourceServices] = useState([]);
    /** Array of user-facing error lines; null when none */
    const [error, setError] = useState(null);
    const formScrollRef = useRef(null);

    useEffect(() => {
        if (!isOpen) return;
        if ((error?.length || duplicateNotice) && formScrollRef.current) {
            formScrollRef.current.scrollTo({ top: 0, behavior: 'smooth' });
        }
    }, [error, duplicateNotice, isOpen]);

    useEffect(() => {
        if (isOpen) {
            if (editingRecord) {
                // Find matching state from configs to handle case mismatches (e.g. "Goa" vs "GOA")
                const matchingState = configs.states?.find(s => 
                    s.value?.toUpperCase() === editingRecord.state?.toUpperCase() || 
                    s.display_name?.toUpperCase() === editingRecord.state?.toUpperCase()
                );

                const { standard, custom } = splitSourceOfIncome(editingRecord.source_of_income);
                setForm({
                    ...initialState,
                    ...editingRecord,
                    priority: normalizePriority(editingRecord.priority),
                    state: matchingState ? matchingState.value : (editingRecord.state || ''),
                    financial_year: asStringArray(editingRecord.financial_year),
                    source_of_income: standard,
                    refund_amount: editingRecord.refund_amount !== null ? editingRecord.refund_amount : ''
                });
                setOtherSourceServices(custom);
            } else {
                setForm(initialState);
                setOtherSourceServices([]);
            }
            setError(null);
            setCustomFyInput('');
            setOtherSourceInput('');
        }
    }, [isOpen, editingRecord]);

    if (!isOpen) return null;
    if (variant === 'drawer' && !editingRecord) return null;

    const financialYearPresetOptions = buildFinancialYearPresetOptions({ yearsBack: 5 });

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        let finalValue = type === 'checkbox' ? checked : value;
        
        if (name === 'pan_number') {
            finalValue = finalValue.toUpperCase();
        }
        if (name === 'referral_phone_number') {
            finalValue = String(finalValue).replace(/\D/g, '').slice(0, 10);
        }

        setForm(prev => ({ ...prev, [name]: finalValue }));
    };

    const toggleFinancialYear = (fy) => {
        setForm((prev) => {
            const set = new Set(prev.financial_year);
            if (set.has(fy)) set.delete(fy);
            else set.add(fy);
            return { ...prev, financial_year: [...set] };
        });
    };

    const addCustomFinancialYear = () => {
        const fy = customFyInput.trim();
        if (!fy) return;
        const err = validateFinancialYearAllowed(fy);
        if (err) {
            setError([{ label: 'Financial Year', detail: err }]);
            return;
        }
        setForm((prev) => {
            const set = new Set(prev.financial_year);
            set.add(fy);
            return { ...prev, financial_year: [...set] };
        });
        setCustomFyInput('');
        setError(null);
    };

    const toggleSourceOfIncome = (code) => {
        setForm((prev) => {
            const set = new Set(prev.source_of_income);
            if (set.has(code)) {
                set.delete(code);
                if (code === 'OTHER_SOURCES') {
                    setOtherSourceServices([]);
                    setOtherSourceInput('');
                }
            } else {
                set.add(code);
            }
            return { ...prev, source_of_income: [...set] };
        });
    };

    const addOtherSourceService = () => {
        const label = otherSourceInput.trim();
        if (!label) return;
        if (label.length < 2) {
            setError([{ label: 'Other Sources', detail: 'Service name must be at least 2 characters.' }]);
            return;
        }
        setForm((prev) => {
            const codes = new Set(prev.source_of_income);
            codes.add('OTHER_SOURCES');
            return { ...prev, source_of_income: [...codes] };
        });
        setOtherSourceServices((prev) => {
            const exists = prev.some((s) => s.toLowerCase() === label.toLowerCase());
            if (exists) return prev;
            return [...prev, label];
        });
        setOtherSourceInput('');
        setError(null);
    };

    const removeOtherSourceService = (label) => {
        setOtherSourceServices((prev) => prev.filter((s) => s !== label));
    };

    const hasOtherSources = form.source_of_income.includes('OTHER_SOURCES');

    const validateForm = () => {
        const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;
        if (!panRegex.test(form.pan_number)) {
            return [
                {
                    label: 'PAN Number',
                    detail: 'Use five letters, four digits, one letter (example: ABCDE1234F).',
                },
            ];
        }

        const fyList = asStringArray(form.financial_year);
        if (fyList.length === 0) {
            return [{ label: 'Financial Year', detail: 'Select or add at least one financial year.' }];
        }
        for (const fy of fyList) {
            const fyErr = validateFinancialYearAllowed(fy);
            if (fyErr) return [{ label: 'Financial Year', detail: fyErr }];
        }

        const sourcePayload = buildSourceOfIncomePayload(
            form.source_of_income,
            otherSourceServices
        );
        if (!sourcePayload?.length) {
            if (form.source_of_income.includes('OTHER_SOURCES')) {
                return [{
                    label: 'Other Sources',
                    detail: 'Please add at least one service or income type under Other Sources.',
                }];
            }
            return [{
                label: 'Source of income',
                detail: 'Select or add at least one source of income.',
            }];
        }

        if (!form.client_name) return [{ label: 'Client Name', detail: 'This field is required.' }];
        if (!form.mobile) return [{ label: 'Mobile', detail: 'This field is required.' }];

        const refPhone = String(form.referral_phone_number || '').replace(/\D/g, '');
        if (refPhone.length > 0 && refPhone.length !== 10) {
            return [{ label: 'Referral phone', detail: 'Enter a valid 10-digit mobile number, or leave blank.' }];
        }

        return null;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const validationError = validateForm();
        if (validationError) {
            setError(validationError);
            return;
        }

        setLoading(true);
        setError(null);

        const payload = {
            client_name: form.client_name,
            mobile: form.mobile,
            email_id: form.email_id || null,
            pan_number: form.pan_number,
            financial_year: asStringArray(form.financial_year),
            filed_status: form.filed_status,
            source_of_income: buildSourceOfIncomePayload(
                form.source_of_income,
                otherSourceServices
            ),
            language: form.language || null,
            state: form.state || null,
            referral_phone_number: (form.referral_phone_number || '').replace(/\D/g, '') || null,
            refund_amount: form.refund_amount ? parseFloat(form.refund_amount) : 0,
            rm_id: resolveRmIdForPayload({
                profileData,
                isEditMode,
                editingRecord,
                formRmId: form.rm_id,
            }),
            op_id: resolveOpIdForPayload({
                profileData,
                isEditMode,
                editingRecord,
                formOpId: form.op_id,
            }),
            priority: normalizePriority(form.priority),
            remarks: form.remarks || null,
        };

        try {
            if (editingRecord) {
                await editIncomeTax(editingRecord.id, payload);
            } else {
                await createIncomeTax(payload);
            }
            onSuccess();
        } catch (err) {
            console.error("Error saving income tax record:", err);
            const apiErr = getIncomeTaxErrorPayload(err);
            if (
                !editingRecord
                && apiErr?.type === 'duplicate_record'
                && apiErr.existingIncomeTaxId
            ) {
                const notice = {
                    message:
                        apiErr.message
                        || 'A record already exists for this client in this calendar year.',
                    recordYear: apiErr.recordYear,
                    existingIncomeTaxId: apiErr.existingIncomeTaxId,
                };
                setError(null);
                if (onDuplicateRecord) {
                    onDuplicateRecord(notice);
                }
                return;
            }
            setError(formatIncomeTaxApiErrors(err));
        } finally {
            setLoading(false);
        }
    };

    const isRecordActive = form.is_active !== false;

    const handleToggleActive = async () => {
        if (!editingRecord?.id) return;
        const nextActive = !isRecordActive;
        setStatusLoading(true);
        setError(null);
        try {
            await setIncomeTaxActive(editingRecord.id, nextActive);
            setForm((prev) => ({ ...prev, is_active: nextActive }));
            onSuccess();
        } catch (err) {
            console.error(`Failed to ${isRecordActive ? 'deactivate' : 'activate'} income tax record:`, err);
            setError(formatIncomeTaxApiErrors(err));
        } finally {
            setStatusLoading(false);
        }
    };

    const errorBanner = error && error.length > 0 && (
        <div className="itr-duplicate-notice itr-form-alert" role="alert">
            <div className="itr-duplicate-notice__icon">
                <AlertCircle size={22} />
            </div>
            <div className="itr-duplicate-notice__body">
                <strong className="itr-duplicate-notice__title">
                    Please fix the following before continuing
                </strong>
                <ul className="itr-duplicate-notice__error-list">
                    {error.map((item, idx) => (
                        <li key={idx} className="itr-duplicate-notice__message">
                            {typeof item === 'object' && item.label && item.label !== 'Form'
                                ? `${item.label}: ${item.detail}`
                                : (item.detail ?? String(item))}
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    );

    const formSections = (
        <>
                        <DuplicateRecordNotice
                            notice={duplicateNotice}
                            onContinue={onOpenExistingRecord}
                            loading={loading}
                        />
                        {errorBanner}
                        <div className="form-section-group">
                            <h4 className="section-title">Primary Identity</h4>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label>Client Name *</label>
                                    <input type="text" name="client_name" value={form.client_name} onChange={handleChange} required placeholder="Full Name" />
                                </div>
                                <div className="form-group-v4">
                                    <label>PAN Number *</label>
                                    <input type="text" name="pan_number" value={form.pan_number} onChange={handleChange} required placeholder="ABCDE1234F" />
                                </div>
                                <div className="form-group-v4">
                                    <label>Priority</label>
                                    <FormCustomSelect
                                        name="priority"
                                        value={form.priority}
                                        onChange={handleChange}
                                        options={[
                                            { value: 'LOW', label: 'Low' },
                                            { value: 'NORMAL', label: 'Normal' },
                                            { value: 'HIGH', label: 'High' },
                                        ]}
                                        placeholder="Normal"
                                        ariaLabel="Priority"
                                    />
                                    <p className="field-hint-v4">Used for internal triage.</p>
                                </div>
                            </div>

                            <div className="itr-choice-panel itr-fy-panel">
                                <div className="itr-choice-panel__head">
                                    <div className="itr-choice-panel__icon">
                                        <Calendar size={18} />
                                    </div>
                                    <div>
                                        <p className="itr-choice-panel__title">Financial Year *</p>
                                        <p className="itr-choice-panel__subtitle">
                                            Previous financial years only — for the current calendar year you file earlier FYs here
                                        </p>
                                    </div>
                                </div>
                                <div className="itr-fy-pills" role="group" aria-label="Financial years">
                                    {financialYearPresetOptions.map((fy) => {
                                        const selected = form.financial_year.includes(fy);
                                        return (
                                            <button
                                                key={fy}
                                                type="button"
                                                className={`itr-fy-pill${selected ? ' is-selected' : ''}`}
                                                onClick={() => toggleFinancialYear(fy)}
                                                aria-pressed={selected}
                                            >
                                                {fy}
                                            </button>
                                        );
                                    })}
                                </div>
                                <div className="itr-fy-custom-row">
                                    <input
                                        type="text"
                                        className="itr-fy-custom-input"
                                        value={customFyInput}
                                        onChange={(e) => setCustomFyInput(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') {
                                                e.preventDefault();
                                                addCustomFinancialYear();
                                            }
                                        }}
                                        placeholder="Other year — e.g. 2023-24"
                                        aria-describedby="fy-format-hint"
                                    />
                                    <button type="button" className="btn-itr-fy-add" onClick={addCustomFinancialYear}>
                                        <Plus size={14} />
                                        Add year
                                    </button>
                                </div>
                                {form.financial_year.length > 0 && (
                                    <div className="itr-selected-summary">
                                        <span className="itr-selected-summary__label">Selected</span>
                                        <div className="itr-multi-tags">
                                            {form.financial_year.map((fy) => (
                                                <span key={fy} className="itr-multi-tag">
                                                    {fy}
                                                    <button type="button" onClick={() => toggleFinancialYear(fy)} aria-label={`Remove ${fy}`}>
                                                        ×
                                                    </button>
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                <p id="fy-format-hint" className="itr-choice-panel__hint">
                                    {getFinancialYearFormHint()}
                                </p>
                            </div>
                        </div>

                        <div className="form-section-group">
                            <h4 className="section-title">Contact & Location</h4>
                            <div className="form-grid-2">
                                <div className="form-group-v4">
                                    <label>Mobile *</label>
                                    <input type="text" name="mobile" value={form.mobile} onChange={handleChange} required placeholder="+91" />
                                </div>
                                <div className="form-group-v4">
                                    <label>Email ID</label>
                                    <input type="email" name="email_id" value={form.email_id} onChange={handleChange} placeholder="example@mail.com" />
                                </div>
                            </div>
                            <div className="form-grid-2" style={{ marginTop: '20px' }}>
                                <div className="form-group-v4">
                                    <label>State</label>
                                    <FormCustomSelect
                                        name="state"
                                        value={form.state}
                                        onChange={handleChange}
                                        options={optionsFromConfig(configs?.states || [], 'Select State')}
                                        placeholder="Select State"
                                        ariaLabel="State"
                                    />
                                </div>
                                <div className="form-group-v4">
                                    <label>Language</label>
                                    <FormCustomSelect
                                        name="language"
                                        value={form.language}
                                        onChange={handleChange}
                                        options={optionsFromConfig(configs?.languages || [], 'Select Language')}
                                        placeholder="Select Language"
                                        ariaLabel="Language"
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="form-section-group">
                            <h4 className="section-title">Filing & Financials</h4>
                            <div className="itr-choice-panel itr-source-panel">
                                <div className="itr-choice-panel__head">
                                    <div className="itr-choice-panel__icon itr-choice-panel__icon--wallet">
                                        <Wallet size={18} />
                                    </div>
                                    <div>
                                        <p className="itr-choice-panel__title">Source of Income</p>
                                        <p className="itr-choice-panel__subtitle">Choose all that apply for this filing</p>
                                    </div>
                                </div>
                                <div className="itr-source-grid" role="group" aria-label="Sources of income">
                                    {INCOME_SOURCE_OPTIONS.map(({ value, label }) => {
                                        const selected = form.source_of_income.includes(value);
                                        return (
                                            <button
                                                key={value}
                                                type="button"
                                                className={`itr-source-tile${selected ? ' is-selected' : ''}`}
                                                onClick={() => toggleSourceOfIncome(value)}
                                                aria-pressed={selected}
                                            >
                                                <span className="itr-source-tile__label">{label}</span>
                                            </button>
                                        );
                                    })}
                                </div>
                                {hasOtherSources && (
                                    <div className="itr-other-source-block">
                                        <label className="itr-other-source-block__label">
                                            Specify service / income type
                                        </label>
                                        <div className="itr-fy-custom-row">
                                            <input
                                                type="text"
                                                className="itr-fy-custom-input"
                                                value={otherSourceInput}
                                                onChange={(e) => setOtherSourceInput(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') {
                                                        e.preventDefault();
                                                        addOtherSourceService();
                                                    }
                                                }}
                                                placeholder="e.g. Freelance consulting, Rental from shop"
                                                maxLength={100}
                                            />
                                            <button
                                                type="button"
                                                className="btn-itr-fy-add btn-itr-other-add"
                                                onClick={addOtherSourceService}
                                            >
                                                <Plus size={14} />
                                                Add
                                            </button>
                                        </div>
                                        {otherSourceServices.length > 0 && (
                                            <div className="itr-multi-tags itr-other-source-tags">
                                                {otherSourceServices.map((service) => (
                                                    <span key={service} className="itr-multi-tag itr-other-tag">
                                                        {service}
                                                        <button
                                                            type="button"
                                                            onClick={() => removeOtherSourceService(service)}
                                                            aria-label={`Remove ${service}`}
                                                        >
                                                            ×
                                                        </button>
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        <p className="itr-choice-panel__hint itr-other-source-hint">
                                            Add each additional income source not listed above.
                                        </p>
                                    </div>
                                )}
                            </div>
                            <div className="form-grid-2 itr-filing-row">
                                <div className="form-group-v4">
                                    <label>Filing Status</label>
                                    <FormCustomSelect
                                        name="filed_status"
                                        value={form.filed_status}
                                        onChange={handleChange}
                                        options={[
                                            { value: 'NOT_FILED', label: 'Not Filed' },
                                            { value: 'FILED', label: 'Filed' },
                                        ]}
                                        placeholder="Not Filed"
                                        ariaLabel="Filing status"
                                    />
                                </div>
                                <div className="form-group-v4">
                                    <label>Refund Amount</label>
                                    <input type="number" name="refund_amount" value={form.refund_amount} onChange={handleChange} placeholder="0.00" />
                                </div>
                            </div>
                        </div>

                        {showAssignmentSection && (
                        <div className="form-section-group">
                            <h4 className="section-title">Internal Management</h4>
                            <div className={showRmField && showOpField ? 'form-grid-2' : 'form-grid-1'}>
                                {showRmField && (
                                <div className="form-group-v4">
                                    <label>Assigned RM</label>
                                    <FormCustomSelect
                                        name="rm_id"
                                        value={form.rm_id}
                                        onChange={handleChange}
                                        options={optionsFromPairs(
                                            buildRmOpSelectOptions(configs?.activeRMs || [], {
                                                id: editingRecord?.rm_id,
                                                label: editingRecord?.rm_name || editingRecord?.rm_username,
                                            }),
                                            'Select RM'
                                        )}
                                        placeholder="Select RM"
                                        ariaLabel="Assigned RM"
                                    />
                                </div>
                                )}
                                {showOpField && (
                                <div className="form-group-v4">
                                    <label>Assigned OP</label>
                                    <FormCustomSelect
                                        name="op_id"
                                        value={form.op_id}
                                        onChange={handleChange}
                                        options={optionsFromPairs(
                                            buildRmOpSelectOptions(configs?.activeOps || [], {
                                                id: editingRecord?.op_id,
                                                label: editingRecord?.op_name || editingRecord?.op_username,
                                            }),
                                            'Select OP'
                                        )}
                                        placeholder="Select OP"
                                        ariaLabel="Assigned OP"
                                    />
                                </div>
                                )}
                            </div>
                        </div>
                        )}

                        <div className="form-section-group">
                            <h4 className="section-title">Referral Information</h4>
                            <div className="form-grid-2">
                                <div className="form-group-v4">
                                    <label>Referrer phone</label>
                                    <input
                                        type="tel"
                                        inputMode="numeric"
                                        maxLength={10}
                                        name="referral_phone_number"
                                        value={form.referral_phone_number}
                                        onChange={handleChange}
                                        placeholder="10-digit mobile (optional)"
                                    />
                                </div>
                            </div>

                            <div className="form-group-v4" style={{ marginTop: '24px' }}>
                                <label>Internal Remarks</label>
                                <textarea 
                                    name="remarks" 
                                    value={form.remarks} 
                                    onChange={handleChange} 
                                    placeholder="Add any specific instructions or notes for this filing..." 
                                    rows={4} 
                                    style={{
                                        width: '100%',
                                        padding: '16px',
                                        background: 'var(--bg-input)',
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius-lg)',
                                        color: 'var(--text-primary)',
                                        fontSize: '13px',
                                        resize: 'none',
                                        minHeight: '120px'
                                    }}
                                />
                            </div>
                        </div>

        </>
    );

    const incomeTaxId = editingRecord?.id;
    const filedStatusNorm = String(form.filed_status || editingRecord?.filed_status || '')
        .trim()
        .toUpperCase();
    const showSchedulePayment = variant === 'drawer'
        && isEditMode
        && Boolean(incomeTaxId)
        && form.is_active !== false
        && filedStatusNorm === 'FILED';

    const handleSchedulePayment = async () => {
        if (!incomeTaxId) return;
        onClose();
        let openSchedulePaymentDrawer = false;
        try {
            const lead = await getCrmLeadByIncomeTaxId(incomeTaxId);
            openSchedulePaymentDrawer = isItrCrmStageForSchedulePayment(lead?.stage);
        } catch (err) {
            console.warn('Could not load CRM lead for schedule payment:', err);
        }
        navigate(`/crm-dashboard?${buildIncomeTaxCrmLeadActionSearchParams(incomeTaxId, openSchedulePaymentDrawer).toString()}`);
    };

    const drawerFooter = (
        <AppDrawerFooter
            leading={
                showSchedulePayment ? (
                    <button
                        type="button"
                        onClick={handleSchedulePayment}
                        className="gst-btn-schedule-payment"
                        disabled={loading || statusLoading}
                        title={`Schedule payment in CRM for income tax record ${incomeTaxId}`}
                    >
                        <CalendarClock size={16} />
                        Schedule Payment
                    </button>
                ) : null
            }
        >
            {editingRecord && (
                <AppDrawerBtnDelete
                    onClick={handleToggleActive}
                    disabled={loading || statusLoading}
                    label={isRecordActive ? 'Deactivate' : 'Activate'}
                />
            )}
            <AppDrawerBtnCancel onClick={onClose} disabled={loading || statusLoading} />
            <AppDrawerBtnSave
                type="submit"
                loading={loading}
                loadingLabel={editingRecord ? 'Saving...' : 'Creating...'}
                label={editingRecord ? 'Save Changes' : 'Create Record'}
                disabled={statusLoading}
            />
        </AppDrawerFooter>
    );

    const modalFooterButtons = (
        <>
            <button type="button" className="btn-cancel-v4" onClick={onClose} disabled={loading}>
                Cancel
            </button>
            <button type="submit" className="btn-submit-v4" disabled={loading}>
                {loading ? <Loader2 className="spin" size={14} /> : null}
                {editingRecord ? 'Save Changes' : 'Create Record'}
            </button>
        </>
    );

    if (variant === 'drawer') {
        return (
            <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={onClose}>
                <div
                    className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell itr-side-drawer-shell itr-income-tax-form-drawer app-drawer-panel"
                    onClick={(e) => e.stopPropagation()}
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="itr-edit-drawer-title"
                >
                    <div className="drawer-header">
                        <div>
                            <h2 id="itr-edit-drawer-title" style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)', margin: 0 }}>
                                {duplicateNotice ? 'Update existing record' : 'Edit Income Tax Record'}
                            </h2>
                            <p style={{ margin: '6px 0 0', fontSize: '13px', color: 'var(--text-primary)' }}>
                                {editingRecord.id}
                                {editingRecord.client_name ? ` · ${editingRecord.client_name}` : ''}
                            </p>
                        </div>
                        <button type="button" className="btn-drawer-close" onClick={onClose} disabled={loading} aria-label="Close">
                            <X size={20} />
                        </button>
                    </div>
                    <form className="modal-form-v4 itr-drawer-form flex-drawer-form" onSubmit={handleSubmit}>
                        <div className="drawer-content itr-drawer-form-scroll" ref={formScrollRef}>{formSections}</div>
                        {drawerFooter}
                    </form>
                </div>
            </div>
        );
    }

    return (
        <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={onClose}>
            <div className="gst-modal-card-v4 wide-modal app-drawer-panel gst-reg-side-drawer-shell" onClick={(e) => e.stopPropagation()}>
                <button className="btn-close-modal-v4-top" onClick={onClose} disabled={loading}>
                    <X size={20} />
                </button>
                <div className="modal-header-v4">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4">
                            <FileText size={24} />
                        </div>
                        <div className="modal-title-box">
                            <h2>New Income Tax Record</h2>
                            <p className="modal-subtitle-v4">Enter client details and filing status</p>
                        </div>
                    </div>
                </div>

                <form className="modal-form-v4" onSubmit={handleSubmit}>
                    <div className="form-scroll-container" ref={formScrollRef}>{formSections}</div>

                    <div className="modal-footer-v4 app-drawer-edit-footer">
                        <div className="footer-actions-v4">{modalFooterButtons}</div>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default IncomeTaxFormModal;
