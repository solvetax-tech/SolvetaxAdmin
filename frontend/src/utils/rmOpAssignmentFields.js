/**
 * RM/OP assignment field visibility and payload rules for create/edit forms.
 *
 * Create & edit: RM sees/edits OP only (self as RM on create); OP sees/edits RM only (self as OP on create); admins see both.
 * On edit, each role keeps the assignment field they cannot see unchanged on save.
 */

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

/** Admins, managers, and RM/OP can open create and edit forms. */
export function canManageRmOpRecords(profileData, isAdmin = false) {
    if (isAdmin) return true;
    const role = String(profileData?.role || '').toUpperCase();
    if (role === 'SALES_MANAGER' || role === 'OP_MANAGER') return true;
    return role === 'RM' || role === 'OP';
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
