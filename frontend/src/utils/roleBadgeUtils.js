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
