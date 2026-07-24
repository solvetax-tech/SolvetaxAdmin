import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
    X, Shield, Save, RotateCcw, CheckCircle2, AlertCircle, Loader2, 
    Calculator, Building2, GanttChart, BookOpen, Briefcase, Layers, Check,
    Plus, Minus
} from 'lucide-react';
import './ManageCustomerServicesModal.css';
import api from '../../utils/api';
import { STAFF_SERVICE_CONFIG_PATH } from '../../utils/staffServiceConfigApi';
import { addNotification } from '../../utils/notificationUtils';

const ManageCustomerServicesModal = ({ isOpen, onClose, customerId, onSuccess }) => {
    const [customer, setCustomer] = useState(null);
    const [servicesConfig, setServicesConfig] = useState([]);
    const [loading, setLoading] = useState(true);
    const [subLoading, setSubLoading] = useState(false);
    const [error, setError] = useState(null);
    const [message, setMessage] = useState({ type: '', text: '' });
    
    // Draft state for selected services
    const [selectedRequired, setSelectedRequired] = useState([]);
    
    // UI state
    const [expandedCategories, setExpandedCategories] = useState(new Set());

    const toggleCategory = (type, category) => {
        const key = `${type}-${category}`;
        setExpandedCategories(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const fetchData = useCallback(async () => {
        if (!customerId) return;
        setLoading(true);
        setError(null);
        setMessage({ type: '', text: '' });

        try {
            const [custRes, servicesRes] = await Promise.all([
                api.get(`/api/v1/customers/${customerId}`),
                api.get(STAFF_SERVICE_CONFIG_PATH)
            ]);

            const custData = custRes.data || {};
            setCustomer(custData);
            setSelectedRequired(custData.service_required || []);
            setServicesConfig(servicesRes.data?.data || []);
        } catch (err) {
            setError(err?.message || "Failed to load management data.");
        } finally {
            setLoading(false);
        }
    }, [customerId]);

    useEffect(() => {
        if (isOpen && customerId) {
            fetchData();
        } else {
            setCustomer(null);
            setMessage({ type: '', text: '' });
        }
    }, [isOpen, customerId, fetchData]);

    const toggleService = (type, code) => {
        if (type === 'required') {
            setSelectedRequired(prev =>
                prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]
            );
        }
    };

    const handleSave = async () => {
        setSubLoading(true);
        setMessage({ type: '', text: '' });

        try {
            const payload = {
                service_required: selectedRequired,
            };

            await api.post(`/api/v1/customers/${customerId}/edit`, payload);
            
            setMessage({ type: 'success', text: 'Service assignments updated successfully! ✨' });
            
            addNotification(
                'Services Updated',
                `Service assignments for ${customer?.full_name || 'Customer'} were updated.`,
                'UPDATE'
            );

            if (onSuccess) onSuccess();
            
            setTimeout(() => {
                onClose();
            }, 1500);

        } catch (err) {
            setMessage({ type: 'error', text: err?.message || "Update failed." });
        } finally {
            setSubLoading(false);
        }
    };

    const categoryIconMap = {
        'ACCOUNTING': <Calculator size={14} />,
        'COMPANY': <Building2 size={14} />,
        'GST': <GanttChart size={14} />,
        'INCOME TAX': <BookOpen size={14} />,
        'BUSINESS': <Briefcase size={14} />,
        'DEFAULT': <Layers size={14} />
    };

    const servicesByCategory = useMemo(() => {
        return servicesConfig.reduce((acc, service) => {
            const category = service.service_category || 'OTHER';
            if (!acc[category]) acc[category] = [];
            acc[category].push(service);
            return acc;
        }, {});
    }, [servicesConfig]);

    const getSelectedNames = (codes) => {
        if (!codes || codes.length === 0) return [];
        return codes.map(code => {
            const svc = servicesConfig.find(s => s.service_code === code);
            return svc ? svc.service_name : code;
        });
    };

    if (!isOpen) return null;
    
    const ServicesSkeleton = () => (
        <div className="services-manager-grid services-manager-grid--single">
            {[1].map(col => (
                <div key={col} className="services-column-card skeleton">
                    <div className="column-card-header">
                        <div className="header-left-group">
                            <div className="skeleton-icon-v5 skeleton-pulse-v5" />
                            <div className="skeleton-line-v5 short skeleton-pulse-v5" />
                        </div>
                    </div>
                    <div className="services-list-container">
                        {[1, 2].map(cat => (
                            <div key={cat} className="service-category-group">
                                <div className="skeleton-line-v5 x-short skeleton-pulse-v5" style={{ marginBottom: '12px' }} />
                                {[1, 2, 3].map(item => (
                                    <div key={item} className="skeleton-line-v5 box-v5 skeleton-pulse-v5" style={{ marginBottom: '8px', height: '40px' }} />
                                ))}
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );

    const renderColumn = (type, title, icon, selectedList, accentClass) => {
        const IconComponent = icon;
        return (
            <div className={`services-column-card ${type}`}>
                <div className="column-card-header">
                    <div className="header-left-group">
                        <div className="header-icon-box">
                            <IconComponent size={18} />
                        </div>
                        <h3>{title}</h3>
                    </div>
                </div>
                <div className="services-list-container">
                    {Object.entries(servicesByCategory).map(([category, items]) => {
                        const key = `${type}-${category}`;
                        const isExpanded = expandedCategories.has(key);
                        const selectedInCategory = items.filter(svc => selectedList.includes(svc.service_code)).length;

                        return (
                            <div key={key} className={`service-category-group ${isExpanded ? 'expanded' : 'collapsed'}`}>
                                <div 
                                    className="category-header-v5 clickable" 
                                    onClick={() => toggleCategory(type, category)}
                                >
                                    <div className="category-header-left">
                                        <span className="category-icon-v5">{categoryIconMap[category] || categoryIconMap['DEFAULT']}</span>
                                        <span className="category-label">{category}</span>
                                        {selectedInCategory > 0 && (
                                            <span className="category-selection-count-v5">
                                                {selectedInCategory}
                                            </span>
                                        )}
                                    </div>
                                    <div className="category-toggle-icon">
                                        {isExpanded ? <Minus size={14} /> : <Plus size={14} />}
                                    </div>
                                </div>
                                {isExpanded && (
                                    <div className="services-options-list">
                                        {items.map(svc => {
                                            const isChecked = selectedList.includes(svc.service_code);
                                            return (
                                                <label 
                                                    className={`service-checkbox-item ${isChecked ? 'checked' : ''}`} 
                                                    key={`${type}-${svc.id}`}
                                                >
                                                    <input 
                                                        type="checkbox" 
                                                        hidden
                                                        checked={isChecked}
                                                        onChange={() => toggleService(type, svc.service_code)}
                                                    />
                                                    <div className="st-checkbox-v5">
                                                        <Check size={12} className="st-checkmark-icon" />
                                                    </div>
                                                    <span className="service-name-text" title={svc.service_name}>{svc.service_name}</span>
                                                </label>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    };

    return (
        <div className="modal-overlay app-side-drawer-mode">
            <div className="modal-content-glass manage-services-modal">
                <div className="modal-header">
                    <button className="modal-close-btn" onClick={onClose} aria-label="Close">
                        <X size={20} />
                    </button>
                    <div className="msm-header-titlerow">
                        <h1>Manage Services</h1>
                        <span className="header-badge-v4 config-mode">CONFIGURATION</span>
                    </div>
                    <p className="msm-header-sub">
                        <strong>{customer?.full_name || `Customer #${customerId}`}</strong>
                        <span className="msm-id-pill">ID {customerId}</span>
                    </p>
                </div>

                <div className="modal-body">
                    {loading ? (
                        <ServicesSkeleton />
                    ) : error ? (
                        <div className="message-banner-v5 error">
                            <AlertCircle size={18} />
                            {error}
                        </div>
                    ) : (
                        <>
                            {message.text && (
                                <div className={`message-banner-v5 ${message.type}`}>
                                    {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                                    {message.text}
                                </div>
                            )}

                            <div className="services-summary-bar-v5 required">
                                <div className="summary-hero-v5">
                                    <div className="summary-hero-badge"><Shield size={22} /></div>
                                    <div className="summary-hero-count">{selectedRequired.length}</div>
                                    <div className="summary-hero-meta">
                                        <span className="summary-hero-title">Services Selected</span>
                                        <span className="summary-hero-sub">Required for {customer?.full_name || `customer #${customerId}`}</span>
                                    </div>
                                </div>
                                <div className="summary-chips-wrap-v5">
                                    {selectedRequired.length === 0 ? (
                                        <span className="summary-empty-v5">No services selected yet — pick from the categories below.</span>
                                    ) : (
                                        <div className="summary-chips-v5">
                                            {getSelectedNames(selectedRequired).map((name, i) => (
                                                <span key={i} className="service-chip-v5">{name}</span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="services-manager-grid services-manager-grid--single">
                                {renderColumn('required', 'Services Required', Shield, selectedRequired)}
                            </div>
                        </>
                    )}
                </div>

                <div className="modal-footer">
                    <button className="btn-secondary-link" onClick={onClose} disabled={subLoading}>
                        Cancel
                    </button>
                    <button 
                        className="btn-primary-v4" 
                        onClick={handleSave} 
                        disabled={subLoading || loading}
                        style={{ minWidth: '180px' }}
                    >
                        {subLoading ? <Loader2 size={18} className="refresh-spin" /> : <Save size={18} />}
                        {subLoading ? 'Updating...' : 'Save Assignments'}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ManageCustomerServicesModal;
