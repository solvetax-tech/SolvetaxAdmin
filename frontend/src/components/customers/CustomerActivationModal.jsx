import React, { useState } from 'react';
import { AlertCircle, X, RotateCcw } from 'lucide-react';
import './CustomerActivationModal.css';
import api from '../../utils/api';
import { addNotification } from '../../utils/notificationUtils';

const CustomerActivationModal = ({ isOpen, onClose, customer, onActivate }) => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    if (!isOpen) return null;

    const handleActivate = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await api.post(`/api/v1/customers/${customer.customer_id}/activate`, {});
            // Backend returns specific success messages for Case 1, 2, and 3
            const successMsg = response.data?.message || 'Customer activated successfully! ✨';

            addNotification(
                'Customer Activated',
                successMsg,
                'CREATE'
            );

            onActivate(successMsg);
        } catch (err) {
            setError(err.response?.data?.detail || err.message || 'Failed to activate customer');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="customer-activation-overlay">
            <div className="customer-activation-content">
                <button className="confirm-close-btn" onClick={onClose}>
                    <X size={20} />
                </button>

                <div className="confirm-icon-wrapper">
                    <AlertCircle size={40} color="#2eb87a" />
                </div>

                <h2>Activate Customer</h2>
                <p>
                    This customer - <strong>{customer?.full_name}</strong> is currently deactivated.
                    First activate to edit the customer details.
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

export default CustomerActivationModal;
