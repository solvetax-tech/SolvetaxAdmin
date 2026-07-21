/**
 * Normalize contact / government-id fields AS THE USER TYPES so the input can
 * never hold a value the backend would reject. Mirrors the backend patterns in
 * backend/gst_registration/schemas.py and backend/crm/schemas_common.py:
 *
 *   mobile / referral_phone_number  -> digits only, max 10   (backend ^\d{10}$)
 *   pan                             -> A-Z0-9 upper, max 10   (^[A-Z]{5}[0-9]{4}[A-Z]$)
 *   gstin                           -> A-Z0-9 upper, max 15   (15-char GSTIN)
 *
 * Any other field name is returned unchanged. Use in a form's onChange before
 * writing to state: `setForm({ ...form, [name]: sanitizeGovIdInput(name, value) })`.
 */
export function sanitizeGovIdInput(name, value) {
    if (typeof value !== 'string') return value;
    switch (name) {
        case 'mobile':
        case 'referral_phone_number':
        case 'referralPhoneNumber':
            return value.replace(/\D/g, '').slice(0, 10);
        case 'pan':
        case 'pan_number':
            return value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10);
        case 'gstin':
            return value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 15);
        default:
            return value;
    }
}
