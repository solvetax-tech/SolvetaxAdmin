import { PAYMENT_PENDING_DEFAULT_REMARK } from './crmLeadRemarksConfig';

/** Sidebar tab id for the payment-pending leads board. */
export const CRM_TAB_PAYMENT_PENDING = 'payment-pending';
export const CRM_TAB_TODAY_ASSIGNED = 'today-assigned';

export const PAYMENT_PENDING_BOARD_STAGE = 'PENDING_ITR_DATA';

/** Fixed filters for the payment-pending board (ITR only). */
export const PAYMENT_PENDING_BOARD_FILTERS = {
    stages: [PAYMENT_PENDING_BOARD_STAGE],
    remarks: PAYMENT_PENDING_DEFAULT_REMARK,
};

export const PAYMENT_PENDING_BOARD_LABEL = 'Payment done service pending';
export const TODAY_ASSIGNED_BOARD_LABEL = 'Today Assigned Leads';

export const CRM_TAB_DISPLAY_NAMES = {
    dashboard: 'Dashboard',
    leads: 'Leads',
    [CRM_TAB_PAYMENT_PENDING]: PAYMENT_PENDING_BOARD_LABEL,
    [CRM_TAB_TODAY_ASSIGNED]: TODAY_ASSIGNED_BOARD_LABEL,
    'smart-board': 'Smart Board',
    pipeline: 'Pipeline',
    settings: 'Settings',
    notifications: 'Notifications',
    knowledge: 'Knowledge',
    profile: 'Profile',
};
