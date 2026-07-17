import api from './api';
import { withPublicApiKeyHeaders } from './publicApiKey';
import { getRmOpAssignmentVisibility } from './rmOpAssignmentFields';
import { resolveBusinessTypeForApi } from './businessTypeUtils';

/** Set by digital marketing integration only — never sent from staff UI. */
export const CUSTOMER_MARKETING_ONLY_FIELDS = ['lead_source', 'tag', 'lead_type'];

/** POST /api/v1/customers — staff dashboard create body. */
export const CUSTOMER_CREATE_ALLOWED_FIELDS = [
    'full_name',
    'email',
    'mobile',
    'service_required',
    'language',
    'business_name',
    'business_description',
    'business_image_url',
    'business_type',
    'state',
    'city',
    'remark',
    'referral_phone_number',
];

/** POST /api/v1/customers/{id}/edit — dynamic PATCH body. */
export const CUSTOMER_EDIT_ALLOWED_FIELDS = [
    ...CUSTOMER_CREATE_ALLOWED_FIELDS,
    'rm_id',
    'op_id',
];

export const INITIAL_CUSTOMER_FORM = {
    full_name: '',
    email: '',
    mobile: '',
    business_name: '',
    business_description: '',
    business_image_url: '',
    business_type: '',
    business_type_other: '',
    state: '',
    city: '',
    remark: '',
    rm_id: '',
    op_id: '',
    referral_phone_number: '',
    language: '',
    service_required: [],
};

export function customerRequestHeaders(staffToken = null) {
    const token = staffToken ?? (typeof localStorage !== 'undefined' ? localStorage.getItem('session_token') : null);
    const headers = withPublicApiKeyHeaders({
        'Content-Type': 'application/json',
    });
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }
    return headers;
}

export function normalizeReferralPhone(value) {
    const digits = String(value ?? '').replace(/\D/g, '');
    return digits.length > 0 ? digits : null;
}

export function normalizeMobile(value) {
    const digits = String(value ?? '').replace(/\D/g, '');
    return digits.length === 10 ? digits : '';
}

/** Optional; when set must be exactly 10 digits (same rule as mobile). */
export function validateReferralPhone(value) {
    const digits = String(value ?? '').replace(/\D/g, '');
    if (!digits) return '';
    if (!/^\d{10}$/.test(digits)) return '10 digits required';
    return '';
}


function coerceEmpId(value) {
    if (value == null || value === '') return null;
    const n = parseInt(String(value).trim(), 10);
    return Number.isNaN(n) || n <= 0 ? null : n;
}

function pickStringField(payload, key, value) {
    if (value == null) return;
    const trimmed = typeof value === 'string' ? value.trim() : value;
    if (trimmed !== '') payload[key] = trimmed;
}

/**
 * POST /api/v1/customers — staff create.
 * rm_id / op_id: only sent when the user can pick them (admin). RM/OP logins omit
 * their own role field — backend sets assignee from JWT (see customer.py create).
 */
export function buildCustomerCreatePayload(formData, profileData, businessTypeConfig = []) {
    const visibility = getRmOpAssignmentVisibility(profileData);
    const payload = {};

    pickStringField(payload, 'full_name', formData.full_name);
    pickStringField(payload, 'email', formData.email);
    const mobile = normalizeMobile(formData.mobile);
    if (mobile) payload.mobile = mobile;

    pickStringField(payload, 'business_name', formData.business_name);
    pickStringField(payload, 'business_description', formData.business_description);
    pickStringField(payload, 'business_image_url', formData.business_image_url);
    pickStringField(
        payload,
        'business_type',
        resolveBusinessTypeForApi(
            formData.business_type,
            formData.business_type_other,
            businessTypeConfig,
        ),
    );
    pickStringField(payload, 'state', formData.state);
    pickStringField(payload, 'city', formData.city);
    pickStringField(payload, 'remark', formData.remark);
    pickStringField(payload, 'language', formData.language);

    const referral = normalizeReferralPhone(formData.referral_phone_number);
    if (referral) payload.referral_phone_number = referral;

    const services = Array.isArray(formData.service_required)
        ? formData.service_required.filter(Boolean)
        : [];
    if (services.length > 0) payload.service_required = services;

    if (visibility.showRmField && formData.rm_id) {
        const rmId = coerceEmpId(formData.rm_id);
        if (rmId != null) payload.rm_id = rmId;
    }
    if (visibility.showOpField && formData.op_id) {
        const opId = coerceEmpId(formData.op_id);
        if (opId != null) payload.op_id = opId;
    }

    return payload;
}

/** POST /api/v1/customers/:id/edit */
export function buildCustomerEditPayload(formData, profileData, editingRecord, businessTypeConfig = []) {
    const visibility = getRmOpAssignmentVisibility(profileData);
    const payload = {};

    for (const key of CUSTOMER_EDIT_ALLOWED_FIELDS) {
        let value = formData[key];
        if (key === 'business_type') {
            value = resolveBusinessTypeForApi(
                formData.business_type,
                formData.business_type_other,
                businessTypeConfig,
            );
        }
        if (key === 'referral_phone_number') {
            payload.referral_phone_number = normalizeReferralPhone(value);
            continue;
        }
        if (key === 'mobile') {
            const mobile = normalizeMobile(value);
            if (mobile) payload.mobile = mobile;
            continue;
        }
        if (key === 'service_required') {
            payload.service_required = Array.isArray(value) ? value.filter(Boolean) : [];
            continue;
        }
        if (value !== undefined && value !== '') {
            payload[key] = typeof value === 'string' ? value.trim() : value;
        }
    }

    if (visibility.showRmField) {
        const rmId = coerceEmpId(formData.rm_id);
        payload.rm_id = rmId != null ? rmId : null;
    } else if (editingRecord?.rm_id != null) {
        payload.rm_id = editingRecord.rm_id;
    }

    if (visibility.showOpField) {
        const opId = coerceEmpId(formData.op_id);
        payload.op_id = opId != null ? opId : null;
    } else if (editingRecord?.op_id != null) {
        payload.op_id = editingRecord.op_id;
    }

    return payload;
}

export async function createCustomer(payload, staffToken = null) {
    return api.post('/api/v1/customers', payload, {
        headers: customerRequestHeaders(staffToken),
    });
}

/** Stored mobiles are exactly 10 digits (see normalizeMobile), so a pasted
 *  +91/0-prefixed number has to be reduced before it can match. */
function toStoredMobile(digits) {
    if (digits.length === 10) return digits;
    if (digits.length === 12 && digits.startsWith('91')) return digits.slice(2);
    if (digits.length === 11 && digits.startsWith('0')) return digits.slice(1);
    return '';
}

/**
 * GET /api/v1/customers/customer_get/filter — lookup for customer pickers.
 *
 * The endpoint ANDs its conditions, so matching "name OR business" needs two
 * calls merged here. mobile is an exact match server-side
 * (`trim(mobile) = trim($1)`), hence the full-10-digits requirement; a shorter
 * digit string is read as a customer_id instead, which keeps working for staff
 * who know the id. Results are scoped by the caller's own visibility rules.
 */
export async function searchCustomers(query, { signal, limit = 8 } = {}) {
    const q = String(query ?? '').trim();
    if (q.length < 2) return [];

    const base = { is_active: true, limit };
    const digits = q.replace(/\D/g, '');
    const looksNumeric = /^[\d\s+()-]+$/.test(q);
    const requests = [];

    if (looksNumeric) {
        const mobile = toStoredMobile(digits);
        if (mobile) {
            requests.push({ ...base, mobile });
        } else if (digits.length > 0 && digits.length < 10) {
            requests.push({ ...base, customer_id: Number(digits) });
        } else {
            return [];
        }
    } else {
        requests.push({ ...base, full_name: q }, { ...base, business_name: q });
    }

    const pages = await Promise.all(
        requests.map((params) =>
            api.get('/api/v1/customers/customer_get/filter', { params, signal }).then((res) => {
                const body = res.data;
                return Array.isArray(body) ? body : (body?.data || body?.items || []);
            }),
        ),
    );

    // Name matches lead business-name matches; first occurrence wins.
    const byId = new Map();
    pages.flat().forEach((row) => {
        if (row?.customer_id != null && !byId.has(row.customer_id)) {
            byId.set(row.customer_id, row);
        }
    });
    return Array.from(byId.values()).slice(0, limit);
}

export const SERVICE_REQUIRED_CRM_HINT =
    'GST Registration and ITR Filing selections create CRM leads automatically (Smart Board). Other services are added as pending customer services.';
