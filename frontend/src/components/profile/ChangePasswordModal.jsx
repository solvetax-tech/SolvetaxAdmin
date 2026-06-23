import React, { useState, useEffect } from 'react';
import {
    X, Lock, Shield, Eye, EyeOff, Check, AlertCircle,
    RefreshCw, CheckCircle2, AlertTriangle, Loader2, ShieldCheck
} from 'lucide-react';
import api from '../../utils/api';
import './ChangePasswordModal.css';

const ChangePasswordModal = ({ isOpen, onClose, empId, onPasswordChanged }) => {
    const [formData, setFormData] = useState({
        currentPassword: '',
        newPassword: '',
        confirmPassword: ''
    });
    const [showPasswords, setShowPasswords] = useState({
        current: false,
        new: false,
        confirm: false
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [fieldErrors, setFieldErrors] = useState({});

    // Strength meter state
    const [passwordStrength, setPasswordStrength] = useState(0);
    const [criteria, setCriteria] = useState({
        length: false,
        upper: false,
        lower: false,
        number: false,
        special: false
    });

    useEffect(() => {
        if (!isOpen) {
            setFormData({ currentPassword: '', newPassword: '', confirmPassword: '' });
            setError(null);
            setFieldErrors({});
            setPasswordStrength(0);
            setCriteria({ length: false, upper: false, lower: false, number: false, special: false });
        }
    }, [isOpen]);

    const handlePasswordChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));

        if (name === 'newPassword') {
            const newCriteria = {
                length: value.length >= 8,
                upper: /[A-Z]/.test(value),
                lower: /[a-z]/.test(value),
                number: /\d/.test(value),
                special: /[!@#$%^&*(),.?":{}|<>]/.test(value)
            };
            setCriteria(newCriteria);

            // Calculate strength 0-4
            const metCount = Object.values(newCriteria).filter(Boolean).length;
            setPasswordStrength(Math.max(0, metCount - 1));
        }

        if (error) setError(null);
        if (fieldErrors[name]) {
            setFieldErrors(prev => ({ ...prev, [name]: null }));
        }
    };

    const toggleShow = (field) => {
        setShowPasswords(prev => ({ ...prev, [field]: !prev[field] }));
    };

    const validate = () => {
        const errors = {};
        if (!formData.currentPassword) errors.currentPassword = 'Required';
        if (!formData.newPassword) errors.newPassword = 'Required';
        if (formData.newPassword !== formData.confirmPassword) {
            errors.confirmPassword = 'Passwords do not match';
        }
        if (formData.newPassword.length < 8) {
            errors.newPassword = 'Minimum 8 characters';
        }

        const metCount = Object.values(criteria).filter(Boolean).length;
        if (metCount < 4) { // Requiring at least 4 criteria for "Fair/Good"
            errors.newPassword = 'Password too weak';
        }

        setFieldErrors(errors);
        return Object.keys(errors).length === 0;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!validate()) return;

        setLoading(true);
        setError(null);
        try {
            await api.post(`/api/v1/employees/${empId}/change-password`, {
                current_password: formData.currentPassword,
                new_password: formData.newPassword
            });

            if (onPasswordChanged) onPasswordChanged();
            onClose();
        } catch (err) {
            console.error("Change password error:", err);
            const detail = err.response?.data?.detail;
            if (detail?.error?.fields) {
                setFieldErrors(detail.error.fields);
                setError(detail.error.message || 'Validation failed');
            } else {
                setError(typeof detail === 'string' ? detail : 'Failed to change password. Please try again.');
            }
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    const strengthLabels = ['Extremely Weak', 'Weak', 'Fair', 'Strong', 'Secure'];

    return (
        <div className="change-password-overlay" onClick={onClose}>
            <div className="change-password-modal-v4" onClick={e => e.stopPropagation()}>
                <button className="cp-close-btn-v4" onClick={onClose}><X size={20} /></button>

                <div className="cp-grid-inner-v4">
                    {/* Left Column: Info & Context */}
                    <div className="cp-col-left-v4">
                        <div className="cp-header-v4">
                            <div className="cp-icon-glow">
                                <Shield size={32} />
                            </div>
                            <h2>Secure Account</h2>
                            <p>Protect your identity with a strong, unique password.</p>
                        </div>

                        <div className="cp-security-card-v4">
                            <h4><ShieldCheck size={14} /> Security Tips</h4>
                            <ul>
                                <li>Use a combination of letters, numbers, and symbols.</li>
                                <li>Avoid using personal information like birthdays.</li>
                                <li>Never share your password with anyone.</li>
                            </ul>
                        </div>
                    </div>

                    {/* Right Column: Actions */}
                    <div className="cp-col-right-v4">
                        <form onSubmit={handleSubmit} className="cp-form-v4">
                            {error && (
                                <div className="cp-error-banner">
                                    <AlertTriangle size={18} />
                                    <span>{error}</span>
                                </div>
                            )}

                            <div className="cp-input-group">
                                <label><Lock size={14} /> Current Password</label>
                                <div className="cp-input-wrapper">
                                    <input
                                        type={showPasswords.current ? "text" : "password"}
                                        name="currentPassword"
                                        value={formData.currentPassword}
                                        onChange={handlePasswordChange}
                                        placeholder="Enter current password"
                                        autoComplete="current-password"
                                    />
                                    <button
                                        type="button"
                                        className="cp-password-toggle"
                                        onClick={() => toggleShow('current')}
                                    >
                                        {showPasswords.current ? <EyeOff size={16} /> : <Eye size={16} />}
                                    </button>
                                </div>
                                {fieldErrors.current_password && <span className="input-error-text" style={{ margin: '4px 0 0 4px' }}><AlertCircle size={12} /> {fieldErrors.current_password}</span>}
                            </div>

                            <div className="cp-input-row-v4">
                                <div className="cp-input-group">
                                    <label><RefreshCw size={14} /> New Password</label>
                                    <div className="cp-input-wrapper">
                                        <input
                                            type={showPasswords.new ? "text" : "password"}
                                            name="newPassword"
                                            value={formData.newPassword}
                                            onChange={handlePasswordChange}
                                            placeholder="8+ chars"
                                            autoComplete="new-password"
                                        />
                                        <button
                                            type="button"
                                            className="cp-password-toggle"
                                            onClick={() => toggleShow('new')}
                                        >
                                            {showPasswords.new ? <EyeOff size={16} /> : <Eye size={16} />}
                                        </button>
                                    </div>
                                    {fieldErrors.new_password && <span className="input-error-text" style={{ margin: '4px 0 0 4px' }}><AlertCircle size={12} /> {fieldErrors.new_password}</span>}
                                </div>

                                <div className="cp-input-group">
                                    <label><CheckCircle2 size={14} /> Confirm</label>
                                    <div className="cp-input-wrapper">
                                        <input
                                            type={showPasswords.confirm ? "text" : "password"}
                                            name="confirmPassword"
                                            value={formData.confirmPassword}
                                            onChange={handlePasswordChange}
                                            placeholder="Repeat"
                                            autoComplete="new-password"
                                        />
                                        <button
                                            type="button"
                                            className="cp-password-toggle"
                                            onClick={() => toggleShow('confirm')}
                                        >
                                            {showPasswords.confirm ? <EyeOff size={16} /> : <Eye size={16} />}
                                        </button>
                                    </div>
                                    {fieldErrors.confirmPassword && <span className="input-error-text" style={{ margin: '4px 0 0 4px' }}><AlertCircle size={12} /> {fieldErrors.confirmPassword}</span>}
                                </div>
                            </div>

                            {/* Strength & Criteria */}
                            <div className="cp-validation-section-v4">
                                <div className="cp-strength-meter">
                                    {[...Array(4)].map((_, i) => (
                                        <div
                                            key={i}
                                            className={`cp-dot ${i <= passwordStrength && formData.newPassword ? 'active' : ''} level-${passwordStrength}`}
                                        />
                                    ))}
                                    <span className={`cp-strength-text ${strengthLabels[passwordStrength].toLowerCase().split(' ').pop()}`}>
                                        {formData.newPassword ? strengthLabels[passwordStrength] : 'No Password'}
                                    </span>
                                </div>

                                <div className="cp-criteria-mini-v4">
                                    <div className={`cp-crit-chip ${criteria.length ? 'met' : ''}`}>8+ Chars</div>
                                    <div className={`cp-crit-chip ${criteria.upper ? 'met' : ''}`}>Upper</div>
                                    <div className={`cp-crit-chip ${criteria.lower ? 'met' : ''}`}>Lower</div>
                                    <div className={`cp-crit-chip ${criteria.number ? 'met' : ''}`}>Num</div>
                                    <div className={`cp-crit-chip ${criteria.special ? 'met' : ''}`}>Symbol</div>
                                </div>
                            </div>

                            <div className="cp-footer-v4">
                                <button
                                    type="submit"
                                    className="cp-btn-primary full-width"
                                    disabled={loading || !formData.newPassword || formData.newPassword !== formData.confirmPassword || passwordStrength < 2}
                                >
                                    {loading ? (
                                        <>
                                            <Loader2 className="spin" size={18} />
                                            <span>Updating...</span>
                                        </>
                                    ) : (
                                        <>
                                            <Shield size={18} />
                                            <span>Update Password</span>
                                        </>
                                    )}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ChangePasswordModal;
