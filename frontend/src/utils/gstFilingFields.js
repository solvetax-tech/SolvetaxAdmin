/**
 * @file gstFilingFields.js
 * @description Single source of truth for WHICH fields the GST filing form may
 * send, and on which request. Keep this in sync with the backend schemas:
 *
 *   POST  /api/v1/gst-filings        -> GSTFilingIn      (backend/gst_registration_filing/schemas.py)
 *   PATCH /api/v1/gst-filings/{id}   -> GSTFilingEditIn
 *
 * Both schemas are `extra: "forbid"`. That makes this file load-bearing: ONE
 * field the schema does not declare makes pydantic reject the ENTIRE request
 * with 422, so an unrelated stray key silently blocks every other edit on the
 * form. That is exactly the bug this file was extracted to prevent -- the edit
 * modal always sent `filing_period`, which GSTFilingEditIn does not accept, so
 * no filing could be updated at all, whatever the user changed.
 */

/**
 * Editable on PATCH. Every one of these exists on GSTFilingEditIn.
 * Grouped by what they mean, not by table order.
 */
export const FILING_EDITABLE_FIELDS = [
    // --- Core business. Changing ANY of these makes the backend recalculate
    // --- and rebuild the filing's return-detail rows (recalc_required).
    'filing_category',
    'filing_frequency',
    'taxpayer_type',
    'turnover_details',
    'state',

    // --- Workflow
    'status',
    'priority',
    'remarks',

    // --- Assignment. Backend drops these unless the caller is ADMIN.
    'rm_id',
    'op_id',

    // --- Business identity / login. These also sync back to the linked
    // --- gst_registration master record ("Identity Sync Active" in the modal).
    'business_name',
    'business_type',
    'business_description',
    'username',
    'password',
    'email_id',

    // --- Flags & misc
    'rent',
    'rule14a',
    'is_auto_enabled',
];

/**
 * Sent on POST only. The backend deliberately refuses these on PATCH:
 *
 *  - filing_period / gst_registration_id: identity. update_gst_filing() reads
 *    `filing_period = old["filing_period"]` and pins the registration, because
 *    changing either would orphan the generated return rows and collide with
 *    the one-filing-per-period rule that is only enforced on create.
 *  - customer_id / gstin: ownership, likewise fixed once created.
 *  - mode: create-time only.
 *
 * Anything here MUST be stripped from a PATCH payload or the request 422s.
 */
export const FILING_CREATE_ONLY_FIELDS = [
    'customer_id',
    'gst_registration_id',
    'gstin',
    'filing_period',
    'mode',
];

/** Everything the create form may send. */
export const FILING_CREATABLE_FIELDS = [
    ...FILING_CREATE_ONLY_FIELDS,
    ...FILING_EDITABLE_FIELDS,
];

/**
 * Accepted by GSTFilingEditIn but intentionally not exposed by this form
 * (no input renders them): gst_reg_status, language, referral_id,
 * referral_entity, is_active. Listed so the omission reads as a decision
 * rather than an oversight if someone diffs the schema against this file.
 */
export const FILING_EDITABLE_NOT_IN_FORM = [
    'gst_reg_status',
    'language',
    'referral_id',
    'referral_entity',
    'is_active',
];

/**
 * Strip a payload down to what the target request actually accepts.
 * @param {object} payload
 * @param {boolean} isEdit true for PATCH, false for POST
 */
export const pickFilingPayloadFields = (payload, isEdit) => {
    const allowed = isEdit ? FILING_EDITABLE_FIELDS : FILING_CREATABLE_FIELDS;
    return Object.fromEntries(
        Object.entries(payload).filter(([key]) => allowed.includes(key))
    );
};
