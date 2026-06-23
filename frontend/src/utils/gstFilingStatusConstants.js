/** Canonical GST filing statuses (parent gst_filings.status). */
export const GST_FILING_STATUSES = [
  'DATA_PENDING',
  'DATA_RECEIVED',
  'IN_PREPARATION',
  'PENDING_OTP',
  'READY_TO_FILE',
  'FILED',
  'OVERDUE',
];

/** Return-detail column statuses (gst_filing_return_details.*_status). */
export const GST_RETURN_DETAIL_STATUSES = [
  ...GST_FILING_STATUSES,
  'NOT_FILED',
  'MISSED',
];

/** Manual UI/API updates only — MISSED & OVERDUE are system-set (due dates / scheduler). */
export const GST_RETURN_DETAIL_EDITABLE_STATUSES = [
  'DATA_PENDING',
  'DATA_RECEIVED',
  'IN_PREPARATION',
  'PENDING_OTP',
  'READY_TO_FILE',
  'FILED',
  'NOT_FILED',
];

export const GST_FILING_STATUS_LABELS = {
  DATA_PENDING: 'Data Pending',
  DATA_RECEIVED: 'Data Received',
  IN_PREPARATION: 'In Preparation',
  PENDING_OTP: 'Pending OTP',
  READY_TO_FILE: 'Ready to File',
  FILED: 'Filed',
  OVERDUE: 'Overdue',
  NOT_FILED: 'Not Filed',
  MISSED: 'Missed',
};

export const gstFilingStatusOptions = (includeAny = true) => {
  const items = GST_FILING_STATUSES.map((value) => ({
    value,
    label: GST_FILING_STATUS_LABELS[value] || value.replace(/_/g, ' '),
  }));
  if (includeAny) {
    return [{ value: '', label: 'Any Status' }, ...items];
  }
  return items;
};

export const gstReturnDetailStatusOptions = (includeEmpty = true) => {
  const items = GST_RETURN_DETAIL_STATUSES.map((value) => ({
    value,
    label: GST_FILING_STATUS_LABELS[value] || value.replace(/_/g, ' '),
  }));
  if (includeEmpty) {
    return [{ value: '', label: 'Select Status' }, ...items];
  }
  return items;
};

/** Status picker for manual updates (excludes MISSED & OVERDUE). */
export const gstReturnDetailEditableStatusOptions = (includeEmpty = true) => {
  const items = GST_RETURN_DETAIL_EDITABLE_STATUSES.map((value) => ({
    value,
    label: GST_FILING_STATUS_LABELS[value] || value.replace(/_/g, ' '),
  }));
  if (includeEmpty) {
    return [{ value: '', label: 'Select Status' }, ...items];
  }
  return items;
};

export const GST_RETURN_FORM_OPTIONS = [
  { value: 'GSTR1', label: 'GSTR-1' },
  { value: 'GSTR3B', label: 'GSTR-3B' },
  { value: 'CMP08', label: 'CMP-08' },
  { value: 'GSTR4', label: 'GSTR-4' },
  { value: 'GSTR9', label: 'GSTR-9' },
  { value: 'GSTR9C', label: 'GSTR-9C' },
];

export const createEmptyReturnStatusRule = () => ({ form: '', status: '' });

export const getActiveReturnStatusRules = (rules = []) =>
  (rules || []).filter((rule) => rule?.form && rule?.status);

export const appendReturnStatusRulesToParams = (params, matchMode, rules = []) => {
  const active = getActiveReturnStatusRules(rules);
  if (!active.length) return;
  params.append('return_status_match', (matchMode || 'AND').toUpperCase());
  active.forEach((rule) => {
    params.append('return_status_rules', `${rule.form}:${rule.status}`);
  });
};

export const formatReturnStatusRule = (rule) => {
  const formLabel = GST_RETURN_FORM_OPTIONS.find((item) => item.value === rule.form)?.label || rule.form;
  const statusLabel = GST_FILING_STATUS_LABELS[rule.status] || rule.status;
  return `${formLabel} = ${statusLabel}`;
};

export const formatReturnStatusRulesSummary = (matchMode, rules = []) => {
  const active = getActiveReturnStatusRules(rules);
  if (!active.length) return null;
  const joiner = (matchMode || 'AND').toUpperCase() === 'OR' ? ' OR ' : ' AND ';
  return active.map(formatReturnStatusRule).join(joiner);
};

export const GST_RETURN_FORM_STATUS_FIELDS = {
  GSTR1: 'gstr1_status',
  GSTR3B: 'gstr3b_status',
  CMP08: 'cmp08_status',
  GSTR4: 'gstr4_status',
  GSTR9: 'gstr9_status',
  GSTR9C: 'gstr9c_status',
};

export const GST_RETURN_FORM_FOLLOWUP_FIELDS = {
  GSTR1: 'gstr1_followup_at',
  GSTR3B: 'gstr3b_followup_at',
  CMP08: 'cmp08_followup_at',
  GSTR4: 'gstr4_followup_at',
  GSTR9: 'gstr9_followup_at',
  GSTR9C: 'gstr9c_followup_at',
};

export const getGstReturnStatusChipClass = (status) => {
  const value = String(status || '').toUpperCase();
  const map = {
    DATA_PENDING: 'data-pending',
    DATA_RECEIVED: 'data-received',
    IN_PREPARATION: 'in-preparation',
    PENDING_OTP: 'pending-otp',
    READY_TO_FILE: 'ready-to-file',
    FILED: 'filed',
    OVERDUE: 'overdue',
    NOT_FILED: 'not-filed',
    MISSED: 'missed',
  };
  return map[value] || 'default';
};

export const GST_RETURN_STATUS_LEGEND = GST_RETURN_DETAIL_STATUSES.map((value) => ({
  value,
  label: GST_FILING_STATUS_LABELS[value] || value.replace(/_/g, ' '),
  chipClass: getGstReturnStatusChipClass(value),
}));

/** GST Filings matrix filter — exclude OVERDUE (use MISSED instead). */
export const GFM_FILING_STATUS_FILTER_OPTIONS = GST_RETURN_STATUS_LEGEND.filter(
  (item) => item.value !== 'OVERDUE',
);

export const getGstStatusStyleKey = (status) => {
  const value = String(status || '').toUpperCase();
  if (value === 'FILED' || value === 'COMPLETED' || value === 'SUCCESS') return 'completed';
  if (value === 'OVERDUE' || value === 'CRITICAL') return 'overdue';
  if (['DATA_PENDING', 'DATA_RECEIVED', 'IN_PREPARATION', 'PENDING_OTP', 'READY_TO_FILE', 'PENDING'].includes(value)) {
    return 'pending';
  }
  if (value === 'NOT_FILED') return 'not-filed';
  if (value === 'MISSED' || value === 'FAILED') return 'missed';
  return 'default';
};
