export function formatEntityLabel(entityTypeValue) {
  const normalized = (entityTypeValue || '').trim().toUpperCase();
  if (normalized === 'INCOME_TAX') return 'Income Tax';
  if (normalized === 'GST_REGISTRATION') return 'GST Registration';
  return normalized.replace(/_/g, ' ') || '—';
}

export function formatLogAssignedRoles(log) {
  if (log.assigned_roles) return log.assigned_roles;
  const roles = log.summary?.roles || {};
  const parts = ['RM', 'OP'].filter((r) => Number(roles[r]?.total_assigned || 0) > 0);
  if (parts.length) return parts.join(' + ');
  return log.summary?.assignment_role || '—';
}
