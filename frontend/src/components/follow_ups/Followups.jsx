import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';
import api from '../../utils/api';
import {
    listCustomerServiceFollowups,
    getCustomerServiceFollowupAlerts,
    updateCustomerServiceFollowup,
    fetchCustomerServiceFollowupStats,
    fetchPaymentFollowupStats,
    fetchPaymentFollowupMonthItems,
    fetchCustomerServiceFollowupMonthItems,
    getFollowupActivityBadge,
    matchesFollowupStatFilter,
    listPaymentFollowups,
    getPaymentFollowupAlerts,
    schedulePaymentFollowup,
    updatePaymentFollowup,
    resolvePaymentEntityTypeCode,
    buildFollowupRangeFromDates,
    getFollowupListMeta,
    FOLLOWUP_SCHEDULE_PAGE_SIZE,
    PAYMENT_ENTITY_TYPE_MAP,
} from '../../utils/followupsApi';
import {
    Search,
    Filter,
    AlertCircle,
    ChevronLeft,
    ChevronRight,
    MessageSquare,
    User,
    Loader2,
    X,
    CalendarCheck,
    Calendar,
    Bell,
    Clock,
    History,
    Check,
    CheckCircle,
    CheckCircle2,
    Activity,
    Plus,
    Phone,
    ExternalLink,
    ArrowRight
} from 'lucide-react';
import LoadingOverlay from '../common/LoadingOverlay';
import DataTableLoader from '../common/DataTableLoader';
import './Followups.css';
import { addNotification } from '../../utils/notificationUtils';
import Pagination from '../common/Pagination';
import ModernDateTimePicker from '../common/ModernDateTimePicker';

const SERVICE_TYPE_MAP = {
    'Customer Service': 'CUSTOMER',
    'GST Return': 'GST_FILING',
    'GST Notice': 'GST_NOTICE',
    'Company Registration': 'COMPANY_REGISTRATION',
    'TDS Return': 'TDS_RETURN'
};

const resolveEntityTypeCode = (entityTypeLabel) => {
    if (!entityTypeLabel) return undefined;
    return SERVICE_TYPE_MAP[entityTypeLabel] || entityTypeLabel;
};

const SERVICE_LABEL_MAP = Object.fromEntries(
    Object.entries(SERVICE_TYPE_MAP).map(([label, code]) => [code, label])
);

/**
 * Build YYYY-MM-DD from local calendar parts (no timezone drift).
 */
const toDateKey = (year, monthIndex, day) =>
    `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

/**
 * Safe local YYYY-MM-DD date formatter independent of browser locale or string formatting rules.
 */
const formatLocalDateStr = (dateInput) => {
    if (!dateInput) return '';
    if (typeof dateInput === 'string') {
        const trimmed = dateInput.trim();
        if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
    }
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    return toDateKey(d.getFullYear(), d.getMonth(), d.getDate());
};

const normalizeSelectedDates = (dates = []) =>
    [...new Set(dates.map((d) => formatLocalDateStr(d)).filter(Boolean))];

/**
 * Robust fallback for service types when entity_type is missing
 */
 
const getServiceTypeDisplay = (item) => {
    if (item.entity_type && SERVICE_LABEL_MAP[item.entity_type]) {
        return SERVICE_LABEL_MAP[item.entity_type];
    }

    // Fallback based on service name heuristics
    const name = (item.service_name || '').toUpperCase();
    if (name.includes('GST')) return 'GST Return';
    if (name.includes('TDS')) return 'TDS Return';
    if (name.includes('NOTICE')) return 'GST Notice';
    if (name.includes('COMPANY')) return 'Company Reg';

    return item.entity_type || 'Service';
};

 
const Followups = ({ isAdmin, profileData, setToastMessage }) => {
    const [searchParams, setSearchParams] = useSearchParams();

    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filtering, setFiltering] = useState(false);
    const [activeFollowupCategory, setActiveFollowupCategory] = useState(() => {
        const cat = new URLSearchParams(window.location.search).get('category');
        return cat === 'payments' ? 'payments' : 'services';
    });
     
    const [error, setError] = useState(null);

    const [page, setPage] = useState(1);
    const limit = 20;

    const [filters, setFilters] = useState({
        today_only: false,
        is_overdue: false,
        status: '',
        search: ''
    });

    const [showFilterModal, setShowFilterModal] = useState(false);
     
    const [showCalendar, setShowCalendar] = useState(false);
    const [selectedDates, setSelectedDates] = useState(() => [formatLocalDateStr(new Date())]); // Default: Today selected
    const [calendarViewDate, setCalendarViewDate] = useState(new Date());
    const [followupCounts, setFollowupCounts] = useState({}); // { date: total }
    const [dailyStats, setDailyStats] = useState({}); // { date: { pending, total } }

    const [dashboardStats, setDashboardStats] = useState({
        scheduledToday: 0,
        overduePendingToday: 0,
        overdueCompletedToday: 0,
        completedToday: 0,
        pendingToday: 0,
        successRate: 100
    });
    const [statsLoading, setStatsLoading] = useState(false);

    const [updatingStatusId, setUpdatingStatusId] = useState(null);
    const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
    const [alertsData, setAlertsData] = useState([]);
    const [loadingAlerts, setLoadingAlerts] = useState(false);
    const [recentActivities, setRecentActivities] = useState([]);
    const [schedulePage, setSchedulePage] = useState(1);
    const [scheduleHasMore, setScheduleHasMore] = useState(false);
    const [scheduleTotal, setScheduleTotal] = useState(null);
    const [scheduleLoading, setScheduleLoading] = useState(false);

    const [selectedCalendarDate, setSelectedCalendarDate] = useState(null);
    const [debouncedSearch, setDebouncedSearch] = useState(filters.search);
    const [activeStatFilter, setActiveStatFilter] = useState('ALL');

    // Debounce search effect
    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedSearch(filters.search);
        }, 500);
        return () => clearTimeout(timer);
    }, [filters.search]);

    // Reset filters and page when active category changes
    useEffect(() => {
        const todayStr = formatLocalDateStr(new Date());
        setSelectedDates([todayStr]);
        setPage(1);
        setFilters({
            today_only: false,
            is_overdue: false,
            status: '',
            search: ''
        });
        setActiveStatFilter('ALL');
        setSchedulePage(1);
    }, [activeFollowupCategory]);

    // Reset stat filter when selected dates change
    useEffect(() => {
        setActiveStatFilter('ALL');
        setSchedulePage(1);
    }, [selectedDates]);

    // Completion Modal State
    const [showCompleteModal, setShowCompleteModal] = useState(false);
     
    const [loadingTaskHistoryId, setLoadingTaskHistoryId] = useState(null);
    const [selectedTask, setSelectedTask] = useState(null);
    const [taskHistory, setTaskHistory] = useState([]);
    const [loadingHistory, setLoadingHistory] = useState(false);
    const [completionRemark, setCompletionRemark] = useState('Completed');

    // Details Side Drawer State
    const [selectedDetailTask, setSelectedDetailTask] = useState(null);
    const [showDetailDrawer, setShowDetailDrawer] = useState(false);

    // History Drawer State
     
    const [showHistoryDrawer, setShowHistoryDrawer] = useState(false);
    const [selectedHistoryTask, setSelectedHistoryTask] = useState(null);
    const [detailedHistory, setDetailedHistory] = useState([]);
    const [loadingDetailedHistory, setLoadingDetailedHistory] = useState(false);

    // Add Payment Follow-up State
    const [showAddPaymentFollowup, setShowAddPaymentFollowup] = useState(false);
    const [pendingPayments, setPendingPayments] = useState([]);
    const [loadingPendingPayments, setLoadingPendingPayments] = useState(false);
    const [newPaymentFollowup, setNewPaymentFollowup] = useState({
        payment_id: '',
        followup_at: '',
        remarks: ''
    });
    const [savingPaymentFollowup, setSavingPaymentFollowup] = useState(false);
    const [addPaymentFollowupError, setAddPaymentFollowupError] = useState(null);

    const calendarRef = useRef(null);
    const filterRef = useRef(null);
    const alertsRef = useRef(null);
    const completeModalRef = useRef(null);
    const historyDrawerRef = useRef(null);
    const lastProcessedTaskIdRef = useRef(null);
    const dataRef = useRef(data);

    const switchFollowupCategory = React.useCallback((category) => {
        setActiveFollowupCategory(category);
        setFilters((prev) => ({ ...prev, entity_type: '' }));

        const newParams = new URLSearchParams(searchParams);
        newParams.set('category', category);
        newParams.delete('complete_task_id');
        setSearchParams(newParams, { replace: true });

        lastProcessedTaskIdRef.current = null;
        setShowDetailDrawer(false);
        setShowCompleteModal(false);
        setSelectedDetailTask(null);
        setSelectedTask(null);
    }, [searchParams, setSearchParams]);

    // Sync dataRef whenever data changes to allow stable handleRedirection
    useEffect(() => {
        dataRef.current = data;
    }, [data]);

    const formatDate = (dateStr) => {
        if (!dateStr) return '-';
        const date = new Date(dateStr);
        return date.toLocaleString('en-IN', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };



    const normalizeFollowupItem = React.useCallback((item, category) => {
        const status = item.followup_status || item.status || 'PENDING';
        if (category === 'payments') {
            let label = 'Payment';
            if (item.entity_type === 'GST_FILING') label = 'GST Filing Payment';
            else if (item.entity_type === 'GST_FILING_RETURN_DETAILS') label = 'GST Return Payment';
            else if (item.entity_type === 'CUSTOMER_SERVICE') label = 'Service Payment';

            const displayLabel = item.amount ? `${label} (₹${item.amount})` : label;

            return {
                ...item,
                status,
                service_name: displayLabel,
                assigned_to_name: item.rm_name || item.op_name || 'System',
                customer_service_id: item.entity_id || item.id,
            };
        } else {
            return {
                ...item,
                status,
                service_name: item.service_name || 'Customer Service',
                assigned_to_name: item.rm_first_name || item.op_first_name || 'System',
                customer_service_id: item.customer_service_id || item.id,
            };
        }
    }, []);

    const fetchAlerts = React.useCallback(async () => {
        setLoadingAlerts(true);
        try {
            if (activeFollowupCategory === 'payments') {
                const alertsRes = await getPaymentFollowupAlerts();
                const mapped = (alertsRes.data.data || [])
                    .map(item => normalizeFollowupItem(item, 'payments'))
                    .sort((a, b) => new Date(a.followup_at) - new Date(b.followup_at));
                setAlertsData(mapped);
            } else {
                const alertsRes = await getCustomerServiceFollowupAlerts();
                const mappedAlerts = (alertsRes.data.data || [])
                    .map(item => normalizeFollowupItem(item, 'services'))
                    .sort((a, b) => new Date(a.followup_at) - new Date(b.followup_at));
                setAlertsData(mappedAlerts);
            }
        } catch (err) {
            console.error("Error fetching alerts:", err);
        } finally {
            setLoadingAlerts(false);
        }
    }, [activeFollowupCategory, normalizeFollowupItem]);

    const fetchPendingPaymentsForDropdown = React.useCallback(async () => {
        setLoadingPendingPayments(true);
        setAddPaymentFollowupError(null);
        try {
            const response = await api.get('/api/v1/payments/dynamic_filter?payment_status=PENDING&limit=100&include_inactive=false');
            const list = response.data?.data || [];
            const validTypes = ['GST_FILING', 'GST_FILING_RETURN_DETAILS', 'CUSTOMER_SERVICE'];
            const filtered = list.filter(p => p.is_active && validTypes.includes(p.entity_type));
            setPendingPayments(filtered);
        } catch (err) {
            console.error("Failed to fetch pending payments for dropdown:", err);
            setAddPaymentFollowupError("Failed to fetch eligible pending payments. Please try again.");
        } finally {
            setLoadingPendingPayments(false);
        }
    }, []);

    useEffect(() => {
        if (showAddPaymentFollowup) {
            fetchPendingPaymentsForDropdown();
            // Reset form when opened
            setNewPaymentFollowup({
                payment_id: '',
                followup_at: '',
                remarks: ''
            });
            setAddPaymentFollowupError(null);
        }
    }, [showAddPaymentFollowup, fetchPendingPaymentsForDropdown]);

    const fetchRecentActivities = React.useCallback(async () => {
        setScheduleLoading(true);
        try {
            const dateKeys = selectedDates?.length
                ? selectedDates
                : [formatLocalDateStr(new Date())];
            const { followup_from, followup_to } = buildFollowupRangeFromDates(dateKeys);

            const params = {
                limit: FOLLOWUP_SCHEDULE_PAGE_SIZE,
                offset: (schedulePage - 1) * FOLLOWUP_SCHEDULE_PAGE_SIZE,
                followup_from,
                followup_to,
            };

            if (activeFollowupCategory === 'services' && filters.entity_type) {
                if (SERVICE_TYPE_MAP[filters.entity_type]) {
                    params.service_code = SERVICE_TYPE_MAP[filters.entity_type];
                }
            } else if (activeFollowupCategory === 'payments' && filters.entity_type) {
                params.entity_type = resolvePaymentEntityTypeCode(filters.entity_type);
            }

            const mapListParams = (baseParams) => {
                const listParams = { ...baseParams };
                if (listParams.followup_from) {
                    listParams.from_date = listParams.followup_from;
                    delete listParams.followup_from;
                }
                if (listParams.followup_to) {
                    listParams.to_date = listParams.followup_to;
                    delete listParams.followup_to;
                }
                return listParams;
            };

            let rawData = [];
            let meta = { total: null, hasMore: false };
            if (activeFollowupCategory === 'payments') {
                const response = await listPaymentFollowups(mapListParams(params));
                meta = getFollowupListMeta(response, FOLLOWUP_SCHEDULE_PAGE_SIZE);
                rawData = meta.rows;
            } else {
                const response = await listCustomerServiceFollowups(mapListParams(params));
                meta = getFollowupListMeta(response, FOLLOWUP_SCHEDULE_PAGE_SIZE);
                rawData = meta.rows;
            }

            setScheduleTotal(meta.total);
            setScheduleHasMore(meta.hasMore);

            let mapped = rawData.map(item => normalizeFollowupItem(item, activeFollowupCategory));

            mapped.sort((a, b) => new Date(a.followup_at) - new Date(b.followup_at));

            const formatted = mapped.map(act => ({
                id: act.id,
                activity_type: act.status,
                performed_at: act.followup_at,
                completed_at: act.completed_at,
                missed_at: act.missed_at,
                lead_id: act.customer_service_id || act.id,
                call_status_code: act.status,
                remarks: act.remarks || '',
                service_name: act.service_name || 'Customer Service',
                mobile: act.mobile || '',
                full_name: act.full_name || '',
                customer_id: act.customer_id || '',
                originalItem: act
            }));

            setRecentActivities(formatted);
        } catch (err) {
            console.error("[Followups] fetchRecentActivities failed:", {
                category: activeFollowupCategory,
                selectedDates,
                status: err?.response?.status,
                detail: err?.response?.data?.detail || err?.message
            });
            setRecentActivities([]);
            setScheduleHasMore(false);
            setScheduleTotal(null);
        } finally {
            setScheduleLoading(false);
        }
    }, [selectedDates, activeFollowupCategory, filters.entity_type, schedulePage, normalizeFollowupItem]);

    const refreshDashboardStats = React.useCallback(async () => {
        const dates = selectedDates?.length ? selectedDates : [formatLocalDateStr(new Date())];

        setStatsLoading(true);
        try {
            if (activeFollowupCategory === 'services') {
                const serviceCode = filters.entity_type && SERVICE_TYPE_MAP[filters.entity_type]
                    ? SERVICE_TYPE_MAP[filters.entity_type]
                    : undefined;
                const stats = await fetchCustomerServiceFollowupStats({
                    selectedDates: dates,
                    serviceCode,
                });
                setDashboardStats(stats);
                return;
            }

            const stats = await fetchPaymentFollowupStats({
                selectedDates: dates,
                entityType: filters.entity_type,
            });
            setDashboardStats(stats);
        } catch (err) {
            console.error('[Followups] refreshDashboardStats failed:', err);
        } finally {
            setStatsLoading(false);
        }
    }, [selectedDates, activeFollowupCategory, filters.entity_type, normalizeFollowupItem]);

    const fetchMonthlyCounts = React.useCallback(async () => {
        try {
            const year = calendarViewDate.getFullYear();
            const month = calendarViewDate.getMonth() + 1;
            const startDate = `${year}-${String(month).padStart(2, '0')}-01`;
            const endDate = `${year}-${String(month).padStart(2, '0')}-${new Date(year, month, 0).getDate()}`;

            if (activeFollowupCategory === 'payments') {
                const allItemsRaw = await fetchPaymentFollowupMonthItems({
                    year: calendarViewDate.getFullYear(),
                    monthIndex: calendarViewDate.getMonth(),
                    entityType: filters.entity_type,
                });
                const allItems = allItemsRaw.map(item => normalizeFollowupItem(item, 'payments'));

                const countMap = {};
                const statsMap = {};

                allItems.forEach(item => {
                    const itemDate = formatLocalDateStr(item.followup_at);
                    countMap[itemDate] = (countMap[itemDate] || 0) + 1;

                    if (!statsMap[itemDate]) statsMap[itemDate] = { pending: 0, total: 0 };
                    statsMap[itemDate].total += 1;

                    const isPending = item.status === 'PENDING' || item.status === 'MISSED';
                    if (isPending) {
                        statsMap[itemDate].pending += 1;
                    }
                });

                setFollowupCounts(countMap);
                setDailyStats(statsMap);
            } else {
                const serviceCode = filters.entity_type && SERVICE_TYPE_MAP[filters.entity_type]
                    ? SERVICE_TYPE_MAP[filters.entity_type]
                    : undefined;
                const allItemsRaw = await fetchCustomerServiceFollowupMonthItems({
                    year: calendarViewDate.getFullYear(),
                    monthIndex: calendarViewDate.getMonth(),
                    serviceCode,
                });
                const allItems = allItemsRaw.map(item => normalizeFollowupItem(item, 'services'));

                const countMap = {};
                const statsMap = {};

                allItems.forEach(item => {
                    const itemDate = formatLocalDateStr(item.followup_at);
                    countMap[itemDate] = (countMap[itemDate] || 0) + 1;

                    if (!statsMap[itemDate]) statsMap[itemDate] = { pending: 0, total: 0 };
                    statsMap[itemDate].total += 1;

                    const isPending = item.status === 'PENDING' || item.status === 'MISSED';
                    if (isPending) {
                        statsMap[itemDate].pending += 1;
                    }
                });

                setFollowupCounts(countMap);
                setDailyStats(statsMap);
            }
        } catch (err) {
            console.error("Error fetching counts:", err);
        }
    }, [calendarViewDate, activeFollowupCategory, filters.entity_type, normalizeFollowupItem]);

    const fetchFollowups = React.useCallback(async (isFilter = false) => {
        if (isFilter) setFiltering(true);
        else setLoading(true);

        try {
            const params = {
                limit: (selectedDates && selectedDates.length > 0) ? 100 : limit,
                offset: (page - 1) * limit,
                ...filters,
                search: debouncedSearch,
            };

            // Map frontend entity_type filter to backend service_code query parameter only for services
            if (params.entity_type) {
                if (activeFollowupCategory === 'services') {
                    if (SERVICE_TYPE_MAP[params.entity_type]) {
                        params.service_code = SERVICE_TYPE_MAP[params.entity_type];
                    }
                    delete params.entity_type;
                }
            }

            const localNow = new Date();
            const startOfToday = new Date(localNow.getFullYear(), localNow.getMonth(), localNow.getDate(), 0, 0, 0);
            const endOfToday = new Date(localNow.getFullYear(), localNow.getMonth(), localNow.getDate(), 23, 59, 59, 999);

            const startOfTodayISO = startOfToday.toISOString();
            const endOfTodayISO = endOfToday.toISOString();

            if (selectedDates && selectedDates.length > 0) {
                params.dates = selectedDates.join(',');
                // "Overdue" is a derived state, not a stored status. Translate it to
                // PENDING/MISSED so the backend (which only accepts
                // PENDING/COMPLETED/MISSED) doesn't 400 when a date is also selected.
                if (params.status === 'OVERDUE' || filters.is_overdue) {
                    params.statuses = ['PENDING', 'MISSED'];
                    delete params.status;
                }
                delete params.today_only;
                delete params.is_overdue;
                delete params.followup_from;
                delete params.followup_to;
            } else if (filters.today_only) {
                params.followup_from = startOfTodayISO;
                params.followup_to = endOfTodayISO;
                params.statuses = ['PENDING', 'MISSED'];
                delete params.status;
                delete params.today_only;
                delete params.is_overdue;
            } else if (filters.is_overdue || filters.status === 'OVERDUE') {
                params.followup_from = '2025-01-01T00:00:00.000Z';
                params.followup_to = startOfTodayISO;
                params.statuses = ['PENDING', 'MISSED'];
                delete params.status;
                delete params.is_overdue;
                delete params.today_only;
            } else if (filters.status === 'PENDING') {
                params.followup_from = startOfTodayISO;
                params.statuses = ['PENDING', 'MISSED'];
                delete params.status;
                delete params.is_overdue;
                delete params.today_only;
            }

            Object.keys(params).forEach(key => {
                const val = params[key];
                if (val === '' || val === false || val === null || val === undefined) {
                    delete params[key];
                }
            });

            const queryParams = new URLSearchParams();
            Object.keys(params).forEach(key => {
                const value = params[key];
                if (Array.isArray(value)) {
                    value.forEach(v => queryParams.append(key, v));
                } else {
                    queryParams.append(key, value);
                }
            });

            console.log("[Followups] Query Params:", queryParams.toString());

            let fetchedData = [];
            if (activeFollowupCategory === 'services') {
                const listParams = Object.fromEntries(queryParams.entries());
                // Object.fromEntries collapses duplicate keys to the last value, which drops
                // 'PENDING' from a multi-value statuses filter (e.g. ['PENDING','MISSED']).
                const statusesArr = queryParams.getAll('statuses');
                if (statusesArr.length > 1) listParams.statuses = statusesArr;
                Object.keys(listParams).forEach((key) => {
                    if (listParams[key] === 'true') listParams[key] = true;
                    if (listParams[key] === 'false') listParams[key] = false;
                });
                if (listParams.dates) {
                    const sortedDates = listParams.dates.split(',').sort();
                    const [sYear, sMonth, sDay] = sortedDates[0].split('-').map(Number);
                    listParams.from_date = new Date(sYear, sMonth - 1, sDay, 0, 0, 0).toISOString();
                    const [eYear, eMonth, eDay] = sortedDates[sortedDates.length - 1].split('-').map(Number);
                    listParams.to_date = new Date(eYear, eMonth - 1, eDay, 23, 59, 59, 999).toISOString();
                    delete listParams.dates;
                }
                if (listParams.followup_from) {
                    listParams.from_date = listParams.followup_from;
                    delete listParams.followup_from;
                }
                if (listParams.followup_to) {
                    listParams.to_date = listParams.followup_to;
                    delete listParams.followup_to;
                }

                const response = await listCustomerServiceFollowups(listParams);
                fetchedData = (response.data.data || []).map(item => normalizeFollowupItem(item, 'services'));

                if (selectedDates && selectedDates.length > 0) {
                    fetchedData = fetchedData.filter(item =>
                        selectedDates.includes(formatLocalDateStr(item.followup_at))
                    );
                }

                const searchTerm = (debouncedSearch || '').trim().toLowerCase();
                if (searchTerm) {
                    fetchedData = fetchedData.filter((item) => {
                        const haystack = [
                            item.full_name,
                            item.mobile,
                            item.service_name,
                            item.service_code,
                            item.remarks,
                            String(item.customer_service_id ?? item.id ?? ''),
                        ]
                            .filter(Boolean)
                            .join(' ')
                            .toLowerCase();
                        return haystack.includes(searchTerm);
                    });
                }
            } else {
                const listParams = Object.fromEntries(queryParams.entries());
                // Object.fromEntries collapses duplicate keys to the last value, which drops
                // 'PENDING' from a multi-value statuses filter (e.g. ['PENDING','MISSED']).
                const statusesArr = queryParams.getAll('statuses');
                if (statusesArr.length > 1) listParams.statuses = statusesArr;
                Object.keys(listParams).forEach((key) => {
                    if (listParams[key] === 'true') listParams[key] = true;
                    if (listParams[key] === 'false') listParams[key] = false;
                });
                if (listParams.dates) {
                    const sortedDates = listParams.dates.split(',').sort();
                    const [sYear, sMonth, sDay] = sortedDates[0].split('-').map(Number);
                    listParams.from_date = new Date(sYear, sMonth - 1, sDay, 0, 0, 0).toISOString();
                    const [eYear, eMonth, eDay] = sortedDates[sortedDates.length - 1].split('-').map(Number);
                    listParams.to_date = new Date(eYear, eMonth - 1, eDay, 23, 59, 59, 999).toISOString();
                    delete listParams.dates;
                }
                if (listParams.followup_from) {
                    listParams.from_date = listParams.followup_from;
                    delete listParams.followup_from;
                }
                if (listParams.followup_to) {
                    listParams.to_date = listParams.followup_to;
                    delete listParams.followup_to;
                }
                if (listParams.entity_type) {
                    listParams.entity_type = resolvePaymentEntityTypeCode(listParams.entity_type);
                }

                const response = await listPaymentFollowups(listParams);
                fetchedData = (response.data.data || []).map(item => normalizeFollowupItem(item, 'payments'));

                if (selectedDates && selectedDates.length > 0) {
                    fetchedData = fetchedData.filter(item =>
                        selectedDates.includes(formatLocalDateStr(item.followup_at))
                    );
                }

                const searchTerm = (debouncedSearch || '').trim().toLowerCase();
                if (searchTerm) {
                    fetchedData = fetchedData.filter((item) => {
                        const haystack = [
                            item.full_name,
                            item.mobile,
                            item.service_name,
                            item.entity_type,
                            item.remarks,
                            String(item.id ?? ''),
                        ]
                            .filter(Boolean)
                            .join(' ')
                            .toLowerCase();
                        return haystack.includes(searchTerm);
                    });
                }
            }

            setData(fetchedData);
            setError(null);
        } catch (err) {
            console.error("Error fetching follow-ups:", err);
            setError("Failed to load follow-ups. Please try again.");
        } finally {
            setLoading(false);
            setTimeout(() => setFiltering(false), 300);
        }
    }, [page, filters, debouncedSearch, selectedDates, limit, activeFollowupCategory, normalizeFollowupItem]);

    useEffect(() => {
        fetchRecentActivities();
    }, [selectedDates, activeFollowupCategory, filters.entity_type, schedulePage, fetchRecentActivities]);

    useEffect(() => {
        refreshDashboardStats();
    }, [refreshDashboardStats]);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (calendarRef.current && !calendarRef.current.contains(event.target)) {
                setShowCalendar(false);
            }
            if (filterRef.current && !filterRef.current.contains(event.target)) {
                setShowFilterModal(false);
            }
            if (alertsRef.current && !alertsRef.current.contains(event.target)) {
                setShowAlertsDrawer(false);
            }
            if (completeModalRef.current && !completeModalRef.current.contains(event.target)) {
                setShowCompleteModal(false);
            }
            if (historyDrawerRef.current && !historyDrawerRef.current.contains(event.target)) {
                setShowHistoryDrawer(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Listen for global follow-up updates (from other tabs like Customer Services)
    useEffect(() => {
        const handleGlobalUpdate = () => {
            console.log("[Followups] Caught global update event. Refreshing...");
            fetchAlerts();
            fetchMonthlyCounts();
            fetchRecentActivities();
            refreshDashboardStats();
        };

        window.addEventListener('st_followups_updated', handleGlobalUpdate);
        return () => window.removeEventListener('st_followups_updated', handleGlobalUpdate);
    }, [fetchAlerts, fetchMonthlyCounts, fetchRecentActivities, refreshDashboardStats]);

    useEffect(() => {
        fetchMonthlyCounts();
        fetchAlerts();
        fetchRecentActivities();
        refreshDashboardStats();

        // TIME RESONANCE FIX: Polling every 60 seconds to match the exact beat of the backend schedular.py
        // This ensures cards auto-refresh silently in the background exactly when the 10-minute grace period expires
        const pollInterval = setInterval(() => {
            fetchMonthlyCounts();
            fetchAlerts();
            refreshDashboardStats();
        }, 60000);

        return () => clearInterval(pollInterval);
    }, [calendarViewDate, fetchMonthlyCounts, fetchAlerts, fetchRecentActivities, refreshDashboardStats]);

    const fetchTaskHistory = React.useCallback(async (task) => {
        setLoadingHistory(true);
        try {
            if (activeFollowupCategory === 'payments') {
                const response = await listPaymentFollowups({ payment_id: task.id });
                const list = (response.data.data || []).map(item => normalizeFollowupItem(item, 'payments'));
                setTaskHistory(list);
            } else {
                const csId = task.customer_service_id || task.id;
                const response = await listCustomerServiceFollowups({ customer_service_id: csId });
                const list = (response.data.data || []).map(item => normalizeFollowupItem(item, 'services'));
                setTaskHistory(list);
            }
        } catch (err) {
            console.error("Error fetching task history:", err);
        } finally {
            setLoadingHistory(false);
        }
    }, [activeFollowupCategory, normalizeFollowupItem]);

     
    const fetchDetailedHistory = React.useCallback(async (task) => {
        setLoadingDetailedHistory(true);
        setLoadingTaskHistoryId(task.id);
        setDetailedHistory([]);
        try {
            const minWait = new Promise(resolve => setTimeout(resolve, 400));

            let list = [];
            if (activeFollowupCategory === 'payments') {
                const response = await listPaymentFollowups({ payment_id: task.id });
                list = (response.data.data || []).map(item => normalizeFollowupItem(item, 'payments'));
            } else {
                const csId = task.customer_service_id || task.id;
                const [response] = await Promise.all([
                    listCustomerServiceFollowups({ customer_service_id: csId }),
                    minWait,
                ]);
                list = (response.data.data || []).map(item => normalizeFollowupItem(item, 'services'));
            }

            const historyData = list.sort((a, b) => new Date(b.followup_at) - new Date(a.followup_at));
            setDetailedHistory(historyData);
        } catch (err) {
            console.error("Error fetching detailed history:", err);
        } finally {
            setLoadingDetailedHistory(false);
            setLoadingTaskHistoryId(null);
        }
    }, [activeFollowupCategory, normalizeFollowupItem]);

    // --- Hybrid Redirection System (Bullseye Final Fix) ---
    // Core function to fetch and open the UI (Atomic and State-Aware)
    const handleRedirection = React.useCallback(async (taskId, mode = 'URL', forcedCategory = null) => {
        if (!taskId) return;

        // Guard for URL mode to prevent mount/re-render loops
        if (mode === 'URL' && lastProcessedTaskIdRef.current === taskId) return;
        lastProcessedTaskIdRef.current = taskId;

        const currentCategory = forcedCategory || searchParams.get('category') || activeFollowupCategory;

        console.log(`[Followups Redirection] Level-1 Trigger: ${mode} for Task ${taskId} (Category: ${currentCategory})`);
        setLoadingTaskHistoryId(taskId);

        try {
            // Self-sufficient task lookup from API (Bypass local view uncertainty)
            console.log(`[Followups Redirection] Fetching fresh data for UI synchronization...`);
            let rawTask;
            if (currentCategory === 'payments') {
                const response = await listPaymentFollowups({ payment_id: taskId });
                rawTask = response.data.data?.[0];
            } else {
                const response = await listCustomerServiceFollowups({ customer_service_id: taskId });
                rawTask = response.data.data?.[0];
            }
            const task = rawTask ? normalizeFollowupItem(rawTask, currentCategory) : null;

            if (task) {
                console.log(`[Followups Redirection] Task Found! (Status: ${task.status}). Opening details drawer...`);

                window.requestAnimationFrame(async () => {
                    const minWait = new Promise(resolve => setTimeout(resolve, 400));
                    setSelectedDetailTask(task);
                    setShowDetailDrawer(true);
                    setShowCompleteModal(false);
                    setSelectedTask(null);
                    await minWait;
                });
            } else {
                console.warn(`[Followups Redirection] Task ${taskId} not found on server.`);
            }
        } catch (err) {
            console.error("[Followups Redirection] Atomic processing failed:", err);
            lastProcessedTaskIdRef.current = null;
        } finally {
            setLoadingTaskHistoryId(null);
        }
    }, [activeFollowupCategory, normalizeFollowupItem, fetchTaskHistory, searchParams]);

    // --- Cleanup Logic (Sticky Sync) ---
    const closeCompleteModal = React.useCallback(() => {
        setShowCompleteModal(false);
        setSelectedTask(null);
        // Sync URL: Remove taskId ONLY when UI is actually closed
        const params = new URLSearchParams(window.location.search);
        if (params.has('complete_task_id')) {
            const newParams = new URLSearchParams(searchParams);
            newParams.delete('complete_task_id');
            setSearchParams(newParams, { replace: true });
        }
    }, [searchParams, setSearchParams]);

    const closeHistoryDrawer = React.useCallback(() => {
        setShowHistoryDrawer(false);
        setSelectedHistoryTask(null);
        // Sync URL: Remove taskId ONLY when UI is actually closed
        const params = new URLSearchParams(window.location.search);
        if (params.has('complete_task_id')) {
            const newParams = new URLSearchParams(searchParams);
            newParams.delete('complete_task_id');
            setSearchParams(newParams, { replace: true });
        }
    }, [searchParams, setSearchParams]);

    const closeDetailDrawer = React.useCallback(() => {
        setShowDetailDrawer(false);
        setSelectedDetailTask(null);
        // Sync URL: Remove taskId ONLY when UI is actually closed
        const params = new URLSearchParams(window.location.search);
        if (params.has('complete_task_id')) {
            const newParams = new URLSearchParams(searchParams);
            newParams.delete('complete_task_id');
            setSearchParams(newParams, { replace: true });
        }
    }, [searchParams, setSearchParams]);

    // Listener 1: URL Parameters (For Refresh / Mount)
    useEffect(() => {
        const taskId = searchParams.get('complete_task_id');
        const cat = searchParams.get('category');
        if (cat === 'services' || cat === 'payments') {
            setActiveFollowupCategory(cat);
        }
        if (taskId) {
            handleRedirection(taskId, 'URL');
        } else {
            // Reset guard to allow future clicks for the same ID to re-trigger URL logic on mount 
            lastProcessedTaskIdRef.current = null;
        }
    }, [searchParams, handleRedirection]);

    // Listener 2: Global Signal (For Live Clicks - ZERO GUARD FORCE OPEN)
    useEffect(() => {
        const onOpenFollowup = (event) => {
            const taskId = event.detail?.taskId;
            const category = event.detail?.category;
            if (taskId) {
                console.log(`[Followups] FORCE SIGNAL RECEIVED for Task ${taskId} (Category: ${category})`);
                if (category && (category === 'services' || category === 'payments')) {
                    setActiveFollowupCategory(category);
                }
                // Use 'EVENT' mode to bypass guards and force an open every time a click happens
                handleRedirection(taskId, 'EVENT', category);
            }
        };

        window.addEventListener('st_open_followup', onOpenFollowup);
        return () => window.removeEventListener('st_open_followup', onOpenFollowup);
    }, [handleRedirection]);




    const toggleSelectedDate = React.useCallback((dateKey) => {
        const key = formatLocalDateStr(dateKey);
        if (!key) return;

        setSelectedDates((prev) => {
            const normalized = normalizeSelectedDates(prev);
            if (normalized.includes(key)) {
                return normalized.filter((d) => d !== key);
            }
            return [...normalized, key];
        });
        setPage(1);
    }, []);

    const renderFilterDrawer = () => {
        // CANCELLED has no backend equivalent (domain is PENDING/COMPLETED/MISSED),
        // so it could never return results — omitted. OVERDUE is a derived state
        // translated to PENDING+MISSED in fetchFollowups.
        const statuses = ['PENDING', 'OVERDUE', 'COMPLETED'];
        const serviceEntityTypes = Object.keys(SERVICE_TYPE_MAP);
        const isPaymentsTab = activeFollowupCategory === 'payments';

        return (
            <>
                <div className="filter-drawer-overlay" onClick={() => setShowFilterModal(false)} />
                <div className="followups-filter-drawer" ref={filterRef} onClick={e => e.stopPropagation()}>
                    <div className="calendar-drawer-header">
                        <h2><Filter size={20} /> Filter Tasks</h2>
                        <button className="btn-close-drawer" onClick={() => setShowFilterModal(false)}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="calendar-drawer-body">
                        <div className="filter-section">
                            <label className="section-label">Task Status</label>
                            <div className="filter-chip-group">
                                {statuses.map(s => (
                                    <button
                                        key={s}
                                        className={`filter-chip ${filters.status === s ? 'active' : ''}`}
                                        onClick={() => setFilters({
                                            ...filters,
                                            status: filters.status === s ? '' : s,
                                            is_overdue: false, // Selected status chip overrides urgency toggles for clarity
                                            today_only: false
                                        })}
                                    >
                                        {s}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="filter-section">
                            <label className="section-label">{isPaymentsTab ? 'Payment Type' : 'Service Type'}</label>
                            <div className="filter-chip-group">
                                {isPaymentsTab ? (
                                    Object.entries(PAYMENT_ENTITY_TYPE_MAP).map(([label, code]) => (
                                        <button
                                            key={code}
                                            className={`filter-chip ${filters.entity_type === code ? 'active' : ''}`}
                                            onClick={() => setFilters({ ...filters, entity_type: filters.entity_type === code ? '' : code })}
                                        >
                                            {label}
                                        </button>
                                    ))
                                ) : (
                                    serviceEntityTypes.map((t) => (
                                        <button
                                            key={t}
                                            className={`filter-chip ${filters.entity_type === t ? 'active' : ''}`}
                                            onClick={() => setFilters({ ...filters, entity_type: filters.entity_type === t ? '' : t })}
                                        >
                                            {t}
                                        </button>
                                    ))
                                )}
                            </div>
                        </div>

                        <div className="filter-section urgency-section">
                            <label className="section-label">Urgency & Timing</label>
                            <div className="toggle-group-v2">
                                <label className="toggle-item-v2">
                                    <input
                                        type="checkbox"
                                        checked={filters.today_only}
                                        onChange={e => setFilters({ ...filters, today_only: e.target.checked, is_overdue: false })}
                                    />
                                    <span className="toggle-label-v2">Only Due Today</span>
                                    <div className="toggle-switch-v2"></div>
                                </label>
                                <label className="toggle-item-v2">
                                    <input
                                        type="checkbox"
                                        checked={filters.is_overdue}
                                        onChange={e => setFilters({ ...filters, is_overdue: e.target.checked, today_only: false })}
                                    />
                                    <span className="toggle-label-v2">Only Overdue</span>
                                    <div className="toggle-switch-v2"></div>
                                </label>
                            </div>
                        </div>

                    </div>

                    <div className="drawer-footer">
                        <button className="btn-drawer-reset" onClick={() => {
                            setFilters({
                                today_only: false,
                                is_overdue: false,
                                status: '',
                                search: ''
                            });
                            setSelectedDates([]);
                            setShowFilterModal(false);
                        }}>Reset All</button>
                        <button className="btn-drawer-today" onClick={() => {
                            setShowFilterModal(false);
                        }}>Apply Filters</button>
                    </div>
                </div>
            </>
        );
    };

    const handleCreatePaymentFollowup = async (e) => {
        if (e) e.preventDefault();

        // Strict Validation
        if (!newPaymentFollowup.payment_id) {
            setAddPaymentFollowupError("Please select a pending payment.");
            return;
        }
        if (!newPaymentFollowup.followup_at) {
            setAddPaymentFollowupError("Please select a follow-up Date & Time.");
            return;
        }
        if (!newPaymentFollowup.remarks?.trim()) {
            setAddPaymentFollowupError("Please enter follow-up remarks/notes.");
            return;
        }

        const selectedPayment = pendingPayments.find(p => String(p.id) === String(newPaymentFollowup.payment_id));

        setSavingPaymentFollowup(true);
        setAddPaymentFollowupError(null);

        try {
            await schedulePaymentFollowup({
                payment_id: parseInt(newPaymentFollowup.payment_id),
                followup_at: newPaymentFollowup.followup_at,
                remarks: newPaymentFollowup.remarks
            });

            // Reset state
            setNewPaymentFollowup({
                payment_id: '',
                followup_at: '',
                remarks: ''
            });
            setShowAddPaymentFollowup(false);

            // Refetch data
            setSchedulePage(1);
            await Promise.all([
                fetchMonthlyCounts(),
                fetchRecentActivities(),
                refreshDashboardStats(),
                fetchAlerts(),
            ]);

            // High-Fidelity Global Toast (consistent with general followups)
            window.dispatchEvent(new CustomEvent('st_show_toast', {
                detail: {
                    message: `Payment follow-up added successfully for ID ${newPaymentFollowup.payment_id}.`,
                    action: { label: 'Dismiss' },
                    variant: 'success'
                }
            }));

            // Add notification for activity feed
            addNotification(
                'Payment Follow-up Created',
                `Added payment follow-up for Payment ID ${newPaymentFollowup.payment_id} (${selectedPayment?.full_name || 'Client'}).`,
                'CREATE',
                { label: 'View Follow-ups', path: `/dashboard?tab=dashboard&sub=followups` }
            );

            // Trigger global refresh for alerts and dashboard metrics
            window.dispatchEvent(new Event('st_followups_updated'));
        } catch (err) {
            console.error("Create payment followup error:", err);
            const errorData = err.response?.data?.detail;
            let errorMessage = "Failed to add payment follow-up";

            if (typeof errorData === 'string') {
                errorMessage = errorData;
            } else if (Array.isArray(errorData)) {
                errorMessage = errorData.map(e => e.msg).join(", ");
            } else if (errorData?.msg) {
                errorMessage = errorData.msg;
            } else if (errorData?.error?.message) {
                errorMessage = errorData.error.message;
            } else {
                errorMessage = err.message || errorMessage;
            }

            setAddPaymentFollowupError(errorMessage);
        } finally {
            setSavingPaymentFollowup(false);
        }
    };

    const renderAddPaymentFollowupDrawer = () => {
        return (
            <>
                <div className="filter-drawer-overlay" style={{ zIndex: 1999 }} onClick={() => setShowAddPaymentFollowup(false)} />
                <div className="followups-filter-drawer followups-payment-drawer" style={{ zIndex: 2000 }} onClick={e => e.stopPropagation()}>
                    <div className="calendar-drawer-header">
                        <h2><CalendarCheck size={20} /> Add Payment Followup</h2>
                        <button className="btn-close-drawer" onClick={() => setShowAddPaymentFollowup(false)}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="calendar-drawer-body">
                        {addPaymentFollowupError && (
                            <div className="inlay-error" style={{ margin: '0 0 16px 0', padding: '10px 12px', background: 'rgba(var(--danger-rgb), 0.1)', border: '1px solid rgba(var(--danger-rgb), 0.2)', borderRadius: '6px', color: 'var(--danger)', fontSize: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span>{addPaymentFollowupError}</span>
                                <button style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '14px' }} onClick={() => setAddPaymentFollowupError(null)}>&times;</button>
                            </div>
                        )}

                        <form onSubmit={handleCreatePaymentFollowup} className="inlay-form" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div className="form-field">
                                <label style={{ color: 'var(--text-primary)', fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px', display: 'block' }}>Select Pending Payment</label>
                                {loadingPendingPayments ? (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-primary)', fontSize: '13px', padding: '10px', background: 'rgba(var(--fg-rgb), 0.02)', border: '1px solid rgba(var(--fg-rgb),0.05)', borderRadius: '6px' }}>
                                        <Loader2 size={14} className="spin" />
                                        <span>Loading pending payments...</span>
                                    </div>
                                ) : pendingPayments.length === 0 ? (
                                    <div style={{ color: 'var(--text-primary)', fontSize: '13px', padding: '10px', background: 'rgba(var(--fg-rgb), 0.02)', border: '1px solid rgba(var(--fg-rgb),0.05)', borderRadius: '6px' }}>
                                        No active pending payments found.
                                    </div>
                                ) : (
                                    <div className="input-with-icon" style={{ position: 'relative' }}>
                                        <select
                                            value={newPaymentFollowup.payment_id}
                                            onChange={e => setNewPaymentFollowup({ ...newPaymentFollowup, payment_id: e.target.value })}
                                            style={{ width: '100%', background: 'var(--bg-input)', border: '1px solid rgba(var(--fg-rgb), 0.08)', borderRadius: '6px', color: 'var(--text-primary)', padding: '10px 12px', fontSize: '13px', outline: 'none' }}
                                        >
                                            <option value="">-- Choose Pending Payment --</option>
                                            {pendingPayments.map(p => (
                                                <option key={p.id} value={p.id}>
                                                    {p.id} - {p.full_name} ({p.entity_type.replace('_', ' ')}) - ₹{p.remaining_amount ? p.remaining_amount.toFixed(2) : p.net_amount.toFixed(2)} remaining
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                )}
                            </div>

                            <div className="form-field">
                                <label style={{ color: 'var(--text-primary)', fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px', display: 'block' }}>Date & Time</label>
                                <ModernDateTimePicker
                                    value={newPaymentFollowup.followup_at}
                                    onChange={val => setNewPaymentFollowup({ ...newPaymentFollowup, followup_at: val })}
                                    placeholder="When to follow up?"
                                />
                            </div>

                            <div className="form-field">
                                <label style={{ color: 'var(--text-primary)', fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px', display: 'block' }}>Remarks / Notes</label>
                                <textarea
                                    placeholder="Enter details about this follow-up..."
                                    value={newPaymentFollowup.remarks}
                                    onChange={e => setNewPaymentFollowup({ ...newPaymentFollowup, remarks: e.target.value })}
                                    style={{ width: '100%', minHeight: '100px', background: 'var(--bg-input)', border: '1px solid rgba(var(--fg-rgb), 0.08)', borderRadius: '6px', color: 'var(--text-primary)', padding: '10px 12px', fontSize: '13px', outline: 'none', resize: 'vertical' }}
                                />
                            </div>
                        </form>
                    </div>

                    <div className="drawer-footer">
                        <button className="btn-drawer-reset" style={{ flex: 1 }} onClick={() => setShowAddPaymentFollowup(false)}>Cancel</button>
                        <button
                            className="btn-drawer-today"
                            style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
                            onClick={handleCreatePaymentFollowup}
                            disabled={savingPaymentFollowup || !newPaymentFollowup.payment_id || !newPaymentFollowup.followup_at || !newPaymentFollowup.remarks?.trim()}
                        >
                            {savingPaymentFollowup ? <Loader2 size={14} className="spin" /> : null}
                            <span>{savingPaymentFollowup ? 'Adding...' : 'Add Follow-up'}</span>
                        </button>
                    </div>
                </div>
            </>
        );
    };

    const renderStatsGrid = () => {
        const {
            scheduledToday = 0,
            overduePendingToday = 0,
            overdueCompletedToday = 0,
            completedToday = 0,
            pendingToday = 0,
            successRate = 100
        } = dashboardStats || {};

        const dates = selectedDates?.length ? selectedDates : [formatLocalDateStr(new Date())];
        const todayStr = formatLocalDateStr(new Date());
        const statsPeriodLabel = (() => {
            if (dates.length === 1 && dates[0] === todayStr) return 'TODAY';
            if (dates.length === 1) {
                const [y, m, d] = dates[0].split('-').map(Number);
                return new Date(y, m - 1, d).toLocaleDateString(undefined, {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                }).toUpperCase();
            }
            return `${dates.length} SELECTED DATES`;
        })();

        const stats = [
            {
                label: 'Scheduled',
                value: scheduledToday,
                icon: <Calendar size={20} />,
                color: 'var(--info)',
                desc: `SCHEDULED ${statsPeriodLabel}`,
                type: 'SCHEDULED'
            },
            {
                label: 'Overdue (Pending)',
                value: overduePendingToday,
                icon: <AlertCircle size={20} />,
                color: 'var(--danger)',
                desc: `OVERDUE PENDING ${statsPeriodLabel}`,
                type: 'OVERDUE_PENDING'
            },
            {
                label: 'Overdue (Completed)',
                value: overdueCompletedToday,
                icon: <CheckCircle2 size={20} />,
                color: 'var(--warning)',
                desc: `OVERDUE COMPLETED ${statsPeriodLabel}`,
                type: 'OVERDUE_COMPLETED'
            },
            {
                label: 'Completed (On-time)',
                value: completedToday,
                icon: <CheckCircle size={20} />,
                color: 'var(--accent)',
                desc: `COMPLETED ${statsPeriodLabel}`,
                type: 'COMPLETED'
            },
            {
                label: 'Pending (Urgent)',
                value: pendingToday,
                icon: <Clock size={20} />,
                color: 'var(--warning)',
                desc: `PENDING ${statsPeriodLabel}`,
                type: 'PENDING'
            },
            {
                label: 'Success Rate',
                value: `${successRate}%`,
                icon: <Activity size={20} />,
                color: 'var(--success)',
                desc: statsPeriodLabel === 'TODAY' ? 'SUCCESS RATE TODAY' : `SUCCESS RATE (${statsPeriodLabel})`,
                type: null
            },
        ];

        return (
            <div className="stats-grid-v4">
                {stats.map((s, i) => (
                    <div
                        key={i}
                        className={`stat-card-premium ${activeStatFilter === s.type ? 'active' : ''}`}
                        style={{ 
                            '--accent-color': s.color,
                            cursor: s.type ? 'pointer' : 'default',
                            border: activeStatFilter === s.type ? `1.5px solid ${s.color}` : '1px solid var(--border)',
                            boxShadow: activeStatFilter === s.type ? 'var(--shadow-md)' : 'var(--shadow-sm)',
                            transform: activeStatFilter === s.type ? 'translateY(-2px)' : 'none',
                            transition: 'all 0.3s cubic-bezier(0.165, 0.84, 0.44, 1)'
                        }}
                        title={s.desc}
                        onClick={() => {
                            if (s.type) {
                                setActiveStatFilter(activeStatFilter === s.type ? 'ALL' : s.type);
                            }
                        }}
                    >
                        <div className="stat-icon-wrap" style={{ color: s.color }}>
                            {s.icon}
                        </div>
                        <div className="stat-content-v5">
                            <span className="stat-value-v5">
                                {statsLoading ? (
                                    <div className="skeleton-pulse" style={{ height: '24px', width: '50px', borderRadius: '4px' }} />
                                ) : (
                                    s.value
                                )}
                            </span>
                            <span className="stat-label-v5">{s.label}</span>
                        </div>
                    </div>
                ))}
            </div>
        );
    };

    const renderAlertsDrawer = () => {
        const activeItems = alertsData.filter(item => item.status === 'PENDING' || item.status === 'MISSED');
        const now = new Date();
        const todayStart = new Date(now).setHours(0, 0, 0, 0);
        const todayEnd = new Date(now).setHours(23, 59, 59, 999);

        const todayPending = activeItems.filter(item => {
            const fDate = new Date(item.followup_at).getTime();
            return fDate >= todayStart && fDate <= todayEnd;
        });
        const pastOverdue = activeItems.filter(item => {
            const fDate = new Date(item.followup_at).getTime();
            return fDate < todayStart;
        });

        return (
            <>
                <div className="alerts-drawer-overlay" onClick={() => setShowAlertsDrawer(false)} />
                <div className="followups-alerts-drawer" ref={alertsRef} onClick={e => e.stopPropagation()}>
                    <div className="calendar-drawer-header">
                        <h2><Bell size={24} /> Task Insights</h2>
                        <button className="btn-close-drawer" onClick={() => setShowAlertsDrawer(false)}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="calendar-drawer-body">
                        <div className="insights-stats-grid-v4">
                            <div className="insight-card-v4 today">
                                <div className="insight-icon-wrap">
                                    <CalendarCheck size={14} />
                                </div>
                                <div className="insight-content">
                                    <span className="insight-value">{todayPending.length}</span>
                                    <span className="insight-label">PENDING TODAY</span>
                                </div>
                            </div>
                            <div className="insight-card-v4 urgent">
                                <div className="insight-icon-wrap">
                                    <AlertCircle size={16} />
                                </div>
                                <div className="insight-content">
                                    <span className="insight-value">{pastOverdue.length}</span>
                                    <span className="insight-label">URGENT (PAST DUE)</span>
                                </div>
                            </div>
                        </div>

                        {loadingAlerts ? (
                            <div className="inlay-loading-centered" style={{ padding: '40px 0' }}>
                                <Loader2 size={32} className="spin" />
                                <span style={{ fontSize: '12px', color: 'var(--text-primary)' }}>Syncing Alerts...</span>
                            </div>
                        ) : alertsData.length === 0 ? (
                            <div className="inlay-empty" style={{ padding: '60px 0' }}>
                                <Bell size={48} style={{ opacity: 0.1, marginBottom: '16px' }} />
                                <p style={{ color: 'var(--text-primary)', fontSize: '14px' }}>No pending tasks for today.</p>
                            </div>
                        ) : (
                            <div className="alerts-scroll-list">
                                {alertsData.map(item => (
                                    <div key={item.id} className={`alert-task-card ${new Date(item.followup_at) < new Date() ? 'is-overdue' : ''}`}>
                                        <div className="card-top">
                                            <span className="task-time">
                                                <Clock size={12} />
                                                {new Date(item.followup_at).toLocaleDateString('en-IN', { weekday: 'short', month: 'short', day: 'numeric' })} | {new Date(item.followup_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                                            </span>
                                            <span className="task-id">{item.customer_id}</span>
                                        </div>
                                        <div className="task-main">
                                            <h4 className="service-name">{item.service_name}</h4>
                                            <p className="task-remarks">{item.remarks}</p>
                                        </div>
                                        <div className="card-actions">
                                            <button
                                                className={`btn-alert-action ${updatingStatusId === item.id ? 'loading' : ''}`}
                                                disabled={updatingStatusId === item.id}
                                                onClick={() => {
                                                    setSelectedTask(item);
                                                    setShowCompleteModal(true);
                                                    fetchTaskHistory(item);
                                                }}
                                            >
                                                {updatingStatusId === item.id ? (
                                                    <Loader2 size={14} className="spin" />
                                                ) : (
                                                    <>
                                                        <CalendarCheck size={14} />
                                                        <span>Complete</span>
                                                    </>
                                                )}
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="drawer-footer">
                        <button className="btn-drawer-reset" style={{ flex: 1 }} onClick={() => setShowAlertsDrawer(false)}>Close Panel</button>
                        <button className="btn-drawer-today" style={{ flex: 1 }} onClick={fetchAlerts}>Refresh Alerts</button>
                    </div>
                </div>
            </>
        );
    };

     
    const renderHistoryDrawer = (closeHandler = closeHistoryDrawer) => {
        if (!selectedHistoryTask) return null;

        return (
            <>
                <div className="history-drawer-overlay" onClick={closeHandler} />
                <div className="followups-history-drawer" ref={historyDrawerRef}>
                    <div className="calendar-drawer-header">
                        <div className="drawer-header-content">
                            <div>
                                <h2 className="header-with-icon">
                                    <Clock size={20} className="icon-muted" style={{ marginRight: '12px' }} />
                                    Follow-up History
                                </h2>
                                <p className="drawer-task-identity">
                                    <span className="task-id-pill">{selectedHistoryTask.id}</span>
                                    <span className="task-service-text">{selectedHistoryTask.service_name}</span>
                                </p>
                            </div>
                        </div>
                        <button className="btn-close-drawer" onClick={closeHandler}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="drawer-body-v2">
                        {loadingDetailedHistory ? (
                            <div className="drawer-loading-area">
                                <Loader2 size={32} className="spin" />
                                <p>Retrieving interaction logs...</p>
                            </div>
                        ) : detailedHistory.length === 0 ? (
                            <div className="drawer-empty-area">
                                <History size={48} style={{ opacity: 0.1, marginBottom: '16px' }} />
                                <p>No history records found for this service.</p>
                            </div>
                        ) : (
                            <div className="audit-timeline">
                                {detailedHistory.map((item, index) => (
                                    <div key={item.id} className="audit-item">
                                        <div className="audit-marker">
                                            <div className="marker-dot"></div>
                                            {index !== detailedHistory.length - 1 && <div className="marker-line"></div>}
                                        </div>
                                        <div className="audit-content-card">
                                            <div className="audit-meta">
                                                <span className="audit-date">{formatDate(item.followup_at)}</span>
                                                <span className={`status-pill ${item.status.toLowerCase()}`}>{item.status}</span>
                                            </div>
                                            <div className="audit-remarks-box-v2">
                                                {item.remarks && item.remarks.includes('\n[COMPLETED]: ') ? (
                                                    <div className="remarks-split">
                                                        <div className="remark-sub-section">
                                                            <span className="remark-sub-label">Original Instruction</span>
                                                            <p className="actual-remark">{item.remarks.split('\n[COMPLETED]: ')[0]}</p>
                                                        </div>
                                                        <div className="remark-sub-section outcome">
                                                            <span className="remark-sub-label">Completion Outcome</span>
                                                            <p className="actual-remark">{item.remarks.split('\n[COMPLETED]: ')[1]}</p>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <>
                                                        <MessageSquare size={12} className="remarks-icon" />
                                                        <p className="actual-remark">{item.remarks || 'No remarks provided'}</p>
                                                    </>
                                                )}
                                            </div>
                                            <div className="audit-assignee">
                                                <User size={10} />
                                                <span>{item.assigned_to_name || 'System'}</span>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="drawer-footer">
                        <button className="btn-drawer-close-v2" onClick={closeHandler}>Close History</button>
                    </div>
                </div>
            </>
        );
    };

    const renderCalendarDrawer = React.useCallback(() => {
        const year = calendarViewDate.getFullYear();
        const month = calendarViewDate.getMonth();
        const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();

        const days = [];
        for (let i = 0; i < firstDay; i++) days.push(<div key={`empty-${i}`} className="cal-day empty"></div>);
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = toDateKey(year, month, d);
            const count = followupCounts[dateStr] || 0;
            const isSelected = normalizeSelectedDates(selectedDates).includes(dateStr);
            // const isToday = formatLocalDateStr(new Date()) === dateStr;

            days.push(
                <div
                    key={d}
                    className={`cal-day ${isSelected ? 'selected' : ''}`}
                    onClick={() => toggleSelectedDate(dateStr)}
                >
                    <span className="day-num">{d}</span>
                    {count > 0 && <span className="task-count-pill">{count}</span>}
                </div>
            );
        }

        const totalMonthTasks = Object.values(followupCounts).reduce((a, b) => a + b, 0);

        // Date-specific insights - show latest or aggregated?
        // Let's show for the most recently selected date if multiple
        // const activeInsightsDate = selectedDates.length > 0 ? selectedDates[selectedDates.length - 1] : null;
        // const selectedDateStats = activeInsightsDate ? (dailyStats[activeInsightsDate] || { pending: 0, total: 0 }) : null;

        return (
            <>
                <div className="calendar-drawer-overlay" onClick={() => setShowCalendar(false)} />
                <div
                    className="followups-calendar-drawer"
                    ref={calendarRef}
                    onClick={e => e.stopPropagation()}
                >
                    <div className="calendar-drawer-header">
                        <h2><Calendar size={24} /> Workload Calendar</h2>
                        <button className="btn-close-drawer" onClick={() => setShowCalendar(false)}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="calendar-drawer-body">
                        <div className="drawer-cal-container">
                            <div className="cal-header">
                                <button onClick={() => setCalendarViewDate(new Date(year, month - 1, 1))}><ChevronLeft size={18} /></button>
                                <div>
                                    <span>{monthNames[month]} {year}</span>
                                    <div className="cal-month-summary">Monthly Pulse: <strong>{totalMonthTasks} tasks</strong></div>
                                </div>
                                <button onClick={() => setCalendarViewDate(new Date(year, month + 1, 1))}><ChevronRight size={18} /></button>
                            </div>
                            <div className="cal-weekdays">
                                {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => <span key={d}>{d}</span>)}
                            </div>
                            <div className="cal-grid">
                                {days}
                            </div>
                        </div>

                        <div className="date-insights-scroll-area">
                            {selectedDates.length > 0 ? (
                                [...selectedDates].sort((a, b) => new Date(a) - new Date(b)).map(dateStr => {
                                    const stats = dailyStats[dateStr] || { pending: 0, total: 0 };
                                    return (
                                        <div key={dateStr} className="date-detail-card-v3">
                                            <div className="card-header-mini">
                                                <div className="card-date-pill">
                                                    <Calendar size={12} style={{ marginRight: '6px' }} />
                                                    {new Date(dateStr).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                                                </div>
                                                <button
                                                    className="btn-remove-detail"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setSelectedDates((prev) => normalizeSelectedDates(prev).filter((d) => d !== dateStr));
                                                    }}
                                                >
                                                    <X size={14} />
                                                </button>
                                            </div>

                                            <div className="insights-stats-grid">
                                                <div className="stat-card">
                                                    <span className="stat-label">Pending</span>
                                                    <span className="stat-value">{stats.pending}</span>
                                                </div>
                                                <div className="stat-card">
                                                    <span className="stat-label">Completed</span>
                                                    <span className="stat-value" style={{ color: 'var(--accent)' }}>
                                                        {stats.total - stats.pending}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })
                            ) : (
                                <div className="empty-detail-state">
                                    <Calendar size={32} />
                                    <p>Select dates in the calendar to view daily breakdowns</p>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="drawer-footer">
                        <button className="btn-drawer-reset" onClick={() => {
                            setSelectedDates([]);
                            setShowCalendar(false);
                        }}>Reset Selection</button>
                        <button className="btn-drawer-today" onClick={() => {
                            const today = new Date();
                            setCalendarViewDate(today);
                            const todayStr = formatLocalDateStr(today);
                            if (!normalizeSelectedDates(selectedDates).includes(todayStr)) {
                                setSelectedDates((prev) => [...normalizeSelectedDates(prev), todayStr]);
                            }
                        }}>Mark Today</button>
                    </div>
                </div>
            </>
        );
    }, [calendarViewDate, selectedDates, followupCounts, dailyStats, toggleSelectedDate]);

    const CalendarDrawer = React.useMemo(() => renderCalendarDrawer(), [renderCalendarDrawer]);




    const renderCompleteTaskModal = (closeHandler = closeCompleteModal) => {
        if (!selectedTask) return null;

        const templates = [
            "Documents Received",
            "Call Answered - Discussed",
            "Left Voicemail",
            "Payment Confirmed",
            "Revision Requested",
            "Meeting Scheduled"
        ];

        return (
            <>
                <div className="filter-drawer-overlay" style={{ zIndex: 2000 }} onClick={closeHandler} />
                <div className="followups-complete-modal" ref={completeModalRef}>
                    <div className="modal-header-v2">
                        <div className="header-title-wrap">
                            <CalendarCheck size={24} className="header-icon-glow" />
                            <div>
                                <h2>Complete Follow-up</h2>
                                <p className="drawer-task-identity">
                                    <span className="task-id-pill">{selectedTask.id}</span>
                                    <span className="task-service-text">{selectedTask.service_name}</span>
                                </p>
                            </div>
                        </div>
                        <button className="btn-close-v3" onClick={closeHandler}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="modal-content-grid">
                        <div className="history-sidebar">
                            <div className="sidebar-label">
                                <Clock size={14} className="icon-bright" style={{ marginRight: '8px' }} />
                                <span>Follow-up History</span>
                            </div>

                            {loadingHistory ? (
                                <div className="history-loader">
                                    <Loader2 size={24} className="animate-spin" />
                                </div>
                            ) : taskHistory.length === 0 ? (
                                <div className="history-empty">No previous history found.</div>
                            ) : (
                                <div className="timeline-container">
                                    {taskHistory.map((h) => (
                                        <div key={h.id} className={`timeline-item ${selectedTask?.id === h.id ? 'active' : ''}`}>
                                            <div className="timeline-marker"></div>
                                            <div className="timeline-content">
                                                <div className="timeline-meta">
                                                    <span>{formatDate(h.followup_at)}</span>
                                                    <span className="timeline-status">{h.status}</span>
                                                </div>
                                                {h.remarks && h.remarks.includes('\n[COMPLETED]: ') ? (
                                                    <div className="timeline-remarks-split">
                                                        <div className="sub-remark"><span className="tiny-label">Instr:</span> {h.remarks.split('\n[COMPLETED]: ')[0]}</div>
                                                        <div className="sub-remark outcome"><span className="tiny-label">Outcome:</span> {h.remarks.split('\n[COMPLETED]: ')[1]}</div>
                                                    </div>
                                                ) : (
                                                    <p className="timeline-remark">{h.remarks || 'No remarks'}</p>
                                                )}
                                                <div className="timeline-assignee">
                                                    <User size={10} />
                                                    <span>{h.assigned_to_name || 'System'}</span>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="completion-form">
                            <div className="completion-scroll-area">
                                {selectedTask.remarks && (
                                    <div className="form-section instruction-section">
                                        <label className="input-label instruction-label">
                                            Original Instruction
                                        </label>
                                        <div className="task-instruction-box">
                                            {selectedTask.remarks.includes('\n[COMPLETED]: ') ? (
                                                <div className="remarks-split-simple">
                                                    <div className="instr-part"><strong>Initial:</strong> {selectedTask.remarks.split('\n[COMPLETED]: ')[0]}</div>
                                                    <div className="out-part"><strong>Outcome:</strong> {selectedTask.remarks.split('\n[COMPLETED]: ')[1]}</div>
                                                </div>
                                            ) : (
                                                <span>{selectedTask.remarks}</span>
                                            )}
                                        </div>
                                    </div>
                                )}

                                <div className="form-section">
                                    <label className="input-label">Completion Remark</label>
                                    <textarea
                                        className="remarks-textarea"
                                        placeholder="Enter details about this follow-up..."
                                        value={completionRemark}
                                        onChange={(e) => setCompletionRemark(e.target.value)}
                                    />
                                    <div className="template-chips">
                                        {templates.map(t => (
                                            <button
                                                key={t}
                                                className="template-chip"
                                                onClick={() => setCompletionRemark(t)}
                                            >
                                                {t}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer-v2">
                                <button
                                    className="btn-modal-secondary"
                                    onClick={closeCompleteModal}
                                    disabled={updatingStatusId === selectedTask.id}
                                >
                                    Cancel
                                </button>
                                <button
                                    className={`btn-modal-primary ${updatingStatusId === selectedTask.id ? 'loading' : ''}`}
                                    disabled={updatingStatusId === selectedTask.id}
                                    onClick={() => handleStatusUpdate(selectedTask, 'COMPLETED', completionRemark)}
                                >
                                    {updatingStatusId === selectedTask.id ? (
                                        <><Loader2 size={16} className="animate-spin" /> Confirming...</>
                                    ) : (
                                        <>Confirm Completion</>
                                    )}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </>
        );
    };

    const renderDetailDrawer = () => {
        if (!selectedDetailTask) return null;

        const task = selectedDetailTask;
        const isCompleted = Boolean(task.completed_at);
        const isMissed = task.status === 'MISSED' || (task.missed_at && !task.completed_at);
        const isPending = task.status === 'PENDING';

        const isOnTime = isCompleted && !task.missed_at;
        const isLateCompleted = isCompleted && Boolean(task.missed_at);

        let statusBadgeClass = 'pending';
        let statusText = 'Pending';
        if (isCompleted) {
            statusBadgeClass = isOnTime ? 'completed' : 'late';
            statusText = isLateCompleted ? 'Completed (Late)' : 'Completed (On-Time)';
        } else if (isMissed) {
            statusBadgeClass = 'missed';
            statusText = 'Missed';
        } else if (new Date(task.followup_at) < new Date()) {
            statusBadgeClass = 'overdue';
            statusText = 'Overdue';
        }

        // Parse audit trails
        const initialRemarks = task.remarks && task.remarks.includes('\n[COMPLETED]: ')
            ? task.remarks.split('\n[COMPLETED]: ')[0]
            : task.remarks;

        const completionOutcome = task.remarks && task.remarks.includes('\n[COMPLETED]: ')
            ? task.remarks.split('\n[COMPLETED]: ')[1]
            : null;

        return createPortal(
            <>
                <div className="followups-detail-drawer-overlay" onClick={closeDetailDrawer} />
                <div className="followups-detail-drawer" onClick={e => e.stopPropagation()}>
                    <div className="calendar-drawer-header" style={{ borderBottom: '1px solid rgba(var(--fg-rgb), 0.08)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Activity size={20} className="header-icon-glow" style={{ color: 'var(--accent)' }} />
                            <h2>Follow-up Details</h2>
                        </div>
                        <button className="btn-close-drawer" onClick={closeDetailDrawer}>
                            <X size={20} />
                        </button>
                    </div>

                    <div className="calendar-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '24px 20px', overflowY: 'auto' }}>
                        {/* Status Card */}
                        <div className="detail-section glass-card-v4" style={{ padding: '16px', background: 'rgba(var(--fg-rgb), 0.02)', border: '1px solid var(--border-subtle)', borderRadius: '12px' }}>
                            <span className={`followup-status-badge ${statusBadgeClass}`} style={{ marginBottom: '12px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                {isCompleted ? <Check size={12} /> : (isPending || statusBadgeClass === 'overdue') ? <Clock size={12} /> : null}
                                <span>{statusText}</span>
                            </span>
                            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.4 }}>
                                {task.service_name}
                            </h3>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '12px' }}>
                                <span className="entity-type-badge-v4 company" style={{ background: 'rgba(var(--fg-rgb), 0.05)', color: 'var(--text-muted)', fontSize: '10px' }}>
                                    ID: {task.id}
                                </span>
                                <span className="entity-type-badge-v4 company" style={{ background: 'rgba(var(--fg-rgb), 0.05)', color: 'var(--text-muted)', fontSize: '10px' }}>
                                    Type: {task.entity_type || 'CUSTOMER_SERVICE'}
                                </span>
                                <span className="entity-type-badge-v4 company" style={{ background: 'rgba(var(--fg-rgb), 0.05)', color: 'var(--text-muted)', fontSize: '10px' }}>
                                    Entity ID: {task.entity_id || task.customer_service_id || task.id}
                                </span>
                            </div>
                        </div>

                        {/* Punctuality and Time details */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                            <div className="glass-card-v4" style={{ padding: '12px', background: 'rgba(var(--fg-rgb), 0.03)', border: '1px solid var(--border-subtle)', borderRadius: '10px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '10px', fontWeight: 700, marginBottom: '6px' }}>
                                    <Calendar size={12} style={{ color: 'var(--accent)' }} />
                                    <span>SCHEDULED AT</span>
                                </div>
                                <div style={{ color: 'var(--text-primary)', fontSize: '12px', fontWeight: 600 }}>
                                    {formatDate(task.followup_at)}
                                </div>
                            </div>

                            {isCompleted ? (
                                <div className="glass-card-v4" style={{ padding: '12px', background: 'rgba(var(--fg-rgb), 0.03)', border: '1px solid var(--border-subtle)', borderRadius: '10px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '10px', fontWeight: 700, marginBottom: '6px' }}>
                                        <CheckCircle2 size={12} style={{ color: 'var(--accent)' }} />
                                        <span>COMPLETED AT</span>
                                    </div>
                                    <div style={{ color: 'var(--text-primary)', fontSize: '12px', fontWeight: 600 }}>
                                        {formatDate(task.completed_at)}
                                    </div>
                                </div>
                            ) : (
                                <div className="glass-card-v4" style={{ padding: '12px', background: 'rgba(var(--fg-rgb), 0.03)', border: '1px solid var(--border-subtle)', borderRadius: '10px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '10px', fontWeight: 700, marginBottom: '6px' }}>
                                        <Clock size={12} style={{ color: 'var(--info)' }} />
                                        <span>SLA STATUS</span>
                                    </div>
                                    <div style={{ color: 'var(--info)', fontSize: '12px', fontWeight: 600 }}>
                                        Awaiting Completion
                                    </div>
                                </div>
                            )}

                            {isCompleted && (
                                <div className="glass-card-v4" style={{ gridColumn: 'span 2', padding: '12px', background: 'rgba(var(--fg-rgb), 0.03)', border: '1px solid var(--border-subtle)', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '10px', fontWeight: 700 }}>
                                        <Clock size={12} style={{ color: isOnTime ? 'var(--accent)' : 'var(--warning)' }} />
                                        <span>SLA COMPLIANCE</span>
                                    </div>
                                    <div style={{ color: isOnTime ? 'var(--accent)' : 'var(--warning)', fontSize: '12px', fontWeight: 700 }}>
                                        {isOnTime ? 'SLA Passed (On-Time Completion)' : 'SLA Failed (Late Completion)'}
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Customer profile */}
                        <div className="detail-section" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <label style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>CLIENT INFORMATION</label>
                            <div className="glass-card-v4" style={{ padding: '16px', background: 'rgba(var(--fg-rgb), 0.02)', border: '1px solid var(--border-subtle)', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                    <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>{task.full_name || 'Walk-in Client'}</span>
                                    <span style={{ fontSize: '11px', color: 'var(--text-primary)' }}>Cust ID: {task.customer_id || 'N/A'}</span>
                                    <span style={{ fontSize: '11px', color: 'var(--text-primary)' }}>Phone: {task.mobile || 'No phone registered'}</span>
                                </div>
                                {task.mobile && (
                                    <a href={`tel:${task.mobile}`} className="btn-icon-mini" style={{ background: 'rgba(var(--accent-rgb), 0.1)', color: 'var(--accent)', border: '1px solid rgba(var(--accent-rgb), 0.2)', borderRadius: '50%', padding: '10px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }} title="Call Client">
                                        <Phone size={16} />
                                    </a>
                                )}
                            </div>
                        </div>

                        {/* Assignee Card */}
                        <div className="detail-section" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <label style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>ASSIGNED HANDLER</label>
                            <div className="glass-card-v4" style={{ padding: '12px 16px', background: 'rgba(var(--fg-rgb), 0.02)', border: '1px solid var(--border-subtle)', borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'rgba(var(--accent-rgb), 0.1)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 700, border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                                    {(task.assigned_to_name || 'S').charAt(0).toUpperCase()}
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{task.assigned_to_name || 'System / Unassigned'}</span>
                                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Account Owner</span>
                                </div>
                            </div>
                        </div>

                        {/* Remarks History Category */}
                        {(initialRemarks || completionOutcome) && (
                            <div className="detail-section" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                <label style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase' }}>REMARKS HISTORY</label>
                                <div className="glass-card-v4" style={{ padding: '16px', background: 'rgba(var(--fg-rgb), 0.02)', border: '1px solid var(--border-subtle)', borderRadius: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    {initialRemarks && (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '9px', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
                                                <MessageSquare size={10} />
                                                <span>INITIAL INSTRUCTION</span>
                                            </div>
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5, paddingLeft: '12px', borderLeft: '2px solid rgba(var(--fg-rgb), 0.1)' }}>
                                                {initialRemarks}
                                            </p>
                                        </div>
                                    )}

                                    {initialRemarks && completionOutcome && <div style={{ height: '1px', background: 'rgba(var(--fg-rgb), 0.06)' }} />}

                                    {isCompleted && (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '9px', color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase' }}>
                                                <Check size={10} />
                                                <span>COMPLETION OUTCOME</span>
                                            </div>
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--accent)', lineHeight: 1.5, paddingLeft: '12px', borderLeft: '2px solid var(--accent)' }}>
                                                {completionOutcome || 'Completed successfully.'}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Footer buttons */}
                    {(isPending || isMissed || (!isCompleted && new Date(task.followup_at) < new Date())) && (
                        <div className="calendar-drawer-footer" style={{ borderTop: '1px solid rgba(var(--fg-rgb), 0.08)', padding: '16px 20px', display: 'flex', gap: '10px', background: 'rgba(var(--fg-rgb),0.01)' }}>
                            <button
                                className="btn-modal-primary"
                                style={{ flex: 1, padding: '10px 14px', fontSize: '12px' }}
                                onClick={() => {
                                    setSelectedTask(task);
                                    setShowCompleteModal(true);
                                    fetchTaskHistory(task);
                                    setShowDetailDrawer(false);
                                }}
                            >
                                Complete Now
                            </button>
                        </div>
                    )}
                </div>
            </>,
            document.body
        );
    };

    const handleStatusUpdate = async (task, newStatus, remark = null) => {
        const id = typeof task === 'object' ? task.id : task;
        const originalRemarks = typeof task === 'object' ? task.remarks : '';

        setUpdatingStatusId(id);
        try {
            let finalRemark = remark;
            if (newStatus === 'COMPLETED' && remark) {
                // Preserving audit trail: instruction | outcome
                finalRemark = originalRemarks ? `${originalRemarks}\n[COMPLETED]: ${remark}` : remark;
            } else if (!remark) {
                finalRemark = newStatus === 'COMPLETED' ? 'Completed' : `Status updated to ${newStatus} via dashboard.`;
            }

            if (activeFollowupCategory === 'payments') {
                await updatePaymentFollowup(id, {
                    status: newStatus,
                    remarks: finalRemark
                });
            } else {
                const csId = task?.customer_service_id || task?.id || id;
                await updateCustomerServiceFollowup(csId, {
                    status: newStatus,
                    remarks: finalRemark
                });
            }
            await Promise.all([
                fetchAlerts(),
                fetchMonthlyCounts(),
                fetchRecentActivities(),
                refreshDashboardStats(),
            ]);

            // High-Fidelity Notification Structure (Internal Dashboard Context)
            const typeMap = {
                'CUSTOMER_SERVICE': 'Customer Service',
                'GST_PEOPLE': 'GST People',
                'GST_DOCUMENTS': 'GST Documents'
            };
            const entityTypeLabel = typeMap[task?.entity_type] || task?.entity_type || 'Task';
            const displayEntityId = task?.entity_id || task?.customer_service_id || id;

            const notificationTitle = `Follow-up Completed`;
            const notificationDesc = `${entityTypeLabel} with ID ${displayEntityId} was marked as completed.`;

            // Activity Feed (Notifications Tab)
            addNotification(
                notificationTitle,
                notificationDesc,
                'UPDATE',
            );

            // Trigger global refresh for other components to see this completion
            window.dispatchEvent(new Event('st_followups_updated'));
            setShowCompleteModal(false);
            setCompletionRemark('Completed');
        } catch (err) {
            const errorMsg = err.response?.data?.detail || err.message;
            if (errorMsg.includes("Finalized followup cannot be modified")) {
                await Promise.all([fetchRecentActivities(), fetchAlerts()]);
                setShowCompleteModal(false);
            } else {
                if (setToastMessage) {
                    setToastMessage(`Error: ${errorMsg} ❌`);
                } else {
                    alert("Failed to update status: " + errorMsg);
                }
            }
        } finally {
            setUpdatingStatusId(null);
        }
    };



     
    const getStatusBadge = (item) => {
        if (item.status === 'COMPLETED') {
            const isOnTime = item.completed_at &&
                (new Date(item.completed_at) - new Date(item.followup_at) <= 10 * 60 * 1000);
            if (isOnTime) {
                return <span className="followup-status-badge completed" title="Completed within 10-minute SLA buffer">On-Time</span>;
            } else {
                return <span className="followup-status-badge late" title="Completed after 10-minute SLA buffer">Late</span>;
            }
        }

        const now = new Date();
        const todayStart = new Date();
        todayStart.setHours(0, 0, 0, 0);
        const followupTime = new Date(item.followup_at);

        if (item.status === 'PENDING' || item.status === 'MISSED') {
            if (followupTime < todayStart) {
                // Any uncompleted task from a previous day is "Overdue"
                return <span className="followup-status-badge overdue">Overdue</span>;
            } else if (followupTime < now) {
                // Tasks from today that are past their time are "Missed"
                return <span className="followup-status-badge missed">Missed Today</span>;
            }
            return <span className="followup-status-badge pending">Pending</span>;
        }

        return <span className="followup-status-badge pending">{item.status}</span>;
    };

     
    const renderRemarksCell = (remarks) => {
        if (!remarks) return <span className="text-muted">No remarks provided</span>;

        if (remarks.includes('\n[COMPLETED]: ')) {
            const [instr, outcome] = remarks.split('\n[COMPLETED]: ');
            return (
                <div className="remarks-card-v4">
                    <div className="remark-group">
                        <span className="remark-tag task">TASK</span>
                        <p className="remark-text-v4" title={instr}>{instr}</p>
                    </div>
                    <div className="remark-group outcome">
                        <span className="remark-tag done">DONE</span>
                        <p className="remark-text-v4 bold-green" title={outcome}>{outcome}</p>
                    </div>
                </div>
            );
        }

        return (
            <div className="remarks-card-v4">
                <div className="remark-group">
                    <span className="remark-tag pending">PENDING</span>
                    <p className="remark-text-v4" title={remarks}>{remarks}</p>
                </div>
            </div>
        );
    };


    const renderInlineCalendar = () => {
        const viewYear = calendarViewDate.getFullYear();
        const viewMonth = calendarViewDate.getMonth();
        const currentMonthStr = calendarViewDate.toLocaleString('en-US', { month: 'long', year: 'numeric' });

        const firstDay = new Date(viewYear, viewMonth, 1).getDay();
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

        // Previous month days to fill leading slots
        const prevMonthDate = new Date(viewYear, viewMonth, 0);
        const prevMonthDays = prevMonthDate.getDate();

        // Actual current date to highlight today
        const now = new Date();
        const isCurrentMonth = now.getFullYear() === viewYear && now.getMonth() === viewMonth;
        const today = isCurrentMonth ? now.getDate() : null;

        const handleDateClick = (dayObj) => {
            let year = viewYear;
            let monthIndex = viewMonth;
            let day = dayObj.day;

            if (dayObj.isPastMonth) {
                monthIndex = viewMonth - 1;
                if (monthIndex < 0) {
                    monthIndex = 11;
                    year = viewYear - 1;
                }
                setCalendarViewDate(new Date(year, monthIndex, 1));
            } else if (dayObj.isNextMonth) {
                monthIndex = viewMonth + 1;
                if (monthIndex > 11) {
                    monthIndex = 0;
                    year = viewYear + 1;
                }
                setCalendarViewDate(new Date(year, monthIndex, 1));
            }

            toggleSelectedDate(toDateKey(year, monthIndex, day));
        };

        const days = [];
        // Fill leading slots
        for (let i = firstDay - 1; i >= 0; i--) {
            days.push({
                day: prevMonthDays - i,
                isCurrentMonth: false,
                isPastMonth: true
            });
        }
        // Fill current month slots
        for (let i = 1; i <= daysInMonth; i++) {
            days.push({
                day: i,
                isCurrentMonth: true
            });
        }
        // Fill trailing slots to complete the 6-row (42 cells) premium matrix
        const totalGridSlots = 42;
        const remainingSlots = totalGridSlots - days.length;
        for (let i = 1; i <= remainingSlots; i++) {
            days.push({
                day: i,
                isCurrentMonth: false,
                isNextMonth: true
            });
        }

        return (
            <div className="crm-calendar-widget">
                <div className="calendar-header">
                    <div className="cal-nav-group">
                        <button
                            className="btn-chevron-mini"
                            onClick={(e) => {
                                e.stopPropagation();
                                setCalendarViewDate(new Date(viewYear, viewMonth - 1, 1));
                            }}
                            title="Previous Month"
                        >
                            <ChevronLeft size={14} />
                        </button>
                        <span className="month-name">{currentMonthStr}</span>
                        <button
                            className="btn-chevron-mini"
                            onClick={(e) => {
                                e.stopPropagation();
                                setCalendarViewDate(new Date(viewYear, viewMonth + 1, 1));
                            }}
                            title="Next Month"
                        >
                            <ChevronRight size={14} />
                        </button>
                    </div>
                    <Calendar size={14} className="cal-icon" />
                </div>
                <div className="calendar-grid">
                    {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, index) => <div key={`${d}-${index}`} className="weekday">{d}</div>)}
                    {days.map((dayObj, idx) => {
                        if (!dayObj.isCurrentMonth) {
                            return <div key={idx} className="calendar-day empty" />;
                        }

                        const targetDate = new Date(viewYear, viewMonth, dayObj.day);
                        const dateStr = toDateKey(viewYear, viewMonth, dayObj.day);
                        const isPast = targetDate < new Date(now.getFullYear(), now.getMonth(), now.getDate());
                        const isSelected = normalizeSelectedDates(selectedDates).includes(dateStr);
                        const isToday = dayObj.day === today;
                        const hasFollowups = followupCounts[dateStr] > 0;

                        return (
                            <div
                                key={dateStr}
                                role="button"
                                tabIndex={0}
                                aria-pressed={isSelected}
                                className={`calendar-day ${isToday ? 'today' : ''} ${isSelected ? 'selected' : ''} ${isPast ? 'past' : ''} ${hasFollowups ? 'has-events' : ''}`}
                                onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    handleDateClick(dayObj);
                                }}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        handleDateClick(dayObj);
                                    }
                                }}
                            >
                                {dayObj.day}
                                {hasFollowups && (
                                    <span className="calendar-day-count-badge">
                                        {followupCounts[dateStr]}
                                    </span>
                                )}
                                {hasFollowups && <div className="event-dot" />}
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    };

    const renderActivityFeedSkeleton = () => {
        return (
            <div className="activity-feed-timeline">
                {[...Array(5)].map((_, i) => (
                    <div
                        className="activity-item-v4 premium-bento-card skeleton"
                        key={i}
                        style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px', borderRadius: '14px', background: 'rgba(var(--fg-rgb), 0.03)', border: '1px solid var(--border-subtle)', marginBottom: '8px' }}
                    >
                        {/* Customer Header Skeleton */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <div className="skeleton-pulse" style={{ width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0 }} />
                                <div className="skeleton-pulse" style={{ width: '90px', height: '12px', borderRadius: '4px' }} />
                                <div className="skeleton-pulse" style={{ width: '35px', height: '12px', borderRadius: '4px' }} />
                            </div>
                            <div className="skeleton-pulse" style={{ width: '85px', height: '20px', borderRadius: '20px' }} />
                        </div>

                        {/* Service Details & Status Skeleton */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', gap: '12px', paddingTop: '2px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <div className="skeleton-pulse" style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0 }} />
                                <div className="skeleton-pulse" style={{ width: '130px', height: '12px', borderRadius: '4px' }} />
                                <div className="skeleton-pulse" style={{ width: '40px', height: '12px', borderRadius: '4px' }} />
                            </div>
                            <div className="skeleton-pulse" style={{ width: '95px', height: '16px', borderRadius: '20px' }} />
                        </div>

                        {/* Time Badge row Skeleton */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(var(--fg-rgb),0.01)', border: '1px solid var(--border-subtle)', padding: '6px 10px', borderRadius: '8px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <div className="skeleton-pulse" style={{ width: '12px', height: '12px', borderRadius: '3px' }} />
                                <div className="skeleton-pulse" style={{ width: '110px', height: '11px', borderRadius: '3px' }} />
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <div className="skeleton-pulse" style={{ width: '16px', height: '16px', borderRadius: '50%' }} />
                                <div className="skeleton-pulse" style={{ width: '50px', height: '11px', borderRadius: '3px' }} />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        );
    };

    const renderActivityFeed = () => {
        if (scheduleLoading) {
            return renderActivityFeedSkeleton();
        }

        const filteredActivities = recentActivities.filter((act) => (
            matchesFollowupStatFilter(act, activeStatFilter)
        ));

        return (
            <div className="activity-feed-timeline">
                {filteredActivities.length === 0 ? (
                    <div className="empty-feed">
                        <div className="empty-feed-icon-stack">
                            <div className="empty-feed-icon-bg" />
                            <Calendar size={28} className="empty-feed-icon-main" strokeWidth={1.5} />
                            <Clock size={14} className="empty-feed-icon-sub" />
                        </div>
                        <h4 className="empty-feed-title">No Activities Found</h4>
                        <p className="empty-feed-subtitle">No activities match the selected status.</p>
                    </div>
                ) : (
                    filteredActivities.map((act, i) => {
                        const { statusBadgeClass, statusTextString } = getFollowupActivityBadge(act);
                        const isTaskCompleted = statusBadgeClass === 'ontime' || statusBadgeClass === 'late';

                        return (
                            <div
                                className="activity-item-v4 clickable premium-bento-card"
                                key={act.id || i}
                                style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px', borderRadius: '14px', background: 'rgba(var(--fg-rgb), 0.03)', border: '1px solid var(--border-subtle)', transition: 'all 0.3s ease', marginBottom: '8px' }}
                                onClick={() => {
                                    if (act.originalItem) {
                                        setSelectedDetailTask(act.originalItem);
                                        setShowDetailDrawer(true);
                                    }
                                }}
                            >
                                {/* Customer Header Row */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                                        {/* Avatar */}
                                        <div style={{ width: '22px', height: '22px', borderRadius: '50%', background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--info)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: 700, flexShrink: 0 }}>
                                            {(act.full_name || 'N/A').charAt(0).toUpperCase()}
                                        </div>
                                        {/* Name */}
                                        <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {act.full_name || 'N/A'}
                                        </span>
                                        {/* Cust ID Badge */}
                                        <span style={{ fontSize: '9px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(var(--info-rgb), 0.06)', border: '1px solid rgba(var(--info-rgb), 0.12)', color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontVariantNumeric: 'tabular-nums', fontWeight: 600, flexShrink: 0 }}>
                                            CID {act.customer_id || 'N/A'}
                                        </span>
                                    </div>
                                    {/* Phone Badge / Clickable tel Link */}
                                    {act.mobile ? (
                                        <a
                                            href={`tel:${act.mobile}`}
                                            onClick={(e) => e.stopPropagation()}
                                            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px', fontWeight: 700, color: 'var(--warning)', background: 'rgba(var(--warning-rgb), 0.08)', border: '1px solid rgba(var(--warning-rgb), 0.15)', padding: '3px 8px', borderRadius: '20px', textDecoration: 'none', transition: 'all 0.2s ease' }}
                                            onMouseEnter={(e) => {
                                                e.currentTarget.style.background = 'rgba(var(--warning-rgb), 0.15)';
                                                e.currentTarget.style.boxShadow = '0 0 8px rgba(var(--warning-rgb), 0.2)';
                                            }}
                                            onMouseLeave={(e) => {
                                                e.currentTarget.style.background = 'rgba(var(--warning-rgb), 0.08)';
                                                e.currentTarget.style.boxShadow = 'none';
                                            }}
                                        >
                                            <Phone size={10} style={{ flexShrink: 0 }} />
                                            <span>{act.mobile}</span>
                                        </a>
                                    ) : (
                                        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No Phone</span>
                                    )}
                                </div>

                                {/* Service Details & Status Row */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', gap: '12px', paddingTop: '2px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                                        <div className={`timeline-indicator-dot ${statusBadgeClass}`} style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0 }} />
                                        <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.01em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {act.service_name}
                                        </span>
                                        <span style={{ fontSize: '9px', padding: '2px 5px', borderRadius: '4px', background: 'rgba(var(--fg-rgb), 0.04)', border: '1px solid rgba(var(--fg-rgb), 0.08)', color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
                                            {act.lead_id}
                                        </span>
                                    </div>
                                    <span className={`timeline-status-badge ${statusBadgeClass}`} style={{ fontSize: '9px', fontWeight: 800, padding: '3px 8px', borderRadius: '20px', letterSpacing: '0.03em', whiteSpace: 'nowrap', flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                        {isTaskCompleted ? <Check size={10} /> : (statusBadgeClass === 'pending' || statusBadgeClass === 'overdue') ? <Clock size={10} /> : null}
                                        <span>{statusTextString}</span>
                                    </span>
                                </div>

                                {/* Time Badge row */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(var(--fg-rgb),0.01)', border: '1px solid var(--border-subtle)', padding: '6px 10px', borderRadius: '8px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--info)', fontSize: '11px', fontWeight: 600 }}>
                                        <Calendar size={12} />
                                        <span>{formatDate(act.performed_at)}</span>
                                    </div>
                                    {act.originalItem?.assigned_to_name && (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '11px' }}>
                                            <div style={{ width: '16px', height: '16px', borderRadius: '50%', background: 'rgba(var(--accent-rgb), 0.1)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '8px', fontWeight: 700 }}>
                                                {act.originalItem.assigned_to_name.charAt(0).toUpperCase()}
                                            </div>
                                            <span>{act.originalItem.assigned_to_name}</span>
                                        </div>
                                    )}
                                </div>

                                {/* Direct Actions block */}
                                {(act.activity_type === 'PENDING' || act.activity_type === 'MISSED') && (
                                    <div style={{ display: 'flex', justifyContent: 'flex-end', width: '100%' }}>
                                        <button
                                            className="btn-modal-primary"
                                            style={{ padding: '4px 10px', fontSize: '10px', minHeight: '26px', width: 'fit-content' }}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                if (act.originalItem) {
                                                    setSelectedTask(act.originalItem);
                                                    setShowCompleteModal(true);
                                                    fetchTaskHistory(act.originalItem);
                                                }
                                            }}
                                        >
                                            Complete Now
                                        </button>
                                    </div>
                                )}
                            </div>
                        );
                    })
                )}
            </div>
        );
    };

    const FollowupsTableSkeleton = () => (
        <div className="filings-ledger-body">
            {[...Array(10)].map((_, i) => (
                <div key={i} className="filings-ledger-row followups-ledger-grid-template">
                    {[...Array(10)].map((_, j) => (
                        <div key={j} className="filings-ledger-cell">
                            <div className="filings-ledger-skeleton-bar" />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );

    return (
        <div className="followups-container">
            {document.getElementById('dashboard-header-actions-portal') && createPortal(
                <div className="tab-actions-group-right">



                    <div className="alerts-trigger-wrap">
                        <button
                            className={`btn-alerts-trigger ${showAlertsDrawer ? 'active' : ''}`}
                            onClick={() => setShowAlertsDrawer(true)}
                        >
                            <Bell size={14} />
                            Alerts
                            {alertsData.filter((item) => item.status === 'PENDING' || item.status === 'MISSED').length > 0 && (
                                <span className="count-badge-v4">
                                    {alertsData.filter((item) => item.status === 'PENDING' || item.status === 'MISSED').length}
                                </span>
                            )}
                        </button>
                    </div>

                    {activeFollowupCategory === 'payments' && (
                        <button
                            type="button"
                            className="btn-filter-v2"
                            onClick={() => {
                                setShowAddPaymentFollowup(true);
                                setShowCalendar(false);
                                setShowFilterModal(false);
                            }}
                        >
                            <Plus size={14} />
                            Add Payment Follow-up
                        </button>
                    )}

                    <button
                        className={`btn-filter-v2 ${showFilterModal ? 'active' : ''}`}
                        onClick={() => {
                            setShowFilterModal(true);
                            setShowCalendar(false);
                        }}
                    >
                        <div className="badge-dot-wrap">
                            <Filter size={14} />
                            {(filters.status || filters.entity_type || filters.today_only || filters.is_overdue || filters.search) && (
                                <span className="count-badge-v4" style={{ background: 'var(--accent)', color: 'var(--text-inverse)' }}>!</span>
                            )}
                            Filters
                        </div>
                    </button>
                </div>,
                document.getElementById('dashboard-header-actions-portal')
            )}
            <div className="crm-followups-subtabs">
                <button
                    onClick={() => switchFollowupCategory('services')}
                    style={{
                        background: 'transparent',
                        color: activeFollowupCategory === 'services' ? 'var(--accent)' : 'var(--text-muted)',
                        border: 'none',
                        borderBottom: activeFollowupCategory === 'services' ? '2px solid var(--accent)' : '2px solid transparent',
                        fontSize: '14px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        padding: '8px 4px',
                        transition: 'all 0.2s ease',
                        marginBottom: '-1px'
                    }}
                >
                    Service Follow-ups
                </button>
                <button
                    onClick={() => switchFollowupCategory('payments')}
                    style={{
                        background: 'transparent',
                        color: activeFollowupCategory === 'payments' ? 'var(--accent)' : 'var(--text-muted)',
                        border: 'none',
                        borderBottom: activeFollowupCategory === 'payments' ? '2px solid var(--accent)' : '2px solid transparent',
                        fontSize: '14px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        padding: '8px 4px',
                        transition: 'all 0.2s ease',
                        marginBottom: '-1px'
                    }}
                >
                    Payment Follow-ups
                </button>
            </div>

            {renderStatsGrid()}

            <div className="crm-charts-row followups-charts-row-compact">
                <div className="crm-chart-box glass-v4">
                    <div className="chart-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <h3>Follow-up Calendar</h3>
                        </div>
                        {activeFollowupCategory === 'services' && (
                            <div className="entity-type-select-wrap">
                                <select
                                    className="glass-select-v4"
                                    value={filters.entity_type || ''}
                                    onChange={(e) => {
                                        setFilters({
                                            ...filters,
                                            entity_type: e.target.value
                                        });
                                        setPage(1);
                                        setSchedulePage(1);
                                    }}
                                    style={{ height: '32px', padding: '0 28px 0 10px', fontSize: '12px' }}
                                >
                                    <option value="">All Services</option>
                                    {Object.keys(SERVICE_TYPE_MAP).map(type => (
                                        <option key={type} value={type}>{type}</option>
                                    ))}
                                </select>
                            </div>
                        )}
                        {activeFollowupCategory === 'payments' && (
                            <div className="entity-type-select-wrap">
                                <select
                                    className="glass-select-v4"
                                    value={filters.entity_type || ''}
                                    onChange={(e) => {
                                        setFilters({
                                            ...filters,
                                            entity_type: e.target.value
                                        });
                                        setPage(1);
                                        setSchedulePage(1);
                                    }}
                                    style={{ height: '32px', padding: '0 28px 0 10px', fontSize: '12px' }}
                                >
                                    <option value="">All Payments</option>
                                    <option value="GST_FILING">GST Filing Payments</option>
                                    <option value="GST_FILING_RETURN_DETAILS">GST Return Payments</option>
                                    <option value="CUSTOMER_SERVICE">Service Payments</option>
                                </select>
                            </div>
                        )}
                    </div>
                    {renderInlineCalendar()}
                </div>
                <div className="crm-chart-box glass-v4 scheduled-followups-panel">
                    <div className="chart-header">
                        <h3>Scheduled Followups</h3>
                        <button
                            type="button"
                            className="btn-icon-mini"
                            onClick={() => {
                                setSchedulePage(1);
                                fetchRecentActivities();
                            }}
                            title="Refresh Schedule"
                        >
                            <Activity size={14} />
                        </button>
                    </div>
                    {renderActivityFeed()}
                    <div className="scheduled-followups-footer">
                        <Pagination
                            currentPage={schedulePage}
                            onPageChange={setSchedulePage}
                            hasMore={scheduleHasMore}
                            loading={scheduleLoading}
                        />
                    </div>
                </div>
            </div>



            {/* Drawers Rendered at Root Level for Proper Display */}

            {showAlertsDrawer && renderAlertsDrawer()}
            {showFilterModal && renderFilterDrawer()}

            {showCompleteModal && renderCompleteTaskModal(closeCompleteModal)}
            {showAddPaymentFollowup && renderAddPaymentFollowupDrawer()}
            {showDetailDrawer && renderDetailDrawer()}
        </div>
    );
};

export default Followups;
