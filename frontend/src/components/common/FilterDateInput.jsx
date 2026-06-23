import React, { useRef } from 'react';
import { Calendar } from 'lucide-react';
import './Filters.css';

export function openFilterDatePicker(inputEl) {
    if (!inputEl) return;
    if (typeof inputEl.showPicker === 'function') {
        inputEl.showPicker().catch(() => inputEl.focus());
    } else {
        inputEl.focus();
    }
}

/**
 * Date-only filter input with a visible calendar button (dark-mode friendly).
 */
export default function FilterDateInput({
    name,
    value,
    onChange,
    className = '',
    inputClassName = '',
    compact = false,
    ariaLabel,
    ...rest
}) {
    const inputRef = useRef(null);

    return (
        <div
            className={[
                'filter-date-input-wrap',
                compact ? 'filter-date-input-wrap--compact' : '',
                className,
            ].filter(Boolean).join(' ')}
        >
            <input
                ref={inputRef}
                type="date"
                name={name}
                value={value || ''}
                onChange={onChange}
                className={['filter-date-input', inputClassName].filter(Boolean).join(' ')}
                aria-label={ariaLabel}
                {...rest}
            />
            <button
                type="button"
                className="filter-date-picker-btn"
                aria-label={ariaLabel ? `Open date picker for ${ariaLabel}` : 'Open date picker'}
                onClick={() => openFilterDatePicker(inputRef.current)}
            >
                <Calendar size={compact ? 15 : 18} strokeWidth={2} />
            </button>
        </div>
    );
}
