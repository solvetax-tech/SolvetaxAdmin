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

// --------------------------------------------------------------------------- //
// Platform RBAC — mirrors the backend's require_permission / assert_platform_
// permission. The JWT carries permissions.platform.{FEATURE} = [PERMS].
// Features: EMPLOYEE, USER_ACCESS, SETTINGS. Perms: READ, WRITE, DELETE, SPECIAL.
// WRITE implies READ (same rule as the backend).
// --------------------------------------------------------------------------- //

export function decodeSessionToken() {
  try {
    const token = localStorage.getItem('session_token');
    if (!token) return null;
    const part = token.split('.')[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(window.atob(b64));
  } catch {
    return null;
  }
}

/**
 * Role from the session JWT, for components too deep in the tree to be handed
 * `profileData` as a prop. Prefer `profileData?.role` where it is available.
 */
export function getSessionRole() {
  return String(decodeSessionToken()?.role || '').toUpperCase();
}

/**
 * True when the current user holds `permission` on `feature`, read from the JWT
 * permissions claim. If the token carries no permissions claim at all (legacy
 * token), falls back to the ADMIN role so an admin is never locked out.
 */
export function hasPermission(feature, permission) {
  const payload = decodeSessionToken();
  const platform = payload?.permissions?.platform;
  if (!platform || typeof platform !== 'object' || Object.keys(platform).length === 0) {
    return String(payload?.role || '').toUpperCase() === 'ADMIN';
  }
  const perms = Array.isArray(platform[feature]) ? platform[feature] : [];
  if (permission === 'READ' && perms.includes('WRITE')) return true;
  return perms.includes(permission);
}
