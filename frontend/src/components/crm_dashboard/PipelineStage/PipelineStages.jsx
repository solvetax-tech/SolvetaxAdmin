import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { Search, Filter, X, PhoneCall, User, Activity, Clock, History, MessageSquare, ArrowRight, Loader2, Users, FileSpreadsheet, AlertCircle, Info, FileText, ShieldCheck, ClipboardCheck, Briefcase, Globe, Mail, Phone, FileSignature, CheckCircle2 } from 'lucide-react';
import './PipelineStages.css';
import '../leads/Leads.css';
import api from '../../../utils/api';
import { unwrapListPayload } from '../../../utils/apiResponse';
import { useCrmLeadPush } from '../useCrmLeadPush';
import CrmLeadsListTable from '../CrmLeadsListTable';
import CrmLeadViewDrawer from '../CrmLeadViewDrawer';
import CrmLeadCallActionDrawer from '../CrmLeadCallActionDrawer';
import '../crmLeadsBoard.css';
import CrmLeadFilterDrawer from '../CrmLeadFilterDrawer';
import CrmLeadFiltersToolbar from '../CrmLeadFiltersToolbar';
import CrmLeadHistorySummary from '../CrmLeadHistorySummary';
import Pagination from '../../common/Pagination';
import { useListLoading } from '../../../hooks/useListLoading';
import {
    buildEmptyLeadFilters,
    buildCrmLeadFilterApiParams,
    serializeCrmLeadFilterParams,
} from '../crmLeadFilters';
import { getAvailableStatusCodes } from '../crmLeadPitchUtils';
import {
    submitCrmLeadCallUpdate,
    resolveCompleteOpenFollowupOnCallUpdate,
    extractCrmApiErrorMessage,
} from '../../../utils/crmLeadApi';

const PipelineStages = ({ entityType = 'GST_REGISTRATION', stage = null, initialFilters = null }) => {
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalLeads, setTotalLeads] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [sort, setSort] = useState({ by: 'id', dir: 'desc' });
  const rowsPerPage = 50;

  // Drawer States
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [selectedLead, setSelectedLead] = useState(null);
  const [activeActionTab, setActiveActionTab] = useState('call');
  const [viewMode, setViewMode] = useState('list'); // 'list' or 'history'
  const [historyActivities, setHistoryActivities] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLead, setHistoryLead] = useState(null);
  const [viewLead, setViewLead] = useState(null);
  const [historyCurrentPage, setHistoryCurrentPage] = useState(1);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [registrationData, setRegistrationData] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState(null);

  const [appliedFilters, setAppliedFilters] = useState(() => buildEmptyLeadFilters(initialFilters));
  const [filterInputs, setFilterInputs] = useState(() => buildEmptyLeadFilters(initialFilters));
  const { wrapFetch } = useListLoading();

  const [errors, setErrors] = useState({});
  const [completeFollowupOnSave, setCompleteFollowupOnSave] = useState(false);

  // UI Mappings
  const [mappingData, setMappingData] = useState({ stage_to_pitch: [], pitch_to_statuses: {} });
  const [stages, setStages] = useState([]); // Fetch stages for multi-select

  // Edit Form State
  const [editFormData, setEditFormData] = useState({
    rm_id: '',
    op_id: '',
    remarks: ''
  });

  // Call Log Form State
  const [callLogData, setCallLogData] = useState({
    call_type_code: '',
    call_status_code: '',
    followup_at: '',
    remarks: ''
  });

  const [saving, setSaving] = useState(false);

  const {
    isIncomeTaxCrm,
    isGstCrm,
    isLeadPushed,
    handlePush,
    pushingLeadId,
    pushFeedback,
  } = useCrmLeadPush(entityType, setLeads);

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
    fetchMappings();
  }, [entityType]);

  useEffect(() => {
    if (initialFilters) {
      setAppliedFilters((prev) => ({ ...prev, ...initialFilters }));
      setFilterInputs((prev) => ({ ...prev, ...initialFilters }));
      setCurrentPage(1);
    }
  }, [initialFilters]);

  const fetchLeads = useCallback(async () => {
    await wrapFetch(setLoading, async () => {
      try {
      const params = buildCrmLeadFilterApiParams(appliedFilters, {
        limit: rowsPerPage,
        offset: (currentPage - 1) * rowsPerPage,
        entity_type: (entityType || '').trim().toUpperCase(),
        stage: appliedFilters.stages.length === 0 ? (stage || undefined) : undefined,
        is_active: true,
      });
      params.sort_by = sort.by;
      params.sort_dir = sort.dir;

      const apiBase = '/api/v1/crm/leads';
      const response = await api.get(`${apiBase}/filter?${serializeCrmLeadFilterParams(params)}`);
      const { items, total: listTotal } = unwrapListPayload(response);
      const total = listTotal || 0;

      setLeads(items);
      setTotalLeads(total);
    } catch (error) {
      console.error("Error fetching leads:", error);
    }
    });
  }, [currentPage, appliedFilters, rowsPerPage, stage, entityType, sort, wrapFetch]);

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

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  useEffect(() => {
    fetchMappings();
  }, [entityType]);

  const handleRowClick = (lead, options = {}) => {
    setSelectedLead(lead);
    setCompleteFollowupOnSave(Boolean(options.completeFollowup));

    // Auto-select first available pitch type (Robust case-insensitive matching + direct property check)
    const currentStage = (lead.stage || '').trim().toUpperCase();
    const mappingMatch = mappingData.stage_to_pitch.find(m =>
      (m.stage || '').trim().toUpperCase() === currentStage
    );

    // Check direct properties first, then fallback to mapping, then fallback to FIRST_PITCH_CALL if in early stages
    let firstPitch = lead.pitch_type || lead.pitch_type_code || mappingMatch?.pitch_type_code || '';
    
    // Safety Fallback: If pitch is still blank, default to FIRST_PITCH_CALL for initial stages
    if (!firstPitch) {
      if (['NEW', 'PROSPECT', 'FIRST_PITCH', 'INTERESTED'].includes(currentStage)) {
        firstPitch = 'FIRST_PITCH_CALL';
      } else if (['CONNECTED_AND_SCHEDULED', 'SEND_DOCS'].includes(currentStage)) {
        firstPitch = 'FIRST_PITCH_CALL';
      } else {
        // Default to first available mapping if possible, otherwise first pitch
        firstPitch = mappingData.stage_to_pitch[0]?.pitch_type_code || 'FIRST_PITCH_CALL';
      }
    }

    setEditFormData({
      rm_id: lead.rm_id || '',
      op_id: lead.op_id || '',
      remarks: lead.remarks || ''
    });
    setCallLogData({
      call_type_code: firstPitch,
      call_status_code: '',
      followup_at: '',
      remarks: ''
    });
    setActiveActionTab('call');
  };

  const fetchHistory = useCallback(async (leadId, page = 1) => {
    setHistoryLoading(true);
    try {
      const params = {
        limit: rowsPerPage,
        offset: (page - 1) * rowsPerPage,
        entity_type: (entityType || '').trim().toUpperCase()
      };
      const apiBase = '/api/v1/crm/leads';
      const response = await api.get(`${apiBase}/${leadId}/activities`, { params });
      const { items, total } = unwrapListPayload(response);
      setHistoryActivities(items);
      setHistoryTotal(total ?? 0);
    } catch (err) {
      console.error("Failed to fetch history for pipeline:", err);
    } finally {
      setHistoryLoading(false);
    }
  }, [entityType, rowsPerPage]);

  const handleViewLead = (e, lead) => {
    if (e) e.stopPropagation();
    setViewLead(lead);
  };

  const handleEditLead = (e, lead) => {
    if (e) e.stopPropagation();
    handleRowClick(lead);
    setActiveActionTab('edit');
  };

  const handleViewHistory = async (e, lead) => {
    e.stopPropagation();
    setHistoryLead(lead);
    setViewMode('history');
    setHistoryCurrentPage(1);

    // Reset and start fetching details
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

        // Fetch full details from entity-specific endpoint (entity_type is encoded in path)
        const res = await api.get(detailUrl);
        if (res.data) {
          // Normalize data structure for the UI
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
      setSelectedLead(null);
      fetchLeads();
    } catch (err) {
      console.error("Failed to save lead info:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleLogCall = async () => {
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
      const followupIso = callLogData.followup_at
        ? new Date(callLogData.followup_at).toISOString()
        : null;
      const shouldComplete = resolveCompleteOpenFollowupOnCallUpdate(selectedLead, {
        fromFollowupContext: completeFollowupOnSave,
        followupAt: followupIso,
      });
      await submitCrmLeadCallUpdate({
        entityType,
        leadId: selectedLead.id,
        callPayload: {
          call_type_code: callLogData.call_type_code,
          call_status_code: callLogData.call_status_code,
          followup_at: followupIso,
          remarks: callLogData.remarks?.trim() || null,
        },
        completeFollowup: shouldComplete,
      });
      const updatedLeadId = selectedLead.id;
      setSelectedLead(null);
      if (viewMode === 'history' && historyLead?.id === updatedLeadId) {
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
      alert(extractCrmApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  // Derive available pitch types for the current lead's stage
  const availablePitchTypes = useMemo(() => {
    if (!selectedLead) return [];
    return mappingData.stage_to_pitch
      .filter(m => m.stage === selectedLead.stage)
      .map(m => m.pitch_type_code);
  }, [selectedLead, mappingData]);

  // Derive available call statuses for the selected pitch type
  const availableStatuses = useMemo(() => {
    if (!callLogData.call_type_code) return [];
    return getAvailableStatusCodes(callLogData.call_type_code, mappingData.pitch_to_statuses, {
      entityType,
      leadStage: selectedLead?.stage,
    });
  }, [callLogData.call_type_code, mappingData, entityType, selectedLead?.stage]);

  const totalPages = Math.ceil(totalLeads / rowsPerPage);

  const formatDateTime = (dateStr) => {
    if (!dateStr) return '-';
    // Check if it's a valid date string or ISO string
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;

    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');

    return `${d}-${m}-${y} ${hh}:${mm}`;
  };

  const historyTotalPages = Math.ceil(historyTotal / rowsPerPage);

  return (
    <>
      <div className="pipeline-module-container">
        {viewMode === 'list' ? (
          <>
            <CrmLeadFiltersToolbar
              appliedFilters={appliedFilters}
              onOpenFilters={() => setIsFilterOpen(true)}
              onResetFilters={handleResetFilters}
              pushFeedback={pushFeedback}
              sortBy={sort.by}
              sortDir={sort.dir}
              onSortChange={(by, dir) => { setSort({ by, dir }); setCurrentPage(1); }}
              isIncomeTaxCrm={isIncomeTaxCrm}
              contextPill={
                appliedFilters.stages.length > 0 ? (
                  <span className="filter-pill">
                    Stages: {appliedFilters.stages.length} selected
                  </span>
                ) : (
                  stage ? <span className="filter-pill">Stage: {stage}</span> : null
                )
              }
            />

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
                  emptyMessage="No leads found in this stage."
                  loadingMessage="Loading pipeline data..."
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
            <div className="tab-header-v2" style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '16px' }}>
              <button className="btn-drawer-secondary" onClick={() => setViewMode('list')} style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ArrowRight size={18} style={{ transform: 'rotate(180deg)' }} /> Back to Pipeline
              </button>
            </div>

            <div className="gst-table-wrapper">
              <CrmLeadHistorySummary
                lead={historyLead}
                onCallStatus={() => handleRowClick(historyLead, { completeFollowup: true })}
                onPaymentRecorded={async () => {
                  if (!historyLead?.id) return;
                  const apiBase = entityType === 'INCOME_TAX' ? '/api/v1/crm/itr/leads' : '/api/v1/crm/leads';
                  try {
                    const res = await api.get(`${apiBase}/filter?id=${historyLead.id}&limit=1&entity_type=${encodeURIComponent(entityType)}`);
                    const fresh = res.data?.items?.[0];
                    if (fresh) setHistoryLead(fresh);
                  } catch (err) { console.warn('Refresh lead after payment failed:', err); }
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
                <span>Performance Records</span>
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
                      <tr><td colSpan="7" className="text-center">Fetching records...</td></tr>
                    ) : historyActivities.length === 0 ? (
                      <tr><td colSpan="7" className="text-center">No performance records found.</td></tr>
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
                        <td>{act.performed_by ? `Employee ${act.performed_by}` : 'System'}</td>
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
        showPipelineStages={false}
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
        onClose={() => setSelectedLead(null)}
        onSubmit={handleLogCall}
      />

      <CrmLeadViewDrawer lead={viewLead} entityType={entityType} onClose={() => setViewLead(null)} />
    </>
  );
};

export default PipelineStages;
