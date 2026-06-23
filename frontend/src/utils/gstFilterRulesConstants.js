import {
  GST_FILING_STATUS_LABELS,
  GST_RETURN_FORM_OPTIONS,
  gstFilingStatusOptions,
} from './gstFilingStatusConstants';

export const FILING_ATTRIBUTE_FIELD_OPTIONS = [
  { value: 'STATUS', label: 'Status' },
  { value: 'PRIORITY', label: 'Priority' },
  { value: 'FILING_CATEGORY', label: 'Category' },
  { value: 'FILING_FREQUENCY', label: 'Frequency' },
  { value: 'TAXPAYER_TYPE', label: 'Taxpayer Type' },
  { value: 'STATE', label: 'State' },
];

export const PRIORITY_OPTIONS = [
  { value: 'HIGH', label: 'High' },
  { value: 'NORMAL', label: 'Normal' },
  { value: 'LOW', label: 'Low' },
];

export const FILING_CATEGORY_OPTIONS = [
  { value: 'RETURN', label: 'Standard Return' },
  { value: 'ANNUAL', label: 'Annual Filing' },
];

export const FILING_FREQUENCY_OPTIONS = [
  { value: 'MONTHLY', label: 'Monthly' },
  { value: 'QUARTERLY', label: 'Quarterly' },
  { value: 'YEARLY', label: 'Yearly' },
];

export const TAXPAYER_TYPE_OPTIONS = [
  { value: 'REGULAR', label: 'Regular' },
  { value: 'COMPOSITION', label: 'Composition' },
];

export const DOCUMENT_FILTER_FIELD_OPTIONS = [
  { value: 'DOCUMENT_TYPE', label: 'Document Type' },
  { value: 'VERIFIED', label: 'Verified Status' },
];

export const DOCUMENT_TYPE_OPTIONS = [
  { value: 'WORKING_SHEET', label: 'Working Sheet' },
  { value: 'SUMMARY_SHEET', label: 'Summary Sheet' },
  { value: 'RECON_SHEET', label: 'Recon Sheet' },
  { value: 'MISC_SHEET', label: 'Miscellaneous' },
];

export const VERIFIED_STATUS_OPTIONS = [
  { value: 'VERIFIED', label: 'Verified' },
  { value: 'UNVERIFIED', label: 'Unverified' },
];

export const createEmptyFilingAttributeRule = () => ({ field: '', value: '' });
export const createEmptyDueDateRule = () => ({ form: '', from: '', to: '' });
export const createEmptyDocumentFilterRule = () => ({ field: '', value: '' });

const isNonEmpty = (value) => value !== '' && value !== null && value !== undefined;

export const getActiveFilingAttributeRules = (rules = []) =>
  (rules || []).filter((rule) => isNonEmpty(rule?.field) && isNonEmpty(rule?.value));

export const getActiveDueDateRules = (rules = []) =>
  (rules || []).filter((rule) => isNonEmpty(rule?.form) && (isNonEmpty(rule?.from) || isNonEmpty(rule?.to)));

export const getActiveDocumentFilterRules = (rules = []) =>
  (rules || []).filter((rule) => isNonEmpty(rule?.field) && isNonEmpty(rule?.value));

export const getFilingAttributeValueOptions = (field, states = []) => {
  switch (field) {
    case 'STATUS':
      return gstFilingStatusOptions(false);
    case 'PRIORITY':
      return PRIORITY_OPTIONS;
    case 'FILING_CATEGORY':
      return FILING_CATEGORY_OPTIONS;
    case 'FILING_FREQUENCY':
      return FILING_FREQUENCY_OPTIONS;
    case 'TAXPAYER_TYPE':
      return TAXPAYER_TYPE_OPTIONS;
    case 'STATE':
      return (states || []).map((state) => {
        const value = state?.value || state?.name || state;
        const label = state?.label || state?.name || state?.display_name || value;
        return { value: String(value).toUpperCase(), label };
      });
    default:
      return [];
  }
};

export const getDocumentFilterValueOptions = (field) => {
  if (field === 'DOCUMENT_TYPE') return DOCUMENT_TYPE_OPTIONS;
  if (field === 'VERIFIED') return VERIFIED_STATUS_OPTIONS;
  return [];
};

const formatFieldLabel = (options, value) =>
  options.find((item) => item.value === value)?.label || value;

export const formatFilingAttributeRule = (rule, states = []) => {
  const fieldLabel = formatFieldLabel(FILING_ATTRIBUTE_FIELD_OPTIONS, rule.field);
  const valueOptions = getFilingAttributeValueOptions(rule.field, states);
  const valueLabel = formatFieldLabel(valueOptions, rule.value)
    || GST_FILING_STATUS_LABELS[rule.value]
    || rule.value;
  return `${fieldLabel} = ${valueLabel}`;
};

export const formatDueDateRule = (rule) => {
  const formLabel = formatFieldLabel(GST_RETURN_FORM_OPTIONS, rule.form) || rule.form;
  const parts = [];
  if (rule.from) parts.push(`from ${rule.from}`);
  if (rule.to) parts.push(`to ${rule.to}`);
  return `${formLabel} due ${parts.join(' ')}`.trim();
};

export const formatDocumentFilterRule = (rule) => {
  const fieldLabel = formatFieldLabel(DOCUMENT_FILTER_FIELD_OPTIONS, rule.field);
  const valueOptions = getDocumentFilterValueOptions(rule.field);
  const valueLabel = formatFieldLabel(valueOptions, rule.value) || rule.value;
  return `${fieldLabel} = ${valueLabel}`;
};

export const formatRulesSummary = (matchMode, rules = [], formatter) => {
  const active = (rules || []).filter(Boolean);
  if (!active.length || !formatter) return null;
  const joiner = (matchMode || 'AND').toUpperCase() === 'OR' ? ' OR ' : ' AND ';
  return active.map(formatter).join(joiner);
};

export const appendFilingFilterRulesToParams = (params, matchMode, rules = []) => {
  const active = getActiveFilingAttributeRules(rules);
  if (!active.length) return;
  params.append('filing_filter_match', (matchMode || 'AND').toUpperCase());
  active.forEach((rule) => {
    params.append('filing_filter_rules', `${rule.field}:${rule.value}`);
  });
};

export const appendDueDateRulesToParams = (params, matchMode, rules = []) => {
  const active = getActiveDueDateRules(rules);
  if (!active.length) return;
  params.append('due_date_match', (matchMode || 'AND').toUpperCase());
  active.forEach((rule) => {
    params.append('due_date_rules', `${rule.form}:${rule.from || ''}:${rule.to || ''}`);
  });
};

export const appendDocumentFilterRulesToParams = (params, matchMode, rules = []) => {
  const active = getActiveDocumentFilterRules(rules);
  if (!active.length) return;
  params.append('document_filter_match', (matchMode || 'AND').toUpperCase());
  active.forEach((rule) => {
    params.append('document_filter_rules', `${rule.field}:${rule.value}`);
  });
};
