import React, { useState, useRef, useEffect, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';
import './CustomSelect.css';

/**
 * Dark-theme dropdown (replaces native &lt;select&gt; — fixes invisible/broken options on Windows).
 */
export default function CustomSelect({
    value,
    options = [],
    onChange,
    disabled = false,
    error = false,
    ariaLabel = 'Select option',
    placeholder = 'Select',
    menuMaxHeight = 220,
    className = '',
    portal = false,
}) {
    const [open, setOpen] = useState(false);
    const [menuStyle, setMenuStyle] = useState(null);
    const ref = useRef(null);
    const menuRef = useRef(null);

    const updateMenuPosition = () => {
        const trigger = ref.current?.querySelector('.custom-select-trigger');
        if (!trigger) return;
        const rect = trigger.getBoundingClientRect();
        setMenuStyle({
            position: 'fixed',
            top: rect.bottom + 4,
            left: rect.left,
            width: rect.width,
            maxHeight: menuMaxHeight,
            zIndex: 25000,
        });
    };

    useLayoutEffect(() => {
        if (!open || !portal) {
            setMenuStyle(null);
            return undefined;
        }
        updateMenuPosition();
        const onReflow = () => requestAnimationFrame(updateMenuPosition);
        window.addEventListener('resize', onReflow);
        window.addEventListener('scroll', onReflow, true);
        return () => {
            window.removeEventListener('resize', onReflow);
            window.removeEventListener('scroll', onReflow, true);
        };
    }, [open, portal, menuMaxHeight]);

    useEffect(() => {
        if (!open) return undefined;
        const close = (event) => {
            const inRoot = ref.current?.contains(event.target);
            const inMenu = menuRef.current?.contains(event.target);
            if (!inRoot && !inMenu) {
                setOpen(false);
            }
        };
        document.addEventListener('mousedown', close);
        return () => document.removeEventListener('mousedown', close);
    }, [open]);

    const selected = options.find((o) => String(o.value) === String(value));
    const hasValue = value !== '' && value !== null && value !== undefined;
    const displayLabel = selected?.label ?? placeholder;

    const rootClass = [
        'custom-select',
        open ? 'is-open' : '',
        disabled ? 'is-disabled' : '',
        error ? 'custom-select--error' : '',
        !hasValue ? 'custom-select--placeholder' : '',
        className,
    ].filter(Boolean).join(' ');

    const menu = open && !disabled ? (
        <ul
            ref={menuRef}
            className={`custom-select-menu ${portal ? 'custom-select-menu--portal' : ''}`}
            style={portal ? menuStyle || { maxHeight: menuMaxHeight } : { maxHeight: menuMaxHeight }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
        >
            {options.map((opt) => (
                <li key={String(opt.value)}>
                    <button
                        type="button"
                        className={`custom-select-option ${String(opt.value) === String(value) ? 'selected' : ''}`}
                        onClick={(e) => {
                            e.stopPropagation();
                            onChange(opt.value);
                            setOpen(false);
                        }}
                    >
                        {opt.label}
                    </button>
                </li>
            ))}
        </ul>
    ) : null;

    return (
        <div className={rootClass} ref={ref}>
            <button
                type="button"
                className="custom-select-trigger"
                aria-label={ariaLabel}
                aria-expanded={open}
                disabled={disabled}
                onClick={(e) => {
                    e.stopPropagation();
                    if (!disabled) setOpen((prev) => !prev);
                }}
            >
                <span className="custom-select-label">{displayLabel}</span>
                <ChevronDown size={14} className="custom-select-chevron" />
            </button>
            {portal && typeof document !== 'undefined' && menu
                ? createPortal(menu, document.body)
                : menu}
        </div>
    );
}
