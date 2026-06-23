import React, { useState, useEffect, useCallback } from 'react';
import { X, User, Mail, Lock, Phone, Shield, UserCheck, CheckCircle2, Eye, EyeOff, Check, AlertCircle, UserPlus } from 'lucide-react';
import api from '../../utils/api';
import './AddEmployeeModal.css';
import { addNotification } from '../../utils/notificationUtils';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';

const AddEmployeeModal = ({ isOpen, onClose, onSuccess }) => {
    const [formData, setFormData] = useState({
        username: '',
        email: '',
        password: '',
        confirm_password: '', // Kept for frontend validation
        first_name: '',
        last_name: '',
        phone_number: '',
        role: '',
        manager_emp_id: '',
    });

    const [managers, setManagers] = useState([]);
    const [roles, setRoles] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [successMessage, setSuccessMessage] = useState('');
    const [fieldErrors, setFieldErrors] = useState({});
    const [isSuccess, setIsSuccess] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);
    const [passwordStrength, setPasswordStrength] = useState(0);
    const [passwordCriteria, setPasswordCriteria] = useState({
        length: false,
        upper: false,
        lower: false,
        number: false,
        special: false
    });

    // Email Verification States
    const [isEmailVerified, setIsEmailVerified] = useState(false);
    const [showOTPInput, setShowOTPInput] = useState(false);
    const [otp, setOtp] = useState('');
    const [verificationLoading, setVerificationLoading] = useState(false);
    const [verificationStatus, setVerificationStatus] = useState({ type: '', message: '' });

    const fetchManagers = useCallback(async () => {
        try {
            const response = await api.get(`/api/v1/employees/filter?is_active=true&limit=100`);
            const managerRoles = ['ADMIN', 'SALES_MANAGER', 'OP_MANAGER'];
            const filteredManagers = response.data.filter(emp => managerRoles.includes(emp.role));
            setManagers(filteredManagers);
        } catch (err) {
            console.error('Failed to fetch managers:', err);
        }
    }, []);

    const fetchRoles = useCallback(async () => {
        try {
            const response = await api.get(`/api/v1/employees/roles`);
            setRoles(Array.isArray(response.data) ? response.data : []);
        } catch (err) {
            console.error('Failed to fetch roles:', err);
        }
    }, []);

    useEffect(() => {
        if (isOpen) {
            fetchManagers();
            fetchRoles();
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'unset';
            // Reset verification states
            setIsEmailVerified(false);
            setShowOTPInput(false);
            setOtp('');
            setVerificationStatus({ type: '', message: '' });
            setSuccessMessage('');
        }
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, fetchManagers, fetchRoles]);

    const handleSendOTP = async () => {
        if (!formData.email || fieldErrors.email) {
            setError('Enter a valid email before verification');
            return;
        }

        setVerificationLoading(true);
        setError('');
        setSuccessMessage('');
        try {
            await api.post('/app/v1/email-verification/request', { email: formData.email });
            setShowOTPInput(true);
            setSuccessMessage('OTP sent to your email');
        } catch (err) {
            // If email is already verified, allow user to proceed
            if (err.message === 'Email already verified and you can proceed with Onboarding') {
                setIsEmailVerified(true);
                setShowOTPInput(false);
                setSuccessMessage('Email already verified. You can proceed!');
                setError('');
            } else {
                setError(err.message || 'Failed to send OTP');
            }
        } finally {
            setVerificationLoading(false);
        }
    };

    const handleVerifyOTP = async () => {
        if (!otp || otp.length !== 6) {
            setError('Please enter the 6-digit OTP code');
            return;
        }

        setVerificationLoading(true);
        setError('');
        try {
            await api.post('/app/v1/email-verification/verify', { email: formData.email, otp });
            setIsEmailVerified(true);
            setShowOTPInput(false);
            setSuccessMessage('Email verified successfully!');
        } catch (err) {
            setError(err.message || 'Verification failed');
        } finally {
            setVerificationLoading(false);
        }
    };

    const validateField = (name, value) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        switch (name) {
            case 'username':
                if (!trimmedValue) errorMsg = 'field required';
                else if (trimmedValue.length > 100) errorMsg = 'Maximum 100 characters';
                break;
            case 'email':
                if (!trimmedValue) errorMsg = 'field required';
                else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedValue)) errorMsg = 'Invalid email format';
                // Reset verification if email changes
                setIsEmailVerified(false);
                setShowOTPInput(false);
                setSuccessMessage('');
                break;
            case 'password':
                if (!value) errorMsg = 'field required';
                else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>])/.test(value)) errorMsg = 'Need Upper, Lower, Num & Special';
                else {
                    const hasUpper = /[A-Z]/.test(value);
                    const hasLower = /[a-z]/.test(value);
                    const hasNumber = /\d/.test(value);
                    if (!hasUpper || !hasLower || !hasNumber) {
                        errorMsg = 'Must include uppercase, lowercase, and number';
                    }
                }
                break;
            case 'confirm_password':
                if (!value) errorMsg = 'field required';
                else if (value !== formData.password) {
                    errorMsg = 'password not matched';
                    setError('Passwords do not match');
                }
                break;
            case 'first_name':
                if (!trimmedValue) errorMsg = 'field required';
                else if (trimmedValue.length > 100) errorMsg = 'Maximum 100 characters';
                break;
            case 'last_name':
                if (!trimmedValue) errorMsg = 'field required';
                else if (trimmedValue.length > 100) errorMsg = 'Maximum 100 characters';
                break;
            case 'phone_number':
                if (!trimmedValue) errorMsg = 'field required';
                else if (!/^\d{10}$/.test(trimmedValue)) errorMsg = '10 digits required';
                break;
            case 'role':
                if (!value) errorMsg = 'field required';
                break;
            case 'manager_emp_id':
                if (value && parseInt(value) <= 0) errorMsg = 'Invalid manager ID';
                break;
            default:
                break;
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return !errorMsg;
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));

        validateField(name, value);
        if (error) setError('');
        if (successMessage) setSuccessMessage('');

        if (name === 'password') {
            const criteria = {
                length: value.length >= 8,
                upper: /[A-Z]/.test(value),
                lower: /[a-z]/.test(value),
                number: /\d/.test(value),
                special: /[!@#$%^&*(),.?":{}|<>]/.test(value)
            };
            setPasswordCriteria(criteria);

            // Calculate strength (0-4)
            const strength = Object.values(criteria).filter(Boolean).length - 1;
            setPasswordStrength(Math.max(0, strength));
        }
    };

    const validateForm = () => {
        const { username, email, password, confirm_password, phone_number, first_name, last_name, role } = formData;
        let errors = {};

        if (!username.trim()) errors.username = 'Username is required';
        if (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = 'Valid email is required';
        if (password.length < 8) {
            errors.password = 'Password (min 8 chars)';
        } else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>])/.test(password)) {
            errors.password = 'Need Upper, Lower, Num & Special';
        }
        if (password !== confirm_password) errors.confirm_password = 'Passwords do not match';
        if (!first_name.trim()) errors.first_name = 'First Name is required';
        if (!last_name.trim()) errors.last_name = 'Last Name is required';
        if (phone_number && !/^\d{10}$/.test(phone_number)) errors.phone_number = '10 digits required';
        if (!role) errors.role = 'Role is required';

        if (!isEmailVerified) {
            errors.email = 'Email verification required';
        }

        setFieldErrors(errors);
        return Object.keys(errors).length === 0;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!isEmailVerified) {
            setError('Please verify your email address first.');
            return;
        }
        if (!validateForm()) return;

        setFieldErrors({});
        setError('');
        setLoading(true);

        try {
            const payload = {
                username: formData.username.trim(),
                email: formData.email.trim().toLowerCase(),
                password: formData.password,
                first_name: formData.first_name.trim() || null,
                last_name: formData.last_name.trim() || null,
                phone_number: formData.phone_number.trim() || null,
                role: formData.role,
                manager_emp_id:
                    formData.manager_emp_id !== '' && formData.manager_emp_id !== null && formData.manager_emp_id !== undefined
                        ? parseInt(formData.manager_emp_id)
                        : null,
            };

            await api.post(`/app/v1/signup`, payload);

            // Log notification to localStorage
            addNotification(
                'New Employee Created',
                `Employee ${formData.first_name} ${formData.last_name} (${formData.role}) was added successfully.`,
                'CREATE'
            );

            setIsSuccess(true);
            setTimeout(() => {
                onSuccess();
            }, 2000);
        } catch (err) {
            // First priority: Use structured field errors from api.js
            if (err.fields && Object.keys(err.fields).length > 0) {
                // Show banner message with line breaks while still highlighting fields
                const combinedMessage = Object.values(err.fields).join('\n');
                setFieldErrors(err.fields); // highlight fields in red
                setError(combinedMessage);
                return;
            }

            setError(err.message || 'Registration failed');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="modal-overlay app-side-drawer-mode">
            <div className="modal-content-glass employee-modal">
                {isSuccess ? (
                    <div className="modal-success-state">
                        <div className="success-icon-wrapper">
                            <CheckCircle2 size={48} className="success-tick" />
                        </div>
                        <h2>Employee Created!</h2>
                        <p style={{ color: 'var(--text-primary)', marginTop: '8px' }}>The account has been successfully registered.</p>
                    </div>
                ) : (
                    <>
                        <div className="modal-header">
                            <div className="header-header-top">
                                <div className="header-icon-box-v4">
                                    <UserPlus size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <h1 className="modal-title-v4">
                                        New Employee <span className="header-badge-v4 create-mode">CREATE</span>
                                    </h1>
                                    <p className="modal-subtitle-v4">Register a new member to the workspace</p>
                                </div>
                            </div>
                            <button className="modal-close-btn" onClick={onClose} aria-label="Close">
                                <X size={20} />
                            </button>
                        </div>

                        <form onSubmit={handleSubmit} className="modal-form-v4">
                            {error && (
                                <div className="form-error-banner-v2" style={{ whiteSpace: 'pre-line' }}>
                                    <AlertCircle size={18} />
                                    <span>{error}</span>
                                </div>
                            )}

                            {successMessage && (
                                <div className="form-success-banner-v2">
                                    <CheckCircle2 size={18} />
                                    <span>{successMessage}</span>
                                </div>
                            )}

                            <div className="form-sections-container">
                                {/* Section 1: Identity & Security */}
                                <div className="form-section-v4">
                                    <h3 className="section-title">Identity & Security</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Username *</label>
                                            <div className="input-wrapper">
                                                <User size={14} className="input-icon" />
                                                <input
                                                    type="text"
                                                    name="username"
                                                    className={`modal-input-v4 ${fieldErrors.username ? 'error' : ''}`}
                                                    placeholder="e.g. johndoe"
                                                    value={formData.username}
                                                    onChange={handleChange}
                                                    required
                                                />
                                            </div>
                                            {fieldErrors.username && <div className="field-error-msg">{fieldErrors.username}</div>}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Email Address *</label>
                                            <div className="input-wrapper">
                                                <Mail size={14} className="input-icon" />
                                                <input
                                                    type="email"
                                                    name="email"
                                                    className={`modal-input-v4 ${fieldErrors.email ? 'error' : ''}`}
                                                    placeholder="john@example.com"
                                                    value={formData.email}
                                                    onChange={handleChange}
                                                    required
                                                    disabled={isEmailVerified}
                                                />
                                                {isEmailVerified ? (
                                                    <div className="verified-badge">
                                                        <CheckCircle2 size={12} />
                                                        <span>Verified</span>
                                                    </div>
                                                ) : formData.email ? (
                                                    <button
                                                        type="button"
                                                        className="verify-btn"
                                                        onClick={handleSendOTP}
                                                        disabled={verificationLoading || fieldErrors.email}
                                                    >
                                                        {verificationLoading ? '...' : 'Verify'}
                                                    </button>
                                                ) : null}
                                            </div>
                                            {fieldErrors.email && <div className="field-error-msg">{fieldErrors.email}</div>}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Password *</label>
                                            <div className="input-wrapper">
                                                <Lock size={14} className="input-icon" />
                                                <input
                                                    type={showPassword ? "text" : "password"}
                                                    name="password"
                                                    className={`modal-input-v4 ${fieldErrors.password ? 'error' : ''}`}
                                                    placeholder="••••••••"
                                                    value={formData.password}
                                                    onChange={handleChange}
                                                    required
                                                />
                                                <button
                                                    type="button"
                                                    className="password-toggle"
                                                    onClick={() => setShowPassword(!showPassword)}
                                                >
                                                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                                                </button>
                                            </div>
                                            {fieldErrors.password && <div className="field-error-msg">{fieldErrors.password}</div>}
                                        </div>

                                        {!isEmailVerified && showOTPInput && (
                                            <div className="otp-verification-container">
                                                <div className="otp-header">
                                                    <Shield size={14} style={{ color: '#2eb87a' }} />
                                                    <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>Enter 6-digit OTP</span>
                                                </div>
                                                <div className="otp-input-group" style={{ display: 'flex', gap: '12px' }}>
                                                    <input
                                                        type="text"
                                                        className="modal-input-v4"
                                                        style={{ width: '120px', textAlign: 'center', letterSpacing: '4px' }}
                                                        placeholder="000000"
                                                        maxLength="6"
                                                        value={otp}
                                                        onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                                                    />
                                                    <button
                                                        type="button"
                                                        className="btn-primary-glow"
                                                        style={{ padding: '8px 20px', fontSize: '12px' }}
                                                        onClick={handleVerifyOTP}
                                                        disabled={verificationLoading || otp.length !== 6}
                                                    >
                                                        {verificationLoading ? '...' : 'Confirm'}
                                                    </button>
                                                </div>
                                            </div>
                                        )}

                                        <div className="password-feedback-area">
                                            <div className="strength-meter">
                                                {[...Array(5)].map((_, i) => (
                                                    <div
                                                        key={i}
                                                        className={`strength-dot ${i <= passwordStrength && formData.password ? 'active' : ''} level-${passwordStrength}`}
                                                    />
                                                ))}
                                                <span className="modal-label-caps" style={{ marginLeft: 'auto' }}>
                                                    {!formData.password ? '' : passwordStrength <= 1 ? 'Weak' : passwordStrength === 2 ? 'Fair' : 'Strong'}
                                                </span>
                                            </div>

                                            <div className="criteria-grid">
                                                <div className={`criteria-item ${passwordCriteria.length ? 'met' : ''}`}>
                                                    {passwordCriteria.length ? <Check size={10} /> : <AlertCircle size={10} />}
                                                    8+ chars
                                                </div>
                                                <div className={`criteria-item ${passwordCriteria.upper ? 'met' : ''}`}>
                                                    {passwordCriteria.upper ? <Check size={10} /> : <AlertCircle size={10} />}
                                                    Uppercase
                                                </div>
                                                <div className={`criteria-item ${passwordCriteria.lower ? 'met' : ''}`}>
                                                    {passwordCriteria.lower ? <Check size={10} /> : <AlertCircle size={10} />}
                                                    Lowercase
                                                </div>
                                                <div className={`criteria-item ${passwordCriteria.number ? 'met' : ''}`}>
                                                    {passwordCriteria.number ? <Check size={10} /> : <AlertCircle size={10} />}
                                                    Number
                                                </div>
                                                <div className={`criteria-item ${passwordCriteria.special ? 'met' : ''}`}>
                                                    {passwordCriteria.special ? <Check size={10} /> : <AlertCircle size={10} />}
                                                    Special
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {/* Section 2: Professional Profile */}
                                <div className="form-section-v4">
                                    <h3 className="section-title">Professional Profile</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">First Name *</label>
                                            <input
                                                type="text"
                                                name="first_name"
                                                className={`modal-input-v4 ${fieldErrors.first_name ? 'error' : ''}`}
                                                placeholder="e.g. John"
                                                value={formData.first_name}
                                                onChange={handleChange}
                                                required
                                            />
                                            {fieldErrors.first_name && <div className="field-error-msg">{fieldErrors.first_name}</div>}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Last Name *</label>
                                            <input
                                                type="text"
                                                name="last_name"
                                                className={`modal-input-v4 ${fieldErrors.last_name ? 'error' : ''}`}
                                                placeholder="e.g. Doe"
                                                value={formData.last_name}
                                                onChange={handleChange}
                                                required
                                            />
                                            {fieldErrors.last_name && <div className="field-error-msg">{fieldErrors.last_name}</div>}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Contact Number</label>
                                            <div className="input-wrapper">
                                                <Phone size={14} className="input-icon" />
                                                <input
                                                    type="tel"
                                                    name="phone_number"
                                                    className={`modal-input-v4 ${fieldErrors.phone_number ? 'error' : ''}`}
                                                    placeholder="10 digit mobile"
                                                    value={formData.phone_number}
                                                    onChange={handleChange}
                                                />
                                            </div>
                                            {fieldErrors.phone_number && <div className="field-error-msg">{fieldErrors.phone_number}</div>}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Role Selection *</label>
                                            <div className="input-wrapper">
                                                <Shield size={14} className="input-icon" />
                                                <FormCustomSelect
                                                    name="role"
                                                    value={formData.role}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs([
                                                        { value: '', label: 'Select Role' },
                                                        ...roles.map((r) => ({ value: r.role_code, label: r.role_code })),
                                                    ])}
                                                    placeholder="Select Role"
                                                    ariaLabel="Role"
                                                    error={Boolean(fieldErrors.role)}
                                                />
                                            </div>
                                            {fieldErrors.role && <div className="field-error-msg">{fieldErrors.role}</div>}
                                        </div>
                                    </div>
                                </div>

                                {/* Section 3: Reporting */}
                                <div className="form-section-v4">
                                    <h3 className="section-title">Reporting</h3>
                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Reporting Manager</label>
                                            <div className="input-wrapper">
                                                <UserCheck size={14} className="input-icon" />
                                                <FormCustomSelect
                                                    name="manager_emp_id"
                                                    value={formData.manager_emp_id}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs([
                                                        { value: '', label: 'Direct Report (No Manager)' },
                                                        ...managers.map((m) => ({
                                                            value: m.emp_id,
                                                            label: `${m.username} (${m.role})`,
                                                        })),
                                                    ])}
                                                    placeholder="Direct Report (No Manager)"
                                                    ariaLabel="Reporting manager"
                                                    error={Boolean(fieldErrors.manager_emp_id)}
                                                />
                                            </div>
                                            {fieldErrors.manager_emp_id && <div className="field-error-msg">{fieldErrors.manager_emp_id}</div>}
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer">
                                <button type="button" className="btn-secondary-link" onClick={onClose}>Cancel</button>
                                <button
                                    type="submit"
                                    className="btn-primary-glow"
                                    disabled={loading || !isEmailVerified}
                                >
                                    {loading ? 'Processing...' : 'Create Employee Account'}
                                </button>
                            </div>
                        </form>
                    </>
                )}
            </div>
        </div>
    );
};

export default AddEmployeeModal;
