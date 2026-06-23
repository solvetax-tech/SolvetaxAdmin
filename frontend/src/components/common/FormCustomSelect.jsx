import React from 'react';
import CustomSelect from './CustomSelect';
import { syntheticSelectEvent } from './selectOptionUtils';

/**
 * Drop-in replacement for native &lt;select className="modal-input-v4"&gt; in main system forms.
 * Uses the same dark CRM dropdown styling as CustomSelect.
 */
export default function FormCustomSelect({
    name,
    value,
    onChange,
    options = [],
    placeholder = 'Select',
    disabled = false,
    error = false,
    className = '',
    ariaLabel,
    menuMaxHeight = 240,
    portal = true,
}) {
    const handleChange = (val) => {
        if (typeof onChange === 'function') {
            onChange(syntheticSelectEvent(name, val));
        }
    };

    return (
        <CustomSelect
            className={`custom-select--form ${className}`.trim()}
            value={value ?? ''}
            options={options}
            onChange={handleChange}
            disabled={disabled}
            error={error}
            placeholder={placeholder}
            ariaLabel={ariaLabel || name}
            menuMaxHeight={menuMaxHeight}
            portal={portal}
        />
    );
}
