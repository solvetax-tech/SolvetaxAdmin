import React from 'react';
import { createPortal } from 'react-dom';
import {
    X,
    Phone,
    PhoneCall,
    Calendar,
    MessageSquare,
    Loader2,
} from 'lucide-react';
import CrmLeadRemarksField from './CrmLeadRemarksField';
import ModernDateTimePicker from '../common/ModernDateTimePicker';
import CustomSelect from '../common/CustomSelect';
import { formatPitchLabel } from './crmLeadPitchUtils';
import './crmCallActionDrawer.css';

function formatStatusLabel(code) {
    return formatPitchLabel(code);
}

function formatDisplayMobile(mobile) {
    const digits = String(mobile || '').replace(/\D/g, '');
    if (digits.length === 10) return `+91 ${digits}`;
    return mobile || '—';
}

export default function CrmLeadCallActionDrawer({
    lead,
    entityType,
    callLogData,
    onFieldChange,
    availableStatuses = [],
    errors = {},
    onClearError,
    saving = false,
    onClose,
    onSubmit,
}) {
    if (!lead) return null;

    const pitchLabel = formatPitchLabel(callLogData.call_type_code) || '—';
    const minFollowup = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);

    const clearError = (field) => {
        if (onClearError && errors[field]) onClearError(field);
    };

    return createPortal(
        <>
            <div
                className="crm-drawer-overlay"
                onClick={onClose}
                role="presentation"
            />
            <div
                className="crm-drawer-panel crm-call-action-drawer"
                role="dialog"
                aria-labelledby="crm-call-action-title"
                onClick={(e) => e.stopPropagation()}
            >
                <header className="crm-call-action-hero">
                    <button
                        type="button"
                        className="crm-call-action-close"
                        onClick={onClose}
                        aria-label="Close"
                    >
                        <X size={18} />
                    </button>
                    <div className="crm-call-action-hero-inner">
                        <div className="crm-call-action-avatar">
                            <Phone size={22} strokeWidth={2} />
                        </div>
                        <div className="crm-call-action-hero-text">
                            <h3 id="crm-call-action-title">
                                {formatDisplayMobile(lead.mobile)}
                            </h3>
                            <p className="crm-call-action-hero-meta">Update call status &amp; remarks</p>
                            <div className="crm-call-action-badges">
                                {lead.stage && (
                                    <span className="crm-call-action-stage">
                                        {formatStatusLabel(lead.stage)}
                                    </span>
                                )}
                                {lead.id != null && (
                                    <span className="crm-call-action-id">Lead {lead.id}</span>
                                )}
                            </div>
                        </div>
                    </div>
                </header>

                <div className="drawer-body crm-call-action-body">
                    <section>
                        <h4 className="crm-call-action-section-title">Call context</h4>
                        <div className="crm-call-action-card crm-call-action-card--muted">
                            <div className="crm-call-action-readonly-grid">
                                <div className="crm-call-action-readonly-item">
                                    <label>Mobile</label>
                                    <span>{lead.mobile || '—'}</span>
                                </div>
                                <div className="crm-call-action-readonly-item">
                                    <label>Pitch type</label>
                                    <span>{pitchLabel}</span>
                                </div>
                            </div>
                        </div>
                    </section>

                    <section>
                        <h4 className="crm-call-action-section-title">Update details</h4>
                        <div className="crm-call-action-card">
                            <div className="crm-call-action-fields">
                                <div className="crm-call-action-field">
                                    <label>
                                        <PhoneCall size={13} />
                                        Call status
                                    </label>
                                    <CustomSelect
                                        value={callLogData.call_status_code || ''}
                                        options={[
                                            { value: '', label: 'Select status' },
                                            ...availableStatuses.map((code) => ({
                                                value: code,
                                                label: formatStatusLabel(code),
                                            })),
                                        ]}
                                        onChange={(val) => {
                                            onFieldChange('call_status_code', val);
                                            clearError('call_status_code');
                                        }}
                                        disabled={!callLogData.call_type_code}
                                        error={Boolean(errors.call_status_code)}
                                        ariaLabel="Call status"
                                        placeholder="Select status"
                                        menuMaxHeight={240}
                                    />
                                </div>

                                <div className="crm-call-action-field">
                                    <label>
                                        <Calendar size={13} />
                                        Follow-up at
                                    </label>
                                    <ModernDateTimePicker
                                        value={callLogData.followup_at}
                                        onChange={(val) => {
                                            onFieldChange('followup_at', val);
                                            clearError('followup_at');
                                        }}
                                        min={minFollowup}
                                        placeholder="Select follow-up date & time"
                                        outputFormat="local"
                                        placement="bottom"
                                        className="modern-dt-picker--crm"
                                        error={Boolean(errors.followup_at)}
                                    />
                                    {errors.followup_at && (
                                        <span className="crm-call-action-field-error">
                                            {errors.followup_at}
                                        </span>
                                    )}
                                </div>

                                <div className="crm-call-action-field">
                                    <label>
                                        <MessageSquare size={13} />
                                        Remarks
                                    </label>
                                    <CrmLeadRemarksField
                                        entityType={entityType}
                                        stage={lead.stage}
                                        callStatusCode={callLogData.call_status_code}
                                        value={callLogData.remarks}
                                        onChange={(remarks) => {
                                            onFieldChange('remarks', remarks);
                                            clearError('remarks');
                                        }}
                                        error={errors.remarks}
                                        onClearError={() => clearError('remarks')}
                                        rows={4}
                                    />
                                </div>
                            </div>
                        </div>
                    </section>
                </div>

                <footer className="drawer-footer">
                    <button
                        type="button"
                        className="btn-drawer-secondary"
                        onClick={onClose}
                        disabled={saving}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        className="btn-drawer-primary"
                        onClick={onSubmit}
                        disabled={saving}
                    >
                        {saving ? (
                            <>
                                <Loader2 size={16} className="spin" />
                                Saving…
                            </>
                        ) : (
                            'Save update'
                        )}
                    </button>
                </footer>
            </div>
        </>,
        document.body
    );
}
