// Redesigned Employee Details Modal V4
import React, { useState, useEffect, useCallback } from 'react';
import {
    X, User, Mail, Phone, Shield, UserCheck,
    CheckCircle2,
    AlertCircle, Link as LinkIcon, RotateCcw,
    Save, Check
} from 'lucide-react';
import './EmployeeDetailsModal.css';
import api from '../../utils/api';
import { addNotification } from '../../utils/notificationUtils';
import {
    handleDrawerCancelEdit,
    shouldCloseDrawerAfterSave,
} from '../../utils/drawerEditFlow';
import {
    AppDrawerModalFooter,
    AppDrawerBtnDelete,
    AppDrawerBtnCancel,
    AppDrawerBtnSave,
} from '../common/AppDrawerEditFooter';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import { hasPermission } from '../../utils/rbac';

const EmployeeDetailsModal = ({ isOpen, onClose, empId, initialEditMode = false, onUpdated }) => {
    const [employee, setEmployee] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [editMode, setEditMode] = useState(initialEditMode);
    const [formData, setFormData] = useState({});
    const [managers, setManagers] = useState([]);
    const [roles, setRoles] = useState([]);
    const [message, setMessage] = useState({ type: '', text: '' });
    const [fieldErrors, setFieldErrors] = useState({});
    const [subLoading, setSubLoading] = useState(false);
    const [confirmStatus, setConfirmStatus] = useState({ show: false, action: null });

    const fetchData = useCallback(async () => {
        if (!empId) return;
        setLoading(true);
        setError(null);

        try {
            const [empRes, rolesRes, managersRes] = await Promise.allSettled([
                api.get(`/api/v1/employees/employee/${empId}`),
                api.get(`/api/v1/employees/roles`),
                api.get(`/api/v1/employees/filter?is_active=true&limit=100`),
            ]);

            if (empRes.status === 'fulfilled') {
                setEmployee(empRes.value.data);
                setFormData(empRes.value.data);
            } else {
                setError("Employee not found");
            }

            if (rolesRes.status === 'fulfilled') {
                setRoles(rolesRes.value.data || []);
            }

            if (managersRes.status === 'fulfilled') {
                const managerRoles = ['ADMIN', 'SALES_MANAGER', 'OP_MANAGER'];
                setManagers((managersRes.value.data || []).filter(m => managerRoles.includes(m.role)));
            }

        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [empId]);

    useEffect(() => {
        if (isOpen && empId) {
            setEditMode(initialEditMode);
            fetchData();
            document.body.style.overflow = 'hidden';
        } else {
            setEditMode(false);
            document.body.style.overflow = 'unset';
        }
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, empId, initialEditMode, fetchData]);

    useEffect(() => {
        if (isOpen && initialEditMode) setEditMode(true);
    }, [isOpen, initialEditMode]);

    const handleCancelEdit = () => {
        handleDrawerCancelEdit({
            initialEditMode,
            onClose,
            setEditMode,
            resetEditState: () => {
                setFormData(employee || {});
                setMessage({ type: '', text: '' });
                setFieldErrors({});
            },
        });
    };

    const isEditing = editMode || initialEditMode;
    const showEditFooter = isEditing;

    const validateField = (name, value) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        switch (name) {
            case 'username':
                if (!trimmedValue) errorMsg = 'field required';
                break;
            case 'email':
                if (!trimmedValue) errorMsg = 'field required';
                else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedValue)) errorMsg = 'Invalid email format';
                break;
            case 'first_name':
            case 'last_name':
                if (!trimmedValue) errorMsg = 'field required';
                break;
            case 'phone_number':
                if (trimmedValue && !/^\d{10}$/.test(trimmedValue)) errorMsg = '10 digits required';
                break;
            default:
                break;
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return !errorMsg;
    };

    const validateForm = () => {
        const fieldsToValidate = ['username', 'email', 'first_name', 'last_name', 'phone_number', 'role'];
        let isValid = true;
        fieldsToValidate.forEach(field => {
            if (!validateField(field, formData[field])) {
                isValid = false;
            }
        });
        return isValid;
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        validateField(name, value);
        if (message.text) setMessage({ type: '', text: '' });
    };

    const handleSave = async () => {
        if (!validateForm()) {
            setMessage({ type: 'error', text: 'Please correct the highlighted fields.' });
            return;
        }
        setFieldErrors({});
        setMessage({ type: '', text: '' });
        setSubLoading(true);
        try {
            // Filter only allowed fields to avoid "Extra inputs not permitted" error from strict backend validation
            const allowedFields = [
                'username', 'email', 'first_name', 'last_name', 
                'phone_number', 'role', 'manager_emp_id'
            ];
            
            const filteredData = {};
            allowedFields.forEach(field => {
                if (formData[field] !== undefined) {
                    filteredData[field] = formData[field];
                }
            });

            const updatePayload = {
                ...filteredData,
                manager_emp_id: formData.manager_emp_id ? parseInt(formData.manager_emp_id) : null,
            };
            
            await api.post(`/api/v1/employees/${empId}/emp_dyn/edit`, updatePayload);
            setMessage({ type: 'success', text: 'Profile updated successfully! ✨' });
            if (onUpdated) onUpdated();
            if (shouldCloseDrawerAfterSave(initialEditMode)) {
                onClose();
                return;
            }
            setEditMode(false);
            await fetchData();
        } catch (err) {
            if (err.fields) setFieldErrors(err.fields);
            setMessage({ type: 'error', text: err.message || 'Update failed' });
        } finally {
            setSubLoading(false);
        }
    };

    const handleToggleStatus = (activate) => {
        setConfirmStatus({ show: true, action: activate });
    };

    const executeToggleStatus = async () => {
        const activate = confirmStatus.action;
        setSubLoading(true);
        try {
            await api.post(`/api/v1/employees/${empId}/emp_dyn/edit`, { is_active: activate });
            setMessage({ type: 'success', text: `Employee ${activate ? 'activated' : 'deactivated'} successfully!` });
            setConfirmStatus({ show: false, action: null });
            await fetchData();
            if (onUpdated) onUpdated();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setSubLoading(false);
        }
    };

    const DetailsSkeleton = () => (
        <div className="form-content">
            {[1, 2, 3].map(s => (
                <div key={s} className="form-section-v4" style={{ marginBottom: '32px' }}>
                    <div className="skeleton-box" style={{ width: '150px', height: '12px', marginBottom: '16px' }} />
                    <div className="form-grid-3">
                        {[1, 2, 3].map(i => (
                            <div key={i} className="form-group-v4">
                                <div className="skeleton-box" style={{ width: '80px', height: '10px', marginBottom: '8px' }} />
                                <div className="skeleton-box" style={{ height: '42px' }} />
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );

    if (!isOpen) return null;

    return (
        <div className="modal-overlay app-side-drawer-mode" onClick={onClose}>
            <div className="modal-content-glass employee-details-modal gst-reg-side-drawer-shell app-drawer-panel" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                        <div className="header-header-top">
                            <div className="header-icon-box-v4">
                                <User size={20} />
                            </div>
                            <div className="modal-title-box">
                                <h1 className="modal-title-v4">
                                    {employee?.first_name ? `${employee.first_name} ${employee.last_name || ''}` : 'Employee Profile'}
                                    <span className={`header-badge-v4 ${isEditing ? 'edit-mode' : 'view-mode'}`}>
                                        {isEditing ? 'EDITING' : 'VIEWING'}
                                    </span>
                                </h1>
                                <p className="modal-subtitle-v4">ID: {empId} • {employee?.role || 'Member'}</p>
                            </div>
                        </div>
                        <button className="modal-close-btn" onClick={onClose} aria-label="Close">
                            <X size={20} />
                        </button>
                    </div>

                    <div className="card-scroll">
                        {loading ? (
                            <DetailsSkeleton />
                        ) : error ? (
                            <div className="form-content">
                                <div className="form-error-banner-v2">
                                    <AlertCircle size={18} />
                                    <span>{error}</span>
                                </div>
                            </div>
                        ) : (
                            <div className="form-content">
                                {message.text && (
                                    <div className={`employee-message-banner ${message.type === 'success' ? 'success' : 'error'}`} style={{ margin: '0 0 4px' }}>
                                        {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                                        <span className="employee-message-banner-text">{message.text}</span>
                                    </div>
                                )}

                                {/* Section 1: Identity & Credentials */}
                                <div className="form-section-v4">
                                    <h3 className="section-title">Identity & Credentials</h3>
                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Username</label>
                                            {editMode ? (
                                                <input name="username" className="modal-input-v4" value={formData.username || ''} onChange={handleChange} />
                                            ) : (
                                                <div className="form-value-box-v4">{employee?.username}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Email Address</label>
                                            {editMode ? (
                                                <input name="email" className="modal-input-v4" value={formData.email || ''} onChange={handleChange} />
                                            ) : (
                                                <div className="form-value-box-v4">{employee?.email}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Section 2: Professional Profile */}
                                <div className="form-section-v4">
                                    <h3 className="section-title">Professional Profile</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">First Name</label>
                                            {editMode ? (
                                                <input name="first_name" className="modal-input-v4" value={formData.first_name || ''} onChange={handleChange} />
                                            ) : (
                                                <div className="form-value-box-v4">{employee?.first_name || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Last Name</label>
                                            {editMode ? (
                                                <input name="last_name" className="modal-input-v4" value={formData.last_name || ''} onChange={handleChange} />
                                            ) : (
                                                <div className="form-value-box-v4">{employee?.last_name || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Contact Phone</label>
                                            {editMode ? (
                                                <input name="phone_number" className="modal-input-v4" value={formData.phone_number || ''} onChange={handleChange} />
                                            ) : (
                                                <div className="form-value-box-v4">{employee?.phone_number || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Role</label>
                                            {editMode && hasPermission('USER_ACCESS', 'WRITE') ? (
                                                <FormCustomSelect
                                                    name="role"
                                                    value={formData.role || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs(roles.map((r) => ({ value: r.role_code, label: r.role_code })))}
                                                    placeholder="Select role"
                                                    ariaLabel="Role"
                                                />
                                            ) : (
                                                <div className="form-value-box-v4">{employee?.role}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Section 3: Hierarchy & Reporting */}
                                <div className="form-section-v4">
                                    <h3 className="section-title">Hierarchy & Reporting</h3>
                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Reporting Manager</label>
                                            {editMode ? (
                                                <div className="form-group-v4">
                                                    <FormCustomSelect
                                                        name="manager_emp_id"
                                                        value={formData.manager_emp_id || ''}
                                                        onChange={handleChange}
                                                        options={optionsFromPairs([
                                                            { value: '', label: 'No Manager (Direct Report)' },
                                                            ...managers.map((m) => ({
                                                                value: m.emp_id,
                                                                label: `${m.username} (${m.role})`,
                                                            })),
                                                        ])}
                                                        placeholder="No Manager (Direct Report)"
                                                        ariaLabel="Reporting manager"
                                                        error={Boolean(fieldErrors.manager_emp_id)}
                                                    />
                                                    {fieldErrors.manager_emp_id && (
                                                        <span className="field-error-v2">{fieldErrors.manager_emp_id}</span>
                                                    )}
                                                </div>
                                            ) : (
                                                <div className="form-value-box-v4">
                                                    {employee?.manager_username ? `${employee.manager_username} (${employee.manager_role})` : 'Direct Report'}
                                                </div>
                                            )}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Account Status</label>
                                            {editMode ? (
                                                <div className="status-toggle-wrapper-v4" onClick={() => setFormData(prev => ({ ...prev, is_active: !prev.is_active }))}>
                                                    <div className={`status-toggle-track ${formData.is_active ? 'active' : ''}`}>
                                                        <div className="status-toggle-thumb">
                                                            {formData.is_active ? <Check size={10} /> : <X size={10} />}
                                                        </div>
                                                    </div>
                                                    <span className="status-toggle-label">{formData.is_active ? 'Account Active' : 'Account Inactive'}</span>
                                                </div>
                                            ) : (
                                                <div className="form-value-box-v4">
                                                    <span className={`status-badge ${employee?.is_active ? 'active' : 'inactive'}`}>
                                                        {employee?.is_active ? 'ACTIVE' : 'INACTIVE'}
                                                    </span>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    {error && !showEditFooter && (
                        <AppDrawerModalFooter>
                            <AppDrawerBtnCancel onClick={onClose}>Close</AppDrawerBtnCancel>
                        </AppDrawerModalFooter>
                    )}

                    {showEditFooter && !loading && (
                        <AppDrawerModalFooter>
                            {hasPermission('EMPLOYEE', 'DELETE') && employee?.is_active && (
                                <AppDrawerBtnDelete onClick={() => handleToggleStatus(false)} disabled={subLoading || loading}>
                                    Deactivate
                                </AppDrawerBtnDelete>
                            )}
                            {hasPermission('EMPLOYEE', 'WRITE') && !employee?.is_active && (
                                <AppDrawerBtnSave
                                    onClick={() => handleToggleStatus(true)}
                                    icon={Check}
                                    label="Activate Account"
                                    disabled={loading}
                                />
                            )}
                            <AppDrawerBtnCancel onClick={handleCancelEdit} disabled={subLoading || loading} />
                            <AppDrawerBtnSave
                                onClick={handleSave}
                                loading={subLoading}
                                disabled={loading}
                                icon={Save}
                            />
                        </AppDrawerModalFooter>
                    )}
                {confirmStatus.show && (
                    <div className="confirm-modal-overlay">
                        <div className="confirm-modal-content">
                            <div className="confirm-icon-wrapper">
                                <AlertCircle size={32} color={confirmStatus.action ? "var(--accent)" : "var(--danger)"} />
                            </div>
                            <h2 style={{ color: 'var(--text-primary)', marginBottom: '12px' }}>Confirm Action</h2>
                            <p style={{ color: 'var(--text-primary)', marginBottom: '32px' }}>
                                Are you sure you want to <strong>{confirmStatus.action ? 'activate' : 'deactivate'}</strong> this employee account?
                            </p>
                            <div style={{ display: 'flex', gap: '16px', justifyContent: 'center' }}>
                                <button className="btn-secondary-link" onClick={() => setConfirmStatus({ show: false, action: null })} disabled={subLoading}>Cancel</button>
                                <button 
                                    className={confirmStatus.action ? "btn-primary-glow" : "btn-danger-glass"} 
                                    onClick={executeToggleStatus}
                                    disabled={subLoading}
                                >
                                    {subLoading ? <RotateCcw size={16} className="refresh-spin" color={confirmStatus.action ? "var(--text-inverse)" : "var(--danger)"} /> : null}
                                    <span>{subLoading ? 'Processing...' : 'Confirm Action'}</span>
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default EmployeeDetailsModal;
