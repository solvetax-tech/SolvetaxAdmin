/**
 * Role helpers for workspace / CRM visibility rules.
 *
 * ADMIN — all data
 * RM / OP — rows assigned to them
 * SALES_MANAGER — own + RM team (reporting tree on rm_id)
 * OP_MANAGER — own + OP team (reporting tree on op_id) + GST Filings dashboard
 */

export function normalizeRole(profileData) {
  return String(profileData?.role || '').toUpperCase();
}

export function isTrueAdmin(profileData) {
  return normalizeRole(profileData) === 'ADMIN';
}

export function isSalesManager(profileData) {
  return normalizeRole(profileData) === 'SALES_MANAGER';
}

export function isOpManager(profileData) {
  return normalizeRole(profileData) === 'OP_MANAGER';
}

export function isManager(profileData) {
  const role = normalizeRole(profileData);
  return role === 'SALES_MANAGER' || role === 'OP_MANAGER';
}

/** GST Filings monthly matrix on main dashboard — ADMIN + OP_MANAGER only. */
export function canSeeGstFilingsDashboard(profileData) {
  const role = normalizeRole(profileData);
  return role === 'ADMIN' || role === 'OP_MANAGER';
}
