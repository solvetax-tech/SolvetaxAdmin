import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  Building2,
  FileText,
  UserCircle,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Settings as SettingsIcon,
  Bell,
  Search,
  Plus,
  BellRing,
  CreditCard,
  BookOpen,
  History,
  Briefcase, Camera, Edit2, Shield, Clock, Activity, Mail, Phone, Hash, Calendar, CalendarCheck, ShieldCheck, CheckCircle2, XCircle, MoreVertical, Loader2, X, AlertCircle, ArrowRight, Lock, Landmark, ListTodo, Headphones, Sun, Moon, Bug, UserPlus
} from 'lucide-react';
import './Dashboard.css';
import './common/AppSideDrawer.css';
import './common/CustomSelect.css';
import { GSTRegistration } from './gst_registration/gst_registration';
import { GSTFilings } from './gst_filings/gst_filings';
import { IncomeTax } from './income_tax/IncomeTax';
import { GSTPeople } from './gst_registration/gst_people';
import { GSTDocuments } from './gst_registration/gst_documents';
import Employee from './employees/Employee';
import Customer from './customers/Customer';
import { Payments } from './payments/Payments';
import AddPayment from './payments/AddPayment';
import Knowledge from './knowledge/Knowledge';
import SettingsTab from './settings/SettingsTab';
import CustomerServices from './customers/CustomerServices';
import Followups from './follow_ups/Followups';
import ServiceDonePaymentPending from './dashboard/ServiceDonePaymentPending';
import GstFilingMonthlyMatrix from './dashboard/GstFilingMonthlyMatrix';
import ContactSupportLeads from './contact_support/ContactSupportLeads';
import RaiseIssueModal from './issues/RaiseIssueModal';
import TasksPage from './tasks/TasksPage';
import useTaskReminders from '../hooks/useTaskReminders';
import api from '../utils/api';
import { fetchCustomerServiceProgressTracker } from '../utils/customerServiceApi';
import { dispatchGstFilingFocusOpen, resolveGstFocusFromAction } from '../utils/dashboardApi';
import { getRoleCssClassFor, getRoleDisplayLabel } from '../utils/roleBadgeUtils';
import { getRememberedAccounts, rememberAccount } from '../utils/rememberedAccounts';
import LoadingOverlay from './common/LoadingOverlay';
import Pagination from './common/Pagination';
import NotificationsTab from './notifications/NotificationsTab';
import ChangePasswordModal from './profile/ChangePasswordModal';
import DataTableLoader from './common/DataTableLoader';
import ThemeToggle from './common/ThemeToggle';
import useFollowupReminders from '../hooks/useFollowupReminders';
import useGstFilingFollowupReminders from '../hooks/useGstFilingFollowupReminders';
import { canSeeGstFilingsDashboard, canSeeCrmDashboard, isTrueAdmin, hasPermission } from '../utils/rbac';

class DashboardErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[Dashboard] render error:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="dashboard-layout-wrapper">
          <div className="dashboard-main" style={{ padding: 32 }}>
            <h2 style={{ color: 'var(--text-primary)', marginBottom: 8 }}>Dashboard failed to load</h2>
            <p style={{ color: 'var(--text-muted)', maxWidth: 520, marginBottom: 16 }}>
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            <button
              type="button"
              className="btn-save-v4"
              onClick={() => window.location.assign('/dashboard?tab=dashboard&sub=followups')}
            >
              Reload Dashboard
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const DASHBOARD_SUB_TABS = ['followups', 'progress', 'service-done-payment', 'gst-filing-matrix', 'today-tasks'];
const DEFAULT_DASHBOARD_SUB_TAB = 'followups';

function resolveDashboardSubTab(sub, tab) {
  if (tab && tab !== 'dashboard') return DEFAULT_DASHBOARD_SUB_TAB;
  return DASHBOARD_SUB_TABS.includes(sub) ? sub : DEFAULT_DASHBOARD_SUB_TAB;
}

const DASHBOARD_PRESERVED_PARAMS = [
  'complete_task_id',
  'category',
  'focus_customer_id',
  'focus_return_detail_id',
  'focus_form_key',
  'focus_period',
];

function buildDashboardSearch(sub, sourceParams = new URLSearchParams()) {
  const params = new URLSearchParams();
  params.set('tab', 'dashboard');
  params.set('sub', resolveDashboardSubTab(sub, 'dashboard'));
  DASHBOARD_PRESERVED_PARAMS.forEach((key) => {
    const value = sourceParams.get(key);
    if (value) params.set(key, value);
  });
  return params.toString();
}

const WORKSPACE_TAB_LABELS = {
  dashboard: 'Dashboard',
  employees: 'Employees',
  customers: 'Customers',
  gst: 'GST Portal',
  'income-tax': 'Income Tax',
  payments: 'Payments',
  'customer-services': 'Customer Services',
  'contact-leads': 'Contact/Referral',
  'add-payment': 'Add Payment',
  knowledge: 'Knowledge',
  settings: 'Settings',
  profile: 'Profile',
  notifications: 'Notifications',
};

function getWorkspaceTabLabel(tab) {
  if (WORKSPACE_TAB_LABELS[tab]) return WORKSPACE_TAB_LABELS[tab];
  if (!tab) return 'Dashboard';
  return tab.charAt(0).toUpperCase() + tab.slice(1).replace(/-/g, ' ');
}

const Dashboard = ({ onLogout }) => {
  const navigate = useNavigate();
  const location = useLocation();

  // Helper to get params
  const getSearchParams = useCallback(() => new URLSearchParams(location.search), [location.search]);

  const [activeTab, setActiveTab] = useState(() => getSearchParams().get('tab') || 'dashboard');
  const [activeSubTab, setActiveSubTab] = useState(() => {
    const params = getSearchParams();
    const tab = params.get('tab') || 'dashboard';
    return params.get('sub') || (tab === 'dashboard' ? 'followups' : 'registrations');
  });
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);
  const [profileData, setProfileData] = useState(null);
  const [isGstExpanded, setIsGstExpanded] = useState(false);
  const [globalSearchTerm, setGlobalSearchTerm] = useState('');
  const [globalSearchResults, setGlobalSearchResults] = useState({
    customers: [],
    employees: [],
    gstRegistrations: [],
    gstPeople: [],
    gstDocuments: [],
    payments: []
  });
  const [globalSearchLoading, setGlobalSearchLoading] = useState(false);
  const [showGlobalSearch, setShowGlobalSearch] = useState(false);
  const searchRef = useRef(null);

  const [dashboardSubTab, setDashboardSubTab] = useState(() => {
    const params = getSearchParams();
    const tab = params.get('tab') || 'dashboard';
    return resolveDashboardSubTab(params.get('sub'), tab);
  });
  const [serviceUsernamesById, setServiceUsernamesById] = useState({});
  const [customerProgressRows, setCustomerProgressRows] = useState([]);
  const [customerProgressLoading, setCustomerProgressLoading] = useState(false);
  const [customerProgressError, setCustomerProgressError] = useState(null);
  const [progressStatusFilter, setProgressStatusFilter] = useState('ALL'); // ALL, NOT_STARTED, IN_PROGRESS, COMPLETED
  const [progressPage, setProgressPage] = useState(1);
  const progressRowsPerPage = 20;
  const [progressSelectedCustomerId, setProgressSelectedCustomerId] = useState(null);
  const [isProgressLayoutCollapsed, setIsProgressLayoutCollapsed] = useState(
    () => (typeof window !== 'undefined' ? window.innerWidth < 1380 : false)
  );
  const [progressSummary, setProgressSummary] = useState({
    total: 0,
    completed: 0,
    inProgress: 0,
    notStarted: 0,
  });

  const handleLogout = useCallback(() => {
    if (onLogout) onLogout();
    navigate('/login');
  }, [onLogout, navigate]);

  // Edit Profile State
  const [isEditProfileOpen, setIsEditProfileOpen] = useState(false);
  const [editProfileData, setEditProfileData] = useState({
    first_name: '', last_name: '', email: '', phone_number: ''
  });
  const [editProfileLoading, setEditProfileLoading] = useState(false);
  const [editProfileFetching, setEditProfileFetching] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [toasts, setToasts] = useState([]);
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);
  const [hasNotifications, setHasNotifications] = useState(false);
  const [showRaiseIssue, setShowRaiseIssue] = useState(false);
  const [showCrmDropdown, setShowCrmDropdown] = useState(false);

  // --- Follow-up Reminders (service + payment only; GST filings are separate) ---
  useFollowupReminders(profileData);
  useTaskReminders(profileData);
  useGstFilingFollowupReminders(profileData);

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  function setToastMessage(msg, variant = 'success') {
    if (msg == null || msg === '') return;

    let message = msg;
    let toastVariant = variant;

    if (typeof msg === 'object') {
      message = msg.text ?? msg.message ?? '';
      toastVariant = msg.type ?? msg.variant ?? variant ?? 'success';
    }

    if (!message) return;

    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, variant: toastVariant || 'success' }]);
  }

  // --- Toast Auto-Cleanup Logic (15s per-toast) ---
  useEffect(() => {
    if (toasts.length > 0) {
      const timers = toasts.map(toast => {
        if (!toast.hasTimerStarted) {
          toast.hasTimerStarted = true;
          const duration = toast.action ? 15000 : 5000;
          return setTimeout(() => removeToast(toast.id), duration);
        }
        return null;
      }).filter(Boolean);
      
      return () => timers.forEach(clearTimeout);
    }
  }, [toasts, removeToast]);

  // --- Notification Checker ---
  useEffect(() => {
    const checkNotifications = () => {
      try {
        const notifs = JSON.parse(localStorage.getItem('st_notifications') || '[]');
        setHasNotifications(notifs.length > 0);
      } catch (err) {
        console.error("Failed to check notifications:", err);
      }
    };

    checkNotifications();
    window.addEventListener('st_notifications_updated', checkNotifications);

    // Toast Global Event Listener (Priority Delivery)
    const handleGlobalToast = (event) => {
      const { message, action, variant = 'success' } = event.detail || {};
      if (message) {
        console.log(`[Dashboard] Global Toast Received: ${message}`);
        const id = Date.now() + Math.random();
        setToasts(prev => [...prev, { id, message, action, variant }]);
      }
    };

    window.addEventListener('st_show_toast', handleGlobalToast);

    return () => {
      window.removeEventListener('st_notifications_updated', checkNotifications);
      window.removeEventListener('st_show_toast', handleGlobalToast);
    };
  }, []);

  // --- Universal URL sync + dashboard query normalization ---
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const tab = params.get('tab') || 'dashboard';
    const rawSub = params.get('sub');
    const taskId = params.get('complete_task_id');
    const category = params.get('category');

    if (taskId) {
      window.dispatchEvent(new CustomEvent('st_open_followup', {
        detail: {
          taskId,
          category: category === 'payments' ? 'payments' : 'services',
        },
      }));
    }

    if (tab === 'dashboard') {
      const nextSub = resolveDashboardSubTab(rawSub, tab);
      const targetSearch = `?${buildDashboardSearch(nextSub, params)}`;
      if (targetSearch !== location.search) {
        navigate(`/dashboard${targetSearch}`, { replace: true });
        return;
      }
      setActiveTab('dashboard');
      setDashboardSubTab(nextSub);
      return;
    }

    // GST Filings is ADMIN + OP_MANAGER only. Guard the URL too, so a pasted or
    // bookmarked link can't reach it. Waits for profileData — otherwise an admin
    // would be bounced on first paint, before their role is known.
    // Computed inline rather than via showGstFilingsTab: that const is declared
    // further down, so naming it in the dep array would be a temporal dead zone.
    if (tab === 'gst' && rawSub === 'filings' && profileData
        && !canSeeGstFilingsDashboard(profileData)) {
      navigate('/dashboard?tab=gst&sub=registrations', { replace: true });
      return;
    }

    setActiveTab(tab);
    setActiveSubTab(rawSub || (tab === 'contact-leads' ? 'contact_support' : 'registrations'));
    if (tab === 'gst') setIsGstExpanded(true);
  }, [location.search, navigate, profileData]);



  // --- Edit Profile Handlers ---
  const handleOpenEditProfile = async () => {
    // 1. Immediately pre-fill with whatever data we currently have to avoid UI lag.
    setEditProfileData({
      first_name: profileData?.first_name || '',
      last_name: profileData?.last_name || '',
      email: profileData?.email || '',
      phone_number: profileData?.phone_number || '',
      username: profileData?.username || ''
    });
    setFieldErrors({});
    setIsEditProfileOpen(true);

    // 2. Fetch the fresh, complete data directly from the GET API to ensure accuracy
    if (profileData?.emp_id) {
      try {
        setEditProfileFetching(true);
        const res = await api.get(`/api/v1/employees/employee/${profileData.emp_id}`);
        const freshData = res.data?.data || res.data;

        // Update the form with the fresh data from the DB
        setEditProfileData({
          first_name: freshData.first_name || '',
          last_name: freshData.last_name || '',
          email: freshData.email || '',
          phone_number: freshData.phone_number || '',
          username: freshData.username || ''
        });

        // Also subtly update the parent profile data if things changed in the background
        setProfileData(prev => ({ ...prev, ...freshData }));
      } catch (err) {
        console.error("Failed to fetch fresh profile data for editing:", err);
      } finally {
        setEditProfileFetching(false);
      }
    }
  };

  const handleEditProfileChange = (e) => {
    const { name, value } = e.target;
    setEditProfileData(prev => ({ ...prev, [name]: value }));
    // Clear the specific field error when user starts typing again
    if (fieldErrors[name]) {
      setFieldErrors(prev => ({ ...prev, [name]: null }));
    }
  };

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setEditProfileLoading(true);
    setFieldErrors({});

    try {
      const response = await api.post(`/api/v1/employees/${profileData.emp_id}/emp_dyn/edit`, editProfileData);

      // 1. Update local profile data without refreshing the page
      const updatedProfile = response.data?.data || response.data;
      setProfileData(prev => ({ ...prev, ...updatedProfile }));

      // 2. Notify parent component by showing a success toast and closing modal
      setIsEditProfileOpen(false);
      setToastMessage('Profile updated successfully! âœ¨');
    } catch (err) {
      console.error("Failed to update profile", err);

      // Handle custom FastAPI structured errors (409 Conflict or 422 Unprocessable Entity)
      if (err.response && (err.response.status === 409 || err.response.status === 422 || err.response.status === 400)) {
        const detail = err.response.data?.detail;

        // Structured Error Payload (e.g. from employee_edit.py Duplicate checks)
        if (detail?.error?.fields) {
          setFieldErrors(detail.error.fields);
        }
        // Array of validation errors (Pydantic style)
        else if (Array.isArray(detail)) {
          const newErrors = {};
          detail.forEach(errItem => {
            const field = errItem.loc?.[errItem.loc.length - 1]; // Get field name
            if (field) newErrors[field] = errItem.msg;
          });
          setFieldErrors(newErrors);
        }
        // Fallback for flat string
        else if (typeof detail === 'string') {
          const lowerDetail = detail.toLowerCase();
          if (lowerDetail.includes('email')) {
            setFieldErrors({ email: detail });
          } else if (lowerDetail.includes('phone') || lowerDetail.includes('mobile')) {
            setFieldErrors({ phone_number: detail });
          } else if (lowerDetail.includes('username')) {
            setFieldErrors({ username: detail });
          } else if (detail.includes('error.message')) {
            // Unlikely fallback
            setFieldErrors({ _global: err.response.data.detail.error.message });
          } else {
            setFieldErrors({ _global: detail });
          }
        } else {
          setFieldErrors({ _global: 'Failed to update profile. Please check your inputs.' });
        }
      } else {
        setFieldErrors({ _global: err.response?.data?.detail || 'An unexpected error occurred while saving.' });
      }
    } finally {
      setEditProfileLoading(false);
    }
  };

  const getApiErrorMessage = useCallback((err, fallback = 'Request failed') => {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
        .filter(Boolean);
      if (msgs.length > 0) return msgs.join(', ');
      return fallback;
    }
    if (detail && typeof detail === 'object') {
      if (typeof detail?.message === 'string') return detail.message;
      if (typeof detail?.error?.message === 'string') return detail.error.message;
      return fallback;
    }
    return err?.message || fallback;
  }, []);

  const fetchCustomerProgress = useCallback(async () => {
    setCustomerProgressLoading(true);
    setCustomerProgressError(null);
    try {
      const result = await fetchCustomerServiceProgressTracker({ limit: 500, offset: 0 });
      const summary = result.summary || {};
      setProgressSummary({
        total: Number(summary.tracked_customers) || 0,
        completed: Number(summary.completed) || 0,
        inProgress: Number(summary.in_progress) || 0,
        notStarted: Number(summary.not_started) || 0,
      });

      const rows = (result.rows || []).map((row) => ({
        customer_id: row.customer_id,
        customer_name: row.customer_name || '-',
        business_name: row.business_name || '',
        customer_mobile: row.phone_number || '-',
        phone_number: row.phone_number || '',
        required_count: Number(row.required_count) || 0,
        provided_count: Number(row.provided_count) || 0,
        pending_count: Number(row.pending_count) || 0,
        completion_percent: Number(row.completion_percent) || 0,
        overall_status: row.overall_status || 'NOT_STARTED',
        required_services: row.required_services || [],
        provided_services: row.provided_services || [],
        pending_services: row.pending_services || [],
        rm_id: row.rm_id ?? null,
        op_id: row.op_id ?? null,
        rm_username: row.rm_username || '-',
        op_username: row.op_username || '-',
      }));

      setCustomerProgressRows(rows);
    } catch (err) {
      setCustomerProgressError(getApiErrorMessage(err, 'Failed to fetch customer progress'));
      setCustomerProgressRows([]);
      setProgressSummary({ total: 0, completed: 0, inProgress: 0, notStarted: 0 });
    } finally {
      setCustomerProgressLoading(false);
    }
  }, [getApiErrorMessage]);

  useEffect(() => {
    if (dashboardSubTab !== 'progress') return;
    fetchCustomerProgress();
    return undefined;
  }, [dashboardSubTab, fetchCustomerProgress]);

  useEffect(() => {
    const missingIds = Array.from(
      new Set(
        customerProgressRows
          .flatMap((svc) => [svc?.rm_id, svc?.op_id])
          .filter((id) => id !== null && id !== undefined)
          .map((id) => String(id))
          .filter((id) => !serviceUsernamesById[id])
      )
    );

    if (missingIds.length === 0) return;

    let cancelled = false;
    const loadMissingUsernames = async () => {
      const pairs = await Promise.all(
        missingIds.map(async (id) => {
          try {
            const res = await api.get(`/api/v1/employees/employee/${id}`);
            const emp = res.data?.data || res.data || {};
            return [id, emp.username || emp.email || emp.first_name || '-'];
          } catch {
            return [id, '-'];
          }
        })
      );

      if (cancelled) return;
      const patch = Object.fromEntries(pairs);
      setServiceUsernamesById((prev) => ({ ...prev, ...patch }));
    };

    loadMissingUsernames();
    return () => {
      cancelled = true;
    };
  }, [customerProgressRows, serviceUsernamesById]);

  // Fetch logged-in user profile
  const fetchUserProfile = useCallback(async () => {
    let payload = null;
    try {
      const token = localStorage.getItem('session_token');
      if (!token) return;

      const parts = token.split('.');
      if (parts.length < 2 || !parts[1]) return;

      const base64Url = parts[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      payload = JSON.parse(window.atob(base64));
      const empId = payload.sub;

      if (empId) {
        const res = await api.get(`/api/v1/employees/employee/${empId}`);
        setProfileData(res.data?.data || res.data);
      }
    } catch (err) {
      console.error("Failed to fetch profile:", err);
      // Fallback so a transient profile-fetch failure doesn't silently downgrade
      // an admin to the non-admin toolset: the signed JWT already carries the
      // role, so seed a minimal profile from it rather than leaving it null.
      if (payload?.role) {
        setProfileData((prev) => prev || { emp_id: payload.sub, role: payload.role });
      }
    }
  }, []);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowGlobalSearch(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const performGlobalSearch = async (term) => {
    const query = String(term || '').trim();
    if (!query) {
      setGlobalSearchResults({
        customers: [],
        employees: [],
        gstRegistrations: [],
        gstPeople: [],
        gstDocuments: [],
        payments: []
      });
      setShowGlobalSearch(false);
      return;
    }

    const isEmail = query.includes('@');
    const isNumeric = /^\d+$/.test(query);
    const isPhone = /^\d{10}$/.test(query);
    const isGstin = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/i.test(query);

    const buildParams = (base, extra) => {
      const params = new URLSearchParams(base);
      Object.entries(extra).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) params.append(k, v);
      });
      return params.toString();
    };

    setGlobalSearchLoading(true);
    setShowGlobalSearch(true);

    const customerParams = buildParams({ limit: 5, offset: 0, include_inactive: true }, {
      ...(isEmail ? { email: query } : {}),
      ...(isPhone ? { mobile: query } : {}),
      ...(isNumeric && !isPhone ? { customer_id: query } : {}),
      ...(!isEmail && !isPhone && !isNumeric ? { full_name: query } : {})
    });

    const employeeParams = buildParams({ limit: 5, offset: 0, include_inactive: true }, {
      ...(isEmail ? { email: query } : {}),
      ...(isPhone ? { phone_number: query } : {}),
      ...(isNumeric && !isPhone ? { emp_id: query } : {}),
      ...(!isEmail && !isPhone && !isNumeric ? { full_name: query } : {})
    });

    const gstRegParams = buildParams({ limit: 5, offset: 0, include_inactive: true }, {
      ...(isGstin ? { gstin: query.toUpperCase() } : {}),
      ...(isEmail ? { email: query } : {}),
      ...(isPhone ? { mobile: query } : {}),
      ...(isNumeric && !isPhone ? { gst_registration_id: query } : {}),
      ...(!isEmail && !isPhone && !isNumeric && !isGstin ? { gstin: query } : {})
    });

    const gstPeopleParams = buildParams({ limit: 5, offset: 0 }, {
      ...(isEmail ? { email: query } : {}),
      ...(isPhone ? { mobile: query } : {}),
      ...(isNumeric && !isPhone ? { person_id: query } : {}),
      ...(!isEmail && !isPhone && !isNumeric ? { full_name: query } : {})
    });

    const gstDocsParams = buildParams({ limit: 5, offset: 0 }, {
      ...(isGstin ? { gstin: query.toUpperCase() } : {}),
      ...(isNumeric && !isPhone ? { person_id: query } : {}),
      ...(!isEmail && !isPhone && !isNumeric && !isGstin ? { document_type: query } : {})
    });

    const paymentsParams = buildParams({ limit: 5, offset: 0, include_inactive: true }, {
      ...(isNumeric && !isPhone ? { payment_id: query } : {})
    });

    const requests = [
      api.get(`/api/v1/customers/customer_get/filter?${customerParams}`),
      api.get(`/api/v1/employees/filter?${employeeParams}`),
      api.get(`/api/v1/gst-registrations/dynamic_filter?${gstRegParams}`),
      api.get(`/api/v1/gst-people/dynamic_filter?${gstPeopleParams}`),
      api.get(`/api/v1/gst-documents/dynamic_filter?${gstDocsParams}`),
      isNumeric ? api.get(`/api/v1/payments/dynamic_filter?${paymentsParams}`) : Promise.resolve({ data: { data: [] } })
    ];

    const [custRes, empRes, gstRes, peopleRes, docRes, payRes] = await Promise.allSettled(requests);

    const unwrap = (res) => {
      if (!res || res.status !== 'fulfilled') return [];
      const val = res.value?.data;
      return Array.isArray(val) ? val : (val?.data || []);
    };

    setGlobalSearchResults({
      customers: unwrap(custRes),
      employees: unwrap(empRes),
      gstRegistrations: unwrap(gstRes),
      gstPeople: unwrap(peopleRes),
      gstDocuments: unwrap(docRes),
      payments: unwrap(payRes)
    });

    setGlobalSearchLoading(false);
  };

  const handleSearchResultClick = (type, payload) => {
    setShowGlobalSearch(false);
    if (!payload) return;

    if (type === 'customer') {
      navigate(`/dashboard?tab=customers&customer_id=${payload.customer_id}`);
      return;
    }
    if (type === 'employee') {
      navigate(`/dashboard?tab=employees&emp_id=${payload.emp_id}`);
      return;
    }
    if (type === 'gst_registration') {
      const id = payload.id || payload.gst_registration_id;
      if (id) {
        navigate(`/dashboard?tab=gst&sub=registrations&gst_registration_id=${id}`);
      } else if (payload.gstin) {
        navigate(`/dashboard?tab=gst&sub=registrations&gstin=${encodeURIComponent(payload.gstin)}`);
      }
      return;
    }
    if (type === 'gst_person') {
      navigate(`/dashboard?tab=gst&sub=people&person_id=${payload.person_id}`);
      return;
    }
    if (type === 'gst_document') {
      if (payload.gstin) {
        navigate(`/dashboard?tab=gst&sub=documents&gstin=${encodeURIComponent(payload.gstin)}`);
      } else if (payload.person_id) {
        navigate(`/dashboard?tab=gst&sub=documents&person_id=${payload.person_id}`);
      }
      return;
    }
    if (type === 'payment') {
      navigate(`/dashboard?tab=payments&payment_id=${payload.payment_id}`);
    }
  };

  // Handle Tab Change
  const handleTabChange = (tab, sub = null) => {
    const params = new URLSearchParams();
    params.set('tab', tab);
    if (tab === 'dashboard') {
      params.set('sub', resolveDashboardSubTab(sub, tab));
    } else if (sub) {
      params.set('sub', sub);
    }
    navigate(`/dashboard?${params.toString()}`);
  };

  const isFetchingRef = useRef(false);
  useEffect(() => {
    const loadData = async () => {
      if (isFetchingRef.current) return;

      if (profileData && activeTab !== 'profile' && activeTab !== 'dashboard') {
        return;
      }

      isFetchingRef.current = true;
      try {
        if (!profileData || activeTab === 'profile') {
          await fetchUserProfile();
        }
      } finally {
        isFetchingRef.current = false;
      }
    };

    loadData();
  }, [activeTab, fetchUserProfile, profileData]);

  // Close CRM dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      const dropdown = document.querySelector('.crm-dropdown-container');
      if (dropdown && !dropdown.contains(event.target)) {
        setShowCrmDropdown(false);
      }
    };

    if (showCrmDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
    } else {
      document.removeEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showCrmDropdown]);

  // Close profile dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      const dropdown = document.querySelector('.user-profile-container');
      if (dropdown && !dropdown.contains(event.target)) {
        setShowProfileDropdown(false);
      }
    };

    if (showProfileDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
    } else {
      document.removeEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showProfileDropdown]);

  // --- Account switcher (profile dropdown) -------------------------------- //
  // Remembered accounts are a device-local convenience list (name/email/role,
  // no passwords, no tokens), so this never weakens the httpOnly refresh-token
  // model. Switching just pre-fills the login email; the password is still
  // required. See utils/rememberedAccounts.
  const [savedAccounts, setSavedAccounts] = useState([]);

  // Remember the current account whenever its profile is (re)loaded.
  useEffect(() => {
    if (!profileData?.email) return;
    const name = `${profileData.first_name || ''} ${profileData.last_name || ''}`.trim()
      || profileData.username || '';
    rememberAccount({
      emp_id: profileData.emp_id,
      email: profileData.email,
      name,
      role: profileData.role,
    });
  }, [profileData?.email, profileData?.emp_id, profileData?.role, profileData?.first_name, profileData?.last_name, profileData?.username]);

  // localStorage isn't reactive — re-read the list each time the dropdown opens.
  useEffect(() => {
    if (showProfileDropdown) setSavedAccounts(getRememberedAccounts());
  }, [showProfileDropdown]);

  const switchToAccount = (email) => {
    setShowProfileDropdown(false);
    navigate(`/login?email=${encodeURIComponent(email)}`);
  };

  const addAnotherAccount = () => {
    setShowProfileDropdown(false);
    navigate('/login');
  };

  // ADMIN-only system tools; managers use team-scoped access via profileData.role in APIs.
  const isAdmin = isTrueAdmin(profileData);
  const showGstFilingsTab = canSeeGstFilingsDashboard(profileData);
  const showCrmSwitcher = canSeeCrmDashboard(profileData);
  const canSignup = isAdmin;

  useEffect(() => {
    if (!profileData) return;
    if (dashboardSubTab === 'gst-filing-matrix' && !showGstFilingsTab) {
      handleTabChange('dashboard', DEFAULT_DASHBOARD_SUB_TAB);
    }
  }, [profileData, dashboardSubTab, showGstFilingsTab]);

  const formatDateTime = (dtStr) => {
    if (!dtStr) return '-';
    try {
      return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
    } catch {
      return dtStr;
    }
  };

  const filteredCustomerProgressRows = useMemo(() => {
    if (progressStatusFilter === 'ALL') return customerProgressRows;
    return customerProgressRows.filter((row) => row.overall_status === progressStatusFilter);
  }, [customerProgressRows, progressStatusFilter]);

  const paginatedCustomerProgressRows = useMemo(() => {
    const start = (progressPage - 1) * progressRowsPerPage;
    const end = start + progressRowsPerPage;
    return filteredCustomerProgressRows.slice(start, end);
  }, [filteredCustomerProgressRows, progressPage]);

  useEffect(() => {
    setProgressPage(1);
  }, [progressStatusFilter, customerProgressRows.length]);

  useEffect(() => {
    setProgressSelectedCustomerId(null);
  }, [progressPage]);

  const progressSelectedRow = customerProgressRows.find(r => r.customer_id === progressSelectedCustomerId);

  // Clear sub-tabs when switching main tabs
  useEffect(() => {
    if (!progressSelectedCustomerId) return;
    const stillVisible = filteredCustomerProgressRows.some((row) => row.customer_id === progressSelectedCustomerId);
    if (!stillVisible) {
      setProgressSelectedCustomerId(null);
    }
  }, [filteredCustomerProgressRows, progressSelectedCustomerId]);

  const hasDesktopProgressPanel = !isProgressLayoutCollapsed;

  useEffect(() => {
    const onWindowResize = () => setIsProgressLayoutCollapsed(window.innerWidth < 1380);
    window.addEventListener('resize', onWindowResize);
    return () => window.removeEventListener('resize', onWindowResize);
  }, []);

  const toTitleCase = (v = '') => v.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());

  const renderProgressDetailPanel = (row) => (
    <div className={`followup-drawer-overlay ${row ? 'show' : ''}`} onClick={() => setProgressSelectedCustomerId(null)}>
      <div className={`followup-drawer-panel tracker-drawer ${row ? 'show' : ''}`} onClick={e => e.stopPropagation()}>
        {row ? (
          <>
            <div className="drawer-header">
              <div className="drawer-title">
                <ShieldCheck size={24} color="var(--accent)" />
                <div>
                  <h3>{row.customer_name}</h3>
                  <p>Customer ID {row.customer_id}</p>
                </div>
              </div>
              <button className="btn-close-drawer" onClick={() => setProgressSelectedCustomerId(null)}>
                <X size={20} />
              </button>
            </div>

            <div className="drawer-body">
              {/* Progress Overview Section */}
              <div className="progress-overview-premium">
                <div className="progress-header-row">
                  <span className={`overall-status-badge ${(row.overall_status || 'not_started').toLowerCase()}`}>
                    {toTitleCase(row.overall_status || 'NOT_STARTED')}
                  </span>
                  <span className="completion-label">{row.completion_percent || 0}%</span>
                </div>
                <div className="premium-progress-track">
                  <div className="premium-progress-fill" style={{ width: `${Math.max(0, Math.min(100, row.completion_percent || 0))}%` }} />
                </div>

                <div className="kpi-grid-premium">
                  <div className="kpi-item-premium">
                    <span className="kpi-label-v2">Required</span>
                    <span className="kpi-value-v2">{row.required_count}</span>
                  </div>
                  <div className="kpi-item-premium">
                    <span className="kpi-label-v2">Provided</span>
                    <span className="kpi-value-v2" style={{ color: 'var(--accent)' }}>{row.provided_count}</span>
                  </div>
                  <div className="kpi-item-premium">
                    <span className="kpi-label-v2">Pending</span>
                    <span className="kpi-value-v2" style={{ color: 'var(--warning)' }}>{row.pending_count}</span>
                  </div>
                </div>
              </div>

              {/* Ownership Section */}
              <div className="owner-section-premium">
                <div className="owner-card-premium">
                  <div className="owner-icon-wrap"><Users size={16} /></div>
                  <div className="owner-info">
                    <span className="owner-title">Rel. Manager</span>
                    <span className="owner-name">
                      {serviceUsernamesById[String(row.rm_id)] || row.rm_username || '-'}
                    </span>
                  </div>
                </div>
                <div className="owner-card-premium">
                  <div className="owner-icon-wrap"><Briefcase size={16} /></div>
                  <div className="owner-info">
                    <span className="owner-title">Ops Owner</span>
                    <span className="owner-name">
                      {serviceUsernamesById[String(row.op_id)] || row.op_username || '-'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Detailed Services Section */}
              <div className="services-list-premium">
                <div className="service-type-group required-group">
                  <div className="group-header">
                    <div className="group-title"><ListTodo size={14} /> Required Services</div>
                    <div className="group-count">{row.required_count}</div>
                  </div>
                  <div className="service-items-grid">
                    {row.required_services?.length > 0
                      ? row.required_services.map((service, i) => (
                          <div key={`panel-req-${row.customer_id}-${i}`} className="service-pill-v4">{service}</div>
                        ))
                      : <div className="service-pill-v4 muted">None</div>}
                  </div>
                </div>

                <div className="service-type-group">
                  <div className="group-header">
                    <div className="group-title"><CheckCircle2 size={14} color="var(--accent)" /> Provided Services</div>
                    <div className="group-count">{row.provided_count}</div>
                  </div>
                  <div className="service-items-grid">
                    {row.provided_services?.length > 0
                      ? row.provided_services.map((service, i) => (
                          <div key={`panel-prov-${row.customer_id}-${i}`} className="service-pill-v4 provided">{service}</div>
                        ))
                      : <div className="service-pill-v4 muted">None</div>}
                  </div>
                </div>

                <div className="service-type-group">
                  <div className="group-header">
                    <div className="group-title"><Clock size={14} color="var(--warning)" /> Pending Services</div>
                    <div className="group-count">{row.pending_count}</div>
                  </div>
                  <div className="service-items-grid">
                    {row.pending_services?.length > 0
                      ? row.pending_services.map((service, i) => (
                          <div key={`panel-pend-${row.customer_id}-${i}`} className="service-pill-v4 pending">{service}</div>
                        ))
                      : <div className="service-pill-v4 muted">None</div>}
                  </div>
                </div>
              </div>
            </div>

            <div className="drawer-footer">
              <button type="button" className="btn-save-v4" style={{ width: '100%' }} onClick={() => navigate(`/dashboard?tab=customer-services&customer_id=${row.customer_id}`)}>
                Open Customer Services <ArrowRight size={14} />
              </button>
            </div>
          </>
        ) : (
          <div className="progress-side-empty-state">
            <div className="progress-side-empty-title">Select a Customer</div>
            <div className="progress-side-empty-desc">Click any row to view progress details.</div>
          </div>
        )}
      </div>
    </div>
  );

  const SkeletonBar = ({ width = '100%', height = '14px', borderRadius = '4px', className = '' }) => (
    <div 
      className={`skeleton-pulse ${className}`} 
      style={{ width, height, borderRadius, background: 'rgba(var(--fg-rgb), 0.05)', position: 'relative', overflow: 'hidden' }} 
    />
  );

  const effectiveDashboardSubTab = (() => {
    const sub = DASHBOARD_SUB_TABS.includes(dashboardSubTab)
      ? dashboardSubTab
      : DEFAULT_DASHBOARD_SUB_TAB;
    if (sub === 'gst-filing-matrix' && profileData && !showGstFilingsTab) {
      return DEFAULT_DASHBOARD_SUB_TAB;
    }
    return sub;
  })();

  const renderDashboardTab = () => (
    <>
      <div className="bg-orb orb-1" />
      <div className="bg-orb orb-2" />

      <div className="dashboard-sub-nav-v4 dashboard-sub-nav-v4--wrap">
        <button
          type="button"
          className={`sub-nav-btn-v4 ${effectiveDashboardSubTab === 'followups' ? 'active' : ''}`}
          onClick={() => handleTabChange('dashboard', 'followups')}
        >
          Follow Ups
        </button>
        <button
          type="button"
          className={`sub-nav-btn-v4 ${effectiveDashboardSubTab === 'progress' ? 'active' : ''}`}
          onClick={() => handleTabChange('dashboard', 'progress')}
        >
          Service Pending
        </button>
        <button
          type="button"
          className={`sub-nav-btn-v4 sub-nav-btn-v4--compact ${effectiveDashboardSubTab === 'service-done-payment' ? 'active' : ''}`}
          onClick={() => handleTabChange('dashboard', 'service-done-payment')}
        >
          Service Done Payment Pending
        </button>
        {showGstFilingsTab ? (
          <button
            type="button"
            className={`sub-nav-btn-v4 sub-nav-btn-v4--compact ${effectiveDashboardSubTab === 'gst-filing-matrix' ? 'active' : ''}`}
            onClick={() => handleTabChange('dashboard', 'gst-filing-matrix')}
          >
            GST Filings
          </button>
        ) : null}
        <button
          type="button"
          className={`sub-nav-btn-v4 ${effectiveDashboardSubTab === 'today-tasks' ? 'active' : ''}`}
          onClick={() => handleTabChange('dashboard', 'today-tasks')}
        >
          Tasks
        </button>
      </div>

      <div className="dashboard-sub-page-v4">
          {effectiveDashboardSubTab === 'progress' ? renderProgressTab() : null}
          {effectiveDashboardSubTab === 'followups' ? (
            <Followups
              isAdmin={isAdmin}
              profileData={profileData}
              setToastMessage={setToastMessage}
            />
          ) : null}
          {effectiveDashboardSubTab === 'service-done-payment' ? (
            <ServiceDonePaymentPending />
          ) : null}
          {effectiveDashboardSubTab === 'gst-filing-matrix' ? (
            <GstFilingMonthlyMatrix />
          ) : null}
          {effectiveDashboardSubTab === 'today-tasks' ? (
            <TasksPage setToastMessage={setToastMessage} />
          ) : null}
        </div>
    </>
  );







  const ProgressTableSkeleton = () => (
    <div className="filings-ledger-body">
      {[...Array(12)].map((_, i) => (
        <div key={i} className="filings-ledger-row progress-tracker-grid-template">
          {[...Array(5)].map((_, j) => (
            <div key={j} className="filings-ledger-cell">
              <div className="filings-ledger-skeleton-bar" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );

  const renderProgressTab = () => (
    <div className="progress-tracker-page">
      <div className="progress-stats-row-v4" role="tablist" aria-label="Filter customer service tracker">
        <button
          type="button"
          role="tab"
          aria-selected={progressStatusFilter === 'ALL'}
          className={`progress-badge-v4 total ${progressStatusFilter === 'ALL' ? 'is-filter-active' : ''}`}
          onClick={() => setProgressStatusFilter('ALL')}
        >
          <div className="badge-icon-wrap"><Users size={18} /></div>
          <div className="badge-info">
            <span className="badge-value">
              {customerProgressLoading ? <SkeletonBar width="40px" height="18px" /> : progressSummary.total}
            </span>
            <span className="badge-label">Tracked Customers</span>
          </div>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={progressStatusFilter === 'COMPLETED'}
          className={`progress-badge-v4 completed ${progressStatusFilter === 'COMPLETED' ? 'is-filter-active' : ''}`}
          onClick={() => setProgressStatusFilter('COMPLETED')}
        >
          <div className="badge-icon-wrap"><CheckCircle2 size={18} /></div>
          <div className="badge-info">
            <span className="badge-value">
              {customerProgressLoading ? <SkeletonBar width="40px" height="18px" /> : progressSummary.completed}
            </span>
            <span className="badge-label">Completed</span>
          </div>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={progressStatusFilter === 'IN_PROGRESS'}
          className={`progress-badge-v4 in-progress ${progressStatusFilter === 'IN_PROGRESS' ? 'is-filter-active' : ''}`}
          onClick={() => setProgressStatusFilter('IN_PROGRESS')}
        >
          <div className="badge-icon-wrap"><Activity size={18} /></div>
          <div className="badge-info">
            <span className="badge-value">
              {customerProgressLoading ? <SkeletonBar width="40px" height="18px" /> : progressSummary.inProgress}
            </span>
            <span className="badge-label">In Progress</span>
          </div>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={progressStatusFilter === 'NOT_STARTED'}
          className={`progress-badge-v4 not-started ${progressStatusFilter === 'NOT_STARTED' ? 'is-filter-active' : ''}`}
          onClick={() => setProgressStatusFilter('NOT_STARTED')}
        >
          <div className="badge-icon-wrap"><AlertCircle size={18} /></div>
          <div className="badge-info">
            <span className="badge-value">
              {customerProgressLoading ? <SkeletonBar width="40px" height="18px" /> : progressSummary.notStarted}
            </span>
            <span className="badge-label">Not Started</span>
          </div>
        </button>
      </div>

      <div className="service-records-shell-v5 progress-shell">
        <div className="progress-content-layout">
          <div className="progress-main-column">
            <div className="service-records-header-v5 progress-header">
              <div className="header-title-group services-title-group-v5">
                <h3 style={{ margin: 0 }}>Customer Service Tracker</h3>
                <span className="service-record-count-v5">{filteredCustomerProgressRows.length} rows</span>
              </div>
            </div>

            <div className="progress-tracker-container-v4">
              <div className="filings-ledger-header progress-tracker-grid-template">
                <div className="filings-ledger-header-cell">Customer ID</div>
                <div className="filings-ledger-header-cell">Customer</div>
                <div className="filings-ledger-header-cell">Service Required</div>
                <div className="filings-ledger-header-cell">Service Provided</div>
                <div className="filings-ledger-header-cell">Pending Service</div>
              </div>

              {customerProgressLoading ? (
                <ProgressTableSkeleton />
              ) : customerProgressError ? (
                <div className="employee-table-error">Error: {customerProgressError}</div>
              ) : (
                <div className="filings-ledger-body">
                  {paginatedCustomerProgressRows.length === 0 ? (
                    <div className="no-data-v4">No tracked customers found</div>
                  ) : (
                    paginatedCustomerProgressRows.map((row, idx) => (
                      <div 
                        key={`${row.customer_id}-${idx}`} 
                        className={`filings-ledger-row progress-tracker-grid-template ${progressSelectedCustomerId === row.customer_id ? 'active' : ''}`}
                        onClick={() => setProgressSelectedCustomerId(row.customer_id)}
                      >
                        <div className="filings-ledger-cell">
                          <span className="customer-id-green-v4">{row.customer_id}</span>
                        </div>
                        <div className="filings-ledger-cell">
                          <div className="customer-info-mini-v4">
                            <span className="customer-name-v4">{row.customer_name}</span>
                            <span className="customer-mobile-v4">
                              {[row.business_name, row.customer_mobile !== '-' ? row.customer_mobile : null]
                                .filter(Boolean)
                                .join(' • ') || '-'}
                            </span>
                          </div>
                        </div>
                        <div className="filings-ledger-cell">
                          <div className="service-count-badge-v4 required">{row.required_count}</div>
                        </div>
                        <div className="filings-ledger-cell">
                          <div className="service-count-badge-v4 provided">{row.provided_count}</div>
                        </div>
                        <div className="filings-ledger-cell">
                          <div className="service-count-badge-v4 pending">{row.pending_count}</div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      {renderProgressDetailPanel(progressSelectedRow)}
      <Pagination
        currentPage={progressPage}
        onPageChange={setProgressPage}
        hasMore={progressPage * progressRowsPerPage < filteredCustomerProgressRows.length}
        loading={customerProgressLoading}
      />
    </div>
  );


  // Helper to format "Time at Company"
  const getTimeAtCompany = (dateString) => {
    if (!dateString) return 'N/A';
    const start = new Date(dateString);
    if (isNaN(start.getTime())) return 'N/A'; // Handle invalid date strings

    const now = new Date();
    const diffTime = Math.abs(now - start);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays < 30) return `${diffDays} Days`;
    const months = Math.floor(diffDays / 30);
    if (months < 12) return `${months} Months`;
    const years = Math.floor(months / 12);
    const remainingMonths = months % 12;
    return `${years}Y ${remainingMonths}M`;
  };

  const renderProfileTab = () => (
    <div className="profile-container-v3">
      {/* 1. Cover Photo Hero */}
      <div className="profile-hero-v3">
        <div className="profile-cover">
          <div className="cover-edit-btn">
            <Camera size={14} /> Edit Cover
          </div>
        </div>
        <div className="profile-hero-content">
          <div className="profile-avatar-wrapper">
            <div className="profile-avatar-v3">
              {profileData?.employee_image_url ? (
                <img src={profileData.employee_image_url} alt="Profile" />
              ) : (
                <UserCircle size={80} strokeWidth={1} color="var(--text-muted)" />
              )}
              <div className="avatar-edit-overlay">
                <Camera size={24} />
              </div>
            </div>
            <div className="profile-status-ping active" title="Active"></div>
          </div>

          <div className="profile-hero-info-v3">
            <div className="info-main">
              <h1>
                {profileData?.first_name || profileData?.last_name
                  ? `${profileData?.first_name || ''} ${profileData?.last_name || ''}`.trim()
                  : profileData?.username || 'User User'}
              </h1>
              <span className={`role-badge-v3 ${getRoleCssClassFor(profileData)}`}>
                <Shield size={12} className="role-icon" />
                {getRoleDisplayLabel(profileData) || 'User'}
              </span>
            </div>
            <p className="profile-joined-text">
              <Clock size={12} /> Joined {profileData?.created_at ? new Date(profileData.created_at).toLocaleDateString() : 'N/A'} â€¢ <span className="highlight-time">{getTimeAtCompany(profileData?.created_at)}</span>
            </p>
          </div>

          <div className="profile-hero-actions">
            <button className="btn-secondary-v3" onClick={handleOpenEditProfile}>
              <Edit2 size={14} /> Edit Profile
            </button>
            <button className="btn-icon-v3">
              <MoreVertical size={16} />
            </button>
          </div>
        </div>
      </div>

      <div className="profile-content-grid">
        {/* 2. Left Column: Contact & Personal Info */}
        <div className="profile-column-left">
          <div className="profile-section-card">
            <h3 className="section-title">Contact Information</h3>
            <div className="info-list">
              <div className="info-list-item">
                <div className="icon-wrapper"><Hash size={16} /></div>
                <div className="item-content">
                  <label>Employee ID</label>
                  <p>{profileData?.emp_id || 'N/A'}</p>
                </div>
              </div>

              <div className="info-list-item interactive">
                <div className="icon-wrapper"><Mail size={16} /></div>
                <div className="item-content">
                  <label>Email Address</label>
                  <p>{profileData?.email || 'N/A'}</p>
                </div>
                <button className="inline-edit-btn" onClick={handleOpenEditProfile}><Edit2 size={14} /></button>
              </div>

              <div className="info-list-item interactive">
                <div className="icon-wrapper"><Phone size={16} /></div>
                <div className="item-content">
                  <label>Phone Number</label>
                  <p>{profileData?.phone_number || 'N/A'}</p>
                </div>
                <button className="inline-edit-btn" onClick={handleOpenEditProfile}><Edit2 size={14} /></button>
              </div>
            </div>
          </div>
        </div>

        {/* 2. Right Column: Security & System */}
        <div className="profile-column-right">
          <div className="profile-section-card">
            <h3 className="section-title">Security & System</h3>
            <div className="info-list">
              <div className="info-list-item">
                <div className="icon-wrapper"><UserCircle size={16} /></div>
                <div className="item-content">
                  <label>System Username</label>
                  <p className="mono-text">@{profileData?.username || 'N/A'}</p>
                </div>
              </div>

              <div className="info-list-item">
                <div className="icon-wrapper"><ShieldCheck size={16} /></div>
                <div className="item-content">
                  <label>Account Status</label>
                  <div className="status-badge-glow active">
                    <CheckCircle2 size={10} /> Active
                  </div>
                </div>
              </div>

              <div className="info-list-item">
                <div className="icon-wrapper"><Calendar size={16} /></div>
                <div className="item-content">
                  <label>Member Since</label>
                  <p>{profileData?.created_at ? new Date(profileData.created_at).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) : 'N/A'}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Activity Heatmap Placeholder */}
      <div className="profile-section-card activity-section">
        <div className="section-header">
          <h3 className="section-title"><Activity size={16} /> Recent Activity</h3>
          <span className="activity-period">Last 30 Days</span>
        </div>
        <div className="activity-placeholder-box">
          <div className="heatmap-grid">
            {Array.from({ length: 28 }).map((_, i) => (
              <div key={i} className={`heatmap-cell intensity-${Math.floor(Math.random() * 4)}`} />
            ))}
          </div>
          <div className="activity-stats">
            <div className="stat">
              <span className="value">142</span>
              <span className="label">Registrations processed</span>
            </div>
            <div className="stat">
              <span className="value">12</span>
              <span className="label">Logins this week</span>
            </div>
            <div className="stat">
              <span className="value">8</span>
              <span className="label">Documents verified</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <DashboardErrorBoundary>
    <div className={`dashboard-layout-wrapper ${isSidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="sidebar-brand">
          <div className="brand-logo">ST</div>
          <span className="brand-name">SolveTax</span>
        </div>

        <button
          className="sidebar-toggle-btn"
          onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
          aria-label={isSidebarCollapsed ? "Expand Sidebar" : "Collapse Sidebar"}
        >
          {isSidebarCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
        </button>

        <nav className="sidebar-nav">
          <div
            className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => handleTabChange('dashboard')}
            title="Dashboard"
          >
            <span className="nav-icon"><LayoutDashboard size={18} /></span>
            <span className="nav-label">Dashboard</span>
          </div>

          {hasPermission('EMPLOYEE', 'READ') && (
          <div
            className={`nav-item ${activeTab === 'employees' ? 'active' : ''}`}
            onClick={() => handleTabChange('employees')}
            title="Employees"
          >
            <span className="nav-icon"><Users size={18} /></span>
            <span className="nav-label">Employees</span>
          </div>
          )}

          <div
            className={`nav-item ${activeTab === 'customers' ? 'active' : ''}`}
            onClick={() => handleTabChange('customers')}
            title="Customers"
          >
            <span className="nav-icon"><Building2 size={18} /></span>
            <span className="nav-label">Customers</span>
          </div>


          <div className="nav-group">
            <div
              className={`nav-item ${activeTab === 'gst' ? 'active' : ''} ${isGstExpanded ? 'expanded' : ''}`}
              onClick={() => setIsGstExpanded(!isGstExpanded)}
              title="GST Portal"
            >
              <span className="nav-icon"><FileText size={18} /></span>
              <span className="nav-label">GST Portal</span>
              <span className="chevron-icon"><ChevronDown size={12} /></span>
            </div>
            <div className={`nav-sub-items-wrapper ${isGstExpanded && !isSidebarCollapsed ? 'expanded' : ''}`}>
              <div className="nav-sub-items">
                <div
                  onClick={() => handleTabChange('gst', 'registrations')}
                  className={`sub-item ${activeSubTab === 'registrations' || activeSubTab === 'people' || activeSubTab === 'documents' ? 'active' : ''}`}
                >
                  Registrations
                </div>
                {/* Filings is ADMIN + OP_MANAGER only — RM/OP have no write
                    access to any filing endpoint, so the section is hidden
                    rather than shown read-only. */}
                {showGstFilingsTab && (
                  <div
                    onClick={() => handleTabChange('gst', 'filings')}
                    className={`sub-item ${activeSubTab === 'filings' ? 'active' : ''}`}
                  >
                    Filings
                  </div>
                )}
              </div>
            </div>
          </div>

          <div
            className={`nav-item ${activeTab === 'income-tax' ? 'active' : ''}`}
            onClick={() => handleTabChange('income-tax')}
            title="Income Tax"
          >
            <span className="nav-icon"><Landmark size={18} /></span>
            <span className="nav-label">Income Tax</span>
          </div>

          <div
            className={`nav-item ${activeTab === 'payments' ? 'active' : ''}`}
            onClick={() => handleTabChange('payments')}
            title="Payments"
          >
            <span className="nav-icon"><CreditCard size={18} /></span>
            <span className="nav-label">Payments</span>
          </div>



          <div
            className={`nav-item ${activeTab === 'customer-services' ? 'active' : ''}`}
            onClick={() => handleTabChange('customer-services')}
            title="Customer Services"
          >
            <span className="nav-icon"><Briefcase size={18} /></span>
            <span className="nav-label">Customer Services</span>
          </div>

          <div
            className={`nav-item ${activeTab === 'contact-leads' ? 'active' : ''}`}
            onClick={() => handleTabChange('contact-leads', 'contact_support')}
            title="Contact / Referral"
          >
            <span className="nav-icon"><Headphones size={18} /></span>
            <span className="nav-label">Contact/Referral</span>
          </div>
        </nav>

        <div className="sidebar-footer-v2">
          <div
            className={`nav-item footer-item ${activeTab === 'knowledge' ? 'active' : ''}`}
            onClick={() => handleTabChange('knowledge')}
            title="Knowledge Base"
          >
            <span className="nav-icon"><BookOpen size={18} /></span>
            <span className="nav-label">Knowledge</span>
          </div>

          {hasPermission('SETTINGS', 'READ') && (
          <div
            className={`nav-item footer-item ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => handleTabChange('settings')}
            title="Settings Hub"
          >
            <span className="nav-icon"><SettingsIcon size={18} /></span>
            <span className="nav-label">Settings</span>
          </div>
          )}

          <div
            className={`nav-item footer-item ${activeTab === 'profile' ? 'active' : ''}`}
            onClick={() => handleTabChange('profile')}
            title="My Profile"
          >
            <span className="nav-icon"><UserCircle size={18} /></span>
            <span className="nav-label">Profile</span>
          </div>

          <ThemeToggle />
        </div>
      </aside >

      <main className="dashboard-main">
        <header className="top-workspace-bar">
          <div className="workspace-info">
            <span className="workspace-breadcrumb">
              Workspace <span className="separator">/</span>
              <span className="current-page">
                {getWorkspaceTabLabel(activeTab)}
                {activeTab === 'gst' && (
                  <>
                    <span className="separator" style={{ margin: '0 8px' }}>/</span>
                    {activeSubTab.charAt(0).toUpperCase() + activeSubTab.slice(1)}
                  </>
                )}
              </span>
            </span>
          </div>

          <div className="topbar-search-container">
            <div className="topbar-search v4-search" ref={searchRef}>
              <Search size={16} className="topbar-search-icon" />
              <input
                type="text"
                placeholder="Search customers, employees, GST, payments, docs..."
                value={globalSearchTerm}
                onChange={(e) => {
                  setGlobalSearchTerm(e.target.value);
                  if (!e.target.value) {
                    setShowGlobalSearch(false);
                    setGlobalSearchResults({
                      customers: [],
                      employees: [],
                      gstRegistrations: [],
                      gstPeople: [],
                      gstDocuments: [],
                      payments: []
                    });
                  }
                }}
                onFocus={() => {
                  if (globalSearchTerm.trim()) setShowGlobalSearch(true);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    performGlobalSearch(globalSearchTerm);
                  }
                }}
              />
              <button
                type="button"
                className="topbar-search-btn"
                onClick={() => performGlobalSearch(globalSearchTerm)}
                title="Search"
              >
                <Search size={14} />
              </button>

              {showGlobalSearch && (
                <div className="topbar-search-results v4-search-results">
                  {globalSearchLoading ? (
                    <div className="search-result-item muted">Searching...</div>
                  ) : (
                    <>
                      {globalSearchResults.customers.length === 0 &&
                        globalSearchResults.employees.length === 0 &&
                        globalSearchResults.gstRegistrations.length === 0 &&
                        globalSearchResults.gstPeople.length === 0 &&
                        globalSearchResults.gstDocuments.length === 0 &&
                        globalSearchResults.payments.length === 0 ? (
                        <div className="search-result-item muted">No results found</div>
                      ) : (
                        <div className="search-results-grid">
                          {globalSearchResults.customers.length > 0 && (
                            <div className="search-section">
                              <div className="search-section-title">Customers</div>
                              {globalSearchResults.customers.map((c) => (
                                <div key={`cust-${c.customer_id}`} className="search-result-item" onClick={() => handleSearchResultClick('customer', c)}>
                                  <div className="search-result-title">{c.full_name || `Customer ${c.customer_id}`}</div>
                                  <div className="search-result-sub">{c.mobile || c.email || c.business_name || '-'}</div>
                                </div>
                              ))}
                            </div>
                          )}
                          {globalSearchResults.employees.length > 0 && (
                            <div className="search-section">
                              <div className="search-section-title">Employees</div>
                              {globalSearchResults.employees.map((e) => (
                                <div key={`emp-${e.emp_id}`} className="search-result-item" onClick={() => handleSearchResultClick('employee', e)}>
                                  <div className="search-result-title">{e.full_name || e.username || `${e.first_name || ''} ${e.last_name || ''}`.trim() || `Employee ${e.emp_id}`}</div>
                                  <div className="search-result-sub">{e.email || e.phone_number || '-'}</div>
                                </div>
                              ))}
                            </div>
                          )}
                          {globalSearchResults.gstRegistrations.length > 0 && (
                            <div className="search-section">
                              <div className="search-section-title">GST Registrations</div>
                              {globalSearchResults.gstRegistrations.map((g) => (
                                <div key={`gst-${g.id || g.gst_registration_id}`} className="search-result-item" onClick={() => handleSearchResultClick('gst_registration', g)}>
                                  <div className="search-result-title">{g.gstin || `GST ${g.id || g.gst_registration_id}`}</div>
                                  <div className="search-result-sub">{g.business_name || g.mobile || g.email || '-'}</div>
                                </div>
                              ))}
                            </div>
                          )}
                          {globalSearchResults.gstPeople.length > 0 && (
                            <div className="search-section">
                              <div className="search-section-title">GST People</div>
                              {globalSearchResults.gstPeople.map((p) => (
                                <div key={`person-${p.person_id}`} className="search-result-item" onClick={() => handleSearchResultClick('gst_person', p)}>
                                  <div className="search-result-title">{p.full_name || `Person ${p.person_id}`}</div>
                                  <div className="search-result-sub">{p.mobile || p.email || '-'}</div>
                                </div>
                              ))}
                            </div>
                          )}
                          {globalSearchResults.gstDocuments.length > 0 && (
                            <div className="search-section">
                              <div className="search-section-title">GST Documents</div>
                              {globalSearchResults.gstDocuments.map((d) => (
                                <div key={`doc-${d.document_id}`} className="search-result-item" onClick={() => handleSearchResultClick('gst_document', d)}>
                                  <div className="search-result-title">{d.document_type || `Doc ${d.document_id}`}</div>
                                  <div className="search-result-sub">{d.gstin || `Person ${d.person_id || '-'}`}</div>
                                </div>
                              ))}
                            </div>
                          )}
                          {globalSearchResults.payments.length > 0 && (
                            <div className="search-section">
                              <div className="search-section-title">Payments</div>
                              {globalSearchResults.payments.map((p) => (
                                <div key={`pay-${p.payment_id}`} className="search-result-item" onClick={() => handleSearchResultClick('payment', p)}>
                                  <div className="search-result-title">{`Payment ${p.payment_id}`}</div>
                                  <div className="search-result-sub">{`Customer ${p.customer_id || '-'}`}</div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="workspace-actions">
            <div className="topbar-actions-group">
              <button
                className="topbar-icon-btn v4-btn"
                onClick={() => setShowRaiseIssue(true)}
                title="Report an issue"
              >
                <Bug size={20} />
              </button>
              <button
                className={`topbar-icon-btn v4-btn ${activeTab === 'notifications' ? 'active' : ''}`}
                onClick={() => handleTabChange('notifications')}
                title="Notifications"
              >
                <Bell size={20} />
                {hasNotifications && <span className="notification-dot" />}
              </button>
            </div>

            <div className="vertical-divider" style={{ margin: '0 8px' }} />

            {showCrmSwitcher && (
            <div className="crm-dropdown-container" style={{ position: 'relative' }}>
              <button
                className="topbar-icon-btn v4-btn crm-header-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowCrmDropdown(!showCrmDropdown);
                }}
                title="Open CRM Dashboard"
                style={{ 
                  padding: '0 14px', 
                  width: 'auto', 
                  borderRadius: '10px', 
                  fontSize: '12px', 
                  fontWeight: '700', 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '8px', 
                  backgroundColor: 'rgba(var(--accent-rgb), 0.08)', 
                  color: 'var(--accent)',
                  border: '1px solid rgba(var(--accent-rgb), 0.2)',
                  height: '38px',
                  transition: 'all 0.2s ease',
                  cursor: 'pointer'
                }}
              >
                <LayoutDashboard size={16} /> CRM
                <ChevronDown size={14} className={showCrmDropdown ? 'rotate' : ''} style={{ transition: 'transform 0.2s' }} />
              </button>

              {showCrmDropdown && (
                <div className="profile-dropdown-popover crm-popover" style={{ right: 0, top: 'calc(100% + 8px)' }}>
                  <button className="dropdown-item" onClick={() => { navigate('/crm-dashboard?entity_type=GST_REGISTRATION'); setShowCrmDropdown(false); }}>
                    <Shield size={14} /> <span>GST Registration</span>
                  </button>
                  <button className="dropdown-item" onClick={() => { navigate('/crm-dashboard?entity_type=INCOME_TAX'); setShowCrmDropdown(false); }}>
                    <FileText size={14} /> <span>Income Tax</span>
                  </button>
                </div>
              )}
            </div>
            )}

            <div className="vertical-divider" />



            <div className="user-profile-container">
              <div
                className={`user-profile-mini ${showProfileDropdown ? 'active' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setShowProfileDropdown(!showProfileDropdown);
                }}
              >
                <div className="mini-info">
                  <span className="user-name">
                    {profileData?.first_name || profileData?.username || 'User'}
                  </span>
                  <span className={`mini-role-badge ${profileData?.role ? getRoleCssClassFor(profileData) : ''}`}>
                    {getRoleDisplayLabel(profileData) || 'User'}
                  </span>
                  <span className="chevron-icon">
                    <ChevronDown size={14} className={showProfileDropdown ? 'rotate' : ''} />
                  </span>
                </div>
              </div>

              {showProfileDropdown && (
                <div className="profile-dropdown-popover">
                  <div className="dropdown-header">
                    <span className="dropdown-name">
                      {profileData?.first_name || profileData?.last_name
                        ? `${profileData?.first_name || ''} ${profileData?.last_name || ''}`.trim()
                        : profileData?.username || 'User'}
                    </span>
                    {profileData?.email && <span className="dropdown-email">{profileData.email}</span>}
                    <span className={`dropdown-role ${getRoleCssClassFor(profileData)}`}>{getRoleDisplayLabel(profileData) || 'User'}</span>
                  </div>

                  {(() => {
                    const currentEmail = String(profileData?.email || '').toLowerCase();
                    const otherAccounts = savedAccounts.filter(
                      (a) => String(a.emp_id) !== String(profileData?.emp_id) && a.email !== currentEmail
                    );
                    if (otherAccounts.length === 0) return null;
                    return (
                      <>
                        <div className="dropdown-divider" />
                        <div className="dropdown-section-label">Switch account</div>
                        {otherAccounts.map((acc) => (
                          <button
                            key={acc.email}
                            className="dropdown-item account-switch-item"
                            onClick={() => switchToAccount(acc.email)}
                            title={`Switch to ${acc.email}`}
                          >
                            <span className="account-avatar">{(acc.name || acc.email).charAt(0).toUpperCase()}</span>
                            <span className="account-meta">
                              <span className="account-name">{acc.name || acc.email}</span>
                              <span className="account-email">{acc.email}</span>
                            </span>
                            {acc.role && (
                              <span className={`mini-role-badge ${getRoleCssClassFor(acc)}`}>{getRoleDisplayLabel(acc)}</span>
                            )}
                          </button>
                        ))}
                      </>
                    );
                  })()}

                  <div className="dropdown-divider" />
                  <button className="dropdown-item" onClick={addAnotherAccount}>
                    <UserPlus size={14} /> <span>Add another account</span>
                  </button>
                  <button className="dropdown-item logout" onClick={handleLogout}>
                    <LogOut size={14} /> <span>Logout</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header >

        <div className={`dashboard-container-v2${activeTab === 'dashboard' ? ' dashboard-container-v2--dashboard' : ''}${activeTab === 'income-tax' ? ' dashboard-container-v2--income-tax' : ''}${activeTab === 'gst' ? ' dashboard-container-v2--gst-portal' : ''}${activeTab === 'customer-services' ? ' dashboard-container-v2--customer-services' : ''}${activeTab === 'contact-leads' ? ' dashboard-container-v2--contact-leads' : ''}${activeTab === 'payments' ? ' dashboard-container-v2--payments' : ''}${activeTab === 'customers' ? ' dashboard-container-v2--customers' : ''}${activeTab === 'employees' ? ' dashboard-container-v2--employees' : ''}${activeTab === 'settings' ? ' dashboard-container-v2--settings' : ''}`}>
          {activeTab === 'dashboard' ? (
            renderDashboardTab()
          ) : activeTab === 'gst' ? (
            activeSubTab === 'registrations' || activeSubTab === 'people' || activeSubTab === 'documents' ? (
              <GSTRegistration 
                handleLogout={handleLogout} 
                isAdmin={isAdmin} 
                profileData={profileData} 
                onNewPayment={() => handleTabChange('add-payment')}
                initialSubTab={activeSubTab} 
              />
            ) :
              activeSubTab === 'filings' && showGstFilingsTab ? (
                <GSTFilings
                  handleLogout={handleLogout}
                  isAdmin={isAdmin}
                  profileData={profileData}
                  onNewPayment={() => handleTabChange('add-payment')}
                />
              ) : null
          ) : activeTab === 'employees' ? (
            <Employee handleLogout={handleLogout} canSignup={canSignup} isAdmin={isAdmin} profileData={profileData} />
          ) : activeTab === 'customers' ? (
            <Customer handleLogout={handleLogout} isAdmin={isAdmin} profileData={profileData} />
          ) : activeTab === 'income-tax' ? (
            <IncomeTax isAdmin={isAdmin} profileData={profileData} />
          ) : activeTab === 'customer-services' ? (
            <CustomerServices isAdmin={isAdmin} profileData={profileData} setToastMessage={setToastMessage} />
          ) : activeTab === 'contact-leads' ? (
            <ContactSupportLeads />
          ) : activeTab === 'payments' ? (
            <Payments
              handleLogout={handleLogout}
              isAdmin={isAdmin}
              onNewPayment={() => handleTabChange('add-payment')}
            />
          ) : activeTab === 'add-payment' ? (
            <AddPayment 
              onBack={() => {
                const params = new URLSearchParams(location.search);
                const returnTab = params.get('return_tab') || 'payments';
                const returnSub = params.get('return_sub') || null;
                const returnView = params.get('return_view');
                const returnCategory = params.get('return_category');
                const backParams = new URLSearchParams();
                backParams.set('tab', returnTab);
                if (returnSub) backParams.set('sub', returnSub);
                if (returnView) backParams.set('filing_view', returnView);
                if (returnCategory) backParams.set('category', returnCategory);
                navigate(`/dashboard?${backParams.toString()}`);
              }}
              isAdmin={isAdmin} 
              initialEntityId={new URLSearchParams(location.search).get('entity_id')} 
              initialServiceType={new URLSearchParams(location.search).get('service_type') || undefined}
            />
          ) : activeTab === 'knowledge' ? (
            <Knowledge />

          ) : activeTab === 'settings' ? (
            <SettingsTab isAdmin={isAdmin} setToastMessage={setToastMessage} />
          ) : activeTab === 'profile' ? (
            renderProfileTab()
          ) : activeTab === 'notifications' ? (
            <NotificationsTab />
          ) : null}
        </div>
      </main >

      {/* Edit Profile Modal (Glassmorphic Premium V4) */}
      {
        isEditProfileOpen && (
          <div className="premium-filter-overlay show" onClick={() => setIsEditProfileOpen(false)}>
            <div className="premium-edit-modal-v4" onClick={e => e.stopPropagation()}>
              <div className="edit-modal-grid-v4">
                {/* Left Column: Header & Security */}
                <div className="edit-modal-col-left-v4">
                  <div className="edit-modal-header-v4 vertical">
                    <div className="header-brand-icon-v4">
                      <UserCircle size={32} />
                    </div>
                    <div className="header-text-content-v4">
                      <h3>Edit Profile</h3>
                      <p>{profileData?.emp_id || 'Employee'}</p>
                    </div>
                  </div>

                  <div className="edit-modal-security-section-v4">
                    <div className="security-info-v4">
                      <ShieldCheck size={16} />
                      <span>Security & Access</span>
                    </div>
                    <button
                      type="button"
                      className="cp-trigger-btn-minimal-v4"
                      onClick={() => setIsChangePasswordOpen(true)}
                    >
                      <Lock size={14} /> Change Your Password
                    </button>
                  </div>
                </div>

                {/* Right Column: Form Fields */}
                <div className="edit-modal-col-right-v4">
                  <button
                    className="btn-close-modal-v4-top"
                    onClick={() => setIsEditProfileOpen(false)}
                    disabled={editProfileLoading}
                  >
                    <X size={20} />
                  </button>

                  {/* Global Error Banner for Non-Field Specific Errors */}
                  {fieldErrors._global && (
                    <div className="modal-global-error-banner">
                      <span>{fieldErrors._global}</span>
                    </div>
                  )}

                  <div className="edit-modal-body-v4">
                    {editProfileFetching && (
                      <div className="modal-inner-loading-overlay">
                        <Loader2 className="spin" size={24} />
                        <p>Fetching latest details...</p>
                      </div>
                    )}
                    <form id="editProfileForm" onSubmit={handleSaveProfile} className={editProfileFetching ? 'content-blur' : ''}>
                      <div className="premium-edit-grid-v4">
                        <div className="input-group-v4">
                          <label><UserCircle size={14} /> First Name</label>
                          <div className="input-wrapper-v4">
                            <input
                              type="text"
                              name="first_name"
                              value={editProfileData.first_name || ''}
                              onChange={handleEditProfileChange}
                              required
                              placeholder="e.g. John"
                            />
                          </div>
                          {fieldErrors.first_name && <span className="input-error-text"><AlertCircle size={12} /> {fieldErrors.first_name}</span>}
                        </div>

                        <div className="input-group-v4">
                          <label><UserCircle size={14} /> Last Name</label>
                          <div className="input-wrapper-v4">
                            <input
                              type="text"
                              name="last_name"
                              value={editProfileData.last_name || ''}
                              onChange={handleEditProfileChange}
                              placeholder="e.g. Doe"
                            />
                          </div>
                          {fieldErrors.last_name && <span className="input-error-text"><AlertCircle size={12} /> {fieldErrors.last_name}</span>}
                        </div>

                        <div className="input-group-v4 full">
                          <label><Mail size={14} /> Email Address</label>
                          <div className="input-wrapper-v4">
                            <input
                              type="email"
                              name="email"
                              value={editProfileData.email || ''}
                              onChange={handleEditProfileChange}
                              required
                              placeholder="john.doe@solvetax.in"
                            />
                          </div>
                          {fieldErrors.email && <span className="input-error-text"><AlertCircle size={12} /> {fieldErrors.email}</span>}
                        </div>

                        <div className="input-group-v4 full">
                          <label><ShieldCheck size={14} /> System Username</label>
                          <div className="input-wrapper-v4">
                            <input
                              type="text"
                              name="username"
                              value={editProfileData.username || ''}
                              onChange={handleEditProfileChange}
                              required
                              className="mono-text"
                              placeholder="johndoe"
                            />
                          </div>
                          {fieldErrors.username && <span className="input-error-text"><AlertCircle size={12} /> {fieldErrors.username}</span>}
                        </div>

                        <div className="input-group-v4 full">
                          <label><Phone size={14} /> Mobile Number</label>
                          <div className="input-wrapper-v4">
                            <input
                              type="tel"
                              name="phone_number"
                              value={editProfileData.phone_number || ''}
                              onChange={handleEditProfileChange}
                              placeholder="+91 99999 99999"
                            />
                          </div>
                          {fieldErrors.phone_number && <span className="input-error-text"><AlertCircle size={12} /> {fieldErrors.phone_number}</span>}
                        </div>
                      </div>
                    </form>
                  </div>

                  <div className="edit-modal-footer-v4">
                    <button
                      className="btn-cancel-v4"
                      onClick={() => setIsEditProfileOpen(false)}
                      type="button"
                      disabled={editProfileLoading}
                    >
                      Cancel
                    </button>
                    <button
                      className="btn-save-v4"
                      type="submit"
                      form="editProfileForm"
                      disabled={editProfileLoading}
                    >
                      {editProfileLoading ? (
                        <>
                          <Loader2 className="spin" size={16} />
                          <span>Saving...</span>
                        </>
                      ) : 'Save Profile'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )
      }

      {/* Change Password Modal (v4 Aesthetics) */}
      <ChangePasswordModal
        isOpen={isChangePasswordOpen}
        onClose={() => setIsChangePasswordOpen(false)}
        empId={profileData?.emp_id}
        setToastMessage={setToastMessage}
      />

      {/* Report-an-issue drawer (opened from the topbar bug button) */}
      {showRaiseIssue && (
        <RaiseIssueModal
          onClose={() => setShowRaiseIssue(false)}
          onCreated={() => setToastMessage('Issue reported. Thank you!')}
        />
      )}

      {/* Global Toast Notification Engine (Stacked v4 Architecture) - 15s Persistence */}
      <div className="st-toast-stack-container">
        {toasts.map((toast) => (
          <div 
            key={toast.id} 
            className={`toast-notification v4 show ${toast.variant === 'urgent' ? 'urgent' : 'success'}`}
          >
            <div className="toast-main-content">
              <div className="toast-icon-side">
                {toast.variant === 'urgent' ? (
                  <AlertCircle size={18} className="toast-icon error" />
                ) : (
                  <CheckCircle2 size={18} className="toast-icon success" />
                )}
              </div>
              <div className="toast-text-content">
                <span className="toast-message-v4">
                  {typeof toast.message === 'object'
                    ? (toast.message?.text ?? toast.message?.message ?? '')
                    : toast.message}
                </span>
              </div>
            </div>
            
            {toast.action && (
              <button 
                className="btn-toast-action-v4"
                onClick={(e) => {
                  e.stopPropagation();

                  if (toast.action.path) {
                    navigate(toast.action.path);
                    const gstFocus = resolveGstFocusFromAction(toast.action);
                    if (gstFocus) dispatchGstFilingFocusOpen(gstFocus);
                    removeToast(toast.id);
                    return;
                  }
                  
                  // Hybrid Redirection Signal
                  if (toast.action.taskId) {
                    window.dispatchEvent(new CustomEvent('st_open_followup', { 
                      detail: { 
                        taskId: toast.action.taskId,
                        category: toast.action.category || 'services',
                      } 
                    }));
                  }

                  const params = new URLSearchParams();
                  params.set('tab', 'dashboard');
                  params.set('sub', 'followups');
                  params.set('category', toast.action.category || 'services');
                  params.set('complete_task_id', toast.action.taskId);
                  navigate(`/dashboard?${params.toString()}`);
                  removeToast(toast.id);
                }}
              >
                {toast.action.label}
              </button>
            )}

            <button className="btn-toast-close" onClick={() => removeToast(toast.id)}>
              <X size={14} />
            </button>

            {/* Visual Progress Bar (15s Countdown) */}
            <div className="toast-progress-container-v4">
              <div className="toast-progress-bar-v4" />
            </div>
          </div>
        ))}
      </div>
    </div >
    </DashboardErrorBoundary>
  );
};

export default Dashboard;
