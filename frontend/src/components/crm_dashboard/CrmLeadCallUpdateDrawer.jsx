import React, { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { User, X } from 'lucide-react';
import api from '../../utils/api';
import {
    formatPitchLabel,
    getAvailableStatusCodes,
    getCallUpdateApiPath,
    ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS,
    PITCH_TYPES,
} from './crmLeadPitchUtils';
import { PAYMENT_PENDING_DEFAULT_REMARK } from './crmLeadRemarksConfig';
import CrmLeadRemarksField from './CrmLeadRemarksField';
import ModernDateTimePicker from '../common/ModernDateTimePicker';
import CustomSelect from '../common/CustomSelect';

const MANDATORY_STATUSES = [
    'CALL_BACK',
    'CONNECTED_AND_SCHEDULED',
    'SCHEDULED_PAYMENT',
    'SCHEDULED_PAYMENTS',
];

export default function CrmLeadCallUpdateDrawer({
    lead,
    entityType,
    callTypeCode,
    mappingData,
    onClose,
    onSuccess,
}) {
    const [callLogData, setCallLogData] = useState({
        call_status_code: '',
        followup_at: '',
        remarks: '',
    });
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);

    const pitchLabel = callTypeCode === PITCH_TYPES.FINAL ? 'Final pitch call' : 'First pitch call';

    const availableStatuses = useMemo(
        () => getAvailableStatusCodes(callTypeCode, mappingData?.pitch_to_statuses, {
            entityType,
            leadStage: lead?.stage,
        }),
        [callTypeCode, mappingData, entityType, lead?.stage]
    );

    if (!lead || !callTypeCode) return null;

    const minFollowup = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);

    const handleSubmit = async () => {
        setErrors({});
        const newErrors = {};

        if (!callLogData.call_status_code) {
            alert('Please select a call status.');
            return;
        }

        if (MANDATORY_STATUSES.includes(callLogData.call_status_code)) {
            if (!callLogData.followup_at) newErrors.followup_at = 'Required';
            if (!callLogData.remarks?.trim()) newErrors.remarks = 'Required';
        }

        if (Object.keys(newErrors).length > 0) {
            setErrors(newErrors);
            return;
        }

        setSaving(true);
        try {
            const payload = {
                call_type_code: callTypeCode,
                call_status_code: callLogData.call_status_code,
                followup_at: callLogData.followup_at
                    ? new Date(callLogData.followup_at).toISOString()
                    : null,
                remarks: callLogData.remarks,
            };
            await api.post(getCallUpdateApiPath(entityType, lead.id), payload, {
                params: { entity_type: entityType },
            });
            onClose();
            if (onSuccess) {
                setTimeout(() => onSuccess(), 600);
            }
        } catch (err) {
            console.error('Call update failed:', err);
            alert(err?.response?.data?.detail?.message || err?.response?.data?.detail || 'Failed to update lead.');
        } finally {
            setSaving(false);
        }
    };

    return createPortal(
        <>
            <div className="crm-drawer-overlay" onClick={onClose} role="presentation" />
            <div className="crm-drawer-panel" role="dialog" aria-labelledby="crm-call-update-title">
                <div className="drawer-header">
                    <div className="drawer-title">
                        <User size={20} />
                        <div>
                            <h3 id="crm-call-update-title">{lead.mobile}</h3>
                            <span style={{ fontSize: '12px', color: 'var(--text-primary)' }}>
                                {pitchLabel} &bull; {lead.stage} &bull; {lead.id}
                            </span>
                        </div>
                    </div>
                    <button type="button" className="btn-close-drawer" onClick={onClose} aria-label="Close">
                        <X size={20} />
                    </button>
                </div>

                <div className="drawer-body">
                    <div className="drawer-section">
                        <div className="crm-input-group">
                            <label>Mobile</label>
                            <input
                                type="text"
                                className="crm-input-field"
                                value={lead.mobile || ''}
                                readOnly
                                style={{
                                    opacity: 0.7,
                                    cursor: 'not-allowed',
                                    background: 'var(--bg-surface-2)',
                                }}
                            />
                        </div>
                        <div className="crm-input-group">
                            <label>Pitch type</label>
                            <input
                                type="text"
                                className="crm-input-field"
                                value={formatPitchLabel(callTypeCode)}
                                readOnly
                                style={{
                                    opacity: 0.7,
                                    cursor: 'not-allowed',
                                    background: 'var(--bg-surface-2)',
                                }}
                            />
                        </div>
                        <div className="crm-input-group">
                            <label>Call status</label>
                            <CustomSelect
                                value={callLogData.call_status_code || ''}
                                options={[
                                    { value: '', label: 'Select status' },
                                    ...availableStatuses.map((code) => ({
                                        value: code,
                                        label: formatPitchLabel(code),
                                    })),
                                ]}
                                onChange={(code) => {
                                    setCallLogData({
                                        ...callLogData,
                                        call_status_code: code,
                                        remarks:
                                            code === ITR_FIRST_PITCH_PAYMENT_PENDING_STATUS
                                                ? PAYMENT_PENDING_DEFAULT_REMARK
                                                : callLogData.remarks,
                                    });
                                }}
                                ariaLabel="Call status"
                                placeholder="Select status"
                                menuMaxHeight={240}
                            />
                        </div>
                        <div className="crm-input-group">
                            <label>Follow-up at</label>
                            <ModernDateTimePicker
                                value={callLogData.followup_at}
                                onChange={(val) => {
                                    setCallLogData({ ...callLogData, followup_at: val });
                                    if (errors.followup_at) setErrors({ ...errors, followup_at: null });
                                }}
                                min={minFollowup}
                                placeholder="Select follow-up date & time"
                                outputFormat="local"
                                placement="bottom"
                                className="modern-dt-picker--crm"
                                error={Boolean(errors.followup_at)}
                            />
                            {errors.followup_at && (
                                <span style={{ color: 'var(--danger)', fontSize: '11px', marginTop: '2px' }}>
                                    {errors.followup_at}
                                </span>
                            )}
                        </div>
                        <div className="crm-input-group">
                            <label>Remarks</label>
                            <CrmLeadRemarksField
                                entityType={entityType}
                                stage={lead?.stage}
                                callStatusCode={callLogData.call_status_code}
                                value={callLogData.remarks}
                                onChange={(remarks) => setCallLogData({ ...callLogData, remarks })}
                                error={errors.remarks}
                                onClearError={() => errors.remarks && setErrors({ ...errors, remarks: null })}
                                rows={5}
                            />
                        </div>
                    </div>
                </div>

                <div className="drawer-footer">
                    <button type="button" className="btn-drawer-secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </button>
                    <button
                        type="button"
                        className="btn-drawer-primary"
                        onClick={handleSubmit}
                        disabled={saving}
                    >
                        {saving ? 'Saving…' : 'Save call update'}
                    </button>
                </div>
            </div>
        </>,
        document.body
    );
}
