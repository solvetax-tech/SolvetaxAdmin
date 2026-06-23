import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Calendar, ChevronDown, X } from 'lucide-react';
import {
    formatGfmPeriodLabel,
    generateGfmMonthOptions,
    normalizeGfmPeriodList,
} from './gfmMonthUtils';

const MONTH_OPTIONS = generateGfmMonthOptions(24);
const DEFAULT_MONTH_COUNT = 6;

export default function GfmMonthFilter({ value = [], onChange }) {
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);
    const selectedPeriods = useMemo(() => normalizeGfmPeriodList(value), [value]);

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

    const togglePeriod = (period) => {
        const next = selectedPeriods.includes(period)
            ? selectedPeriods.filter((item) => item !== period)
            : normalizeGfmPeriodList([...selectedPeriods, period]);
        onChange(next);
    };

    const triggerLabel = selectedPeriods.length
        ? `${selectedPeriods.length} month${selectedPeriods.length === 1 ? '' : 's'} selected`
        : `Last ${DEFAULT_MONTH_COUNT} months (default)`;

    return (
        <div className="gfm-month-filter" ref={rootRef}>
            <label className="gfm-month-filter-label">Months</label>
            <button
                type="button"
                className={`gfm-month-filter-trigger${open ? ' gfm-month-filter-trigger--open' : ''}`}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
                aria-haspopup="listbox"
            >
                <Calendar size={15} />
                <span className="gfm-month-filter-trigger-text">{triggerLabel}</span>
                <ChevronDown size={14} className={`gfm-month-filter-trigger-caret${open ? ' is-open' : ''}`} />
            </button>

            {open && (
                <div className="gfm-month-filter-popover" role="listbox" aria-label="Select filing months" aria-multiselectable="true">
                    <p className="gfm-month-filter-hint">
                        Select one or more months · leave empty for last {DEFAULT_MONTH_COUNT} months
                    </p>
                    <div className="gfm-month-filter-list">
                        {MONTH_OPTIONS.map((period) => {
                            const isSelected = selectedPeriods.includes(period);
                            return (
                                <button
                                    key={period}
                                    type="button"
                                    role="option"
                                    aria-selected={isSelected}
                                    className={`gfm-month-filter-option${isSelected ? ' is-selected' : ''}`}
                                    onClick={() => togglePeriod(period)}
                                >
                                    <span className="gfm-month-filter-check" aria-hidden="true">
                                        {isSelected ? '✓' : ''}
                                    </span>
                                    <span>{formatGfmPeriodLabel(period)}</span>
                                    <span className="gfm-month-filter-option-meta">{period}</span>
                                </button>
                            );
                        })}
                    </div>
                    <div className="gfm-month-filter-popover-actions">
                        <button
                            type="button"
                            className="gfm-month-filter-quick"
                            onClick={() => onChange(MONTH_OPTIONS.slice(-DEFAULT_MONTH_COUNT))}
                        >
                            Last {DEFAULT_MONTH_COUNT}
                        </button>
                        <button
                            type="button"
                            className="gfm-month-filter-quick"
                            onClick={() => onChange([...MONTH_OPTIONS])}
                        >
                            All
                        </button>
                        <button
                            type="button"
                            className="gfm-month-filter-quick"
                            onClick={() => onChange([])}
                            disabled={!selectedPeriods.length}
                        >
                            Clear
                        </button>
                    </div>
                </div>
            )}

            {selectedPeriods.length > 0 && (
                <div className="gfm-month-filter-chips" aria-label="Selected months">
                    {selectedPeriods.map((period) => (
                        <span key={period} className="gfm-month-filter-chip">
                            {formatGfmPeriodLabel(period)}
                            <button
                                type="button"
                                className="gfm-month-filter-chip-remove"
                                onClick={() => togglePeriod(period)}
                                aria-label={`Remove ${period}`}
                            >
                                <X size={12} />
                            </button>
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}

export { normalizeGfmPeriodList };
