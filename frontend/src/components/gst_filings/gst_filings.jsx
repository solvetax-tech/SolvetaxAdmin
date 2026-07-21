import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import '../Dashboard.css';
import './gst_filings.css';
import '../gst_registration/gst_registration.css';
import api from '../../utils/api';
import { useListLoading } from '../../hooks/useListLoading';
import {
    getRmOpAssignmentVisibility,
    resolveRmIdForPayload,
    resolveOpIdForPayload,
} from '../../utils/rmOpAssignmentFields';
import LoadingOverlay from '../common/LoadingOverlay';
import FilterDateInput from '../common/FilterDateInput';
import '../common/Filters.css';
import {
    gstFilingStatusOptions,
    gstReturnDetailEditableStatusOptions,
    gstReturnDetailStatusOptions,
    getGstStatusStyleKey,
    GST_RETURN_FORM_OPTIONS,
    createEmptyReturnStatusRule,
    getActiveReturnStatusRules,
    formatReturnStatusRulesSummary,
} from '../../utils/gstFilingStatusConstants';
import { pickFilingPayloadFields } from '../../utils/gstFilingFields';
import {
    FILING_ATTRIBUTE_FIELD_OPTIONS,
    DOCUMENT_FILTER_FIELD_OPTIONS,
    createEmptyFilingAttributeRule,
    createEmptyDueDateRule,
    createEmptyDocumentFilterRule,
    getActiveFilingAttributeRules,
    getActiveDueDateRules,
    getActiveDocumentFilterRules,
    getFilingAttributeValueOptions,
    getDocumentFilterValueOptions,
    formatFilingAttributeRule,
    formatDueDateRule,
    formatDocumentFilterRule,
    formatRulesSummary,
    appendFilingFilterRulesToParams,
} from '../../utils/gstFilterRulesConstants';
import GstFilterRuleBuilder from './GstFilterRuleBuilder';
import Pagination from '../common/Pagination';
import {
    Filter,
    X,
    RotateCcw,
    Plus,
    AlertCircle,
    Check,
    CheckCircle,
    CheckCircle2,
    User,
    Search,
    Clock,
    ArrowRight,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    FileText,
    History,
    Files,
    Sparkles,
    Eye,
    EyeOff,
    Pencil,
    CreditCard
} from 'lucide-react';
import GstFilingDocuments from './GstFilingDocuments';
import GSTFilingsReturns from './GSTFilingsReturns';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig, optionsFromConfigOnly, optionsFromPairs } from '../common/selectOptionUtils';
import {
    parseActiveEmployeesFromApi,
    buildRmOpSelectOptions,
} from '../../utils/activeEmployees';
import Button from '../ui/Button';
import StatusPill from '../ui/StatusPill';

/** Priority → pill tone: HIGH/URGENT danger, LOW neutral, NORMAL info. */
const priorityTone = (p) => {
    const v = String(p || '').toUpperCase();
    if (v === 'HIGH' || v === 'URGENT') return 'danger';
    if (v === 'LOW') return 'neutral';
    return 'info';
};

const extractErrorMessage = (err) => {
    const detail = err?.response?.data?.detail;
    if (detail && typeof detail === 'object' && detail.error && detail.error.message) {
        return detail.error.message;
    }
    if (Array.isArray(detail)) {
        const first = detail[0];
        const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : 'field';
        return `${String(field).replace(/_/g, ' ')}: ${first?.msg || 'Invalid value'}`;
    }
    if (typeof detail === 'string') return detail;
    return err?.message || 'Request failed. Please try again.';
};

/**
 * Optimized Location Search component to isolate typing-frequency re-renders.
 * Prevents the main GstFilings dashboard from re-rendering on every keystroke.
 */
const LocationSearchField = React.memo(({ onSelect, defaultValue = '' }) => {
    const [locSearch, setLocSearch] = useState(defaultValue);
    const [locResults, setLocResults] = useState([]);
    const [isLocDropdownOpen, setIsLocDropdownOpen] = useState(false);
    const [locLoading, setLocLoading] = useState(false);
    const [locError, setLocError] = useState(null);
    const skipNextLocSearch = useRef(false);

    useEffect(() => {
        if (skipNextLocSearch.current) {
            skipNextLocSearch.current = false;
            setLocError(null);
            return;
        }

        if (!locSearch) {
            setLocResults([]);
            setIsLocDropdownOpen(false);
            setLocError(null);
            return;
        }

        const isNumeric = /^\d+$/.test(locSearch);
        
        if (isNumeric) {
            if (locSearch.length < 6) {
                setLocResults([]);
                setLocError("Please enter a valid pincode");
                setIsLocDropdownOpen(true);
                return;
            } else if (locSearch.length > 6) {
                setLocResults([]);
                setLocError("Pincode must be exactly 6 digits");
                setIsLocDropdownOpen(true);
                return;
            }
        } else {
            if (locSearch.length < 2) {
                setLocResults([]);
                setIsLocDropdownOpen(false);
                setLocError(null);
                return;
            }
        }

        setLocError(null);

        const timeoutId = setTimeout(async () => {
            setLocLoading(true);
            try {
                let res;
                if (isNumeric && locSearch.length === 6) {
                    res = await api.get(`/api/v1/customers/pincode/${locSearch}`);
                } else {
                    const params = { name: locSearch, query: locSearch, search: locSearch };
                    res = await api.get(`/api/v1/customers/pincode-search`, { params });
                }
                
                const rawData = res.data;
                let locations = [];
                if (Array.isArray(rawData)) {
                    locations = rawData;
                } else if (rawData?.locations && Array.isArray(rawData.locations)) {
                    locations = rawData.locations;
                } else if (rawData && typeof rawData === 'object' && rawData.name) {
                    locations = [rawData];
                }

                setLocResults(locations);
                setIsLocDropdownOpen(true);
            } catch (err) {
                if (err.response?.status !== 404 && err.response?.status !== 422) {
                    console.error("Location lookup failed:", err);
                }
                setLocResults([]);
                setIsLocDropdownOpen(true);
            } finally {
                setLocLoading(false);
            }
        }, 250);

        return () => clearTimeout(timeoutId);
    }, [locSearch]);

    return (
        <div className="form-group-v4">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label>Location Search (Pincode/City)</label>
                {locLoading && <Clock size={12} className="refresh-spin" />}
            </div>
            <div style={{ position: 'relative' }}>
                <input
                    type="text"
                    placeholder="type pincode or city name..."
                    value={locSearch}
                    onChange={e => setLocSearch(e.target.value)}
                    onFocus={() => {
                        if (locResults.length > 0 || locError) setIsLocDropdownOpen(true);
                    }}
                />
                {isLocDropdownOpen && (
                    <div className="searchable-dropdown location-search-dropdown">
                        <div className="results-header">Search Results</div>
                        {locError ? (
                            <div className="no-results-item" style={{ padding: '12px 15px', color: 'var(--danger)', fontSize: '13px', textAlign: 'center', background: 'rgba(var(--danger-rgb), 0.05)' }}>
                                {locError}
                            </div>
                        ) : locResults.length > 0 ? (
                            locResults.map((loc, idx) => (
                                <div 
                                    key={`loc-${loc.pincode}-${idx}`} 
                                    className="dropdown-item"
                                    onClick={() => {
                                        onSelect(loc);
                                        skipNextLocSearch.current = true;
                                        setLocSearch(loc.name || '');
                                        setIsLocDropdownOpen(false);
                                    }}
                                >
                                    <div className="item-main">
                                        <div className="item-id">{loc.pincode}</div>
                                        <div className="item-name">{loc.name}</div>
                                    </div>
                                    <div className="item-sub">{loc.district}, {loc.state}</div>
                                </div>
                            ))
                        ) : (
                            <div className="no-results-item" style={{ padding: '12px 15px', color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center' }}>
                                No matching locations found
                            </div>
                        )}
                    </div>
                )}
                {isLocDropdownOpen && <div className="dropdown-backdrop" onClick={() => setIsLocDropdownOpen(false)} />}
            </div>
        </div>
    );
});

export const TableSkeleton = ({ columns, rows = 12 }) => {
    return (
        <div className="filings-ledger-body">
            {[...Array(rows)].map((_, i) => (
                <div key={`skeleton-${i}`} className="filings-ledger-row filings-ledger-grid-template filings-ledger-skeleton-row">
                    {[...Array(columns)].map((_, j) => (
                        <div key={`cell-${j}`} className="filings-ledger-cell">
                            <div
                                className="filings-ledger-skeleton-bar"
                                style={{
                                    width: j === 0 ? '30px' : undefined // Use CSS default (70%) for others
                                }}
                            />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );
};

export const GSTFilings = ({ isAdmin, profileData }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [hasMore, setHasMore] = useState(false);
    const [currentPage, setCurrentPage] = useState(1);
    const [showFilterDrawer, setShowFilterDrawer] = useState(false);
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [returnsHasMore, setReturnsHasMore] = useState(false);
    const [returnsCurrentPage, setReturnsCurrentPage] = useState(1);
    const rowsPerPage = 20;
    const { wrapFetch } = useListLoading();

    const buildDefaultMainFilters = () => ({
        id: '',
        gstin: '',
        customer_id: '',
        gst_registration_id: '',
        filing_filter_match: 'AND',
        filing_filter_rules: [createEmptyFilingAttributeRule()],
        rm_id: '',
        op_id: '',
        include_inactive: false,
        language: '',
        referral_id: '',
        referral_entity: '',
        created_from: '',
        created_to: '',
    });

    const [mainFilterInputs, setMainFilterInputs] = useState(buildDefaultMainFilters);

    const [mainAppliedFilters, setMainAppliedFilters] = useState(buildDefaultMainFilters);

    const buildDefaultReturnsFilters = () => ({
        gstin: '',
        filing_period: '',
        return_cycle: '',
        return_status_match: 'AND',
        return_status_rules: [createEmptyReturnStatusRule()],
        due_date_match: 'AND',
        due_date_rules: [createEmptyDueDateRule()],
        is_current: true,
    });

    const [returnsFilterInputs, setReturnsFilterInputs] = useState(buildDefaultReturnsFilters);

    const [returnsAppliedFilters, setReturnsAppliedFilters] = useState(buildDefaultReturnsFilters);

    const buildDefaultDocFilters = () => ({
        gst_filing_id: '',
        document_filter_match: 'AND',
        document_filter_rules: [createEmptyDocumentFilterRule()],
        verified_by: '',
        gstin: '',
        created_from: '',
        created_to: '',
    });

    const [docFilterInputs, setDocFilterInputs] = useState(buildDefaultDocFilters);

    const [appliedDocFilters, setAppliedDocFilters] = useState(buildDefaultDocFilters);

    const initialCreateFormState = {
        customer_id: '',
        gst_registration_id: '',
        gstin: '',
        filing_period: '',
        filing_frequency: 'MONTHLY',
        filing_category: 'RETURN',
        taxpayer_type: 'REGULAR',
        turnover_details: 'LESS_THAN_2CR',
        state: '',
        rent: '',
        username: '',
        password: '',
        priority: 'NORMAL',
        status: 'DATA_PENDING',
        remarks: '',
        rm_id: '',
        op_id: '',
        business_name: '',
        business_type: '',
        business_description: '',
        rule14a: false,
        email_id: '',
        is_auto_enabled: true,
        city: '',
        pincode: ''
    };

    const [createForm, setCreateForm] = useState(initialCreateFormState);

    // --- Status Update Modal (Hoisted from GSTFilingsReturns) ---
    const [selectedReturnForStatus, setSelectedReturnForStatus] = useState(null);
    const [statusUpdateLoading, setStatusUpdateLoading] = useState(false);
    const [statusUpdateForm, setStatusUpdateForm] = useState({
        gstr1_status: '',
        gstr3b_status: '',
        cmp08_status: '',
        gstr4_status: '',
        gstr9_status: '',
        gstr9c_status: ''
    });
    const [statusUpdateError, setStatusUpdateError] = useState('');
    const [statusRefreshTrigger, setStatusRefreshTrigger] = useState(0);

    const handleOpenStatusModal = (item) => {
        setSelectedReturnForStatus(item);
        setStatusUpdateForm({
            gstr1_status: item.gstr1_status || '',
            gstr3b_status: item.gstr3b_status || '',
            cmp08_status: item.cmp08_status || '',
            gstr4_status: item.gstr4_status || '',
            gstr9_status: item.gstr9_status || '',
            gstr9c_status: item.gstr9c_status || ''
        });
        setStatusUpdateError('');
    };

    const handleCloseStatusModal = () => {
        setSelectedReturnForStatus(null);
        setStatusUpdateError('');
        setStatusUpdateLoading(false);
    };

    const handleStatusSubmit = async (e) => {
        e.preventDefault();
        if (!selectedReturnForStatus) return;

        // 🔥 Source-Aware Routing Logic:
        // Because the UI collapses multiple DB records (Monthly & Yearly) into one row,
        // we must route each status change to its original source record ID.
        const rawItems = selectedReturnForStatus._rawItems || [selectedReturnForStatus];
        const updatesById = {};

        Object.entries(statusUpdateForm).forEach(([field, value]) => {
            // Only process changed fields
            if (!value || value === selectedReturnForStatus[field]) return;

            const fieldPrefix = field.split('_')[0];

            // Identify which raw database record owns this specific return field
            const targetItem = rawItems.find(item => {
                const hasStatus = item[`${fieldPrefix}_status`] !== undefined && item[`${fieldPrefix}_status`] !== null && item[`${fieldPrefix}_status`] !== '';
                const hasDate = item[`${fieldPrefix}_due_date`] !== undefined && item[`${fieldPrefix}_due_date`] !== null && item[`${fieldPrefix}_due_date`] !== '';
                return hasStatus || hasDate;
            });

            if (targetItem) {
                const targetId = targetItem.id;
                if (!updatesById[targetId]) updatesById[targetId] = {};
                updatesById[targetId][field] = value;
            }
        });

        if (Object.keys(updatesById).length === 0) {
            setStatusUpdateError('Select at least one applicable status change before saving.');
            return;
        }

        setStatusUpdateLoading(true);
        setStatusUpdateError('');

        try {
            // Send updates to each identified target ID in parallel
            await Promise.all(
                Object.entries(updatesById).map(([id, payload]) =>
                    api.patch(`/api/v1/gst-filings/${id}/returns/status`, payload)
                )
            );

            setStatusRefreshTrigger(prev => prev + 1);
            handleCloseStatusModal();
        } catch (err) {
            console.error('Error updating return statuses:', err);

            let message = 'Failed to update return statuses.';
            if (err?.response?.data?.detail) {
                const detail = err.response.data.detail;
                message = typeof detail === 'string' ? detail : (detail.message || JSON.stringify(detail));
            } else if (err?.response?.data?.message) {
                message = err.response.data.message;
            }

            setStatusUpdateError(message);
        } finally {
            setStatusUpdateLoading(false);
        }
    };

    const [formLoading, setFormLoading] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const [createError, setCreateError] = useState(null);
    const [customers, setCustomers] = useState([]);
    const [registrations, setRegistrations] = useState([]);
    const [activeSubTab, setActiveSubTab] = useState('GST Filings');

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        if (params.get('filing_view') === 'returns') {
            setActiveSubTab('GST Filings Returns');
        }
    }, [location.search]);

    // --- Hoisted Document States for Unified UI ---
    const [docsLoading, setDocsLoading] = useState(false);
    const [docsHasMore, setDocsHasMore] = useState(false);
    const [currentDocsPage, setCurrentDocsPage] = useState(1);
    const [configs, setConfigs] = useState({
        states: [],
        activeRMs: [],
        activeOps: [],
        employees: [],
        businessTypes: [],
        entityTypes: []
    });

    // Searchable Registration State
    const [regSearch, setRegSearch] = useState('');
    const [isRegDropdownOpen, setIsRegDropdownOpen] = useState(false);
    const [searchLoading, setSearchLoading] = useState(false);
    const [aiLoading, setAiLoading] = useState(false);
    const [autoSelectPeriod, setAutoSelectPeriod] = useState(true);
    const [existingPeriods, setExistingPeriods] = useState([]);
    const [editingFiling, setEditingFiling] = useState(null);
    const filingFormIsEdit = Boolean(editingFiling);
    const { showRmField, showOpField } = getRmOpAssignmentVisibility(profileData);
    const [recentSearches, setRecentSearches] = useState([]);
    const [showCreateDocModal, setShowCreateDocModal] = useState(false);

    const handleCloseCreateModal = () => {
        setShowCreateModal(false);
        setEditingFiling(null);
        setCreateForm(initialCreateFormState);
        setRegSearch('');
        setAutoSelectPeriod(true);
        setExistingPeriods([]);
        setError(null);
        setIsRegDropdownOpen(false);
        // NOTE: the location-search state (locSearch/locResults/…) is owned by
        // the child location-search input component, not this one; it resets
        // itself when the modal unmounts. Calling those setters here referenced
        // undefined variables and threw on every modal close.
    };

    const fetchExistingPeriods = async (regId) => {
        if (!regId) {
            setExistingPeriods([]);
            return;
        }

        try {
            // 🔥 NEW DEDICATED ENDPOINT: Fetching the list of occupied periods 
            // directly from the backend to ensure 100% accuracy and bypass RBAC gaps.
            const res = await api.get(`/api/v1/gst-filings/gst-registration/${regId}/occupied-periods`);
            const serverPeriods = res.data?.data || [];
            
            // Normalize for local comparison safety
            const localNorm = serverPeriods.map(p => normalizePeriod(p));
            setExistingPeriods(localNorm);
        } catch (err) {
            console.error("Triple-collision check failed:", err);
            setExistingPeriods([]);
        }
    };

    const handleEditFiling = async (item) => {
        setFormLoading(true);
        try {
            // First populate the form
            setEditingFiling(item);
            setCreateForm({
                ...initialCreateFormState,
                customer_id: item.customer_id,
                gst_registration_id: item.gst_registration_id,
                gstin: item.gstin || '',
                filing_period: item.filing_period,
                filing_frequency: item.filing_frequency,
                filing_category: item.filing_category,
                taxpayer_type: item.taxpayer_type,
                turnover_details: item.turnover_details,
                state: item.state || '',
                rent: item.rent || '',
                username: item.username || '',
                password: item.password || '',
                priority: item.priority || 'NORMAL',
                status: item.status || 'DATA_PENDING',
                remarks: item.remarks || '',
                rm_id: item.rm_id || '',
                op_id: item.op_id || '',
                business_name: item.business_name || '',
                business_type: item.business_type || '',
                business_description: item.business_description || '',
                rule14a: !!item.rule14a,
                email_id: item.email_id || '',
                is_auto_enabled: !!item.is_auto_enabled,
            });
            setAutoSelectPeriod(!!item.is_auto_enabled);
            setRegSearch(item.gstin || item.business_name || `Reg ${item.gst_registration_id}`);

            setShowCreateModal(true);
        } catch (err) {
            console.error("Error preparing edit modal:", err);
            setError("Failed to load filing data for editing");
        } finally {
            setFormLoading(false);
        }
    };

    // Real-time Collision Detection Effect
    useEffect(() => {
        if (showCreateModal && createForm.gst_registration_id) {
            fetchExistingPeriods(createForm.gst_registration_id);
        }
    }, [showCreateModal, createForm.gst_registration_id]);

    // Searchable Auditor State (for Document Filters)
    const [auditorSearch, setAuditorSearch] = useState('');
    const [isAuditorDropdownOpen, setIsAuditorDropdownOpen] = useState(false);
    const auditorInputRef = useRef(null);

    // Auto-focus hidden input when dropdown opens
    useEffect(() => {
        if (isAuditorDropdownOpen && auditorInputRef.current) {
            auditorInputRef.current.focus();
        }
    }, [isAuditorDropdownOpen]);

    // Load recent searches on mount
    useEffect(() => {
        const saved = localStorage.getItem('gst_recent_searches');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                if (Array.isArray(parsed)) setRecentSearches(parsed);
            } catch (e) {
                console.error("Failed to parse recent searches", e);
            }
        }
    }, []);

    const saveToRecentSearches = useCallback((reg) => {
        setRecentSearches(prev => {
            const filtered = prev.filter(item => item.id !== reg.id);
            const updated = [reg, ...filtered].slice(0, 5);
            localStorage.setItem('gst_recent_searches', JSON.stringify(updated));
            return updated;
        });
    }, []);

    // 🔥 Super-Fuzzy Normalizer: Removes ALL special characters (slashes, hyphens, dots, spaces) for maximum match reliability
    // 🔥 Enhanced Fuzzy Normalizer: Converts 'QUARTER-2' to 'Q2', 'Q 2' to 'Q2' and removes all non-alphanumeric.
    const normalizePeriod = (p) => {
        let s = (p || '').toString().toUpperCase().trim();
        // Standardize Quarter formats before alphanumeric cleanup
        s = s.replace(/QUARTER[-\s]?/g, 'Q');
        // Final cleanup
        return s.replace(/[^A-Z0-9]/g, '').trim();
    };

    // 🔥 Unified Period Formatter: The single source of truth for converting dates to labels
    const formatPeriodLabel = (dateRaw, frequency) => {
        if (!dateRaw) return null;
        const date = new Date(dateRaw);
        if (isNaN(date.getTime())) return null;

        const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
        const m = date.getMonth();
        const y = date.getFullYear();

        if (frequency === 'MONTHLY') {
            const d = new Date(date);
            d.setMonth(date.getMonth() - 1);
            return `${months[d.getMonth()]}-${d.getFullYear()}`;
        }

        if (frequency === 'QUARTERLY' || frequency === 'QRMP') {
            // Mapping Due Date Month to Period
            // Due Apr (3) -> Q1 (Jan-Mar)
            // Due Jul (6) -> Q2 (Apr-Jun)
            // Due Oct (9) -> Q3 (Jul-Sep)
            // Due Jan (0) -> Q4 (Oct-Dec)
            let q, qYear = y;
            if (m >= 1 && m <= 3) q = 1;      // FEB, MAR, APR -> Q1
            else if (m >= 4 && m <= 6) q = 2; // MAY, JUN, JUL -> Q2
            else if (m >= 7 && m <= 9) q = 3; // AUG, SEP, OCT -> Q3
            else { q = 4; if (m === 0) qYear = y - 1; } // NOV, DEC, JAN -> Q4 (JAN is for prev year)

            return `Q${q}-${qYear}`;
        }

        if (frequency === 'YEARLY' || frequency === 'ANNUAL' || frequency === 'ANUAL') {
            const fyStart = m <= 2 ? y - 2 : y - 1;
            return `${fyStart}-${String(fyStart + 1).slice(-2)}`;
        }

        return null;
    };

    /**
     * 🔥 Robust Period Helper: Extracts the stored period label from a record.
     * We strictly avoid "guessing" from dates if a label already exists to prevent phantom collisions.
     */
    const computeFilingPeriodFromRecord = (row) => {
        // Priority 1: Use existing label from DB (Most Accurate)
        const label = row.filing_period || row.period || row.period_name;
        if (label) return label;

        // Priority 2: ONLY derive from dates if the record is a placeholder with NO label
        if (row.is_auto_enabled || row.status === 'AUTO' || row.status === 'NOT_FILED' || !label) {
            const freq = (row.filing_frequency || row.filing_preference || 'QUARTERLY').toUpperCase();
            
            // 🔥 PRECISION DATE SCAN: Check only fields that logically define a filing cycle.
            // We EXCLUDE created_at because it doesn't strictly represent the filing period.
            const rawDate = row.due_date || row.gstr1_due_date || row.gstr3b_due_date || 
                            row.cmp08_due_date || row.gstr9_due_date || row.gstr4_due_date || 
                            row.next_auto_generate_at;
                            
            return formatPeriodLabel(rawDate, freq);
        }

        return null;
    };

    const calculatePreviousPeriod = (frequency) => {
        const now = new Date();
        // We use the shared formatter to ensure the default "Next" period
        // is always mathematically consistent with the dropdown options.
        return formatPeriodLabel(now, frequency);
    };

    const handleGenerateDescription = async () => {
        if (!createForm.business_name) {
            setError('Business name required for AI generation');
            return;
        }

        setAiLoading(true);
        try {
            const response = await api.post('/api/v1/customers/business-description/generate', {
                full_name: createForm.username || 'Filer',
                business_name: createForm.business_name,
                business_type: createForm.business_type,
                state: createForm.state,
                city: '',
                remark: createForm.remarks,
            });

            if (response.data?.business_description) {
                setCreateForm(prev => ({ ...prev, business_description: response.data.business_description }));
            }
        } catch (err) {
            console.error('AI Generation Error:', err);
            setError('Failed to generate business description.');
        } finally {
            setAiLoading(false);
        }
    };

    const fetchRegistrationsGlobally = async (search = '') => {
        setSearchLoading(true);
        try {
            let url = '/api/v1/gst-registrations/dynamic_filter?limit=20&offset=0';
            if (search) {
                if (/^\d+$/.test(search)) {
                    url += `&gst_registration_id=${search}`;
                } else if (/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$/i.test(search.trim())) {
                    url += `&gstin=${search.trim().toUpperCase()}`;
                } else {
                    url += `&business_name=${encodeURIComponent(search)}`;
                }
            }
            const res = await api.get(url);
            setRegistrations(res.data.data || []);
        } catch (err) {
            console.error("Error fetching registrations globally:", err);
        } finally {
            setSearchLoading(false);
        }
    };

    // Debounced search
    useEffect(() => {
        const timer = setTimeout(() => {
            if (showCreateModal) {
                fetchRegistrationsGlobally(regSearch);
            }
        }, 400);
        return () => clearTimeout(timer);
    }, [regSearch, showCreateModal]);

    const fetchConfigs = useCallback(async () => {
        try {
            const [statesRes, rmsRes, opsRes, empRes, btRes, entityRes] = await Promise.all([
                api.get('/api/v1/gst-registration/config/state'),
                api.get('/api/v1/employees/active-rm'),
                api.get('/api/v1/employees/active-op'),
                api.get('/api/v1/employees/filter?include_inactive=false&limit=100'),
                api.get('/api/v1/gst-registration/config/business-type'),
                api.get('/api/v1/entity-types?is_active=true&limit=100')
            ]);

            const adminList = Array.isArray(empRes.data) ? empRes.data : (empRes.data?.data || []);

            setConfigs({
                states: statesRes.data || [],
                // emp_id-bearing rows so RM/OP <select> option values are emp_ids
                // (filter + create/edit form both send rm_id/op_id as int).
                activeRMs: parseActiveEmployeesFromApi(rmsRes),
                activeOps: parseActiveEmployeesFromApi(opsRes),
                employees: adminList,
                businessTypes: btRes.data?.data || btRes.data || [],
                entityTypes: entityRes.data?.items || entityRes.data?.data || entityRes.data || []
            });
        } catch (err) {
            console.error("Error fetching GST configs:", err);
        }
    }, []);

    const generateFilingPeriods = (frequency) => {
        const periods = [];
        const now = new Date();

        if (frequency === 'MONTHLY') {
            for (let i = 0; i < 24; i++) {
                const d = new Date(now.getFullYear(), now.getMonth() - i, 15);
                const label = formatPeriodLabel(d, 'MONTHLY');
                if (label) periods.push(label);
            }
        } else if (frequency === 'QUARTERLY') {
            for (let i = 0; i < 8; i++) {
                // Stabilized generation: Start from the current quarter's end month and count back 3 months at a time.
                const d = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3 - (i * 3) + 3, 15);
                const label = formatPeriodLabel(d, 'QUARTERLY');
                if (label) periods.push(label);
            }
        } else if (frequency === 'YEARLY') {
            for (let i = 0; i < 4; i++) {
                const d = new Date(now.getFullYear() - i, 6, 15); // July of each year
                const label = formatPeriodLabel(d, 'YEARLY');
                if (label) periods.push(label);
            }
        }
        return [...new Set(periods)]; // Unique only
    };

    const fetchRegistrations = async (customerId) => {
        try {
            const res = await api.get(`/api/v1/gst-registrations/dynamic_filter?customer_id=${customerId}&limit=50&offset=0`);
            const regs = res.data.data || [];
            setRegistrations(regs);

            // If exactly one registration found, auto-select it
            if (regs.length === 1) {
                const reg = regs[0];
                handleRegistrationChange(reg.id, reg.customer_id);
            }
        } catch (err) {
            console.error("Error fetching registrations:", err);
        }
    };

    const fetchPrefillData = async (regId, customerId) => {
        setFormLoading(true);
        setError(null); // Clear any previous errors
        try {
            const res = await api.get(`/api/v1/gst-filings/gst-registration/${regId}/prefill`);
            const prefill = res.data;

            // 🔥 Legacy Data Mapper: Translate old DB values to new valid Literals
            const normalizePrefillValue = (val, type) => {
                if (!val) return val;
                const upper = val.toString().toUpperCase().trim();

                // Detect and ignore generic DB placeholders
                const isPlaceholder = ['STRING', 'NULL', 'UNDEFINED', 'N/A', '-'].includes(upper);

                if (type === 'taxpayer_type') {
                    if (isPlaceholder) return 'REGULAR'; // Default for placeholders
                    if (upper === 'NORMAL') return 'REGULAR';
                }

                if (type === 'turnover_details') {
                    if (isPlaceholder) return 'LESS_THAN_2CR'; // Default for placeholders
                    // Normalize variations of "Less than 2Cr"
                    if (upper.includes('LESS THAN 2') || upper.includes('UP TO 2') || upper.includes('LESS_THAN_2')) return 'LESS_THAN_2CR';

                    // Normalize variations of "Between 2Cr and 5Cr"
                    if (upper.includes('BETWEEN 2') || upper.includes('2CR-5CR') || upper.includes('BETWEEN_2CR_5CR')) return 'BETWEEN_2CR_5CR';

                    // Normalize variations of "More than 5Cr"
                    if (upper.includes('MORE THAN 5') || upper.includes('>5CR') || upper.includes('MORE_THAN_5') || upper.includes('>5 CR')) return 'MORE_THAN_5CR';

                    // Fallback to existing logic for exact legacy matches
                    if (upper === 'LESS_THAN_5CR' || upper === 'BETWEEN_2CR_5CR') return 'BETWEEN_2CR_5CR';
                }

                if (isPlaceholder) return ''; // Return empty for unknown placeholders in other fields (like state)
                return upper.replace(/\s+/g, '_'); // Replace spaces with underscores for general compliance
            };

            setExistingPeriods([]); // Reset periods before fetching new ones

            const tpType = normalizePrefillValue(prefill.taxpayer_type, 'taxpayer_type')?.toUpperCase();
            let freq = (prefill.filing_frequency || prefill.filing_preference || 'MONTHLY').toUpperCase();

            // 🔥 Auto-correction for Composition taxpayers: No MONTHLY allowed
            if (tpType === 'COMPOSITION' && freq === 'MONTHLY') {
                freq = 'QUARTERLY';
            }

            setCreateForm(prev => ({
                ...prev, // Keep non-profile state like filing_category or autoSelectPeriod
                gst_registration_id: regId,
                customer_id: customerId || prefill.customer_id || prev.customer_id,
                gstin: prefill.gstin || '',
                username: prefill.username || '',
                password: prefill.password || '',
                taxpayer_type: tpType || 'REGULAR',
                filing_frequency: freq || 'MONTHLY',
                turnover_details: normalizePrefillValue(prefill.turnover_details, 'turnover_details') || 'LESS_THAN_2CR',
                state: prefill.state || '',
                business_name: prefill.business_name || '',
                business_type: prefill.business_type || '',
                business_description: prefill.business_description || '',
                email_id: prefill.email_id || '',
                rm_id: prefill.rm_id || '',
                op_id: prefill.op_id || '',
                filing_period: autoSelectPeriod ? calculatePreviousPeriod(freq) : prev.filing_period
            }));

            // Save to recent searches
            saveToRecentSearches({
                id: regId,
                gstin: prefill.gstin,
                business_name: prefill.business_name,
                state: prefill.state,
                customer_id: customerId || prefill.customer_id
            });

            // Fetch existing filings for this registration to filter duplicates
            // We pass the gstin explicitly to avoid state-sync issues
            await fetchExistingPeriods(regId, prefill.gstin);
        } catch (err) {
            console.error("Error fetching prefill data:", err);
            setError(extractErrorMessage(err));

            // Revert selection if prefill failed (e.g., registration not APPROVED)
            setCreateForm(prev => ({
                ...prev,
                gst_registration_id: '',
                gstin: '',
                username: '',
                password: '',
                business_name: '',
                business_type: '',
                business_description: '',
                email_id: '',
                rm_id: '',
                op_id: ''
            }));
            setRegSearch('');
        } finally {
            setFormLoading(false);
        }
    };

    const handleRegistrationChange = (regId, customerId) => {
        if (!regId) {
            setExistingPeriods([]);
            setCreateForm(prev => ({
                ...prev,
                gst_registration_id: '',
                customer_id: '',
                gstin: '',
                username: '',
                password: '',
                business_name: '',
                business_type: '',
                business_description: '',
                taxpayer_type: 'REGULAR',
                filing_frequency: 'MONTHLY',
                turnover_details: 'LESS_THAN_2CR',
                state: '',
                email_id: '',
                rm_id: '',
                op_id: '',
                filing_period: autoSelectPeriod ? calculatePreviousPeriod('MONTHLY') : '',
                priority: 'Normal',
                rule_14a_applicable: false,
                rent_amount: '',
                remarks: '',
                filing_category: 'Return'
            }));
            return;
        }
        fetchPrefillData(regId, customerId);
    };

    useEffect(() => {
        fetchConfigs();
    }, [fetchConfigs]);

    useEffect(() => {
        if (showCreateModal) {
            fetchRegistrationsGlobally();
        }
    }, [showCreateModal]);

    const fetchFilings = useCallback(async () => {
        await wrapFetch(setLoading, async () => {
        setError(null);
        try {
            const params = new URLSearchParams();
            const activeFilters = activeSubTab === 'GST Filings Returns' ? returnsAppliedFilters : mainAppliedFilters;

            Object.entries(activeFilters).forEach(([key, value]) => {
                if (value !== '' && value !== null && value !== undefined) {
                    if (key === 'return_cycle') {
                        if (value === 'MONTHLY') params.append('filing_frequency', 'MONTHLY');
                        else if (value === 'QUARTERLY') params.append('filing_frequency', 'QUARTERLY');
                        else if (value === 'ANNUAL') params.append('filing_category', 'ANNUAL');
                    } else if ([
                        'return_status_match',
                        'return_status_rules',
                        'due_date_match',
                        'due_date_rules',
                        'filing_filter_match',
                        'filing_filter_rules',
                    ].includes(key)) {
                        // Handled below or by child fetchers
                    } else {
                        params.append(key, value.toString());
                    }
                }
            });

            if (activeSubTab === 'GST Filings') {
                appendFilingFilterRulesToParams(
                    params,
                    mainAppliedFilters.filing_filter_match,
                    mainAppliedFilters.filing_filter_rules,
                );
            }

            params.append('offset', (currentPage - 1) * rowsPerPage);
            params.append('limit', rowsPerPage);

            const endpoint = activeSubTab === 'GST Filings Returns'
                ? '/api/v1/gst-filings/table/return-details'
                : '/api/v1/gst-filings/table/filings';

            const response = await api.get(`${endpoint}?${params.toString()}`);
            const result = response.data;
            const filingsData = result.data || [];
            setData(filingsData);
            setHasMore(filingsData.length >= rowsPerPage);
        } catch (err) {
            console.error("Error fetching filings:", err);
            setError("Failed to load GST filings. Please check your connection.");
        }
        });
    }, [mainAppliedFilters, returnsAppliedFilters, currentPage, activeSubTab, wrapFetch]);

    useEffect(() => {
        if (activeSubTab === 'GST Filings') {
            fetchFilings();
        }
    }, [fetchFilings, activeSubTab]);

    const handleApplyFilters = () => {
        if (activeSubTab === 'Documents') {
            setAppliedDocFilters({
                ...docFilterInputs,
                document_filter_rules: (docFilterInputs.document_filter_rules || []).map((rule) => ({ ...rule })),
            });
        } else if (activeSubTab === 'GST Filings Returns') {
            setReturnsAppliedFilters({
                ...returnsFilterInputs,
                return_status_rules: (returnsFilterInputs.return_status_rules || []).map((rule) => ({ ...rule })),
                due_date_rules: (returnsFilterInputs.due_date_rules || []).map((rule) => ({ ...rule })),
            });
        } else {
            setMainAppliedFilters({
                ...mainFilterInputs,
                filing_filter_rules: (mainFilterInputs.filing_filter_rules || []).map((rule) => ({ ...rule })),
            });
        }
        setCurrentPage(1);
        setShowFilterDrawer(false);
    };

    const handleResetFilters = () => {
        if (activeSubTab === 'Documents') {
            const resetDoc = buildDefaultDocFilters();
            setDocFilterInputs(resetDoc);
            setAppliedDocFilters(resetDoc);
            setAuditorSearch('');
        } else if (activeSubTab === 'GST Filings Returns') {
            const resetReturns = buildDefaultReturnsFilters();
            setReturnsFilterInputs(resetReturns);
            setReturnsAppliedFilters(resetReturns);
        } else {
            const resetMain = buildDefaultMainFilters();
            setMainFilterInputs(resetMain);
            setMainAppliedFilters(resetMain);
        }
        setCurrentPage(1);
        setShowFilterDrawer(false);
    };

    const removeFilter = (key) => {
        if (activeSubTab === 'Documents') {
            if (key === 'document_filter_rules') {
                const next = buildDefaultDocFilters();
                setAppliedDocFilters(next);
                setDocFilterInputs(next);
                setCurrentPage(1);
                return;
            }
            setAppliedDocFilters(prev => ({ ...prev, [key]: '' }));
            setDocFilterInputs(prev => ({ ...prev, [key]: '' }));
        } else if (activeSubTab === 'GST Filings Returns') {
            if (key === 'return_status_rules') {
                const cleared = buildDefaultReturnsFilters();
                setReturnsAppliedFilters(cleared);
                setReturnsFilterInputs(cleared);
                return;
            }
            if (key === 'due_date_rules') {
                const next = {
                    ...returnsAppliedFilters,
                    due_date_match: 'AND',
                    due_date_rules: [createEmptyDueDateRule()],
                };
                setReturnsAppliedFilters(next);
                setReturnsFilterInputs(next);
                return;
            }
            const defaultValue = '';
            setReturnsAppliedFilters(prev => ({ ...prev, [key]: defaultValue }));
            setReturnsFilterInputs(prev => ({ ...prev, [key]: defaultValue }));
        } else if (key === 'filing_filter_rules') {
            const next = {
                ...mainAppliedFilters,
                filing_filter_match: 'AND',
                filing_filter_rules: [createEmptyFilingAttributeRule()],
            };
            setMainAppliedFilters(next);
            setMainFilterInputs(next);
            return;
        } else {
            const defaultValue = key === 'include_inactive' ? false : '';
            setMainAppliedFilters(prev => ({ ...prev, [key]: defaultValue }));
            setMainFilterInputs(prev => ({ ...prev, [key]: defaultValue }));
        }
        setCurrentPage(1);
    };

    const handleCreateSubmit = async (e) => {
        e.preventDefault();
        setFormLoading(true);
        try {
            const payload = { ...createForm };
            payload.rm_id = resolveRmIdForPayload({
                profileData,
                isEditMode: filingFormIsEdit,
                editingRecord: editingFiling,
                formRmId: createForm.rm_id,
            });
            payload.op_id = resolveOpIdForPayload({
                profileData,
                isEditMode: filingFormIsEdit,
                editingRecord: editingFiling,
                formOpId: createForm.op_id,
            });

            if (!editingFiling && payload.filing_period && existingPeriods.includes(normalizePeriod(payload.filing_period))) {
                setError(`A filing for period ${payload.filing_period} already exists.`);
                setFormLoading(false);
                return;
            }

            // Clean up: Delete empty strings for all fields to satisfy backend EmailStr and NotEmpty validators
            Object.keys(payload).forEach(key => {
                if (payload[key] === '' || payload[key] === null) {
                    delete payload[key];
                }
            });

            if (payload.gst_registration_id) {
                delete payload.gstin;
            }

            // Cleanup numeric/optional fields
            if (payload.rent) payload.rent = parseFloat(payload.rent);
            if (payload.rm_id) payload.rm_id = parseInt(payload.rm_id);
            if (payload.op_id) payload.op_id = parseInt(payload.op_id);

            // 🔥 STRICT LITERAL NORMALIZATION: Ensure backend-required literals are correct uppercase
            if (payload.filing_category) payload.filing_category = payload.filing_category.toUpperCase();
            if (payload.filing_frequency) payload.filing_frequency = payload.filing_frequency.toUpperCase();
            if (payload.taxpayer_type) payload.taxpayer_type = payload.taxpayer_type.toUpperCase();
            if (payload.turnover_details) payload.turnover_details = payload.turnover_details.toUpperCase();
            if (payload.priority) payload.priority = payload.priority.toUpperCase();
            if (payload.status) payload.status = payload.status.toUpperCase();
            if (payload.gst_reg_status) payload.gst_reg_status = payload.gst_reg_status.toUpperCase();
            if (payload.mode) payload.mode = payload.mode.toUpperCase();

            // 🔥 AIRTIGHT AUTO-GEN SAFETY: 
            // If the user manually picked a period (Auto-select is OFF), we MUST 
            // disable auto-generation to prevent redundant scheduling chains.
            // If Auto-select is ON, we ensure it's enabled.
            payload.is_auto_enabled = autoSelectPeriod;

            // Both filing schemas are extra:"forbid", so a single field the target
            // request does not accept 422s the WHOLE payload. See gstFilingFields.js
            // for which fields belong to which request and why.
            const body = pickFilingPayloadFields(payload, Boolean(editingFiling));
            if (!editingFiling) delete body.status;

            const method = editingFiling ? 'patch' : 'post';
            const endpoint = editingFiling ? `/api/v1/gst-filings/${editingFiling.id}` : '/api/v1/gst-filings';

            const response = await api[method](endpoint, body);

            // Check for potential "Duplicate" message returned with 200 OK status
            if (response.data?.message && response.data.message.includes('already exists')) {
                setError(response.data.message);
                setFormLoading(false);
                return;
            }

            handleCloseCreateModal();
            fetchFilings();
        } catch (err) {
            console.error("Error creating filing:", err);
            setError(extractErrorMessage(err));
        } finally {
            setFormLoading(false);
        }
    };

    const getStatusStyle = (status) => getGstStatusStyleKey(status);

    const getFilterLabel = (key, value) => {
        if (!value || value === false) return null;

        const ruleBuilderKeys = [
            'filing_filter_rules',
            'filing_filter_match',
            'return_status_rules',
            'return_status_match',
            'due_date_rules',
            'due_date_match',
            'document_filter_rules',
            'document_filter_match',
        ];
        if (ruleBuilderKeys.includes(key)) return null;

        // Document specific labels
        if (activeSubTab === 'Documents') {
            switch (key) {
                case 'gst_filing_id': return { label: 'Filing ID', value: value };
                case 'gstin': return { label: 'GSTIN', value: value };
                case 'verified_by': {
                    const emp = configs?.employees?.find(e => String(e.emp_id) === String(value));
                    return { label: 'Auditor', value: emp ? emp.username : value };
                }
                case 'created_from': return { label: 'From', value: value };
                case 'created_to': return { label: 'To', value: value };
                default: return null;
            }
        }

        // Returns specific labels
        if (activeSubTab === 'GST Filings Returns') {
            switch (key) {
                case 'filing_period': return { label: 'Period', value: value };
                case 'return_cycle': return { label: 'Cycle', value: value };
                default: break;
            }
        }

        // Filing specific labels
        const labels = {
            id: 'Filing ID',
            gstin: 'GSTIN',
            customer_id: 'Customer',
            gst_registration_id: 'GST ID',
            rm_id: 'RM',
            op_id: 'OP',
            include_inactive: 'Inactive',
            language: 'Language',
            referral_id: 'Referral ID',
            referral_entity: 'Referral',
            created_from: 'From',
            created_to: 'To',
        };

        let displayValue = String(value);
        if ((key === 'rm_id' || key === 'op_id') && configs?.employees) {
            const emp = configs.employees.find(e => String(e.emp_id) === String(value));
            if (emp) displayValue = emp.username;
        }

        return { label: labels[key] || key.replace('_', ' '), value: displayValue };
    };

    const countFiltersWithRules = (entries, ruleGroups = []) => {
        const exclude = new Set();
        ruleGroups.forEach(({ matchKey, rulesKey }) => {
            exclude.add(matchKey);
            exclude.add(rulesKey);
        });
        const scalarCount = Object.entries(entries).filter(([k, v]) => {
            if (exclude.has(k)) return false;
            if (v === '' || v === false) return false;
            return true;
        }).length;
        const ruleCount = ruleGroups.reduce(
            (sum, { rulesKey, getActive }) => sum + (getActive(entries[rulesKey]).length ? 1 : 0),
            0,
        );
        return scalarCount + ruleCount;
    };

    const docFilterCount = countFiltersWithRules(appliedDocFilters, [{
        matchKey: 'document_filter_match',
        rulesKey: 'document_filter_rules',
        getActive: getActiveDocumentFilterRules,
    }]);
    const activeFilterCount = activeSubTab === 'Documents'
        ? docFilterCount
        : activeSubTab === 'GST Filings Returns'
            ? countFiltersWithRules(returnsAppliedFilters, [
                { matchKey: 'return_status_match', rulesKey: 'return_status_rules', getActive: getActiveReturnStatusRules },
                { matchKey: 'due_date_match', rulesKey: 'due_date_rules', getActive: getActiveDueDateRules },
            ])
            : countFiltersWithRules(mainAppliedFilters, [{
                matchKey: 'filing_filter_match',
                rulesKey: 'filing_filter_rules',
                getActive: getActiveFilingAttributeRules,
            }]);

    return (

        <div className="gst-main-content gst-portal-page">

            <div className="gst-portal-top-row">
            <div className="dashboard-sub-nav-v4">
                <button
                    className={`sub-nav-btn-v4 ${activeSubTab === 'GST Filings' ? 'active' : ''}`}
                    onClick={() => setActiveSubTab('GST Filings')}
                >
                    <FileText size={14} />
                    <span>GST Filings</span>
                </button>
                <button
                    className={`sub-nav-btn-v4 ${activeSubTab === 'GST Filings Returns' ? 'active' : ''}`}
                    onClick={() => setActiveSubTab('GST Filings Returns')}
                >
                    <History size={14} />
                    <span>GST Filings Returns</span>
                </button>
                <button
                    className={`sub-nav-btn-v4 ${activeSubTab === 'Documents' ? 'active' : ''}`}
                    onClick={() => setActiveSubTab('Documents')}
                >
                    <Files size={14} />
                    <span>Documents</span>
                </button>
            </div>

                <div className="gst-portal-top-actions">
                    {activeFilterCount > 0 && (
                        <Button variant="ghost" size="sm" icon={<RotateCcw size={14} />} onClick={handleResetFilters}>
                            Reset Filters
                        </Button>
                    )}
                    <Button variant="secondary" size="sm" icon={<Filter size={13} />} onClick={() => setShowFilterDrawer(true)}>
                        Filters
                        {activeFilterCount > 0 && <span className="filter-badge-count">{activeFilterCount}</span>}
                    </Button>
                    {activeSubTab === 'Documents' ? (
                        <Button variant="primary" size="sm" icon={<Plus size={13} />} onClick={() => setShowCreateDocModal(true)}>
                            Add Document Link
                        </Button>
                    ) : activeSubTab === 'GST Filings' ? (
                        <Button variant="primary" size="sm" icon={<Plus size={13} />} onClick={() => setShowCreateModal(true)}>
                            New Filing
                        </Button>
                    ) : null}
                </div>
            </div>

            <div className="gst-registration-container">
                {activeFilterCount > 0 && (
                    <div className="gst-portal-filter-chips-row">
                        <div className="active-filters-container">
                            {activeSubTab === 'GST Filings Returns' && formatReturnStatusRulesSummary(
                                returnsAppliedFilters.return_status_match,
                                returnsAppliedFilters.return_status_rules,
                            ) && (
                                <div className="gst-filter-chip">
                                    <span className="filter-chip-label">Status:</span>
                                    <span className="filter-chip-value">
                                        {formatReturnStatusRulesSummary(
                                            returnsAppliedFilters.return_status_match,
                                            returnsAppliedFilters.return_status_rules,
                                        )}
                                    </span>
                                    <button type="button" className="btn-remove-chip" onClick={() => removeFilter('return_status_rules')}>
                                        <X size={13} />
                                    </button>
                                </div>
                            )}
                            {activeSubTab === 'GST Filings Returns' && formatRulesSummary(
                                returnsAppliedFilters.due_date_match,
                                getActiveDueDateRules(returnsAppliedFilters.due_date_rules),
                                formatDueDateRule,
                            ) && (
                                <div className="gst-filter-chip">
                                    <span className="filter-chip-label">Due dates:</span>
                                    <span className="filter-chip-value">
                                        {formatRulesSummary(
                                            returnsAppliedFilters.due_date_match,
                                            getActiveDueDateRules(returnsAppliedFilters.due_date_rules),
                                            formatDueDateRule,
                                        )}
                                    </span>
                                    <button type="button" className="btn-remove-chip" onClick={() => removeFilter('due_date_rules')}>
                                        <X size={13} />
                                    </button>
                                </div>
                            )}
                            {activeSubTab === 'GST Filings' && formatRulesSummary(
                                mainAppliedFilters.filing_filter_match,
                                getActiveFilingAttributeRules(mainAppliedFilters.filing_filter_rules),
                                (rule) => formatFilingAttributeRule(rule, configs.states),
                            ) && (
                                <div className="gst-filter-chip">
                                    <span className="filter-chip-label">Attributes:</span>
                                    <span className="filter-chip-value">
                                        {formatRulesSummary(
                                            mainAppliedFilters.filing_filter_match,
                                            getActiveFilingAttributeRules(mainAppliedFilters.filing_filter_rules),
                                            (rule) => formatFilingAttributeRule(rule, configs.states),
                                        )}
                                    </span>
                                    <button type="button" className="btn-remove-chip" onClick={() => removeFilter('filing_filter_rules')}>
                                        <X size={13} />
                                    </button>
                                </div>
                            )}
                            {activeSubTab === 'Documents' && formatRulesSummary(
                                appliedDocFilters.document_filter_match,
                                getActiveDocumentFilterRules(appliedDocFilters.document_filter_rules),
                                formatDocumentFilterRule,
                            ) && (
                                <div className="gst-filter-chip">
                                    <span className="filter-chip-label">Document:</span>
                                    <span className="filter-chip-value">
                                        {formatRulesSummary(
                                            appliedDocFilters.document_filter_match,
                                            getActiveDocumentFilterRules(appliedDocFilters.document_filter_rules),
                                            formatDocumentFilterRule,
                                        )}
                                    </span>
                                    <button type="button" className="btn-remove-chip" onClick={() => removeFilter('document_filter_rules')}>
                                        <X size={13} />
                                    </button>
                                </div>
                            )}
                            {Object.entries(
                                activeSubTab === 'Documents' ? appliedDocFilters :
                                    activeSubTab === 'GST Filings Returns' ? returnsAppliedFilters :
                                        mainAppliedFilters
                            ).map(([key, value]) => {
                                if (activeSubTab === 'GST Filings Returns' && [
                                    'return_status_rules',
                                    'return_status_match',
                                    'due_date_rules',
                                    'due_date_match',
                                ].includes(key)) {
                                    return null;
                                }
                                if (activeSubTab === 'GST Filings' && ['filing_filter_rules', 'filing_filter_match'].includes(key)) {
                                    return null;
                                }
                                if (activeSubTab === 'Documents' && ['document_filter_rules', 'document_filter_match'].includes(key)) {
                                    return null;
                                }
                                const data = getFilterLabel(key, value);
                                if (!data) return null;
                                return (
                                    <div key={key} className="gst-filter-chip">
                                        <span className="filter-chip-label">{data.label}:</span>
                                        <span className="filter-chip-value">{data.value}</span>
                                        <button type="button" className="btn-remove-chip" onClick={() => removeFilter(key)}>
                                            <X size={13} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}

            <main className="gst-main-content-table">
                <div className="gst-table-wrapper gst-table-wrapper--portal">
                <div className="gst-table-container gst-table-container--portal filings-gst-ledger-container">
                    {activeSubTab === 'GST Filings' ? (
                        <>

                            <div className="filings-ledger-header filings-ledger-grid-template">
                                <div className="filings-ledger-header-cell filings-ledger-sticky-id filings-ledger-sticky-col-1">ID</div>
                                <div className="filings-ledger-header-cell filings-ledger-sticky-id filings-ledger-sticky-col-2">Cust ID</div>
                                <div className="filings-ledger-header-cell filings-ledger-sticky-id filings-ledger-sticky-col-3">GST ID</div>
                                <div className="filings-ledger-header-cell">Period</div>
                                <div className="filings-ledger-header-cell">Category</div>
                                <div className="filings-ledger-header-cell">Priority</div>
                                <div className="filings-ledger-header-cell">GSTIN</div>
                                <div className="filings-ledger-header-cell">Type</div>
                                <div className="filings-ledger-header-cell">Frequency</div>
                                <div className="filings-ledger-header-cell">Status</div>
                                <div className="filings-ledger-header-cell">State</div>
                                <div className="filings-ledger-header-cell">RM</div>
                                <div className="filings-ledger-header-cell">OP</div>
                                <div className="filings-ledger-header-cell">Business Name</div>
                                <div className="filings-ledger-header-cell">Business Type</div>
                                <div className="filings-ledger-header-cell">Remarks</div>
                                <div className="filings-ledger-header-cell gst-sticky-actions" style={{ justifyContent: 'center' }}>Actions</div>
                            </div>

                            {loading ? (
                                <TableSkeleton columns={17} rows={12} />
                            ) : data.length > 0 ? (
                                <div className="filings-ledger-body">
                                    {data.map((item) => (
                                        <div key={item.id} className="filings-ledger-row filings-ledger-grid-template gst-table-row gst-table-row--static">
                                            <div className="filings-ledger-cell filings-ledger-sticky-id filings-ledger-sticky-col-1 gst-filings-filing-id-cell">
                                                <span className="ui-num">{item.id ?? '-'}</span>
                                            </div>
                                            <div className="filings-ledger-cell filings-ledger-sticky-id filings-ledger-sticky-col-2">
                                                <span className="ui-num">{item.customer_id ?? '-'}</span>
                                            </div>
                                            <div className="filings-ledger-cell filings-ledger-sticky-id filings-ledger-sticky-col-3">
                                                <span className="ui-num">{item.gst_registration_id || '-'}</span>
                                            </div>
                                            <div className="filings-ledger-cell">
                                                <span className="ui-num" style={{ color: 'var(--text-primary)' }}>{item.filing_period}</span>
                                            </div>
                                            <div className="filings-ledger-cell">
                                                <StatusPill tone="neutral" dot={false}>{item.filing_category}</StatusPill>
                                            </div>
                                            <div className="filings-ledger-cell">
                                                <StatusPill value={item.priority} tone={priorityTone(item.priority)} dot={false} />
                                            </div>
                                            <div className="filings-ledger-cell gstin-cell">
                                                <span className="ui-num">{item.gstin}</span>
                                            </div>
                                            <div className="filings-ledger-cell">
                                                <StatusPill tone="neutral" dot={false}>{item.taxpayer_type}</StatusPill>
                                            </div>
                                            <div className="filings-ledger-cell">
                                                <span className="freq-subtext">{item.filing_frequency}</span>
                                            </div>
                                            <div className="filings-ledger-cell">
                                                <StatusPill value={item.status} />
                                            </div>
                                            <div className="filings-ledger-cell state-cell">
                                                {configs.states?.find(s => s.value === item.state)?.display_name || item.state || '-'}
                                            </div>
                                            <div className="filings-ledger-cell staff-cell" title={`RM ID: ${item.rm_id}`}>
                                                {configs.employees.find(e => Number(e.emp_id) === Number(item.rm_id))?.username || '-'}
                                            </div>
                                            <div className="filings-ledger-cell staff-cell" title={`OP ID: ${item.op_id}`}>
                                                {configs.employees.find(e => Number(e.emp_id) === Number(item.op_id))?.username || '-'}
                                            </div>
                                            <div className="filings-ledger-cell business-name-cell" title={item.business_name}>
                                                {item.business_name || '-'}
                                            </div>
                                            <div className="filings-ledger-cell business-type-cell">
                                                {item.business_type || '-'}
                                            </div>
                                            <div className="filings-ledger-cell remarks-cell">
                                                <div className="remarks-scroll-box-ledger" title={item.remarks}>
                                                    {item.remarks || '-'}
                                                </div>
                                            </div>
                                            <div className="filings-ledger-cell gst-action-buttons gst-sticky-actions" style={{ justifyContent: 'center' }}>
                                                <Button
                                                    variant="ghost"
                                                    icon={<Pencil size={14} />}
                                                    title="Edit Filing"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleEditFiling(item);
                                                    }}
                                                />
                                                <Button
                                                    variant="ghost"
                                                    icon={<CreditCard size={14} />}
                                                    title="Record Payment"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        navigate(`/dashboard?tab=add-payment&service_type=GST_FILING&entity_id=${item.id}&return_tab=gst&return_sub=filings`);
                                                    }}
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="filings-ledger-empty-container">
                                    <Search size={48} opacity={0.2} />
                                    <span className="filings-ledger-empty-title">No filings found</span>
                                    <span className="filings-ledger-empty-text">Try adjusting your filters or search terms</span>
                                </div>
                            )}
                        </>
                    ) : activeSubTab === 'GST Filings Returns' ? (
                        <GSTFilingsReturns
                            filters={returnsAppliedFilters}
                            rowsPerPage={rowsPerPage}
                            setError={setError}
                            onOpenStatusUpdate={handleOpenStatusModal}
                            refreshTrigger={statusRefreshTrigger}
                            // Hoisted Pagination State
                            currentPage={returnsCurrentPage}
                            setCurrentPage={setReturnsCurrentPage}
                            setHasMore={setReturnsHasMore}
                        />
                    ) : activeSubTab === 'Documents' ? (
                        <GstFilingDocuments
                            filters={appliedDocFilters}
                            configs={configs}
                            setAppliedDocFilters={setAppliedDocFilters}
                            docFilterInputs={docFilterInputs}
                            setDocFilterInputs={setDocFilterInputs}
                            rowsPerPage={rowsPerPage}
                            setError={setError}
                            showCreateDocModal={showCreateDocModal}
                            setShowCreateDocModal={setShowCreateDocModal}
                            // Hoisted State
                            setCurrentDocsPage={setCurrentDocsPage}
                            currentDocsPage={currentDocsPage}
                            setDocsHasMore={setDocsHasMore}
                            docsHasMore={docsHasMore}
                            docsLoading={docsLoading}
                            setDocsLoading={setDocsLoading}
                        />
                    ) : null}
                </div>

                    <Pagination
                        currentPage={
                            activeSubTab === 'Documents' ? currentDocsPage :
                                activeSubTab === 'GST Filings Returns' ? returnsCurrentPage :
                                    currentPage
                        }
                        hasMore={
                            activeSubTab === 'Documents' ? docsHasMore :
                                activeSubTab === 'GST Filings Returns' ? returnsHasMore :
                                    hasMore
                        }
                        onPageChange={
                            activeSubTab === 'Documents' ? setCurrentDocsPage :
                                activeSubTab === 'GST Filings Returns' ? setReturnsCurrentPage :
                                    setCurrentPage
                        }
                        loading={loading || docsLoading}
                    />
                </div>
            </main>
            </div>

            {/* Filter Drawer */}
            {showFilterDrawer && (
                <div className="gst-filters-drawer-overlay" onClick={() => setShowFilterDrawer(false)}>
                    <div className="gst-filters-drawer" onClick={e => e.stopPropagation()}>
                        <div className="drawer-header">
                            <h2>{activeSubTab === 'Documents' ? 'Filter Documents' : 'Filter Filings'}</h2>
                            <button className="btn-drawer-close" onClick={() => setShowFilterDrawer(false)}><X size={20} /></button>
                        </div>

                        <div className="drawer-content">
                            {activeSubTab === 'Documents' ? (
                                <>
                                    <div className="filter-group-v4">
                                        <label>Filing ID</label>
                                        <input
                                            type="text"
                                            placeholder="Enter numeric ID (e.g. 52)"
                                            value={docFilterInputs.gst_filing_id}
                                            onChange={e => setDocFilterInputs({ ...docFilterInputs, gst_filing_id: e.target.value })}
                                        />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>GSTIN</label>
                                        <input
                                            type="text"
                                            placeholder="24AAAAA..."
                                            value={docFilterInputs.gstin}
                                            onChange={e => setDocFilterInputs({ ...docFilterInputs, gstin: e.target.value.toUpperCase() })}
                                        />
                                    </div>
                                    <GstFilterRuleBuilder
                                        title="Document filter rules"
                                        hint="Combine document type and verified status with AND or OR."
                                        matchMode={docFilterInputs.document_filter_match}
                                        onMatchModeChange={(mode) => setDocFilterInputs({ ...docFilterInputs, document_filter_match: mode })}
                                        rules={docFilterInputs.document_filter_rules}
                                        onRulesChange={(next) => setDocFilterInputs({ ...docFilterInputs, document_filter_rules: next })}
                                        createEmptyRule={createEmptyDocumentFilterRule}
                                        columns={[
                                            {
                                                key: 'field',
                                                placeholder: 'Select field',
                                                options: DOCUMENT_FILTER_FIELD_OPTIONS,
                                                clearOnChange: ['value'],
                                            },
                                            {
                                                key: 'value',
                                                placeholder: 'Select value',
                                                getOptions: (rule) => getDocumentFilterValueOptions(rule.field),
                                            },
                                        ]}
                                    />
                                    <div className="filter-group-v4">
                                        <label>Verified By (Auditor)</label>
                                        <div className={`headless-select-wrapper ${isAuditorDropdownOpen ? 'is-active' : ''}`} style={{ position: 'relative' }}>
                                            <div
                                                className="headless-select-trigger"
                                                onClick={() => setIsAuditorDropdownOpen(!isAuditorDropdownOpen)}
                                                tabIndex={0}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter' || e.key === ' ') {
                                                        setIsAuditorDropdownOpen(true);
                                                    }
                                                }}
                                                style={{
                                                    background: 'rgba(var(--fg-rgb), 0.03)',
                                                    border: '1px solid rgba(var(--fg-rgb), 0.08)',
                                                    borderRadius: '16px',
                                                    padding: '14px 18px',
                                                    color: docFilterInputs.verified_by ? 'var(--text-primary)' : 'rgba(var(--fg-rgb),0.3)',
                                                    fontSize: '13px',
                                                    cursor: 'pointer',
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    alignItems: 'center',
                                                    minHeight: '48px',
                                                    transition: 'all 0.2s'
                                                }}
                                            >
                                                <span>
                                                    {docFilterInputs.verified_by
                                                        ? configs.employees.find(e => String(e.emp_id) === docFilterInputs.verified_by)?.username
                                                        : 'Select Auditor...'}
                                                </span>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    {docFilterInputs.verified_by && (
                                                        <X
                                                            size={14}
                                                            className="clear-icon"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setDocFilterInputs({ ...docFilterInputs, verified_by: '' });
                                                                setAuditorSearch('');
                                                            }}
                                                        />
                                                    )}
                                                    <ChevronDown size={16} style={{
                                                        transform: isAuditorDropdownOpen ? 'rotate(180deg)' : 'rotate(0)',
                                                        transition: 'transform 0.3s ease',
                                                        opacity: 0.5
                                                    }} />
                                                </div>

                                                {/* Hidden input to capture keystrokes */}
                                                <input
                                                    type="text"
                                                    ref={auditorInputRef}
                                                    value={auditorSearch}
                                                    onChange={(e) => {
                                                        setAuditorSearch(e.target.value);
                                                        if (!isAuditorDropdownOpen) setIsAuditorDropdownOpen(true);
                                                    }}
                                                    onBlur={(e) => {
                                                        // Prevent closing if we clicked something inside the dropdown
                                                        if (!e.currentTarget.parentElement.contains(e.relatedTarget)) {
                                                            setTimeout(() => setIsAuditorDropdownOpen(false), 200);
                                                        }
                                                    }}
                                                    style={{
                                                        position: 'absolute',
                                                        opacity: 0,
                                                        top: 0,
                                                        left: 0,
                                                        width: '100%',
                                                        height: '100%',
                                                        border: 'none',
                                                        outline: 'none',
                                                        cursor: 'pointer'
                                                    }}
                                                />
                                            </div>

                                            {isAuditorDropdownOpen && (
                                                <div className="searchable-dropdown" style={{
                                                    position: 'absolute',
                                                    top: '100%',
                                                    left: 0,
                                                    right: 0,
                                                    maxHeight: '220px',
                                                    overflowY: 'auto',
                                                    background: 'var(--bg-elevated)',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '12px',
                                                    zIndex: 1000,
                                                    boxShadow: 'var(--shadow-lg)',
                                                    marginTop: '8px',
                                                    scrollbarWidth: 'thin',
                                                    scrollbarColor: 'rgba(var(--fg-rgb),0.2) transparent',
                                                    animation: 'dropdownIn 0.2s ease-out'
                                                }}>
                                                    {auditorSearch && (
                                                        <div style={{
                                                            padding: '8px 16px',
                                                            fontSize: '10px',
                                                            color: 'var(--accent)',
                                                            background: 'rgba(var(--accent-rgb), 0.05)',
                                                            borderBottom: '1px solid var(--border-subtle)',
                                                            fontWeight: '600',
                                                            display: 'flex',
                                                            justifyContent: 'space-between'
                                                        }}>
                                                            <span>FILTERING: {auditorSearch.toUpperCase()}</span>
                                                            <span onClick={() => setAuditorSearch('')} style={{ cursor: 'pointer', opacity: 0.6 }}>CLEAR</span>
                                                        </div>
                                                    )}

                                                    {(() => {
                                                        const filtered = configs.employees.filter(emp =>
                                                            emp.username?.toLowerCase().includes(auditorSearch.toLowerCase()) ||
                                                            emp.role?.toLowerCase().includes(auditorSearch.toLowerCase()) ||
                                                            emp.first_name?.toLowerCase().includes(auditorSearch.toLowerCase()) ||
                                                            emp.last_name?.toLowerCase().includes(auditorSearch.toLowerCase())
                                                        );

                                                        if (filtered.length === 0) {
                                                            return <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px', fontStyle: 'italic' }}>No staff matches "{auditorSearch}"</div>;
                                                        }

                                                        return filtered.map(emp => (
                                                            <div
                                                                key={emp.emp_id}
                                                                className={`dropdown-item ${docFilterInputs.verified_by === String(emp.emp_id) ? 'selected' : ''}`}
                                                                onClick={() => {
                                                                    setDocFilterInputs({ ...docFilterInputs, verified_by: String(emp.emp_id) });
                                                                    setAuditorSearch(''); // Clear search on select
                                                                    setIsAuditorDropdownOpen(false);
                                                                }}
                                                                style={{
                                                                    padding: '12px 16px',
                                                                    cursor: 'pointer',
                                                                    display: 'flex',
                                                                    justifyContent: 'space-between',
                                                                    alignItems: 'center',
                                                                    borderBottom: '1px solid var(--border-subtle)',
                                                                    background: docFilterInputs.verified_by === String(emp.emp_id) ? 'rgba(var(--accent-rgb), 0.12)' : 'transparent',
                                                                    transition: 'background 0.2s'
                                                                }}
                                                            >
                                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                                                    <span style={{ fontSize: '13px', color: docFilterInputs.verified_by === String(emp.emp_id) ? 'var(--accent)' : 'var(--text-primary)', fontWeight: '600' }}>{emp.username}</span>
                                                                    <span style={{ fontSize: '10px', color: 'var(--text-primary)' }}>{emp.first_name || ''} {emp.last_name || ''}</span>
                                                                </div>
                                                                <span className="role-badge" style={{
                                                                    fontSize: '9px',
                                                                    padding: '2px 6px',
                                                                    borderRadius: '4px',
                                                                    background: 'rgba(var(--fg-rgb),0.06)',
                                                                    color: 'var(--text-primary)',
                                                                    fontWeight: '800',
                                                                    textTransform: 'uppercase',
                                                                    letterSpacing: '0.05em'
                                                                }}>{emp.role}</span>
                                                            </div>
                                                        ));
                                                    })()}
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                    <div className="filter-section-v4">
                                        <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px' }}>Upload Timeline</h4>
                                        <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                            <div className="filter-group-v4">
                                                <label>From Date</label>
                                                <FilterDateInput
                                                    name="created_from"
                                                    value={docFilterInputs.created_from}
                                                    onChange={(e) => setDocFilterInputs({ ...docFilterInputs, created_from: e.target.value })}
                                                    ariaLabel="Created from"
                                                />
                                            </div>
                                            <div className="filter-group-v4">
                                                <label>To Date</label>
                                                <FilterDateInput
                                                    name="created_to"
                                                    value={docFilterInputs.created_to}
                                                    onChange={(e) => setDocFilterInputs({ ...docFilterInputs, created_to: e.target.value })}
                                                    ariaLabel="Created to"
                                                />
                                            </div>
                                        </div>
                                    </div>
                                </>
                            ) : (
                                <>
                                    {activeSubTab === 'GST Filings Returns' ? (
                                        <>
                                            <div className="filter-group-v4">
                                                <label>GSTIN / Identification</label>
                                                <input
                                                    type="text"
                                                    value={returnsFilterInputs.gstin}
                                                    onChange={e => setReturnsFilterInputs({ ...returnsFilterInputs, gstin: e.target.value.toUpperCase() })}
                                                    placeholder="e.g. 24AAAA..."
                                                />
                                            </div>


                                            <div className="filter-group-v4">
                                                <label>Return Cycle Focus</label>
                                                <div className="cycle-chips" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                                    {[
                                                        { id: 'MONTHLY', label: 'Monthly' },
                                                        { id: 'QUARTERLY', label: 'Quarterly' },
                                                        { id: 'ANNUAL', label: 'Annual (9/9C)' }
                                                    ].map(c => (
                                                        <button
                                                            key={c.id}
                                                            type="button"
                                                            className={`cycle-chip ${returnsFilterInputs.return_cycle === c.id ? 'active' : ''}`}
                                                            onClick={() => setReturnsFilterInputs({ ...returnsFilterInputs, return_cycle: returnsFilterInputs.return_cycle === c.id ? '' : c.id })}
                                                            style={{
                                                                padding: '8px 16px',
                                                                borderRadius: '20px',
                                                                border: '1px solid rgba(var(--fg-rgb),0.1)',
                                                                background: returnsFilterInputs.return_cycle === c.id ? 'rgba(var(--fg-rgb),0.1)' : 'transparent',
                                                                color: returnsFilterInputs.return_cycle === c.id ? 'var(--text-primary)' : 'rgba(var(--fg-rgb),0.4)',
                                                                fontSize: '11px',
                                                                fontWeight: '600',
                                                                cursor: 'pointer',
                                                                transition: 'all 0.2s'
                                                            }}
                                                        >
                                                            {c.label}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>

                                            <GstFilterRuleBuilder
                                                title="Return status rules"
                                                hint="Pick a form (GSTR-1, 3B, …) and one of the shared statuses for each rule."
                                                matchMode={returnsFilterInputs.return_status_match}
                                                onMatchModeChange={(mode) => setReturnsFilterInputs({ ...returnsFilterInputs, return_status_match: mode })}
                                                rules={returnsFilterInputs.return_status_rules}
                                                onRulesChange={(next) => setReturnsFilterInputs({ ...returnsFilterInputs, return_status_rules: next })}
                                                createEmptyRule={createEmptyReturnStatusRule}
                                                columns={[
                                                    {
                                                        key: 'form',
                                                        placeholder: 'Select form',
                                                        options: GST_RETURN_FORM_OPTIONS,
                                                        clearOnChange: ['status'],
                                                    },
                                                    {
                                                        key: 'status',
                                                        placeholder: 'Select status',
                                                        getOptions: () => gstReturnDetailStatusOptions(false),
                                                    },
                                                ]}
                                            />

                                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '12px 0' }} />

                                            <div className="filter-group-v4">
                                                <label>Filing Period</label>
                                                <input
                                                    type="text"
                                                    value={returnsFilterInputs.filing_period}
                                                    onChange={e => setReturnsFilterInputs({ ...returnsFilterInputs, filing_period: e.target.value })}
                                                    placeholder="e.g. APR-24"
                                                />
                                            </div>

                                            <GstFilterRuleBuilder
                                                title="Due date rules"
                                                hint="Filter by per-form due date ranges. Use from, to, or both on each rule."
                                                matchMode={returnsFilterInputs.due_date_match}
                                                onMatchModeChange={(mode) => setReturnsFilterInputs({ ...returnsFilterInputs, due_date_match: mode })}
                                                rules={returnsFilterInputs.due_date_rules}
                                                onRulesChange={(next) => setReturnsFilterInputs({ ...returnsFilterInputs, due_date_rules: next })}
                                                createEmptyRule={createEmptyDueDateRule}
                                                columns={[
                                                    {
                                                        key: 'form',
                                                        placeholder: 'Select form',
                                                        options: GST_RETURN_FORM_OPTIONS,
                                                    },
                                                    {
                                                        key: 'from',
                                                        type: 'date',
                                                        label: 'From',
                                                        ariaLabel: 'Due date from',
                                                    },
                                                    {
                                                        key: 'to',
                                                        type: 'date',
                                                        label: 'To',
                                                        ariaLabel: 'Due date to',
                                                    },
                                                ]}
                                            />

                                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                            <div className="filter-section-v4">
                                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px' }}>History & Versioning</h4>
                                                <div className="filter-row-v4">
                                                    <div className="filter-group-v4" style={{ flexDirection: 'row', alignItems: 'center', gap: '10px' }}>
                                                        <div 
                                                            className={`custom-checkbox-v4 ${returnsFilterInputs.is_current ? 'checked' : ''}`}
                                                            onClick={() => setReturnsFilterInputs({ ...returnsFilterInputs, is_current: !returnsFilterInputs.is_current })}
                                                        >
                                                            {returnsFilterInputs.is_current && <div className="checkmark-inner" />}
                                                        </div>
                                                        <label style={{ marginBottom: 0, fontSize: '11px', color: 'var(--text-primary)', cursor: 'pointer' }} onClick={() => setReturnsFilterInputs({ ...returnsFilterInputs, is_current: !returnsFilterInputs.is_current })}>
                                                            Show Current Versions Only
                                                        </label>
                                                    </div>
                                                </div>
                                            </div>
                                        </>
                                    ) : (
                                        <>
                                            <div className="filter-section-v4">
                                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px' }}>Account Identifiers</h4>
                                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                                    <div className="filter-group-v4">
                                                        <label>Filing ID (#)</label>
                                                        <input type="number" value={mainFilterInputs.id} onChange={e => setMainFilterInputs({ ...mainFilterInputs, id: e.target.value })} placeholder="ID..." />
                                                    </div>
                                                    <div className="filter-group-v4">
                                                        <label>GST Reg ID (#)</label>
                                                        <input type="number" value={mainFilterInputs.gst_registration_id} onChange={e => setMainFilterInputs({ ...mainFilterInputs, gst_registration_id: e.target.value })} placeholder="GID..." />
                                                    </div>
                                                </div>
                                            </div>

                                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                            <div className="filter-section-v4">
                                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px' }}>Assignment & Ownership</h4>
                                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                                    <div className="filter-group-v4">
                                                        <label>Assignee (RM)</label>
                                                        <FormCustomSelect
                                                            name="rm_id"
                                                            value={mainFilterInputs.rm_id}
                                                            onChange={(e) => setMainFilterInputs({ ...mainFilterInputs, rm_id: e.target.value })}
                                                            options={optionsFromPairs(buildRmOpSelectOptions(configs.activeRMs), 'Any RM')}
                                                            placeholder="Any RM"
                                                            ariaLabel="Assignee RM"
                                                        />
                                                    </div>
                                                    <div className="filter-group-v4">
                                                        <label>Operation (OP)</label>
                                                        <FormCustomSelect
                                                            name="op_id"
                                                            value={mainFilterInputs.op_id}
                                                            onChange={(e) => setMainFilterInputs({ ...mainFilterInputs, op_id: e.target.value })}
                                                            options={optionsFromPairs(buildRmOpSelectOptions(configs.activeOps), 'Any OP')}
                                                            placeholder="Any OP"
                                                            ariaLabel="Operation OP"
                                                        />
                                                    </div>
                                                </div>
                                            </div>

                                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                            <GstFilterRuleBuilder
                                                title="Filing attribute rules"
                                                hint="Combine status, priority, category, frequency, taxpayer type, or state with AND or OR."
                                                matchMode={mainFilterInputs.filing_filter_match}
                                                onMatchModeChange={(mode) => setMainFilterInputs({ ...mainFilterInputs, filing_filter_match: mode })}
                                                rules={mainFilterInputs.filing_filter_rules}
                                                onRulesChange={(next) => setMainFilterInputs({ ...mainFilterInputs, filing_filter_rules: next })}
                                                createEmptyRule={createEmptyFilingAttributeRule}
                                                columns={[
                                                    {
                                                        key: 'field',
                                                        placeholder: 'Select attribute',
                                                        options: FILING_ATTRIBUTE_FIELD_OPTIONS,
                                                        clearOnChange: ['value'],
                                                    },
                                                    {
                                                        key: 'value',
                                                        placeholder: 'Select value',
                                                        getOptions: (rule) => getFilingAttributeValueOptions(rule.field, configs.states),
                                                    },
                                                ]}
                                            />

                                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                            <div className="filter-section-v4">
                                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px' }}>Entity & Location</h4>
                                                <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                                    <label>GSTIN / Entity Identification</label>
                                                    <input
                                                        type="text"
                                                        value={mainFilterInputs.gstin}
                                                        onChange={e => setMainFilterInputs({ ...mainFilterInputs, gstin: e.target.value.toUpperCase() })}
                                                        placeholder="e.g. 24AAAA..."
                                                    />
                                                </div>
                                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px', marginTop: '12px' }}>
                                                    <div className="filter-group-v4">
                                                        <label>Language</label>
                                                        <input type="text" value={mainFilterInputs.language} onChange={e => setMainFilterInputs({ ...mainFilterInputs, language: e.target.value })} placeholder="Language" />
                                                    </div>
                                                    <div className="filter-group-v4">
                                                        <label>Referral Entity</label>
                                                        <FormCustomSelect
                                                            name="referral_entity"
                                                            value={mainFilterInputs.referral_entity}
                                                            onChange={(e) => setMainFilterInputs({ ...mainFilterInputs, referral_entity: e.target.value })}
                                                            options={optionsFromPairs([
                                                                { value: '', label: 'Any' },
                                                                ...(configs.entityTypes || []).map((ent) => ({
                                                                    value: ent.value || ent.name || ent,
                                                                    label: ent.entity_name || ent.display_name || ent.name || ent,
                                                                })),
                                                            ])}
                                                            placeholder="Any"
                                                            ariaLabel="Referral entity"
                                                        />
                                                    </div>
                                                </div>
                                                <div className="filter-group-v4" style={{ marginTop: '12px' }}>
                                                    <label>Referral ID</label>
                                                    <input type="number" value={mainFilterInputs.referral_id} onChange={e => setMainFilterInputs({ ...mainFilterInputs, referral_id: e.target.value })} placeholder="Referral ID" />
                                                </div>
                                            </div>

                                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                            <div className="filter-section-v4">
                                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px' }}>Audit Timeline</h4>
                                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                                    <div className="filter-group-v4">
                                                        <label>From Date</label>
                                                        <FilterDateInput
                                                            name="created_from"
                                                            value={mainFilterInputs.created_from}
                                                            onChange={(e) => setMainFilterInputs({ ...mainFilterInputs, created_from: e.target.value })}
                                                            ariaLabel="Created from"
                                                        />
                                                    </div>
                                                    <div className="filter-group-v4">
                                                        <label>To Date</label>
                                                        <FilterDateInput
                                                            name="created_to"
                                                            value={mainFilterInputs.created_to}
                                                            onChange={(e) => setMainFilterInputs({ ...mainFilterInputs, created_to: e.target.value })}
                                                            ariaLabel="Created to"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        </>
                                    )}
                                </>
                            )}
                        </div>

                        <div className="drawer-footer">
                            <button className="btn-reset-v4" onClick={handleResetFilters}>Reset</button>
                            <button className="btn-apply-v4" onClick={handleApplyFilters}>Apply Filters</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Creation Modal */}
            {showCreateModal && (
                <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={handleCloseCreateModal}>
                    <div className="gst-modal-card-v4 wide-modal app-drawer-panel gst-reg-side-drawer-shell" onClick={e => e.stopPropagation()}>
                        <div className="modal-header-v4">
                            <div className="header-content-v4">
                                <div className="header-icon-box-v4">
                                    <FileText size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <div className="modal-header-texts">
                                        <h2 className="modal-title-v4">{editingFiling ? `Edit GST Filing ${editingFiling.id}` : 'Create New GST Filing'}</h2>
                                        <p className="modal-subtitle-v4">{editingFiling ? 'Modify existing filing configuration and parameters' : 'Configure and initialize new GST return filing process'}</p>
                                    </div>
                                </div>
                            </div>
                            <button className="btn-drawer-close" onClick={handleCloseCreateModal}><X size={20} /></button>
                        </div>

                        <form onSubmit={handleCreateSubmit} className="modal-form-v4 expanded-form">
                             {editingFiling && (
                                <div className="sync-notice-banner-v4" style={{ margin: '0 32px 24px' }}>
                                    <div className="sync-notice-icon">
                                        <RotateCcw size={16} />
                                    </div>
                                    <div className="sync-notice-text">
                                        <strong>Identity Sync Active:</strong> Core business updates (State, Frequency, Turnover) made here will sync back to the master GST Registration record.
                                    </div>
                                </div>
                             )}

                             {error && (
                                <div className="gst-message-banner error" style={{ margin: '0 24px 20px 24px' }}>
                                    <AlertCircle size={18} />
                                    <span className="gst-message-banner-text">{error}</span>
                                </div>
                            )}
                            <div className="form-scroll-container">
                                {/* SECTION 1: IDENTITY & LINK */}
                                <div className="form-section-group">
                                    <h3 className="section-title">1. Search & Link Registration</h3>
                                    <div className="form-grid-2 section-1-grid">
                                        <div className="form-group-v4 searchable-select-container">
                                            <label>Search GST Registration (GSTIN / ID / Name)</label>
                                            <div className={`searchable-select-wrapper ${searchLoading ? 'is-loading' : ''}`}>
                                                <input
                                                    type="text"
                                                    placeholder={editingFiling ? "Registration fixed" : "Enter GSTIN, ID, or Business Name..."}
                                                    value={regSearch}
                                                    onFocus={() => !editingFiling && setIsRegDropdownOpen(true)}
                                                    onChange={(e) => {
                                                        const val = e.target.value;
                                                        setRegSearch(val);
                                                        setIsRegDropdownOpen(true);

                                                        if (!val) {
                                                            handleRegistrationChange(null);
                                                            setRegistrations([]);
                                                        }
                                                    }}
                                                    disabled={!!editingFiling}
                                                    className={`search-select-input ${editingFiling ? 'disabled-input' : ''}`}
                                                />
                                                <div className="input-affix-right">
                                                    {(regSearch && !searchLoading && !formLoading && !editingFiling) ? (
                                                        <button
                                                            type="button"
                                                            className="clear-search-btn"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setRegSearch('');
                                                                handleRegistrationChange(null);
                                                                setRegistrations([]);
                                                                setIsRegDropdownOpen(false);
                                                            }}
                                                        >
                                                            <X size={14} />
                                                        </button>
                                                    ) : (
                                                        (searchLoading || formLoading) ? <RotateCcw size={14} className="refresh-spin" /> : <Search size={14} />
                                                    )}
                                                </div>

                                                {isRegDropdownOpen && (
                                                    <div className="searchable-dropdown">
                                                        {searchLoading && (
                                                            <div className="dropdown-skeleton-container">
                                                                {[1, 2, 3].map(i => (
                                                                    <div key={i} className="dropdown-skeleton-item">
                                                                        <div className="skeleton-circle gst-skeleton-pulse" />
                                                                        <div className="skeleton-content">
                                                                            <div className="skeleton-line long gst-skeleton-pulse" />
                                                                            <div className="skeleton-line medium gst-skeleton-pulse" />
                                                                        </div>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}
                                                        {!regSearch && recentSearches.length > 0 && registrations.length === 0 && (
                                                            <div className="recent-searches-section">
                                                                <div className="recent-searches-header">
                                                                    <History size={12} />
                                                                    <span>Recent Registrations</span>
                                                                </div>
                                                                {recentSearches.map(r => (
                                                                    <div
                                                                        key={`recent-${r.id}`}
                                                                        className="dropdown-item recent-item"
                                                                        onClick={() => {
                                                                            setIsRegDropdownOpen(false);
                                                                            setRegSearch(r.gstin || r.business_name || `Reg ${r.id}`);
                                                                            handleRegistrationChange(r.id, r.customer_id);
                                                                        }}
                                                                    >
                                                                        <div className="item-main">
                                                                            <span className="item-id">{r.id}</span>
                                                                            <span className="item-name">{r.gstin}</span>
                                                                        </div>
                                                                        <div className="item-sub">
                                                                            {r.business_name} • <span style={{ color: 'var(--accent)' }}>{r.state}</span>
                                                                        </div>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}

                                                        {registrations.length > 0 ? (
                                                            <div className="results-section">
                                                                {regSearch && (
                                                                    <div className="results-header">Search Results</div>
                                                                )}
                                                                {registrations.map(r => (
                                                                    <div
                                                                        key={r.id}
                                                                        className={`dropdown-item ${createForm.gst_registration_id === r.id ? 'selected' : ''}`}
                                                                        onClick={() => {
                                                                            // Manual selection triggers the selection and pre-fill
                                                                            setIsRegDropdownOpen(false);
                                                                            setRegSearch(r.gstin || r.business_name || `Reg ${r.id}`);
                                                                            handleRegistrationChange(r.id, r.customer_id);
                                                                        }}
                                                                    >
                                                                        <div className="item-main">
                                                                            <span className="item-id">{r.id}</span>
                                                                            <span className="item-name">{r.gstin}</span>
                                                                            <span className="item-badge">{r.registration_status}</span>
                                                                        </div>
                                                                        <div className="item-sub">
                                                                            {r.business_name} • <span style={{ color: 'var(--accent)', fontWeight: '800' }}>{r.state}</span> • <span style={{ opacity: 0.6 }}>Cust {r.customer_id}</span>
                                                                        </div>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            !searchLoading && regSearch && <div className="dropdown-no-results">No registrations found</div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                            {isRegDropdownOpen && <div className="dropdown-backdrop" onClick={() => setIsRegDropdownOpen(false)} />}
                                        </div>

                                        <div className="form-group-v4">
                                            <label>Manual GSTIN (Optional)</label>
                                            <input
                                                type="text"
                                                placeholder="24AAAAA0000A1Z5"
                                                value={createForm.gstin}
                                                onChange={e => setCreateForm({ ...createForm, gstin: e.target.value.toUpperCase() })}
                                                disabled={!!createForm.gst_registration_id}
                                            />
                                        </div>
                                    </div>
                                </div>

                                 <div className="form-section-group">
                                    <h3 className="section-title">2. Business Rules</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label>Filing Category</label>
                                            <FormCustomSelect
                                                name="filing_category"
                                                value={createForm.filing_category}
                                                onChange={(e) => setCreateForm({ ...createForm, filing_category: e.target.value })}
                                                options={optionsFromConfigOnly([
                                                    { value: 'RETURN', label: 'Return' },
                                                    { value: 'ANNUAL', label: 'Annual' },
                                                ])}
                                                placeholder="Filing category"
                                                ariaLabel="Filing category"
                                            />
                                        </div>

                                        <div className="form-group-v4">
                                            <label>Taxpayer Type</label>
                                            <FormCustomSelect
                                                name="taxpayer_type"
                                                value={createForm.taxpayer_type}
                                                onChange={(e) => setCreateForm({ ...createForm, taxpayer_type: e.target.value })}
                                                options={optionsFromConfigOnly([
                                                    { value: 'REGULAR', label: 'Regular' },
                                                    { value: 'COMPOSITION', label: 'Composition' },
                                                ])}
                                                placeholder="Taxpayer type"
                                                ariaLabel="Taxpayer type"
                                                disabled
                                            />
                                        </div>

                                        <div className="form-group-v4">
                                            <label>Filing Frequency</label>
                                            <FormCustomSelect
                                                name="filing_frequency"
                                                value={createForm.filing_frequency}
                                                onChange={(e) => {
                                                    const freq = e.target.value;
                                                    setCreateForm({
                                                        ...createForm,
                                                        filing_frequency: freq,
                                                        filing_period: autoSelectPeriod ? calculatePreviousPeriod(freq) : createForm.filing_period,
                                                    });
                                                }}
                                                options={optionsFromPairs([
                                                    ...(createForm.taxpayer_type !== 'COMPOSITION'
                                                        ? [{ value: 'MONTHLY', label: 'Monthly' }]
                                                        : []),
                                                    { value: 'QUARTERLY', label: 'Quarterly' },
                                                    { value: 'YEARLY', label: 'Yearly' },
                                                ])}
                                                placeholder="Filing frequency"
                                                ariaLabel="Filing frequency"
                                            />
                                        </div>

                                         <div className="form-group-v4">
                                            <label>Turnover Details</label>
                                            <FormCustomSelect
                                                name="turnover_details"
                                                value={createForm.turnover_details}
                                                onChange={(e) => setCreateForm({ ...createForm, turnover_details: e.target.value })}
                                                options={optionsFromConfigOnly([
                                                    { value: 'LESS_THAN_2CR', label: 'Less than 2Cr' },
                                                    { value: 'BETWEEN_2CR_5CR', label: '2Cr - 5Cr' },
                                                    { value: 'MORE_THAN_5CR', label: 'More than 5Cr' },
                                                ])}
                                                placeholder="Turnover details"
                                                ariaLabel="Turnover details"
                                            />
                                        </div>

                                        <div className="form-group-v4">
                                            <LocationSearchField 
                                                defaultValue={createForm.city}
                                                onSelect={(loc) => {
                                                    const apiState = (loc.state || '').toLowerCase();
                                                    const matchedState = configs.states.find(s => 
                                                        s.value?.toLowerCase() === apiState || 
                                                        s.display_name?.toLowerCase() === apiState
                                                    );

                                                    setCreateForm(prev => ({ 
                                                        ...prev, 
                                                        state: matchedState ? matchedState.value : (loc.state || '').toUpperCase(),
                                                        city: loc.name || '',
                                                        pincode: loc.pincode || ''
                                                    }));
                                                }}
                                            />
                                        </div>

                                        <div className="form-group-v4">
                                            <label>State</label>
                                            <FormCustomSelect
                                                name="state"
                                                value={createForm.state}
                                                onChange={(e) => setCreateForm({ ...createForm, state: e.target.value })}
                                                options={optionsFromConfig(configs.states, 'Select State')}
                                                placeholder="Select State"
                                                ariaLabel="State"
                                            />
                                        </div>
                                    </div>

                                    {/* Auto Generation Section - Full Width */}
                                    <div style={{ marginTop: '24px' }}>
                                        <div style={{ 
                                                background: 'rgba(var(--fg-rgb),0.02)', 
                                                padding: '28px', 
                                                borderRadius: '20px', 
                                                border: '1px solid rgba(var(--fg-rgb),0.05)', 
                                                display: 'grid', 
                                                gridTemplateColumns: '1.3fr 1fr 1fr', 
                                                gap: '24px 40px'
                                            }}>
                                                {/* COLUMN 1: Auto-select & Description */}
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                    <div className="auto-select-container" style={{ marginBottom: 0 }}>
                                                        <div
                                                            className={`custom-checkbox-v4 ${autoSelectPeriod ? 'checked' : ''}`}
                                                            onClick={() => {
                                                                const newState = !autoSelectPeriod;
                                                                setAutoSelectPeriod(newState);
                                                                setCreateForm(prev => ({
                                                                    ...prev,
                                                                    is_auto_enabled: newState,
                                                                    // Editing: is_auto_enabled still saves, but the period itself is
                                                                    // fixed -- don't show a recalculated one that can never persist.
                                                                    filing_period: (newState && !editingFiling)
                                                                        ? calculatePreviousPeriod(prev.filing_frequency)
                                                                        : prev.filing_period
                                                                }));
                                                            }}
                                                        >
                                                            {autoSelectPeriod && <div className="checkmark-inner" />}
                                                        </div>
                                                        <div
                                                            className="auto-select-label"
                                                            style={{ fontSize: '11px', fontWeight: '600' }}
                                                            onClick={() => {
                                                                const newState = !autoSelectPeriod;
                                                                setAutoSelectPeriod(newState);
                                                                setCreateForm(prev => ({
                                                                    ...prev,
                                                                    is_auto_enabled: newState,
                                                                    // Editing: is_auto_enabled still saves, but the period itself is
                                                                    // fixed -- don't show a recalculated one that can never persist.
                                                                    filing_period: (newState && !editingFiling)
                                                                        ? calculatePreviousPeriod(prev.filing_frequency)
                                                                        : prev.filing_period
                                                                }));
                                                            }}
                                                        >
                                                            Auto-select previous period
                                                        </div>
                                                    </div>
                                                    
                                                    <p style={{ margin: 0, fontSize: '10px', color: 'var(--text-primary)', paddingLeft: '32px', lineHeight: '1.5' }}>
                                                        Enable to automatically calculate the period based on today's date.
                                                    </p>
                                                </div>

                                                {/* COLUMN 2: Period Dropdown & Warning Badge */}
                                                {/* Period is identity: fixed once the filing exists (see gstFilingFields.js). */}
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                    <div style={{ width: '100%' }}>
                                                        <FormCustomSelect
                                                            key={`period-select-${existingPeriods.length}`}
                                                            name="filing_period"
                                                            value={createForm.filing_period}
                                                            onChange={(e) => setCreateForm({ ...createForm, filing_period: e.target.value })}
                                                            disabled={autoSelectPeriod || Boolean(editingFiling)}
                                                            options={optionsFromPairs([
                                                                ...(!autoSelectPeriod ? [{ value: '', label: 'Select Period' }] : []),
                                                                ...generateFilingPeriods(createForm.filing_frequency)
                                                                    .filter((p) => {
                                                                        const normP = normalizePeriod(p);
                                                                        if (autoSelectPeriod) return normP === normalizePeriod(createForm.filing_period);
                                                                        return !existingPeriods.some((ep) => ep === normP);
                                                                    })
                                                                    .map((p) => ({ value: p, label: p })),
                                                            ])}
                                                            placeholder="Select Period"
                                                            ariaLabel="Filing period"
                                                        />
                                                    </div>

                                                    {editingFiling && (
                                                        <p style={{ margin: 0, fontSize: '10px', color: 'var(--text-muted)', lineHeight: '1.5' }}>
                                                            Period is fixed once the filing exists. Create a new filing for another period.
                                                        </p>
                                                    )}

                                                    {autoSelectPeriod && createForm.filing_period && createForm.filing_period !== "" &&
                                                        existingPeriods.some(ep => ep === normalizePeriod(createForm.filing_period)) && (
                                                        <div 
                                                            className="warning-badge-v4" 
                                                            style={{ 
                                                                color: 'var(--warning)',
                                                                display: 'flex', 
                                                                alignItems: 'center', 
                                                                gap: '4px',
                                                                cursor: 'help',
                                                                padding: '4px 10px',
                                                                borderRadius: '6px',
                                                                background: 'rgba(var(--warning-rgb), 0.1)',
                                                                border: '1px solid rgba(var(--warning-rgb), 0.15)',
                                                                whiteSpace: 'nowrap',
                                                                width: 'fit-content',
                                                                marginTop: '4px',
                                                                animation: 'fadeIn 0.2s ease-out'
                                                            }}
                                                            title="This period already has an active filing. Please review."
                                                        >
                                                            <AlertCircle size={10} />
                                                            <span style={{ fontSize: '9px', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Already Filed</span>
                                                        </div>
                                                    )}
                                                </div>

                                                {/* COLUMN 3: Auto Generation Section & Status Message */}
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                                        <div className={`custom-checkbox-v4 ${autoSelectPeriod ? 'checked' : ''}`} style={{ cursor: 'default' }}>
                                                            {autoSelectPeriod && <div className="checkmark-inner" />}
                                                        </div>
                                                        <label style={{ marginBottom: 0, fontSize: '10px', color: 'var(--text-primary)', cursor: 'default', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Auto Generation</label>
                                                    </div>
                                                    
                                                    <div style={{ 
                                                        fontSize: '10px', 
                                                        fontWeight: '700',
                                                        textTransform: 'uppercase',
                                                        letterSpacing: '0.04em',
                                                        color: autoSelectPeriod ? 'var(--accent)' : 'rgba(var(--fg-rgb),0.3)',
                                                        background: autoSelectPeriod ? 'rgba(var(--accent-rgb), 0.1)' : 'transparent',
                                                        padding: autoSelectPeriod ? '4px 12px' : '0',
                                                        borderRadius: '6px',
                                                        width: 'fit-content',
                                                        transition: 'all 0.3s ease',
                                                        whiteSpace: 'nowrap',
                                                        marginLeft: '32px',
                                                        marginTop: '4px'
                                                    }}>
                                                        {autoSelectPeriod 
                                                            ? "Enabled for next filing period" 
                                                            : "Disabled for next filing period"}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>






                                {/* SECTION 3: FILING IDENTITY */}
                                <div className="form-section-group">
                                    <h3 className="section-title">3. Filing Identity</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label>Email ID (Portal)</label>
                                            <input
                                                type="email"
                                                placeholder="portal@example.com"
                                                value={createForm.email_id}
                                                onChange={e => setCreateForm({ ...createForm, email_id: e.target.value })}
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label>Username</label>
                                            <input
                                                type="text"
                                                placeholder="GST Username"
                                                value={createForm.username}
                                                onChange={e => setCreateForm({ ...createForm, username: e.target.value })}
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label>Password (Internal)</label>
                                            <div style={{ position: 'relative' }}>
                                                <input
                                                    type={showPassword ? "text" : "password"}
                                                    placeholder="Leave blank to keep current"
                                                    value={createForm.password}
                                                    onChange={e => setCreateForm({ ...createForm, password: e.target.value })}
                                                    style={{ paddingRight: '40px' }}
                                                />
                                                <button
                                                    type="button"
                                                    onClick={() => setShowPassword(!showPassword)}
                                                    style={{
                                                        position: 'absolute',
                                                        top: '50%',
                                                        transform: 'translateY(-50%)',
                                                        right: '12px',
                                                        background: 'transparent',
                                                        border: 'none',
                                                        color: 'var(--text-primary)',
                                                        cursor: 'pointer',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        padding: '4px'
                                                    }}
                                                >
                                                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 4: ASSIGNMENT & COMPLIANCE */}
                                <div className="form-section-group">
                                    <h3 className="section-title">4. Assignment & Compliance</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label>Priority</label>
                                            <FormCustomSelect
                                                name="priority"
                                                value={createForm.priority}
                                                onChange={(e) => setCreateForm({ ...createForm, priority: e.target.value })}
                                                options={optionsFromConfigOnly([
                                                    { value: 'LOW', label: 'Low' },
                                                    { value: 'NORMAL', label: 'Normal' },
                                                    { value: 'HIGH', label: 'High' },
                                                ])}
                                                placeholder="Priority"
                                                ariaLabel="Priority"
                                            />
                                        </div>
                                        {editingFiling && (
                                        <div className="form-group-v4">
                                            <label>Filing Status</label>
                                            <FormCustomSelect
                                                name="status"
                                                value={createForm.status}
                                                onChange={(e) => setCreateForm({ ...createForm, status: e.target.value })}
                                                options={optionsFromPairs(gstFilingStatusOptions(false))}
                                                placeholder="Filing status"
                                                ariaLabel="Filing status"
                                            />
                                        </div>
                                        )}
                                        {showRmField && (
                                        <div className="form-group-v4">
                                            <label>Relationship Manager (RM)</label>
                                            <FormCustomSelect
                                                name="rm_id"
                                                value={createForm.rm_id}
                                                onChange={(e) => setCreateForm({ ...createForm, rm_id: e.target.value })}
                                                options={optionsFromPairs(buildRmOpSelectOptions(configs.activeRMs, { id: editingFiling?.rm_id }), 'Select RM')}
                                                placeholder="Select RM"
                                                ariaLabel="Relationship manager"
                                            />
                                        </div>
                                        )}
                                        {showOpField && (
                                        <div className="form-group-v4">
                                            <label>Operations Personnel (Ops)</label>
                                            <FormCustomSelect
                                                name="op_id"
                                                value={createForm.op_id}
                                                onChange={(e) => setCreateForm({ ...createForm, op_id: e.target.value })}
                                                options={optionsFromPairs(buildRmOpSelectOptions(configs.activeOps, { id: editingFiling?.op_id }), 'Select Ops')}
                                                placeholder="Select Ops"
                                                ariaLabel="Operations personnel"
                                            />
                                        </div>
                                        )}
                                        <div className="form-group-v4 checkbox-group-v4">
                                            <label className="checkbox-label">
                                                <input
                                                    type="checkbox"
                                                    checked={createForm.rule14a}
                                                    onChange={e => setCreateForm({ ...createForm, rule14a: e.target.checked })}
                                                />
                                                <span>Rule 14A Applicable</span>
                                            </label>
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 5: BUSINESS & REMARKS */}
                                <div className="form-section-group">
                                    <h3 className="section-title">5. Business & Remarks</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label>Business Name (Override)</label>
                                            <input
                                                type="text"
                                                placeholder="Custom business name"
                                                value={createForm.business_name}
                                                onChange={e => setCreateForm({ ...createForm, business_name: e.target.value })}
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label>Business Type</label>
                                            <FormCustomSelect
                                                name="business_type"
                                                value={createForm.business_type}
                                                onChange={(e) => setCreateForm({ ...createForm, business_type: e.target.value })}
                                                options={optionsFromConfig(configs.businessTypes, 'Select Business Type')}
                                                placeholder="Select Business Type"
                                                ariaLabel="Business type"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label>Rent Amount</label>
                                            <input
                                                type="number"
                                                placeholder="Monthly Rent"
                                                value={createForm.rent}
                                                onChange={e => setCreateForm({ ...createForm, rent: e.target.value })}
                                            />
                                        </div>
                                    </div>

                                    <div className="form-grid-2" style={{ marginTop: '24px' }}>
                                        <div className="form-group-v4">
                                            <label>Business Description</label>
                                            <div style={{ position: 'relative' }}>
                                                <textarea
                                                    placeholder="Briefly describe the business activities..."
                                                    value={createForm.business_description}
                                                    onChange={e => setCreateForm({ ...createForm, business_description: e.target.value })}
                                                    disabled={aiLoading}
                                                    style={{ paddingRight: '40px' }}
                                                ></textarea>
                                                <button
                                                    type="button"
                                                    onClick={handleGenerateDescription}
                                                    disabled={aiLoading || !createForm.business_name}
                                                    title={!createForm.business_name ? "Enter business name first" : "Generate professional description"}
                                                    style={{
                                                        position: 'absolute',
                                                        top: '50%',
                                                        transform: 'translateY(-50%)',
                                                        right: '12px',
                                                        background: 'transparent',
                                                        border: 'none',
                                                        color: 'var(--accent)',
                                                        cursor: aiLoading || !createForm.business_name ? 'not-allowed' : 'pointer',
                                                        opacity: aiLoading || !createForm.business_name ? 0.5 : 1,
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'center',
                                                        padding: '4px'
                                                    }}
                                                >
                                                    {aiLoading ? <RotateCcw size={16} className="refresh-spin" /> : <Sparkles size={16} />}
                                                </button>
                                            </div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label>Remarks</label>
                                            <textarea
                                                placeholder="Internal notes or special instructions..."
                                                value={createForm.remarks}
                                                onChange={e => setCreateForm({ ...createForm, remarks: e.target.value })}
                                            ></textarea>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer-v4">
                                <div className="footer-actions-v4">
                                    <button type="button" className="btn-cancel-v4" onClick={handleCloseCreateModal}>Cancel</button>
                                    <button type="submit" className="btn-submit-v4" disabled={formLoading}>
                                        {formLoading ? <RotateCcw size={13} className="refresh-spin" /> : null}
                                        {formLoading ? 'Processing...' : (editingFiling ? 'Update Filing' : 'Create Filing')}
                                    </button>
                                </div>
                            </div>
                        </form>
                        </div>
                    </div>
                )}

            {/* Hoisted Status Update Modal (centered to webpage) */}
            {selectedReturnForStatus && (
                <div className="gst-modal-overlay-v4 app-side-drawer-mode" style={{ zIndex: 10000 }} onClick={handleCloseStatusModal}>
                    <div className="gst-modal-card-v4 returns-status-modal app-drawer-panel gst-reg-side-drawer-shell" onClick={(e) => e.stopPropagation()}>
                        <div className="modal-header-v4">
                            <div className="header-content-v4">
                                <div className="header-icon-box-v4" style={{ background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--info)', borderColor: 'rgba(var(--info-rgb), 0.2)' }}>
                                    <Sparkles size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <div className="modal-header-texts">
                                        <h2 className="modal-title-v4">Update Return Status</h2>
                                        <div className="modal-context-badge" style={{ marginTop: '4px' }}>
                                            <span className="context-label">Filing ID</span>
                                            <span className="context-value">{selectedReturnForStatus.gst_filing_id || selectedReturnForStatus.id}</span>
                                            <div style={{ width: '1px', height: '12px', background: 'rgba(var(--fg-rgb),0.1)', margin: '0 8px' }}></div>
                                            <span className="context-label">GSTIN</span>
                                            <span className="context-value">{selectedReturnForStatus.gstin || 'No GSTIN'}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <button className="btn-drawer-close" onClick={handleCloseStatusModal}>
                                <X size={20} />
                            </button>
                        </div>

                        <form onSubmit={handleStatusSubmit} className="modal-form-v4">
                            {statusUpdateError && (
                                <div className="modal-alert-v4" style={{ margin: '20px 24px 0 24px' }}>
                                    <AlertCircle size={18} className="alert-icon" />
                                    <div className="alert-content-v4">
                                        <span className="alert-title">Update Failed</span>
                                        <span className="alert-message">{statusUpdateError}</span>
                                    </div>
                                </div>
                            )}

                            <div className="form-scroll-container">
                                <div className="returns-status-grid">
                                    {[
                                        { field: 'gstr1_status', label: 'GSTR-1' },
                                        { field: 'gstr3b_status', label: 'GSTR-3B' },
                                        { field: 'cmp08_status', label: 'CMP-08' },
                                        { field: 'gstr4_status', label: 'GSTR-4' },
                                        { field: 'gstr9_status', label: 'Annual (GSTR-9)' },
                                        { field: 'gstr9c_status', label: 'Annual (GSTR-9C)' }
                                    ].map(({ field, label }) => {
                                        const applicable = Boolean(selectedReturnForStatus[`${field.split('_')[0]}_status`] || selectedReturnForStatus[`${field.split('_')[0]}_due_date`]);
                                        return (
                                            <div key={field} className={`returns-status-field ${!applicable ? 'disabled' : ''}`}>
                                                <label className="modal-label-caps">{label}</label>
                                                <FormCustomSelect
                                                    name={field}
                                                    value={statusUpdateForm[field]}
                                                    onChange={(e) => setStatusUpdateForm((prev) => ({ ...prev, [field]: e.target.value }))}
                                                    disabled={!applicable || statusUpdateLoading}
                                                    options={optionsFromPairs(gstReturnDetailEditableStatusOptions(true))}
                                                    placeholder="Select Status"
                                                    ariaLabel={label}
                                                />
                                                {!applicable && (
                                                    <div className="returns-status-hint">Not applicable for this filing</div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            <div className="modal-footer-v4">
                                <button
                                    type="button"
                                    className="btn-cancel-v4"
                                    onClick={handleCloseStatusModal}
                                    disabled={statusUpdateLoading}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="btn-submit-v4"
                                    disabled={statusUpdateLoading}
                                >
                                    {statusUpdateLoading ? <RotateCcw size={16} className="gst-refresh-spin" /> : <CheckCircle size={16} />}
                                    <span>{statusUpdateLoading ? 'Processing...' : 'Save Status Changes'}</span>
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};
