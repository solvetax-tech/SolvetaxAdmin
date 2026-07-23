/**
 * RM/OP assignment visibility and payload rules for create/edit forms, and the
 * matching column rule for the list tables.
 *
 * Create & edit: RM sees/edits OP only (self as RM on create); OP sees/edits RM only (self as OP on create); admins see both.
 * On edit, each role keeps the assignment field they cannot see unchanged on save.
 * Tables: same rule — an RM hides the RM column, an OP hides the OP column.
 */

import { getSessionRole } from './rbac';

export function getRmOpAssignmentVisibility(profileData) {
    const userRole = String(profileData?.role || '').toUpperCase();
    const isRmUser = userRole === 'RM';
    const isOpUser = userRole === 'OP';
    const isRmOrOpUser = isRmUser || isOpUser;
    const showRmField = !isRmUser;
    const showOpField = !isOpUser;
    const showAssignmentSection = showRmField || showOpField;
    return {
        userRole,
        isRmUser,
        isOpUser,
        isRmOrOpUser,
        showRmField,
        showOpField,
        showAssignmentSection,
    };
}

/**
 * Ledger column visibility for the same rule: an RM already knows every row is
 * theirs, so the RM column is dead weight; likewise OP. Managers keep both —
 * they oversee a team, so the column still distinguishes rows.
 *
 * The ledgers are CSS grids with fixed track lists, so a hidden column keeps its
 * cell in the DOM and collapses to a zero-width track instead of being dropped —
 * skipping the cell would shift every following column into the wrong track.
 * Spread `containerClass` onto the header/row element and `cellClass` onto the
 * matching RM/OP cells.
 */
export function getRmOpColumnVisibility(profileData) {
    // CRM/dashboard tables sit too deep to be handed profileData; fall back to
    // the role on the session JWT so they follow the same rule.
    const resolved = profileData?.role ? profileData : { role: getSessionRole() };
    const { isRmUser, isOpUser, showRmField, showOpField } = getRmOpAssignmentVisibility(resolved);
    return {
        showRmColumn: showRmField,
        showOpColumn: showOpField,
        containerClass: `${isRmUser ? 'rmop-hide-rm' : ''}${isOpUser ? ' rmop-hide-op' : ''}`.trim(),
        rmCellClass: showRmField ? '' : 'rmop-col-hidden',
        opCellClass: showOpField ? '' : 'rmop-col-hidden',
    };
}

/** Admins, managers, and RM/OP can open create and edit forms. */
export function canManageRmOpRecords(profileData, isAdmin = false) {
    if (isAdmin) return true;
    const role = String(profileData?.role || '').toUpperCase();
    if (role === 'SALES_MANAGER' || role === 'OP_MANAGER') return true;
    return role === 'RM' || role === 'OP';
}

/**
 * Create access for the sales-funnel origination points — new Customer, new GST
 * registration, new Customer Service, new Contact/Referral lead. These start a
 * record in the acquisition funnel; the operations roles (OP, OP_MANAGER) work
 * existing records but don't originate them, so they're excluded here even
 * though canManageRmOpRecords (edits, plus create of nested GST people/documents)
 * still allows them.
 *
 * `isAdmin` short-circuits to true. Otherwise the role comes from profileData
 * when available, falling back to the session-token role for components mounted
 * too deep to receive profileData (e.g. Contact/Referral leads).
 */
export function canCreateSalesRecords(profileData, isAdmin = false) {
    if (isAdmin) return true;
    const role = String(profileData?.role || getSessionRole() || '').toUpperCase();
    return role === 'ADMIN' || role === 'SALES_MANAGER' || role === 'RM';
}

export function coerceAssignmentValue(value) {
    if (value == null || value === '') return null;
    const s = String(value).trim();
    const n = parseInt(s, 10);
    if (!Number.isNaN(n) && String(n) === s) return n;
    return s;
}

export function resolveRmIdForPayload({
    profileData,
    isEditMode = false,
    editingRecord,
    formRmId,
}) {
    const { isRmUser, isOpUser } = getRmOpAssignmentVisibility(profileData);
    if (isEditMode && isRmUser && editingRecord) {
        const raw = editingRecord.rm_id ?? editingRecord.rm_username;
        return coerceAssignmentValue(raw);
    }
    if (!isEditMode && isRmUser && profileData?.username) {
        return profileData.username;
    }
    if (isEditMode && isOpUser) {
        return coerceAssignmentValue(formRmId);
    }
    return coerceAssignmentValue(formRmId);
}

/**
 * @param {string} [opRecordKey] - Record field for OP when API uses another name (e.g. `created_by` on GST registration).
 */
export function resolveOpIdForPayload({
    profileData,
    isEditMode = false,
    editingRecord,
    formOpId,
    opRecordKey = 'op_id',
}) {
    const { isOpUser, isRmUser } = getRmOpAssignmentVisibility(profileData);
    if (isEditMode && isOpUser && editingRecord) {
        const raw = editingRecord[opRecordKey] ?? editingRecord.op_id ?? editingRecord.op_username;
        return coerceAssignmentValue(raw);
    }
    if (!isEditMode && isOpUser && profileData?.username) {
        return profileData.username;
    }
    if (isEditMode && isRmUser) {
        return coerceAssignmentValue(formOpId);
    }
    return coerceAssignmentValue(formOpId);
}
