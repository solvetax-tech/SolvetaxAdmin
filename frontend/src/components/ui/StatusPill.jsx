import React from 'react';

/**
 * One status pill for the whole app. Maps any status/enum string to a semantic
 * tone (success / warning / danger / info / neutral) so PAID, VERIFIED, ACTIVE,
 * PENDING, MISSED, FRESH_LEAD, etc. all render consistently in light + dark.
 * Replaces the ~112 bespoke pill classes across features.
 */
const TONE_MAP = {
  // success (green — "cleared / filed / good")
  PAID: 'success', VERIFIED: 'success', ACTIVE: 'success', FILED: 'success',
  COMPLETED: 'success', DONE: 'success', APPROVED: 'success', SUBSCRIBED: 'success',
  CLEARED: 'success', PROVIDED: 'success', SUCCESS: 'success', LIVE: 'success',
  YES: 'success', ENABLED: 'success', GST_REGISTRATION_DONE: 'success',
  // warning (amber — "in flight / needs attention")
  PENDING: 'warning', DATA_PENDING: 'warning', IN_PREPARATION: 'warning',
  IN_PROGRESS: 'warning', PROCESSING: 'warning', SCHEDULED: 'warning', PARTIAL: 'warning',
  FOLLOW_UP: 'warning', FOLLOWUP: 'warning', ON_HOLD: 'warning', PENDING_REGISTRATION_DATA: 'warning',
  SCHEDULED_PAYMENTS: 'warning', LOW: 'warning', PENDING_OTP: 'warning',
  // danger (red — "failed / stopped")
  MISSED: 'danger', FAILED: 'danger', REJECTED: 'danger', CANCELLED: 'danger',
  CANCELED: 'danger', INACTIVE: 'danger', OVERDUE: 'danger', EXPIRED: 'danger',
  NOT_INTERESTED: 'danger', DISABLED: 'danger', ERROR: 'danger', NO: 'danger', HIGH: 'danger',
  // info (blue — "new / neutral flow state")
  NEW: 'info', FRESH_LEAD: 'info', INTERESTED: 'info', CONTACTED: 'info', DRAFT: 'info',
  NORMAL: 'info', DATA_RECEIVED: 'info', READY_TO_FILE: 'info',
};

export function statusTone(value) {
  if (value === null || value === undefined) return 'neutral';
  const key = String(value).trim().toUpperCase().replace(/[\s-]+/g, '_');
  return TONE_MAP[key] || 'neutral';
}

export default function StatusPill({ value, tone, dot = true, className = '', children }) {
  const t = tone || statusTone(value);
  const isEmpty = value === null || value === undefined || value === '' || value === '-';
  const label =
    children ?? (isEmpty ? '—' : String(value).replace(/_/g, ' '));
  return (
    <span className={`ui-pill ui-pill--${t} ${className}`.trim()}>
      {dot && !isEmpty && <span className="ui-pill__dot" />}
      {label}
    </span>
  );
}
