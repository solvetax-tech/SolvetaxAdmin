/**
 * RM/OP assignment field visibility and payload rules for create/edit forms.
 *
 * Create & edit: RM sees/edits OP only (self as RM on create); OP sees/edits RM only (self as OP on create); admins see both.
 * On edit, each role keeps the assignment field they cannot see unchanged on save.
 */

import { resolveAssignmentEmpId } from './activeEmployees';

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

export function coerceAssignmentValue(value, assignmentPool = []) {
    return resolveAssignmentEmpId(value, assignmentPool);
}

function profileEmpId(profileData) {
    const raw = profileData?.emp_id ?? profileData?.sub;
    if (raw == null || raw === '') return null;
    const n = parseInt(String(raw).trim(), 10);
    return Number.isNaN(n) || n <= 0 ? null : n;
}

export function resolveRmIdForPayload({
    profileData,
    isEditMode = false,
    editingRecord,
    formRmId,
    assignmentPool = [],
}) {
    const { isRmUser, isOpUser } = getRmOpAssignmentVisibility(profileData);
    if (isEditMode && isRmUser && editingRecord) {
        const raw = editingRecord.rm_id ?? editingRecord.rm_username;
        return resolveAssignmentEmpId(raw, assignmentPool);
    }
    if (!isEditMode && isRmUser) {
        return profileEmpId(profileData);
    }
    if (isEditMode && isOpUser) {
        return resolveAssignmentEmpId(formRmId, assignmentPool);
    }
    return resolveAssignmentEmpId(formRmId, assignmentPool);
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
    assignmentPool = [],
}) {
    const { isOpUser, isRmUser } = getRmOpAssignmentVisibility(profileData);
    if (isEditMode && isOpUser && editingRecord) {
        const raw = editingRecord[opRecordKey] ?? editingRecord.op_id ?? editingRecord.op_username;
        return resolveAssignmentEmpId(raw, assignmentPool);
    }
    if (!isEditMode && isOpUser) {
        return profileEmpId(profileData);
    }
    if (isEditMode && isRmUser) {
        return resolveAssignmentEmpId(formOpId, assignmentPool);
    }
    return resolveAssignmentEmpId(formOpId, assignmentPool);
}
