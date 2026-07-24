import React, { useState, useRef, useEffect, useMemo, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Search } from 'lucide-react';
import { getAnchorRect } from '../../utils/zoom';
import './CustomSelect.css';

/** Show the type-to-filter box once a list is long enough to be worth searching. */
const SEARCH_THRESHOLD = 6;

/**
 * Dark-theme dropdown (replaces native <select> — fixes invisible/broken options on Windows).
 * Long lists get a type-to-filter search box on top; click-to-select still works exactly as before.
 * Pass `searchable={true|false}` to force the search box on/off regardless of list length.
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
    searchable,
    searchPlaceholder = 'Search…',
}) {
    const [open, setOpen] = useState(false);
    const [menuStyle, setMenuStyle] = useState(null);
    const [query, setQuery] = useState('');
    const [activeIndex, setActiveIndex] = useState(-1);
    const ref = useRef(null);
    const menuRef = useRef(null);
    const searchRef = useRef(null);

    const showSearch = (searchable === undefined ? options.length >= SEARCH_THRESHOLD : searchable) && !disabled;

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return options;
        return options.filter((o) => String(o.label ?? '').toLowerCase().includes(q));
    }, [options, query]);

    const updateMenuPosition = () => {
        const trigger = ref.current?.querySelector('.custom-select-trigger');
        if (!trigger) return;
        // Zoom-corrected: the menu is portalled to <body>, so a raw viewport rect
        // would be re-scaled by the app's html zoom and miss the field.
        const rect = getAnchorRect(trigger);
        setMenuStyle({
            position: 'fixed',
            top: rect.bottom + 4,
            left: rect.left,
            width: rect.width,
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

    // Reset the filter and focus the search box each time the menu opens.
    useEffect(() => {
        if (!open) return undefined;
        setQuery('');
        setActiveIndex(-1);
        if (!showSearch) return undefined;
        const id = requestAnimationFrame(() => searchRef.current?.focus());
        return () => cancelAnimationFrame(id);
    }, [open, showSearch]);

    // Keep the keyboard-highlighted option scrolled into view.
    useEffect(() => {
        if (!open || activeIndex < 0) return;
        menuRef.current?.querySelector('.custom-select-option.active')?.scrollIntoView({ block: 'nearest' });
    }, [activeIndex, open]);

    const commitOption = (opt) => {
        if (!opt) return;
        onChange(opt.value);
        setOpen(false);
    };

    const onSearchKeyDown = (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveIndex((i) => Math.min(filtered.length - 1, i + 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveIndex((i) => Math.max(0, i - 1));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            commitOption(filtered[activeIndex >= 0 ? activeIndex : 0]);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            setOpen(false);
        }
    };

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
        <div
            ref={menuRef}
            className={`custom-select-menu ${portal ? 'custom-select-menu--portal' : ''}`}
            style={portal ? (menuStyle || undefined) : undefined}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
        >
            {showSearch && (
                <div className="custom-select-search">
                    <Search size={14} className="custom-select-search-icon" />
                    <input
                        ref={searchRef}
                        type="text"
                        className="custom-select-search-input"
                        value={query}
                        placeholder={searchPlaceholder}
                        onChange={(e) => { setQuery(e.target.value); setActiveIndex(-1); }}
                        onKeyDown={onSearchKeyDown}
                        aria-label="Search options"
                    />
                </div>
            )}
            <ul className="custom-select-list" role="listbox" style={{ maxHeight: menuMaxHeight }}>
                {filtered.length === 0 ? (
                    <li className="custom-select-empty">No matches</li>
                ) : filtered.map((opt, idx) => (
                    <li key={String(opt.value)}>
                        <button
                            type="button"
                            role="option"
                            aria-selected={String(opt.value) === String(value)}
                            className={`custom-select-option ${String(opt.value) === String(value) ? 'selected' : ''} ${idx === activeIndex ? 'active' : ''}`}
                            onMouseEnter={() => setActiveIndex(idx)}
                            onClick={(e) => {
                                e.stopPropagation();
                                commitOption(opt);
                            }}
                        >
                            {opt.label}
                        </button>
                    </li>
                ))}
            </ul>
        </div>
    ) : null;

    return (
        <div className={rootClass} ref={ref}>
            <button
                type="button"
                className="custom-select-trigger"
                aria-label={ariaLabel}
                aria-haspopup="listbox"
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
