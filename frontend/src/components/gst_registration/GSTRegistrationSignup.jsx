/**
 * @file GSTRegistrationSignup.jsx
 * @description Renders the comprehensive form for establishing a new GST Registration.
 * Collects business credentials, jurisdictional paths, and associates with a parent customer.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './GSTRegistrationSignup.css';
import api from '../../utils/api';
import {
    getRmOpAssignmentVisibility,
    resolveRmIdForPayload,
    resolveOpIdForPayload,
} from '../../utils/rmOpAssignmentFields';
import {
    fetchActiveRmOpEmployeeLists,
    buildRmOpSelectOptions,
} from '../../utils/activeEmployees';
import { X, AlertCircle, CheckCircle2, RotateCcw, ChevronDown, User, Plus, Users, FileText } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig, optionsFromPairs } from '../common/selectOptionUtils';

const BASE_URL = import.meta.env.VITE_API_URL;

const extractGstRegistrationError = (err) => {
    const detail = err?.response?.data?.detail;
    if (detail && typeof detail === 'object' && detail.error && detail.error.fields) {
        const fields = detail.error.fields || {};
        const messages = Object.values(fields).filter(Boolean);
        if (messages.length) return messages.join('\n');
        if (detail.error.message) return detail.error.message;
    }
    if (Array.isArray(detail)) {
        const first = detail[0];
        const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : 'field';
        if (first?.type === 'missing' || String(first?.msg || '').toLowerCase().includes('field required')) {
            return `${String(field).replace(/_/g, ' ')} is required.`;
        }
        return first?.msg || 'Validation failed.';
    }
    if (typeof detail === 'string') return detail;
    return err?.message || 'Request failed.';
};

const GSTRegistrationSignup = ({ isOpen = true, onClose, onSuccess, profileData }) => {
    const { showRmField, showOpField } = getRmOpAssignmentVisibility(profileData);
    const initialFormData = {
        customer_id: '',
        username: '',
        password: '',
        pan: '',
        gstin: '',
        business_name: '',
        registration_type: '',
        ownership_category: '',
        business_type: '',
        state: '',
        turnover_details: '',
        registration_status: 'DRAFT',
        suspension_reason: '',
        cancellation_reason: '',
        is_rcm_applicable: false,
        is_filing_needed: true,
        mobile: '',
        email: '',
        secondary_email: '',
        rm_id: '',
        created_by: '',
        filing_preference: '',
        language: '',
        client_name: '',
        referral_phone_number: '',
    };

    const [formData, setFormData] = useState(initialFormData);

    const [registrationTypes, setRegistrationTypes] = useState([]);
    const [ownershipCategories, setOwnershipCategories] = useState([]);
    const [businessTypes, setBusinessTypes] = useState([]);
    const [states, setStates] = useState([]);
    const [turnoverDetailsList, setTurnoverDetailsList] = useState([]);
    const [registrationStatuses, setRegistrationStatuses] = useState([]);
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [languages, setLanguages] = useState([]);
    const [loading, setLoading] = useState(false);

    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);
    const [fieldErrors, setFieldErrors] = useState({});
    const navigate = useNavigate();
    const closeModal = onClose || (() => navigate('/dashboard?tab=gst&sub=registrations'));

    useEffect(() => {
        if (!isOpen) return;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) return;
        setSuccess(false);
        setError('');
        setLoading(false);
        setFormData(initialFormData);
    }, [isOpen]);

    useEffect(() => {
        const fetchConfigs = async () => {
            const configs = [
                { url: `/api/v1/gst-registration/config/REGISTRATION_TYPE`, setter: setRegistrationTypes },
                { url: `/api/v1/gst-registration/config/OWNERSHIP_CATEGORY`, setter: setOwnershipCategories },
                { url: `/api/v1/gst-registration/config/BUSINESS_TYPE`, setter: setBusinessTypes },
                { url: `/api/v1/gst-registration/config/STATE`, setter: setStates },
                { url: `/api/v1/gst-registration/config/TURNOVER_DETAILS`, setter: setTurnoverDetailsList },
                { url: `/api/v1/gst-registration/config/REGISTRATION_STATUS`, setter: setRegistrationStatuses },
                { url: `/api/v1/gst-registration/config/LANGUAGE`, setter: setLanguages }
            ];

            for (const config of configs) {
                try {
                    const response = await api.get(config.url);
                    const data = response.data?.items || response.data?.data || response.data || [];
                    config.setter(Array.isArray(data) ? data : []);
                } catch (err) {
                    console.error(`Failed to fetch config from ${config.url}:`, err);
                }
            }

            try {
                const { activeRMs, activeOps } = await fetchActiveRmOpEmployeeLists();
                setActiveRMs(activeRMs);
                setActiveOps(activeOps);
            } catch (err) {
                console.error('Failed to fetch active RM/OP lists:', err);
            }
        };

        fetchConfigs();
    }, [isOpen]);

    const validateField = (name, value, currentFormData = formData) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        const requiredFields = [
            'business_name', 'registration_type', 'state', 'mobile', 'email',
        ];
        if (showRmField) requiredFields.push('rm_id');
        if (showOpField) requiredFields.push('created_by');

        if (requiredFields.includes(name) && (!trimmedValue || trimmedValue === '')) {
            errorMsg = 'field required';
        } else {
            switch (name) {
                case 'customer_id':
                    if (trimmedValue === '' || trimmedValue === null || trimmedValue === undefined) {
                        break;
                    }
                    if (!/^\d+$/.test(String(trimmedValue)) || parseInt(trimmedValue, 10) <= 0) {
                        errorMsg = 'Enter a valid Customer ID';
                    }
                    break;
                case 'username':
                    if (value && value.length < 3) errorMsg = 'Min 3 characters';
                    if (value && value.length > 100) errorMsg = 'Max 100 characters';
                    break;
                case 'password':
                    if (value && value.length < 8) errorMsg = 'Min 8 characters';
                    if (value && value.length > 128) errorMsg = 'Max 128 characters';
                    break;
                case 'pan':
                    if (value) {
                        const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
                        if (!panRegex.test(value.toUpperCase())) errorMsg = 'Invalid PAN format(ABCDE1234F)';
                        if (currentFormData.gstin && currentFormData.gstin.length >= 12) {
                            const gstinPan = currentFormData.gstin.substring(2, 12).toUpperCase();
                            if (value.toUpperCase() !== gstinPan) {
                                errorMsg = 'PAN must match GSTIN (chars 3-12)';
                            }
                        }
                    }
                    break;
                case 'gstin':
                    if (value) {
                        const gstinRegex = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$/;
                        if (!gstinRegex.test(value.toUpperCase())) errorMsg = 'Invalid GSTIN format(22ABCDE1234F1Z5)';
                        if (value.length >= 12 && currentFormData.pan) {
                            const gstinPan = value.substring(2, 12).toUpperCase();
                            if (currentFormData.pan.toUpperCase() !== gstinPan) {
                                setFieldErrors(prev => ({ ...prev, gstin: 'GSTIN does not match PAN (chars 3-12)' }));
                                return 'GSTIN does not match PAN (chars 3-12)';
                            }
                        }
                    }
                    break;
                case 'business_name':
                    if (value.length > 200) errorMsg = 'Max 200 characters';
                    break;
                case 'registration_type':
                    if (value.length > 50) errorMsg = 'Max 50 characters';
                    break;
                case 'ownership_category':
                    if (value && value.length > 100) errorMsg = 'Max 100 characters';
                    break;
                case 'business_type':
                    if (value && value.length > 100) errorMsg = 'Max 100 characters';
                    break;
                case 'state':
                    if (value.length > 100) errorMsg = 'Max 100 characters';
                    break;
                case 'turnover_details':
                    if (value && value.length > 50) errorMsg = 'Max 50 characters';
                    break;
                case 'suspension_reason':
                    if (currentFormData.registration_status === 'SUSPENDED' && !value) errorMsg = 'Reason required';
                    if (value && value.length > 255) errorMsg = 'Max 255 characters';
                    break;
                case 'cancellation_reason':
                    if (currentFormData.registration_status === 'CANCELLED' && !value) errorMsg = 'Reason required';
                    if (value && value.length > 255) errorMsg = 'Max 255 characters';
                    break;
                case 'rm_id':
                    if (parseInt(value) <= 0) errorMsg = 'Invalid RM ID';
                    break;
                case 'mobile':
                    if (!/^\d{10}$/.test(value)) errorMsg = '10 digits required';
                    break;
                case 'email':
                case 'secondary_email':
                    if (value) {
                        const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
                        if (!emailRegex.test(value)) errorMsg = 'Invalid email format';
                        if (value.length > 150) errorMsg = 'Max 150 characters';
                    }
                    break;
                case 'language':
                    if (value && value.length > 50) errorMsg = 'Max 50 characters';
                    break;
                case 'client_name':
                    if (value && value.length > 200) errorMsg = 'Max 200 characters';
                    break;
                case 'referral_phone_number':
                    if (value && !/^\d{10}$/.test(String(value).replace(/\D/g, ''))) {
                        errorMsg = '10 digits required';
                    }
                    break;
                default:
                    break;
            }
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return errorMsg;
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        const newValue = type === 'checkbox' ? checked : value;
        setFormData((prev) => {
            const updated = { ...prev, [name]: newValue };
            
            if (name === 'registration_status') {
                if (newValue !== 'SUSPENDED') {
                    updated.suspension_reason = '';
                    setFieldErrors(prevErrs => ({ ...prevErrs, suspension_reason: '' }));
                }
                if (newValue !== 'CANCELLED') {
                    updated.cancellation_reason = '';
                    setFieldErrors(prevErrs => ({ ...prevErrs, cancellation_reason: '' }));
                }
            }

            if (name === 'registration_type' && newValue === 'COMPOSITION') {
                if (updated.filing_preference === 'MONTHLY') {
                    updated.filing_preference = 'QUARTERLY';
                }
            }
            
            validateField(name, newValue, updated);

            if (name === 'registration_status') {
                validateField('suspension_reason', updated.suspension_reason, updated);
                validateField('cancellation_reason', updated.cancellation_reason, updated);
            }

            return updated;
        });
    };

    const validateForm = () => {
        const errors = {};
        const keysToValidate = new Set([...Object.keys(formData), 'suspension_reason', 'cancellation_reason']);
        
        keysToValidate.forEach(key => {
            const errorMsg = validateField(key, formData[key]);
            if (errorMsg) errors[key] = errorMsg;
        });

        if (formData.pan && formData.gstin && formData.gstin.length >= 12) {
            const gstinPan = formData.gstin.substring(2, 12).toUpperCase();
            if (formData.pan.toUpperCase() !== gstinPan) {
                errors.gstin = 'GSTIN does not match PAN';
                setFieldErrors(prev => ({ ...prev, gstin: 'GSTIN does not match PAN' }));
            }
        }

        if (Object.keys(errors).length > 0) return "Please correct the errors in the form.";
        return null;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setFieldErrors({});

        const validationError = validateForm();
        if (validationError) {
            setError(validationError);
            return;
        }

        setLoading(true);
        const token = localStorage.getItem('session_token');
        try {
            let createdBy = null;
            if (token) {
                try {
                    const payload = JSON.parse(atob(token.split('.')[1]));
                    if (payload?.sub) {
                        createdBy = parseInt(payload.sub, 10);
                    }
                } catch (e) {
                    // token parse error handled below
                }
            }

            if (!createdBy || Number.isNaN(createdBy)) {
                setError("Unable to identify current user. Please login again.");
                setLoading(false);
                return;
            }

            const parsedCustomerId = parseInt(formData.customer_id, 10);
            const rawPayload = {
                ...formData,
                customer_id: Number.isFinite(parsedCustomerId) && parsedCustomerId > 0
                    ? parsedCustomerId
                    : undefined,
                pan: formData.pan.toUpperCase(),
                gstin: formData.gstin ? formData.gstin.toUpperCase() : '',
                rm_id: resolveRmIdForPayload({
                    profileData,
                    isEditMode: false,
                    formRmId: formData.rm_id,
                    assignmentPool: activeRMs,
                }),
                created_by: (() => {
                    const resolved = resolveOpIdForPayload({
                        profileData,
                        isEditMode: false,
                        formOpId: formData.created_by,
                        opRecordKey: 'created_by',
                        assignmentPool: activeOps,
                    });
                    return resolved != null ? resolved : createdBy;
                })(),
                filing_preference: formData.filing_preference || null,
                client_name: formData.client_name?.trim() || null,
                referral_phone_number: (formData.referral_phone_number || '').replace(/\D/g, '') || null,
            };

            // Remove empty strings so backend doesn't fail validation
            const payload = Object.fromEntries(
                Object.entries(rawPayload).filter(([_, v]) => v !== '' && v !== null)
            );

            await api.post(`/api/v1/gst-registrations`, payload);

            setSuccess(true);
            setTimeout(() => {
                if (onSuccess) {
                    onSuccess();
                }
                closeModal();
            }, 2000);
        } catch (err) {
            setError(extractGstRegistrationError(err));
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={closeModal}>
            <div className="gst-modal-card-v4 wide-modal app-drawer-panel gst-reg-side-drawer-shell" onClick={e => e.stopPropagation()}>
                {success ? (
                    <div className="gst-modal-success-state">
                        <div className="gst-success-icon-wrapper">
                            <CheckCircle2 size={48} className="gst-success-tick" />
                        </div>
                        <h2 className="modal-title-v4">GST Record Created</h2>
                        <p className="modal-subtitle-v4">The GST registration has been successfully established in the system.</p>
                        <button className="glow-green" onClick={closeModal} style={{ marginTop: '24px' }}>
                            Go to Dashboard
                        </button>
                    </div>
                ) : (
                    <>
                        <div className="modal-header-v4">
                            <div className="header-content-v4">
                                <div className="header-icon-box-v4" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#2eb87a' }}>
                                    <Users size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <div className="modal-header-texts">
                                        <h2 className="modal-title-v4">
                                            Create GST Registration
                                            <span className="modal-header-tag-v4 create">NEW</span>
                                        </h2>
                                        <p className="modal-subtitle-v4">Onboard a new GST profile and assign ownership</p>
                                    </div>
                                </div>
                            </div>
                            <button className="btn-drawer-close" onClick={closeModal}><X size={20} /></button>
                        </div>

                        <form onSubmit={handleSubmit} className="modal-form-v4 expanded-form">
                            {error && (
                                <div className="gst-message-banner error" style={{ margin: '0 32px 24px' }}>
                                    <AlertCircle size={18} />
                                    <span className="gst-message-banner-text">{error}</span>
                                </div>
                            )}

                            <div className="form-scroll-container">
                                {/* SECTION 1: IDENTITY & CUSTOMER LINK */}
                                <div className="form-section-group">
                                    <h3 className="section-title">1. Identity & Customer Link</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Customer ID</label>
                                            <input
                                                type="number"
                                                name="customer_id"
                                                value={formData.customer_id}
                                                onChange={handleChange}
                                                min="1"
                                                placeholder="Enter customer ID"
                                                className={`modal-input-v4 ${fieldErrors.customer_id ? 'error' : ''}`}
                                            />
                                            {fieldErrors.customer_id && (
                                                <span className="field-error-msg">{fieldErrors.customer_id}</span>
                                            )}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Client Name</label>
                                            <input type="text" name="client_name" value={formData.client_name} onChange={handleChange} maxLength="200" className="modal-input-v4" />
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Name*</label>
                                            <input type="text" name="business_name" value={formData.business_name} onChange={handleChange} required className="modal-input-v4" />
                                            {fieldErrors.business_name && <span className="field-error-msg">{fieldErrors.business_name}</span>}
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Username</label>
                                            <input type="text" name="username" value={formData.username} onChange={handleChange} className="modal-input-v4" />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Password</label>
                                            <input type="password" name="password" value={formData.password} onChange={handleChange} className="modal-input-v4" />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">PAN*</label>
                                            <input type="text" name="pan" value={formData.pan} onChange={handleChange} required placeholder="ABCDE1234F" className="modal-input-v4" />
                                            {fieldErrors.pan && <span className="field-error-msg">{fieldErrors.pan}</span>}
                                        </div>
                                        <div className="form-group-v4" style={{ gridColumn: 'span 2' }}>
                                            <label className="modal-label-caps">GSTIN</label>
                                            <input type="text" name="gstin" value={formData.gstin} onChange={handleChange} className="modal-input-v4 mono-v4" style={{ color: '#2eb87a' }} placeholder="Optional" />
                                            {fieldErrors.gstin && <span className="field-error-msg">{fieldErrors.gstin}</span>}
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 2: CONFIGURATION */}
                                <div className="form-section-group" style={{ marginTop: '32px' }}>
                                    <h3 className="section-title">2. Business Configuration</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Registration Type*</label>
                                            <FormCustomSelect
                                                name="registration_type"
                                                value={formData.registration_type}
                                                onChange={handleChange}
                                                options={optionsFromConfig(registrationTypes, 'Select Type')}
                                                placeholder="Select Type"
                                                ariaLabel="Registration type"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Ownership Category</label>
                                            <FormCustomSelect
                                                name="ownership_category"
                                                value={formData.ownership_category}
                                                onChange={handleChange}
                                                options={optionsFromConfig(ownershipCategories, 'Select Category')}
                                                placeholder="Select Category"
                                                ariaLabel="Ownership category"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Type</label>
                                            <FormCustomSelect
                                                name="business_type"
                                                value={formData.business_type}
                                                onChange={handleChange}
                                                options={optionsFromConfig(businessTypes, 'Select Type')}
                                                placeholder="Select Type"
                                                ariaLabel="Business type"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">State*</label>
                                            <FormCustomSelect
                                                name="state"
                                                value={formData.state}
                                                onChange={handleChange}
                                                options={optionsFromConfig(states, 'Select State')}
                                                placeholder="Select State"
                                                ariaLabel="State"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Turnover Details*</label>
                                            <FormCustomSelect
                                                name="turnover_details"
                                                value={formData.turnover_details}
                                                onChange={handleChange}
                                                options={optionsFromConfig(turnoverDetailsList, 'Select Details')}
                                                placeholder="Select Details"
                                                ariaLabel="Turnover details"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Filing Preference</label>
                                            <FormCustomSelect
                                                name="filing_preference"
                                                value={formData.filing_preference}
                                                onChange={handleChange}
                                                options={optionsFromPairs([
                                                    { value: '', label: 'Select Preference' },
                                                    ...(formData.registration_type !== 'COMPOSITION'
                                                        ? [{ value: 'MONTHLY', label: 'MONTHLY' }]
                                                        : []),
                                                    { value: 'QUARTERLY', label: 'QUARTERLY' },
                                                ])}
                                                placeholder="Select Preference"
                                                ariaLabel="Filing preference"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Initial Status</label>
                                            <FormCustomSelect
                                                name="registration_status"
                                                value={formData.registration_status}
                                                onChange={handleChange}
                                                options={optionsFromConfig(registrationStatuses, 'Select Status')}
                                                placeholder="Select Status"
                                                ariaLabel="Initial status"
                                            />
                                        </div>
                                    </div>

                                    <div className="gst-checkbox-row-v4" style={{ marginTop: '20px', display: 'flex', gap: '24px' }}>
                                        <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-primary)' }}>
                                            <input type="checkbox" name="is_rcm_applicable" checked={formData.is_rcm_applicable} onChange={handleChange} className="modal-checkbox-v4" />
                                            <span>RCM Applicable</span>
                                        </label>
                                        <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-primary)' }}>
                                            <input type="checkbox" name="is_filing_needed" checked={formData.is_filing_needed} onChange={handleChange} className="modal-checkbox-v4" />
                                            <span>Filing Needed</span>
                                        </label>
                                    </div>
                                </div>

                                {/* SECTION 3: ASSIGNMENTS & CONTACT */}
                                <div className="form-section-group" style={{ marginTop: '32px' }}>
                                    <h3 className="section-title">3. Assignments & Contact</h3>
                                    <div className="form-grid-3">
                                        {showRmField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Relationship Manager*</label>
                                            <FormCustomSelect
                                                name="rm_id"
                                                value={formData.rm_id}
                                                onChange={handleChange}
                                                options={optionsFromPairs(buildRmOpSelectOptions(activeRMs), 'Select RM')}
                                                placeholder="Select RM"
                                                ariaLabel="Relationship manager"
                                            />
                                        </div>
                                        )}
                                        {showOpField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Assigned OP*</label>
                                            <FormCustomSelect
                                                name="created_by"
                                                value={formData.created_by}
                                                onChange={handleChange}
                                                options={optionsFromPairs(buildRmOpSelectOptions(activeOps), 'Select OP')}
                                                placeholder="Select OP"
                                                ariaLabel="Assigned OP"
                                            />
                                        </div>
                                        )}
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Mobile*</label>
                                            <input type="tel" name="mobile" value={formData.mobile} onChange={handleChange} maxLength="10" required className="modal-input-v4" />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Email*</label>
                                            <input type="email" name="email" value={formData.email} onChange={handleChange} required className="modal-input-v4" />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Secondary Email</label>
                                            <input type="email" name="secondary_email" value={formData.secondary_email} onChange={handleChange} className="modal-input-v4" />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Preferred Language</label>
                                            <FormCustomSelect
                                                name="language"
                                                value={formData.language}
                                                onChange={handleChange}
                                                options={optionsFromConfig(languages, 'Select Language')}
                                                placeholder="Select Language"
                                                ariaLabel="Preferred language"
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Referral Phone</label>
                                            <input type="tel" name="referral_phone_number" value={formData.referral_phone_number} onChange={handleChange} maxLength="10" className="modal-input-v4" />
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer-v4">
                                <div className="footer-actions-v4">
                                    <button type="button" onClick={closeModal} className="gst-btn-secondary">Cancel</button>
                                    <button type="submit" className="gst-btn-primary" disabled={loading}>
                                        {loading && <RotateCcw size={16} className="gst-refresh-spin" />}
                                        {loading ? 'Creating...' : 'Create Registration'}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </>
                )}
            </div>
        </div>
    );
};

export default GSTRegistrationSignup;
