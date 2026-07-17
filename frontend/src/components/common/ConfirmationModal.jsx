import React from 'react';
import { AlertCircle, X, Check, RotateCcw } from 'lucide-react';
import './ConfirmationModal.css';

const ConfirmationModal = ({
    isOpen,
    onClose,
    onConfirm,
    title = 'Are you sure?',
    message = 'This action cannot be undone.',
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    loading = false,
    type = 'danger' // 'danger', 'info', 'warning'
}) => {
    if (!isOpen) return null;

    const getIcon = () => {
        switch (type) {
            case 'danger': return <AlertCircle size={40} color="var(--danger)" />;
            case 'warning': return <AlertCircle size={40} color="var(--warning)" />;
            default: return <AlertCircle size={40} color="var(--info)" />;
        }
    };

    return (
        <div className="confirmation-overlay">
            <div className="confirmation-content" onClick={e => e.stopPropagation()}>
                <button className="confirmation-close-btn" onClick={onClose}>
                    <X size={20} />
                </button>

                <div className={`confirmation-icon-wrapper ${type}`}>
                    {getIcon()}
                </div>

                <h2>{title}</h2>
                <p>{message}</p>

                <div className="confirmation-actions">
                    <button
                        className="btn-confirmation-cancel"
                        onClick={onClose}
                        disabled={loading}
                    >
                        {cancelText}
                    </button>
                    <button
                        className={`btn-confirmation-confirm ${type}`}
                        onClick={onConfirm}
                        disabled={loading}
                    >
                        {loading ? <RotateCcw size={16} className="refresh-spin" /> : <Check size={16} />}
                        <span>
                            {loading ? 'Processing...' : confirmText}
                        </span>
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ConfirmationModal;
