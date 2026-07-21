import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../utils/api';
import {
    appendReturnStatusRulesToParams,
    getGstStatusStyleKey,
} from '../../utils/gstFilingStatusConstants';
import {
    appendDueDateRulesToParams,
} from '../../utils/gstFilterRulesConstants';
import Pagination from '../common/Pagination';
import { useNavigate } from 'react-router-dom';
import { Calendar, History, RotateCcw, X, CreditCard } from 'lucide-react';
import './GSTFilingsReturns.css';

const RETURN_FIELD_MAP = {
    gstr1: {
        statusKeys: ['gstr1_status'],
        dueDateKeys: ['gstr1_due_date']
    },
    gstr3b: {
        statusKeys: ['gstr3b_status'],
        dueDateKeys: ['gstr3b_due_date']
    },
    cmp08: {
        statusKeys: ['cmp08_status'],
        dueDateKeys: ['cmp08_due_date']
    },
    gstr4: {
        statusKeys: ['gstr4_status'],
        dueDateKeys: ['gstr4_due_date']
    },
    gstr9: {
        statusKeys: ['gstr9_status'],
        dueDateKeys: ['gstr9_due_date']
    },
    gstr9c: {
        statusKeys: ['gstr9c_status'],
        dueDateKeys: ['gstr9c_due_date']
    }
};

const BASE_MERGE_KEYS = [
    'gst_filing_id',
    'gst_registration_id',
    'business_name',
    'business_type',
    'taxpayer_type',
    'gstin',
    'is_auto_generated',
    'next_auto_generate_at'
];



const ReturnsTableSkeleton = ({ rows = 8 }) => (
    <>
        {[...Array(rows)].map((_, rowIndex) => (
            <div key={`returns-skeleton-${rowIndex}`} className="ledger-row ledger-grid-template ledger-skeleton-row">
                {[...Array(13)].map((__, columnIndex) => (
                    <div 
                        key={`returns-skeleton-cell-${columnIndex}`} 
                        className={`ledger-cell ${
                            columnIndex === 0 ? 'ledger-sticky-id ledger-sticky-col-1' :
                            columnIndex === 1 ? 'ledger-sticky-id ledger-sticky-col-2' :
                            columnIndex === 12 ? 'gst-sticky-actions' : ''
                        }`}
                    >
                        <div 
                            className="ledger-skeleton-bar" 
                            style={{ 
                                width: (columnIndex === 0 || columnIndex === 1) ? '30px' : '80%' 
                            }} 
                        />
                    </div>
                ))}
            </div>
        ))}
    </>
);

const getStatusStyle = (status) => getGstStatusStyleKey(status);

const formatFinancialYear = (period) => {
    if (!period) return period;
    
    // 🔥 Fix: Only skip if it's a full ISO date (e.g. 2026-04-11)
    // Month-Year formats like MAR-2026 or 2026-03 should be processed.
    const isFullIsoDate = /^\d{4}-\d{2}-\d{2}/.test(period);
    if (isFullIsoDate) return period;
    
    let year, month;
    if (period.includes('-')) {
        const parts = period.split('-');
        if (parts[0].length === 4) {
            year = parseInt(parts[0]);
            month = parseInt(parts[1]);
        } else {
            // Handle MAR-2026
            const monthStr = parts[0].toUpperCase();
            const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
            month = months.indexOf(monthStr) + 1;
            year = parseInt(parts[1]);
            
            // If month logic fails, try new Date
            if (month === 0) {
                month = new Date(`${parts[0]} 1, 2000`).getMonth() + 1;
            }
        }
    } else {
        return period;
    }

    if (!year || !month) return period;

    // In India, Financial Year starts in April. 
    // If month is Jan-Mar (1-3), the FY starts in the previous year.
    const fyStart = month <= 3 ? year - 1 : year;
    const fyEnd = (fyStart + 1).toString().slice(-2);
    return `${fyStart}-${fyEnd}`;
};

/**
 * 🔥 Compute the true filing period from a detail row's actual due dates or auto-run dates.
 * 
 * Logic for QUARTERLY taxpayers:
 *   IFF/GSTR-1 due dates are shifted 1 month after the period.
 *   - Due in Feb, Mar, Apr -> Q1 (Jan-Mar)
 *   - Due in May, Jun, Jul -> Q2 (Apr-Jun)
 *   - Due in Aug, Sep, Oct -> Q3 (Jul-Sep)
 *   - Due in Nov, Dec, Jan -> Q4 (Oct-Dec)
 */
const computeEffectivePeriod = (row, freqHint = '') => {
    const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
    
    // Detect frequency with high resilience
    let freq = (freqHint || row?.filing_frequency || row?.filing_preference || '').toUpperCase();
    
    // If freq is missing, try to guess from the parent filing_period
    const parentPeriod = (row?.filing_period || '').toUpperCase();
    if (!freq && parentPeriod) {
        if (parentPeriod.startsWith('Q')) freq = 'QUARTERLY';
        else if (parentPeriod.includes('-') && parentPeriod.length >= 7) freq = 'YEARLY';
        else if (parentPeriod.includes('-')) freq = 'MONTHLY';
    }

    // Guess frequency from present due date fields if still missing
    if (!freq) {
        if (row?.gstr9_due_date || row?.gstr4_due_date) freq = 'YEARLY';
        else if (row?.cmp08_due_date) freq = 'QUARTERLY';
        else if (row?.gstr1_due_date || row?.gstr3b_due_date) freq = 'MONTHLY';
    }

    // Pick the most reliable date signal
    const rawDate = row?.gstr1_due_date || row?.gstr3b_due_date || row?.cmp08_due_date || row?.gstr9_due_date || row?.gstr4_due_date || row?.next_auto_generate_at;
    if (!rawDate) return null;

    const date = new Date(rawDate);
    if (isNaN(date.getTime())) return null;

    const month = date.getMonth(); // 0-indexed
    const year = date.getFullYear();

    // ── YEARLY ────────────────────────────────────────────────
    if (freq === 'YEARLY' || row?.gstr9_due_date || row?.gstr4_due_date) {
        // e.g. Due Oct-Dec 2026 -> FY 2025-26
        const fyStart = month <= 2 ? year - 2 : year - 1; 
        return `${fyStart}-${String(fyStart + 1).slice(-2)}`;
    }

    // ── QUARTERLY ─────────────────────────────────────────────
    if (freq === 'QUARTERLY') {
        // Mapping (0-indexed):
        //   q = 1 (Jan-Mar): Due in Feb(1), Mar(2), Apr(3)
        //   q = 2 (Apr-Jun): Due in May(4), Jun(5), Jul(6)
        //   q = 3 (Jul-Sep): Due in Aug(7), Sep(8), Oct(9)
        //   q = 4 (Oct-Dec): Due in Nov(10), Dec(11), Jan(0)
        let q;
        if (month >= 1 && month <= 3) q = 1;
        else if (month >= 4 && month <= 6) q = 2;
        else if (month >= 7 && month <= 9) q = 3;
        else q = 4;
        
        // Year adjustment for Q4 due in Jan
        const qYear = (q === 4 && month === 0) ? year - 1 : year;
        return `Q${q}-${qYear}`;
    }

    // ── MONTHLY ──────────────────────────────────────────────
    if (freq === 'MONTHLY') {
        const periodDate = new Date(date);
        periodDate.setMonth(date.getMonth() - 1);
        return `${MONTHS[periodDate.getMonth()]}-${periodDate.getFullYear()}`;
    }

    return null;
};


const formatDateCell = (value) => {
    if (!value) return 'No Due';
    const date = new Date(value);
    if (isNaN(date.getTime())) return 'Invalid Date';
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    return `${d}/${m}/${y}`;
};

const formatDateTimeCell = (value) => {
    if (!value) return 'N/A';
    const date = new Date(value);
    if (isNaN(date.getTime())) return 'Invalid Date';
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    return `${d}/${m}/${y}`;
};

const ComplianceCell = ({ status, date }) => (
    <div className="ledger-cell">
        <div className="ledger-compliance-stack">
            <span className={`ledger-status-badge ${getStatusStyle(status)}`}>
                {status || '-'}
            </span>
            {date && (
                <div className="ledger-due-box">
                    <span className="ledger-perf-dot"></span>
                    <span className="ledger-date-small">{formatDateCell(date)}</span>
                </div>
            )}
        </div>
    </div>
);

const readFirstValue = (item, keys) => keys.map((key) => item?.[key]).find((value) => value !== undefined && value !== null && value !== '');

const normalizeReturnType = (item) => {
    const raw = [
        item?.return_type,
        item?.form_type,
        item?.due_form_type,
        item?.compliance_type,
        item?.return_name,
        item?.return_label,
        item?.filing_type
    ].find((value) => value);

    const token = String(raw || '').toUpperCase().replace(/[^A-Z0-9]/g, '');

    if (!token) return null;
    if (token.includes('GSTR1')) return 'gstr1';
    if (token.includes('GSTR3B')) return 'gstr3b';
    if (token.includes('CMP08')) return 'cmp08';
    if (token.includes('GSTR4')) return 'gstr4';
    if (token.includes('GSTR9') || token.includes('9C') || token.includes('ANNUAL')) return 'gstr9';
    return null;
};

const getGroupingKey = (item, index) => (
    [
        item?.gst_filing_id,
        item?.id,
        item?.gst_registration_id,
        item?.gstin,
        item?.filing_period
    ].find((value) => value !== undefined && value !== null && value !== '') || `row-${index}`
);

const normalizeReturnsData = (rows) => {
    return rows.map((row) => {
        const frequency = (row?.filing_frequency || row?.filing_preference || '').toUpperCase();

        // 🔥 Primary: derive period from the detail row's actual due dates (ground truth)
        // Fallback: use parent filing's filing_period
        let period = computeEffectivePeriod(row, frequency) || row?.filing_period || 'NO_PERIOD';

        const filingId = row?.gst_filing_id || row?.id || 'NO_ID';
        const recordId = row?.id || `temp-${Math.random().toString(36).substr(2, 9)}`;

        const item = {
            id: recordId,
            gst_filing_id: filingId,
            gst_registration_id: row?.gst_registration_id ?? '-',
            is_active: Boolean(row?.is_active),
            filing_period: period,
            frequency: frequency,
            business_name: row?.business_name ?? '-',
            business_type: row?.business_type ?? '',
            taxpayer_type: row?.taxpayer_type ?? '',
            gstin: row?.gstin ?? '-',
            is_auto_generated: row?.is_auto_generated ?? false,
            next_auto_generate_at: row?.next_auto_generate_at ?? null,
            is_current: row?.is_current !== false, // Default to true if missing
            gstr1_status: null,
            gstr1_due_date: null,
            gstr3b_status: null,
            gstr3b_due_date: null,
            cmp08_status: null,
            cmp08_due_date: null,
            gstr4_status: null,
            gstr4_due_date: null,
            gstr9_status: null,
            gstr9_due_date: null,
            gstr9c_status: null,
            gstr9c_due_date: null,
        };

        BASE_MERGE_KEYS.forEach((mergeKey) => {
            const incoming = row?.[mergeKey];
            if (incoming !== undefined && incoming !== null && incoming !== '') {
                item[mergeKey] = incoming;
            }
        });

        // Map return statuses and due dates
        Object.keys(RETURN_FIELD_MAP).forEach((returnType) => {
            const { statusKeys, dueDateKeys } = RETURN_FIELD_MAP[returnType];
            
            statusKeys.forEach((key) => {
                if (row?.[key] !== undefined && row?.[key] !== null && row?.[key] !== '') {
                    item[statusKeys[0]] = row[key];
                }
            });

            dueDateKeys.forEach((key) => {
                if (row?.[key] !== undefined && row?.[key] !== null) {
                    item[dueDateKeys[0]] = row[key];
                }
            });
        });

        return item;
    });
};



const isReturnFieldApplicable = (item, fieldPrefix) => {
    const statusValue = item?.[`${fieldPrefix}_status`];
    const dueDateValue = item?.[`${fieldPrefix}_due_date`];
    return Boolean(statusValue || dueDateValue);
};

const GSTFilingsReturns = ({ filters, rowsPerPage, setError, onOpenStatusUpdate, refreshTrigger, currentPage, setCurrentPage, setHasMore }) => {
    const navigate = useNavigate();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);

    const normalizedFilters = useMemo(() => ({
        gstin: filters?.gstin || '',
        filing_period: filters?.filing_period || '',
        return_cycle: filters?.return_cycle || '',
        return_status_match: filters?.return_status_match || 'AND',
        return_status_rules: filters?.return_status_rules || [],
        due_date_match: filters?.due_date_match || 'AND',
        due_date_rules: filters?.due_date_rules || [],
        is_current: filters?.is_current !== undefined ? filters.is_current : true
    }), [filters]);
    
    // 🔥 Optimization: Memoize the grouping and normalization logic
    // This ensures we only re-calculate the "grouped" view when the raw API data changes.
    const normalizedData = useMemo(() => {
        return normalizeReturnsData(data);
    }, [data]);

    const fetchReturns = useCallback(async () => {
        setLoading(true);
        try {
            setError(null);
            const params = new URLSearchParams();

            Object.entries(normalizedFilters).forEach(([key, value]) => {
                if ([
                    'return_status_match',
                    'return_status_rules',
                    'due_date_match',
                    'due_date_rules',
                ].includes(key)) return;
                if (!value || value === 'ALL') return;

                if (key === 'return_cycle') {
                    if (value === 'MONTHLY') params.append('filing_frequency', 'MONTHLY');
                    else if (value === 'QUARTERLY') params.append('filing_frequency', 'QUARTERLY');
                    else if (value === 'ANNUAL') params.append('filing_category', 'ANNUAL');
                    return;
                }

                if (key === 'is_current' && value === true) {
                    params.append('is_current', 'true');
                    return;
                }

                params.append(key, value.toString());
            });

            appendReturnStatusRulesToParams(
                params,
                normalizedFilters.return_status_match,
                normalizedFilters.return_status_rules,
            );
            appendDueDateRulesToParams(
                params,
                normalizedFilters.due_date_match,
                normalizedFilters.due_date_rules,
            );

            params.append('include_inactive', 'true');
            params.append('include_details', 'true');
            params.append('offset', (currentPage - 1) * rowsPerPage);
            params.append('limit', rowsPerPage);

            const response = await api.get(`/api/v1/gst-filings/table/return-details?${params.toString()}`);
            const result = response.data || {};

            const rawData = result.data || [];
            
            // 🔥 Strict Stable Sort: Sort strictly by Record ID (Newest first)
            const sortedData = [...rawData].sort((a, b) => (b.id || 0) - (a.id || 0));

            setData(sortedData);

            setHasMore(rawData.length >= (rowsPerPage || 20));

        } catch (err) {
            console.error('Error fetching GST filing returns:', err);
            setError('Failed to load GST filing returns. Please check your connection.');
        } finally {
            setLoading(false);
        }
    }, [currentPage, normalizedFilters, rowsPerPage, setError, setHasMore]);

    useEffect(() => {
        setCurrentPage(1);
    }, [normalizedFilters]);

    useEffect(() => {
        fetchReturns();
    }, [fetchReturns, refreshTrigger]);

    const handleStatusFieldChange = (field, value) => {
        // Now handled by parent
    };

    return (
        <div className="gst-filings-returns-module">
            <div className="gst-ledger-container">
                {/* HEADERS */}
                <div className="ledger-header ledger-grid-template">
                    <div className="ledger-header-cell ledger-sticky-id ledger-sticky-col-1">ID</div>
                    <div className="ledger-header-cell ledger-sticky-id ledger-sticky-col-2">Filing ID</div>
                    <div className="ledger-header-cell">Period</div>
                    <div className="ledger-header-cell">GSTR-1</div>
                    <div className="ledger-header-cell">GSTR-3B</div>
                    <div className="ledger-header-cell">CMP-08</div>
                    <div className="ledger-header-cell">GSTR-4</div>
                    <div className="ledger-header-cell">GSTR-9</div>
                    <div className="ledger-header-cell">GSTR-9C</div>
                    <div className="ledger-header-cell">Auto</div>
                    <div className="ledger-header-cell">Status</div>
                    <div className="ledger-header-cell">Next Run</div>
                    <div className="ledger-header-cell gst-sticky-actions" style={{ justifyContent: 'center' }}>Action</div>
                </div>

                {/* BODY */}
                {loading ? (
                    <ReturnsTableSkeleton />
                ) : normalizedData.length > 0 ? (
                    <div className="ledger-body">
                        {normalizedData.map((item) => (
                            <div key={item.id} className={`ledger-row ledger-grid-template ${!item.is_current ? 'archived-row' : ''}`}>
                                <div className="ledger-cell ledger-sticky-id ledger-sticky-col-1 gst-filing-returns-id-cell">
                                    {item.id ?? '-'}
                                </div>
                                <div className="ledger-cell ledger-sticky-id ledger-sticky-col-2 gst-filing-returns-filing-id-cell">
                                    {item.gst_filing_id || '-'}
                                </div>

                                <div className="ledger-cell">
                                    <div className="period-tag small">
                                        {item.filing_period || '-'}
                                        {!item.is_current && <span className="archived-badge">ARCHIVED</span>}
                                    </div>
                                </div>
                                
                                <ComplianceCell status={item.gstr1_status} date={item.gstr1_due_date} />
                                <ComplianceCell status={item.gstr3b_status} date={item.gstr3b_due_date} />
                                <ComplianceCell status={item.cmp08_status} date={item.cmp08_due_date} />
                                <ComplianceCell status={item.gstr4_status} date={item.gstr4_due_date} />
                                <ComplianceCell status={item.gstr9_status} date={item.gstr9_due_date} />
                                <ComplianceCell status={item.gstr9c_status} date={item.gstr9c_due_date} />

                                <div className="ledger-cell">
                                    <span className={`ledger-auto-tag ${item.is_auto_generated ? 'verified' : 'manual'}`}>
                                        {item.is_auto_generated ? 'Auto' : 'Manual'}
                                    </span>
                                </div>
                                <div className="ledger-cell">
                                    <span className={`ledger-status-pill ${item.is_active ? 'active' : 'inactive'}`}>
                                        {item.is_active ? 'Active' : 'Inactive'}
                                    </span>
                                </div>
                                <div className="ledger-cell" style={{ color: 'var(--text-muted)' }}>
                                    {formatDateTimeCell(item.next_auto_generate_at)}
                                </div>
                                <div className="ledger-cell gst-sticky-actions" style={{ justifyContent: 'center' }}>
                                    <button
                                        type="button"
                                        className="ledger-action-btn"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onOpenStatusUpdate(item);
                                        }}
                                    >
                                        Update Status
                                    </button>
                                    <button
                                        type="button"
                                        className="ledger-action-btn"
                                        title="Record Payment"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            navigate(`/dashboard?tab=add-payment&service_type=GST_FILING_RETURN_DETAILS&entity_id=${item.id}&return_tab=gst&return_sub=filings&return_view=returns`);
                                        }}
                                    >
                                        <CreditCard size={14} />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="ledger-empty-container">
                        <History size={48} opacity={0.2} />
                        <span className="ledger-empty-title">No return details available</span>
                        <span className="ledger-empty-text">Try adjusting your filters or search terms</span>
                    </div>
                )}
            </div>

        </div>
    );
};

export default GSTFilingsReturns;
