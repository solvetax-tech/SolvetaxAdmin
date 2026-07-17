/**
 * @file Customer.jsx
 * @description Renders the Customer data table and search/filter interface.
 * Handles fetching paginated customer records, role-based row click navigation, 
 * and dynamic column rendering based on the backend schema.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import '../Dashboard.css';

import axios from 'axios';
import { Filter, X, RotateCcw, Plus, UserPlus, Trash2, Edit3, Briefcase, Eye, ChevronRight, ShieldCheck, ListTodo, CheckCircle2, Clock, Users, Pencil } from 'lucide-react';
import api from '../../utils/api';
import LoadingOverlay from '../common/LoadingOverlay';
import Pagination from '../common/Pagination';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import Button from '../ui/Button';
import StatusPill from '../ui/StatusPill';
import './Customer.css';
import AddCustomerModal from './AddCustomerModal';
import { canManageRmOpRecords } from '../../utils/rmOpAssignmentFields';
import CustomerDetailsModal from './CustomerDetailsModal';
import CustomerActivationModal from './CustomerActivationModal';
import ManageCustomerServicesModal from './ManageCustomerServicesModal';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig, optionsFromPairs } from '../common/selectOptionUtils';
import {
    parseActiveUsernamesFromApi,
    buildRmOpSelectOptions,
} from '../../utils/activeEmployees';
import { fetchStaffServiceConfig } from '../../utils/staffServiceConfigApi';

const BASE_URL = import.meta.env.VITE_API_URL;

const Customer = ({ handleLogout, isAdmin, canSignup, profileData }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [hasFetched, setHasFetched] = useState(false);
    const userRole = profileData?.role || '';
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [showFilterModal, setShowFilterModal] = useState(false);
    const [isAddModalOpen, setIsAddModalOpen] = useState(false);
    const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false);
    const [detailsEditMode, setDetailsEditMode] = useState(false);
    const [isActivationModalOpen, setIsActivationModalOpen] = useState(false);
    const [selectedCustomerId, setSelectedCustomerId] = useState(null);
    const [selectedCustomer, setSelectedCustomer] = useState(null);
    const [autoOpenCustomerId, setAutoOpenCustomerId] = useState(null);
    const [isManageModalOpen, setIsManageModalOpen] = useState(false);
    const [manageCustomerId, setManageCustomerId] = useState(null);
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [states, setStates] = useState([]);
    const [businessTypes, setBusinessTypes] = useState([]);
    const [servicesConfig, setServicesConfig] = useState([]);
    const [openPopover, setOpenPopover] = useState({ customerId: null, type: null, placement: 'bottom' });
    const [popoverPosition, setPopoverPosition] = useState({ top: 0, left: 0 });
    const [sidePanel, setSidePanel] = useState({ isOpen: false, data: null });

    // ... useEffect for token check ...

    // Customer Filter Inputs
    const [filterInputs, setFilterInputs] = useState({
        customerId: '', fullName: '', email: '', mobile: '', referralPhoneNumber: '',
        businessType: '', state: '', city: '', rmId: '', opId: '', isActive: '',
        createdAtFrom: '', createdAtTo: '',
    });

    // Applied Filters (used for fetching)
    const [appliedFilters, setAppliedFilters] = useState({
        customerId: '', fullName: '', email: '', mobile: '', referralPhoneNumber: '',
        businessType: '', state: '', city: '', rmId: '', opId: '', isActive: '',
        createdAtFrom: '', createdAtTo: '',
    });

    const clearFilters = () => {
        setHasFetched(false);
        const emptyFilters = {
            customerId: '', fullName: '', email: '', mobile: '', referralPhoneNumber: '',
            businessType: '', state: '', city: '', rmId: '', opId: '', isActive: '',
            createdAtFrom: '', createdAtTo: '',
        };
        setFilterInputs(emptyFilters);
        setAppliedFilters(emptyFilters);
        setCustPage(1);
    };

    const removeFilter = (key) => {
        setFilterInputs(prev => ({ ...prev, [key]: '' }));
        setAppliedFilters(prev => ({ ...prev, [key]: '' }));
        setCustPage(1);
    };

    const renderFilterChips = () => {
        const labels = {
            customerId: 'ID',
            fullName: 'Name',
            email: 'Email',
            mobile: 'Mobile',
            referralPhoneNumber: 'Referrer',
            businessType: 'Type',
            state: 'State',
            city: 'City',
            rmId: 'RM',
            opId: 'OP',
            isActive: 'Status',
            createdAtFrom: 'From',
            createdAtTo: 'To'
        };

        return Object.entries(appliedFilters)
            .filter(([_, value]) => value !== '' && value !== null)
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

    const [custPage, setCustPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [rowsPerPage] = useState(20);
    const abortControllerRef = useRef(null);

    const serviceNameByCode = servicesConfig.reduce((acc, service) => {
        if (service.service_code) acc[service.service_code] = service.service_name || service.service_code;
        return acc;
    }, {});
    const mapServiceCodesToNames = (list) => {
        if (!Array.isArray(list)) return [];
        return list.map(code => serviceNameByCode[code] || code).filter(Boolean);
    };

    useEffect(() => {
        const fetchFilterOptions = async () => {
            try {
                const [rmRes, opRes, statesRes, bizTypeRes] = await Promise.allSettled([
                    api.get('/api/v1/employees/active-rm'),
                    api.get('/api/v1/employees/active-op'),
                    api.get(`/api/v1/gst-registration/config/STATE`),
                    api.get(`/api/v1/gst-registration/config/BUSINESS_TYPE`),
                ]);
                if (rmRes.status === 'fulfilled') setActiveRMs(parseActiveUsernamesFromApi(rmRes.value));
                if (opRes.status === 'fulfilled') setActiveOps(parseActiveUsernamesFromApi(opRes.value));
                if (statesRes.status === 'fulfilled') setStates(statesRes.value.data || []);
                if (bizTypeRes.status === 'fulfilled') setBusinessTypes(bizTypeRes.value.data || []);
                try {
                    const services = await fetchStaffServiceConfig();
                    setServicesConfig(services);
                } catch {
                    setServicesConfig([]);
                }
            } catch {
                // silent for filter dropdowns
            }
        };
        fetchFilterOptions();
    }, []);

    const getDisplayName = (list, value) => {
        if (!value) return '-';
        const match = list.find(item => item.value === value);
        if (match) return match.display_name;
        // Fallback: cleanup snake case
        return value.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()).join(' ');
    };

    const fetchData = useCallback(async () => {
        if (abortControllerRef.current) abortControllerRef.current.abort();
        const controller = new AbortController();
        abortControllerRef.current = controller;

        setLoading(true);
        setError(null);
        setHasFetched(false);

        try {
            const params = new URLSearchParams();

            const mapping = {
                customerId: 'customer_id', fullName: 'full_name', email: 'email',
                mobile: 'mobile', referralPhoneNumber: 'referral_phone_number',
                businessType: 'business_type', state: 'state',
                city: 'city', rmId: 'rm_id', opId: 'op_id',
                createdAtFrom: 'from_date', createdAtTo: 'to_date'
            };
            Object.entries(mapping).forEach(([k, v]) => {
                const raw = appliedFilters[k];
                if (!raw) return;
                if (k === 'referralPhoneNumber' || k === 'mobile') {
                    const digits = String(raw).replace(/\D/g, '');
                    if (digits.length === 10) params.append(v, digits);
                    return;
                }
                params.append(v, raw);
            });

            if (appliedFilters.isActive === 'active') params.append('is_active', 'true');
            else if (appliedFilters.isActive === 'inactive') params.append('is_active', 'false');
            else params.append('include_inactive', 'true');

            params.append('limit', rowsPerPage);
            params.append('offset', (custPage - 1) * rowsPerPage);

            const endpoint = `/api/v1/customers/customer_get/filter`;

            const response = await api.get(`${endpoint}?${params.toString()}`, {
                signal: controller.signal
            });

            const result = response.data;
            setData(Array.isArray(result) ? result : (result?.data || result?.items || []));
            if (result?.total_pages) setTotalPages(result.total_pages);
        } catch (err) {
            if (axios.isCancel(err) || err.name === 'CanceledError') return;

            if (!localStorage.getItem('session_token')) return;

            // Handle structured backend errors
            const backendError =
                err?.response?.data?.error?.message ||
                err?.response?.data?.detail?.error?.message ||
                err?.response?.data?.detail?.message;

            if (backendError) {
                setError(backendError);
            } else if (err?.response?.data?.error?.fields) {
                const fieldMessages = Object.values(err.response.data.error.fields).join(', ');
                setError(fieldMessages);
            } else {
                setError(`${err.message} (Check network/backend)`);
            }
        } finally {
            if (!controller.signal.aborted) {
                setLoading(false);
                setHasFetched(true);
            }
        }
    }, [appliedFilters, custPage, rowsPerPage]);

    useEffect(() => {
        fetchData();
        return () => {
            if (abortControllerRef.current) abortControllerRef.current.abort();
        };
    }, [custPage, rowsPerPage, fetchData]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const cid = params.get('customer_id');
        if (cid) {
            setFilterInputs(prev => ({ ...prev, customerId: cid }));
            setAppliedFilters(prev => ({ ...prev, customerId: cid }));
            setCustPage(1);
            setAutoOpenCustomerId(cid);
        }
    }, [location.search]);

    useEffect(() => {
        if (!autoOpenCustomerId) return;
        if (!data || data.length === 0) return;
        const match = data.find(item => String(item.customer_id) === String(autoOpenCustomerId));
        if (match) {
            if (!match.is_active && isAdmin) {
                setSelectedCustomer(match);
                setIsActivationModalOpen(true);
            } else {
                setSelectedCustomer(match);
                setSelectedCustomerId(match.customer_id);
                setIsDetailsModalOpen(true);
            }
            setAutoOpenCustomerId(null);
        }
    }, [autoOpenCustomerId, data, isAdmin]);

    useEffect(() => {
        const handleDocClick = (e) => {
            const isInsidePopover = e.target.closest('.service-popover-cell');
            if (!isInsidePopover) {
                setOpenPopover({ customerId: null, type: null, placement: 'bottom' });
            }
        };
        document.addEventListener('mousedown', handleDocClick);
        return () => document.removeEventListener('mousedown', handleDocClick);
    }, []);

    useEffect(() => {
        const handleScroll = (e) => {
            const target = e.target;
            if (target instanceof Element && target.closest('.service-popover')) {
                return;
            }
            setOpenPopover({ customerId: null, type: null, placement: 'bottom' });
        };
        window.addEventListener('scroll', handleScroll, true);
        return () => window.removeEventListener('scroll', handleScroll, true);
    }, []);

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const openSidePanel = (item) => {
        setSidePanel({ isOpen: true, data: item });
    };

    const openCustomerView = (item, e) => {
        e?.stopPropagation();
        if (!item.is_active && isAdmin) {
            setSelectedCustomer(item);
            setIsActivationModalOpen(true);
            return;
        }
        setSelectedCustomer(item);
        setSelectedCustomerId(item.customer_id);
        setDetailsEditMode(false);
        setIsDetailsModalOpen(true);
    };

    const openCustomerEdit = (item, e) => {
        e?.stopPropagation();
        if (!item.is_active && isAdmin) {
            setSelectedCustomer(item);
            setIsActivationModalOpen(true);
            return;
        }
        setSelectedCustomer(item);
        setSelectedCustomerId(item.customer_id);
        setDetailsEditMode(true);
        setIsDetailsModalOpen(true);
    };

    const closeSidePanel = () => {
        setSidePanel({ isOpen: false, data: null });
    };

    const handleSearch = () => {
        setHasFetched(false);
        setCustPage(1);
        setAppliedFilters({ ...filterInputs });
    };

    const renderStatusFilter = (value, onChange) => (
        <div className="filter-field">
            <label>Status</label>
            <FormCustomSelect
                name="isActive"
                value={value}
                onChange={onChange}
                options={optionsFromPairs([
                    { value: '', label: 'All Status' },
                    { value: 'active', label: 'Active Only' },
                    { value: 'inactive', label: 'Inactive Only' },
                ])}
                placeholder="All Status"
                ariaLabel="Status"
            />
        </div>
    );


    // Filter Fields Component (rendered inside modal)
    const renderFilterFields = () => (
        <div className="premium-filter-grid">
            <div className="filter-field">
                <label>Customer ID</label>
                <input type="text" name="customerId" value={filterInputs.customerId} onChange={handleFilterChange} placeholder="Enter ID..." />
            </div>
            <div className="filter-field">
                <label>Full Name</label>
                <input type="text" name="fullName" value={filterInputs.fullName} onChange={handleFilterChange} placeholder="Enter Name..." />
            </div>
            <div className="filter-field">
                <label>Email</label>
                <input type="text" name="email" value={filterInputs.email} onChange={handleFilterChange} placeholder="Enter Email..." />
            </div>
            <div className="filter-field">
                <label>Mobile</label>
                <input
                    type="tel"
                    name="mobile"
                    value={filterInputs.mobile}
                    onChange={handleFilterChange}
                    maxLength="10"
                    placeholder="10 digit mobile"
                />
            </div>
            <div className="filter-field">
                <label>Referrer mobile</label>
                <input
                    type="tel"
                    name="referralPhoneNumber"
                    value={filterInputs.referralPhoneNumber}
                    onChange={handleFilterChange}
                    maxLength="10"
                    placeholder="10 digit mobile"
                />
            </div>
            <div className="filter-field">
                <label>Business Type</label>
                <FormCustomSelect
                    name="businessType"
                    value={filterInputs.businessType}
                    onChange={handleFilterChange}
                    options={optionsFromConfig(businessTypes, 'All Types')}
                    placeholder="All Types"
                    ariaLabel="Business type"
                />
            </div>
            <div className="filter-field">
                <label>City</label>
                <input type="text" name="city" value={filterInputs.city} onChange={handleFilterChange} placeholder="Enter City..." />
            </div>
            <div className="filter-field">
                <label>State</label>
                <FormCustomSelect
                    name="state"
                    value={filterInputs.state}
                    onChange={handleFilterChange}
                    options={optionsFromConfig(states, 'All States')}
                    placeholder="All States"
                    ariaLabel="State"
                />
            </div>
            {renderStatusFilter(filterInputs.isActive, handleFilterChange)}
            <div className="filter-field">
                <label>RM ID</label>
                <FormCustomSelect
                    name="rmId"
                    value={filterInputs.rmId}
                    onChange={handleFilterChange}
                    options={optionsFromPairs(buildRmOpSelectOptions(activeRMs), 'All RM')}
                    placeholder="All RM"
                    ariaLabel="RM"
                />
            </div>
            <div className="filter-field">
                <label>OP ID</label>
                <FormCustomSelect
                    name="opId"
                    value={filterInputs.opId}
                    onChange={handleFilterChange}
                    options={optionsFromPairs(buildRmOpSelectOptions(activeOps), 'All OP')}
                    placeholder="All OP"
                    ariaLabel="OP"
                />
            </div>
            <div className="filter-field">
                <label>Created From</label>
                <FilterDateInput name="createdAtFrom" value={filterInputs.createdAtFrom} onChange={handleFilterChange} ariaLabel="Created from" />
            </div>
            <div className="filter-field">
                <label>Created To</label>
                <FilterDateInput name="createdAtTo" value={filterInputs.createdAtTo} onChange={handleFilterChange} ariaLabel="Created to" />
            </div>
        </div>
    );

    return (
        <div className="customer-tab-container">
            <div className="gst-action-bar-v2">
                <div className="active-filters-container">
                    {renderFilterChips()}
                </div>
                <div className="gst-action-buttons">
                    <Button variant="secondary" size="sm" icon={<Filter size={13} />} onClick={() => setShowFilterModal(true)}>
                        Filters
                    </Button>
                    {(appliedFilters.customerId || appliedFilters.fullName || appliedFilters.email || appliedFilters.isActive) && (
                        <Button variant="ghost" size="sm" icon={<X size={14} />} onClick={clearFilters}>
                            Reset Filters
                        </Button>
                    )}
                    {canManageRmOpRecords(profileData, isAdmin) && (
                        <Button variant="primary" size="sm" icon={<UserPlus size={13} />} onClick={() => setIsAddModalOpen(true)}>
                            Create Customer
                        </Button>
                    )}
                </div>
            </div>

            {/* Filter Drawer */}
            <div className={`premium-drawer-overlay ${showFilterModal ? 'show' : ''}`} onClick={() => setShowFilterModal(false)}>
                <div className="premium-drawer-right" onClick={e => e.stopPropagation()}>
                    <div className="drawer-header-v4">
                        <h2><Filter size={20} /> Filter Customers</h2>
                        <button className="btn-drawer-close" onClick={() => setShowFilterModal(false)}><X size={18} /></button>
                    </div>

                    <div className="drawer-content-v4">
                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Core Identifiers</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>Customer ID</label>
                                    <input type="text" name="customerId" value={filterInputs.customerId} onChange={handleFilterChange} placeholder="Enter ID..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Full Name</label>
                                    <input type="text" name="fullName" value={filterInputs.fullName} onChange={handleFilterChange} placeholder="Enter Name..." />
                                </div>
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Contact Details</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>Email</label>
                                    <input type="text" name="email" value={filterInputs.email} onChange={handleFilterChange} placeholder="Enter Email..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Mobile</label>
                                    <input type="text" name="mobile" value={filterInputs.mobile} onChange={handleFilterChange} placeholder="Enter Mobile..." />
                                </div>
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Location & Business</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>Business Type</label>
                                    <FormCustomSelect
                                        name="businessType"
                                        value={filterInputs.businessType}
                                        onChange={handleFilterChange}
                                        options={optionsFromConfig(businessTypes, 'All Types')}
                                        placeholder="All Types"
                                        ariaLabel="Business type"
                                    />
                                </div>
                                <div className="filter-group-v4">
                                    <label>State</label>
                                    <FormCustomSelect
                                        name="state"
                                        value={filterInputs.state}
                                        onChange={handleFilterChange}
                                        options={optionsFromConfig(states, 'All States')}
                                        placeholder="All States"
                                        ariaLabel="State"
                                    />
                                </div>
                                <div className="filter-group-v4">
                                    <label>City</label>
                                    <input type="text" name="city" value={filterInputs.city} onChange={handleFilterChange} placeholder="Enter City..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Status</label>
                                    <FormCustomSelect
                                        name="isActive"
                                        value={filterInputs.isActive}
                                        onChange={handleFilterChange}
                                        options={optionsFromPairs([
                                            { value: '', label: 'All Status' },
                                            { value: 'active', label: 'Active Only' },
                                            { value: 'inactive', label: 'Inactive Only' },
                                        ])}
                                        placeholder="All Status"
                                        ariaLabel="Status"
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Assignment</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>RM ID</label>
                                    <FormCustomSelect
                                        name="rmId"
                                        value={filterInputs.rmId}
                                        onChange={handleFilterChange}
                                        options={optionsFromPairs(buildRmOpSelectOptions(activeRMs), 'All RM')}
                                        placeholder="All RM"
                                        ariaLabel="RM"
                                    />
                                </div>
                                <div className="filter-group-v4">
                                    <label>OP ID</label>
                                    <FormCustomSelect
                                        name="opId"
                                        value={filterInputs.opId}
                                        onChange={handleFilterChange}
                                        options={optionsFromPairs(buildRmOpSelectOptions(activeOps), 'All OP')}
                                        placeholder="All OP"
                                        ariaLabel="OP"
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Configuration</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>Created From</label>
                                    <FilterDateInput name="createdAtFrom" value={filterInputs.createdAtFrom} onChange={handleFilterChange} ariaLabel="Created from" />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Created To</label>
                                    <FilterDateInput name="createdAtTo" value={filterInputs.createdAtTo} onChange={handleFilterChange} ariaLabel="Created to" />
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="drawer-footer-v4">
                        <button className="btn-reset-v4" onClick={clearFilters}>Reset</button>
                        <button className="btn-apply-v4" onClick={() => { handleSearch(); setShowFilterModal(false); }}>
                            {loading ? 'Searching...' : 'Apply Filters'}
                        </button>
                    </div>
                </div>
            </div>

            <div className="gst-table-wrapper">
                <div className="gst-table-container">
                    <div className="filings-ledger-header customer-grid-template">
                        <div className="filings-ledger-header-cell">Cust ID</div>
                        <div className="filings-ledger-header-cell">Full Name</div>
                        <div className="filings-ledger-header-cell">Email</div>
                        <div className="filings-ledger-header-cell">Mobile</div>
                        <div className="filings-ledger-header-cell">Referrer</div>
                        <div className="filings-ledger-header-cell">Business Name</div>
                        <div className="filings-ledger-header-cell">Business Type</div>
                        <div className="filings-ledger-header-cell">State</div>
                        <div className="filings-ledger-header-cell">City</div>
                        <div className="filings-ledger-header-cell">RM Name</div>
                        <div className="filings-ledger-header-cell">OP Name</div>
                        <div className="filings-ledger-header-cell" style={{ justifyContent: 'center' }}>Active</div>
                        <div className="filings-ledger-header-cell customer-actions-sticky">Actions</div>
                    </div>

                    {loading ? (
                        <div className="filings-ledger-body">
                            {[...Array(12)].map((_, i) => (
                                <div key={i} className="filings-ledger-row customer-grid-template">
                                    {[...Array(13)].map((_, j) => (
                                        <div key={j} className="filings-ledger-cell">
                                            <div className="filings-ledger-skeleton-bar" />
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    ) : error ? (
                        <div className="employee-table-error" style={{ padding: '20px', textAlign: 'center' }}>Error: {error}</div>
                    ) : data.length === 0 ? (
                        <div className="employee-table-msg" style={{ padding: '20px', textAlign: 'center' }}>
                            {hasFetched ? 'No customers found matching filters.' : 'Fetch customers to view results.'}
                        </div>
                    ) : (
                        <div className="filings-ledger-body">
                            {data.map(item => (
                                <div
                                    key={item.customer_id}
                                    className={`filings-ledger-row customer-grid-template ${openPopover.customerId === item.customer_id ? 'customer-row-active' : ''}`}
                                >
                                    <div className="filings-ledger-cell">
                                        <span className="ui-num">{item.customer_id}</span>
                                    </div>
                                    <div className="filings-ledger-cell" title={item.full_name}>
                                        <span className="customer-name-blue-v4">{item.full_name}</span>
                                    </div>
                                    <div className="filings-ledger-cell" title={item.email}>{item.email || '-'}</div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{item.mobile || '-'}</span></div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{item.referral_phone_number || '-'}</span></div>
                                    <div className="filings-ledger-cell ledger-cell-longtext" title={item.business_name}>{item.business_name || '-'}</div>
                                    <div className="filings-ledger-cell" title={item.business_type}>
                                        <StatusPill tone="neutral" dot={false}>
                                            {getDisplayName(businessTypes, item.business_type)}
                                        </StatusPill>
                                    </div>
                                    <div className="filings-ledger-cell" title={item.state}>{getDisplayName(states, item.state)}</div>
                                    <div className="filings-ledger-cell" title={item.city}>{item.city || '-'}</div>
                                    <div className="filings-ledger-cell" title={item.rm_name}>{item.rm_name || '-'}</div>
                                    <div className="filings-ledger-cell" title={item.op_name}>{item.op_name || '-'}</div>
                                    <div className="filings-ledger-cell" style={{ justifyContent: 'center' }}>
                                        <StatusPill tone={item.is_active ? 'success' : 'danger'}>
                                            {item.is_active ? 'Active' : 'Inactive'}
                                        </StatusPill>
                                    </div>
                                    <div className="filings-ledger-cell customer-actions-sticky">
                                        <div className="table-actions-combined">
                                            <button
                                                type="button"
                                                className="btn-view-services-mini btn-view-icon-only"
                                                title="View customer"
                                                aria-label="View customer"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    openCustomerView(item, e);
                                                }}
                                            >
                                                <Eye size={16} />
                                            </button>
                                            <button
                                                type="button"
                                                className="btn-edit-action"
                                                title="Edit customer"
                                                aria-label="Edit customer"
                                                onClick={(e) => openCustomerEdit(item, e)}
                                            >
                                                <Pencil size={14} />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            <Pagination
                currentPage={custPage}
                onPageChange={setCustPage}
                hasMore={data.length >= rowsPerPage}
                loading={loading}
            />

            <AddCustomerModal
                isOpen={isAddModalOpen}
                onClose={() => setIsAddModalOpen(false)}
                onSuccess={() => fetchData()}
                profileData={profileData}
            />

            <CustomerDetailsModal
                key={selectedCustomerId ? `cust-${selectedCustomerId}-${detailsEditMode}` : 'cust-closed'}
                isOpen={isDetailsModalOpen}
                onClose={() => {
                    setIsDetailsModalOpen(false);
                    setSelectedCustomerId(null);
                    setDetailsEditMode(false);
                    fetchData();
                }}
                customerId={selectedCustomerId}
                isAdmin={isAdmin}
                profileData={profileData}
                userRole={profileData?.role}
                initialData={selectedCustomer}
                initialEditMode={detailsEditMode}
            />

            <CustomerActivationModal
                isOpen={isActivationModalOpen}
                onClose={() => {
                    setIsActivationModalOpen(false);
                    setSelectedCustomer(null);
                }}
                customer={selectedCustomer}
                onActivate={(msg) => {
                    setIsActivationModalOpen(false);
                    setSelectedCustomerId(selectedCustomer.customer_id);
                    setIsDetailsModalOpen(true);
                    // Pass message to details modal if needed, but for now just refresh
                    setSelectedCustomer(null);
                    fetchData();
                }}
            />

            <ManageCustomerServicesModal 
                isOpen={isManageModalOpen}
                customerId={manageCustomerId}
                onClose={() => {
                    setIsManageModalOpen(false);
                    setManageCustomerId(null);
                }}
                onSuccess={() => {
                    fetchData();
                }}
            />

            {/* Premium Services Side Panel */}
            <div className={`side-panel-overlay ${sidePanel.isOpen ? 'show' : ''}`} onClick={closeSidePanel}>
                <div className={`followup-drawer-panel tracker-drawer side-panel-drawer ${sidePanel.isOpen ? 'open show' : ''}`} onClick={e => e.stopPropagation()}>
                    {sidePanel.data && (
                        <>
                            <div className="drawer-header">
                                <div className="drawer-title">
                                    <ShieldCheck size={24} color="var(--accent)" />
                                    <div>
                                        <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>{sidePanel.data.full_name}</h3>
                                        <p style={{ margin: 0, color: 'var(--accent)', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em' }}>Customer ID {sidePanel.data.customer_id}</p>
                                    </div>
                                </div>
                                <button className="btn-close-drawer" onClick={closeSidePanel}>
                                    <X size={20} />
                                </button>
                            </div>

                            <div className="drawer-body">
                                {/* Progress Overview Section */}
                                {(() => {
                                    const reqSet = Array.from(new Set(sidePanel.data.service_required || []));
                                    const reqCount = reqSet.length;

                                    return (
                                        <>
                                            <div className="progress-overview-premium">
                                                <div className="progress-header-row">
                                                    <span className={`overall-status-badge ${reqCount > 0 ? 'in_progress' : 'not_started'}`}>
                                                        {reqCount > 0 ? 'SERVICES LISTED' : 'NOT STARTED'}
                                                    </span>
                                                    <span className="completion-label" style={{ color: 'var(--text-primary)', fontWeight: 900, fontSize: '24px' }}>{reqCount}</span>
                                                </div>
                                                <div className="kpi-grid-premium">
                                                    <div className="kpi-item-premium">
                                                        <span className="kpi-label-v2">Required</span>
                                                        <span className="kpi-value-v2">{reqCount}</span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Ownership Section */}
                                            <div className="owner-section-premium">
                                                <div className="owner-card-premium">
                                                    <div className="owner-icon-wrap"><Users size={16} /></div>
                                                    <div className="owner-info">
                                                        <span className="owner-title">Rel. Manager</span>
                                                        <span className="owner-name">{sidePanel.data.rm_name || '-'}</span>
                                                    </div>
                                                </div>
                                                <div className="owner-card-premium">
                                                    <div className="owner-icon-wrap"><Briefcase size={16} /></div>
                                                    <div className="owner-info">
                                                        <span className="owner-title">Ops Owner</span>
                                                        <span className="owner-name">{sidePanel.data.op_name || '-'}</span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Detailed Services Section */}
                                            <div className="services-list-premium">
                                                <div className="service-type-group required-group">
                                                    <div className="group-header">
                                                        <div className="group-title" style={{ fontSize: '12px', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                            <ListTodo size={14} /> Required Services
                                                        </div>
                                                        <div className="group-count">{reqCount}</div>
                                                    </div>
                                                    <div className="service-items-grid">
                                                        {reqCount > 0 ? reqSet.map((code, i) => (
                                                            <div key={`side-req-${i}`} className="service-pill-v4">
                                                                {serviceNameByCode[code] || code}
                                                            </div>
                                                        )) : <div className="service-pill-v4 muted">None</div>}
                                                    </div>
                                                </div>
                                            </div>
                                        </>
                                    );
                                })()}
                            </div>

                            <div className="drawer-footer">
                                <button className="btn-panel-action-full" onClick={() => {
                                    setManageCustomerId(sidePanel.data.customer_id);
                                    setIsManageModalOpen(true);
                                }}>
                                    <Briefcase size={16} /> Manage Services
                                </button>
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div >
    );
};

export default Customer;
