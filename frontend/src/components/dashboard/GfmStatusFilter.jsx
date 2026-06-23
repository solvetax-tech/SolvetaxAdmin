import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Filter } from 'lucide-react';
import { GFM_FILING_STATUS_FILTER_OPTIONS } from '../../utils/gstFilingStatusConstants';

const FLAG_OPTIONS = [
    { key: 'followup_scheduled', label: 'Follow-up scheduled', chipClass: 'followup' },
    { key: 'remaining_payment', label: 'Remaining payment', chipClass: 'remaining-payment' },
];

export default function GfmStatusFilter({ value = {}, onChange }) {
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);

    const selectedStatuses = useMemo(
        () => new Set((value.statuses || []).map((item) => String(item).toUpperCase())),
        [value.statuses],
    );

    const selectedCount = useMemo(() => {
        let count = 0;
        if (value.followup_scheduled) count += 1;
        if (value.remaining_payment) count += 1;
        count += selectedStatuses.size;
        return count;
    }, [value.followup_scheduled, value.remaining_payment, selectedStatuses]);

    const triggerLabel = selectedCount
        ? `${selectedCount} status${selectedCount === 1 ? '' : 'es'} selected`
        : 'All statuses';

    useEffect(() => {
        if (!open) return undefined;

        const handlePointerDown = (event) => {
            if (rootRef.current && !rootRef.current.contains(event.target)) {
                setOpen(false);
            }
        };

        document.addEventListener('mousedown', handlePointerDown);
        return () => document.removeEventListener('mousedown', handlePointerDown);
    }, [open]);

    const emitChange = (next) => {
        onChange?.({
            statuses: value.statuses || [],
            followup_scheduled: Boolean(value.followup_scheduled),
            remaining_payment: Boolean(value.remaining_payment),
            ...next,
        });
    };

    const toggleFlag = (key) => {
        emitChange({ [key]: !value?.[key] });
    };

    const toggleStatus = (statusValue) => {
        const normalized = String(statusValue).toUpperCase();
        const current = [...selectedStatuses];
        const next = current.includes(normalized)
            ? current.filter((item) => item !== normalized)
            : [...current, normalized];
        emitChange({ statuses: next });
    };

    const clearAll = () => {
        emitChange({
            statuses: [],
            followup_scheduled: false,
            remaining_payment: false,
        });
    };

    const renderOption = (key, label, chipClass, isSelected, onToggle) => (
        <button
            key={key}
            type="button"
            role="option"
            aria-selected={isSelected}
            className={`gfm-status-filter-option${isSelected ? ' is-selected' : ''}`}
            onClick={onToggle}
        >
            <span className="gfm-status-filter-check" aria-hidden="true">
                {isSelected ? '✓' : ''}
            </span>
            <span className={`gfm-swatch gfm-swatch--${chipClass}`} aria-hidden="true" />
            <span className="gfm-status-filter-option-label">{label}</span>
        </button>
    );

    return (
        <div className="gfm-status-filter" ref={rootRef}>
            <label className="gfm-status-filter-label">Filings status</label>
            <button
                type="button"
                className={`gfm-status-filter-trigger${open ? ' gfm-status-filter-trigger--open' : ''}${selectedCount ? ' has-selection' : ''}`}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
                aria-haspopup="listbox"
            >
                <Filter size={15} />
                <span className="gfm-status-filter-trigger-text">{triggerLabel}</span>
                <ChevronDown size={14} className={`gfm-status-filter-trigger-caret${open ? ' is-open' : ''}`} />
            </button>

            {open && (
                <div
                    className="gfm-status-filter-popover"
                    role="listbox"
                    aria-label="Filing status filters"
                    aria-multiselectable="true"
                >
                    <p className="gfm-status-filter-hint">
                        Select multiple · matches if any selected (OR) · phone/month use Apply
                    </p>
                    <div className="gfm-status-filter-list">
                        {FLAG_OPTIONS.map(({ key, label, chipClass }) => renderOption(
                            key,
                            label,
                            chipClass,
                            Boolean(value?.[key]),
                            () => toggleFlag(key),
                        ))}
                        {GFM_FILING_STATUS_FILTER_OPTIONS.map(({ value: statusValue, label, chipClass }) => renderOption(
                            statusValue,
                            label,
                            chipClass,
                            selectedStatuses.has(statusValue),
                            () => toggleStatus(statusValue),
                        ))}
                    </div>
                    {selectedCount > 0 && (
                        <div className="gfm-status-filter-popover-actions">
                            <button type="button" className="gfm-status-filter-clear" onClick={clearAll}>
                                Clear all
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
