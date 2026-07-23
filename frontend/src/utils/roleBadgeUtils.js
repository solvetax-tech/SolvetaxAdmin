/** Map backend role codes to table badge class (role-badge-v4.*). */
export function getRoleBadgeClass(role) {
    const r = (role || '').toUpperCase();
    if (r === 'ADMIN') return 'admin';
    if (r === 'HR') return 'hr';
    if (r === 'SR_MANAGER' || r === 'SENIOR_MANAGER') return 'sr-manager';
    if (r === 'SALES_MANAGER') return 'manager';
    if (r === 'OP_MANAGER') return 'op-manager';
    if (r === 'MANAGER') return 'manager';
    if (r === 'TL' || r === 'TEAM_LEAD') return 'tl';
    if (r === 'RM') return 'rm';
    if (r === 'OP') return 'op';
    if (r.includes('SALES')) return 'sales';
    if (r.includes('OP') || r.includes('OPERATION')) return 'op';
    if (r.includes('ASSOCIATE')) return 'associate';
    if (r.includes('ACCOUNTANT')) return 'accountant';
    return 'default';
}

/** Map backend role codes to header/dropdown CSS class suffix. */
export function getRoleCssClass(role) {
    const r = (role || '').toUpperCase();
    if (r === 'ADMIN') return 'admin';
    if (r === 'HR') return 'hr';
    if (r === 'SR_MANAGER' || r === 'SENIOR_MANAGER') return 'sr-manager';
    if (r === 'SALES_MANAGER') return 'manager';
    if (r === 'OP_MANAGER') return 'op';
    if (r === 'MANAGER') return 'manager';
    if (r === 'TL' || r === 'TEAM_LEAD') return 'tl';
    if (r === 'RM') return 'rm';
    if (r === 'OP') return 'op';
    if (r.includes('SALES')) return 'sales';
    if (r.includes('OP') || r.includes('OPERATION')) return 'op';
    return 'employee';
}

// --------------------------------------------------------------------------- //
// CO-ADMIN — a display-only distinction. A few ADMIN accounts are surfaced in
// the UI as "CO-ADMIN" with their own badge colour; their backend role stays
// ADMIN, so permissions are unchanged. The override is keyed on account email.
// --------------------------------------------------------------------------- //

const CO_ADMIN_EMAILS = new Set(['samuelinti9@gmail.com']);

/** True when a record's ADMIN role should render as CO-ADMIN. Pass an object with { role, email }. */
export function isCoAdmin(record) {
    if (!record) return false;
    const role = String(record.role || '').toUpperCase();
    const email = String(record.email || '').trim().toLowerCase();
    return role === 'ADMIN' && CO_ADMIN_EMAILS.has(email);
}

/** Role text to display, applying the CO-ADMIN override. Falls back to the raw role. */
export function getRoleDisplayLabel(record) {
    if (isCoAdmin(record)) return 'CO-ADMIN';
    return record?.role || '';
}

/** Header/dropdown CSS class, honouring the CO-ADMIN override. Pass a record { role, email }. */
export function getRoleCssClassFor(record) {
    if (isCoAdmin(record)) return 'co-admin';
    return getRoleCssClass(record?.role);
}
