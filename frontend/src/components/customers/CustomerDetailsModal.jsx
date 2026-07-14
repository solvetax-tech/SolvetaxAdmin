import React, { useState, useEffect, useCallback } from 'react';
import {
    X, User, Mail, Phone, Briefcase, Hash, MapPin,
    FileText, Link as LinkIcon, Trash2,
    CheckCircle2, AlertCircle, RotateCcw, Save, Shield, Sparkles, Search
} from 'lucide-react';
import './CustomerDetailsModal.css';
import api from '../../utils/api';
import { getRmOpAssignmentVisibility } from '../../utils/rmOpAssignmentFields';
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
import { optionsFromConfig, optionsFromPairs } from '../common/selectOptionUtils';
import { buildRmOpIdSelectOptions, fetchAssignmentListsIfNeeded } from '../../utils/activeEmployees';
import {
    buildCustomerEditPayload,
    validateReferralPhone,
    SERVICE_REQUIRED_CRM_HINT,
} from '../../utils/customerApi';
import {
    isBusinessTypeOther,
    parseBusinessTypeFromApi,
    resolveBusinessTypeForApi,
} from '../../utils/businessTypeUtils';
import {
    fetchStaffServiceConfig,
    groupStaffServicesByCategory,
    sortedStaffServiceCategoryEntries,
    getServiceCategoryLabel,
} from '../../utils/staffServiceConfigApi';

const CustomerDetailsModal = ({ isOpen, onClose, customerId, isAdmin, profileData, userRole, initialData, initialEditMode = false }) => {
    const effectiveProfile = profileData || (userRole ? { role: userRole } : null);
    const { showRmField, showOpField } = getRmOpAssignmentVisibility(effectiveProfile);
    const [customer, setCustomer] = useState(initialData || null);
    const [loading, setLoading] = useState(!initialData);
    const [error, setError] = useState(null);
    const [editMode, setEditMode] = useState(initialEditMode);
    const [formData, setFormData] = useState(initialData || {});
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [states, setStates] = useState([]);
    const [message, setMessage] = useState({ type: '', text: '' });
    const [subLoading, setSubLoading] = useState(false);
    const [businessTypes, setBusinessTypes] = useState([]);
    const [confirmDeactivate, setConfirmDeactivate] = useState(false);
    const [servicesConfig, setServicesConfig] = useState([]);
    const [fieldErrors, setFieldErrors] = useState({});
    const [aiLoading, setAiLoading] = useState(false);
    const [isLocationSelected, setIsLocationSelected] = useState(false);
    const [languages, setLanguages] = useState([]);
    
    // Location Search States
    const [locationResults, setLocationResults] = useState([]);
    const [locationLoading, setLocationLoading] = useState(false);
    const [showLocationResults, setShowLocationResults] = useState(false);
    const ignoreSearchRef = React.useRef(false);

    const fetchData = useCallback(async () => {
        if (!customerId) return;
        setLoading(true);
        setError(null);

        try {
            const results = await Promise.allSettled([
                api.get(`/api/v1/customers/${customerId}`),
                api.get(`/api/v1/gst-registration/config/STATE`),
                api.get(`/api/v1/gst-registration/config/BUSINESS_TYPE`),
                api.get(`/api/v1/gst-registration/config/LANGUAGE`),
            ]);

            const [custRes, statesRes, bizTypeRes, langRes] = results;

            const getConfigData = (res) => {
                if (res.status !== 'fulfilled') return [];
                const data = res.value.data?.items || res.value.data?.data || res.value.data || [];
                return Array.isArray(data) ? data : [];
            };

            const bizTypes = getConfigData(bizTypeRes);

            if (custRes.status === 'fulfilled') {
                const custData = custRes.value.data || {};
                const parsedBiz = parseBusinessTypeFromApi(custData.business_type, bizTypes);
                setCustomer(custData);
                setFormData({
                    ...custData,
                    rm_id: custData.rm_id != null && custData.rm_id !== '' ? String(custData.rm_id) : '',
                    op_id: custData.op_id != null && custData.op_id !== '' ? String(custData.op_id) : '',
                    referral_phone_number: custData.referral_phone_number || '',
                    service_required: custData.service_required || [],
                    service_provided: custData.service_provided || [],
                    business_type: parsedBiz.selectValue,
                    business_type_other: parsedBiz.otherText,
                });
                setIsLocationSelected(!!custData.city);
            } else if (!initialData) {
                setError(custRes.reason?.message || "Customer not found or access denied");
            }

            if (showRmField || showOpField) {
                try {
                    const { activeRMs: rms, activeOps: ops } = await fetchAssignmentListsIfNeeded({
                        needRm: showRmField,
                        needOp: showOpField,
                    });
                    if (showRmField) setActiveRMs(rms);
                    if (showOpField) setActiveOps(ops);
                } catch (empErr) {
                    console.error('Failed to load RM/OP employees:', empErr);
                }
            }
            setStates(getConfigData(statesRes));
            setBusinessTypes(bizTypes);
            setLanguages(getConfigData(langRes));

            try {
                const services = await fetchStaffServiceConfig();
                setServicesConfig(services);
            } catch (svcErr) {
                console.error('Failed to load staff service config:', svcErr);
                setServicesConfig([]);
            }

        } catch (err) {
            // api.js interceptor already formats backend errors
            setError(err?.message || "Failed to load customer data.");
        } finally {
            setLoading(false);
        }
    }, [customerId, showRmField, showOpField]);

    useEffect(() => {
        if (isOpen && customerId) {
            setEditMode(initialEditMode);
            if (initialData) {
                setCustomer(initialData);
                setFormData({
                    ...initialData,
                    rm_id: initialData.rm_id != null ? String(initialData.rm_id) : '',
                    op_id: initialData.op_id != null ? String(initialData.op_id) : '',
                    service_required: initialData.service_required || [],
                    service_provided: initialData.service_provided || [],
                });
                setLoading(false);
            } else {
                setLoading(true);
            }
            fetchData();
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'unset';
            setEditMode(false);
            setMessage({ type: '', text: '' });
            setConfirmDeactivate(false);
            setFieldErrors({});
        }
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, customerId, initialEditMode, fetchData]);

    useEffect(() => {
        if (isOpen && initialEditMode) setEditMode(true);
    }, [isOpen, initialEditMode]);

    const handleCancelEdit = () => {
        handleDrawerCancelEdit({
            initialEditMode,
            onClose,
            setEditMode,
            resetEditState: () => {
                if (customer) {
                    const parsedBiz = parseBusinessTypeFromApi(customer.business_type, businessTypes);
                    setFormData({
                        ...customer,
                        rm_id: customer.rm_id != null && customer.rm_id !== '' ? String(customer.rm_id) : '',
                        op_id: customer.op_id != null && customer.op_id !== '' ? String(customer.op_id) : '',
                        referral_phone_number: customer.referral_phone_number || '',
                        service_required: customer.service_required || [],
                        service_provided: customer.service_provided || [],
                        business_type: parsedBiz.selectValue,
                        business_type_other: parsedBiz.otherText,
                    });
                } else {
                    setFormData({});
                }
                setMessage({ type: '', text: '' });
                setFieldErrors({});
            },
        });
    };

    const isEditing = editMode || initialEditMode;
    const showEditFooter = isEditing;

    // Location Search Effect
    useEffect(() => {
        if (!editMode) return;
        const timer = setTimeout(async () => {
            if (ignoreSearchRef.current) {
                ignoreSearchRef.current = false;
                return;
            }

            const searchVal = formData.city;
            if (!searchVal || searchVal.length < 3) {
                setLocationResults([]);
                setShowLocationResults(false);
                return;
            }

            setLocationLoading(true);
            setShowLocationResults(true);

            try {
                let response;
                const isPincode = /^\d{6}$/.test(searchVal.trim());
                if (isPincode) {
                    response = await api.get(`/api/v1/customers/pincode/${searchVal.trim()}`);
                } else {
                    response = await api.get(`/api/v1/customers/pincode-search?search=${searchVal.trim()}`);
                }
                const locations = response.data.locations || [];
                setLocationResults(locations);
            } catch (err) {
                setLocationResults([]);
            } finally {
                setLocationLoading(false);
            }
        }, 600);

        return () => clearTimeout(timer);
    }, [formData.city, editMode]);

    const handleSelectLocation = (loc) => {
        ignoreSearchRef.current = true;
        setFormData(prev => ({
            ...prev,
            state: loc.state?.toUpperCase().replace(/\s+/g, '_') || prev.state,
            city: loc.name || loc.district || prev.city
        }));
        setIsLocationSelected(true);
        setShowLocationResults(false);
        setFieldErrors(prev => ({ ...prev, state: '', city: '' }));
    };

    const validateField = (name, value) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        switch (name) {
            case 'full_name':
                if (!trimmedValue) errorMsg = 'field required';
                else if (trimmedValue.length < 2) errorMsg = 'Minimum 2 characters';
                else if (trimmedValue.length > 150) errorMsg = 'Maximum 150 characters';
                break;
            case 'mobile':
                if (!trimmedValue) errorMsg = 'field required';
                else if (!/^\d{10}$/.test(trimmedValue)) errorMsg = '10 digits required';
                break;
            case 'email':
                if (trimmedValue) {
                    if (trimmedValue.length > 150) errorMsg = 'Maximum 150 characters';
                    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedValue)) errorMsg = 'Invalid email format';
                }
                break;
            case 'business_name':
                if (!trimmedValue) errorMsg = 'field required';
                else if (trimmedValue.length > 200) errorMsg = 'Maximum 200 characters';
                break;
            case 'rm_id':
                if (showRmField && !value) errorMsg = 'field required';
                break;
            case 'op_id':
                if (showOpField && !value) errorMsg = 'field required';
                break;
            case 'language':
                if (trimmedValue && trimmedValue.length > 50) errorMsg = 'Maximum 50 characters';
                break;
            case 'referral_phone_number':
                errorMsg = validateReferralPhone(value);
                break;
            case 'business_type_other':
                if (isBusinessTypeOther(formData.business_type, businessTypes) && trimmedValue && trimmedValue.length > 50) {
                    errorMsg = 'Maximum 50 characters';
                }
                break;
            default:
                break;
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return !errorMsg;
    };

    const validateForm = () => {
        const fieldsToValidate = ['full_name', 'mobile', 'business_name'];
        if (isBusinessTypeOther(formData.business_type, businessTypes)) {
            fieldsToValidate.push('business_type_other');
        }
        if (showRmField) fieldsToValidate.push('rm_id');
        if (showOpField) fieldsToValidate.push('op_id');
        let isValid = true;
        fieldsToValidate.forEach(field => {
            if (!validateField(field, formData[field])) {
                isValid = false;
            }
        });
        return isValid;
    };

    const handleChange = (e) => {
        const { name, value, multiple, options } = e.target;
        if (multiple && options) {
            const selected = Array.from(options)
                .filter(option => option.selected)
                .map(option => option.value);
            setFormData(prev => ({ ...prev, [name]: selected }));
        } else {
            setFormData((prev) => {
                const next = { ...prev, [name]: value };
                if (name === 'business_type' && !isBusinessTypeOther(value, businessTypes)) {
                    next.business_type_other = '';
                }
                return next;
            });
            if (name === 'city') setIsLocationSelected(false);
            if (name !== 'service_required') {
                validateField(name, value);
            }
            if (name === 'business_type') {
                validateField('business_type_other', formData.business_type_other);
            }
        }
    };

    const toggleService = (field, code) => {
        setFormData(prev => {
            const current = Array.isArray(prev[field]) ? prev[field] : [];
            const exists = current.includes(code);
            const next = exists ? current.filter(item => item !== code) : [...current, code];
            return { ...prev, [field]: next };
        });
    };

    const normalizeServiceList = (value) => {
        if (value === undefined || value === null) return undefined;
        if (Array.isArray(value)) {
            return value.map(v => String(v).trim()).filter(Boolean);
        }
        if (typeof value === 'string') {
            return value.split(',').map(v => v.trim()).filter(Boolean);
        }
        return [];
    };

    const handleGenerateDescription = async () => {
        if (!formData.business_name) {
            addNotification('More Context Required', 'Please enter a business name first.', 'WARNING');
            return;
        }

        setAiLoading(true);
        try {
            const response = await api.post('/api/v1/customers/business-description/generate', {
                full_name: formData.full_name || 'Customer',
                business_name: formData.business_name,
                business_type: resolveBusinessTypeForApi(
                    formData.business_type,
                    formData.business_type_other,
                    businessTypes,
                ),
                state: formData.state,
                city: formData.city,
                remark: formData.remark,
            });

            if (response.data?.business_description) {
                setFormData(prev => ({ ...prev, business_description: response.data.business_description }));
                addNotification('AI Generation Success', 'Professional business description has been updated.', 'INFO');
            }
        } catch (err) {
            console.error('AI Generation Error:', err);
            const errorMsg = err?.message || '';
            if (errorMsg.includes('AI not configured')) {
                addNotification('AI Unavailable', 'Business description AI is not yet configured for this environment. Please enter the description manually.', 'WARNING');
            } else {
                addNotification('AI Generation Failed', errorMsg || 'Failed to generate description.', 'ERROR');
            }
        } finally {
            setAiLoading(false);
        }
    };

    const handleSave = async () => {
        setMessage({ type: '', text: '' });

        if (!validateForm()) {
            setMessage({ type: 'error', text: 'Please correct the highlighted fields.' });
            return;
        }

        setSubLoading(true);
        try {
            const updatePayload = buildCustomerEditPayload(formData, effectiveProfile, customer, businessTypes);
            await api.post(`/api/v1/customers/${customerId}/edit`, updatePayload);
            setMessage({ type: 'success', text: 'Customer details updated successfully! ✨' });

            addNotification(
                'Customer Profile Updated',
                `Profile for ${formData.full_name} was updated.`,
                'UPDATE'
            );

            if (shouldCloseDrawerAfterSave(initialEditMode)) {
                onClose();
                return;
            }
            setEditMode(false);
            fetchData();
        } catch (err) {
            // interceptor already extracted the backend message
            setMessage({ type: 'error', text: err?.message || "Update failed." });
        } finally {
            setSubLoading(false);
        }
    };

    const handleDeactivate = async () => {
        setConfirmDeactivate(false);
        setSubLoading(true);
        setMessage({ type: '', text: '' });

        try {
            const response = await api.delete(`/api/v1/customers/${customerId}/soft_delete`);
            // Backend returns specific success messages for Case 1 and Case 2
            const successMsg = response.data?.message || 'Customer deactivated successfully! ✨';
            setMessage({ type: 'success', text: successMsg });

            addNotification(
                'Customer Deactivated',
                successMsg,
                'SYSTEM'
            );

            fetchData();
        } catch (err) {
            // interceptor already extracted the backend message
            setMessage({ type: 'error', text: err?.message || "Deactivation failed." });
        } finally {
            setSubLoading(false);
        }
    };

    if (!isOpen) return null;

    const serviceCategoryEntries = sortedStaffServiceCategoryEntries(
        groupStaffServicesByCategory(servicesConfig),
    );
    const serviceNameByCode = servicesConfig.reduce((acc, service) => {
        if (service.service_code) acc[service.service_code] = service.service_name || service.service_code;
        return acc;
    }, {});
    const mapServiceCodesToNames = (list) => {
        if (!Array.isArray(list)) return [];
        return list.map(code => serviceNameByCode[code] || code).filter(Boolean);
    };

    return (
        <div className="modal-overlay app-side-drawer-mode" onClick={onClose}>
            <div className={`modal-content-v4 customer-details-modal gst-reg-side-drawer-shell app-drawer-panel${isEditing ? ' edit-mode' : ''}`} onClick={(e) => e.stopPropagation()}>
                <div className="modal-form-wrapper">
                    <div className="modal-header">
                        <div className="header-header-top">
                            <div className="header-icon-box-v4">
                                <User size={20} />
                            </div>
                            <div className="modal-title-box">
                                <h1 className="modal-title-v4">
                                    {customer?.full_name || 'Customer Profile'}
                                    <span className={`header-badge-v4 ${isEditing ? 'edit-mode' : 'view-mode'}`}>
                                        {isEditing ? 'EDITING' : 'VIEWING'}
                                    </span>
                                </h1>
                                <p className="modal-subtitle-v4">Manage business profile and assignments • <span className="highlight-green-v4">ID: {customerId}</span></p>
                            </div>
                        </div>
                        <button className="modal-close-btn" onClick={onClose} aria-label="Close">
                            <X size={20} />
                        </button>
                    </div>

                        <div className="form-sections-container">
                            {loading ? (
                                <div className="gst-skeleton-v4">
                                    {[1, 2, 3].map(section => (
                                        <div key={section} className="form-section-v4">
                                            <div className="skeleton-line-v4 short skeleton-pulse-v4" />
                                            <div className="form-grid-3">
                                                {[1, 2, 3, 4, 5, 6].map(i => (
                                                    <div key={i} className="form-group-v4">
                                                        <div className="skeleton-line-v4 x-short skeleton-pulse-v4" style={{ marginBottom: '8px' }} />
                                                        <div className="skeleton-line-v4 box-v4 skeleton-pulse-v4" />
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : error ? (
                                <div className="message-banner error">
                                    <AlertCircle size={18} />
                                    {error}
                                </div>
                            ) : (
                                <>
                                    {message.text && (
                                        <div className={`message-banner ${message.type}`}>
                                            {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                                            {message.text}
                                        </div>
                                    )}

                                <div className="form-section-v4">
                                    <h3 className="section-title">1. Customer Details</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Full Name</label>
                                            {editMode ? (
                                                <input name="full_name" value={formData.full_name || ''} onChange={handleChange} className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box highlight">{customer?.full_name}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Mobile</label>
                                            {editMode ? (
                                                <input type="tel" name="mobile" value={formData.mobile || ''} onChange={handleChange} maxLength="10" className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box highlight">{customer?.mobile}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Email</label>
                                            {editMode ? (
                                                <input name="email" value={formData.email || ''} onChange={handleChange} className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.email || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Name</label>
                                            {editMode ? (
                                                <input name="business_name" value={formData.business_name || ''} onChange={handleChange} className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box highlight">{customer?.business_name || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Type</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="business_type"
                                                    value={formData.business_type || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(businessTypes, 'Select Type')}
                                                    placeholder="Select Type"
                                                    ariaLabel="Business type"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.business_type || '-'}</div>
                                            )}
                                        </div>
                                        {editMode && isBusinessTypeOther(formData.business_type, businessTypes) && (
                                            <div className="form-group-v4">
                                                <label className="modal-label-caps">Specify Business Type</label>
                                                <input
                                                    type="text"
                                                    name="business_type_other"
                                                    placeholder="Enter specific business type"
                                                    value={formData.business_type_other || ''}
                                                    onChange={handleChange}
                                                    maxLength={50}
                                                    className={`modal-input-v4 ${fieldErrors.business_type_other ? 'error' : ''}`}
                                                />
                                                {fieldErrors.business_type_other && (
                                                    <div className="field-error-msg">{fieldErrors.business_type_other}</div>
                                                )}
                                            </div>
                                        )}
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Preferred Language</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="language"
                                                    value={formData.language || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(languages, 'Select Language')}
                                                    placeholder="Select Language"
                                                    ariaLabel="Preferred language"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.language || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Account Status</label>
                                            <div className="gst-form-value-box">
                                                <span className={`status-badge ${customer?.is_active ? 'active' : 'inactive'}`}>
                                                    {customer?.is_active ? 'ACTIVE' : 'INACTIVE'}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">2. Location & Remark</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">State</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="state"
                                                    value={formData.state || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(states, 'Select State')}
                                                    placeholder="Select State"
                                                    ariaLabel="State"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.state || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">City / Pincode Search</label>
                                            {editMode ? (
                                                <div className="location-search-wrapper" style={{ position: 'relative' }}>
                                                    <input
                                                        type="text"
                                                        name="city"
                                                        value={formData.city || ''}
                                                        onChange={handleChange}
                                                        className="modal-input-v4"
                                                        placeholder="Search city or pincode..."
                                                        style={{ paddingRight: isLocationSelected ? '52px' : '36px' }}
                                                    />
                                                    <div style={{ position: 'absolute', right: '12px', top: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        {isLocationSelected && (
                                                            <X
                                                                size={14}
                                                                style={{ color: 'var(--danger)', cursor: 'pointer' }}
                                                                onClick={() => {
                                                                    setFormData(prev => ({ ...prev, city: '', state: '' }));
                                                                    setIsLocationSelected(false);
                                                                }}
                                                            />
                                                        )}
                                                        {locationLoading ? (
                                                            <RotateCcw size={14} className="refresh-spin" style={{ color: 'rgba(var(--fg-rgb),0.2)' }} />
                                                        ) : (
                                                            <Search size={14} style={{ color: isLocationSelected ? 'rgba(var(--fg-rgb),0.2)' : 'var(--accent)' }} />
                                                        )}
                                                    </div>
                                                    {showLocationResults && (
                                                        <div className="location-results-dropdown">
                                                            {locationResults.map((loc, idx) => (
                                                                <div key={idx} className="location-result-item" onClick={() => handleSelectLocation(loc)}>
                                                                    <span className="location-main-text">{loc.name}</span>
                                                                    <span className="location-sub-text">{loc.district}, {loc.state}</span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            ) : (
                                                <div className="gst-form-value-box highlight">{customer?.city || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Remark</label>
                                            {editMode ? (
                                                <input name="remark" value={formData.remark || ''} onChange={handleChange} className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.remark || '-'}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">3. Assignments & Referral</h3>
                                    <div className="form-grid-3">
                                        {showRmField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Relationship Manager</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="rm_id"
                                                    value={formData.rm_id || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs(
                                                        buildRmOpIdSelectOptions(activeRMs, {
                                                            id: customer?.rm_id,
                                                            label: customer?.rm_username || customer?.rm_name,
                                                        }),
                                                        'Select RM'
                                                    )}
                                                    placeholder="Select RM"
                                                    ariaLabel="Relationship manager"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.rm_username || customer?.rm_name || customer?.rm_id || 'Unassigned'}</div>
                                            )}
                                        </div>
                                        )}
                                        {showOpField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Assigned OP</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="op_id"
                                                    value={formData.op_id || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs(
                                                        buildRmOpIdSelectOptions(activeOps, {
                                                            id: customer?.op_id,
                                                            label: customer?.op_username || customer?.op_name,
                                                        }),
                                                        'Select OP'
                                                    )}
                                                    placeholder="Select OP"
                                                    ariaLabel="Assigned OP"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.op_username || customer?.op_name || customer?.op_id || 'Unassigned'}</div>
                                            )}
                                        </div>
                                        )}
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Referrer mobile (optional)</label>
                                            {editMode ? (
                                                <>
                                                    <input
                                                        type="tel"
                                                        name="referral_phone_number"
                                                        value={formData.referral_phone_number || ''}
                                                        onChange={handleChange}
                                                        maxLength="10"
                                                        className={`modal-input-v4 ${fieldErrors.referral_phone_number ? 'error' : ''}`}
                                                        placeholder="10 digit mobile"
                                                    />
                                                    {fieldErrors.referral_phone_number && (
                                                        <div className="field-error-msg">{fieldErrors.referral_phone_number}</div>
                                                    )}
                                                </>
                                            ) : (
                                                <div className="gst-form-value-box">{customer?.referral_phone_number || '-'}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">4. Services Required</h3>
                                    {editMode && (
                                        <p className="services-hint-text">{SERVICE_REQUIRED_CRM_HINT}</p>
                                    )}
                                    {editMode ? (
                                        <div className="services-grid services-grid--single">
                                            <div className="services-card">
                                                <div className="services-card-header">
                                                    <Shield size={16} />
                                                    <span>Services Required</span>
                                                </div>
                                                {serviceCategoryEntries.length === 0 ? (
                                                    <div className="services-empty">No services available</div>
                                                ) : (
                                                    serviceCategoryEntries.map(([category, items]) => (
                                                        <details className="services-dropdown" key={category} open={serviceCategoryEntries.length <= 3}>
                                                            <summary className="services-dropdown-summary">
                                                                <span>{getServiceCategoryLabel(category)}</span>
                                                                <span className="services-dropdown-icon" aria-hidden="true" />
                                                            </summary>
                                                            <div className="services-dropdown-content">
                                                                <div className="services-options">
                                                                    {items.map(service => {
                                                                        const checked = Array.isArray(formData.service_required)
                                                                            && formData.service_required.includes(service.service_code);
                                                                        return (
                                                                            <label className="services-option" key={service.id}>
                                                                                <input
                                                                                    type="checkbox"
                                                                                    checked={checked}
                                                                                    onChange={() => toggleService('service_required', service.service_code)}
                                                                                />
                                                                                <span>{service.service_name}</span>
                                                                            </label>
                                                                        );
                                                                    })}
                                                                </div>
                                                            </div>
                                                        </details>
                                                    ))
                                                )}
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="form-grid-3">
                                            <div className="form-group-v4">
                                                <label className="modal-label-caps">Service Required</label>
                                                <div className="gst-form-value-box" style={{ minHeight: '60px', alignItems: 'flex-start', paddingTop: '12px' }}>
                                                    {Array.isArray(customer?.service_required) && customer.service_required.length > 0
                                                        ? mapServiceCodesToNames(customer.service_required).join(', ')
                                                        : '-'}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {(customer?.lead_source || customer?.tag || customer?.lead_type) && !editMode && (
                                <div className="form-section-v4">
                                    <h3 className="section-title">Marketing Attribution</h3>
                                    <p className="services-hint-text">Set automatically by digital marketing integration (read-only).</p>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Lead Source</label>
                                            <div className="gst-form-value-box">{customer?.lead_source || '-'}</div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Tag</label>
                                            <div className="gst-form-value-box">{customer?.tag || '-'}</div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Lead Type</label>
                                            <div className="gst-form-value-box">{customer?.lead_type || '-'}</div>
                                        </div>
                                    </div>
                                </div>
                                )}

                                <div className="form-section-v4">
                                    <h3 className="section-title">5. Business Profile</h3>
                                    <div className="form-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Image</label>
                                            {editMode ? (
                                                <textarea
                                                    name="business_image_url"
                                                    value={formData.business_image_url || ''}
                                                    onChange={handleChange}
                                                    rows="3"
                                                    className="modal-input-v4"
                                                    style={{ minHeight: '80px', resize: 'none' }}
                                                />
                                            ) : (
                                                <div className="gst-form-value-box" style={{ minHeight: '80px' }}>
                                                    {customer?.business_image_url ? <a href={customer.business_image_url} target="_blank" rel="noopener noreferrer">VIEW ATTACHMENT</a> : '-'}
                                                </div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Description</label>
                                            {editMode ? (
                                                <div className="textarea-ai-wrapper">
                                                    <textarea
                                                        name="business_description"
                                                        value={formData.business_description || ''}
                                                        onChange={handleChange}
                                                        rows="3"
                                                        className="modal-input-v4"
                                                        style={{ minHeight: '80px', resize: 'none' }}
                                                    />
                                                    <button type="button" className="ai-generate-btn-nested" onClick={handleGenerateDescription} disabled={aiLoading || !formData.business_name}>
                                                        {aiLoading ? <RotateCcw size={12} className="refresh-spin" /> : <Sparkles size={12} />}
                                                        <span>AI Generate</span>
                                                    </button>
                                                </div>
                                            ) : (
                                                <div className="gst-form-value-box" style={{ minHeight: '80px', alignItems: 'flex-start', paddingTop: '10px' }}>
                                                    {customer?.business_description || '-'}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                </>
                            )}
                        </div>

                        {showEditFooter && !loading && (
                            <AppDrawerModalFooter>
                                {isAdmin && customer?.is_active && (
                                    <AppDrawerBtnDelete
                                        onClick={() => setConfirmDeactivate(true)}
                                        disabled={subLoading || loading}
                                    />
                                )}
                                <AppDrawerBtnCancel
                                    onClick={handleCancelEdit}
                                    disabled={subLoading || loading}
                                />
                                <AppDrawerBtnSave
                                    onClick={handleSave}
                                    loading={subLoading}
                                    disabled={loading}
                                    icon={Save}
                                />
                            </AppDrawerModalFooter>
                        )}
                </div>

                {confirmDeactivate && (
                    <div className="confirm-modal-overlay">
                        <div className="confirm-modal-content">
                            <div className="confirm-icon-wrapper">
                                <AlertCircle size={32} color="var(--danger)" />
                            </div>
                            <h2>Confirm Deactivation</h2>
                            <p>Are you sure you want to deactivate this customer? If the customer has GST registrations, associated records may also be deactivated.</p>
                            <div className="confirm-modal-actions">
                                <button className="btn-secondary-link" onClick={() => setConfirmDeactivate(false)}>
                                    Cancel
                                </button>
                                <button className="btn-danger-glass" onClick={handleDeactivate}>
                                    Confirm
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default CustomerDetailsModal;
