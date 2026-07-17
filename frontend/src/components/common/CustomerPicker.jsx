import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { Search, X, Loader2, UserPlus } from 'lucide-react';
import { searchCustomers, normalizeMobile } from '../../utils/customerApi';
import './CustomerPicker.css';

const MIN_QUERY = 2;
const DEBOUNCE_MS = 300;

const EMPTY_NEW_CUSTOMER = { full_name: '', mobile: '', business_name: '' };

/**
 * Names a customer for a form: find an existing one, or draft a new one.
 *
 * Fully controlled, and the two modes are mutually exclusive by construction --
 * `customer` (an existing row) and `newCustomer` (a draft) are separate props
 * and picking one clears the other, which is what the API requires.
 *
 * Results render inline rather than in a floating menu: this field lives in a
 * scrolling drawer, where an absolutely-positioned menu would be clipped and
 * would need zoom-corrected anchoring to track the input (see CustomSelect).
 */
export default function CustomerPicker({
    customer = null,
    onSelect,
    newCustomer = null,
    onNewCustomerChange,
    fieldErrors = {},
    disabled = false,
    error = false,
    inputId = 'customer-search',
}) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchError, setSearchError] = useState(null);
    const [searched, setSearched] = useState(false);
    const [activeIndex, setActiveIndex] = useState(-1);
    const abortRef = useRef(null);
    const inputRef = useRef(null);

    const trimmed = query.trim();
    const drafting = newCustomer !== null;

    useEffect(() => {
        if (customer || drafting || trimmed.length < MIN_QUERY) {
            abortRef.current?.abort();
            setResults([]);
            setLoading(false);
            setSearchError(null);
            setSearched(false);
            setActiveIndex(-1);
            return undefined;
        }

        const timer = setTimeout(async () => {
            abortRef.current?.abort();
            const controller = new AbortController();
            abortRef.current = controller;

            setLoading(true);
            setSearchError(null);
            try {
                const rows = await searchCustomers(trimmed, { signal: controller.signal });
                if (controller.signal.aborted) return;
                setResults(rows);
                setActiveIndex(rows.length > 0 ? 0 : -1);
                setSearched(true);
            } catch (err) {
                if (axios.isCancel(err) || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
                    return;
                }
                const detail = err?.response?.data?.detail;
                setResults([]);
                setSearchError(
                    (typeof detail === 'string' && detail) || err?.message || 'Customer lookup failed.',
                );
                setSearched(true);
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        }, DEBOUNCE_MS);

        return () => clearTimeout(timer);
    }, [trimmed, customer, drafting]);

    useEffect(() => () => abortRef.current?.abort(), []);

    const choose = useCallback((row) => {
        onSelect?.(row);
        setQuery('');
        setResults([]);
        setSearched(false);
        setActiveIndex(-1);
    }, [onSelect]);

    const clearSelected = () => {
        onSelect?.(null);
        setQuery('');
        requestAnimationFrame(() => inputRef.current?.focus());
    };

    /** Carry the typed query across so it is not retyped: 10 digits is the phone,
     *  anything else is the name. */
    const startDraft = () => {
        const asMobile = normalizeMobile(trimmed);
        onNewCustomerChange?.({
            ...EMPTY_NEW_CUSTOMER,
            mobile: asMobile,
            full_name: asMobile ? '' : trimmed,
        });
    };

    const cancelDraft = () => {
        onNewCustomerChange?.(null);
        setQuery('');
    };

    const editDraft = (e) => {
        const { name, value } = e.target;
        onNewCustomerChange?.({ ...newCustomer, [name]: value });
    };

    const handleKeyDown = (e) => {
        if (results.length === 0) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveIndex((i) => (i + 1) % results.length);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveIndex((i) => (i <= 0 ? results.length - 1 : i - 1));
        } else if (e.key === 'Enter') {
            // The field sits inside a <form>; Enter picks a row, never submits.
            e.preventDefault();
            if (activeIndex >= 0) choose(results[activeIndex]);
        } else if (e.key === 'Escape') {
            setResults([]);
            setActiveIndex(-1);
        }
    };

    // 1. An existing customer is attached.
    if (customer) {
        return (
            <div className="cust-pick-card">
                <div className="cust-pick-card-head">
                    <div>
                        <span className="cust-pick-card-name">{customer.full_name || 'Unnamed customer'}</span>
                        <span className="cust-pick-card-id">#{customer.customer_id}</span>
                    </div>
                    <button type="button" className="cust-pick-ghost-btn" onClick={clearSelected} disabled={disabled}>
                        <X size={12} /> Change
                    </button>
                </div>
                <dl className="cust-pick-facts">
                    <dt>Phone</dt>
                    <dd>{customer.mobile || '—'}</dd>
                    <dt>Business</dt>
                    <dd>{customer.business_name || '—'}</dd>
                    <dt>Email</dt>
                    <dd>{customer.email || '—'}</dd>
                </dl>
            </div>
        );
    }

    // 2. Drafting a new customer, created by the same request as the service.
    if (drafting) {
        return (
            <div className="cust-pick-card">
                <div className="cust-pick-card-head">
                    <span className="cust-pick-card-name">New customer</span>
                    <button type="button" className="cust-pick-ghost-btn" onClick={cancelDraft} disabled={disabled}>
                        <X size={12} /> Cancel
                    </button>
                </div>

                <div className="cust-pick-draft">
                    <div className="cust-pick-draft-row">
                        <div className="filter-group-v4">
                            <label htmlFor={`${inputId}-name`}>
                                Full Name <span style={{ color: 'var(--danger)' }}>*</span>
                            </label>
                            <input
                                id={`${inputId}-name`}
                                type="text"
                                name="full_name"
                                value={newCustomer.full_name}
                                onChange={editDraft}
                                disabled={disabled}
                                placeholder="Customer name"
                                className={fieldErrors.full_name ? 'has-error' : ''}
                            />
                            {fieldErrors.full_name && <span className="field-error-msg">{fieldErrors.full_name}</span>}
                        </div>
                        <div className="filter-group-v4">
                            <label htmlFor={`${inputId}-mobile`}>
                                Phone <span style={{ color: 'var(--danger)' }}>*</span>
                            </label>
                            <input
                                id={`${inputId}-mobile`}
                                type="tel"
                                inputMode="numeric"
                                name="mobile"
                                value={newCustomer.mobile}
                                onChange={editDraft}
                                disabled={disabled}
                                placeholder="10-digit mobile"
                                className={fieldErrors.mobile ? 'has-error' : ''}
                            />
                            {fieldErrors.mobile && <span className="field-error-msg">{fieldErrors.mobile}</span>}
                        </div>
                    </div>
                    <div className="filter-group-v4">
                        <label htmlFor={`${inputId}-business`}>Business Name</label>
                        <input
                            id={`${inputId}-business`}
                            type="text"
                            name="business_name"
                            value={newCustomer.business_name}
                            onChange={editDraft}
                            disabled={disabled}
                            placeholder="Optional"
                            className={fieldErrors.business_name ? 'has-error' : ''}
                        />
                        {fieldErrors.business_name && (
                            <span className="field-error-msg">{fieldErrors.business_name}</span>
                        )}
                    </div>
                    <p className="cust-pick-hint">
                        Created together with the service — if the service fails, the customer is not saved.
                    </p>
                </div>
            </div>
        );
    }

    // 3. Searching.
    const showEmpty = searched && !loading && !searchError && results.length === 0;

    return (
        <div className="cust-pick">
            <div className={`cust-pick-input ${error ? 'has-error' : ''}`}>
                <Search size={14} className="cust-pick-input-icon" />
                <input
                    id={inputId}
                    ref={inputRef}
                    type="text"
                    role="combobox"
                    autoComplete="off"
                    aria-expanded={results.length > 0}
                    aria-controls={`${inputId}-results`}
                    aria-label="Search customers by name, phone, or business name"
                    placeholder="Search by name, phone, or business…"
                    value={query}
                    disabled={disabled}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={handleKeyDown}
                />
                {loading && <Loader2 size={14} className="cust-pick-spinner" />}
            </div>

            {results.length > 0 && (
                <ul className="cust-pick-results" id={`${inputId}-results`} role="listbox">
                    {results.map((row, i) => (
                        <li key={row.customer_id} role="option" aria-selected={i === activeIndex}>
                            <button
                                type="button"
                                className={`cust-pick-result ${i === activeIndex ? 'is-active' : ''}`}
                                onMouseEnter={() => setActiveIndex(i)}
                                onClick={() => choose(row)}
                            >
                                <span className="cust-pick-result-top">
                                    <span className="cust-pick-result-name">{row.full_name || 'Unnamed customer'}</span>
                                    <span className="cust-pick-result-phone">{row.mobile || '—'}</span>
                                </span>
                                <span className="cust-pick-result-sub">
                                    {row.business_name || 'No business name'} · #{row.customer_id}
                                </span>
                            </button>
                        </li>
                    ))}
                </ul>
            )}

            {searchError && <span className="field-error-msg">{searchError}</span>}

            {showEmpty && (
                <p className="cust-pick-hint">
                    No active customer matches “{trimmed}”. Phone must be the full 10 digits.
                </p>
            )}

            <button type="button" className="cust-pick-new-btn" onClick={startDraft} disabled={disabled}>
                <UserPlus size={13} /> New customer
            </button>
        </div>
    );
}
