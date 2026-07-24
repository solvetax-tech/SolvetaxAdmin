import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUpDown, Check } from 'lucide-react';
import Button from '../ui/Button';
import './CrmLeadSortControl.css';

/**
 * Shared CRM sort control: a Filters-matched button that opens a dropdown of
 * curated sort options. Emits onChange(sortBy, sortDir) and mirrors the fixed
 * backend contract on GET /api/v1/crm/leads/filter (sort_by + sort_dir).
 */

// Curated option list (label -> { by, dir }). Order = render order.
const BASE_OPTIONS = [
    { label: 'Newest first', by: 'id', dir: 'desc' },
    { label: 'Oldest first', by: 'id', dir: 'asc' },
    { label: 'Name A - Z', by: 'full_name', dir: 'asc' },
    { label: 'Name Z - A', by: 'full_name', dir: 'desc' },
    { label: 'Mobile ascending', by: 'mobile', dir: 'asc' },
    { label: 'Mobile descending', by: 'mobile', dir: 'desc' },
    { label: 'Stage A - Z', by: 'stage', dir: 'asc' },
    { label: 'Stage Z - A', by: 'stage', dir: 'desc' },
    { label: 'Most call attempts', by: 'call_attempts', dir: 'desc' },
    { label: 'Fewest call attempts', by: 'call_attempts', dir: 'asc' },
    { label: 'Most calls connected', by: 'call_connected', dir: 'desc' },
    { label: 'Fewest calls connected', by: 'call_connected', dir: 'asc' },
    { label: 'Follow-up soonest', by: 'followup_at', dir: 'asc' },
    { label: 'Follow-up latest', by: 'followup_at', dir: 'desc' },
    { label: 'Recently updated', by: 'updated_at', dir: 'desc' },
    { label: 'Recently created', by: 'created_at', dir: 'desc' },
];

// Income-tax CRM adds assessment-year sorts.
const INCOME_TAX_OPTIONS = [
    { label: 'Assessment year - newest', by: 'ay', dir: 'desc' },
    { label: 'Assessment year - oldest', by: 'ay', dir: 'asc' },
];

export default function CrmLeadSortControl({ sortBy, sortDir, onChange, isIncomeTaxCrm = false }) {
    const [open, setOpen] = useState(false);
    const wrapRef = useRef(null);

    const options = isIncomeTaxCrm ? [...BASE_OPTIONS, ...INCOME_TAX_OPTIONS] : BASE_OPTIONS;

    const activeOption = options.find((o) => o.by === sortBy && o.dir === sortDir);
    const currentLabel = activeOption ? activeOption.label : 'Sort';

    const close = useCallback(() => setOpen(false), []);

    useEffect(() => {
        if (!open) return undefined;
        const handlePointer = (event) => {
            if (wrapRef.current && !wrapRef.current.contains(event.target)) {
                close();
            }
        };
        const handleKey = (event) => {
            if (event.key === 'Escape') close();
        };
        document.addEventListener('mousedown', handlePointer);
        document.addEventListener('keydown', handleKey);
        return () => {
            document.removeEventListener('mousedown', handlePointer);
            document.removeEventListener('keydown', handleKey);
        };
    }, [open, close]);

    const handleSelect = (option) => {
        onChange(option.by, option.dir);
        close();
    };

    return (
        <div className="crm-lead-sort" ref={wrapRef}>
            <Button
                variant="secondary"
                size="sm"
                icon={<ArrowUpDown size={13} />}
                onClick={() => setOpen((prev) => !prev)}
                aria-haspopup="listbox"
                aria-expanded={open}
                className="crm-lead-sort-trigger"
            >
                {currentLabel}
            </Button>
            {open && (
                <div className="crm-lead-sort-menu" role="listbox" aria-label="Sort leads by">
                    {options.map((option) => {
                        const isActive = option === activeOption;
                        return (
                            <button
                                key={`${option.by}-${option.dir}`}
                                type="button"
                                role="option"
                                aria-selected={isActive}
                                className={`crm-lead-sort-option${isActive ? ' is-active' : ''}`}
                                onClick={() => handleSelect(option)}
                            >
                                <span className="crm-lead-sort-option-label">{option.label}</span>
                                {isActive && <Check size={14} className="crm-lead-sort-option-check" />}
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
