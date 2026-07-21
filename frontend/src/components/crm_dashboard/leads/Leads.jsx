import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Search, Filter, X, PhoneCall, User, Activity, Clock, History, MessageSquare, ArrowRight, Loader2, Users, FileSpreadsheet, AlertCircle, Info, FileText, ShieldCheck, ClipboardCheck, Briefcase, Globe, Mail, Phone, FileSignature, CheckCircle2 } from 'lucide-react';
import { useCrmLeadPush } from '../useCrmLeadPush';
import CrmLeadsListTable from '../CrmLeadsListTable';
import CrmLeadViewDrawer from '../CrmLeadViewDrawer';
import CrmLeadCallActionDrawer from '../CrmLeadCallActionDrawer';
import CrmLeadFilterDrawer from '../CrmLeadFilterDrawer';
import CrmLeadFiltersToolbar from '../CrmLeadFiltersToolbar';
import CreateLeadModal from '../CreateLeadModal';
import CrmLeadHistorySummary from '../CrmLeadHistorySummary';
import './Leads.css';
import '../crmLeadsBoard.css';
import api from '../../../utils/api';
import { unwrapListPayload } from '../../../utils/apiResponse';
import Pagination from '../../common/Pagination';
import { useListLoading } from '../../../hooks/useListLoading';
import {
    buildEmptyLeadFilters,
    buildCrmLeadFilterApiParams,
    serializeCrmLeadFilterParams,
    hasActiveLeadFilters,
} from '../crmLeadFilters';
import {
    getAvailableStatusCodes,
    isSchedulePaymentCallStatus,
    normalizeSchedulePaymentCallStatus,
    normalizeStage,
    resolveCallTypeForLeadUpdate,
} from '../crmLeadPitchUtils';
import {
    getLeadActivitiesApiPath,
    submitCrmLeadCallUpdate,
    extractCrmApiErrorMessage,
    resolveCompleteOpenFollowupOnCallUpdate,
} from '../../../utils/crmLeadApi';

const Leads = ({
  entityType = 'GST_REGISTRATION',
  initialStage = null,
  initialFilters = null,
  hideFilters = false,
  boardPreset = null,
  targetLeadId = null,
  targetEntityId = null,
  targetView = 'action',
  targetCallStatus = null,
  onLeadOpened = null,
  currentRole = null,
  currentEmpId = null,
}) => {
  // Create Lead is only offered on the main Leads tab (which passes the current
  // user's role), not on the derived boards (payment-pending, today-assigned).
  const canCreateLead = Boolean(currentRole) && !boardPreset && !hideFilters;
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalLeads, setTotalLeads] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 20;

  // Drawer States
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [selectedLead, setSelectedLead] = useState(null);
  const [activeActionTab, setActiveActionTab] = useState('call'); // 'call' or 'edit'
  const [viewMode, setViewMode] = useState('list'); // 'list' or 'history'
  const [historyActivities, setHistoryActivities] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLead, setHistoryLead] = useState(null);
  const [viewLead, setViewLead] = useState(null);
  const [historyCurrentPage, setHistoryCurrentPage] = useState(1);
  const [historyTotal, setHistoryTotal] = useState(0);

  // Lead Details Data
  const [registrationData, setRegistrationData] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState(null);

  const [appliedFilters, setAppliedFilters] = useState(() => buildEmptyLeadFilters(initialFilters));
  const [filterInputs, setFilterInputs] = useState(() => buildEmptyLeadFilters(initialFilters));
  const { wrapFetch } = useListLoading();

  const [errors, setErrors] = useState({});
  const [showCreateModal, setShowCreateModal] = useState(false);
  const deepLinkConsumedKeyRef = useRef(null);

  const getCrmLeadsApiBases = useCallback((entityTypeNorm) => (
    entityTypeNorm === 'INCOME_TAX'
      ? ['/api/v1/crm/leads', '/api/v1/crm/itr/leads']
      : ['/api/v1/crm/leads']
  ), []);

  const fetchLeadForDeepLink = useCallback(async (entityTypeNorm, leadId, entityId) => {
    const entityTypeParam = encodeURIComponent(entityTypeNorm);
    const query = leadId
      ? `id=${encodeURIComponent(leadId)}`
      : `entity_id=${encodeURIComponent(entityId)}`;
    const bases = getCrmLeadsApiBases(entityTypeNorm);
    for (const apiBase of bases) {
      try {
        const res = await api.get(
          `${apiBase}/filter?${query}&limit=1&entity_type=${entityTypeParam}`
        );
        const lead = res.data?.items?.[0];
        if (lead) return lead;
      } catch (err) {
        console.warn(`Deep-link lead lookup failed on ${apiBase}:`, err);
      }
    }
    return null;
  }, [getCrmLeadsApiBases]);

  const closeCallActionDrawer = useCallback(() => {
    setSelectedLead(null);
    setCompleteFollowupOnSave(false);
    deepLinkConsumedKeyRef.current = null;
    if (onLeadOpened) onLeadOpened();
  }, [onLeadOpened]);

  useEffect(() => {
    if (initialFilters) {
      setAppliedFilters((prev) => ({ ...prev, ...initialFilters }));
      setFilterInputs((prev) => ({ ...prev, ...initialFilters }));
      setCurrentPage(1);
    }
  }, [initialFilters]);

  // UI Mappings
  const [mappingData, setMappingData] = useState({ stage_to_pitch: [], pitch_to_statuses: {} });
  const [stages, setStages] = useState([]);

  // Edit Form State
  const [editFormData, setEditFormData] = useState({
    rm_id: '',
    op_id: '',
    stage: '',
    remarks: ''
  });

  const getIstDateKey = useCallback((input) => {
    if (!input) return null;
    const dt = new Date(input);
    if (Number.isNaN(dt.getTime())) return null;
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(dt);
  }, []);

  const todayAssignedRoleFilter = useCallback((items, scope = {}) => {
    const role = String(scope.role || '').toUpperCase();
    const selfEmpId = Number(scope.empId) || null;
    const rmTeamIds = Array.isArray(scope.rmTeamIds) ? scope.rmTeamIds.map(Number).filter(Boolean) : [];
    const opTeamIds = Array.isArray(scope.opTeamIds) ? scope.opTeamIds.map(Number).filter(Boolean) : [];

    const todayIst = getIstDateKey(new Date());
    if (!todayIst) return [];

    const isToday = (value) => getIstDateKey(value) === todayIst;
    const inSet = (set, value) => set.has(Number(value));

    const rmScope = new Set([selfEmpId, ...rmTeamIds].filter(Boolean));
    const opScope = new Set([selfEmpId, ...opTeamIds].filter(Boolean));

    return (Array.isArray(items) ? items : []).filter((lead) => {
      const rmToday = isToday(lead?.rm_assigned_at);
      const opToday = isToday(lead?.op_assigned_at);
      const rmId = lead?.rm_id;
      const opId = lead?.op_id;

      if (role === 'ADMIN') return rmToday || opToday;
      if (role === 'RM') return rmToday && Number(rmId) === selfEmpId;
      if (role === 'OP') return opToday && Number(opId) === selfEmpId;
      if (role === 'SALES_MANAGER') return rmToday && inSet(rmScope, rmId);
      if (role === 'OP_MANAGER') return opToday && inSet(opScope, opId);

      // Fallback for any other staff role.
      return (rmToday && Number(rmId) === selfEmpId) || (opToday && Number(opId) === selfEmpId);
    });
  }, [getIstDateKey]);

  // Call Log Form State
  const [callLogData, setCallLogData] = useState({
    call_type_code: '',
    call_status_code: '',
    followup_at: '',
    remarks: ''
  });

  const [saving, setSaving] = useState(false);
  /** true only when opened from Lead details "Update Call Status" (history); list call_status uses call-update only */
  const [completeFollowupOnSave, setCompleteFollowupOnSave] = useState(false);

  const {
    isIncomeTaxCrm,
    isGstCrm,
    isLeadPushed,
    handlePush,
    pushingLeadId,
    pushFeedback,
  } = useCrmLeadPush(entityType, setLeads);

  const fetchLeads = useCallback(async () => {
    await wrapFetch(setLoading, async () => {
      try {
      const searchParams = new URLSearchParams(
        serializeCrmLeadFilterParams(buildCrmLeadFilterApiParams(appliedFilters, {
          entity_type: (entityType || '').trim().toUpperCase(),
          is_active: true,
        })),
      );

      const apiBase = '/api/v1/crm/leads';

      if (boardPreset?.type === 'today-assigned') {
        const allItems = [];
        const pageLimit = 200;
        let pageOffset = 0;
        let keepFetching = true;

        while (keepFetching) {
          const pageParams = new URLSearchParams(searchParams.toString());
          pageParams.set('limit', String(pageLimit));
          pageParams.set('offset', String(pageOffset));

          const response = await api.get(`${apiBase}/filter?${pageParams.toString()}`);
          const batch = unwrapListPayload(response).items;
          allItems.push(...batch);

          if (batch.length < pageLimit) {
            keepFetching = false;
          } else {
            pageOffset += pageLimit;
          }

          // Hard stop safety to avoid runaway loop on bad API pagination.
          if (allItems.length >= 2000) keepFetching = false;
        }

        const filtered = todayAssignedRoleFilter(allItems, boardPreset.scope);
        const start = (currentPage - 1) * rowsPerPage;
        const paged = filtered.slice(start, start + rowsPerPage);
        setLeads(paged);
        setTotalLeads(filtered.length);
        return;
      }

      const pageParams = new URLSearchParams(searchParams.toString());
      pageParams.set('limit', String(rowsPerPage));
      pageParams.set('offset', String((currentPage - 1) * rowsPerPage));
      const response = await api.get(`${apiBase}/filter?${pageParams.toString()}`);
      const { items, total } = unwrapListPayload(response);
      setLeads(items);
      setTotalLeads(total || 0);
    } catch (error) {
      console.error("Error fetching leads:", error);
    }
    });
  }, [currentPage, appliedFilters, rowsPerPage, entityType, wrapFetch, boardPreset, todayAssignedRoleFilter]);

  const openFilterDrawer = () => {
    setFilterInputs({ ...appliedFilters, stages: [...appliedFilters.stages] });
    setIsFilterOpen(true);
  };

  const handleResetFilters = () => {
    const empty = buildEmptyLeadFilters(null);
    setFilterInputs(empty);
    setAppliedFilters(empty);
    setCurrentPage(1);
    setIsFilterOpen(false);
  };

  const handleApplyFilters = () => {
    setAppliedFilters({ ...filterInputs, stages: [...filterInputs.stages] });
    setCurrentPage(1);
    setIsFilterOpen(false);
  };

  const fetchMappings = async () => {
    try {
      const apiBase = '/api/v1/crm/leads';
      const [mappingRes, stagesRes] = await Promise.all([
        api.get(`${apiBase}/ui-mappings`, { params: { entity_type: entityType } }),
        api.get(`${apiBase}/stages`, { params: { entity_type: entityType } })
      ]);
      setMappingData(mappingRes.data);
      setStages(stagesRes.data.stages || []);
    } catch (err) {
      console.error("Failed to fetch UI mappings:", err);
    }
  };

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  useEffect(() => {
    fetchMappings();
  }, [entityType]);

  // Derive available pitch types for the current lead's stage
  const availablePitchTypes = useMemo(() => {
    if (!selectedLead) return [];
    const stageNorm = normalizeStage(selectedLead.stage);
    return mappingData.stage_to_pitch
      .filter((m) => normalizeStage(m.stage) === stageNorm)
      .map((m) => m.pitch_type_code);
  }, [selectedLead, mappingData]);

  // Derive available call statuses for the selected pitch type
  const availableStatuses = useMemo(() => {
    if (!callLogData.call_type_code) return [];
    const codes = getAvailableStatusCodes(callLogData.call_type_code, mappingData.pitch_to_statuses, {
      entityType,
      leadStage: selectedLead?.stage,
    });
    const selected = callLogData.call_status_code;
    if (selected && !codes.includes(selected)) {
      return [...codes, selected];
    }
    return codes;
  }, [callLogData.call_type_code, callLogData.call_status_code, mappingData, entityType, selectedLead?.stage]);

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

  const totalPages = Math.ceil(totalLeads / rowsPerPage);
  const historyTotalPages = Math.ceil(historyTotal / rowsPerPage);

  const handleRowClick = useCallback((lead, options = {}) => {
    setSelectedLead(lead);
    setCompleteFollowupOnSave(Boolean(options.completeFollowup));

    const initialStatusRaw = options.initialCallStatus || '';
    const initialStatus = isSchedulePaymentCallStatus(initialStatusRaw)
      ? normalizeSchedulePaymentCallStatus(initialStatusRaw)
      : initialStatusRaw;

    const pitchType = resolveCallTypeForLeadUpdate(lead, mappingData.stage_to_pitch, {
      initialCallStatus: initialStatus,
    });

    setEditFormData({
      rm_id: lead.rm_id || '',
      op_id: lead.op_id || '',
      stage: lead.stage || '',
      remarks: lead.remarks || ''
    });
    setCallLogData({
      call_type_code: pitchType,
      call_status_code: initialStatus,
      followup_at: '',
      remarks: ''
    });
    setActiveActionTab('call');
  }, [mappingData]);

  const fetchHistory = useCallback(async (leadId, page = 1) => {
    setHistoryLoading(true);
    try {
      const params = {
        limit: rowsPerPage,
        offset: (page - 1) * rowsPerPage,
        entity_type: (entityType || '').trim().toUpperCase()
      };
      const response = await api.get(getLeadActivitiesApiPath(entityType, leadId), { params });
      const { items, total } = unwrapListPayload(response);
      setHistoryActivities(items);
      setHistoryTotal(total ?? 0);
    } catch (err) {
      console.error("Failed to fetch history:", err);
    } finally {
      setHistoryLoading(false);
    }
  }, [entityType, rowsPerPage]);

  const handleViewHistory = useCallback(async (e, lead) => {
    if (e) e.stopPropagation();
    setHistoryLead(lead);
    setViewMode('history');
    setHistoryCurrentPage(1);

    setRegistrationData(null);
    setDetailsError(null);
    fetchHistory(lead.id, 1);

    const entityId = lead.entity_id || lead.id;

    if (entityId) {
      setDetailsLoading(true);
      try {
        const detailUrl = entityType === 'INCOME_TAX'
          ? `/api/v1/income-tax/${entityId}/full`
          : `/api/v1/gst-registrations/${entityId}/full`;

        const res = await api.get(detailUrl);

        if (res.data) {
          const normalizedData = entityType === 'INCOME_TAX'
            ? { registration: res.data.income_tax, ...res.data }
            : res.data;

          if (normalizedData.registration) {
            setRegistrationData(normalizedData);
          } else {
            setDetailsError("Detailed profile not found for this lead.");
          }
        }
      } catch (err) {
        console.error("Failed to fetch lead details:", err);
        if (err.response?.status === 404) {
          setDetailsError("No active registration record found for this lead.");
        } else {
          setDetailsError("Failed to load registration details.");
        }
      } finally {
        setDetailsLoading(false);
      }
    } else {
      setDetailsError("No linked entity ID found for this lead.");
    }
  }, [entityType, fetchHistory]);

  // Deep link: open CRM drawer only when target_view is set (e.g. schedule payment on allowed stages)
  useEffect(() => {
    if (!targetLeadId && !targetEntityId) return;
    if (!targetView) return;

    const urlParams = new URLSearchParams(window.location.search);
    const urlCallStatus = urlParams.get('target_call_status');
    const effectiveCallStatus = targetCallStatus || urlCallStatus || '';
    if (
      targetView === 'action'
      && isSchedulePaymentCallStatus(urlCallStatus)
      && !targetCallStatus
    ) {
      return;
    }

    const linkKey = [
      entityType,
      targetLeadId || '',
      targetEntityId || '',
      targetView || '',
      effectiveCallStatus,
    ].join('|');
    if (deepLinkConsumedKeyRef.current === linkKey) return;

    const fetchAndOpenTarget = async () => {
      try {
        const entityTypeNorm = (entityType || '').trim().toUpperCase();
        const lead = await fetchLeadForDeepLink(
          entityTypeNorm,
          targetLeadId,
          targetEntityId
        );
        if (!lead) return;

        deepLinkConsumedKeyRef.current = linkKey;

        if (targetView === 'history') {
          handleViewHistory(null, lead);
        } else if (targetView === 'view') {
          setViewLead(lead);
        } else if (targetView === 'action') {
          handleRowClick(lead, {
            initialCallStatus: effectiveCallStatus,
          });
        }
      } catch (err) {
        console.error('Failed to fetch target lead for deep-link:', err);
      }
    };
    fetchAndOpenTarget();
  }, [
    targetLeadId,
    targetEntityId,
    targetView,
    targetCallStatus,
    entityType,
    fetchLeadForDeepLink,
    handleRowClick,
    handleViewHistory,
  ]);

  const handleViewLead = (e, lead) => {
    if (e) e.stopPropagation();
    setViewLead(lead);
  };

  const handleEditLead = (e, lead) => {
    if (e) e.stopPropagation();
    handleRowClick(lead);
    setActiveActionTab('edit');
  };

  useEffect(() => {
    if (viewMode === 'history' && historyLead) {
      fetchHistory(historyLead.id, historyCurrentPage);
    }
  }, [viewMode, historyLead, historyCurrentPage, fetchHistory]);

  const handleSaveEdit = async () => {
    if (!selectedLead) return;
    setSaving(true);
    try {
      const apiBase = entityType === 'INCOME_TAX' ? '/api/v1/crm/itr/leads' : '/api/v1/crm/leads';
      await api.post(`${apiBase}/${selectedLead.id}/edit`, editFormData, { params: { entity_type: entityType } });
      closeCallActionDrawer();
      fetchLeads();
    } catch (err) {
      console.error("Failed to save lead info:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleLogCall = async () => {
    if (!selectedLead) return;

    // Clear previous errors
    setErrors({});
    let newErrors = {};

    if (!callLogData.call_type_code || !callLogData.call_status_code) {
      alert("Please select a Call Status.");
      return;
    }

    // Validation Rules
    const mandatoryStatuses = ['CALL_BACK', 'CONNECTED_AND_SCHEDULED', 'SCHEDULE_PAYMENT', 'SCHEDULED_PAYMENT'];
    if (mandatoryStatuses.includes(callLogData.call_status_code)) {
      if (!callLogData.followup_at) {
        newErrors.followup_at = "Field required";
      }
      if (!callLogData.remarks || !callLogData.remarks.trim()) {
        newErrors.remarks = "Field required";
      }
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setSaving(true);
    try {
      const pitchTypeCode = resolveCallTypeForLeadUpdate(selectedLead, mappingData.stage_to_pitch, {
        initialCallStatus: callLogData.call_status_code,
      });
      const allowedStatuses = getAvailableStatusCodes(
        pitchTypeCode,
        mappingData.pitch_to_statuses,
        { entityType, leadStage: selectedLead.stage },
      );
      if (!allowedStatuses.includes(callLogData.call_status_code)) {
        alert(`Call status is not allowed for pitch type ${pitchTypeCode.replace(/_/g, ' ')} on this stage.`);
        return;
      }

      let followupIso = null;
      if (callLogData.followup_at) {
        const followupDate = new Date(callLogData.followup_at);
        if (Number.isNaN(followupDate.getTime())) {
          setErrors({ followup_at: 'Invalid date/time' });
          return;
        }
        followupIso = followupDate.toISOString();
      }

      const shouldComplete = resolveCompleteOpenFollowupOnCallUpdate(selectedLead, {
        fromFollowupContext: completeFollowupOnSave,
        followupAt: followupIso,
      });

      const payload = {
        call_type_code: pitchTypeCode,
        call_status_code: callLogData.call_status_code,
        followup_at: followupIso,
        remarks: callLogData.remarks?.trim() || null,
        complete_open_followup: shouldComplete,
      };
      await submitCrmLeadCallUpdate({
        entityType,
        leadId: selectedLead.id,
        callPayload: payload,
        completeFollowup: shouldComplete,
      });
      const updatedLeadId = selectedLead.id;
      closeCallActionDrawer();
      if (viewMode === 'history' && historyLead?.id === updatedLeadId) {
        setHistoryLead((prev) => (
          prev
            ? {
                ...prev,
                follow_up_status: shouldComplete
                  ? (followupIso ? 'PENDING' : 'COMPLETED')
                  : prev.follow_up_status,
              }
            : prev
        ));
        setTimeout(() => {
          fetchHistory(historyLead.id, historyCurrentPage);
          fetchLeads();
        }, 600);
      } else {
        setTimeout(() => {
          fetchLeads();
        }, 600);
      }
    } catch (err) {
      console.error("Failed to log call:", err);
      if (err.fields && Object.keys(err.fields).length > 0) {
        setErrors(err.fields);
        return;
      }
      alert(extractCrmApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };


  return (
    <>
      {showCreateModal && (
        <CreateLeadModal
          entityType={entityType}
          currentRole={currentRole}
          currentEmpId={currentEmpId}
          onClose={() => setShowCreateModal(false)}
          onCreated={() => fetchLeads()}
        />
      )}
      <div className="leads-module-container">
        {viewMode === 'list' ? (
          <>
            {(hasActiveLeadFilters(appliedFilters) || !hideFilters) && (
              <CrmLeadFiltersToolbar
                appliedFilters={appliedFilters}
                onOpenFilters={openFilterDrawer}
                onResetFilters={handleResetFilters}
                showFiltersButton={!hideFilters}
                pushFeedback={pushFeedback}
                onCreateLead={canCreateLead ? () => setShowCreateModal(true) : null}
              />
            )}

            <div className="gst-table-wrapper">
              <div className="gst-table-container">
                <CrmLeadsListTable
                  leads={leads}
                  loading={loading}
                  isIncomeTaxCrm={isIncomeTaxCrm}
                  isGstCrm={isGstCrm}
                  isLeadPushed={isLeadPushed}
                  onPush={handlePush}
                  pushingLeadId={pushingLeadId}
                  onViewLead={handleViewLead}
                  onEditLead={handleEditLead}
                  onHistoryLead={handleViewHistory}
                />
              </div>

              <Pagination
                currentPage={currentPage}
                onPageChange={setCurrentPage}
                hasMore={currentPage < totalPages}
                loading={loading}
              />
            </div>
          </>
        ) : (
          <div className="history-view-container">
            <div className="crm-history-view-toolbar">
              <button
                type="button"
                className="btn-drawer-secondary"
                onClick={() => setViewMode('list')}
              >
                <ArrowRight size={18} style={{ transform: 'rotate(180deg)' }} />
                Back to Leads
              </button>
            </div>

            <div className="gst-table-wrapper">
              <CrmLeadHistorySummary
                lead={historyLead}
                onCallStatus={() => handleRowClick(historyLead, { completeFollowup: true })}
                onPaymentRecorded={async () => {
                  if (!historyLead?.id) return;
                  const et = String(historyLead.entity_type || entityType || 'GST_REGISTRATION').toUpperCase();
                  const fresh = await fetchLeadForDeepLink(et, historyLead.id, null);
                  if (fresh) setHistoryLead(fresh);
                  fetchHistory(historyLead.id, historyCurrentPage);
                  fetchLeads();
                }}
              />

              {detailsLoading && (
                <div className="crm-history-profile-loading">
                  <Loader2 className="spin" size={20} />
                  <span>Loading linked profile…</span>
                </div>
              )}

              {!detailsLoading && registrationData ? (
                <div className="comprehensive-details-view">
                  {/* 1. REGISTRATION SECTION */}
                  <div className="details-section">
                    <div className="details-header">
                      <Briefcase size={20} />
                      <h4>{entityType === 'INCOME_TAX' ? 'ITR Filings' : 'Registration Details'}</h4>
                    </div>
                    <div className="details-grid">
                      <div className="snapshot-item">
                        <label>Business Name</label>
                        <div className="value accent">{registrationData.registration?.business_name || 'N/A'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Username</label>
                        <div className="value accent">{registrationData.registration?.username || 'NOT SET'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>GSTIN</label>
                        <div className="value accent">{registrationData.registration?.gstin || 'PENDING'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>PAN</label>
                        <div className="value accent">{registrationData.registration?.pan || 'N/A'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Registration Type</label>
                        <div className="value">{registrationData.registration?.registration_type || 'N/A'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Ownership Category</label>
                        <div className="value">{registrationData.registration?.ownership_category || 'N/A'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Registration Status</label>
                        <div className="value">
                          <span className={`status-pill ${registrationData.registration?.registration_status === 'APPROVED' ? 'active' : 'pending'}`}>
                            {registrationData.registration?.registration_status || 'DRAFT'}
                          </span>
                        </div>
                      </div>
                      <div className="snapshot-item">
                        <label>Filing Needed?</label>
                        <div className="value">{registrationData.registration?.is_filing_needed ? 'YES' : 'NO'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>RCM Applicable?</label>
                        <div className="value">{registrationData.registration?.is_rcm_applicable ? 'YES' : 'NO'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Filing Preference</label>
                        <div className="value">{registrationData.registration?.filing_preference || 'NOT SET'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>State</label>
                        <div className="value">
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Globe size={14} opacity={0.5} />
                            {registrationData.registration?.state || 'N/A'}
                          </div>
                        </div>
                      </div>
                      <div className="snapshot-item">
                        <label>Mobile Number</label>
                        <div className="value">
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Phone size={14} opacity={0.5} />
                            {registrationData.registration?.mobile || 'N/A'}
                          </div>
                        </div>
                      </div>
                      <div className="snapshot-item">
                        <label>Primary Email</label>
                        <div className="value" style={{ fontSize: '12px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Mail size={14} opacity={0.5} />
                            {registrationData.registration?.email || 'N/A'}
                          </div>
                        </div>
                      </div>
                      <div className="snapshot-item">
                        <label>Secondary Email</label>
                        <div className="value" style={{ fontSize: '12px' }}>{registrationData.registration?.secondary_email || 'N/A'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Relationship Manager</label>
                        <div className="value accent">{registrationData.registration?.rm_name || 'Unassigned'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Created By</label>
                        <div className="value">{registrationData.registration?.created_by_name || 'System'}</div>
                      </div>
                      <div className="snapshot-item">
                        <label>Created At</label>
                        <div className="value" style={{ fontSize: '11px' }}>{formatDateTime(registrationData.registration?.created_at)}</div>
                      </div>
                    </div>
                  </div>

                  {/* 2. PEOPLE SECTION (GST ONLY) */}
                  {entityType === 'GST_REGISTRATION' && (
                    <div className="details-section">
                      <div className="details-header">
                        <Users size={20} />
                        <h4>Associated People</h4>
                      </div>
                      {registrationData.persons?.length > 0 ? (
                        <div className="person-cards-grid">
                          {registrationData.persons.map((person, idx) => (
                            <div key={person.person_id || idx} className="person-card">
                              <div className="person-card-header">
                                <span className="person-name">{person.full_name}</span>
                                {person.is_primary_customer && <span className="primary-badge">Primary</span>}
                              </div>
                              <div className="snapshot-item">
                                <label>Designation</label>
                                <div className="value" style={{ color: 'var(--text-muted)' }}>{person.designation}</div>
                              </div>
                              <div className="person-details-row">
                                <div className="snapshot-item">
                                  <label>PAN</label>
                                  <div className="value" style={{ fontSize: '12px' }}>{person.pan || '-'}</div>
                                </div>
                                <div className="snapshot-item">
                                  <label>Aadhaar</label>
                                  <div className="value" style={{ fontSize: '12px' }}>{person.aadhaar || '-'}</div>
                                </div>
                              </div>
                              <div className="person-details-row">
                                <div className="snapshot-item">
                                  <label>Mobile</label>
                                  <div className="value" style={{ fontSize: '12px' }}>{person.mobile || '-'}</div>
                                </div>
                                <div className="snapshot-item">
                                  <label>Email</label>
                                  <div className="value" style={{ fontSize: '10px', wordBreak: 'break-all' }}>{person.email || '-'}</div>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="snapshot-empty-state" style={{ padding: '20px' }}>
                          <span>No associated people records found.</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* 3. DOCUMENTS SECTION (INCOME TAX ONLY) */}
                  {entityType === 'INCOME_TAX' && (
                    <div className="details-section">
                      <div className="details-header">
                        <FileText size={20} />
                        <h4>Documents Vault</h4>
                      </div>
                      {registrationData.documents?.length > 0 ? (
                        <div className="document-grid">
                          {registrationData.documents.map((doc, idx) => (
                            <a
                              key={doc.document_id || idx}
                              href={doc.document_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="document-card"
                            >
                              <div className="doc-info">
                                <div className="doc-icon">
                                  <FileSignature size={18} />
                                </div>
                                <div>
                                  <div className="doc-type">{doc.document_type}</div>
                                  {doc.verified && (
                                    <div className="doc-verified">
                                      <CheckCircle2 size={10} /> Verified
                                    </div>
                                  )}
                                </div>
                              </div>
                              <span className="view-link">View</span>
                            </a>
                          ))}
                        </div>
                      ) : (
                        <div className="snapshot-empty-state" style={{ padding: '20px' }}>
                          <span>No documents uploaded for this lead.</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* 4. CUSTOMER SERVICES SECTION (HIDDEN) */}

                </div>
              ) : null}

              <div className="history-section-divider">
                <div className="line"></div>
                <span>Activity History</span>
                <div className="line"></div>
              </div>

              <div className="gst-table-container history-mode">
                <table className="gst-registrations-table bordered">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Activity Type</th>
                      <th>Performed At</th>
                      <th>Performed By</th>
                      <th className="status-column">Stage Transition</th>
                      <th className="status-column">Call Details</th>
                      <th>Remarks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyLoading ? (
                      <tr><td colSpan="7" className="text-center">Loading history data...</td></tr>
                    ) : historyActivities.length === 0 ? (
                      <tr><td colSpan="7" className="text-center">No activity history found.</td></tr>
                    ) : historyActivities.map((act, idx) => (
                      <tr key={act.id || idx} className="gst-reg-table-row">
                        <td>{act.id}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {act.activity_type === 'CALL' ? <PhoneCall size={14} color="var(--text-primary)" /> : <Activity size={14} color="var(--info)" />}
                            <span style={{ fontWeight: 500 }}>{act.activity_type?.replace(/_/g, ' ')}</span>
                          </div>
                        </td>
                        <td>{formatDateTime(act.performed_at)}</td>
                        <td>{act.performed_by || 'System'}</td>
                        <td>
                          {(act.old_stage || act.new_stage) && act.old_stage !== act.new_stage ? (
                            <div className="stage-transition" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span style={{ color: 'var(--text-primary)' }}>{act.old_stage || 'START'}</span>
                              <ArrowRight size={12} />
                              <span>{act.new_stage}</span>
                            </div>
                          ) : '-'}
                        </td>
                        <td>
                          {act.activity_type === 'CALL' ? (
                            <div style={{ display: 'flex', gap: '4px' }}>
                              <span style={{ fontSize: '10px', background: 'rgba(var(--fg-rgb),0.05)', color: 'var(--text-primary)', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(var(--fg-rgb),0.1)' }}>{act.call_type_code?.replace(/_/g, ' ')}</span>
                              <span style={{ fontSize: '10px', background: 'rgba(var(--fg-rgb),0.1)', color: 'var(--text-primary)', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(var(--fg-rgb),0.2)' }}>{act.call_status_code?.replace(/_/g, ' ')}</span>
                            </div>
                          ) : '-'}
                        </td>
                        <td style={{ maxWidth: '300px', whiteSpace: 'normal' }}>
                          {act.remarks || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Pagination
                currentPage={historyCurrentPage}
                onPageChange={setHistoryCurrentPage}
                hasMore={historyCurrentPage < historyTotalPages}
                loading={historyLoading}
              />
            </div>
          </div>
        )}
      </div>
      <CrmLeadFilterDrawer
        open={isFilterOpen}
        filterInputs={filterInputs}
        setFilterInputs={setFilterInputs}
        stages={stages}
        entityType={entityType}
        onClose={() => setIsFilterOpen(false)}
        onReset={handleResetFilters}
        onApply={handleApplyFilters}
      />

      <CrmLeadCallActionDrawer
        lead={selectedLead}
        entityType={entityType}
        callLogData={callLogData}
        onFieldChange={(field, value) =>
          setCallLogData((prev) => ({ ...prev, [field]: value }))
        }
        availableStatuses={availableStatuses}
        errors={errors}
        onClearError={(field) =>
          setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev))
        }
        saving={saving}
        onClose={closeCallActionDrawer}
        onSubmit={handleLogCall}
      />


      <CrmLeadViewDrawer lead={viewLead} entityType={entityType} onClose={() => setViewLead(null)} />
    </>
  );
};

export default Leads;
