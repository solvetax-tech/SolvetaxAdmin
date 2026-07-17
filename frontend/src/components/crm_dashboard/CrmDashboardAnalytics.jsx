/**
 * CRM Dashboard — follow-ups view aligned with main workspace Followups tab.
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Calendar,
  CheckCircle2,
  CheckCircle,
  Clock,
  Activity,
  Phone,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertCircle,
  Bell,
  X,
  CalendarCheck,
  ArrowRight,
} from 'lucide-react';
import {
  fetchCrmLeadAlerts,
  fetchCrmFollowupStats,
  fetchCrmScheduledFollowupsPage,
  fetchCrmCalendarMonthLeads,
} from '../../utils/crmLeadsAlerts';
import {
  formatFollowupDateKey,
  FOLLOWUP_SCHEDULE_PAGE_SIZE,
  getFollowupActivityBadge,
} from '../../utils/followupsApi';
import { matchesCrmFollowupKpiFilter } from '../../utils/crmFollowupKpi';
import Pagination from '../common/Pagination';
import '../follow_ups/Followups.css';

const toDateKey = (year, monthIndex, day) =>
  `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

const formatLocalDateStr = (dateInput) => {
  if (!dateInput) return '';
  if (typeof dateInput === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dateInput.trim())) {
    return dateInput.trim();
  }
  const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
  if (Number.isNaN(d.getTime())) return '';
  return toDateKey(d.getFullYear(), d.getMonth(), d.getDate());
};

const normalizeSelectedDates = (dates = []) =>
  [...new Set(dates.map((d) => formatLocalDateStr(d)).filter(Boolean))];

const formatDateTime = (dateStr) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  const d = String(date.getDate()).padStart(2, '0');
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const y = date.getFullYear();
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${d}-${m}-${y} ${hh}:${mm}`;
};

export default function CrmDashboardAnalytics({
  activeEntityType,
  isActive,
  profileData,
  profileLoadFailed = false,
  stages = [],
  onOpenLead,
}) {
  const [activeFollowupCategory, setActiveFollowupCategory] = useState('service');
  const [stageFilter, setStageFilter] = useState('');
  const [activeStatFilter, setActiveStatFilter] = useState('ALL');
  const [calendarLeads, setCalendarLeads] = useState([]);
  const [scheduledPageLeads, setScheduledPageLeads] = useState([]);
  const [schedulePage, setSchedulePage] = useState(1);
  const [scheduleHasMore, setScheduleHasMore] = useState(false);
  const [scheduleTotal, setScheduleTotal] = useState(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [selectedDates, setSelectedDates] = useState(() => [formatLocalDateStr(new Date())]);
  const [calendarViewDate, setCalendarViewDate] = useState(new Date());
  const [followupCounts, setFollowupCounts] = useState({});
  const [dashboardStats, setDashboardStats] = useState({
    scheduledToday: 0,
    overduePendingToday: 0,
    overdueCompletedToday: 0,
    completedToday: 0,
    pendingToday: 0,
    successRate: 100,
  });
  const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
  const [alertsData, setAlertsData] = useState([]);
  const [loadingAlerts, setLoadingAlerts] = useState(false);
  const alertsRef = useRef(null);

  const followupCategory = activeFollowupCategory === 'payment' ? 'payment' : 'service';

  const dateKeys = useMemo(
    () => (selectedDates?.length ? normalizeSelectedDates(selectedDates) : [formatLocalDateStr(new Date())]),
    [selectedDates],
  );

  const displayLeads = useMemo(
    () => scheduledPageLeads.filter((l) => matchesCrmFollowupKpiFilter(l, activeStatFilter)),
    [scheduledPageLeads, activeStatFilter],
  );

  const toggleSelectedDate = useCallback((dateStr) => {
    setSelectedDates((prev) => {
      const normalized = normalizeSelectedDates(prev);
      if (normalized.includes(dateStr)) {
        const next = normalized.filter((d) => d !== dateStr);
        return next.length ? next : [formatLocalDateStr(new Date())];
      }
      return [...normalized, dateStr].sort();
    });
    setActiveStatFilter('ALL');
    setSchedulePage(1);
  }, []);

  const profileReady = Boolean(profileData?.emp_id);

  const refreshDashboardStats = useCallback(async () => {
    if (!isActive || !profileReady) return;
    setStatsLoading(true);
    try {
      const stats = await fetchCrmFollowupStats({
        entityType: activeEntityType,
        selectedDates: dateKeys,
        category: followupCategory,
        stageFilter,
        profileData,
      });
      setDashboardStats(stats);
    } catch (err) {
      console.error('Failed to fetch CRM follow-up dashboard stats:', err);
    } finally {
      setStatsLoading(false);
    }
  }, [isActive, profileReady, activeEntityType, profileData, followupCategory, dateKeys, stageFilter]);

  const fetchCalendarMonth = useCallback(async () => {
    if (!isActive || !profileReady) {
      setCalendarLeads([]);
      return;
    }
    try {
      const items = await fetchCrmCalendarMonthLeads({
        entityType: activeEntityType,
        profileData,
        category: followupCategory,
        year: calendarViewDate.getFullYear(),
        monthIndex: calendarViewDate.getMonth(),
        stageFilter,
      });
      setCalendarLeads(items);
    } catch (err) {
      console.error('Failed to fetch CRM calendar month leads:', err);
      setCalendarLeads([]);
    }
  }, [isActive, activeEntityType, profileData, followupCategory, calendarViewDate, stageFilter]);

  const fetchScheduledPage = useCallback(async () => {
    if (!isActive || !profileReady) {
      setScheduledPageLeads([]);
      setScheduleHasMore(false);
      setScheduleTotal(null);
      return;
    }
    setScheduleLoading(true);
    try {
      const { items, total, hasMore } = await fetchCrmScheduledFollowupsPage({
        entityType: activeEntityType,
        profileData,
        category: followupCategory,
        dateKeys,
        stageFilter,
        page: schedulePage,
        pageSize: FOLLOWUP_SCHEDULE_PAGE_SIZE,
      });
      setScheduledPageLeads(items);
      setScheduleTotal(total);
      setScheduleHasMore(hasMore);
    } catch (err) {
      console.error('Failed to fetch CRM scheduled follow-ups page:', err);
      setScheduledPageLeads([]);
      setScheduleHasMore(false);
      setScheduleTotal(null);
    } finally {
      setScheduleLoading(false);
    }
  }, [
    isActive,
    profileReady,
    activeEntityType,
    profileData,
    followupCategory,
    dateKeys,
    stageFilter,
    schedulePage,
  ]);

  const fetchAlerts = useCallback(async () => {
    if (!isActive || !profileReady) {
      setAlertsData([]);
      return;
    }
    setLoadingAlerts(true);
    try {
      const category = activeFollowupCategory === 'payment' ? 'payment' : 'service';
      const items = await fetchCrmLeadAlerts({
        entityType: activeEntityType,
        profileData,
        category,
        stageFilter,
      });
      setAlertsData(items);
    } catch (err) {
      console.error('Failed to fetch CRM lead alerts:', err);
      setAlertsData([]);
    } finally {
      setLoadingAlerts(false);
    }
  }, [isActive, profileReady, activeEntityType, activeFollowupCategory, profileData, stageFilter]);

  useEffect(() => {
    if (!isActive || !profileReady) return undefined;
    refreshDashboardStats();
    fetchCalendarMonth();
    fetchScheduledPage();
    fetchAlerts();

    // Match main Followups.jsx: poll every 60s so KPIs/alerts stay in sync with the 10-min missed buffer.
    const pollInterval = setInterval(() => {
      refreshDashboardStats();
      fetchCalendarMonth();
      fetchScheduledPage();
      fetchAlerts();
    }, 60000);

    return () => clearInterval(pollInterval);
  }, [isActive, profileReady, refreshDashboardStats, fetchCalendarMonth, fetchScheduledPage, fetchAlerts]);

  useEffect(() => {
    const onFollowupsUpdated = () => {
      if (isActive && profileReady) {
        refreshDashboardStats();
        fetchCalendarMonth();
        fetchScheduledPage();
        fetchAlerts();
      }
    };
    window.addEventListener('st_followups_updated', onFollowupsUpdated);
    return () => window.removeEventListener('st_followups_updated', onFollowupsUpdated);
  }, [isActive, profileReady, refreshDashboardStats, fetchCalendarMonth, fetchScheduledPage, fetchAlerts]);

  useEffect(() => {
    const year = calendarViewDate.getFullYear();
    const month = calendarViewDate.getMonth();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const countMap = {};

    calendarLeads.forEach((lead) => {
      const key = formatFollowupDateKey(lead.followup_at);
      if (!key) return;
      const [y, m] = key.split('-').map(Number);
      if (y === year && m - 1 === month) {
        countMap[key] = (countMap[key] || 0) + 1;
      }
    });

    for (let d = 1; d <= daysInMonth; d += 1) {
      const key = toDateKey(year, month, d);
      if (!countMap[key]) countMap[key] = 0;
    }

    setFollowupCounts(countMap);
  }, [calendarLeads, calendarViewDate]);

  useEffect(() => {
    const todayStr = formatLocalDateStr(new Date());
    setSelectedDates([todayStr]);
    setActiveStatFilter('ALL');
    setStageFilter('');
    setSchedulePage(1);
  }, [activeFollowupCategory, activeEntityType]);

  useEffect(() => {
    setSchedulePage(1);
  }, [selectedDates, stageFilter, activeStatFilter]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (alertsRef.current && !alertsRef.current.contains(event.target)) {
        setShowAlertsDrawer(false);
      }
    };
    if (showAlertsDrawer) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showAlertsDrawer]);

  const activeAlertsCount = useMemo(
    () => alertsData.filter((item) => item.status === 'PENDING' || item.status === 'MISSED').length,
    [alertsData],
  );

  const renderAlertsDrawer = () => {
    const activeItems = alertsData.filter((item) => item.status === 'PENDING' || item.status === 'MISSED');
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999).getTime();

    const todayPending = activeItems.filter((item) => {
      const fDate = new Date(item.followup_at).getTime();
      return fDate >= todayStart && fDate <= todayEnd;
    });
    const pastOverdue = activeItems.filter((item) => {
      const fDate = new Date(item.followup_at).getTime();
      return fDate < todayStart;
    });

    return (
      <>
        <div className="alerts-drawer-overlay" onClick={() => setShowAlertsDrawer(false)} />
        <div className="followups-alerts-drawer" ref={alertsRef} onClick={(e) => e.stopPropagation()}>
          <div className="calendar-drawer-header">
            <h2><Bell size={24} /> Task Insights</h2>
            <button type="button" className="btn-close-drawer" onClick={() => setShowAlertsDrawer(false)}>
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
                <p style={{ color: 'var(--text-primary)', fontSize: '14px' }}>No pending lead follow-ups.</p>
              </div>
            ) : (
              <div className="alerts-scroll-list">
                {alertsData.map((item) => (
                  <div
                    key={item.id}
                    className={`alert-task-card ${new Date(item.followup_at) < new Date() ? 'is-overdue' : ''}`}
                  >
                    <div className="card-top">
                      <span className="task-time">
                        <Clock size={12} />
                        {new Date(item.followup_at).toLocaleDateString('en-IN', { weekday: 'short', month: 'short', day: 'numeric' })}
                        {' | '}
                        {new Date(item.followup_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span className="task-id">{`ID ${item.customer_id}`}</span>
                    </div>
                    <div className="task-main">
                      <h4 className="service-name">{item.full_name} — {item.service_name}</h4>
                      <p className="task-remarks">{item.remarks || item.mobile || 'No remarks'}</p>
                    </div>
                    <div className="card-actions">
                      <button
                        type="button"
                        className="btn-alert-action"
                        onClick={() => {
                          setShowAlertsDrawer(false);
                          onOpenLead?.({ leadId: item.id, view: 'history' });
                        }}
                      >
                        <ArrowRight size={14} />
                        <span>Open Lead</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="drawer-footer">
            <button type="button" className="btn-drawer-reset" style={{ flex: 1 }} onClick={() => setShowAlertsDrawer(false)}>
              Close Panel
            </button>
            <button type="button" className="btn-drawer-today" style={{ flex: 1 }} onClick={fetchAlerts}>
              Refresh Alerts
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
      successRate = 100,
    } = dashboardStats;

    const todayStr = formatLocalDateStr(new Date());
    const statsPeriodLabel = (() => {
      if (dateKeys.length === 1 && dateKeys[0] === todayStr) return 'TODAY';
      if (dateKeys.length === 1) {
        const [y, m, d] = dateKeys[0].split('-').map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        }).toUpperCase();
      }
      return `${dateKeys.length} SELECTED DATES`;
    })();

    const stats = [
      {
        label: 'Scheduled',
        value: scheduledToday,
        icon: <Calendar size={20} />,
        color: 'var(--info)',
        desc: `SCHEDULED ${statsPeriodLabel}`,
        type: 'SCHEDULED',
      },
      {
        label: 'Overdue (Pending)',
        value: overduePendingToday,
        icon: <AlertCircle size={20} />,
        color: 'var(--danger)',
        desc: `OVERDUE PENDING ${statsPeriodLabel}`,
        type: 'OVERDUE_PENDING',
      },
      {
        label: 'Overdue (Completed)',
        value: overdueCompletedToday,
        icon: <CheckCircle2 size={20} />,
        color: 'var(--warning)',
        desc: `OVERDUE COMPLETED ${statsPeriodLabel}`,
        type: 'OVERDUE_COMPLETED',
      },
      {
        label: 'Completed (On-time)',
        value: completedToday,
        icon: <CheckCircle size={20} />,
        color: 'var(--accent)',
        desc: `COMPLETED ${statsPeriodLabel}`,
        type: 'COMPLETED',
      },
      {
        label: 'Pending (Urgent)',
        value: pendingToday,
        icon: <Clock size={20} />,
        color: 'var(--warning)',
        desc: `PENDING ${statsPeriodLabel}`,
        type: 'PENDING',
      },
      {
        label: 'Success Rate',
        value: `${successRate}%`,
        icon: <Activity size={20} />,
        color: 'var(--info)',
        desc: statsPeriodLabel === 'TODAY' ? 'SUCCESS RATE TODAY' : `SUCCESS RATE (${statsPeriodLabel})`,
        type: null,
      },
    ];

    return (
      <div className="stats-grid-v4">
        {stats.map((s) => (
          <div
            key={s.label}
            className={`stat-card-premium ${activeStatFilter === s.type ? 'active' : ''}`}
            style={{
              '--accent-color': s.color,
              cursor: s.type ? 'pointer' : 'default',
              border: activeStatFilter === s.type ? `1.5px solid ${s.color}` : '1px solid var(--border)',
              boxShadow: activeStatFilter === s.type ? 'var(--shadow-lg)' : 'var(--shadow-sm)',
              transform: activeStatFilter === s.type ? 'translateY(-2px)' : 'none',
              transition: 'all 0.3s cubic-bezier(0.165, 0.84, 0.44, 1)',
            }}
            title={s.desc}
            onClick={() => {
              if (s.type) {
                setActiveStatFilter(activeStatFilter === s.type ? 'ALL' : s.type);
                setSchedulePage(1);
              }
            }}
            onKeyDown={(e) => {
              if (s.type && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault();
                setActiveStatFilter(activeStatFilter === s.type ? 'ALL' : s.type);
                setSchedulePage(1);
              }
            }}
            role={s.type ? 'button' : undefined}
            tabIndex={s.type ? 0 : undefined}
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

  const renderInlineCalendar = () => {
    const now = new Date();
    const viewYear = calendarViewDate.getFullYear();
    const viewMonth = calendarViewDate.getMonth();
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const firstDay = new Date(viewYear, viewMonth, 1).getDay();
    const today = now.getDate();
    const currentMonthStr = calendarViewDate.toLocaleString('en-US', { month: 'long', year: 'numeric' });
    const prevMonthDays = new Date(viewYear, viewMonth, 0).getDate();
    const normalizedSelected = normalizeSelectedDates(selectedDates);

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
    for (let i = firstDay - 1; i >= 0; i -= 1) {
      days.push({ day: prevMonthDays - i, isCurrentMonth: false, isPastMonth: true });
    }
    for (let i = 1; i <= daysInMonth; i += 1) {
      days.push({ day: i, isCurrentMonth: true });
    }
    const totalGridSlots = 42;
    const remainingSlots = totalGridSlots - days.length;
    for (let i = 1; i <= remainingSlots; i += 1) {
      days.push({ day: i, isCurrentMonth: false, isNextMonth: true });
    }

    return (
      <div className="crm-calendar-widget">
        <div className="calendar-header">
          <div className="cal-nav-group">
            <button
              type="button"
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
              type="button"
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
          {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, index) => (
            <div key={`${d}-${index}`} className="weekday">{d}</div>
          ))}
          {days.map((dayObj, idx) => {
            if (!dayObj.isCurrentMonth) {
              return <div key={idx} className="calendar-day empty" />;
            }

            const targetDate = new Date(viewYear, viewMonth, dayObj.day);
            const dateStr = toDateKey(viewYear, viewMonth, dayObj.day);
            const isPast = targetDate < new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const isSelected = normalizedSelected.includes(dateStr);
            const isToday = dayObj.day === today && viewMonth === now.getMonth() && viewYear === now.getFullYear();
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

  const renderActivityFeed = () => {
    if (scheduleLoading) {
      return (
        <div className="activity-feed-timeline">
          {[...Array(4)].map((_, i) => (
            <div
              key={i}
              className="activity-item-v4 premium-bento-card skeleton"
              style={{ padding: '16px', marginBottom: '8px', borderRadius: '14px' }}
            >
              <div className="skeleton-pulse" style={{ height: '12px', width: '60%', marginBottom: '8px' }} />
              <div className="skeleton-pulse" style={{ height: '10px', width: '40%' }} />
            </div>
          ))}
        </div>
      );
    }

    if (displayLeads.length === 0) {
      return (
        <div className="activity-feed-timeline">
          <div className="empty-feed">
            <div className="empty-feed-icon-stack">
              <div className="empty-feed-icon-bg" />
              <Calendar size={28} className="empty-feed-icon-main" strokeWidth={1.5} />
              <Clock size={14} className="empty-feed-icon-sub" />
            </div>
            <h4 className="empty-feed-title">No Activities Found</h4>
            <p className="empty-feed-subtitle">No activities match the selected status.</p>
          </div>
        </div>
      );
    }

    return (
      <div className="activity-feed-timeline">
        {displayLeads.map((lead, i) => {
          const { statusBadgeClass, statusTextString } = getFollowupActivityBadge(lead);

          return (
            <div
              className="activity-item-v4 clickable premium-bento-card"
              key={lead.id || i}
              style={{
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
                padding: '16px',
                borderRadius: '14px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                marginBottom: '8px',
              }}
              onClick={() => openScheduledLead(lead)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  openScheduledLead(lead);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                  <div style={{ width: '22px', height: '22px', borderRadius: '50%', background: 'rgba(var(--info-rgb), 0.12)', color: 'var(--info)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: 700, flexShrink: 0 }}>
                    {(lead.full_name || 'N').charAt(0).toUpperCase()}
                  </div>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {lead.full_name || 'Unknown'}
                  </span>
                  <button
                    type="button"
                    className="crm-scheduled-lead-id-link"
                    title={`Open lead ${lead.id}`}
                    aria-label={`Open lead ${lead.id}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      openScheduledLead(lead);
                    }}
                  >
                    {`ID ${lead.id}`}
                  </button>
                </div>
                {lead.mobile ? (
                  <a
                    href={`tel:${lead.mobile}`}
                    onClick={(e) => e.stopPropagation()}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px', fontWeight: 700, color: 'var(--warning)', background: 'rgba(var(--warning-rgb), 0.1)', border: '1px solid rgba(var(--warning-rgb), 0.2)', padding: '3px 8px', borderRadius: '20px', textDecoration: 'none' }}
                  >
                    <Phone size={10} />
                    <span>{lead.mobile}</span>
                  </a>
                ) : null}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                  <div className={`timeline-indicator-dot ${statusBadgeClass}`} style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0 }} />
                  <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {(lead.stage || 'N/A').replace(/_/g, ' ')}
                  </span>
                </div>
                <span className={`timeline-status-badge ${statusBadgeClass}`} style={{ fontSize: '9px', fontWeight: 800, padding: '3px 8px', borderRadius: '20px' }}>
                  {statusTextString}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-surface-2)', border: '1px solid var(--border-subtle)', padding: '6px 10px', borderRadius: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--info)', fontSize: '11px', fontWeight: 600 }}>
                  <Calendar size={12} />
                  <span>{formatDateTime(lead.followup_at || lead.last_dailed_at)}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const openScheduledLead = useCallback((lead) => {
    if (!lead?.id) return;
    onOpenLead?.({ leadId: lead.id, view: 'history' });
  }, [onOpenLead]);

  const subtabStyle = (active) => ({
    background: 'transparent',
    color: active ? 'var(--accent)' : 'var(--text-muted)',
    border: 'none',
    borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    padding: '8px 4px',
    transition: 'all 0.2s ease',
    marginBottom: '-1px',
  });

  if (!profileReady) {
    return (
      <div className="followups-container crm-dashboard-followups">
        <div className="crm-analytics-content crm-dashboard-empty">
          {profileLoadFailed ? (
            <>
              <AlertCircle size={36} style={{ color: 'var(--danger)' }} />
              <p style={{ marginTop: '12px', color: 'var(--text-primary)', fontSize: '14px', fontWeight: 600 }}>
                Could not load your profile
              </p>
              <p style={{ marginTop: '8px', color: 'var(--text-muted)', fontSize: '13px', maxWidth: 420 }}>
                Sign in again and ensure the API at {import.meta.env.VITE_API_URL || 'VITE_API_URL'} is running.
              </p>
            </>
          ) : (
            <>
              <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent)' }} />
              <p style={{ marginTop: '12px', color: 'var(--text-muted)', fontSize: '14px' }}>
                Loading your CRM dashboard…
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="followups-container crm-dashboard-followups">
      <div className="crm-analytics-content">
        <div className="crm-dashboard-followups-header">
          <div className="crm-followups-subtabs">
            <button
              type="button"
              style={subtabStyle(activeFollowupCategory === 'service')}
              onClick={() => setActiveFollowupCategory('service')}
            >
              Service Follow-ups
            </button>
            <button
              type="button"
              style={subtabStyle(activeFollowupCategory === 'payment')}
              onClick={() => setActiveFollowupCategory('payment')}
            >
              Payment Follow-ups
            </button>
          </div>
          <div className="alerts-trigger-wrap">
            <button
              type="button"
              className={`btn-alerts-trigger ${showAlertsDrawer ? 'active' : ''}`}
              onClick={() => setShowAlertsDrawer(true)}
            >
              <Bell size={14} />
              Alerts
              {activeAlertsCount > 0 && (
                <span className="count-badge-v4">{activeAlertsCount}</span>
              )}
            </button>
          </div>
        </div>

        {renderStatsGrid()}

        <div className="crm-charts-row followups-charts-row-compact">
          <div className="crm-chart-box glass-v4">
            <div className="chart-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
              <h3>Follow-up Calendar</h3>
              {activeFollowupCategory === 'service' && (
                <div className="entity-type-select-wrap">
                  <select
                    className="glass-select-v4"
                    value={stageFilter}
                    onChange={(e) => {
                      setStageFilter(e.target.value);
                      setSchedulePage(1);
                    }}
                    style={{ height: '32px', padding: '0 28px 0 10px', fontSize: '12px' }}
                  >
                    <option value="">All Stages</option>
                    {(Array.isArray(stages) ? stages : []).map((stage) => (
                      <option key={stage.code || stage.id} value={stage.code}>
                        {stage.name || stage.code}
                      </option>
                    ))}
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
                title="Refresh"
                aria-label="Refresh"
                onClick={() => {
                  setSchedulePage(1);
                  refreshDashboardStats();
                  fetchCalendarMonth();
                  fetchScheduledPage();
                  fetchAlerts();
                }}
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
      </div>

      {showAlertsDrawer && renderAlertsDrawer()}
    </div>
  );
}
