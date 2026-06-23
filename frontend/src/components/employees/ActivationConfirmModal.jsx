import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, X, RotateCcw } from 'lucide-react';
import './ActivationConfirmModal.css';
import api from '../../utils/api';
import { addNotification } from '../../utils/notificationUtils';

const ActivationConfirmModal = ({ isOpen, onClose, employee, onActivate }) => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    if (!isOpen) return null;

    const handleActivate = async () => {
        setLoading(true);
        setError(null);
        try {
            await api.post(`/api/v1/employees/${employee.emp_id}/emp_dyn/edit`, { is_active: true });

            addNotification(
                'Employee Activated',
                `Employee ${employee.first_name} ${employee.last_name || ''} has been activated.`,
                'CREATE'
            );

            onActivate();
        } catch (err) {
            setError(err.message || 'Failed to activate employee');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="activation-confirm-overlay">
            <div className="activation-confirm-content">
                <button className="confirm-close-btn" onClick={onClose}>
                    <X size={20} />
                </button>

                <div className="confirm-icon-wrapper">
                    <AlertCircle size={40} color="#2eb87a" />
                </div>

                <h2>Activate Employee</h2>
                <p>
                    This employee - <strong>{employee?.first_name} {employee?.last_name}</strong> is deactivated.
                    First activate to edit the employee details.
                </p>

                {error && (
                    <div className="confirm-error-banner">
                        <AlertCircle size={16} />
                        {error}
                    </div>
                )}

                <div className="confirm-actions">
                    <button
                        className="btn-confirm-cancel"
                        onClick={onClose}
                        disabled={loading}
                    >
                        Cancel
                    </button>
                    <button
                        className="btn-confirm-activate"
                        onClick={handleActivate}
                        disabled={loading}
                        style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
                    >
                        {loading ? <RotateCcw size={16} className="refresh-spin" /> : null}
                        <span>
                            {loading ? 'Activating...' : 'Activate'}
                        </span>
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ActivationConfirmModal;
