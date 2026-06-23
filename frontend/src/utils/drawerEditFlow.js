/**
 * Shared view/edit drawer behavior:
 * - Table "Edit" opens with initialEditMode → Cancel/Save close the drawer (no view fallback).
 * - View → Edit in drawer → Cancel returns to read-only view.
 */

export function resolveEditModeOnOpen(initialEditMode, isOpen) {
    return Boolean(isOpen && initialEditMode);
}

export function handleDrawerCancelEdit({
    initialEditMode,
    onClose,
    setEditMode,
    resetEditState,
}) {
    if (initialEditMode) {
        if (typeof onClose === 'function') onClose();
        return;
    }
    if (typeof setEditMode === 'function') setEditMode(false);
    if (typeof resetEditState === 'function') resetEditState();
}

export function shouldCloseDrawerAfterSave(initialEditMode) {
    return Boolean(initialEditMode);
}
