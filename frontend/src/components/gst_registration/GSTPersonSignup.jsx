/**
 * @file GSTPersonSignup.jsx
 * @description Provides the UI for creating a new GST Stakeholder/Person.
 * Associates individuals (via PAN/Aadhaar validation) to specific GST Registration IDs.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../utils/api';
import './GSTPersonSignup.css';
import { User, X, CheckCircle2, AlertCircle, RotateCcw } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig } from '../common/selectOptionUtils';

const BASE_URL = import.meta.env.VITE_API_URL;

const GSTPersonSignup = () => {
    const [formData, setFormData] = useState({
        gst_registration_id: '',
        full_name: '',
        designation: '',
        pan: '',
        aadhaar: '',
        email: '',
        mobile: '',
        is_primary_customer: false,
    });

    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [fieldErrors, setFieldErrors] = useState({});
    const [success, setSuccess] = useState(false);
    const [designations, setDesignations] = useState([]);
    const [fetchingDesignations, setFetchingDesignations] = useState(false);
    const navigate = useNavigate();

    const fetchDesignations = async (gstId) => {
        if (!gstId) {
            setDesignations([]);
            return;
        }
        setFetchingDesignations(true);
        try {
            const res = await api.get(`/api/v1/gst-people/gst-registration/${gstId}/designations`);
            setDesignations(res.data.designations || []);
        } catch (err) {
            console.error("Error fetching designations:", err);
            setDesignations([]);
        } finally {
            setFetchingDesignations(false);
        }
    };

    useEffect(() => {
        const gstId = formData.gst_registration_id;
        if (gstId && !isNaN(gstId)) {
            const timer = setTimeout(() => {
                fetchDesignations(gstId);
            }, 500);
            return () => clearTimeout(timer);
        } else {
            setDesignations([]);
        }
    }, [formData.gst_registration_id]);

    const validateField = (name, value) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        switch (name) {
            case 'gst_registration_id':
                if (!trimmedValue) {
                    errorMsg = 'field required';
                } else if (parseInt(trimmedValue, 10) < 1) {
                    errorMsg = 'Must be at least 1';
                }
                break;
            case 'full_name':
                if (!trimmedValue) errorMsg = 'field required';
                break;
            case 'designation':
                if (!trimmedValue) errorMsg = 'field required';
                break;
            case 'pan':
                if (trimmedValue) {
                    const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
                    if (!panRegex.test(trimmedValue.toUpperCase())) errorMsg = 'Invalid PAN format(ABCDE1234F)';
                }
                break;
            case 'aadhaar':
                if (trimmedValue) {
                    const aadhaarRegex = /^\d{12}$/;
                    if (!aadhaarRegex.test(trimmedValue)) errorMsg = 'Aadhaar must be 12 digits(123456789012)';
                }
                break;
            case 'email':
                if (trimmedValue) {
                    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                    if (!emailRegex.test(trimmedValue)) errorMsg = 'Invalid email format(';
                }
                break;
            case 'mobile':
                if (trimmedValue) {
                    const phoneRegex = /^\d{10}$/;
                    if (!phoneRegex.test(trimmedValue)) errorMsg = 'Mobile must be 10 digits';
                }
                break;
            default:
                break;
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return !errorMsg;
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        const val = type === 'checkbox' ? checked : value;
        setFormData((prev) => ({
            ...prev,
            [name]: val,
        }));
        if (type !== 'checkbox') {
            validateField(name, val);
        }
    };

    const validateForm = () => {
        const fieldsToValidate = ['gst_registration_id', 'full_name', 'designation', 'pan', 'aadhaar', 'email', 'mobile'];
        let isValid = true;
        fieldsToValidate.forEach(field => {
            if (!validateField(field, formData[field])) {
                isValid = false;
            }
        });
        return isValid;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        if (!validateForm()) {
            setError('Please correct the highlighted fields.');
            return;
        }

        setLoading(true);

        try {
            const rawPayload = {
                ...formData,
                gst_registration_id: parseInt(formData.gst_registration_id, 10),
                pan: formData.pan ? formData.pan.toUpperCase() : null,
                aadhaar: formData.aadhaar || null,
                email: formData.email || null,
                mobile: formData.mobile || null,
            };

            // Remove empty strings so backend doesn't fail validation
            const payload = Object.fromEntries(
                Object.entries(rawPayload).filter(([_, v]) => v !== '' && v !== null)
            );

            await api.post(`/api/v1/gst-people`, payload);

            setSuccess(true);
            setTimeout(() => {
                navigate('/dashboard?tab=gst&sub=people');
            }, 2000);
        } catch (err) {
            console.error("GST Person creation failed:", err);

            const backendMessage =
                err?.response?.data?.detail ||
                err?.response?.data?.message ||
                err?.message;

            setError(backendMessage || 'Failed to create registration person');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="signup-page">
            <div className="bg-orb orb-1" />
            <div className="bg-orb orb-2" />
            <div className="grid-overlay" />

            <div className="gst-modal-card-v4 wide-modal standalone-v4-card" style={{ margin: '40px auto', maxWidth: '800px', position: 'relative', zIndex: 10 }}>
                {success ? (
                    <div className="gst-modal-success-state" style={{ padding: '60px 40px' }}>
                        <div className="gst-success-icon-wrapper">
                            <CheckCircle2 size={48} className="gst-success-tick" />
                        </div>
                        <h2 className="modal-title-v4">Stakeholder Created</h2>
                        <p className="modal-subtitle-v4">The registration person has been created successfully.</p>
                        <button className="gst-btn-primary" onClick={() => navigate('/dashboard?tab=gst&sub=people')} style={{ marginTop: '24px' }}>
                            Go to Dashboard
                        </button>
                    </div>
                ) : (
                    <>
                        <div className="modal-header-v4">
                            <div className="header-content-v4">
                                <div className="header-icon-box-v4" style={{ background: 'rgba(var(--success-rgb), 0.1)', color: 'var(--accent)' }}>
                                    <User size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <div className="modal-header-texts">
                                        <h2 className="modal-title-v4">New GST Stakeholder</h2>
                                        <p className="modal-subtitle-v4">Onboard a new person and associate with a GST profile</p>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <form className="modal-form-v4" onSubmit={handleSubmit}>
                            {error && (
                                <div className="gst-message-banner error" style={{ margin: '0 32px 24px' }}>
                                    <AlertCircle size={18} />
                                    <span className="gst-message-banner-text">{error}</span>
                                </div>
                            )}

                            <div className="form-scroll-container">
                                <div className="form-section-group">
                                    <h3 className="section-title">1. Relationship & Identity</h3>
                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">GST Registration ID*</label>
                                            <input 
                                                type="number" 
                                                name="gst_registration_id" 
                                                value={formData.gst_registration_id} 
                                                onChange={handleChange} 
                                                required 
                                                placeholder="e.g. 1" 
                                                className={`modal-input-v4 ${fieldErrors.gst_registration_id ? 'error' : ''}`} 
                                            />
                                            {fieldErrors.gst_registration_id && <span className="field-error-msg">{fieldErrors.gst_registration_id}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Full Name*</label>
                                            <input 
                                                type="text" 
                                                name="full_name" 
                                                value={formData.full_name} 
                                                onChange={handleChange} 
                                                required 
                                                className={`modal-input-v4 ${fieldErrors.full_name ? 'error' : ''}`} 
                                            />
                                            {fieldErrors.full_name && <span className="field-error-msg">{fieldErrors.full_name}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Designation*</label>
                                            <FormCustomSelect
                                                name="designation"
                                                value={formData.designation}
                                                onChange={handleChange}
                                                options={optionsFromConfig(
                                                    designations,
                                                    fetchingDesignations ? 'Loading...' : 'Select Designation'
                                                )}
                                                placeholder={fetchingDesignations ? 'Loading...' : 'Select Designation'}
                                                ariaLabel="Designation"
                                                disabled={fetchingDesignations || !formData.gst_registration_id}
                                                error={Boolean(fieldErrors.designation)}
                                            />
                                            {fieldErrors.designation && <span className="field-error-msg">{fieldErrors.designation}</span>}
                                            {!formData.gst_registration_id && <span className="field-info-msg">Enter GST Reg ID first</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">PAN</label>
                                            <input 
                                                type="text" 
                                                name="pan" 
                                                value={formData.pan} 
                                                onChange={handleChange} 
                                                placeholder="ABCDE1234F" 
                                                maxLength="10" 
                                                className={`modal-input-v4 ${fieldErrors.pan ? 'error' : ''}`} 
                                            />
                                            {fieldErrors.pan && <span className="field-error-msg">{fieldErrors.pan}</span>}
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-group" style={{ marginTop: '32px' }}>
                                    <h3 className="section-title">2. Contact Details</h3>
                                    <div className="form-grid-2">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Aadhaar</label>
                                            <input 
                                                type="text" 
                                                name="aadhaar" 
                                                value={formData.aadhaar} 
                                                onChange={handleChange} 
                                                placeholder="12-digit number" 
                                                maxLength="12" 
                                                className={`modal-input-v4 ${fieldErrors.aadhaar ? 'error' : ''}`} 
                                            />
                                            {fieldErrors.aadhaar && <span className="field-error-msg">{fieldErrors.aadhaar}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Mobile</label>
                                            <input 
                                                type="tel" 
                                                name="mobile" 
                                                value={formData.mobile} 
                                                onChange={handleChange} 
                                                maxLength="10" 
                                                placeholder="10-digit number" 
                                                className={`modal-input-v4 ${fieldErrors.mobile ? 'error' : ''}`} 
                                            />
                                            {fieldErrors.mobile && <span className="field-error-msg">{fieldErrors.mobile}</span>}
                                        </div>
                                        <div className="form-group-v4" style={{ gridColumn: 'span 2' }}>
                                            <label className="modal-label-caps">Email</label>
                                            <input 
                                                type="email" 
                                                name="email" 
                                                value={formData.email} 
                                                onChange={handleChange} 
                                                className={`modal-input-v4 ${fieldErrors.email ? 'error' : ''}`} 
                                            />
                                            {fieldErrors.email && <span className="field-error-msg">{fieldErrors.email}</span>}
                                        </div>
                                    </div>

                                    <div className="gst-checkbox-row-v4" style={{ marginTop: '20px' }}>
                                        <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-primary)' }}>
                                            <input 
                                                type="checkbox" 
                                                name="is_primary_customer" 
                                                checked={formData.is_primary_customer} 
                                                onChange={handleChange} 
                                                className="modal-checkbox-v4" 
                                            />
                                            <span>Primary Customer</span>
                                        </label>
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer-v4" style={{ padding: '24px 32px' }}>
                                <div className="footer-actions-v4">
                                    <button type="button" className="gst-btn-secondary" onClick={() => navigate('/dashboard?tab=gst&sub=people')}>
                                        Cancel
                                    </button>
                                    <button type="submit" className="gst-btn-primary" disabled={loading}>
                                        {loading && <RotateCcw size={16} className="gst-refresh-spin" />}
                                        {loading ? 'Processing...' : 'Create Person'}
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

export default GSTPersonSignup;
