import React, { useState, useEffect, useCallback, useRef } from 'react';
import { X, User, Mail, Phone, Briefcase, MapPin, FileText, Hash, CheckCircle2, AlertCircle, RotateCcw, Link as LinkIcon, Shield, Sparkles, Search } from 'lucide-react';
import api from '../../utils/api';
import { getRmOpAssignmentVisibility } from '../../utils/rmOpAssignmentFields';
import './AddCustomerModal.css';
import { addNotification } from '../../utils/notificationUtils';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig, optionsFromPairs } from '../common/selectOptionUtils';
import { buildRmOpIdSelectOptions, fetchAssignmentListsIfNeeded } from '../../utils/activeEmployees';
import {
    buildCustomerCreatePayload,
    createCustomer,
    validateReferralPhone,
    SERVICE_REQUIRED_CRM_HINT,
    INITIAL_CUSTOMER_FORM,
} from '../../utils/customerApi';
import {
    isBusinessTypeOther,
    resolveBusinessTypeForApi,
} from '../../utils/businessTypeUtils';
import {
    fetchStaffServiceConfig,
    groupStaffServicesByCategory,
    sortedStaffServiceCategoryEntries,
    getServiceCategoryLabel,
} from '../../utils/staffServiceConfigApi';

const AddCustomerModal = ({ isOpen, onClose, onSuccess, profileData }) => {
    const { showRmField, showOpField } = getRmOpAssignmentVisibility(profileData);
    const [formData, setFormData] = useState({ ...INITIAL_CUSTOMER_FORM });

    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [states, setStates] = useState([]);
    const [businessTypes, setBusinessTypes] = useState([]);
    const [servicesConfig, setServicesConfig] = useState([]);
    const [languages, setLanguages] = useState([]);

    // Location Search States
    const [locationResults, setLocationResults] = useState([]);
    const [locationLoading, setLocationLoading] = useState(false);
    const [showLocationResults, setShowLocationResults] = useState(false);
    const [loading, setLoading] = useState(false);
    const [configLoading, setConfigLoading] = useState(true);
    const [aiLoading, setAiLoading] = useState(false);
    const [isLocationSelected, setIsLocationSelected] = useState(false);
    const [fieldErrors, setFieldErrors] = useState({});
    const [error, setError] = useState('');
    const [isSuccess, setIsSuccess] = useState(false);
    const ignoreSearchRef = useRef(false);

    const fetchConfigData = useCallback(async () => {
        setConfigLoading(true);
        const sources = [
            { url: '/api/v1/gst-registration/config/STATE', setter: setStates },
            { url: '/api/v1/gst-registration/config/BUSINESS_TYPE', setter: setBusinessTypes },
            { url: '/api/v1/gst-registration/config/LANGUAGE', setter: setLanguages },
        ];

        for (const source of sources) {
            try {
                const response = await api.get(source.url);
                const data = response.data?.items || response.data?.data || response.data || [];
                source.setter(Array.isArray(data) ? data : []);
            } catch (err) {
                console.error(`Failed to fetch ${source.url}:`, err);
            }
        }

        try {
            const services = await fetchStaffServiceConfig();
            setServicesConfig(services);
        } catch (err) {
            console.error('Failed to fetch staff service config:', err);
            setServicesConfig([]);
        }

        if (showRmField || showOpField) {
            try {
                const { activeRMs: rms, activeOps: ops } = await fetchAssignmentListsIfNeeded({
                    needRm: showRmField,
                    needOp: showOpField,
                });
                if (showRmField) setActiveRMs(rms);
                if (showOpField) setActiveOps(ops);
            } catch (err) {
                console.error('Failed to fetch active RM/OP lists:', err);
            }
        }

        setConfigLoading(false);
    }, [showRmField, showOpField]);

    useEffect(() => {
        if (isOpen) {
            fetchConfigData();
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'unset';

            // Reset form when modal closes
            setFormData({ ...INITIAL_CUSTOMER_FORM });
            setLocationResults([]);
            setShowLocationResults(false);

            setFieldErrors({});
            setError('');
            setIsSuccess(false);
        }

        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, fetchConfigData]);

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
                if (trimmedValue && trimmedValue.length > 200) errorMsg = 'Maximum 200 characters';
                break;
            case 'business_type':
                if (trimmedValue && trimmedValue.length > 50) errorMsg = 'Maximum 50 characters';
                break;
            case 'state':
                if (trimmedValue && trimmedValue.length > 100) errorMsg = 'Maximum 100 characters';
                break;
            case 'city':
                if (trimmedValue && trimmedValue.length > 100) errorMsg = 'Maximum 100 characters';
                break;
            case 'business_image_url':
                if (trimmedValue) {
                    try {
                        new URL(trimmedValue);
                    } catch (_) {
                        errorMsg = 'Invalid URL format';
                    }
                }
                break;
            case 'rm_id':
                if (showRmField && !trimmedValue) errorMsg = 'field required';
                break;
            case 'op_id':
                break;
            case 'referral_phone_number':
                errorMsg = validateReferralPhone(value);
                break;
            case 'language':
                if (trimmedValue && trimmedValue.length > 50) errorMsg = 'Maximum 50 characters';
                break;
            default:
                break;
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return !errorMsg;
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

        if (error) setError('');
    };

    // --- LOCATION SEARCH LOGIC ---
    useEffect(() => {
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

                const data = response.data;
                const locations = data.locations || [];
                setLocationResults(locations);
            } catch (err) {
                console.error("Location search failed:", err);
                setLocationResults([]);
            } finally {
                setLocationLoading(false);
            }
        }, 600);

        return () => clearTimeout(timer);
    }, [formData.city]);

    const handleSelectLocation = (loc) => {
        ignoreSearchRef.current = true;
        setFormData(prev => ({
            ...prev,
            state: loc.state?.toUpperCase().replace(/\s+/g, '_') || prev.state,
            city: loc.name || loc.district || prev.city
        }));
        setShowLocationResults(false);
        setIsLocationSelected(true);
        
        // Clear errors for auto-filled fields
        setFieldErrors(prev => ({ ...prev, state: null, city: null }));
    };

    const toggleService = (field, code) => {
        setFormData(prev => {
            const current = Array.isArray(prev[field]) ? prev[field] : [];
            const exists = current.includes(code);
            const next = exists ? current.filter(item => item !== code) : [...current, code];
            return { ...prev, [field]: next };
        });
    };

    const validateForm = () => {
        const fieldsToValidate = [
            'full_name', 'mobile', 'email',
            'business_type', 'state', 'city', 'business_image_url',
            'referral_phone_number',
        ];
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

    const handleGenerateDescription = async () => {
        if (!formData.business_name) {
            setFieldErrors(prev => ({ ...prev, business_name: 'Business name required for AI generation' }));
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
                addNotification('AI Generation Success', 'Professional business description has been generated.', 'INFO');
            }
        } catch (err) {
            console.error('AI Generation Error:', err);
            
            // Handle "not configured" case gracefully with a warning instead of a crash error
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

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!validateForm()) {
            setError('Please fix the validation errors below.');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const payload = buildCustomerCreatePayload(formData, profileData, businessTypes);
            await createCustomer(payload);

            addNotification(
                'New Customer Registered',
                `Customer ${formData.full_name} was added successfully.`,
                'CREATE'
            );

            setIsSuccess(true);
            setTimeout(() => {
                onSuccess();
                onClose();
            }, 2000);
        } catch (err) {
            // Reset previous field errors
            setFieldErrors({});

            // api.js interceptor already extracts backend error message
            setError(err?.message || "Request failed. Please try again.");

            // Highlight specific fields if backend returned validation fields
            if (err?.fields && typeof err.fields === "object") {
                setFieldErrors(err.fields);
            }
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    const serviceCategoryEntries = sortedStaffServiceCategoryEntries(
        groupStaffServicesByCategory(servicesConfig),
    );

    return (
        <div className="modal-overlay app-side-drawer-mode">
            <div className="modal-content-glass customer-modal">
                {isSuccess ? (
                    <div className="modal-success-state">
                        <div className="success-icon-wrapper">
                            <CheckCircle2 size={48} className="success-tick" />
                        </div>
                        <h2>Customer Registered!</h2>
                        <p>The profile has been successfully created.</p>
                    </div>
                ) : (
                    <div className="modal-form-wrapper">
                        <div className="modal-header">
                            <div className="header-header-top">
                                <div className="header-icon-box-v4">
                                    <User size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <h1 className="modal-title-v4">
                                        Register Customer <span className="header-badge-v4 create-mode">CREATE</span>
                                    </h1>
                                    <p className="modal-subtitle-v4">Onboard a new client to the system</p>
                                </div>
                            </div>
                            <button className="modal-close-btn" onClick={onClose} aria-label="Close">
                                <X size={20} />
                            </button>
                        </div>

                        <form onSubmit={handleSubmit} className="premium-form">
                            {error && (
                                <div className="form-error-banner-v2">
                                    <AlertCircle size={18} />
                                    <span className="error-item-v2">{error}</span>
                                </div>
                            )}

                            <div className="form-sections-container">
                                <div className="form-section-v4">
                                    <h3 className="section-title">1. Customer Details</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps" style={{ color: '#3b82f6' }}>Full Name *</label>
                                            <input
                                                type="text"
                                                name="full_name"
                                                placeholder="Enter full name"
                                                value={formData.full_name}
                                                onChange={handleChange}
                                                className={`modal-input-v4 ${fieldErrors.full_name ? 'error' : ''}`}
                                                required
                                            />
                                            {fieldErrors.full_name && <div className="field-error-msg">{fieldErrors.full_name}</div>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Mobile *</label>
                                            <input
                                                type="tel"
                                                name="mobile"
                                                placeholder="10 digit mobile"
                                                value={formData.mobile}
                                                onChange={handleChange}
                                                maxLength="10"
                                                className={`modal-input-v4 ${fieldErrors.mobile ? 'error' : ''}`}
                                                required
                                            />
                                            {fieldErrors.mobile && <div className="field-error-msg">{fieldErrors.mobile}</div>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Email</label>
                                            <input
                                                type="email"
                                                name="email"
                                                placeholder="Primary email"
                                                value={formData.email}
                                                onChange={handleChange}
                                                className={`modal-input-v4 ${fieldErrors.email ? 'error' : ''}`}
                                            />
                                            {fieldErrors.email && <div className="field-error-msg">{fieldErrors.email}</div>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Name</label>
                                            <input
                                                type="text"
                                                name="business_name"
                                                placeholder="Official business name"
                                                value={formData.business_name}
                                                onChange={handleChange}
                                                className={`modal-input-v4 ${fieldErrors.business_name ? 'error' : ''}`}
                                            />
                                            {fieldErrors.business_name && <div className="field-error-msg">{fieldErrors.business_name}</div>}
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
                                        {isBusinessTypeOther(formData.business_type, businessTypes) && (
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
                                            <FormCustomSelect
                                                name="language"
                                                value={formData.language}
                                                onChange={handleChange}
                                                options={optionsFromConfig(languages, 'Select Language')}
                                                placeholder="Select Language"
                                                ariaLabel="Preferred language"
                                            />
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">2. Location</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">State</label>
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
                                            <label className="modal-label-caps">City / Pincode Search</label>
                                            <div className="location-search-wrapper" style={{ position: 'relative' }}>
                                                <input
                                                    type="text"
                                                    name="city"
                                                    placeholder="Search city or pincode..."
                                                    value={formData.city}
                                                    onChange={handleChange}
                                                    onFocus={() => locationResults.length > 0 && setShowLocationResults(true)}
                                                    autoComplete="off"
                                                    className="modal-input-v4"
                                                    style={{ paddingRight: isLocationSelected ? '52px' : '36px' }}
                                                />
                                                <div style={{ position: 'absolute', right: '12px', top: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    {isLocationSelected && (
                                                        <X 
                                                            size={14} 
                                                            style={{ color: '#ef4444', cursor: 'pointer' }} 
                                                            onClick={() => {
                                                                setFormData(prev => ({ ...prev, city: '', state: '' }));
                                                                setIsLocationSelected(false);
                                                            }}
                                                        />
                                                    )}
                                                    {locationLoading ? (
                                                        <RotateCcw size={14} className="refresh-spin" style={{ color: 'rgba(var(--fg-rgb),0.2)' }} />
                                                    ) : (
                                                        <Search size={14} style={{ color: isLocationSelected ? 'rgba(var(--fg-rgb),0.2)' : '#2eb87a' }} />
                                                    )}
                                                </div>
                                                {showLocationResults && (
                                                    <div className="location-results-dropdown">
                                                        {locationLoading ? (
                                                            <div className="location-loading-item"><RotateCcw size={14} className="refresh-spin" /><span>Searching...</span></div>
                                                        ) : locationResults.length === 0 ? (
                                                            <div className="location-empty-item"><span>No results</span></div>
                                                        ) : (
                                                            locationResults.map((loc, idx) => (
                                                                <div key={idx} className="location-result-item" onClick={() => handleSelectLocation(loc)}>
                                                                    <span className="location-main-text">{loc.name}</span>
                                                                    <span className="location-sub-text">{loc.district}, {loc.state}</span>
                                                                </div>
                                                            ))
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Remark</label>
                                            <input type="text" name="remark" value={formData.remark} onChange={handleChange} className="modal-input-v4" placeholder="Internal remark" />
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">3. Assignments & Referral</h3>
                                    <div className="form-grid-3">
                                        {showRmField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Relationship Manager *</label>
                                            <FormCustomSelect
                                                name="rm_id"
                                                value={formData.rm_id}
                                                onChange={handleChange}
                                                options={optionsFromPairs(buildRmOpIdSelectOptions(activeRMs), 'Select RM')}
                                                placeholder="Select RM"
                                                ariaLabel="Relationship manager"
                                                error={Boolean(fieldErrors.rm_id)}
                                            />
                                        </div>
                                        )}
                                        {showOpField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Assigned OP</label>
                                            <FormCustomSelect
                                                name="op_id"
                                                value={formData.op_id}
                                                onChange={handleChange}
                                                options={optionsFromPairs(buildRmOpIdSelectOptions(activeOps), 'Select OP')}
                                                placeholder="Select OP"
                                                ariaLabel="Assigned OP"
                                            />
                                        </div>
                                        )}
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Referrer mobile (optional)</label>
                                            <input
                                                type="tel"
                                                name="referral_phone_number"
                                                value={formData.referral_phone_number}
                                                onChange={handleChange}
                                                maxLength="10"
                                                className={`modal-input-v4 ${fieldErrors.referral_phone_number ? 'error' : ''}`}
                                                placeholder="10 digit mobile"
                                            />
                                            {fieldErrors.referral_phone_number && (
                                                <div className="field-error-msg">{fieldErrors.referral_phone_number}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">4. Services Required</h3>
                                    <div className="services-grid services-grid--single">
                                        <div className={`services-card ${fieldErrors.service_required ? 'error' : ''}`}>
                                            <div className="services-card-header">
                                                <Shield size={16} />
                                                <span>Services Required</span>
                                            </div>
                                            <p className="services-hint-text" title={SERVICE_REQUIRED_CRM_HINT}>
                                                {SERVICE_REQUIRED_CRM_HINT}
                                            </p>
                                            {configLoading ? (
                                                <div className="services-loading-skeleton">
                                                    {[1, 2, 3].map(i => (
                                                        <div key={i} className="skeleton-line-v4 box-v4 skeleton-pulse-v4" style={{ height: '36px', marginBottom: '8px' }} />
                                                    ))}
                                                </div>
                                            ) : serviceCategoryEntries.length === 0 ? (
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
                                </div>

                                <div className="form-section-v4">
                                    <h3 className="section-title">5. Business Profile</h3>
                                    <div className="form-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Image URL</label>
                                            <textarea
                                                name="business_image_url"
                                                placeholder="https://..."
                                                value={formData.business_image_url}
                                                onChange={handleChange}
                                                rows="3"
                                                className="modal-input-v4"
                                                style={{ minHeight: '80px', resize: 'none' }}
                                            />
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Description</label>
                                            <div className="textarea-ai-wrapper">
                                                <textarea
                                                    name="business_description"
                                                    placeholder="Professional summary..."
                                                    value={formData.business_description || ''}
                                                    onChange={handleChange}
                                                    rows="3"
                                                    className="modal-input-v4"
                                                    style={{ minHeight: '80px', resize: 'none' }}
                                                />
                                                <button
                                                    type="button"
                                                    className="ai-generate-btn-nested"
                                                    onClick={handleGenerateDescription}
                                                    disabled={aiLoading || !formData.business_name}
                                                >
                                                    {aiLoading ? <RotateCcw size={12} className="refresh-spin" /> : <Sparkles size={12} />}
                                                    <span>{aiLoading ? 'Generating...' : 'AI Generate'}</span>
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer">
                                <button type="button" className="btn-secondary-link" onClick={onClose}>Cancel</button>
                                <button type="submit" className="btn-primary-glow" disabled={loading}>
                                    {loading ? <RotateCcw size={16} className="refresh-spin" /> : null}
                                    {loading ? 'Registering...' : 'Register Customer'}
                                </button>
                            </div>
                        </form>
                    </div>
                )}
            </div>
        </div>
    );
};

export default AddCustomerModal;
