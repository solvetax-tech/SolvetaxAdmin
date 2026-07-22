import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, FileText } from 'lucide-react';
import { GST_RETURN_FORM_OPTIONS } from '../../utils/gstFilingStatusConstants';

/**
 * Return-form filter for the GST filing matrix.
 *
 * Unlike the status filter, a selection here NARROWS which forms the other
 * matrix filters inspect (AND) rather than widening the match (OR) — picking
 * GSTR-1 plus "Missed" means GSTR-1 that is missed.
 */
export default function GfmFormFilter({ value = [], onChange }) {
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);

    const selectedForms = useMemo(
        () => new Set((value || []).map((item) => String(item).toUpperCase())),
        [value],
    );

    const triggerLabel = selectedForms.size
        ? `${selectedForms.size} form${selectedForms.size === 1 ? '' : 's'} selected`
        : 'All forms';

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

    const toggleForm = (formValue) => {
        const normalized = String(formValue).toUpperCase();
        const current = [...selectedForms];
        onChange?.(
            current.includes(normalized)
                ? current.filter((item) => item !== normalized)
                : [...current, normalized],
        );
    };

    return (
        <div className="gfm-status-filter" ref={rootRef}>
            <label className="gfm-status-filter-label">Return forms</label>
            <button
                type="button"
                className={`gfm-status-filter-trigger${open ? ' gfm-status-filter-trigger--open' : ''}${selectedForms.size ? ' has-selection' : ''}`}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
                aria-haspopup="listbox"
            >
                <FileText size={15} />
                <span className="gfm-status-filter-trigger-text">{triggerLabel}</span>
                <ChevronDown size={14} className={`gfm-status-filter-trigger-caret${open ? ' is-open' : ''}`} />
            </button>

            {open && (
                <div
                    className="gfm-status-filter-popover"
                    role="listbox"
                    aria-label="Return form filters"
                    aria-multiselectable="true"
                >
                    <p className="gfm-status-filter-hint">
                        Select multiple · narrows the status filter to these forms
                    </p>
                    <div className="gfm-status-filter-list">
                        {GST_RETURN_FORM_OPTIONS.map(({ value: formValue, label }) => {
                            const isSelected = selectedForms.has(formValue);
                            return (
                                <button
                                    key={formValue}
                                    type="button"
                                    role="option"
                                    aria-selected={isSelected}
                                    className={`gfm-status-filter-option${isSelected ? ' is-selected' : ''}`}
                                    onClick={() => toggleForm(formValue)}
                                >
                                    <span className="gfm-status-filter-check" aria-hidden="true">
                                        {isSelected ? '✓' : ''}
                                    </span>
                                    <span className="gfm-status-filter-option-label">{label}</span>
                                </button>
                            );
                        })}
                    </div>
                    {selectedForms.size > 0 && (
                        <div className="gfm-status-filter-popover-actions">
                            <button
                                type="button"
                                className="gfm-status-filter-clear"
                                onClick={() => onChange?.([])}
                            >
                                Clear all
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
