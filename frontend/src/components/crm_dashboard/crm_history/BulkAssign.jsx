import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  Users, Filter, CheckCircle2, AlertCircle, Loader2, UserPlus, Check, X, ChevronDown,
  Activity, ArrowRight, Zap, Play, Plus, Trash2, MapPin, Power,
} from 'lucide-react';
import api from '../../../utils/api';
import { unwrapListPayload } from '../../../utils/apiResponse';
import {
  buildCrmBulkAutoAssignPayload,
  deleteBulkAssignScheduler,
  fetchAllBulkAssignSchedulers,
  fetchBulkAssignSchedulers,
  runBulkAssignScheduler,
  saveBulkAssignScheduler,
  toggleBulkAssignSchedulerEnabled,
} from '../../../utils/crmBulkAutoAssignApi';
import {
  activeFilterKeysFromSavedFilters,
  buildBulkAssignCandidateParams,
  DEFAULT_AUTO_ACTIVE_FILTER_KEYS,
  DEFAULT_BULK_FILTERS,
  DEFAULT_MANUAL_ACTIVE_FILTER_KEYS,
  filtersFromServer,
  getDefaultAutoActiveFilterKeys,
  getDefaultManualActiveFilterKeys,
  scrubBulkAssignFilters,
} from '../../../utils/crmBulkAssignFilters';
import {
  parseActiveUsernamesFromApi,
  usernameDropdownOptions,
} from '../../../utils/activeEmployees';
import SearchableDropdown from './SearchableDropdown';
import FormCustomSelect from '../../common/FormCustomSelect';
import { optionsFromConfigOnly, optionsFromPairs } from '../../common/selectOptionUtils';
import { formatEntityLabel } from './assignmentHistoryUtils';
import { buildFinancialYearPresetOptions } from '../../../utils/incomeTaxArrays';
import './BulkAssign.css';

const formatSchedulerLastRun = (sched) => {
  const at = sched?.last_run_at || sched?.last_run_summary?.run_at;
  if (!at) return 'Never';
  const parsed = new Date(at);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString();
};

const SchedulerToggle = ({ enabled, disabled, onChange, title }) => (
  <label className="scheduler-toggle" onClick={(e) => e.stopPropagation()} title={title}>
    <input
      type="checkbox"
      checked={Boolean(enabled)}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
    />
    <span className="scheduler-toggle-slider" aria-hidden="true" />
  </label>
);

const BulkAssign = ({ onSuccess, entityType = 'GST_REGISTRATION', onEntityTypeChange }) => {
  const isIncomeTaxCrm = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
  const [assignMode, setAssignMode] = useState('manual');
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [intervalMinutes, setIntervalMinutes] = useState(5);
  const [autoConfigLoading, setAutoConfigLoading] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);
  const [autoRunLoading, setAutoRunLoading] = useState(false);
  const [lastAutoRun, setLastAutoRun] = useState(null);
  const [schedulers, setSchedulers] = useState([]);
  const [activeSchedulerId, setActiveSchedulerId] = useState(null);
  const [isCreatingNewScheduler, setIsCreatingNewScheduler] = useState(false);
  const [schedulerName, setSchedulerName] = useState('Scheduler');
  const skipAutoPickSchedulerRef = useRef(false);
  const [storageReady, setStorageReady] = useState(true);
  const [allSchedulers, setAllSchedulers] = useState([]);
  const [allSchedulersLoading, setAllSchedulersLoading] = useState(false);
  const [togglingSchedulerId, setTogglingSchedulerId] = useState(null);
  const [pendingSchedulerId, setPendingSchedulerId] = useState(null);
  const [isExpanded, setIsExpanded] = useState(true);
  const [loading, setLoading] = useState(false);
  const [candidates, setCandidates] = useState([]);
  const [selectedLeadIds, setSelectedLeadIds] = useState([]);
  const [activeRmUsernames, setActiveRmUsernames] = useState([]);
  const [activeOpUsernames, setActiveOpUsernames] = useState([]);
  const [assigneesLoading, setAssigneesLoading] = useState(false);
  const [manualSelectedRmUsernames, setManualSelectedRmUsernames] = useState([]);
  const [manualSelectedOpUsernames, setManualSelectedOpUsernames] = useState([]);
  const [autoSelectedRmUsernames, setAutoSelectedRmUsernames] = useState([]);
  const [autoSelectedOpUsernames, setAutoSelectedOpUsernames] = useState([]);
  const [assignLoading, setAssignLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [manualActiveFilterKeys, setManualActiveFilterKeys] = useState(() => getDefaultManualActiveFilterKeys(entityType));
  const [autoActiveFilterKeys, setAutoActiveFilterKeys] = useState(() => getDefaultAutoActiveFilterKeys(entityType));
  const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState(1); // Manual: 1 filters, 2 assignment
  const [autoStep, setAutoStep] = useState(1); // Auto: 1 filters, 2 assignment + schedule
  const [previewCount, setPreviewCount] = useState(0);
  const [isCountLoading, setIsCountLoading] = useState(false);
  const filterDropdownRef = useRef(null);

  const [manualFilters, setManualFilters] = useState(() => ({ ...DEFAULT_BULK_FILTERS }));
  const [autoFilters, setAutoFilters] = useState(() => ({ ...DEFAULT_BULK_FILTERS }));

  const [manualAssignmentRoles, setManualAssignmentRoles] = useState({ RM: true, OP: false });
  const [autoAssignmentRoles, setAutoAssignmentRoles] = useState({ RM: true, OP: false });
  const [manualPerEmployeeLimits, setManualPerEmployeeLimits] = useState({ RM: '', OP: '' });
  const [autoPerEmployeeLimits, setAutoPerEmployeeLimits] = useState({ RM: '', OP: '' });

  const filters = assignMode === 'manual' ? manualFilters : autoFilters;
  const activeFilterKeys = assignMode === 'manual' ? manualActiveFilterKeys : autoActiveFilterKeys;
  const assignmentRoles = assignMode === 'manual' ? manualAssignmentRoles : autoAssignmentRoles;
  const selectedRmUsernames = assignMode === 'manual' ? manualSelectedRmUsernames : autoSelectedRmUsernames;
  const selectedOpUsernames = assignMode === 'manual' ? manualSelectedOpUsernames : autoSelectedOpUsernames;
  const perEmployeeLimits = assignMode === 'manual' ? manualPerEmployeeLimits : autoPerEmployeeLimits;

  const parsePerEmployeeLimit = (value) => {
    if (value === '' || value == null) return null;
    const parsed = parseInt(String(value).trim(), 10);
    return Number.isFinite(parsed) && parsed >= 1 ? parsed : null;
  };

  const setRolePerEmployeeLimit = (role, value) => {
    if (assignMode === 'manual') {
      setManualPerEmployeeLimits((prev) => ({ ...prev, [role]: value }));
    } else {
      setAutoPerEmployeeLimits((prev) => ({ ...prev, [role]: value }));
    }
  };

  const setSelectedRmUsernames = (value) => {
    if (assignMode === 'manual') {
      setManualSelectedRmUsernames(value);
    } else {
      setAutoSelectedRmUsernames(value);
    }
  };

  const setSelectedOpUsernames = (value) => {
    if (assignMode === 'manual') {
      setManualSelectedOpUsernames(value);
    } else {
      setAutoSelectedOpUsernames(value);
    }
  };

  const toggleAssignmentRole = (role) => {
    const setter = assignMode === 'manual' ? setManualAssignmentRoles : setAutoAssignmentRoles;
    setter((prev) => {
      const next = { ...prev, [role]: !prev[role] };
      if (!next.RM && !next.OP) return prev;
      return next;
    });
  };

  const rmEmployeeOptions = useMemo(
    () => usernameDropdownOptions(activeRmUsernames),
    [activeRmUsernames]
  );

  const opEmployeeOptions = useMemo(
    () => usernameDropdownOptions(activeOpUsernames),
    [activeOpUsernames]
  );

  const canExecuteAssign = useMemo(() => {
    if (selectedLeadIds.length === 0) return false;
    if (manualAssignmentRoles.RM && manualSelectedRmUsernames.length === 0) return false;
    if (manualAssignmentRoles.OP && manualSelectedOpUsernames.length === 0) return false;
    return manualAssignmentRoles.RM || manualAssignmentRoles.OP;
  }, [
    manualAssignmentRoles,
    selectedLeadIds.length,
    manualSelectedRmUsernames.length,
    manualSelectedOpUsernames.length,
  ]);

  // Metadata
  const [metadata, setMetadata] = useState({
    stages: [],
    followUpStatuses: ['PENDING', 'COMPLETED', 'MISSED'],
    nullFieldOptions: ['STAGE', 'RM_ID', 'OP_ID', 'LEAD_TYPE', 'TAG', 'LEAD_SOURCE', 'ENTITY_TYPE', 'FOLLOW_UP_STATUS', 'AY'],
  });

  const ayFilterOptions = useMemo(
    () => buildFinancialYearPresetOptions({ yearsBack: 8 }).map((ay) => ({ value: ay, label: ay })),
    [],
  );

  /** Active RM/OP lists from employee_edit — username-only payloads. */
  const fetchActiveRmOpLists = useCallback(async () => {
    setAssigneesLoading(true);
    try {
      const [rmRes, opRes] = await Promise.all([
        api.get('/api/v1/employees/active-rm'),
        api.get('/api/v1/employees/active-op'),
      ]);
      setActiveRmUsernames(parseActiveUsernamesFromApi(rmRes));
      setActiveOpUsernames(parseActiveUsernamesFromApi(opRes));
    } catch (err) {
      console.error('BulkAssign: active RM/OP fetch failed:', err);
      setStatus({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to load RM/OP lists.',
      });
    } finally {
      setAssigneesLoading(false);
    }
  }, []);

  const fetchMetadata = useCallback(async () => {
    try {
      const res = await api.get('/api/v1/crm/leads/stages', { params: { entity_type: entityType } });
      setMetadata((prev) => ({ ...prev, stages: res.data?.stages || [] }));
    } catch (err) {
      console.error('BulkAssign: Stages fetch failed:', err);
    }
  }, [entityType]);

  const applyAutoConfigFromServer = useCallback((data) => {
    if (!data) return;
    if (data.id) setActiveSchedulerId(data.id);
    if (data.name) setSchedulerName(data.name);
    const f = data.filters || {};
    if (f && Object.keys(f).length > 0) {
      const parsed = filtersFromServer(f);
      const visibleKeys = activeFilterKeysFromSavedFilters(parsed);
      setAutoActiveFilterKeys(visibleKeys);
      setAutoFilters({ ...scrubBulkAssignFilters(parsed, visibleKeys), offset: 0 });
    }
    setAutoAssignmentRoles({ RM: Boolean(data.assign_rm), OP: Boolean(data.assign_op) });
    setAutoSelectedRmUsernames(data.selected_rm_usernames || []);
    setAutoSelectedOpUsernames(data.selected_op_usernames || []);
    setAutoPerEmployeeLimits({
      RM: data.per_employee_limit_rm != null ? String(data.per_employee_limit_rm) : '',
      OP: data.per_employee_limit_op != null ? String(data.per_employee_limit_op) : '',
    });
    setAutoEnabled(Boolean(data.enabled));
    setIntervalMinutes(data.interval_minutes || 5);
    setLastAutoRun(data.last_run_summary || null);
  }, []);

  const loadAllSchedulers = useCallback(async () => {
    setAllSchedulersLoading(true);
    try {
      const data = await fetchAllBulkAssignSchedulers();
      setAllSchedulers(data.items || []);
    } catch (err) {
      console.error('BulkAssign: all schedulers load failed:', err);
      setAllSchedulers([]);
    } finally {
      setAllSchedulersLoading(false);
    }
  }, []);

  const schedulerSummary = useMemo(() => {
    const running = allSchedulers.filter((s) => s.enabled).length;
    return { running, stopped: allSchedulers.length - running, total: allSchedulers.length };
  }, [allSchedulers]);

  const loadSchedulers = useCallback(async () => {
    setAutoConfigLoading(true);
    try {
      const data = await fetchBulkAssignSchedulers(entityType);
      setStorageReady(data.storage_ready !== false);
      const items = data.items || [];
      setSchedulers(items);
      setActiveSchedulerId((prevId) => {
        if (skipAutoPickSchedulerRef.current && prevId == null) {
          return null;
        }
        const pick =
          (prevId != null && items.find((s) => s.id === prevId))
          || (prevId == null && !skipAutoPickSchedulerRef.current ? items[0] : null)
          || null;
        if (pick) {
          applyAutoConfigFromServer(pick);
          setLastAutoRun(pick.last_run_summary || null);
          setIsCreatingNewScheduler(false);
          skipAutoPickSchedulerRef.current = false;
          return pick.id;
        }
        return prevId;
      });
    } catch (err) {
      console.error('BulkAssign: schedulers load failed:', err);
      setStorageReady(false);
    } finally {
      setAutoConfigLoading(false);
    }
  }, [entityType, applyAutoConfigFromServer]);

  const handleSelectScheduler = (sched) => {
    setActiveSchedulerId(sched.id);
    setSchedulerName(sched.name || 'Scheduler');
    applyAutoConfigFromServer(sched);
    setLastAutoRun(sched.last_run_summary || null);
    setAutoStep(1);
  };

  const handleOpenSchedulerFromOverview = (sched) => {
    const schedEntity = (sched.entity_type || '').trim().toUpperCase();
    const currentEntity = (entityType || '').trim().toUpperCase();
    if (schedEntity && schedEntity !== currentEntity && onEntityTypeChange) {
      setPendingSchedulerId(sched.id);
      onEntityTypeChange(schedEntity);
      return;
    }
    const match = schedulers.find((s) => s.id === sched.id) || sched;
    handleSelectScheduler(match);
  };

  const handleToggleSchedulerEnabled = async (sched, nextEnabled) => {
    setTogglingSchedulerId(sched.id);
    setStatus(null);
    try {
      const updated = await toggleBulkAssignSchedulerEnabled(sched.id, nextEnabled);
      const patch = (list) => list.map((s) => (s.id === sched.id ? { ...s, enabled: updated.enabled } : s));
      setAllSchedulers(patch);
      setSchedulers(patch);
      if (activeSchedulerId === sched.id) {
        setAutoEnabled(Boolean(updated.enabled));
      }
      setStatus({
        type: 'success',
        message: nextEnabled
          ? `"${sched.name}" is running every ${sched.interval_minutes || 5} min.`
          : `"${sched.name}" is stopped.`,
      });
    } catch (err) {
      const detail = err.response?.data?.detail;
      setStatus({
        type: 'error',
        message: typeof detail === 'string' ? detail : 'Failed to update scheduler.',
      });
    } finally {
      setTogglingSchedulerId(null);
    }
  };

  const handleNewScheduler = () => {
    setIsCreatingNewScheduler(true);
    skipAutoPickSchedulerRef.current = true;
    setActiveSchedulerId(null);
    setSchedulerName(`Scheduler ${schedulers.length + 1}`);
    setAutoEnabled(false);
    setAutoFilters({ ...DEFAULT_BULK_FILTERS });
    setAutoActiveFilterKeys(DEFAULT_AUTO_ACTIVE_FILTER_KEYS);
    setAutoAssignmentRoles({ RM: true, OP: false });
    setAutoSelectedRmUsernames([]);
    setAutoSelectedOpUsernames([]);
    setAutoPerEmployeeLimits({ RM: '', OP: '' });
    setAutoStep(1);
    setLastAutoRun(null);
    setStatus(null);
  };

  const handleDeleteScheduler = async (schedId) => {
    if (!window.confirm('Remove this scheduler? Other schedulers are not affected.')) return;
    try {
      await deleteBulkAssignScheduler(schedId);
      if (activeSchedulerId === schedId) {
        setActiveSchedulerId(null);
        handleNewScheduler();
      }
      await loadSchedulers();
      await loadAllSchedulers();
      setStatus({ type: 'success', message: 'Scheduler removed.' });
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.detail || 'Failed to delete scheduler.' });
    }
  };

  useEffect(() => {
    if (!isExpanded) return;
    fetchMetadata();
    fetchActiveRmOpLists();
    loadSchedulers();
    loadAllSchedulers();
  }, [isExpanded, entityType]);

  useEffect(() => {
    setManualActiveFilterKeys(getDefaultManualActiveFilterKeys(entityType));
    setAutoActiveFilterKeys(getDefaultAutoActiveFilterKeys(entityType));
  }, [entityType]);

  useEffect(() => {
    if (!pendingSchedulerId || schedulers.length === 0) return;
    const match = schedulers.find((s) => s.id === pendingSchedulerId);
    if (match) {
      handleSelectScheduler(match);
      setPendingSchedulerId(null);
    }
  }, [schedulers, pendingSchedulerId]);

  useEffect(() => {
    if (!isExpanded) return;
    const onAssignmentStep = assignMode === 'manual' ? currentStep === 2 : autoStep === 2;
    if (onAssignmentStep) {
      fetchActiveRmOpLists();
    }
  }, [currentStep, autoStep, assignMode, isExpanded, fetchActiveRmOpLists]);

  useEffect(() => {
    if (!isExpanded) return;
    const onFilterStep = assignMode === 'manual' ? currentStep === 1 : autoStep === 1;
    if (!onFilterStep) return;

    const previewFilters = assignMode === 'manual' ? manualFilters : autoFilters;
    const previewActiveKeys = assignMode === 'manual' ? manualActiveFilterKeys : autoActiveFilterKeys;

    const timer = setTimeout(async () => {
      setIsCountLoading(true);
      try {
        const params = buildBulkAssignCandidateParams(previewFilters, entityType, previewActiveKeys);
        params.set('limit', '1');

        const response = await api.get(`/api/v1/crm/leads/bulk-assign/candidates?${params.toString()}`);
        setPreviewCount(response.data?.total || 0);
      } catch (err) {
        console.error("BulkAssign: Count preview failed:", err);
      } finally {
        setIsCountLoading(false);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [
    manualFilters,
    autoFilters,
    manualActiveFilterKeys,
    autoActiveFilterKeys,
    currentStep,
    autoStep,
    entityType,
    isExpanded,
    assignMode,
  ]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (filterDropdownRef.current && !filterDropdownRef.current.contains(event.target)) {
        setIsFilterDropdownOpen(false);
      }
    };

    if (isFilterDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isFilterDropdownOpen]);

  const fetchCandidates = async () => {
    setLoading(true);
    setStatus(null);
    try {
      const params = buildBulkAssignCandidateParams(manualFilters, entityType, manualActiveFilterKeys);

      const apiBase = '/api/v1/crm/leads';
      const response = await api.get(`${apiBase}/bulk-assign/candidates?${params.toString()}`);
      const { items, total } = unwrapListPayload(response);
      setCandidates(items);
      setCandidateTotal(total ?? 0);
      setSelectedLeadIds(items.map(l => l.id));
      
      if (items.length === 0) {
        setStatus({ type: 'info', message: 'No leads found matching these filters.' });
      } else {
        setStatus({ type: 'success', message: `Successfully loaded ${items.length} leads for assignment.` });
        setCurrentStep(2); // Move to next step
      }
    } catch (err) {
      console.error("Bulk assign fetch failed:", err);
      setStatus({ type: 'error', message: 'Failed to fetch candidates.' });
    } finally {
      setLoading(false);
    }
  };

  const canSaveAutoConfig = useMemo(() => {
    if (!autoEnabled) return true;
    if (autoAssignmentRoles.RM && autoSelectedRmUsernames.length === 0) return false;
    if (autoAssignmentRoles.OP && autoSelectedOpUsernames.length === 0) return false;
    return autoAssignmentRoles.RM || autoAssignmentRoles.OP;
  }, [autoEnabled, autoAssignmentRoles, autoSelectedRmUsernames.length, autoSelectedOpUsernames.length]);

  const handleSaveAutoConfig = async () => {
    setAutoSaving(true);
    setStatus(null);
    try {
      const payload = buildCrmBulkAutoAssignPayload({
        schedulerId: activeSchedulerId,
        schedulerName,
        entityType,
        filters: autoFilters,
        activeFilterKeys: autoActiveFilterKeys,
        enabled: autoEnabled,
        assignmentRoles: autoAssignmentRoles,
        selectedRmUsernames: autoSelectedRmUsernames,
        selectedOpUsernames: autoSelectedOpUsernames,
        perEmployeeLimits: autoPerEmployeeLimits,
        intervalMinutes,
      });
      const saved = await saveBulkAssignScheduler(payload);
      setIsCreatingNewScheduler(false);
      skipAutoPickSchedulerRef.current = false;
      setActiveSchedulerId(saved.id);
      applyAutoConfigFromServer(saved);
      await loadSchedulers();
      await loadAllSchedulers();
      const limitNote = [];
      if (parsePerEmployeeLimit(autoPerEmployeeLimits.RM) != null) {
        limitNote.push(`max ${parsePerEmployeeLimit(autoPerEmployeeLimits.RM)} per RM per run`);
      }
      if (parsePerEmployeeLimit(autoPerEmployeeLimits.OP) != null) {
        limitNote.push(`max ${parsePerEmployeeLimit(autoPerEmployeeLimits.OP)} per OP per run`);
      }
      const created = !activeSchedulerId;
      setStatus({
        type: 'success',
        message: created
          ? `Scheduler "${saved.name}" created. You can add more anytime with New scheduler.`
          : autoEnabled
            ? `Scheduler updated. Every ${intervalMinutes} min it assigns leads matching your filters${limitNote.length ? ` (${limitNote.join(', ')})` : ''}.`
            : 'Scheduler saved (auto-assign disabled).',
      });
      if (onSuccess) onSuccess();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : 'Failed to save auto-assign configuration.';
      setStatus({ type: 'error', message: msg });
    } finally {
      setAutoSaving(false);
    }
  };

  const handleRunAutoNow = async () => {
    if (!autoEnabled) {
      setStatus({ type: 'info', message: 'Turn on “Enable auto-assign” and save the rule first.' });
      return;
    }
    if (!canSaveAutoConfig) {
      setStatus({ type: 'error', message: 'Select at least one RM or OP for the roles you enabled.' });
      return;
    }

    setAutoRunLoading(true);
    setStatus(null);
    try {
      const payload = buildCrmBulkAutoAssignPayload({
        schedulerId: activeSchedulerId,
        schedulerName,
        entityType,
        filters: autoFilters,
        activeFilterKeys: autoActiveFilterKeys,
        enabled: autoEnabled,
        assignmentRoles: autoAssignmentRoles,
        selectedRmUsernames: autoSelectedRmUsernames,
        selectedOpUsernames: autoSelectedOpUsernames,
        perEmployeeLimits: autoPerEmployeeLimits,
        intervalMinutes,
      });
      const saved = await saveBulkAssignScheduler(payload);
      setActiveSchedulerId(saved.id);
      const result = await runBulkAssignScheduler(saved.id);
      setLastAutoRun(result.summary || null);
      await loadSchedulers();
      await loadAllSchedulers();
      setStatus({ type: 'success', message: result.message || 'Auto-assign run completed.' });
      if (onSuccess) onSuccess();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setStatus({
        type: 'error',
        message: typeof detail === 'string' ? detail : 'Auto-assign run failed. Save the rule first, then try Run now.',
      });
    } finally {
      setAutoRunLoading(false);
    }
  };

  const handleExecuteAssign = async () => {
    setAssignLoading(true);
    try {
      const apiBase = '/api/v1/crm/leads';
      const assignments = [];
      if (manualAssignmentRoles.RM) {
        assignments.push({
          role: 'RM',
          usernames: manualSelectedRmUsernames,
          perEmployeeLimit: parsePerEmployeeLimit(manualPerEmployeeLimits.RM),
        });
      }
      if (manualAssignmentRoles.OP) {
        assignments.push({
          role: 'OP',
          usernames: manualSelectedOpUsernames,
          perEmployeeLimit: parsePerEmployeeLimit(manualPerEmployeeLimits.OP),
        });
      }

      let totalAssigned = 0;
      const roleSummaries = [];
      const batchLogRoles = {};

      for (let i = 0; i < assignments.length; i += 1) {
        const { role, usernames, perEmployeeLimit } = assignments[i];
        const isLast = i === assignments.length - 1;
        const response = await api.post(`${apiBase}/bulk-assign/execute`, {
          lead_ids: selectedLeadIds,
          selected_usernames: usernames,
          assignment_role: role,
          per_employee_limit: perEmployeeLimit,
          suppress_log: !isLast,
          batch_log_roles: isLast && Object.keys(batchLogRoles).length > 0 ? batchLogRoles : undefined,
        });
        const assigned = response.data?.total_assigned ?? 0;
        batchLogRoles[role] = {
          total_assigned: assigned,
          per_employee_counts: response.data?.per_employee_counts ?? {},
        };
        totalAssigned += assigned;
        roleSummaries.push(`${assigned} as ${role}`);
      }

      const summary =
        assignments.length > 1
          ? `Successfully assigned leads (${roleSummaries.join(', ')}).`
          : `Successfully assigned ${totalAssigned} leads.`;

      setStatus({ type: 'success', message: summary });
      setCandidates([]);
      setSelectedLeadIds([]);
      setManualSelectedRmUsernames([]);
      setManualSelectedOpUsernames([]);
      setManualPerEmployeeLimits({ RM: '', OP: '' });
      if (onSuccess) onSuccess();
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.detail || 'Assignment failed.' });
    } finally {
      setAssignLoading(false);
    }
  };

  const handleFilterChange = (key, value) => {
    if (assignMode === 'manual') {
      setManualFilters((prev) => ({ ...prev, [key]: value }));
    } else {
      setAutoFilters((prev) => ({ ...prev, [key]: value }));
    }
  };

  const toggleFilterKey = (key) => {
    const isActive = activeFilterKeys.includes(key);
    const keySetter = assignMode === 'manual' ? setManualActiveFilterKeys : setAutoActiveFilterKeys;
    const filterSetter = assignMode === 'manual' ? setManualFilters : setAutoFilters;

    if (isActive) {
      keySetter((prev) => prev.filter((k) => k !== key));
      filterSetter((prev) => ({
        ...prev,
        [key]: Array.isArray(DEFAULT_BULK_FILTERS[key]) ? [] : DEFAULT_BULK_FILTERS[key],
      }));
    } else {
      keySetter((prev) => [...prev, key]);
    }
  };

  const availableFilterOptions = useMemo(() => {
    const options = [
      { key: 'stages', label: 'Stages' },
      { key: 'rm_ids', label: 'RM' },
      { key: 'op_ids', label: 'OP' },
      { key: 'lead_types', label: 'Lead Types' },
      { key: 'tags', label: 'Tags' },
      { key: 'lead_sources', label: 'Lead Sources' },
      { key: 'entity_types', label: 'Entity Types' },
      { key: 'follow_up_statuses', label: 'Follow up Statuses' },
      { key: 'null_fields', label: 'Null Fields' },
      { key: 'not_null_fields', label: 'Not Null Fields' },
      { key: 'is_active', label: 'Is Active' },
    ];
    if (isIncomeTaxCrm) {
      options.splice(5, 0, { key: 'ays', label: 'Assessment Years' });
    }
    return options;
  }, [isIncomeTaxCrm]);

  const multiValueFilterLabels = {
    lead_types: 'Lead Types',
    ays: 'Assessment Years',
    tags: 'Tags',
    lead_sources: 'Lead Sources',
    entity_types: 'Entity Types',
    follow_up_statuses: 'Follow up Statuses',
  };

  const multiValueFilterKeys = useMemo(() => {
    const keys = ['lead_types', 'tags', 'lead_sources', 'entity_types', 'follow_up_statuses'];
    if (isIncomeTaxCrm) keys.splice(1, 0, 'ays');
    return keys;
  }, [isIncomeTaxCrm]);

  const handleAutoNext = () => {
    if (!schedulerName.trim()) {
      setStatus({ type: 'error', message: 'Enter a scheduler name before continuing.' });
      return;
    }
    setStatus(null);
    setAutoStep(2);
    fetchActiveRmOpLists();
  };

  const schedulerSwitchOptions = useMemo(
    () => schedulers.map((s) => ({
      value: String(s.id),
      label: s.enabled ? `${s.name} · running` : s.name,
    })),
    [schedulers],
  );

  const handleSchedulerSwitch = (value) => {
    if (!value) return;
    const sched = schedulers.find((s) => String(s.id) === value);
    if (sched) handleSelectScheduler(sched);
  };

  return (
    <div className="bulk-assign-container expanded">
      <div className="bulk-assign-header">
        <div className="header-title">
          <Users size={20} className="icon" />
          <span>Advanced Bulk Assignment</span>
        </div>
        <div className="toggle-group mini assign-mode-toggle">
          <button
            type="button"
            className={assignMode === 'manual' ? 'active' : ''}
            onClick={() => { setAssignMode('manual'); setCurrentStep(1); setStatus(null); }}
            aria-pressed={assignMode === 'manual'}
          >
            Manual
          </button>
          <button
            type="button"
            className={assignMode === 'auto' ? 'active' : ''}
            onClick={() => { setAssignMode('auto'); setAutoStep(1); setStatus(null); }}
            aria-pressed={assignMode === 'auto'}
          >
            <Zap size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} />
            Auto
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className="bulk-assign-body">
          {(assignMode === 'manual' ? currentStep === 1 : autoStep === 1) && (
            <>
              {assignMode === 'auto' && (
                <>
                  {!storageReady && (
                    <div className={`status-alert error`} style={{ marginBottom: 16 }}>
                      <AlertCircle size={18} />
                      <span>
                        Run backend script <code>scripts/crm_bulk_assign_scheduler.sql</code> once to enable
                        schedulers and assignment logs.
                      </span>
                    </div>
                  )}
                  <div className="scheduler-overview-panel">
                    <div className="scheduler-overview-header">
                      <div>
                        <h4>Scheduler overview</h4>
                        <p className="assignment-role-hint">
                          {allSchedulersLoading
                            ? 'Loading schedulers…'
                            : `${schedulerSummary.running} running · ${schedulerSummary.stopped} stopped · ${schedulerSummary.total} total`}
                        </p>
                      </div>
                      <div className="scheduler-overview-actions">
                        <button
                          type="button"
                          className="btn-icon-mini"
                          title="Refresh overview"
                          onClick={loadAllSchedulers}
                          disabled={allSchedulersLoading}
                        >
                          <Activity size={14} />
                        </button>
                      </div>
                    </div>
                    {allSchedulersLoading ? (
                      <div className="scheduler-list-empty"><Loader2 className="spin" size={16} /> Loading…</div>
                    ) : allSchedulers.length === 0 ? (
                      <p className="assignment-role-hint">No schedulers saved yet. Use <strong>New scheduler</strong> below to create one.</p>
                    ) : (
                      <div className="scheduler-overview-table-wrap">
                        <table className="scheduler-overview-table">
                          <thead>
                            <tr>
                              <th>Status</th>
                              <th>Scheduler</th>
                              <th>Where</th>
                              <th>Every</th>
                              <th>Last run</th>
                              <th>On / off</th>
                            </tr>
                          </thead>
                          <tbody>
                            {allSchedulers.map((sched) => (
                              <tr
                                key={sched.id}
                                className={`scheduler-overview-row ${activeSchedulerId === sched.id ? 'active' : ''}`}
                                onClick={() => handleOpenSchedulerFromOverview(sched)}
                              >
                                <td>
                                  <span className={`scheduler-status-badge ${sched.enabled ? 'running' : 'stopped'}`}>
                                    {sched.enabled ? <Zap size={12} /> : <Power size={12} />}
                                    {sched.enabled ? 'Running' : 'Stopped'}
                                  </span>
                                </td>
                                <td className="scheduler-overview-name">{sched.name}</td>
                                <td>
                                  <span className="scheduler-entity-badge">
                                    <MapPin size={11} />
                                    {formatEntityLabel(sched.entity_type)}
                                  </span>
                                </td>
                                <td>{sched.interval_minutes}m</td>
                                <td>{formatSchedulerLastRun(sched)}</td>
                                <td onClick={(e) => e.stopPropagation()}>
                                  <div className="scheduler-overview-row-actions">
                                    <SchedulerToggle
                                      enabled={sched.enabled}
                                      disabled={togglingSchedulerId === sched.id}
                                      title={sched.enabled ? 'Turn off scheduler' : 'Turn on scheduler'}
                                      onChange={(next) => handleToggleSchedulerEnabled(sched, next)}
                                    />
                                    <button
                                      type="button"
                                      className="scheduler-list-delete"
                                      title="Delete scheduler"
                                      onClick={() => handleDeleteScheduler(sched.id)}
                                    >
                                      <Trash2 size={14} />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                  <div className="scheduler-editor-panel">
                    <div className="scheduler-editor-head">
                      <div className="scheduler-editor-head-text">
                        <h4>
                          {isCreatingNewScheduler || !activeSchedulerId ? 'New scheduler' : 'Edit scheduler'}
                        </h4>
                        <p className="assignment-role-hint">
                          {autoConfigLoading ? (
                            <><Loader2 className="spin" size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} /> Loading…</>
                          ) : isCreatingNewScheduler || !activeSchedulerId ? (
                            'Configure filters and assignment, then save to add this rule.'
                          ) : (
                            `Editing #${activeSchedulerId} — save updates only this rule.`
                          )}
                        </p>
                      </div>
                      <button type="button" className="btn-new-scheduler" onClick={handleNewScheduler}>
                        <Plus size={14} />
                        New scheduler
                      </button>
                    </div>
                    <div className="scheduler-editor-body">
                      {schedulers.length > 0 && (
                        <div className="scheduler-switcher">
                          <label htmlFor="scheduler-switch">Switch to saved scheduler</label>
                          <FormCustomSelect
                            className="scheduler-switch-select"
                            name="scheduler_switch"
                            value={isCreatingNewScheduler || !activeSchedulerId ? '' : String(activeSchedulerId)}
                            onChange={(e) => handleSchedulerSwitch(e.target.value)}
                            options={optionsFromPairs([
                              {
                                value: '',
                                label: isCreatingNewScheduler || !activeSchedulerId
                                  ? '— New (unsaved) —'
                                  : 'Select a saved scheduler…',
                              },
                              ...schedulerSwitchOptions.map((o) => ({ value: o.value, label: o.label })),
                            ])}
                            placeholder="Select scheduler"
                            ariaLabel="Switch scheduler"
                            portal={false}
                          />
                        </div>
                      )}
                      <div className="scheduler-name-row">
                        <label htmlFor="scheduler-name">Scheduler name</label>
                        <input
                          id="scheduler-name"
                          className="crm-input-field"
                          value={schedulerName}
                          onChange={(e) => setSchedulerName(e.target.value)}
                          placeholder="e.g. Fresh leads → OP pool"
                        />
                      </div>
                    </div>
                  </div>
                </>
              )}
              <div className="bulk-assign-section-header">
                <Filter size={16} />
                <div>
                  <h4>Lead selection filters</h4>
                  <p className="assignment-role-hint">
                    {assignMode === 'manual'
                      ? 'Choose which leads to include, then continue to assignment.'
                      : 'Define which leads this scheduler picks up on each run.'}
                  </p>
                </div>
              </div>
              <div className="swagger-layout bulk-assign-filters-layout">
            <div className="filters-list-col">
              <div className="logic-controls-row">
                <div className="logic-inputs-group" style={{ display: 'flex', gap: '16px', alignItems: 'flex-end' }}>
                  <div className="logic-box-container">
                    <span className="logic-title">Match Mode</span>
                    <FormCustomSelect
                      className="logic-dropdown-box"
                      name="match_mode"
                      value={filters.match_mode}
                      onChange={(e) => handleFilterChange('match_mode', e.target.value)}
                      options={optionsFromConfigOnly([
                        { value: 'AND', label: 'AND' },
                        { value: 'OR', label: 'OR' },
                      ])}
                      placeholder="Match mode"
                      ariaLabel="Match mode"
                      portal={false}
                    />
                  </div>

                  <div className="logic-box-container">
                    <span className="logic-title">Filter Mode</span>
                    <FormCustomSelect
                      className="logic-dropdown-box"
                      name="filter_mode"
                      value={filters.filter_mode}
                      onChange={(e) => handleFilterChange('filter_mode', e.target.value)}
                      options={optionsFromConfigOnly([
                        { value: 'IN', label: 'IN' },
                        { value: 'NOT_IN', label: 'NOT IN' },
                      ])}
                      placeholder="Filter mode"
                      ariaLabel="Filter mode"
                      portal={false}
                    />
                  </div>

                  <div className="logic-box-container">
                    <span className="logic-title">Fetch Limit</span>
                    <input 
                      type="number" 
                      className="logic-dropdown-box" 
                      style={{ width: '80px', textAlign: 'center' }}
                      value={filters.limit}
                      onChange={(e) => handleFilterChange('limit', parseInt(e.target.value) || 0)}
                    />
                  </div>

                  <div className="logic-box-container dropdown-wrapper" style={{ position: 'relative' }} ref={filterDropdownRef}>
                    <button 
                      className="logic-dropdown-box filter-trigger-btn"
                      onClick={() => setIsFilterDropdownOpen(!isFilterDropdownOpen)}
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', background: 'rgba(var(--accent-rgb), 0.1)', borderColor: 'rgba(var(--accent-rgb), 0.3)', color: 'var(--accent)' }}
                    >
                      <Filter size={14} />
                      <span>Filters</span>
                      <ChevronDown size={14} style={{ transform: isFilterDropdownOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
                    </button>

                    {isFilterDropdownOpen && (
                      <div className="filter-selection-dropdown" style={{ 
                        position: 'absolute', 
                        top: '100%', 
                        left: 0, 
                        width: '220px',
                        background: 'var(--bg-elevated)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius-lg)',
                        marginTop: '8px',
                        zIndex: 1000,
                        boxShadow: 'var(--shadow-lg)',
                        padding: '8px'
                      }}>
                        {availableFilterOptions.map(opt => (
                          <div 
                            key={opt.key}
                            className={`filter-opt-item ${activeFilterKeys.includes(opt.key) ? 'selected' : ''}`}
                            onClick={() => {
                              toggleFilterKey(opt.key);
                            }}
                            style={{
                              padding: '10px 12px',
                              borderRadius: '8px',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              fontSize: '13px',
                              color: activeFilterKeys.includes(opt.key) ? 'var(--accent)' : 'rgba(var(--fg-rgb),0.6)',
                              background: activeFilterKeys.includes(opt.key) ? 'rgba(var(--accent-rgb), 0.05)' : 'transparent',
                              transition: 'all 0.2s'
                            }}
                          >
                            <span>{opt.label}</span>
                            {activeFilterKeys.includes(opt.key) && <Check size={14} />}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="filter-divider" />

              <div className="active-filters-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '16px' }}>
                {activeFilterKeys.includes('stages') && (
                  <div className="dynamic-filter-row">
                    <SearchableDropdown 
                      label="Stages"
                      options={metadata.stages.map(s => ({ value: s.code, label: s.name }))}
                      selected={filters.stages}
                      onChange={(val) => handleFilterChange('stages', val)}
                      placeholder="Add stage item"
                    />
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('stages')} aria-label="Remove stages filter"><X size={16} /></button>
                  </div>
                )}

                {activeFilterKeys.includes('rm_ids') && (
                  <div className="dynamic-filter-row">
                    <SearchableDropdown 
                      label="RM"
                      options={rmEmployeeOptions}
                      selected={filters.rm_ids}
                      onChange={(val) => handleFilterChange('rm_ids', val)}
                      placeholder="Select RM"
                    />
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('rm_ids')} aria-label="Remove RM filter"><X size={16} /></button>
                  </div>
                )}

                {activeFilterKeys.includes('op_ids') && (
                  <div className="dynamic-filter-row">
                    <SearchableDropdown 
                      label="OP"
                      options={opEmployeeOptions}
                      selected={filters.op_ids}
                      onChange={(val) => handleFilterChange('op_ids', val)}
                      placeholder="Select OP"
                    />
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('op_ids')} aria-label="Remove OP filter"><X size={16} /></button>
                  </div>
                )}

                {multiValueFilterKeys.map(key => activeFilterKeys.includes(key) && (
                  <div className="dynamic-filter-row" key={key}>
                    <SearchableDropdown 
                      label={multiValueFilterLabels[key] || key}
                      options={
                        key === 'follow_up_statuses'
                          ? metadata.followUpStatuses.map(s => ({ value: s, label: s }))
                          : key === 'ays'
                            ? ayFilterOptions
                            : []
                      }
                      selected={filters[key]}
                      onChange={(val) => handleFilterChange(key, val)}
                      placeholder={
                        key === 'ays'
                          ? 'Select or type assessment year'
                          : key === 'lead_types'
                            ? 'Select or type lead type'
                            : 'Add string item'
                      }
                      allowCustom={['lead_types', 'ays', 'tags', 'lead_sources'].includes(key)}
                    />
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey(key)} aria-label={`Remove ${multiValueFilterLabels[key] || key} filter`}><X size={16} /></button>
                  </div>
                ))}

                {activeFilterKeys.includes('null_fields') && (
                  <div className="dynamic-filter-row">
                    <SearchableDropdown 
                      label="Null Fields"
                      options={metadata.nullFieldOptions.map(f => ({ value: f, label: f.replace(/_/g, ' ') }))}
                      selected={filters.null_fields}
                      onChange={(val) => handleFilterChange('null_fields', val)}
                      placeholder="Add string item"
                    />
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('null_fields')} aria-label="Remove null fields filter"><X size={16} /></button>
                  </div>
                )}

                {activeFilterKeys.includes('not_null_fields') && (
                  <div className="dynamic-filter-row">
                    <SearchableDropdown 
                      label="Not Null Fields"
                      options={metadata.nullFieldOptions.map(f => ({ value: f, label: f.replace(/_/g, ' ') }))}
                      selected={filters.not_null_fields}
                      onChange={(val) => handleFilterChange('not_null_fields', val)}
                      placeholder="Add string item"
                    />
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('not_null_fields')} aria-label="Remove not null fields filter"><X size={16} /></button>
                  </div>
                )}

                {activeFilterKeys.includes('is_active') && (
                  <div className="dynamic-filter-row">
                    <div className="searchable-dropdown-container">
                      <label className="dropdown-label">Is Active</label>
                      <FormCustomSelect
                        className="dropdown-box"
                        name="is_active"
                        value={filters.is_active === null ? '' : filters.is_active.toString()}
                        onChange={(e) => handleFilterChange('is_active', e.target.value === '' ? null : e.target.value === 'true')}
                        options={optionsFromPairs([
                          { value: '', label: '--' },
                          { value: 'true', label: 'True' },
                          { value: 'false', label: 'False' },
                        ])}
                        placeholder="--"
                        ariaLabel="Is active"
                        portal={false}
                      />
                    </div>
                    <button type="button" className="btn-remove-filter" onClick={() => toggleFilterKey('is_active')} aria-label="Remove is active filter"><X size={16} /></button>
                  </div>
                )}
              </div>

              </div>
            </div>

            <div className="bulk-assign-step-footer">
              <div className="matching-leads-preview">
                {isCountLoading ? (
                  <>
                    <Loader2 className="spin" size={14} />
                    <span>Updating count...</span>
                  </>
                ) : (
                  <>
                    <Filter size={14} />
                    <span><strong>{previewCount}</strong> leads matching current filters</span>
                  </>
                )}
              </div>
              {assignMode === 'manual' ? (
                <button
                  className="btn-fetch"
                  onClick={fetchCandidates}
                  disabled={loading}
                  style={{ width: '160px', height: '48px', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
                >
                  {loading ? <Loader2 className="spin" size={18} /> : <ArrowRight size={18} />}
                  <span>Next</span>
                </button>
              ) : (
                <button
                  className="btn-fetch"
                  onClick={handleAutoNext}
                  style={{ width: '160px', height: '48px', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
                >
                  <ArrowRight size={18} />
                  <span>Next</span>
                </button>
              )}
            </div>
          </>
          )}

          {status && (
            <div className={`status-alert ${status.type}`}>
              {status.type === 'success' ? <CheckCircle2 size={18} /> : status.type === 'error' ? <AlertCircle size={18} /> : <Activity size={18} />}
              <span>{status.message}</span>
            </div>
          )}

          {assignMode === 'manual' && currentStep === 2 && candidates.length > 0 && (
            <div className="assignment-workbench">
              <div className="workbench-header-row">
                <button
                  type="button"
                  className="btn-back-to-filters"
                  onClick={() => setCurrentStep(1)}
                >
                  <X size={16} />
                  <span>Back to Filters</span>
                </button>
              </div>
              <div className="workbench-single-col">
                <div className="count-display-card">
                  <div className="count-value">{candidateTotal}</div>
                  <div className="count-label">Leads matching your filters</div>
                  <div className="count-subtext">Ready to be distributed among selected employees</div>
                </div>

                <div className="assignment-config-section">
                  <div className="config-header">
                    <UserPlus size={18} />
                    <h4>Assignment Configuration</h4>
                  </div>
                  
                  <div className="config-grid">
                    <div className="config-item">
                      <label>1. Assign Leads As:</label>
                      <div className="toggle-group mini toggle-group--multi">
                        <button
                          type="button"
                          className={assignmentRoles.RM ? 'active' : ''}
                          onClick={() => toggleAssignmentRole('RM')}
                          aria-pressed={assignmentRoles.RM}
                        >
                          RM
                        </button>
                        <button
                          type="button"
                          className={assignmentRoles.OP ? 'active' : ''}
                          onClick={() => toggleAssignmentRole('OP')}
                          aria-pressed={assignmentRoles.OP}
                        >
                          OP
                        </button>
                      </div>
                      <p className="assignment-role-hint">
                        Select RM only, OP only, or both (turn on each role you want to assign).
                      </p>
                    </div>

                    {assignmentRoles.RM && (
                      <div className="config-item config-item--role-block">
                        <label>2. Select RMs:</label>
                        <SearchableDropdown
                          placeholder={assigneesLoading ? 'Loading RMs...' : activeRmUsernames.length ? 'Select RMs...' : 'No active RMs found'}
                          options={rmEmployeeOptions}
                          selected={selectedRmUsernames}
                          onChange={setSelectedRmUsernames}
                        />
                        <label className="limit-sublabel">Max leads per RM (optional)</label>
                        <input
                          type="number"
                          min={1}
                          className="crm-input-field role-limit-input"
                          placeholder="No limit (round-robin)"
                          value={perEmployeeLimits.RM}
                          onChange={(e) => setRolePerEmployeeLimit('RM', e.target.value)}
                        />
                      </div>
                    )}

                    {assignmentRoles.OP && (
                      <div className="config-item config-item--role-block">
                        <label>{assignmentRoles.RM ? '3. Select OPs:' : '2. Select OPs:'}</label>
                        <SearchableDropdown
                          placeholder={assigneesLoading ? 'Loading OPs...' : activeOpUsernames.length ? 'Select OPs...' : 'No active OPs found'}
                          options={opEmployeeOptions}
                          selected={selectedOpUsernames}
                          onChange={setSelectedOpUsernames}
                        />
                        <label className="limit-sublabel">Max leads per OP (optional)</label>
                        <input
                          type="number"
                          min={1}
                          className="crm-input-field role-limit-input"
                          placeholder="No limit (round-robin)"
                          value={perEmployeeLimits.OP}
                          onChange={(e) => setRolePerEmployeeLimit('OP', e.target.value)}
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="execution-row">
                <div className="execution-summary">
                  Distributing <strong>{selectedLeadIds.length}</strong> leads
                  {assignmentRoles.RM && (
                    <>
                      {' '}to <strong>{selectedRmUsernames.length}</strong> RM{selectedRmUsernames.length === 1 ? '' : 's'}
                      {parsePerEmployeeLimit(perEmployeeLimits.RM) != null && (
                        <> (max <strong>{parsePerEmployeeLimit(perEmployeeLimits.RM)}</strong> each)</>
                      )}
                    </>
                  )}
                  {assignmentRoles.RM && assignmentRoles.OP && ' and'}
                  {assignmentRoles.OP && (
                    <>
                      {' '}<strong>{selectedOpUsernames.length}</strong> OP{selectedOpUsernames.length === 1 ? '' : 's'}
                      {parsePerEmployeeLimit(perEmployeeLimits.OP) != null && (
                        <> (max <strong>{parsePerEmployeeLimit(perEmployeeLimits.OP)}</strong> each)</>
                      )}
                    </>
                  )}
                  .
                </div>
                <button className="btn-execute" onClick={handleExecuteAssign} disabled={assignLoading || !canExecuteAssign}>
                  {assignLoading ? <Loader2 className="spin" size={18} /> : <UserPlus size={18} />}
                  Confirm & Execute Distribution
                </button>
              </div>
            </div>
          )}

          {assignMode === 'auto' && autoStep === 2 && (
            <div className="assignment-workbench">
              <div className="workbench-header-row">
                <button
                  type="button"
                  className="btn-back-to-filters"
                  onClick={() => setAutoStep(1)}
                >
                  <X size={16} />
                  <span>Back to Filters</span>
                </button>
                <span className={`scheduler-step-badge ${isCreatingNewScheduler || !activeSchedulerId ? 'is-new' : ''}`}>
                  {isCreatingNewScheduler || !activeSchedulerId
                    ? `New · ${schedulerName || 'Scheduler'}`
                    : `#${activeSchedulerId} · ${schedulerName}`}
                </span>
              </div>
              <div className="workbench-single-col">
                <div className="count-display-card">
                  <div className="count-value">{previewCount}</div>
                  <div className="count-label">Leads matching your filters</div>
                  <div className="count-subtext">Eligible for this scheduler on each run</div>
                </div>

                <div className="assignment-config-section">
                  <div className="config-header">
                    <UserPlus size={18} />
                    <h4>Assignment Configuration</h4>
                  </div>

                  <div className="config-grid">
                    <div className="config-item">
                      <label>1. Assign Leads As:</label>
                      <div className="toggle-group mini toggle-group--multi">
                        <button
                          type="button"
                          className={autoAssignmentRoles.RM ? 'active' : ''}
                          onClick={() => toggleAssignmentRole('RM')}
                          aria-pressed={autoAssignmentRoles.RM}
                        >
                          RM
                        </button>
                        <button
                          type="button"
                          className={autoAssignmentRoles.OP ? 'active' : ''}
                          onClick={() => toggleAssignmentRole('OP')}
                          aria-pressed={autoAssignmentRoles.OP}
                        >
                          OP
                        </button>
                      </div>
                      <p className="assignment-role-hint">
                        Select RM only, OP only, or both. Leads are distributed round-robin across selected employees.
                      </p>
                    </div>

                    {autoAssignmentRoles.RM && (
                      <div className="config-item config-item--role-block">
                        <label>2. Select RMs:</label>
                        <SearchableDropdown
                          placeholder={assigneesLoading ? 'Loading RMs...' : 'Select RMs...'}
                          options={rmEmployeeOptions}
                          selected={autoSelectedRmUsernames}
                          onChange={setAutoSelectedRmUsernames}
                        />
                        <label className="limit-sublabel">Max leads per RM per run (optional)</label>
                        <input
                          type="number"
                          min={1}
                          className="crm-input-field role-limit-input"
                          placeholder="No limit (round-robin)"
                          value={autoPerEmployeeLimits.RM}
                          onChange={(e) => setRolePerEmployeeLimit('RM', e.target.value)}
                        />
                      </div>
                    )}

                    {autoAssignmentRoles.OP && (
                      <div className="config-item config-item--role-block">
                        <label>{autoAssignmentRoles.RM ? '3. Select OPs:' : '2. Select OPs:'}</label>
                        <SearchableDropdown
                          placeholder={assigneesLoading ? 'Loading OPs...' : 'Select OPs...'}
                          options={opEmployeeOptions}
                          selected={autoSelectedOpUsernames}
                          onChange={setAutoSelectedOpUsernames}
                        />
                        <label className="limit-sublabel">Max leads per OP per run (optional)</label>
                        <input
                          type="number"
                          min={1}
                          className="crm-input-field role-limit-input"
                          placeholder="No limit (round-robin)"
                          value={autoPerEmployeeLimits.OP}
                          onChange={(e) => setRolePerEmployeeLimit('OP', e.target.value)}
                        />
                      </div>
                    )}

                    <div className="config-item">
                      <label>Run every (minutes)</label>
                      <input
                        type="number"
                        min={1}
                        max={1440}
                        className="crm-input-field role-limit-input"
                        value={intervalMinutes}
                        onChange={(e) => setIntervalMinutes(parseInt(e.target.value, 10) || 5)}
                      />
                    </div>

                    <div className="config-item config-item--checkbox">
                      <input
                        type="checkbox"
                        id="auto-enabled"
                        checked={autoEnabled}
                        onChange={(e) => setAutoEnabled(e.target.checked)}
                      />
                      <label htmlFor="auto-enabled">Enable auto-assign (scheduler)</label>
                    </div>
                  </div>

                  {lastAutoRun && (
                    <div className="matching-leads-preview auto-last-run">
                      <Activity size={14} />
                      <span>
                        Last run: {lastAutoRun.ran_at || '—'}
                        {lastAutoRun.candidates_matched != null && ` · ${lastAutoRun.candidates_matched} matched`}
                        {lastAutoRun.roles?.RM && ` · RM assigned ${lastAutoRun.roles.RM.total_assigned || 0}`}
                        {lastAutoRun.roles?.OP && ` · OP assigned ${lastAutoRun.roles.OP.total_assigned || 0}`}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="execution-row">
                <div className="execution-summary">
                  Scheduler <strong>{schedulerName}</strong> will assign up to <strong>{previewCount}</strong> matching leads
                  {autoAssignmentRoles.RM && (
                    <>
                      {' '}to <strong>{autoSelectedRmUsernames.length}</strong> RM{autoSelectedRmUsernames.length === 1 ? '' : 's'}
                      {parsePerEmployeeLimit(autoPerEmployeeLimits.RM) != null && (
                        <> (max <strong>{parsePerEmployeeLimit(autoPerEmployeeLimits.RM)}</strong> each per run)</>
                      )}
                    </>
                  )}
                  {autoAssignmentRoles.RM && autoAssignmentRoles.OP && ' and'}
                  {autoAssignmentRoles.OP && (
                    <>
                      {' '}<strong>{autoSelectedOpUsernames.length}</strong> OP{autoSelectedOpUsernames.length === 1 ? '' : 's'}
                      {parsePerEmployeeLimit(autoPerEmployeeLimits.OP) != null && (
                        <> (max <strong>{parsePerEmployeeLimit(autoPerEmployeeLimits.OP)}</strong> each per run)</>
                      )}
                    </>
                  )}
                  {' '}every <strong>{intervalMinutes}</strong> min.
                </div>
                <div className="execution-actions">
                  <button
                    type="button"
                    className="btn-drawer-today"
                    onClick={handleRunAutoNow}
                    disabled={autoRunLoading || !canSaveAutoConfig}
                    title="Saves current settings and runs one assignment cycle now"
                  >
                    {autoRunLoading ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                    Run now
                  </button>
                  <button
                    type="button"
                    className="btn-execute"
                    onClick={handleSaveAutoConfig}
                    disabled={autoSaving || !canSaveAutoConfig}
                  >
                    {autoSaving ? <Loader2 className="spin" size={18} /> : <Zap size={18} />}
                    {isCreatingNewScheduler || !activeSchedulerId ? 'Create scheduler' : 'Save auto rule'}
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  );
};

export default BulkAssign;
