import React from 'react';
import { Upload, RotateCcw } from 'lucide-react';

/** Standard right-drawer footer shell (GST Documents layout). */
export function AppDrawerFooter({ children, leading = null }) {
    return (
        <div className="drawer-footer gst-reg-details-footer app-drawer-edit-footer">
            <div className="footer-actions-v4">
                {leading}
                {children}
            </div>
        </div>
    );
}

/** Same footer layout for modal-overlay drawers (Employees, Customers). */
export function AppDrawerModalFooter({ children, leading }) {
    return (
        <div className="modal-footer gst-reg-details-footer app-drawer-edit-footer">
            <div className="footer-actions-v4">
                {leading}
                {children}
            </div>
        </div>
    );
}

export function AppDrawerBtnDelete({ onClick, disabled, children, label = 'Delete Record', className = '' }) {
    const text = children ?? label;
    return (
        <button
            type="button"
            className={`app-drawer-btn-cancel app-drawer-btn-delete${className ? ` ${className}` : ''}`}
            onClick={onClick}
            disabled={disabled}
        >
            {text}
        </button>
    );
}

export function AppDrawerBtnCancel({ onClick, disabled, children = 'Cancel' }) {
    return (
        <button type="button" className="app-drawer-btn-cancel" onClick={onClick} disabled={disabled}>
            {children}
        </button>
    );
}

export function AppDrawerBtnSave({
    onClick,
    disabled,
    loading = false,
    label = 'Save Changes',
    type = 'button',
    icon: Icon = Upload,
    loadingLabel = 'Saving...',
}) {
    return (
        <button
            type={type}
            className="app-drawer-btn-save glow-green"
            onClick={onClick}
            disabled={disabled || loading}
        >
            {loading ? <RotateCcw size={16} className="refresh-spin gst-refresh-spin" /> : <Icon size={16} />}
            {loading ? loadingLabel : label}
        </button>
    );
}
