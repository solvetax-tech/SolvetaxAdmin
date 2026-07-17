import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  Target,
  FileSpreadsheet,
  Bell,
  ChevronLeft,
  ChevronRight,
  LogOut,
  ChevronDown,
  TrendingUp,
  PieChart,
  BarChart3,
  ArrowRight,
  Workflow,
  BookOpen,
  UserCircle,
  Camera,
  Edit2,
  Shield,
  Clock,
  Activity,
  Mail,
  Phone,
  Hash,
  Calendar,
  ShieldCheck,
  CheckCircle2,
  MoreVertical,
  Lock,
  Loader2,
  X,
  History,
  Search,
  FileText,
  AlertCircle,
  Settings,
} from 'lucide-react';
import './crm_dashboard.css';
import api from '../../utils/api';
import { unwrapListPayload } from '../../utils/apiResponse';
import {
  CRM_TAB_PAYMENT_PENDING,
  CRM_TAB_TODAY_ASSIGNED,
  CRM_TAB_DISPLAY_NAMES,
  PAYMENT_PENDING_BOARD_FILTERS,
  PAYMENT_PENDING_BOARD_LABEL,
  TODAY_ASSIGNED_BOARD_LABEL,
} from './crmLeadBoardPresets';

import Leads from './leads/Leads';
import SmartBoard from './smart_board/SmartBoard';
import PipelineStages from './PipelineStage/PipelineStages';
import CRMKnowledge from './crm_knowledge/CRMKnowledge';
import CRMNotifications from './notifications/CRMNotifications';
import CRMHistory from './crm_history/CRMHistory';
import BulkAssign from './crm_history/BulkAssign';
import ImportLeads from './crm_history/ImportLeads';
import ChangePasswordModal from '../profile/ChangePasswordModal';
import ThemeToggle from '../common/ThemeToggle';
import CrmDashboardAnalytics from './CrmDashboardAnalytics';

const ALLOWED_IMPORT_USERS = ['bhanuvenkatsrikakulapu8@gmail.com'];

// Hooks & Utils
import useCrmFollowupReminders from '../../hooks/crmFollowUpRemainders';

class CrmDashboardErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[CrmDashboard] render error:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="crm-layout-wrapper">
          <div className="crm-main" style={{ padding: 32 }}>
            <div className="crm-dashboard-empty">
              <AlertCircle size={40} style={{ color: 'var(--danger)', marginBottom: 16 }} />
              <h2 style={{ color: 'var(--text-primary)', marginBottom: 8 }}>CRM dashboard failed to load</h2>
              <p style={{ color: 'var(--text-muted)', maxWidth: 480, marginBottom: 16 }}>
                {this.state.error?.message || 'An unexpected error occurred. Try a hard refresh (Ctrl+Shift+R).'}
              </p>
              <button
                type="button"
                className="crm-main-system-btn"
                onClick={() => window.location.reload()}
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const CrmDashboard = ({ onLogout }) => {
  const navigate = useNavigate();
  const [activeEntityType, setActiveEntityType] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('entity_type') || 'GST_REGISTRATION';
  });
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [activeCrmTab, setActiveCrmTab] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('target_lead_id')) return 'leads';
    if (params.get('entity_id')) return 'leads';
    return 'dashboard';
  });
  const [activeSettingsTab, setActiveSettingsTab] = useState('activities'); // 'bulk-assign', 'import', 'activities'
  const [profileData, setProfileData] = useState(null);
  const [profileLoadFailed, setProfileLoadFailed] = useState(false);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);
  const [isPipelineExpanded, setIsPipelineExpanded] = useState(false);
  const [selectedPipelineStage, setSelectedPipelineStage] = useState(null);
  const [stages, setStages] = useState([]);
  const [analyticsData, setAnalyticsData] = useState({
    total: 0,
    scheduled: 0,
    completed: 0,
    overdue: 0,
    pending: 0,
    completionRate: 0
  });
  const [recentActivities, setRecentActivities] = useState([]);
  const [activitiesLoading, setActivitiesLoading] = useState(false);
  const [selectedCalendarDate, setSelectedCalendarDate] = useState(null);
  const [globalSearchInput, setGlobalSearchInput] = useState('');
  const [activeSearchTerm, setActiveSearchTerm] = useState('');
  const calendarLeadsRef = useRef(null);

  // Profile management state
  const [isEditProfileOpen, setIsEditProfileOpen] = useState(false);
  const [editProfileData, setEditProfileData] = useState({
    first_name: '', last_name: '', email: '', phone_number: '', username: ''
  });
  const [editProfileLoading, setEditProfileLoading] = useState(false);
  const [editProfileFetching, setEditProfileFetching] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [hasNotifications, setHasNotifications] = useState(false);
  const [targetLeadId, setTargetLeadId] = useState(null);
  const [targetEntityId, setTargetEntityId] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('entity_id') || null;
  });
  const [targetView, setTargetView] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('target_view') || null;
  });
  const [targetCallStatus, setTargetCallStatus] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('target_call_status') || null;
  });
  const lastSyncedUrlLeadId = useRef(null);
  const lastSyncedUrlEntityId = useRef(null);
  const [showEntityDropdown, setShowEntityDropdown] = useState(false);
  const [todayAssignedScope, setTodayAssignedScope] = useState({ rmTeamIds: [], opTeamIds: [] });
  const [leadOpenSeq, setLeadOpenSeq] = useState(0);

  const isAllowedImport = useMemo(() => {
    if (!profileData) return false;
    const userEmail = (profileData.email || '').toLowerCase();
    const username = (profileData.username || '').toLowerCase();
    return ALLOWED_IMPORT_USERS.some(u => {
      const allowed = u.toLowerCase();
      return userEmail === allowed || username === allowed;
    });
  }, [profileData]);

  const isAdmin = useMemo(
    () => String(profileData?.role || '').toUpperCase() === 'ADMIN',
    [profileData]
  );
  const isIncomeTaxCrm = activeEntityType === 'INCOME_TAX';
  const isTodayAssignedRole = useMemo(() => {
    const role = String(profileData?.role || '').toUpperCase();
    return ['ADMIN', 'RM', 'OP', 'SALES_MANAGER', 'OP_MANAGER'].includes(role);
  }, [profileData?.role]);

  useEffect(() => {
    if (!isIncomeTaxCrm && activeCrmTab === CRM_TAB_PAYMENT_PENDING) {
      setActiveCrmTab('leads');
    }
  }, [isIncomeTaxCrm, activeCrmTab]);

  // --- Follow-up Reminders ---
  const toastSetter = useCallback((msg, variant) => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message: msg, variant }]);
  }, []);
  
  useCrmFollowupReminders(profileData, toastSetter, activeEntityType);

  // --- Toast Manager & Event Listeners ---
  useEffect(() => {
    const checkNotifications = () => {
      try {
        const notifs = JSON.parse(localStorage.getItem('st_crm_notifications') || '[]');
        setHasNotifications(notifs.length > 0);
      } catch (err) {
        console.error("Failed to check CRM notifications:", err);
      }
    };

    const handleGlobalToast = (event) => {
      const { message, action, variant = 'success' } = event.detail || {};
      if (message) {
        const id = Date.now() + Math.random();
        setToasts(prev => [...prev, { id, message, action, variant }]);
      }
    };

    const handleOpenRedirect = (event) => {
      const { taskId, leadId, view } = event.detail || {};
      const actualId = leadId || taskId;
      if (actualId) {
        console.log(`[CrmDashboard] Redirecting to Lead: ${actualId} (View: ${view || 'default'})`);
        setTargetLeadId(actualId);
        if (view) setTargetView(view);
        setActiveCrmTab('leads');
      }
    };

    checkNotifications();
    window.addEventListener('st_crm_notifications_updated', checkNotifications);
    window.addEventListener('st_show_toast', handleGlobalToast);
    window.addEventListener('st_open_crm_lead', handleOpenRedirect); // Unified CRM deep-link event

    return () => {
      window.removeEventListener('st_crm_notifications_updated', checkNotifications);
      window.removeEventListener('st_show_toast', handleGlobalToast);
      window.removeEventListener('st_open_crm_lead', handleOpenRedirect);
    };
  }, []);

  // Close entity dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      const dropdown = document.querySelector('.entity-switcher-container');
      if (dropdown && !dropdown.contains(event.target)) {
        setShowEntityDropdown(false);
      }
    };

    if (showEntityDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
    } else {
      document.removeEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showEntityDropdown]);

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

  // Sync target redirection from URL if present (Robust Sync)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlLeadId = params.get('target_lead_id');
    const urlEntityId = params.get('entity_id');
    const urlView = params.get('target_view');
    const urlCallStatus = params.get('target_call_status');
    const urlEntityType = params.get('entity_type');
    if (urlEntityType) {
      setActiveEntityType(urlEntityType);
    }
    if (urlEntityId && urlEntityId !== lastSyncedUrlEntityId.current) {
      lastSyncedUrlEntityId.current = urlEntityId;
      setTargetEntityId(urlEntityId);
      setActiveCrmTab('leads');
    }
    if (urlLeadId) {
      if (urlLeadId !== lastSyncedUrlLeadId.current || urlView !== null) {
        lastSyncedUrlLeadId.current = urlLeadId;
        setTargetLeadId(urlLeadId);
        if (urlView) setTargetView(urlView);
        setTargetCallStatus(urlCallStatus || null);
        setActiveCrmTab('leads');
      }
    } else if (urlEntityId) {
      setTargetView(urlView || null);
      setActiveCrmTab('leads');
    }
    if (urlCallStatus) {
      setTargetCallStatus(urlCallStatus);
    } else if (urlEntityId && !urlView) {
      setTargetCallStatus(null);
    }
  }, [window.location.search]);

  const leadsInitialFilters = useMemo(() => {
    const filters = {};
    if (activeSearchTerm) filters.mobile = activeSearchTerm;
    if (targetEntityId) filters.entity_id = String(targetEntityId);
    return Object.keys(filters).length > 0 ? filters : null;
  }, [activeSearchTerm, targetEntityId]);

  // Toast Auto-Cleanup
  useEffect(() => {
    if (toasts.length > 0) {
      const timer = setTimeout(() => {
        setToasts(prev => prev.slice(1));
      }, 15000);
      return () => clearTimeout(timer);
    }
  }, [toasts]);

  // Fetch lead stages
  useEffect(() => {
    const fetchStages = async () => {
      try {
        const res = await api.get('/api/v1/crm/leads/stages', { params: { entity_type: activeEntityType } });
        const rawStages = res.data?.stages ?? res.data?.data?.stages;
        setStages(Array.isArray(rawStages) ? rawStages : []);
      } catch (err) {
        console.error("Failed to fetch lead stages:", err);
      }
    };
    fetchStages();
  }, [activeEntityType]);

  // Fetch profile data
  useEffect(() => {
    const fetchProfile = async () => {
      try {
        setProfileLoadFailed(false);
        const token = localStorage.getItem('session_token');
        if (!token) {
          setProfileLoadFailed(true);
          return;
        }
        const parts = token.split('.');
        if (parts.length < 2) {
          setProfileLoadFailed(true);
          return;
        }
        const payload = JSON.parse(atob(parts[1]));
        const empId = payload.sub;
        if (empId) {
          const res = await api.get(`/api/v1/employees/employee/${empId}`);
          setProfileData(res.data?.data || res.data);
        } else {
          setProfileLoadFailed(true);
        }
      } catch (err) {
        console.error("Failed to fetch profile:", err);
        setProfileLoadFailed(true);
      }
    };
    fetchProfile();
  }, []);

  // Redirect non-admins away from restricted settings tabs
  useEffect(() => {
    if (activeCrmTab === 'settings' && activeSettingsTab === 'bulk-assign' && profileData && !isAdmin) {
      setActiveSettingsTab('activities');
    }
    if (activeCrmTab === 'settings' && activeSettingsTab === 'import' && profileData && !isAllowedImport) {
      setActiveSettingsTab('activities');
    }
  }, [activeCrmTab, activeSettingsTab, profileData, isAdmin, isAllowedImport]);

  useEffect(() => {
    const role = String(profileData?.role || '').toUpperCase();
    const selfEmpId = Number(profileData?.emp_id) || null;
    if (!selfEmpId || (role !== 'SALES_MANAGER' && role !== 'OP_MANAGER')) {
      setTodayAssignedScope({ rmTeamIds: [], opTeamIds: [] });
      return;
    }

    let cancelled = false;
    const fetchTeamScope = async () => {
      try {
        const res = await api.get('/api/v1/employees/filter?is_active=true&limit=100');
        const rows = unwrapListPayload(res).items;
        const directReports = rows.filter((e) => Number(e?.manager_emp_id) === selfEmpId);
        const rmTeamIds = directReports
          .filter((e) => String(e?.role || '').toUpperCase() === 'RM')
          .map((e) => Number(e.emp_id))
          .filter(Boolean);
        const opTeamIds = directReports
          .filter((e) => String(e?.role || '').toUpperCase() === 'OP')
          .map((e) => Number(e.emp_id))
          .filter(Boolean);
        if (!cancelled) {
          setTodayAssignedScope({ rmTeamIds, opTeamIds });
        }
      } catch (err) {
        console.error('Failed to load manager team scope:', err);
        if (!cancelled) setTodayAssignedScope({ rmTeamIds: [], opTeamIds: [] });
      }
    };

    fetchTeamScope();
    return () => {
      cancelled = true;
    };
  }, [profileData?.role, profileData?.emp_id]);

  // Dashboard tab is intentionally empty (nav item kept in sidebar).
  
  // Auto-clear search results when input is cleared
  useEffect(() => {
    if (globalSearchInput === '') {
      setActiveSearchTerm('');
    }
  }, [globalSearchInput]);

  const handleLogout = useCallback(() => {
    if (onLogout) onLogout();
    navigate('/login');
  }, [onLogout, navigate]);

  const setToastMessage = (msg, variant = 'success') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message: msg, variant }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 5000);
  };

  const handleLeadOpened = useCallback(() => {
    setTargetLeadId(null);
    setTargetEntityId(null);
    lastSyncedUrlEntityId.current = null;
    setTargetView(null);
    setTargetCallStatus(null);
  }, []);

  const handleOpenLeadFromDashboard = useCallback(({ leadId, view }) => {
    if (leadId == null || leadId === '') return;
    setTargetEntityId(null);
    setTargetCallStatus(null);
    setTargetLeadId(String(leadId));
    setTargetView(view || 'history');
    setLeadOpenSeq((n) => n + 1);
    setActiveCrmTab('leads');
  }, []);

  const formatDateTime = (dateStr) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    return `${d}-${m}-${y} ${hh}:${mm}`;
  };

  const handleOpenEditProfile = async () => {
    setEditProfileData({
      first_name: profileData?.first_name || '',
      last_name: profileData?.last_name || '',
      email: profileData?.email || '',
      phone_number: profileData?.phone_number || '',
      username: profileData?.username || ''
    });
    setFieldErrors({});
    setIsEditProfileOpen(true);

    if (profileData?.emp_id) {
      try {
        setEditProfileFetching(true);
        const res = await api.get(`/api/v1/employees/employee/${profileData.emp_id}`);
        const freshData = res.data?.data || res.data;
        setEditProfileData({
          first_name: freshData.first_name || '',
          last_name: freshData.last_name || '',
          email: freshData.email || '',
          phone_number: freshData.phone_number || '',
          username: freshData.username || ''
        });
        setProfileData(prev => ({ ...prev, ...freshData }));
      } catch (err) {
        console.error("Failed to fetch fresh profile data:", err);
      } finally {
        setEditProfileFetching(false);
      }
    }
  };

  const handleEditProfileChange = (e) => {
    const { name, value } = e.target;
    setEditProfileData(prev => ({ ...prev, [name]: value }));
    if (fieldErrors[name]) setFieldErrors(prev => ({ ...prev, [name]: null }));
  };

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setEditProfileLoading(true);
    setFieldErrors({});

    try {
      const response = await api.post(`/api/v1/employees/${profileData.emp_id}/emp_dyn/edit`, editProfileData);
      const updatedProfile = response.data?.data || response.data;
      setProfileData(prev => ({ ...prev, ...updatedProfile }));
      setIsEditProfileOpen(false);
      setToastMessage('Profile updated successfully! âœ¨');
    } catch (err) {
      console.error("Failed to update profile", err);
      const detail = err.response?.data?.detail;
      if (typeof detail === 'object' && detail?.error?.fields) {
        setFieldErrors(detail.error.fields);
      } else {
        setFieldErrors({ _global: typeof detail === 'string' ? detail : 'Failed to update profile' });
      }
    } finally {
      setEditProfileLoading(false);
    }
  };

  const getTimeAtCompany = (dateString) => {
    if (!dateString) return 'N/A';
    const start = new Date(dateString);
    if (isNaN(start.getTime())) return 'N/A';
    const now = new Date();
    const diffDays = Math.ceil(Math.abs(now - start) / (1000 * 60 * 60 * 24));
    if (diffDays < 30) return `${diffDays} Days`;
    const months = Math.floor(diffDays / 30);
    if (months < 12) return `${months} Months`;
    return `${Math.floor(months / 12)}Y ${months % 12}M`;
  };

  const renderProfileTab = () => (
    <div className="profile-container-v3">
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
              <span className="role-badge-v3">
                <Shield size={12} className="role-icon" />
                {profileData?.role || 'User'}
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
              <span className="label">Activities Logging</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const handleGlobalSearch = (e) => {
    e.preventDefault();
    
    // Switch to leads tab
    setActiveCrmTab('leads');
    setSelectedPipelineStage(null);
    setSelectedCalendarDate(null);
    setActiveSearchTerm(globalSearchInput);
  };

  const renderCRMCalendar = () => {
    const now = new Date();
    const currentMonth = now.toLocaleString('en-US', { month: 'long', year: 'numeric' });
    const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1).getDay();
    const today = now.getDate();

    const handleDateClick = (day) => {
      if (!day) return;
      const clickedDate = new Date(now.getFullYear(), now.getMonth(), day);
      setSelectedCalendarDate(clickedDate);
      
      // Auto-scroll to leads table
      setTimeout(() => {
        calendarLeadsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 100);
    };

    const days = [];
    for (let i = 0; i < firstDay; i++) days.push(null);
    for (let i = 1; i <= daysInMonth; i++) days.push(i);

    return (
      <div className="crm-calendar-widget">
        <div className="calendar-header">
          <span className="month-name">{currentMonth}</span>
          <Calendar size={14} className="cal-icon" />
        </div>
        <div className="calendar-grid">
          {['S','M','T','W','T','F','S'].map(d => <div key={d} className="weekday">{d}</div>)}
          {days.map((day, idx) => {
            const isPast = day && day < today;
            const isSelected = selectedCalendarDate && 
                             selectedCalendarDate.getDate() === day && 
                             selectedCalendarDate.getMonth() === now.getMonth() &&
                             selectedCalendarDate.getFullYear() === now.getFullYear();
            const showToday = day === today && (!selectedCalendarDate || isSelected);

            return (
              <div 
                key={idx} 
                className={`calendar-day ${isSelected ? 'selected' : ''} ${showToday ? 'today' : ''} ${!day ? 'empty' : ''} ${day ? 'clickable' : ''} ${day && isPast ? 'past' : ''}`}
                onClick={() => day && handleDateClick(day)}
              >
                {day}
                {day && (Math.random() > 0.8) && <div className="event-dot" />}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const renderActivityFeed = () => (
    <div className="activity-feed-timeline">
      {recentActivities.length === 0 ? (
        <div className="empty-feed">
          <Activity size={32} strokeWidth={1} />
          <p>No recent activities found</p>
        </div>
      ) : (
        recentActivities.map((act, i) => (
          <div className="activity-item-v4" key={act.id || i}>
            <div className={`activity-icon-v4 ${act.activity_type.toLowerCase()}`}>
              {act.activity_type === 'CALL' ? <Phone size={14} /> : <Activity size={14} />}
            </div>
            <div className="activity-details-v4">
              <div className="activity-header-v4">
                <span className="user-name">Lead {act.lead_id}</span>
                <span className="time-stamp">Last Dialed at: {formatDateTime(act.performed_at)}</span>
              </div>
              <p className="activity-text-v4">
                {act.activity_type === 'CALL' ? (
                  <><strong>Call Status:</strong> {act.call_status_code.replace(/_/g, ' ')}</>
                ) : 'Status updated'}
              </p>
              {act.remarks && <p className="activity-remarks-v4"><strong>Remarks:</strong> {act.remarks}</p>}
            </div>
          </div>
        ))
      )}
    </div>
  );

  const renderAnalytics = () => (
    <CrmDashboardAnalytics
      activeEntityType={activeEntityType}
      isActive={activeCrmTab === 'dashboard'}
      profileData={profileData}
      profileLoadFailed={profileLoadFailed}
      stages={stages}
      onOpenLead={handleOpenLeadFromDashboard}
    />
  );


  return (
    <CrmDashboardErrorBoundary>
    <div className={`crm-layout-wrapper ${isSidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="crm-sidebar">
        <div className="sidebar-brand">
          <div className="brand-logo crm">CRM</div>
          <span className="brand-name">SolveTax <span className="sub-brand">Hub</span></span>
        </div>

        <button
          className="sidebar-toggle-btn"
          onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        >
          {isSidebarCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
        </button>

        <nav className="sidebar-nav">
          <div
            className={`nav-item ${activeCrmTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveCrmTab('dashboard')}
          >
            <span className="nav-icon"><LayoutDashboard size={18} /></span>
            <span className="nav-label">Dashboard</span>
          </div>

          {activeCrmTab === 'settings' ? (
            <>
              {isAllowedImport && (
                <div
                  className={`nav-item ${activeSettingsTab === 'import' ? 'active' : ''}`}
                  onClick={() => setActiveSettingsTab('import')}
                >
                  <span className="nav-icon"><FileSpreadsheet size={18} /></span>
                  <span className="nav-label">Import Leads</span>
                </div>
              )}

              {isAdmin && (
                <div
                  className={`nav-item ${activeSettingsTab === 'bulk-assign' ? 'active' : ''}`}
                  onClick={() => setActiveSettingsTab('bulk-assign')}
                >
                  <span className="nav-icon"><Users size={18} /></span>
                  <span className="nav-label">Bulk Assign</span>
                </div>
              )}

              <div
                className={`nav-item ${activeSettingsTab === 'activities' ? 'active' : ''}`}
                onClick={() => setActiveSettingsTab('activities')}
              >
                <span className="nav-icon"><Activity size={18} /></span>
                <span className="nav-label">Activities</span>
              </div>
            </>
          ) : (
            <>
              <div
                className={`nav-item ${activeCrmTab === 'leads' ? 'active' : ''}`}
                onClick={() => {
                  setActiveCrmTab('leads');
                  setSelectedPipelineStage(null);
                }}
              >
                <span className="nav-icon"><Target size={18} /></span>
                <span className="nav-label">Leads</span>
              </div>

              {isIncomeTaxCrm && (
                <div
                  className={`nav-item nav-item--board-preset ${activeCrmTab === CRM_TAB_PAYMENT_PENDING ? 'active' : ''}`}
                  onClick={() => {
                    setActiveCrmTab(CRM_TAB_PAYMENT_PENDING);
                    setSelectedPipelineStage(null);
                  }}
                  title={PAYMENT_PENDING_BOARD_LABEL}
                >
                  <span className="nav-icon"><Clock size={18} /></span>
                  <span className="nav-label nav-label--wrap">Payment done service pending</span>
                </div>
              )}

              <div
                className={`nav-item ${activeCrmTab === 'smart-board' ? 'active' : ''}`}
                onClick={() => {
                  setActiveCrmTab('smart-board');
                  setSelectedPipelineStage(null);
                }}
              >
                <span className="nav-icon"><TrendingUp size={18} /></span>
                <span className="nav-label">Smart Board</span>
              </div>

              {isTodayAssignedRole && (
                <div
                  className={`nav-item nav-item--board-preset ${activeCrmTab === CRM_TAB_TODAY_ASSIGNED ? 'active' : ''}`}
                  onClick={() => {
                    setActiveCrmTab(CRM_TAB_TODAY_ASSIGNED);
                    setSelectedPipelineStage(null);
                  }}
                  title={TODAY_ASSIGNED_BOARD_LABEL}
                >
                  <span className="nav-icon"><Clock size={18} /></span>
                  <span className="nav-label nav-label--wrap">{TODAY_ASSIGNED_BOARD_LABEL}</span>
                </div>
              )}

              <div className="nav-group">
                <div
                  className={`nav-item ${activeCrmTab === 'pipeline' ? 'active' : ''} ${isPipelineExpanded ? 'expanded' : ''}`}
                  onClick={() => setIsPipelineExpanded(!isPipelineExpanded)}
                >
                  <span className="nav-icon"><Workflow size={18} /></span>
                  <span className="nav-label">Pipeline</span>
                  <span className="chevron-icon"><ChevronDown size={14} /></span>
                </div>
                
                <div className={`nav-sub-items-wrapper ${isPipelineExpanded && !isSidebarCollapsed ? 'expanded' : ''}`}>
                  <div className="nav-sub-items">
                    {(Array.isArray(stages) ? stages : []).map(stage => (
                      <div
                        key={stage.id || stage.code}
                        className={`sub-item ${selectedPipelineStage === stage.code ? 'active' : ''}`}
                        onClick={() => {
                          setActiveCrmTab('pipeline');
                          setSelectedPipelineStage(stage.code);
                        }}
                      >
                        {stage.name}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </nav>

        <div className="sidebar-footer-v2">
          {activeCrmTab === 'settings' ? (
            <div
              className="nav-item footer-item"
              onClick={() => setActiveCrmTab('leads')}
            >
              <span className="nav-icon"><ChevronLeft size={18} /></span>
              <span className="nav-label">Back to CRM</span>
            </div>
          ) : (
            <>
              <div
                className={`nav-item footer-item ${activeCrmTab === 'knowledge' ? 'active' : ''}`}
                onClick={() => setActiveCrmTab('knowledge')}
              >
                <span className="nav-icon"><BookOpen size={18} /></span>
                <span className="nav-label">Knowledge</span>
              </div>

              <div
                className={`nav-item footer-item ${activeCrmTab === 'settings' ? 'active' : ''}`}
                onClick={() => {
                  setActiveCrmTab('settings');
                  setActiveSettingsTab('activities');
                }}
              >
                <span className="nav-icon"><Settings size={18} /></span>
                <span className="nav-label">Settings</span>
              </div>

              <div
                className={`nav-item footer-item ${activeCrmTab === 'profile' ? 'active' : ''}`}
                onClick={() => setActiveCrmTab('profile')}
              >
                <span className="nav-icon"><UserCircle size={18} /></span>
                <span className="nav-label">Profile</span>
              </div>
            </>
          )}

          <ThemeToggle />
        </div>
      </aside>

      <main className="crm-main">
        <header className="top-workspace-bar">
          <div className="workspace-info">
            <span className="workspace-breadcrumb">
              CRM <span className="separator">/</span>
              <span className="current-page">
                {activeCrmTab === 'pipeline' && selectedPipelineStage 
                  ? `Pipeline / ${stages.find(s => s.code === selectedPipelineStage)?.name || selectedPipelineStage}`
                  : (CRM_TAB_DISPLAY_NAMES[activeCrmTab] || activeCrmTab.charAt(0).toUpperCase() + activeCrmTab.slice(1).replace(/-/g, ' '))}
              </span>
            </span>
          </div>

          <form className="topbar-search-crm" onSubmit={handleGlobalSearch}>
            <Search className="search-icon" size={16} />
            <input 
              type="text" 
              placeholder="Search by Mobile, ID, or Stage..." 
              value={globalSearchInput}
              onChange={(e) => setGlobalSearchInput(e.target.value)}
            />
            {globalSearchInput && (
              <button 
                type="button" 
                className="search-clear-btn"
                onClick={() => {
                  setGlobalSearchInput('');
                  setActiveSearchTerm('');
                }}
              >
                <X size={14} />
              </button>
            )}
            <button type="submit" className="search-submit-btn">
              <ArrowRight size={14} />
            </button>
          </form>

          <div className="crm-type-switcher">
            <button
              type="button"
              className="crm-main-system-btn"
              onClick={() => navigate('/dashboard?tab=dashboard&sub=followups')}
              title="Back to Main System"
            >
              <ChevronLeft size={14} />
              <span>Main System</span>
            </button>

            <div className="entity-switcher-container">
              <button 
                className="entity-switcher-v4"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowEntityDropdown(!showEntityDropdown);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  background: 'var(--bg-surface-2)',
                  border: '1px solid var(--border)',
                  padding: '8px 16px',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-primary)',
                  fontSize: '11px',
                  fontWeight: '800',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  cursor: 'pointer',
                  transition: 'all 0.2s'
                }}
              >
                {activeEntityType === 'GST_REGISTRATION' ? 'GST Registration' : 'Income Tax'}
                <ChevronDown size={14} className={showEntityDropdown ? 'rotate' : ''} style={{ transition: 'transform 0.2s', color: 'var(--text-primary)' }} />
              </button>

              {showEntityDropdown && (
                <div className="profile-dropdown-popover crm-popover" style={{ left: 0, top: 'calc(100% + 8px)' }}>
                  <button className="dropdown-item" onClick={() => { 
                    setActiveEntityType('GST_REGISTRATION'); 
                    setSelectedPipelineStage(null);
                    const params = new URLSearchParams(window.location.search);
                    params.set('entity_type', 'GST_REGISTRATION');
                    navigate(`${window.location.pathname}?${params.toString()}`);
                    setShowEntityDropdown(false); 
                  }}>
                    <Shield size={14} /> <span>GST Registration</span>
                  </button>
                  <button className="dropdown-item" onClick={() => { 
                    setActiveEntityType('INCOME_TAX'); 
                    setSelectedPipelineStage(null);
                    const params = new URLSearchParams(window.location.search);
                    params.set('entity_type', 'INCOME_TAX');
                    navigate(`${window.location.pathname}?${params.toString()}`);
                    setShowEntityDropdown(false); 
                  }}>
                    <FileText size={14} /> <span>Income Tax</span>
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="workspace-actions">
            <button 
              className={`topbar-icon-btn v4-btn ${activeCrmTab === 'notifications' ? 'active' : ''}`}
              onClick={() => setActiveCrmTab('notifications')}
              title="Activity Feed"
            >
              <Bell size={20} />
              {hasNotifications && <span className="notification-dot" />}
            </button>
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
                  <span className="user-name">{profileData?.first_name || profileData?.username || 'User'}</span>
                  <span className="mini-role-badge">{profileData?.role || 'User'}</span>
                  <span className="chevron-icon"><ChevronDown size={14} /></span>
                </div>
              </div>

              {showProfileDropdown && (
                <div className="profile-dropdown-popover">
                  <div className="dropdown-header">
                    <span className="dropdown-name">{profileData?.first_name} {profileData?.last_name}</span>
                    <span className="dropdown-role">{profileData?.role}</span>
                  </div>
                  <div className="dropdown-divider" />
                  <button className="dropdown-item logout" onClick={handleLogout}>
                    <LogOut size={14} /> <span>Logout</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <div className="crm-content-container">
          {activeCrmTab === 'dashboard' && renderAnalytics()}
          {activeCrmTab === 'settings' && (
            <div className="crm-dash-view" style={{ padding: '32px', minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
              {activeSettingsTab === 'bulk-assign' && isAdmin && (
                <BulkAssign entityType={activeEntityType} onEntityTypeChange={setActiveEntityType} />
              )}
              {activeSettingsTab === 'activities' && <CRMHistory userEmail={profileData?.email} userRole={profileData?.role} entityType={activeEntityType} />}
              {activeSettingsTab === 'import' && isAllowedImport && <ImportLeads entityType={activeEntityType} />}
            </div>
          )}
          {activeCrmTab === 'leads' && (
            <Leads 
              key={`leads-tab-${activeEntityType}-${activeSearchTerm}-${leadOpenSeq}`}
              entityType={activeEntityType} 
              initialFilters={leadsInitialFilters}
              targetLeadId={targetLeadId}
              targetEntityId={targetEntityId}
              targetView={targetView}
              targetCallStatus={targetCallStatus}
              onLeadOpened={handleLeadOpened}
            />
          )}
          {activeCrmTab === CRM_TAB_PAYMENT_PENDING && isIncomeTaxCrm && (
            <Leads
              key={`payment-pending-tab-${activeEntityType}`}
              entityType={activeEntityType}
              initialFilters={PAYMENT_PENDING_BOARD_FILTERS}
              hideFilters
              targetLeadId={targetLeadId}
              targetView={targetView}
              targetCallStatus={targetCallStatus}
              onLeadOpened={handleLeadOpened}
            />
          )}
          {activeCrmTab === 'smart-board' && (
            <SmartBoard 
              key={`smart-board-tab-${activeEntityType}-${activeSearchTerm}`}
              entityType={activeEntityType} 
              initialFilters={activeSearchTerm ? { mobile: activeSearchTerm } : null}
              targetLeadId={targetLeadId}
              targetView={targetView}
              onLeadOpened={() => {
                handleLeadOpened();
                setTargetView(null);
              }}
            />
          )}
          {activeCrmTab === CRM_TAB_TODAY_ASSIGNED && isTodayAssignedRole && (
            <Leads
              key={`today-assigned-tab-${activeEntityType}-${profileData?.role || ''}-${profileData?.emp_id || ''}`}
              entityType={activeEntityType}
              boardPreset={{
                type: 'today-assigned',
                scope: {
                  role: profileData?.role,
                  empId: profileData?.emp_id,
                  rmTeamIds: todayAssignedScope.rmTeamIds,
                  opTeamIds: todayAssignedScope.opTeamIds,
                },
              }}
              targetLeadId={targetLeadId}
              targetEntityId={targetEntityId}
              targetView={targetView}
              targetCallStatus={targetCallStatus}
              onLeadOpened={handleLeadOpened}
            />
          )}
          {activeCrmTab === 'pipeline' && <PipelineStages entityType={activeEntityType} stage={selectedPipelineStage} key={`${selectedPipelineStage}-${activeEntityType}`} />}
          {activeCrmTab === 'notifications' && (
            <div className="crm-dash-view">
              <CRMNotifications />
            </div>
          )}
          {activeCrmTab === 'knowledge' && (
            <div className="crm-dash-view" style={{ padding: '32px' }}>
              <CRMKnowledge entityType={activeEntityType} />
            </div>
          )}
          {activeCrmTab === 'profile' && <div className="crm-dash-view" style={{ padding: '32px' }}>{renderProfileTab()}</div>}
        </div>

        {/* --- Modals Ported from Dashboard --- */}
        {isEditProfileOpen && (
          <div className="crm-drawer-overlay" onClick={() => setIsEditProfileOpen(false)} style={{ zIndex: 11000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div className="premium-edit-modal-v4" onClick={e => e.stopPropagation()}>
              <div className="edit-modal-grid-v4">
                <div className="edit-modal-col-left-v4">
                  <div className="edit-modal-header-v4">
                    <div className="header-brand-icon-v4"><UserCircle size={28} /></div>
                    <div className="header-text-content-v4">
                      <h3>Update Profile</h3>
                      <p>Modify your account information</p>
                    </div>
                  </div>
                  <div className="edit-modal-security-section-v4">
                    <button className="cp-trigger-btn-minimal-v4" onClick={() => setIsChangePasswordOpen(true)}>
                      <Lock size={14} /> Change Password
                    </button>
                  </div>
                </div>
                <div className="edit-modal-col-right-v4">
                  <button className="btn-close-modal-v4-top" onClick={() => setIsEditProfileOpen(false)}><X size={18} /></button>
                  <form onSubmit={handleSaveProfile} className="drawer-body" style={{ padding: 0 }}>
                    <div className="premium-edit-grid-v4">
                      <div className="input-group-v4">
                        <label><UserCircle size={14} /> First Name</label>
                        <input name="first_name" value={editProfileData.first_name} onChange={handleEditProfileChange} placeholder="First name" required />
                      </div>
                      <div className="input-group-v4">
                        <label><UserCircle size={14} /> Last Name</label>
                        <input name="last_name" value={editProfileData.last_name} onChange={handleEditProfileChange} placeholder="Last name" required />
                      </div>
                      <div className="input-group-v4" style={{ gridColumn: 'span 2' }}>
                        <label><Mail size={14} /> Email Address</label>
                        <input name="email" type="email" value={editProfileData.email} onChange={handleEditProfileChange} placeholder="Email" required />
                        {fieldErrors.email && <span className="error-text">{fieldErrors.email}</span>}
                      </div>
                      <div className="input-group-v4" style={{ gridColumn: 'span 2' }}>
                        <label><Phone size={14} /> Phone Number</label>
                        <input name="phone_number" value={editProfileData.phone_number} onChange={handleEditProfileChange} placeholder="Phone" required />
                      </div>
                    </div>
                    {fieldErrors._global && <div className="error-text" style={{ marginTop: '16px' }}>{fieldErrors._global}</div>}
                    <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '24px' }}>
                      <button type="button" className="btn-drawer-secondary" onClick={() => setIsEditProfileOpen(false)} style={{ maxWidth: '120px' }}>Cancel</button>
                      <button type="submit" className="btn-save-v4" disabled={editProfileLoading}>
                        {editProfileLoading ? <Loader2 className="spin" size={16} /> : 'Save Changes'}
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
          </div>
        )}

        {isChangePasswordOpen && (
          <ChangePasswordModal 
            isOpen={isChangePasswordOpen} 
            onClose={() => setIsChangePasswordOpen(false)} 
            empId={profileData?.emp_id} 
            setToastMessage={setToastMessage}
          />
        )}

        {/* Global Toast Notification Engine (CRM Instance) */}
        <div className="st-toast-stack-container">
          {toasts.map((toast) => (
            <div 
              key={toast.id} 
              className={`toast-notification v4 show ${toast.variant === 'urgent' ? 'urgent' : 'success'}`}
              onClick={() => {
                if (toast.action?.path) {
                  const segments = toast.action.path.split('?');
                  const queryString = segments.length > 1 ? segments[1] : '';
                  const params = new URLSearchParams(queryString);
                  const leadId = params.get('target_lead_id');
                  const targetView = params.get('target_view');
                  if (leadId) {
                    setTargetLeadId(leadId);
                    if (targetView) setTargetView(targetView);
                    setActiveCrmTab('leads');
                  } else {
                    navigate(toast.action.path || toast.action.taskId || '/crm-dashboard');
                  }
                  setToasts(prev => prev.filter(t => t.id !== toast.id));
                }
              }}
              style={{ cursor: toast.action ? 'pointer' : 'default' }}
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
                    {typeof toast.message === 'object' ? toast.message.message : toast.message}
                  </span>
                </div>
              </div>
              
              {toast.action && (
                <button 
                  className="btn-toast-action-v4"
                  onClick={(e) => {
                    e.stopPropagation();
                    const segments = (toast.action?.path || '').split('?');
                    const queryString = segments.length > 1 ? segments[1] : '';
                    const params = new URLSearchParams(queryString);
                    const leadId = params.get('target_lead_id');
                    const tView = params.get('target_view');
                    if (leadId) {
                      setTargetLeadId(leadId);
                      if (tView) setTargetView(tView);
                      setActiveCrmTab('leads');
                    } else if (toast.action?.path) {
                      navigate(toast.action.path);
                    }
                    setToasts(prev => prev.filter(t => t.id !== toast.id));
                  }}
                >
                  {toast.action.label || 'View'}
                </button>
              )}
            </div>
          ))}
        </div>
      </main>
    </div>
    </CrmDashboardErrorBoundary>
  );
};

export default CrmDashboard;
