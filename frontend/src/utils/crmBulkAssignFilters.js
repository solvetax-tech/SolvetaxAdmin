/** Shared bulk-assign filter shape for Manual + Auto (must match GET /bulk-assign/candidates). */

export const DEFAULT_BULK_FILTERS = {
  stages: [],
  rm_ids: [],
  op_ids: [],
  lead_types: [],
  ays: [],
  tags: [],
  lead_sources: [],
  entity_types: [],
  follow_up_statuses: [],
  null_fields: [],
  not_null_fields: [],
  is_active: null,
  match_mode: 'AND',
  filter_mode: 'IN',
  limit: 500,
  offset: 0,
};

export const BULK_FILTER_FIELD_KEYS = [
  'stages',
  'rm_ids',
  'op_ids',
  'lead_types',
  'ays',
  'tags',
  'lead_sources',
  'entity_types',
  'follow_up_statuses',
  'null_fields',
  'not_null_fields',
  'is_active',
];

export const DEFAULT_MANUAL_ACTIVE_FILTER_KEYS = ['stages', 'rm_ids', 'tags'];
export const DEFAULT_AUTO_ACTIVE_FILTER_KEYS = ['stages'];

export function getDefaultManualActiveFilterKeys(entityType) {
  const isIncomeTaxCrm = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
  if (isIncomeTaxCrm) {
    return ['stages', 'rm_ids', 'lead_types', 'ays', 'tags'];
  }
  return [...DEFAULT_MANUAL_ACTIVE_FILTER_KEYS];
}

export function getDefaultAutoActiveFilterKeys(entityType) {
  const isIncomeTaxCrm = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
  if (isIncomeTaxCrm) {
    return ['stages', 'lead_types', 'ays'];
  }
  return [...DEFAULT_AUTO_ACTIVE_FILTER_KEYS];
}

export function filtersFromServer(f = {}) {
  return {
    ...DEFAULT_BULK_FILTERS,
    stages: f.stages || [],
    rm_ids: f.rm_ids || [],
    op_ids: f.op_ids || [],
    lead_types: f.lead_types || [],
    ays: f.ays || [],
    tags: f.tags || [],
    lead_sources: f.lead_sources || [],
    entity_types: f.entity_types || [],
    follow_up_statuses: f.follow_up_statuses || [],
    null_fields: f.null_fields || [],
    not_null_fields: f.not_null_fields || [],
    is_active: f.is_active ?? null,
    match_mode: f.match_mode || 'AND',
    filter_mode: f.filter_mode || 'IN',
    limit: f.limit || 500,
    offset: 0,
  };
}

/** Visible filter rows when loading a saved scheduler — only fields that have values. */
export function activeFilterKeysFromSavedFilters(filterObj) {
  const fromData = BULK_FILTER_FIELD_KEYS.filter((key) => {
    const value = filterObj[key];
    if (Array.isArray(value)) return value.length > 0;
    if (key === 'is_active') return value !== null && value !== undefined;
    return false;
  });
  return fromData.length > 0 ? fromData : [...DEFAULT_AUTO_ACTIVE_FILTER_KEYS];
}

/**
 * Only include filter fields the user has enabled in the UI.
 * Inactive keys are cleared so hidden scheduler state cannot affect the GET API.
 */
export function scrubBulkAssignFilters(filters, activeFilterKeys) {
  const active = new Set(activeFilterKeys || BULK_FILTER_FIELD_KEYS);
  const scrubbed = {
    match_mode: filters.match_mode || 'AND',
    filter_mode: filters.filter_mode || 'IN',
    limit: filters.limit || 500,
  };

  BULK_FILTER_FIELD_KEYS.forEach((key) => {
    if (!active.has(key)) {
      scrubbed[key] = Array.isArray(DEFAULT_BULK_FILTERS[key]) ? [] : DEFAULT_BULK_FILTERS[key];
      return;
    }
    const value = filters[key];
    if (value === undefined) {
      scrubbed[key] = DEFAULT_BULK_FILTERS[key];
    } else {
      scrubbed[key] = value;
    }
  });

  return scrubbed;
}

/** Build query string for GET /crm/leads/bulk-assign/candidates (Manual + Auto preview). */
export function buildBulkAssignCandidateParams(filters, entityType, activeFilterKeys) {
  const scrubbed = scrubBulkAssignFilters(filters, activeFilterKeys);
  const params = new URLSearchParams();

  if (scrubbed.match_mode) params.append('match_mode', scrubbed.match_mode);
  if (scrubbed.filter_mode) params.append('filter_mode', scrubbed.filter_mode);
  if (scrubbed.limit) params.append('limit', String(scrubbed.limit));

  const effectiveEntityTypes =
    activeFilterKeys?.includes('entity_types') && scrubbed.entity_types?.length > 0
      ? scrubbed.entity_types
      : [entityType];
  effectiveEntityTypes.forEach((v) => params.append('entity_types', v));

  BULK_FILTER_FIELD_KEYS.forEach((key) => {
    const value = scrubbed[key];
    if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) return;
    if (Array.isArray(value)) {
      value.forEach((v) => params.append(key, v));
    } else {
      params.append(key, String(value));
    }
  });

  return params;
}
