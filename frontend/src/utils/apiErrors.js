/**
 * @file apiErrors.js
 * @description Parse this API's error envelopes into something a user can act on.
 *
 * WHY THIS EXISTS
 * backend/main.py installs a custom RequestValidationError handler:
 *
 *     {"detail": "Request validation failed", "errors": [ ...pydantic errors... ]}
 *
 * That is NOT FastAPI's default shape (where `detail` IS the error array). Every
 * frontend extractor was written against the default and checks
 * `Array.isArray(detail)` -- a branch that can never run against this backend.
 * They then fall through to `typeof detail === 'string'` and surface the literal
 * string "Request validation failed", throwing away the per-field reasons the
 * server actually sent. A user gets a red box naming no field.
 *
 * Handles all three envelopes this API emits:
 *   1. 422 validation  -> {detail: "Request validation failed", errors: [...]}
 *   2. 400 field errors -> {detail: {error: {message, fields: {name: msg}}}}
 *   3. plain           -> {detail: "some message"}
 */

const humanizeField = (name) => String(name).replace(/_/g, ' ').trim();

/**
 * Field-keyed errors, suitable for inline display next to inputs.
 * @returns {Object<string,string>} e.g. { ownership_category: 'Field required' }
 */
export const extractFieldErrors = (err) => {
    const data = err?.response?.data;
    if (!data) return {};

    // 2. explicit field map (backend's _raise_validation)
    const fields = data?.detail?.error?.fields;
    if (fields && typeof fields === 'object') return { ...fields };

    // 1. pydantic 422 -> {errors: [{loc: ['body','x'], msg}]}
    const out = {};
    const list = Array.isArray(data.errors) ? data.errors
        : Array.isArray(data.detail) ? data.detail   // default FastAPI shape, just in case
        : [];
    list.forEach((e) => {
        const loc = Array.isArray(e?.loc) ? e.loc : [];
        // drop the leading 'body'/'query' segment
        const name = loc.filter((p) => p !== 'body' && p !== 'query').pop();
        if (name != null) out[name] = e?.msg || 'Invalid value';
    });
    return out;
};

/**
 * One human-readable sentence naming the offending fields.
 */
export const extractErrorMessage = (err, fallback = 'Request failed.') => {
    const data = err?.response?.data;
    const detail = data?.detail;

    const fieldErrors = extractFieldErrors(err);
    const names = Object.keys(fieldErrors);
    if (names.length) {
        return names
            .map((n) => `${humanizeField(n)}: ${fieldErrors[n]}`)
            .join('\n');
    }

    if (detail?.error?.message) return detail.error.message;
    if (typeof detail === 'string') return detail;
    return err?.message || fallback;
};
