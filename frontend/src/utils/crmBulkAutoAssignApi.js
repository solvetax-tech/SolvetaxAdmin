import api from './api';
import { scrubBulkAssignFilters } from './crmBulkAssignFilters';

function parsePerEmployeeLimit(value) {
  if (value === '' || value == null) return null;
  const parsed = parseInt(String(value).trim(), 10);
  return Number.isFinite(parsed) && parsed >= 1 ? parsed : null;
}

/** Build PUT /bulk-assign/schedulers body from Bulk Assign UI state. */
export function buildCrmBulkAutoAssignPayload({
  schedulerId = null,
  schedulerName = 'Scheduler',
  entityType,
  filters,
  activeFilterKeys,
  enabled,
  assignmentRoles,
  selectedRmUsernames,
  selectedOpUsernames,
  perEmployeeLimits,
  intervalMinutes = 5,
}) {
  const scrubbed = scrubBulkAssignFilters(filters, activeFilterKeys);
  const effectiveEntityTypes =
    activeFilterKeys?.includes('entity_types') && scrubbed.entity_types?.length > 0
      ? scrubbed.entity_types
      : [entityType];

  const payload = {
    name: (schedulerName || 'Scheduler').trim(),
    enabled: Boolean(enabled),
    entity_type: entityType,
    filters: {
      stages: scrubbed.stages || [],
      rm_ids: (scrubbed.rm_ids || []).map((id) => Number(id)),
      op_ids: (scrubbed.op_ids || []).map((id) => Number(id)),
      lead_types: scrubbed.lead_types || [],
      ays: scrubbed.ays || [],
      tags: scrubbed.tags || [],
      lead_sources: scrubbed.lead_sources || [],
      entity_types: effectiveEntityTypes,
      follow_up_statuses: scrubbed.follow_up_statuses || [],
      null_fields: scrubbed.null_fields || [],
      not_null_fields: scrubbed.not_null_fields || [],
      is_active: scrubbed.is_active,
      match_mode: scrubbed.match_mode || 'AND',
      filter_mode: scrubbed.filter_mode || 'IN',
      limit: scrubbed.limit || 500,
    },
    assign_rm: Boolean(assignmentRoles?.RM),
    assign_op: Boolean(assignmentRoles?.OP),
    selected_rm_usernames: selectedRmUsernames || [],
    selected_op_usernames: selectedOpUsernames || [],
    per_employee_limit_rm: parsePerEmployeeLimit(perEmployeeLimits?.RM),
    per_employee_limit_op: parsePerEmployeeLimit(perEmployeeLimits?.OP),
    assign_unassigned_only: false,
    interval_minutes: Math.max(1, parseInt(String(intervalMinutes), 10) || 5),
  };
  if (schedulerId) {
    payload.id = schedulerId;
  }
  return payload;
}

export async function fetchBulkAssignSchedulers(entityType) {
  const params = {};
  if (entityType) params.entity_type = entityType;
  const res = await api.get('/api/v1/crm/leads/bulk-assign/schedulers', { params });
  return res.data;
}

/** All schedulers across GST + Income Tax (omit entity filter). */
export async function fetchAllBulkAssignSchedulers() {
  return fetchBulkAssignSchedulers(null);
}

export async function toggleBulkAssignSchedulerEnabled(schedulerId, enabled) {
  const res = await api.patch(
    `/api/v1/crm/leads/bulk-assign/schedulers/${schedulerId}/enabled`,
    { enabled: Boolean(enabled) },
  );
  return res.data;
}

export async function fetchBulkAssignScheduler(schedulerId) {
  const res = await api.get(`/api/v1/crm/leads/bulk-assign/schedulers/${schedulerId}`);
  return res.data;
}

export async function saveBulkAssignScheduler(payload) {
  const res = await api.put('/api/v1/crm/leads/bulk-assign/schedulers', payload);
  return res.data;
}

export async function deleteBulkAssignScheduler(schedulerId) {
  const res = await api.delete(`/api/v1/crm/leads/bulk-assign/schedulers/${schedulerId}`);
  return res.data;
}

export async function runBulkAssignScheduler(schedulerId) {
  const res = await api.post(`/api/v1/crm/leads/bulk-assign/schedulers/${schedulerId}/run`);
  return res.data;
}

export async function fetchBulkAssignLogs({
  entityType,
  runType = null,
  schedulerId = null,
  limit = 30,
  offset = 0,
} = {}) {
  const params = { limit, offset };
  if (entityType) params.entity_type = entityType;
  if (runType) params.run_type = runType;
  if (schedulerId) params.scheduler_id = schedulerId;
  const res = await api.get('/api/v1/crm/leads/bulk-assign/logs', { params });
  return res.data;
}

/** @deprecated Use fetchBulkAssignSchedulers */
export const fetchCrmBulkAutoAssignConfig = fetchBulkAssignSchedulers;

/** @deprecated Use saveBulkAssignScheduler */
export const saveCrmBulkAutoAssignConfig = saveBulkAssignScheduler;

/** @deprecated Use runBulkAssignScheduler */
export async function runCrmBulkAutoAssignNow(entityType, schedulerId) {
  const res = await api.post('/api/v1/crm/leads/bulk-assign/auto/run', null, {
    params: { entity_type: entityType, ...(schedulerId ? { scheduler_id: schedulerId } : {}) },
  });
  return res.data;
}
