/**
 * @file gst_registration.jsx
 * @description Manages the GST Registration listing and detailed view.
 * Handles extensive dynamic filtering options and provides the UI for entering 
 * new GST records or editing existing ones securely.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useLocation } from 'react-router-dom';
import '../Dashboard.css';
import '../employees/EmployeeDetailsModal.css';
import './gst_registration.css';
import './GSTRegistrationSignup.css';
import api from '../../utils/api';
import {
    getRmOpAssignmentVisibility,
    resolveRmIdForPayload,
    resolveOpIdForPayload,
    canManageRmOpRecords,
} from '../../utils/rmOpAssignmentFields';
import {
    fetchActiveRmEmployees,
    fetchActiveOpEmployees,
    buildRmOpSelectOptions,
    lookupAssigneeUsername,
    withAssignmentFormFields,
} from '../../utils/activeEmployees';
import LoadingOverlay from '../common/LoadingOverlay';
import Pagination from '../common/Pagination';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import { Filter, X, RotateCcw, Plus, AlertCircle, CheckCircle2, Users, FileText, LayoutDashboard, Eye, Pencil, CalendarClock, CreditCard } from 'lucide-react';
import {
    buildGstCrmLeadActionSearchParams,
    getCrmLeadByGstRegistrationId,
    isGstCrmStageForSchedulePayment,
} from '../../utils/gstRegistrationApi';
import {
    handleDrawerCancelEdit,
    shouldCloseDrawerAfterSave,
} from '../../utils/drawerEditFlow';
import {
    AppDrawerFooter,
    AppDrawerBtnDelete,
    AppDrawerBtnCancel,
    AppDrawerBtnSave,
} from '../common/AppDrawerEditFooter';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig, optionsFromPairs } from '../common/selectOptionUtils';
import GSTRegistrationSignup from './GSTRegistrationSignup';
import { GSTPeople } from './gst_people';
import { GSTDocuments } from './gst_documents';
import { TableSkeleton } from '../gst_filings/gst_filings';
import '../gst_filings/gst_filings.css';
import GSTRegistrationViewPanel from './GSTRegistrationViewPanel';
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

export const GSTRegistration = ({ handleLogout, isAdmin, profileData, initialSubTab }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [activeTab, setActiveTab] = useState(initialSubTab || 'registrations');
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [totalPages, setTotalPages] = useState(1);
    const [currentPage, setCurrentPage] = useState(1);
    const [showFilterDrawer, setShowFilterDrawer] = useState(false);
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showEditModal, setShowEditModal] = useState(false);
    const [editModalMode, setEditModalMode] = useState(false);
    const [selectedGstItem, setSelectedGstItem] = useState(null);
    const [showInactiveNotice, setShowInactiveNotice] = useState(false);
    const [inactiveActionLoading, setInactiveActionLoading] = useState(false);
    const [viewModalOpen, setViewModalOpen] = useState(false);
    const [viewRecordId, setViewRecordId] = useState(null);
    const rowsPerPage = 20;
    const [peopleToolbar, setPeopleToolbar] = useState(null);
    const [documentsToolbar, setDocumentsToolbar] = useState(null);

    const [configs, setConfigs] = useState({
        registrationTypes: [],
        ownershipCategories: [],
        businessTypes: [],
        states: [],
        turnoverDetailsList: [],
        registrationStatuses: [],
        activeRMs: [],
        activeOps: []
    });

    const [filterInputs, setFilterInputs] = useState({
        gstin: '', mobile: '', email: '', secondary_email: '',
        state: '', registration_status: '', ownership_category: '',
        business_type: '', registration_type: '', turnover_details: '',
        customer_id: '', rm_id: '', gst_registration_id: '',
        is_active: '', include_inactive: true,
        filing_preference: '', has_service: '',
        from_date: '', to_date: ''
    });

    const [appliedFilters, setAppliedFilters] = useState({
        gstin: '', mobile: '', email: '', secondary_email: '',
        state: '', registration_status: '', ownership_category: '',
        business_type: '', registration_type: '', turnover_details: '',
        customer_id: '', rm_id: '', gst_registration_id: '',
        is_active: '', include_inactive: true,
        filing_preference: '', has_service: '',
        from_date: '', to_date: ''
    });

    const fetchGstData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            
            // Build parameters, excluding defaults that might interfere if not strictly needed
            Object.entries(appliedFilters).forEach(([key, value]) => {
                if (value !== '' && value !== null && value !== undefined) {
                    // Only send include_inactive if it's explicitly part of the filter logic
                    if (key === 'include_inactive' && value === true) return; 
                    
                    const paramValue = typeof value === 'boolean' ? value.toString() : value;
                    params.append(key, paramValue);
                }
            });
            
            params.append('offset', (currentPage - 1) * rowsPerPage);
            params.append('limit', rowsPerPage);

            const response = await api.get(`/api/v1/gst-registrations/dynamic_filter?${params.toString()}`);

            const result = response.data;
            // Robust item extraction from various possible backend formats
            let items = [];
            if (Array.isArray(result)) {
                items = result;
            } else if (result && typeof result === 'object') {
                items = result.data || result.results || result.items || result.registrations || [];
            }
            
            if (!Array.isArray(items)) items = [];
            setData(items);
            
            // Total count handling
            const totalCount = result.total !== undefined ? result.total : (result.total_count !== undefined ? result.total_count : result.count);
            if (totalCount !== undefined) {
                setTotalPages(Math.ceil(totalCount / rowsPerPage));
            } else {
                setTotalPages(items.length < rowsPerPage ? currentPage : currentPage + 1);
            }
        } catch (err) {
            console.error("GST Fetch Error:", err);
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [appliedFilters, currentPage]);

    const GstRegTableSkeleton = () => (
        <div className="filings-ledger-body">
            {[...Array(12)].map((_, i) => (
                <div key={i} className="filings-ledger-row gst-reg-grid-template">
                    {[...Array(14)].map((_, j) => (
                        <div key={j} className="filings-ledger-cell">
                            <div className="filings-ledger-skeleton-bar" />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );

    useEffect(() => {
        if (activeTab === 'registrations') {
            fetchGstData();
        }
    }, [fetchGstData, activeTab]);

    useEffect(() => {
        if (initialSubTab && initialSubTab !== activeTab) {
            setActiveTab(initialSubTab);
        }
    }, [initialSubTab]);

    useEffect(() => {
        const fetchConfigs = async () => {
            const configSources = [
                { url: `/api/v1/gst-registration/config/registration-type`, key: 'registrationTypes' },
                { url: `/api/v1/gst-registration/config/ownership-category`, key: 'ownershipCategories' },
                { url: `/api/v1/gst-registration/config/business-type`, key: 'businessTypes' },
                { url: `/api/v1/gst-registration/config/state`, key: 'states' },
                { url: `/api/v1/gst-registration/config/turnover-details`, key: 'turnoverDetailsList' },
                { url: `/api/v1/gst-registration/config/registration-status`, key: 'registrationStatuses' },
                { url: `/api/v1/gst-registration/config/language`, key: 'languages' }
            ];

            const newConfigs = { ...configs };
            await Promise.all(configSources.map(async (source) => {
                try {
                    const response = await api.get(source.url);
                    newConfigs[source.key] = response.data?.data || response.data;
                } catch (err) { /* Silently fail config fetch */ }
            }));
            try {
                const [activeRMs, activeOps] = await Promise.all([
                    fetchActiveRmEmployees(),
                    fetchActiveOpEmployees(),
                ]);
                newConfigs.activeRMs = activeRMs;
                newConfigs.activeOps = activeOps;
            } catch (err) { /* Silently fail */ }
            setConfigs(newConfigs);
        };
        fetchConfigs();
    }, []);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const cid = params.get('customer_id');
        const gid = params.get('gst_registration_id');
        const gstin = params.get('gstin');
        if (cid) {
            setFilterInputs(prev => ({ ...prev, customer_id: cid }));
            setAppliedFilters(prev => ({ ...prev, customer_id: cid }));
            setCurrentPage(1);
        }
        if (gid) {
            setFilterInputs(prev => ({ ...prev, gst_registration_id: gid }));
            setAppliedFilters(prev => ({ ...prev, gst_registration_id: gid }));
            setCurrentPage(1);
        }
        if (gstin) {
            setFilterInputs(prev => ({ ...prev, gstin }));
            setAppliedFilters(prev => ({ ...prev, gstin }));
            setCurrentPage(1);
        }
    }, [location.search]);

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const openEditModal = (item) => {
        if (item?.is_active === false) {
            setSelectedGstItem(item);
            setShowInactiveNotice(true);
            return;
        }
        setSelectedGstItem(item);
        setEditModalMode(true);
        setShowEditModal(true);
    };

    const handleSearch = () => {
        setCurrentPage(1);
        setAppliedFilters({ ...filterInputs });
        setShowFilterDrawer(false);
    };

    const clearFilters = () => {
        const empty = {
            gstin: '', mobile: '', email: '', secondary_email: '',
            state: '', registration_status: '', ownership_category: '',
            business_type: '', registration_type: '', turnover_details: '',
            customer_id: '', rm_id: '', gst_registration_id: '',
            is_active: '', include_inactive: true,
            filing_preference: '', has_service: '',
            from_date: '', to_date: ''
        };
        setFilterInputs(empty);
        setAppliedFilters(empty);
        setCurrentPage(1);
    };

    const removeFilter = (key) => {
        const resetValue = (key === 'include_inactive') ? true : '';
        setFilterInputs(prev => ({ ...prev, [key]: resetValue }));
        setAppliedFilters(prev => ({ ...prev, [key]: resetValue }));
        setCurrentPage(1);
    };

    const renderFilterChips = () => {
        const labels = {
            gstin: 'GSTIN', mobile: 'Mobile', email: 'Email',
            state: 'State', registration_status: 'Status',
            rm_id: 'RM', from_date: 'From', to_date: 'To',
            customer_id: 'Customer', gst_registration_id: 'GST ID'
        };

        return Object.entries(appliedFilters)
            .filter(([key, value]) => {
                if (key === 'include_inactive') return false;
                return value !== '' && value !== null;
            })
            .map(([key, value]) => (
                <div key={key} className="filter-chip">
                    <span className="filter-chip-label">{labels[key] || key}:</span>
                    <span className="filter-chip-value">{value}</span>
                    <button className="btn-remove-chip" onClick={() => removeFilter(key)}>
                        <X size={12} />
                    </button>
                </div>
            ));
    };

    const renderStatusFilter = (value, onChange) => (
        <div className="filter-field">
            <label>Active Status</label>
            <FormCustomSelect
                name="is_active"
                value={value}
                onChange={onChange}
                options={optionsFromPairs([
                    { value: '', label: 'All Status' },
                    { value: 'true', label: 'Active Only' },
                    { value: 'false', label: 'Inactive Only' },
                ])}
                placeholder="All Status"
                ariaLabel="Active status"
            />
        </div>
    );

    const renderFilterFields = () => (
        <div className="drawer-content">
            <div className="filter-section-v4">
                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px' }}>Account Identifiers</h4>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                    <div className="filter-group-v4">
                        <label>GSTIN</label>
                        <input name="gstin" value={filterInputs.gstin} onChange={handleFilterChange} placeholder="Enter GSTIN..." />
                    </div>
                    <div className="filter-group-v4">
                        <label>GST ID</label>
                        <input type="number" name="gst_registration_id" value={filterInputs.gst_registration_id} onChange={handleFilterChange} placeholder="Enter GST ID..." />
                    </div>
                </div>
                <div className="filter-group-v4" style={{ marginTop: '12px' }}>
                    <label>Customer ID</label>
                    <input type="number" name="customer_id" value={filterInputs.customer_id} onChange={handleFilterChange} placeholder="Enter ID..." />
                </div>
            </div>

            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

            <div className="filter-section-v4">
                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px' }}>Registration Profile</h4>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px', marginBottom: '12px' }}>
                    <div className="filter-group-v4">
                        <label>Reg Status</label>
                        <FormCustomSelect
                            name="registration_status"
                            value={filterInputs.registration_status}
                            onChange={handleFilterChange}
                            options={optionsFromConfig(configs.registrationStatuses, 'All Status')}
                            placeholder="All Status"
                            ariaLabel="Registration status"
                        />
                    </div>
                    <div className="filter-group-v4">
                        <label>State Jurisdiction</label>
                        <FormCustomSelect
                            name="state"
                            value={filterInputs.state}
                            onChange={handleFilterChange}
                            options={optionsFromConfig(configs.states, 'All States')}
                            placeholder="All States"
                            ariaLabel="State"
                        />
                    </div>
                </div>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                    <div className="filter-group-v4">
                        <label>Profile Type</label>
                        <FormCustomSelect
                            name="registration_type"
                            value={filterInputs.registration_type}
                            onChange={handleFilterChange}
                            options={optionsFromConfig(configs.registrationTypes, 'Any Profile')}
                            placeholder="Any Profile"
                            ariaLabel="Profile type"
                        />
                    </div>
                    <div className="filter-group-v4">
                        <label>Entity Category</label>
                        <FormCustomSelect
                            name="business_type"
                            value={filterInputs.business_type}
                            onChange={handleFilterChange}
                            options={optionsFromConfig(configs.businessTypes, 'Any Category')}
                            placeholder="Any Category"
                            ariaLabel="Entity category"
                        />
                    </div>
                </div>
            </div>

            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

            <div className="filter-section-v4">
                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px' }}>Assignment & Ownership</h4>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                    <div className="filter-group-v4">
                        <label>Assignee (RM)</label>
                        <FormCustomSelect
                            name="rm_id"
                            value={filterInputs.rm_id}
                            onChange={handleFilterChange}
                            options={optionsFromPairs(buildRmOpSelectOptions(configs.activeRMs), 'Any RM')}
                            placeholder="Any RM"
                            ariaLabel="Assignee RM"
                        />
                    </div>
                    <div className="filter-group-v4">
                        <label>Filing Frequency</label>
                        <FormCustomSelect
                            name="filing_preference"
                            value={filterInputs.filing_preference}
                            onChange={handleFilterChange}
                            options={optionsFromPairs([
                                { value: '', label: 'Any Frequency' },
                                { value: 'MONTHLY', label: 'Monthly' },
                                { value: 'QUARTERLY', label: 'Quarterly' },
                            ])}
                            placeholder="Any Frequency"
                            ariaLabel="Filing frequency"
                        />
                    </div>
                </div>
            </div>

            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

            <div className="filter-section-v4">
                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px' }}>Contact Details</h4>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                    <div className="filter-group-v4">
                        <label>Mobile</label>
                        <input name="mobile" value={filterInputs.mobile} onChange={handleFilterChange} placeholder="Mobile..." />
                    </div>
                    <div className="filter-group-v4">
                        <label>Email Address</label>
                        <input name="email" value={filterInputs.email} onChange={handleFilterChange} placeholder="Email..." />
                    </div>
                </div>
            </div>

            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

            <div className="filter-section-v4">
                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px' }}>System Attributes</h4>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px', marginBottom: '12px' }}>
                    <div className="filter-group-v4">
                        <label>Service Status</label>
                        <FormCustomSelect
                            name="has_service"
                            value={filterInputs.has_service}
                            onChange={handleFilterChange}
                            options={optionsFromPairs([
                                { value: '', label: 'All Services' },
                                { value: 'true', label: 'Active Service' },
                                { value: 'false', label: 'No Service' },
                            ])}
                            placeholder="All Services"
                            ariaLabel="Service status"
                        />
                    </div>
                    <div className="filter-group-v4">
                        <label>Active State</label>
                        <FormCustomSelect
                            name="is_active"
                            value={filterInputs.is_active}
                            onChange={handleFilterChange}
                            options={optionsFromPairs([
                                { value: '', label: 'Any State' },
                                { value: 'true', label: 'Active Only' },
                                { value: 'false', label: 'Inactive Only' },
                            ])}
                            placeholder="Any State"
                            ariaLabel="Active state"
                        />
                    </div>
                </div>
                <div className="filter-group-v4">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <input 
                            type="checkbox" 
                            name="include_inactive" 
                            checked={filterInputs.include_inactive} 
                            onChange={(e) => setFilterInputs(p => ({ ...p, include_inactive: e.target.checked }))} 
                            style={{ width: 'auto' }} 
                        />
                        <label style={{ cursor: 'pointer', textTransform: 'none', opacity: 1, fontSize: '11px', color: 'var(--text-primary)' }}>Include Inactive History</label>
                    </div>
                </div>
            </div>

            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

            <div className="filter-section-v4">
                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px' }}>Audit Timeline</h4>
                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                    <div className="filter-group-v4">
                        <label>From Date</label>
                        <FilterDateInput name="from_date" value={filterInputs.from_date} onChange={handleFilterChange} ariaLabel="From date" />
                    </div>
                    <div className="filter-group-v4">
                        <label>To Date</label>
                        <FilterDateInput name="to_date" value={filterInputs.to_date} onChange={handleFilterChange} ariaLabel="To date" />
                    </div>
                </div>
            </div>
        </div>
    );

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try {
            return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
        } catch {
            return dtStr;
        }
    };

    const getRmDisplayName = (item) => {
        if (item?.rm_username) return item.rm_username;
        if (item?.rm_name) return item.rm_name;
        const rmId = item?.rm_id;
        if (!rmId) return '-';
        return lookupAssigneeUsername(rmId, configs.activeRMs) || `ID: ${rmId}`;
    };

    const getOpDisplayName = (item) => {
        if (item?.op_username) return item.op_username;
        if (item?.created_by_name) return item.created_by_name;
        if (item?.op_name) return item.op_name;
        const opId = item?.created_by;
        if (!opId) return '-';
        return lookupAssigneeUsername(opId, configs.activeOps) || `ID: ${opId}`;
    };

    const hasActiveRegFilters = Object.entries(appliedFilters).some(([key, value]) => {
        if (key === 'include_inactive') return false;
        return value !== '' && value !== null;
    });

    return (
        <div className="gst-main-content gst-portal-page">
            <div className="gst-portal-top-row">
                <div className="dashboard-sub-nav-v4">
                <button
                    className={`sub-nav-btn-v4 ${activeTab === 'registrations' ? 'active' : ''}`}
                    onClick={() => setActiveTab('registrations')}
                >
                    <LayoutDashboard size={14} />
                    <span>Registrations</span>
                </button>
                <button
                    className={`sub-nav-btn-v4 ${activeTab === 'people' ? 'active' : ''}`}
                    onClick={() => setActiveTab('people')}
                >
                    <Users size={14} />
                    <span>People</span>
                </button>
                <button
                    className={`sub-nav-btn-v4 ${activeTab === 'documents' ? 'active' : ''}`}
                    onClick={() => setActiveTab('documents')}
                >
                    <FileText size={14} />
                    <span>Documents</span>
                </button>
            </div>


                <div className="gst-portal-top-actions">
                    {activeTab === 'registrations' && (
                    <>
                        <button
                            type="button"
                            className="btn-gst-payments-entry"
                            onClick={() =>
                                navigate(
                                    '/dashboard?tab=add-payment&service_type=GST_REGISTRATION&return_tab=gst&return_sub=registrations'
                                )
                            }
                            title="Create GST registration payment"
                        >
                            <CreditCard size={13} /> Record Payment
                        </button>
                        <button type="button" className="btn-filter-trigger" onClick={() => setShowFilterDrawer(true)}>
                            <Filter size={13} /> Filters
                        </button>
                        {hasActiveRegFilters && (
                            <button type="button" className="btn-clear-v2" onClick={clearFilters}>
                                <RotateCcw size={14} /> Reset Filters
                            </button>
                        )}
                        {canManageRmOpRecords(profileData, isAdmin) && (
                            <button type="button" className="btn-primary-action" onClick={() => setShowCreateModal(true)}>
                                <Plus size={13} />
                                <span>Create GST</span>
                            </button>
                        )}
                    </>
                    )}
                    {activeTab === 'people' && peopleToolbar}
                    {activeTab === 'documents' && documentsToolbar}
                </div>
            </div>

            {activeTab === 'people' ? (
                <GSTPeople handleLogout={handleLogout} isAdmin={isAdmin} profileData={profileData} onRenderToolbar={setPeopleToolbar} />
            ) : activeTab === 'documents' ? (
                <GSTDocuments handleLogout={handleLogout} isAdmin={isAdmin} profileData={profileData} onRenderToolbar={setDocumentsToolbar} />
            ) : (
                <div className="gst-registration-container">
                    {hasActiveRegFilters && (
                        <div className="gst-portal-filter-chips-row">
                            <div className="active-filters-container">
                                {renderFilterChips()}
                            </div>
                        </div>
                    )}

                                        {/* Unified Filter Drawer */}
                    {showFilterDrawer && (
                        <div className="gst-filters-drawer-overlay" onClick={() => setShowFilterDrawer(false)}>
                            <div className="gst-filters-drawer" onClick={e => e.stopPropagation()}>
                                <div className="drawer-header">
                                    <h2>Filter GST Registrations</h2>
                                    <button className="btn-drawer-close" onClick={() => setShowFilterDrawer(false)}><X size={20} /></button>
                                </div>
                                <div className="drawer-content">
                                    {renderFilterFields()}
                                </div>
                                <div className="drawer-footer">
                                    <button className="btn-reset-v4" onClick={clearFilters}>Reset All</button>
                                    <button className="btn-apply-v4" onClick={handleSearch}>Apply Filters</button>
                                </div>
                            </div>
                        </div>
                    )}

                    <main className="gst-main-content-table">
                        <div className="gst-table-wrapper gst-table-wrapper--portal">
                            <div className="gst-table-container gst-table-container--portal">
                                <div className="filings-ledger-header gst-reg-grid-template">
                                    <div className="filings-ledger-header-cell">ID</div>
                                    <div className="filings-ledger-header-cell">Customer ID</div>
                                    <div className="filings-ledger-header-cell">Username</div>
                                    <div className="filings-ledger-header-cell">Password</div>
                                    <div className="filings-ledger-header-cell gst-ledger-gstin-header">GSTIN</div>
                                    <div className="filings-ledger-header-cell">Business Name</div>
                                    <div className="filings-ledger-header-cell">Reg Type</div>
                                    <div className="filings-ledger-header-cell">Ownership</div>
                                    <div className="filings-ledger-header-cell">Business Type</div>
                                    <div className="filings-ledger-header-cell">State</div>
                                    <div className="filings-ledger-header-cell">Filing Pref</div>
                                    <div className="filings-ledger-header-cell">RM Name</div>
                                    <div className="filings-ledger-header-cell">Assigned OP</div>
                                    <div className="filings-ledger-header-cell gst-sticky-actions" style={{ justifyContent: 'center' }}>Actions</div>
                                </div>
                                {loading ? (
                                    <GstRegTableSkeleton />
                                ) : error ? (
                                    <div className="employee-table-error">Error: {error}</div>
                                ) : data.length === 0 ? (
                                    <div className="gst-no-data-v4">
                                        <div className="no-data-icon-box">
                                            <FileText size={40} />
                                        </div>
                                        <h3>No Registrations Found</h3>
                                        <p>We couldn't find any GST registrations matching your current filters.</p>
                                        <button className="btn-reset-v4" onClick={clearFilters} style={{ marginTop: '16px' }}>
                                            Clear All Filters
                                        </button>
                                    </div>
                                ) : (
                                    <div className="filings-ledger-body">
                                        {data.map((item, idx) => (
                                            <div 
                                                key={idx} 
                                                className="filings-ledger-row gst-reg-grid-template gst-table-row gst-table-row--static"
                                            >
                                                <div className="filings-ledger-cell gst-reg-id-cell" style={{ color: '#2eb87a', fontWeight: 700 }}>{item.id}</div>
                                                <div className="filings-ledger-cell">
                                                    {item.customer_id ?? '-'}
                                                </div>
                                                <div className="filings-ledger-cell" title={item.username || ''}>{item.username || '-'}</div>
                                                <div className="filings-ledger-cell" title={item.password || ''}>{item.password || '-'}</div>
                                                <div className="filings-ledger-cell" style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{item.gstin}</div>
                                                <div className="filings-ledger-cell" style={{ fontWeight: '600' }} title={item.business_name || item.legal_name || item.username || ''}>{item.business_name || item.legal_name || item.username || '-'}</div>
                                                <div className="filings-ledger-cell" title={item.registration_type || ''}>{item.registration_type || '-'}</div>
                                                <div className="filings-ledger-cell" title={item.ownership_category || ''}>{item.ownership_category || '-'}</div>
                                                <div className="filings-ledger-cell" title={item.business_type || ''}>{item.business_type || '-'}</div>
                                                <div className="filings-ledger-cell">{item.state || '-'}</div>
                                                <div className="filings-ledger-cell">{item.filing_preference || '-'}</div>
                                                <div className="filings-ledger-cell" title={getRmDisplayName(item)}>{getRmDisplayName(item)}</div>
                                                <div className="filings-ledger-cell" title={item.created_by_name || item.op_name || ''}>{getOpDisplayName(item)}</div>
                                                <div className="filings-ledger-cell gst-action-buttons gst-sticky-actions" style={{ justifyContent: 'center' }}>
                                                    <button 
                                                        className="btn-view-action" 
                                                        title="View Details" 
                                                        onClick={(e) => { 
                                                            e.stopPropagation(); 
                                                            setViewRecordId(item.id); 
                                                            setViewModalOpen(true); 
                                                        }}
                                                    >
                                                        <Eye size={14} />
                                                    </button>
                                                    <button 
                                                        className="btn-edit-action" 
                                                        title="Edit Record" 
                                                        onClick={(e) => { 
                                                            e.stopPropagation(); 
                                                            openEditModal(item);
                                                        }}
                                                    >
                                                        <Pencil size={14} /> 
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <Pagination
                                currentPage={currentPage}
                                onPageChange={setCurrentPage}
                                hasMore={currentPage < totalPages}
                                loading={loading}
                            />
                        </div>
                    </main>

            <GSTRegistrationSignup
                isOpen={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                profileData={profileData}
                onSuccess={() => {
                    fetchGstData();
                }}
            />

            <GSTRegistrationDetails
                key={selectedGstItem ? `gst-reg-${selectedGstItem.id}-${editModalMode}` : 'gst-reg-closed'}
                isOpen={showEditModal}
                itemData={selectedGstItem}
                isAdmin={isAdmin}
                profileData={profileData}
                initialEditMode={editModalMode}
                onClose={() => {
                    setShowEditModal(false);
                    setSelectedGstItem(null);
                    setEditModalMode(false);
                }}
                onUpdated={() => {
                    fetchGstData();
                }}
            />

            {showInactiveNotice && (
                <div className="gst-confirm-overlay">
                    <div className="gst-confirm-content">
                        <div className="gst-confirm-icon">
                            <AlertCircle size={32} color="#f59e0b" />
                        </div>
                        <h2>GST Inactive</h2>
                        <p>This GST registration is inactive. Please activate it before editing details.</p>
                        <div className="gst-confirm-actions">
                            <button
                                className="gst-btn-secondary"
                                onClick={() => setShowInactiveNotice(false)}
                                disabled={inactiveActionLoading}
                            >
                                Close
                            </button>
                            <button
                                className="gst-btn-success"
                                onClick={async () => {
                                    if (!selectedGstItem?.id) return;
                                    setInactiveActionLoading(true);
                                    try {
                                        await api.post(`/api/v1/gst-registrations/${selectedGstItem.id}/activate`);
                                        setShowInactiveNotice(false);
                                        setSelectedGstItem(null);
                                        fetchGstData();
                                    } finally {
                                        setInactiveActionLoading(false);
                                    }
                                }}
                                disabled={inactiveActionLoading}
                            >
                                {inactiveActionLoading ? <RotateCcw size={16} className="gst-refresh-spin" /> : null}
                                {inactiveActionLoading ? 'Activating...' : 'Activate'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <GSTRegistrationViewPanel 
                isOpen={viewModalOpen} 
                onClose={() => setViewModalOpen(false)} 
                recordId={viewRecordId} 
                configs={configs}
                profileData={profileData}
                onUpdate={() => fetchGstData()}
            />
            </div>
            )}
        </div>
    );
};

export const GSTRegistrationDetails = ({ onLogout, itemData, isOpen = true, onClose, onUpdated, isAdmin: isAdminProp, profileData, initialEditMode = false }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const data = itemData || location.state?.data;
    const closeModal = onClose || (() => navigate('/dashboard?tab=gst&sub=registrations'));

    const label = 'GST Registration';
    const [item, setItem] = useState(data || {});
    const [editMode, setEditMode] = useState(initialEditMode);
    const canEditRecord = canManageRmOpRecords(profileData, isAdminProp);
    const { showRmField, showOpField } = getRmOpAssignmentVisibility(profileData);
    const [formData, setFormData] = useState(data || {});
    const [fieldErrors, setFieldErrors] = useState({});

    const [message, setMessage] = useState({ type: '', text: '' });
    const [isAdmin, setIsAdmin] = useState(Boolean(isAdminProp));
    const [actionLoading, setActionLoading] = useState('');
    const [confirmAction, setConfirmAction] = useState('');

    const [configsLoaded, setConfigsLoaded] = useState(false);

    const [configs, setConfigs] = useState({
        registrationTypes: [], ownershipCategories: [], businessTypes: [],
        states: [], turnoverDetailsList: [], registrationStatuses: [], activeRMs: [], activeOps: [], languages: []
    });

    useEffect(() => {
        const fetchConfigs = async () => {
            const configSources = [
                { url: `/api/v1/gst-registration/config/REGISTRATION_TYPE`, key: 'registrationTypes' },
                { url: `/api/v1/gst-registration/config/OWNERSHIP_CATEGORY`, key: 'ownershipCategories' },
                { url: `/api/v1/gst-registration/config/BUSINESS_TYPE`, key: 'businessTypes' },
                { url: `/api/v1/gst-registration/config/STATE`, key: 'states' },
                { url: `/api/v1/gst-registration/config/TURNOVER_DETAILS`, key: 'turnoverDetailsList' },
                { url: `/api/v1/gst-registration/config/REGISTRATION_STATUS`, key: 'registrationStatuses' },
                { url: `/api/v1/gst-registration/config/LANGUAGE`, key: 'languages' }
            ];

            const updatedConfigs = { ...configs };
            try {
                const responses = await Promise.all(configSources.map(source => api.get(source.url).catch(e => ({ data: [], isError: true }))));
                responses.forEach((response, index) => {
                    const source = configSources[index];
                    if (response.isError) return;
                    const data = response.data?.items || response.data?.data || response.data || [];
                    updatedConfigs[source.key] = Array.isArray(data) ? data : [];
                });
                const [activeRMs, activeOps] = await Promise.all([
                    fetchActiveRmEmployees(),
                    fetchActiveOpEmployees(),
                ]);
                updatedConfigs.activeRMs = activeRMs;
                updatedConfigs.activeOps = activeOps;
                setConfigs(updatedConfigs);
                setConfigsLoaded(true);
            } catch (err) {
                console.error("Failed to fetch GST configs:", err);
                setConfigsLoaded(true); // Proceed anyway
            }
        };
        if (isOpen) fetchConfigs();
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) return;
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = previousOverflow || 'unset';
        };
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen || !data) return;
        setItem(data);
        setFormData(withAssignmentFormFields(data));
        setEditMode(initialEditMode);
        setMessage({ type: '', text: '' });
        setFieldErrors({});
    }, [data, isOpen, initialEditMode]);

    useEffect(() => {
        if (isOpen && initialEditMode) setEditMode(true);
    }, [isOpen, initialEditMode]);

    useEffect(() => {
        if (isAdminProp !== undefined) {
            setIsAdmin(Boolean(isAdminProp));
            return;
        }
        // If isAdmin is passed via location.state, use it to avoid redundant fetch
        if (location.state?.isAdmin !== undefined) {
            setIsAdmin(location.state.isAdmin);
            return;
        }

        const checkAdmin = async () => {
            const token = localStorage.getItem('session_token');
            if (!token) return;
            try {
                const payload = JSON.parse(atob(token.split('.')[1]));
                const res = await api.get(`/api/v1/employees/employee/${payload.sub}`);
                const empData = res.data?.data || res.data;
                setIsAdmin(['ADMIN', 'SALES_MANAGER', 'OP_MANAGER'].includes(empData?.role));
            } catch (err) { /* Silently fail role fetch */ }
        };
        checkAdmin();
    }, [location.state?.isAdmin, isAdminProp]);

    const validateField = (name, value, currentFormData = formData) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        switch (name) {
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
                    if (item.gstin && item.gstin.length >= 12) {
                        const gstinPan = item.gstin.substring(2, 12).toUpperCase();
                        if (value.toUpperCase() !== gstinPan) {
                            errorMsg = 'PAN must match GSTIN (chars 3-12)';
                        }
                    }
                }
                break;
            case 'business_name':
                if (value && value.length > 200) errorMsg = 'Max 200 characters';
                break;
            case 'registration_type':
                if (value && value.length > 50) errorMsg = 'Max 50 characters';
                break;
            case 'ownership_category':
                if (value && value.length > 100) errorMsg = 'Max 100 characters';
                break;
            case 'business_type':
                if (value && value.length > 100) errorMsg = 'Max 100 characters';
                break;
            case 'state':
                if (value && value.length > 100) errorMsg = 'Max 100 characters';
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
            case 'mobile':
                if (value) {
                    const phoneRegex = /^\d{10}$/;
                    if (!phoneRegex.test(value)) errorMsg = '10 digits required';
                }
                break;
            case 'email':
                if (value) {
                    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
                    if (!emailRegex.test(value)) errorMsg = 'Invalid email format';
                    if (value.length > 150) errorMsg = 'Max 150 characters';
                } else {
                    errorMsg = 'field required';
                }
                break;
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
            case 'customer_id':
                if (trimmedValue === '' || trimmedValue === null || trimmedValue === undefined) {
                    break;
                }
                if (!/^\d+$/.test(String(trimmedValue)) || parseInt(trimmedValue, 10) <= 0) {
                    errorMsg = 'Enter a valid Customer ID';
                }
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

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return errorMsg;
    };

    const validateForm = () => {
        const errors = {};
        const keysToValidate = new Set([...Object.keys(formData), 'suspension_reason', 'cancellation_reason']);
        
        keysToValidate.forEach(key => {
            const errorMsg = validateField(key, formData[key]);
            if (errorMsg) errors[key] = errorMsg;
        });

        if (Object.keys(errors).length > 0) return "Please correct the errors in the form.";
        return null;
    };

    const getRmDisplayName = (record) => {
        if (!record) return '-';
        if (record.rm_username) return record.rm_username;
        if (record.rm_name) return record.rm_name;
        const rmId = record.rm_id;
        if (!rmId) return '-';
        return lookupAssigneeUsername(rmId, configs.activeRMs) || `ID: ${rmId}`;
    };

    const getOpDisplayName = (record) => {
        if (!record) return '-';
        if (record.op_username) return record.op_username;
        if (record.created_by_name) return record.created_by_name;
        if (record.op_name) return record.op_name;
        const opId = record.created_by;
        if (!opId) return '-';
        return lookupAssigneeUsername(opId, configs.activeOps) || `ID: ${opId}`;
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        const newValue = type === 'checkbox' ? checked : value;
        setFormData(prev => {
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

    const handleSave = async () => {
        setMessage({ type: '', text: '' });
        setFieldErrors({});

        const validationError = validateForm();
        if (validationError) {
            setMessage({ type: 'error', text: validationError });
            return;
        }
        setActionLoading('save');
        try {
            const targetId = item?.id || data?.id;
            if (!targetId) {
                setMessage({ type: 'error', text: 'GST id is missing. Please reopen details.' });
                setActionLoading('');
                return;
            }

            const rawPayload = {
                ...formData,
                pan: formData.pan ? formData.pan.toUpperCase() : formData.pan,
                rm_id: resolveRmIdForPayload({
                    profileData,
                    isEditMode: true,
                    editingRecord: item,
                    formRmId: formData.rm_id,
                    assignmentPool: configs.activeRMs,
                }),
                created_by: resolveOpIdForPayload({
                    profileData,
                    isEditMode: true,
                    editingRecord: item,
                    formOpId: formData.created_by,
                    opRecordKey: 'created_by',
                    assignmentPool: configs.activeOps,
                }),
                client_name: formData.client_name?.trim() || null,
                referral_phone_number: (formData.referral_phone_number || '').replace(/\D/g, '') || null,
                entity_type: 'GST_REGISTRATION',
                entity_id: targetId,
            };
            // Strictly align with GSTRegistrationEditIn schema
            const writableFields = [
                'customer_id',
                'business_name', 'gstin', 'username', 'password', 'pan', 
                'registration_type', 'ownership_category', 'business_type', 
                'state', 'language', 'client_name', 'referral_phone_number', 
                'turnover_details', 'registration_status', 'suspension_reason', 
                'cancellation_reason', 'is_rcm_applicable', 'is_filing_needed',
                'mobile', 'email', 'secondary_email', 
                'rm_id', 'created_by', 'filing_preference', 'entity_type', 'entity_id'
            ];

            const payload = {};
            writableFields.forEach(key => {
                const value = rawPayload[key];
                if (key === 'customer_id') {
                    if (value === '' || value === null || value === undefined) {
                        payload.customer_id = null;
                    } else {
                        const parsed = parseInt(value, 10);
                        if (Number.isFinite(parsed) && parsed > 0) {
                            payload.customer_id = parsed;
                        }
                    }
                    return;
                }
                // Only include fields that have a meaningful value (not empty string, null, or undefined)
                if (value !== '' && value !== null && value !== undefined) {
                    payload[key] = value;
                }
            });

            await api.post(`/api/v1/gst-registrations/${targetId}/edit`, payload);

            setMessage({ type: 'success', text: 'Updated successfully!' });
            if (onUpdated) onUpdated();
            if (shouldCloseDrawerAfterSave(initialEditMode)) {
                closeModal();
                return;
            }
            const updatedItem = { ...item, ...formData };
            setItem(updatedItem);
            setFormData(withAssignmentFormFields(updatedItem));
            setEditMode(false);
        } catch (err) { setMessage({ type: 'error', text: extractGstRegistrationError(err) }); }
        finally { setActionLoading(''); }
    };

    const handleDelete = async () => {
        setMessage({ type: '', text: '' });
        setConfirmAction('');
        setActionLoading('delete');
        try {
            const targetId = item?.id || data?.id;
            if (!targetId) {
                setMessage({ type: 'error', text: 'GST id is missing. Please reopen details.' });
                setActionLoading('');
                return;
            }

            await api.delete(`/api/v1/gst-registrations/${targetId}/soft_delete`);

            setMessage({ type: 'success', text: 'Deleted successfully!' });
            setTimeout(() => {
                if (onUpdated) onUpdated();
                closeModal();
            }, 1500);
        } catch (err) { setMessage({ type: 'error', text: extractGstRegistrationError(err) }); }
        finally { setActionLoading(''); }
    };

    const handleActivate = async () => {
        setMessage({ type: '', text: '' });
        setConfirmAction('');
        setActionLoading('activate');
        try {
            const res = await api.post(`/api/v1/gst-registrations/${item.id}/activate`);
            const updatedData = res.data;
            setMessage({ type: 'success', text: 'Activated successfully!' });
            const finalData = { ...updatedData, is_active: true };
            setItem(finalData);
            setFormData(withAssignmentFormFields(finalData));
            if (onUpdated) onUpdated();
        } catch (err) { setMessage({ type: 'error', text: extractGstRegistrationError(err) }); }
        finally { setActionLoading(''); }
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try { return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }); } catch { return dtStr; }
    };

    const gstRegistrationId = item?.id || data?.id;
    const registrationStatusNorm = String(item?.registration_status || '')
        .trim()
        .toUpperCase();
    const showSchedulePayment =
        canEditRecord
        && item?.is_active !== false
        && Boolean(gstRegistrationId)
        && registrationStatusNorm === 'APPROVED';

    const isEditing = editMode || initialEditMode;
    const showEditFooter = isEditing;
    const showViewFooter = !isEditing && canEditRecord;

    const handleCancelEdit = () => {
        handleDrawerCancelEdit({
            initialEditMode,
            onClose: closeModal,
            setEditMode,
            resetEditState: () => {
                setFormData(withAssignmentFormFields(item));
                setMessage({ type: '', text: '' });
                setFieldErrors({});
            },
        });
    };

    const handleSchedulePayment = async () => {
        const targetId = gstRegistrationId;
        if (!targetId) {
            setMessage({ type: 'error', text: 'GST id is missing. Please reopen details.' });
            return;
        }
        closeModal();
        let openSchedulePaymentDrawer = false;
        try {
            const lead = await getCrmLeadByGstRegistrationId(targetId);
            openSchedulePaymentDrawer = isGstCrmStageForSchedulePayment(lead?.stage);
        } catch (err) {
            console.warn('Could not load CRM lead for schedule payment:', err);
        }
        navigate(`/crm-dashboard?${buildGstCrmLeadActionSearchParams(targetId, openSchedulePaymentDrawer).toString()}`);
    };

    if (!isOpen) return null;
    if (!data) return <div className="gst-no-data">No data provided. Please navigate from the dashboard.</div>;

    const drawerPanel = (
        <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={closeModal} role="presentation">
            <div
                className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel"
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
                aria-labelledby="gst-reg-details-title"
            >
                <div className="drawer-header gst-reg-details-header">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4" style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' }}>
                            <FileText size={20} />
                        </div>
                        <div className="modal-title-box">
                            <div className="modal-header-texts">
                                <h2 id="gst-reg-details-title" className="modal-title-v4">
                                    GST Registration Details
                                    {isEditing ? (
                                        <span className="modal-header-tag-v4 edit">EDIT</span>
                                    ) : (
                                        <span className="modal-header-tag-v4 view">VIEW</span>
                                    )}
                                </h2>
                                <p className="modal-subtitle-v4">Manage registration profile and assignments • ID: {item?.id || '-'}</p>
                            </div>
                        </div>
                    </div>
                    <button type="button" className="btn-drawer-close" onClick={closeModal} aria-label="Close">
                        <X size={20} />
                    </button>
                </div>

                <div className="drawer-content gst-reg-details-scroll">
                    {message.text && (
                        <div className={`gst-message-banner ${message.type === 'success' ? 'success' : 'error'}`}>
                            {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                            <span className="gst-message-banner-text">{message.text}</span>
                        </div>
                    )}

                    <div className="gst-reg-details-form">
                            <>
                                {/* SECTION 1: IDENTITY & CORE */}
                                <div className="form-section-group">
                                    <h3 className="section-title">1. Identity & Core Details</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4" style={{ gridColumn: 'span 2' }}>
                                            <label className="modal-label-caps">GSTIN</label>
                                            {editMode ? (
                                                <input name="gstin" value={formData.gstin || ''} onChange={handleChange} className={`modal-input-v4 mono-v4 ${fieldErrors.gstin ? 'error' : ''}`} style={{ color: '#2eb87a' }} />
                                            ) : (
                                                <div className="gst-form-value-box mono-v4" style={{ color: '#2eb87a' }}>{item.gstin || '-'}</div>
                                            )}
                                            {fieldErrors.gstin && <span className="field-error-msg">{fieldErrors.gstin}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Name</label>
                                            {editMode ? (
                                                <input name="business_name" value={formData.business_name || ''} onChange={handleChange} className={`modal-input-v4 ${fieldErrors.business_name ? 'error' : ''}`} />
                                            ) : (
                                                <div className="gst-form-value-box">{item.business_name || '-'}</div>
                                            )}
                                            {fieldErrors.business_name && <span className="field-error-msg">{fieldErrors.business_name}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Client Name</label>
                                            {editMode ? (
                                                <input type="text" name="client_name" value={formData.client_name || ''} onChange={handleChange} maxLength="200" className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{item.client_name || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">PAN</label>
                                            {editMode ? (
                                                <input name="pan" value={formData.pan || ''} onChange={handleChange} maxLength="10" className={`modal-input-v4 ${fieldErrors.pan ? 'error' : ''}`} />
                                            ) : (
                                                <div className="gst-form-value-box">{item.pan || '-'}</div>
                                            )}
                                            {fieldErrors.pan && <span className="field-error-msg">{fieldErrors.pan}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Username</label>
                                            {editMode ? (
                                                <input name="username" value={formData.username || ''} onChange={handleChange} className={`modal-input-v4 ${fieldErrors.username ? 'error' : ''}`} />
                                            ) : (
                                                <div className="gst-form-value-box">{item.username || '-'}</div>
                                            )}
                                            {fieldErrors.username && <span className="field-error-msg">{fieldErrors.username}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Password</label>
                                            {editMode ? (
                                                <input name="password" value={formData.password || ''} onChange={handleChange} className={`modal-input-v4 ${fieldErrors.password ? 'error' : ''}`} />
                                            ) : (
                                                <div className="gst-form-value-box">{item.password || '-'}</div>
                                            )}
                                            {fieldErrors.password && <span className="field-error-msg">{fieldErrors.password}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Customer ID</label>
                                            {editMode ? (
                                                <input
                                                    type="number"
                                                    name="customer_id"
                                                    value={formData.customer_id ?? ''}
                                                    onChange={handleChange}
                                                    min="1"
                                                    placeholder="Enter customer ID"
                                                    className={`modal-input-v4 ${fieldErrors.customer_id ? 'error' : ''}`}
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.customer_id || '-'}</div>
                                            )}
                                            {fieldErrors.customer_id && (
                                                <span className="field-error-msg">{fieldErrors.customer_id}</span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 2: CONFIGURATION */}
                                <div className="form-section-group" style={{ marginTop: '32px' }}>
                                    <h3 className="section-title">2. Business Configuration</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Registration Type</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="registration_type"
                                                    value={formData.registration_type || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.registrationTypes, 'Select Type')}
                                                    placeholder="Select Type"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.registration_type || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Ownership Category</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="ownership_category"
                                                    value={formData.ownership_category || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.ownershipCategories, 'Select Category')}
                                                    placeholder="Select Category"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.ownership_category || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Business Type</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="business_type"
                                                    value={formData.business_type || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.businessTypes, 'Select Type')}
                                                    placeholder="Select Type"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.business_type || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">State</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="state"
                                                    value={formData.state || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.states, 'Select State')}
                                                    placeholder="Select State"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.state || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Turnover Details</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="turnover_details"
                                                    value={formData.turnover_details || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.turnoverDetailsList, 'Select Turnover')}
                                                    placeholder="Select Turnover"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.turnover_details || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Filing Preference</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="filing_preference"
                                                    value={formData.filing_preference || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs([
                                                        { value: '', label: 'Select Preference' },
                                                        ...(formData.registration_type !== 'COMPOSITION'
                                                            ? [{ value: 'MONTHLY', label: 'MONTHLY' }]
                                                            : []),
                                                        { value: 'QUARTERLY', label: 'QUARTERLY' },
                                                    ])}
                                                    placeholder="Select Preference"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.filing_preference || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Registration Status</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="registration_status"
                                                    value={formData.registration_status || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.registrationStatuses, 'Select Status')}
                                                    placeholder="Select Status"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.registration_status || '-'}</div>
                                            )}
                                        </div>
                                    </div>

                                    {editMode && (formData.registration_status === 'SUSPENDED' || formData.registration_status === 'CANCELLED') && (
                                        <div className="form-grid-3" style={{ marginTop: '20px' }}>
                                            {formData.registration_status === 'SUSPENDED' && (
                                                <div className="form-group-v4" style={{ gridColumn: 'span 3' }}>
                                                    <label className="modal-label-caps">Suspension Reason</label>
                                                    <input name="suspension_reason" value={formData.suspension_reason || ''} onChange={handleChange} className={`modal-input-v4 ${fieldErrors.suspension_reason ? 'error' : ''}`} />
                                                    {fieldErrors.suspension_reason && <span className="field-error-msg">{fieldErrors.suspension_reason}</span>}
                                                </div>
                                            )}
                                            {formData.registration_status === 'CANCELLED' && (
                                                <div className="form-group-v4" style={{ gridColumn: 'span 3' }}>
                                                    <label className="modal-label-caps">Cancellation Reason</label>
                                                    <input name="cancellation_reason" value={formData.cancellation_reason || ''} onChange={handleChange} className={`modal-input-v4 ${fieldErrors.cancellation_reason ? 'error' : ''}`} />
                                                    {fieldErrors.cancellation_reason && <span className="field-error-msg">{fieldErrors.cancellation_reason}</span>}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {!editMode && (item.suspension_reason || item.cancellation_reason) && (
                                        <div className="form-grid-3" style={{ marginTop: '20px' }}>
                                            {item.suspension_reason && (
                                                <div className="form-group-v4" style={{ gridColumn: 'span 3' }}>
                                                    <label className="modal-label-caps">Suspension Reason</label>
                                                    <div className="gst-form-value-box" style={{ background: 'rgba(244, 67, 54, 0.05)', color: '#f44336' }}>{item.suspension_reason}</div>
                                                </div>
                                            )}
                                            {item.cancellation_reason && (
                                                <div className="form-group-v4" style={{ gridColumn: 'span 3' }}>
                                                    <label className="modal-label-caps">Cancellation Reason</label>
                                                    <div className="gst-form-value-box" style={{ background: 'rgba(244, 67, 54, 0.05)', color: '#f44336' }}>{item.cancellation_reason}</div>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    <div className="gst-checkbox-row-v4" style={{ marginTop: '20px', display: 'flex', gap: '24px' }}>
                                        <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: editMode ? 'pointer' : 'default', fontSize: '13px', color: 'var(--text-primary)' }}>
                                            <input type="checkbox" name="is_rcm_applicable" checked={editMode ? formData.is_rcm_applicable : item.is_rcm_applicable} onChange={handleChange} disabled={!editMode} className="modal-checkbox-v4" />
                                            <span>RCM Applicable</span>
                                        </label>
                                        <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: editMode ? 'pointer' : 'default', fontSize: '13px', color: 'var(--text-primary)' }}>
                                            <input type="checkbox" name="is_filing_needed" checked={editMode ? formData.is_filing_needed : item.is_filing_needed} onChange={handleChange} disabled={!editMode} className="modal-checkbox-v4" />
                                            <span>Filing Needed</span>
                                        </label>
                                    </div>
                                </div>

                                {/* SECTION 3: ASSIGNMENTS & CONTACT */}
                                <div className="form-section-group" style={{ marginTop: '40px' }}>
                                    <h3 className="section-title">3. Assignments & Contact</h3>
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
                                                        buildRmOpSelectOptions(configs.activeRMs, {
                                                            username: item?.rm_username || item?.rm_name || getRmDisplayName(item),
                                                            label: item?.rm_username || item?.rm_name || getRmDisplayName(item),
                                                        }),
                                                        'Select RM'
                                                    )}
                                                    placeholder="Select RM"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{getRmDisplayName(item)}</div>
                                            )}
                                        </div>
                                        )}
                                        {showOpField && (
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Assigned OP</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="created_by"
                                                    value={formData.created_by || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs(
                                                        buildRmOpSelectOptions(configs.activeOps, {
                                                            username: item?.op_username || item?.created_by_name || getOpDisplayName(item),
                                                            label: item?.op_username || item?.created_by_name || getOpDisplayName(item),
                                                        }),
                                                        'Select OP'
                                                    )}
                                                    placeholder="Select OP"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{getOpDisplayName(item)}</div>
                                            )}
                                        </div>
                                        )}
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Mobile</label>
                                            {editMode ? (
                                                <input type="tel" name="mobile" value={formData.mobile || ''} onChange={handleChange} maxLength="10" className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{item.mobile || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Email</label>
                                            {editMode ? (
                                                <input type="email" name="email" value={formData.email || ''} onChange={handleChange} className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{item.email || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Secondary Email</label>
                                            {editMode ? (
                                                <input type="email" name="secondary_email" value={formData.secondary_email || ''} onChange={handleChange} className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{item.secondary_email || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Preferred Language</label>
                                            {editMode ? (
                                                <FormCustomSelect
                                                    name="language"
                                                    value={formData.language || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromConfig(configs.languages, 'Select Language')}
                                                    placeholder="Select Language"
                                                />
                                            ) : (
                                                <div className="gst-form-value-box">{item.language || '-'}</div>
                                            )}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Referral Phone</label>
                                            {editMode ? (
                                                <input type="tel" name="referral_phone_number" value={formData.referral_phone_number || ''} onChange={handleChange} maxLength="10" className="modal-input-v4" />
                                            ) : (
                                                <div className="gst-form-value-box">{item.referral_phone_number || '-'}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* SECTION 4: METADATA */}
                                <div className="form-section-group" style={{ marginTop: '40px', paddingBottom: '20px' }}>
                                    <h3 className="section-title">4. System Metadata</h3>
                                    <div className="form-grid-3">
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Approved At</label>
                                            <div className="gst-form-value-box metadata">{formatDateTime(item.approved_at)}</div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Created At</label>
                                            <div className="gst-form-value-box metadata">{formatDateTime(item.created_at)}</div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Last Updated</label>
                                            <div className="gst-form-value-box metadata">{formatDateTime(item.updated_at)}</div>
                                        </div>
                                    </div>
                                </div>
                            </>
                    </div>
                </div>

                <AppDrawerFooter
                    leading={
                        showSchedulePayment && showEditFooter ? (
                            <button
                                type="button"
                                onClick={handleSchedulePayment}
                                className="gst-btn-schedule-payment"
                                disabled={actionLoading !== ''}
                                title={`Schedule payment in CRM for GST registration ${gstRegistrationId}`}
                            >
                                <CalendarClock size={16} />
                                Schedule Payment
                            </button>
                        ) : null
                    }
                >
                    {showEditFooter && (
                        <>
                            {isAdmin && item?.is_active !== false && (
                                <AppDrawerBtnDelete
                                    onClick={() => setConfirmAction('delete')}
                                    disabled={actionLoading !== ''}
                                />
                            )}
                            <AppDrawerBtnCancel onClick={handleCancelEdit} disabled={actionLoading !== ''} />
                            <AppDrawerBtnSave
                                onClick={handleSave}
                                loading={actionLoading === 'save'}
                            />
                        </>
                    )}
                    {showViewFooter && (
                        item.is_active ? (
                            <>
                                <button type="button" className="glow-green" onClick={() => setEditMode(true)} disabled={actionLoading !== ''}>
                                    Edit Registration
                                </button>
                                {isAdmin && (
                                    <AppDrawerBtnDelete
                                        onClick={() => setConfirmAction('delete')}
                                        disabled={actionLoading !== ''}
                                    />
                                )}
                            </>
                        ) : (
                            isAdmin ? (
                                <button type="button" className="glow-green" onClick={() => setConfirmAction('activate')} disabled={actionLoading === 'activate'}>
                                    Activate Registration
                                </button>
                            ) : null
                        )
                    )}
                </AppDrawerFooter>

                {confirmAction && (
                    <div className="gst-confirm-overlay gst-reg-details-confirm" role="presentation">
                        <div className="gst-confirm-content" onClick={(e) => e.stopPropagation()}>
                            <div className="gst-confirm-icon">
                                <AlertCircle size={32} color={confirmAction === 'delete' ? '#f44336' : '#2eb87a'} />
                            </div>
                            <h2>{confirmAction === 'delete' ? 'Confirm Delete' : 'Confirm Activation'}</h2>
                            <p>
                                {confirmAction === 'delete'
                                    ? 'Are you sure you want to delete this GST registration profile? This action can be reversed by administrators.'
                                    : 'Are you sure you want to reactivate this GST registration?'}
                            </p>
                            <div className="gst-confirm-actions">
                                <button className="gst-btn-secondary" onClick={() => setConfirmAction('')} disabled={actionLoading !== ''}>
                                    Cancel
                                </button>
                                {confirmAction === 'delete' ? (
                                    <button className="gst-btn-danger" onClick={handleDelete} disabled={actionLoading !== ''}>
                                        {actionLoading === 'delete' ? <RotateCcw size={16} className="gst-refresh-spin" /> : 'Confirm Delete'}
                                    </button>
                                ) : (
                                    <button className="gst-btn-primary" onClick={handleActivate} disabled={actionLoading !== ''}>
                                        {actionLoading === 'activate' ? <RotateCcw size={16} className="gst-refresh-spin" /> : 'Confirm Activation'}
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );

    return typeof document !== 'undefined'
        ? createPortal(drawerPanel, document.body)
        : drawerPanel;
};

export default GSTRegistration;
