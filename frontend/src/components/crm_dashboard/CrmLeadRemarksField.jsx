import React, { useEffect, useState } from 'react';
import CustomSelect from '../common/CustomSelect';
import {
    CRM_REMARKS_OTHER,
    ITR_PRESET_REMARK,
    isPresetItrRemark,
    PAYMENT_PENDING_DEFAULT_REMARK,
    usesItrRemarksDropdown,
    usesPaymentPendingPlainRemarks,
} from './crmLeadRemarksConfig';

export default function CrmLeadRemarksField({
    entityType,
    stage,
    callStatusCode,
    value,
    onChange,
    error,
    onClearError,
    rows = 5,
}) {
    const paymentPendingPlain = usesPaymentPendingPlainRemarks(callStatusCode);
    const useDropdown = usesItrRemarksDropdown(entityType, stage, callStatusCode);
    const [otherMode, setOtherMode] = useState(() => {
        if (!useDropdown) return false;
        return Boolean(value) && !isPresetItrRemark(value);
    });

    useEffect(() => {
        if (paymentPendingPlain && value !== PAYMENT_PENDING_DEFAULT_REMARK) {
            onChange(PAYMENT_PENDING_DEFAULT_REMARK);
        }
    }, [paymentPendingPlain, callStatusCode]);

    useEffect(() => {
        if (!useDropdown) return;
        if (isPresetItrRemark(value)) {
            setOtherMode(false);
        } else if (value) {
            setOtherMode(true);
        }
    }, [value, useDropdown]);

    const selectValue = isPresetItrRemark(value)
        ? ITR_PRESET_REMARK
        : otherMode
            ? CRM_REMARKS_OTHER
            : '';

    const showCustomInput = useDropdown && otherMode;

    const handleChange = (next) => {
        onChange(next);
        if (onClearError) onClearError();
    };

    if (paymentPendingPlain || !useDropdown) {
        return (
            <>
                <textarea
                    className={`crm-input-field ${error ? 'error' : ''}`}
                    rows={rows}
                    placeholder="Enter remarks..."
                    value={value}
                    onChange={(e) => handleChange(e.target.value)}
                />
                {error && (
                    <span style={{ color: 'var(--danger)', fontSize: '11px', marginTop: '4px' }}>{error}</span>
                )}
            </>
        );
    }

    const remarkOptions = [
        { value: '', label: 'Select remark' },
        { value: ITR_PRESET_REMARK, label: ITR_PRESET_REMARK },
        { value: CRM_REMARKS_OTHER, label: 'Other' },
    ];

    const handleRemarkSelect = (next) => {
        if (next === CRM_REMARKS_OTHER) {
            setOtherMode(true);
            handleChange('');
        } else if (next === ITR_PRESET_REMARK) {
            setOtherMode(false);
            handleChange(ITR_PRESET_REMARK);
        } else {
            setOtherMode(false);
            handleChange('');
        }
    };

    return (
        <div className="crm-remarks-field">
            <CustomSelect
                value={selectValue}
                options={remarkOptions}
                onChange={handleRemarkSelect}
                error={Boolean(error && !value?.trim())}
                ariaLabel="Remarks"
                placeholder="Select remark"
                menuMaxHeight={200}
            />
            {showCustomInput && (
                <textarea
                    className={`crm-input-field ${error ? 'error' : ''}`}
                    rows={rows}
                    placeholder="Enter your remark..."
                    value={isPresetItrRemark(value) ? '' : (value || '')}
                    onChange={(e) => handleChange(e.target.value)}
                />
            )}
            {error && (
                <span className="crm-remarks-field-error">{error}</span>
            )}
        </div>
    );
}
