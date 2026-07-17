/**
 * @file CustomerServices.jsx
 * @description Renders the Customer Services data table and filter interface.
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import { useLocation, useNavigate } from 'react-router-dom';
import '../Dashboard.css';
import { Filter, X, RotateCcw, FileText, Clock, Plus, XCircle, Search, Eye, Pencil, CreditCard } from 'lucide-react';
import api from '../../utils/api';
import Pagination from '../common/Pagination';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import './CustomerServices.css';
import CustomerServiceDetailsModal from './CustomerServiceDetailsModal';
import FollowupManager from './FollowupManager';
import AddPayment from '../payments/AddPayment';
import FormCustomSelect from '../common/FormCustomSelect';
import CustomerPicker from '../common/CustomerPicker';
import Button from '../ui/Button';
import { normalizeMobile } from '../../utils/customerApi';
import { optionsFromPairs } from '../common/selectOptionUtils';
import { fetchStaffServiceConfig } from '../../utils/staffServiceConfigApi';
import {
    filterCustomerServices,
    buildCustomerServiceFilterParams,
    recordStatusLabel,
} from '../../utils/customerServiceApi';
import {
    fetchActiveRmEmployees,
    fetchActiveOpEmployees,
    buildRmOpIdSelectOptions,
} from '../../utils/activeEmployees';

// Create-form vocabularies. The filter drawer's equivalents lead with an
// "All ..." entry, which is meaningless here: a new row always lands on one
// concrete value. Mirrors ServiceStatusLiteral in backend/common/status_constants.py.
const SERVICE_STATUS_CREATE_OPTIONS = optionsFromPairs([
    { value: 'PENDING', label: 'Pending' },
    { value: 'PROVIDED', label: 'Provided' },
]);

const RECORD_STATUS_CREATE_OPTIONS = optionsFromPairs([
    { value: 'true', label: 'Active' },
    { value: 'false', label: 'Inactive' },
]);

const EMPTY_FILTERS = {
    customer_id: '',
    service_code: '',
    status: '',
    service_status: '',
    from_date: '',
    to_date: '',
    rm_id: '',
    op_id: '',
};

const readFiltersFromSearch = (search) => {
    const params = new URLSearchParams(search);
    const customerId = params.get('customer_id') || '';
    if (!customerId) return { ...EMPTY_FILTERS };
    return { ...EMPTY_FILTERS, customer_id: customerId };
};

const CustomerServices = ({ isAdmin, profileData, setToastMessage }) => {
    const location = useLocation();
    const navigate = useNavigate();
    const fetchAbortRef = useRef(null);
    const [data, setData] = useState([]);
    const [servicesConfig, setServicesConfig] = useState([]);
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [employeeById, setEmployeeById] = useState({});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [selectedServiceId, setSelectedServiceId] = useState(null);
    const [selectedService, setSelectedService] = useState(null);
    const [detailsEditMode, setDetailsEditMode] = useState(false);
    const [activeFollowupId, setActiveFollowupId] = useState(null);
    const [followupServiceData, setFollowupServiceData] = useState(null);
    const rowsPerPage = 20;

    const [showFilterModal, setShowFilterModal] = useState(false);

    // --- Create service drawer (POST /api/v1/customer-service/create) ---
    const CREATE_FORM_EMPTY = {
        service_code: '',
        customer_id: '',
        service_status: 'PENDING',
        is_active: 'true',
        rm_id: '',
        op_id: '',
        followup_at: '',
        followup_remarks: '',
    };
    const [showCreateService, setShowCreateService] = useState(false);
    const [createForm, setCreateForm] = useState(CREATE_FORM_EMPTY);
    // Contact details are NOT service columns, so the drawer names a customer one
    // of two ways, never both: createCustomer is an existing row (-> customer_id),
    // createNewCustomer is a draft the create request itself inserts.
    const [createCustomer, setCreateCustomer] = useState(null);
    const [createNewCustomer, setCreateNewCustomer] = useState(null);
    const [createSaving, setCreateSaving] = useState(false);
    const [createError, setCreateError] = useState(null);
    const [createFieldErrors, setCreateFieldErrors] = useState({});
    const [showAddPayment, setShowAddPayment] = useState(false);
    const [filterInputs, setFilterInputs] = useState(() => readFiltersFromSearch(location.search));
    const [appliedFilters, setAppliedFilters] = useState(() => readFiltersFromSearch(location.search));

    useEffect(() => {
        fetchStaffServiceConfig()
            .then(setServicesConfig)
            .catch(() => setServicesConfig([]));
    }, []);

    useEffect(() => {
        Promise.all([fetchActiveRmEmployees(), fetchActiveOpEmployees()])
            .then(([rms, ops]) => {
                setActiveRMs(rms);
                setActiveOps(ops);
            })
            .catch(() => {
                setActiveRMs([]);
                setActiveOps([]);
            });
    }, []);

    useEffect(() => {
        const fetchEmployees = async () => {
            try {
                const response = await api.get(`/api/v1/employees/filter?is_active=true&limit=100`);
                const rows = Array.isArray(response.data)
                    ? response.data
                    : (Array.isArray(response.data?.data) ? response.data.data : []);
                setEmployees(rows);
            } catch {
                setEmployees([]);
            }
        };
        fetchEmployees();
    }, []);

    useEffect(() => {
        const base = {};
        employees.forEach((emp) => {
            if (emp?.emp_id == null) return;
            base[String(emp.emp_id)] = emp.username || emp.email || emp.first_name || '-';
        });
        setEmployeeById((prev) => ({ ...base, ...prev }));
    }, [employees]);

    const serviceNameByCode = useMemo(() => (
        servicesConfig.reduce((acc, service) => {
            if (service.service_code) {
                acc[service.service_code] = service.service_name || service.service_code;
            }
            return acc;
        }, {})
    ), [servicesConfig]);

    const usernameByEmpId = useMemo(() => (
        employeeById
    ), [employeeById]);

    const rmFilterOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'All RMs' },
            ...buildRmOpIdSelectOptions(activeRMs),
        ]),
        [activeRMs],
    );

    const opFilterOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'All OPs' },
            ...buildRmOpIdSelectOptions(activeOps),
        ]),
        [activeOps],
    );

    const serviceCodeOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'All Services' },
            ...servicesConfig.map((svc) => ({
                value: svc.service_code,
                label: svc.service_name || svc.service_code,
            })),
        ]),
        [servicesConfig],
    );

    // Create-form variants of the dropdowns. The *FilterOptions lists above lead
    // with "All RMs"/"All Services", which is wrong here: on a create form an
    // empty value means "unassigned", and service is required.
    const serviceCreateOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'Select service...' },
            ...servicesConfig.map((svc) => ({
                value: svc.service_code,
                label: svc.service_name || svc.service_code,
            })),
        ]),
        [servicesConfig],
    );

    const rmCreateOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'Unassigned' },
            ...buildRmOpIdSelectOptions(activeRMs),
        ]),
        [activeRMs],
    );

    const opCreateOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'Unassigned' },
            ...buildRmOpIdSelectOptions(activeOps),
        ]),
        [activeOps],
    );

    const fetchServices = useCallback(async () => {
        if (fetchAbortRef.current) {
            fetchAbortRef.current.abort();
        }
        const controller = new AbortController();
        fetchAbortRef.current = controller;

        setLoading(true);
        setError(null);
        try {
            const params = buildCustomerServiceFilterParams(appliedFilters, {
                limit: rowsPerPage,
                offset: (currentPage - 1) * rowsPerPage,
            });
            const result = await filterCustomerServices(params, { signal: controller.signal });
            if (controller.signal.aborted) return;
            setData(Array.isArray(result?.data) ? result.data : []);
        } catch (err) {
            if (axios.isCancel(err) || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
                return;
            }
            const detail = err?.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : err?.message || 'Failed to load services.');
        } finally {
            if (!controller.signal.aborted) {
                setLoading(false);
            }
        }
    }, [appliedFilters, currentPage]);

    useEffect(() => {
        fetchServices();
    }, [fetchServices]);

    useEffect(() => {
        const missingIds = Array.from(
            new Set(
                data
                    .flatMap((item) => [item?.rm_id, item?.op_id])
                    .filter((id) => id !== null && id !== undefined)
                    .map((id) => String(id))
                    .filter((id) => !usernameByEmpId[id])
            )
        );

        if (missingIds.length === 0) return;

        let cancelled = false;
        const fetchMissingUsers = async () => {
            const entries = await Promise.all(
                missingIds.map(async (id) => {
                    try {
                        const res = await api.get(`/api/v1/employees/employee/${id}`);
                        const emp = res.data || {};
                        return [id, emp.username || emp.email || emp.first_name || '-'];
                    } catch {
                        return [id, '-'];
                    }
                })
            );

            if (cancelled) return;
            const patch = Object.fromEntries(entries);
            setEmployeeById((prev) => ({ ...prev, ...patch }));
        };

        fetchMissingUsers();
        return () => {
            cancelled = true;
        };
    }, [data, usernameByEmpId]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const serviceId = params.get('service_id');
        const urlFilters = readFiltersFromSearch(location.search);

        if (serviceId) {
            setSelectedServiceId(parseInt(serviceId, 10));
            setDetailsEditMode(false);
        }

        setFilterInputs((prev) => ({ ...prev, customer_id: urlFilters.customer_id }));
        setAppliedFilters((prev) => {
            if (prev.customer_id === urlFilters.customer_id) return prev;
            return { ...prev, customer_id: urlFilters.customer_id };
        });
        if (urlFilters.customer_id) {
            setCurrentPage(1);
        }
    }, [location.search]);

    const openCreateService = () => {
        setCreateForm(CREATE_FORM_EMPTY);
        setCreateCustomer(null);
        setCreateNewCustomer(null);
        setCreateError(null);
        setCreateFieldErrors({});
        setShowCreateService(true);
    };

    const handleCreateCustomerSelect = (row) => {
        setCreateCustomer(row);
        setCreateNewCustomer(null);
        setCreateForm((prev) => ({
            ...prev,
            customer_id: row?.customer_id != null ? String(row.customer_id) : '',
        }));
        setCreateFieldErrors((prev) => (prev.customer_id ? { ...prev, customer_id: undefined } : prev));
    };

    const handleCreateNewCustomerChange = (draft) => {
        setCreateNewCustomer(draft);
        if (draft) {
            setCreateCustomer(null);
            setCreateForm((prev) => ({ ...prev, customer_id: '' }));
        }
        setCreateFieldErrors((prev) => ({
            ...prev,
            full_name: undefined,
            mobile: undefined,
            business_name: undefined,
        }));
    };

    const handleCreateChange = (e) => {
        const { name, value } = e.target;
        setCreateForm((prev) => ({ ...prev, [name]: value }));
        // clear the field's error as soon as the user edits it
        setCreateFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
    };

    const submitCreateService = async (e) => {
        e.preventDefault();
        if (createSaving) return;

        const errors = {};
        if (!createForm.service_code) errors.service_code = 'Select a service.';

        // Mirrors the API's rule: full_name + mobile are NOT NULL on customers, so
        // a draft without them cannot become a row. Checked here too so the user
        // is not charged a round-trip to learn it.
        if (createNewCustomer) {
            if (createNewCustomer.full_name.trim().length < 2) {
                errors.full_name = "Enter the customer's name (at least 2 characters).";
            }
            if (!normalizeMobile(createNewCustomer.mobile)) {
                errors.mobile = 'Enter a 10-digit mobile number.';
            }
        }
        if (Object.keys(errors).length > 0) {
            setCreateFieldErrors(errors);
            return;
        }

        // Only send what the user filled: the API treats every field except
        // service_code as optional, and customer_id is nullable by design.
        // service_status/is_active are always sent -- both render as an explicit
        // control with a visible default, so the shown value is the sent value.
        const body = {
            service_code: createForm.service_code,
            service_status: createForm.service_status,
            is_active: createForm.is_active === 'true',
        };
        if (createNewCustomer) {
            // The API creates this customer and attaches the service in one
            // transaction. customer_id must stay absent -- sending both is a 400.
            body.full_name = createNewCustomer.full_name.trim();
            body.mobile = normalizeMobile(createNewCustomer.mobile);
            const business = createNewCustomer.business_name.trim();
            if (business !== '') body.business_name = business;
        } else if (createForm.customer_id !== '') {
            body.customer_id = Number(createForm.customer_id);
        }
        if (createForm.rm_id !== '') body.rm_id = Number(createForm.rm_id);
        if (createForm.op_id !== '') body.op_id = Number(createForm.op_id);
        if (createForm.followup_at !== '') body.followup_at = new Date(createForm.followup_at).toISOString();
        if (createForm.followup_remarks.trim() !== '') body.followup_remarks = createForm.followup_remarks.trim();

        setCreateSaving(true);
        setCreateError(null);
        setCreateFieldErrors({});
        try {
            await api.post('/api/v1/customer-service/create', body);
            setShowCreateService(false);
            setCurrentPage(1);
            await fetchServices();
        } catch (err) {
            const status = err?.response?.status;
            const detail = err?.response?.data?.detail;
            // 400 from _raise_validation carries {error:{fields:{...}}}; 409 is a
            // duplicate; 422 is pydantic. Surface each where the user can act on it.
            const fields = detail?.error?.fields;
            if (status === 400 && fields) {
                setCreateFieldErrors(fields);
                setCreateError(detail?.error?.message || 'Validation failed.');
            } else if (status === 409) {
                setCreateError(typeof detail === 'string' ? detail : 'This service already exists.');
            } else if (status === 422) {
                const first = Array.isArray(detail?.errors) ? detail.errors[0] : null;
                setCreateError(first?.msg || 'Please check the values entered.');
            } else {
                setCreateError(
                    (typeof detail === 'string' && detail) || err?.message || 'Failed to create service.'
                );
            }
        } finally {
            setCreateSaving(false);
        }
    };

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const syncCustomerIdToUrl = (customerId) => {
        const params = new URLSearchParams(location.search);
        if (!params.get('tab')) {
            params.set('tab', 'customer-services');
        }
        if (customerId) {
            params.set('customer_id', String(customerId));
        } else {
            params.delete('customer_id');
        }
        navigate(`/dashboard?${params.toString()}`, { replace: true });
    };

    const handleSearch = () => {
        setCurrentPage(1);
        setAppliedFilters({ ...filterInputs });
        syncCustomerIdToUrl(filterInputs.customer_id);
        setShowFilterModal(false);
    };

    const clearFilters = () => {
        setFilterInputs({ ...EMPTY_FILTERS });
        setAppliedFilters({ ...EMPTY_FILTERS });
        setCurrentPage(1);
        syncCustomerIdToUrl('');
    };

    const resolveRmLabel = (item) =>
        item?.rm_name || usernameByEmpId[String(item?.rm_id)] || '-';

    const resolveOpLabel = (item) =>
        item?.op_name || usernameByEmpId[String(item?.op_id)] || '-';

    const openServiceView = (item, e) => {
        e?.stopPropagation?.();
        setDetailsEditMode(false);
        setSelectedServiceId(item.id);
        setSelectedService(item);
    };

    const openServiceEdit = (item, e) => {
        e?.stopPropagation?.();
        setDetailsEditMode(true);
        setSelectedServiceId(item.id);
        setSelectedService(item);
    };

    const closeServiceDetails = () => {
        setSelectedServiceId(null);
        setSelectedService(null);
        setDetailsEditMode(false);
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try {
            return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
        } catch {
            return dtStr;
        }
    };

    const renderFilterChips = () => {
        const labels = {
            customer_id: 'Customer ID',
            service_code: 'Service Code',
            status: 'Status',
            service_status: 'Service Status',
            from_date: 'From',
            to_date: 'To',
            rm_id: 'RM',
            op_id: 'OP',
        };

        return Object.entries(appliedFilters)
            .filter(([key, value]) => value !== '')
            .map(([key, value]) => (
                <div key={key} className="filter-chip">
                    <span className="filter-chip-label">{labels[key] || key}:</span>
                    <span className="filter-chip-value">{value}</span>
                    <button className="btn-remove-chip" onClick={() => {
                        setFilterInputs(prev => ({ ...prev, [key]: '' }));
                        setAppliedFilters(prev => ({ ...prev, [key]: '' }));
                        setCurrentPage(1);
                        if (key === 'customer_id') {
                            syncCustomerIdToUrl('');
                        }
                    }}>
                        <X size={12} />
                    </button>
                </div>
            ));
    };

    const CustomerServicesTableSkeleton = () => (
        <div className="filings-ledger-body">
            {[...Array(12)].map((_, i) => (
                <div key={i} className="filings-ledger-row cs-services-grid-template">
                    {[...Array(13)].map((_, j) => (
                        <div key={j} className="filings-ledger-cell">
                            <div className="skeleton-pulse" style={{
                                width: j === 2 || j === 3 ? '140px' : '60px',
                                height: j === 7 || j === 8 || j === 9 ? '24px' : '12px',
                                borderRadius: j === 7 || j === 8 || j === 9 ? '8px' : '4px',
                            }} />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );

    return (
        <div className="customer-services-container">
            <div className="gst-action-bar-v2">
                <div className="active-filters-container" style={{ flex: 1, display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {renderFilterChips()}
                </div>

                <div className="gst-action-buttons">
                    {(Object.values(appliedFilters).some(v => v !== '')) && (
                        <button className="btn-reset-green-v4" onClick={clearFilters}>
                            <RotateCcw size={14} /> Reset Filters
                        </button>
                    )}
                    <button
                        type="button"
                        className="btn-cs-payments-entry"
                        onClick={() => setShowAddPayment(true)}
                        title="Create customer service payment"
                    >
                        <CreditCard size={13} /> Record Payment
                    </button>
                    <button
                        className="btn-filter-trigger"
                        onClick={() => setShowFilterModal(true)}
                    >
                        <Filter size={13} /> Filters
                    </button>
                    <Button
                        variant="primary"
                        size="sm"
                        icon={<Plus size={13} />}
                        onClick={openCreateService}
                        title="Create customer service"
                    >
                        Create Service
                    </Button>
                </div>
            </div>

            {/* Create Service Drawer -> POST /api/v1/customer-service/create */}
            {showCreateService && (
                <div className="gst-filters-drawer-overlay" onClick={() => !createSaving && setShowCreateService(false)}>
                    <div className="gst-filters-drawer" onClick={e => e.stopPropagation()}>
                        <div className="drawer-header">
                            <h2 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)' }}>Create Customer Service</h2>
                            <button className="btn-drawer-close" onClick={() => setShowCreateService(false)} disabled={createSaving}>
                                <XCircle size={20} />
                            </button>
                        </div>

                        <form onSubmit={submitCreateService} style={{ display: 'contents' }}>
                            <div className="drawer-content">
                                {createError && (
                                    <div className="error-banner" style={{ marginBottom: '14px' }}>
                                        <span>{createError}</span>
                                    </div>
                                )}

                                <div className="filter-section-v4">
                                    <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Service</h4>
                                    <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                        <div className="filter-group-v4">
                                            <label>Service <span style={{ color: 'var(--danger)' }}>*</span></label>
                                            <FormCustomSelect
                                                name="service_code"
                                                value={createForm.service_code}
                                                onChange={handleCreateChange}
                                                options={serviceCreateOptions}
                                                placeholder="Select service..."
                                                ariaLabel="Service code"
                                                error={Boolean(createFieldErrors.service_code)}
                                            />
                                            {createFieldErrors.service_code && (
                                                <span className="field-error-msg">{createFieldErrors.service_code}</span>
                                            )}
                                        </div>
                                        <div className="filter-group-v4">
                                            <label>Fulfillment Status</label>
                                            <FormCustomSelect
                                                name="service_status"
                                                value={createForm.service_status}
                                                onChange={handleCreateChange}
                                                options={SERVICE_STATUS_CREATE_OPTIONS}
                                                placeholder="Pending"
                                                ariaLabel="Fulfillment status"
                                                error={Boolean(createFieldErrors.service_status)}
                                            />
                                            {createFieldErrors.service_status && (
                                                <span className="field-error-msg">{createFieldErrors.service_status}</span>
                                            )}
                                        </div>
                                    </div>
                                    <div className="filter-group-v4" style={{ marginTop: '12px' }}>
                                        <label>Record Status</label>
                                        <FormCustomSelect
                                            name="is_active"
                                            value={createForm.is_active}
                                            onChange={handleCreateChange}
                                            options={RECORD_STATUS_CREATE_OPTIONS}
                                            placeholder="Active"
                                            ariaLabel="Record status"
                                            error={Boolean(createFieldErrors.is_active)}
                                        />
                                        {createFieldErrors.is_active && (
                                            <span className="field-error-msg">{createFieldErrors.is_active}</span>
                                        )}
                                    </div>
                                </div>

                                <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                <div className="filter-section-v4">
                                    <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>
                                        Customer <span style={{ color: 'var(--text-muted)', fontWeight: 400, textTransform: 'none' }}>(optional)</span>
                                    </h4>
                                    <div className="filter-group-v4">
                                        <CustomerPicker
                                            customer={createCustomer}
                                            onSelect={handleCreateCustomerSelect}
                                            newCustomer={createNewCustomer}
                                            onNewCustomerChange={handleCreateNewCustomerChange}
                                            fieldErrors={createFieldErrors}
                                            disabled={createSaving}
                                            error={Boolean(createFieldErrors.customer_id)}
                                            inputId="create-service-customer"
                                        />
                                        {createFieldErrors.customer_id && (
                                            <span className="field-error-msg">{createFieldErrors.customer_id}</span>
                                        )}
                                        {!createCustomer && !createNewCustomer && (
                                            <p style={{ margin: 0, fontSize: '11px', color: 'var(--text-muted)' }}>
                                                Phone and business name belong to the customer. Search for an existing
                                                one, add a new one, or leave empty for a service attached to nobody.
                                            </p>
                                        )}
                                    </div>
                                </div>

                                <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                <div className="filter-section-v4">
                                    <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Assignment</h4>
                                    <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                        <div className="filter-group-v4">
                                            <label>Relationship Manager</label>
                                            <FormCustomSelect
                                                name="rm_id"
                                                value={createForm.rm_id}
                                                onChange={handleCreateChange}
                                                options={rmCreateOptions}
                                                placeholder="Unassigned"
                                                ariaLabel="Relationship manager"
                                            />
                                            {createFieldErrors.rm_id && (
                                                <span className="field-error-msg">{createFieldErrors.rm_id}</span>
                                            )}
                                        </div>
                                        <div className="filter-group-v4">
                                            <label>Assigned OP</label>
                                            <FormCustomSelect
                                                name="op_id"
                                                value={createForm.op_id}
                                                onChange={handleCreateChange}
                                                options={opCreateOptions}
                                                placeholder="Unassigned"
                                                ariaLabel="Assigned OP"
                                            />
                                            {createFieldErrors.op_id && (
                                                <span className="field-error-msg">{createFieldErrors.op_id}</span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                                <div className="filter-section-v4">
                                    <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Follow-up (optional)</h4>
                                    <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                        <label>Follow-up At</label>
                                        <input
                                            type="datetime-local"
                                            name="followup_at"
                                            value={createForm.followup_at}
                                            onChange={handleCreateChange}
                                        />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Remarks</label>
                                        <input
                                            type="text"
                                            name="followup_remarks"
                                            value={createForm.followup_remarks}
                                            onChange={handleCreateChange}
                                            placeholder="Optional note"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="drawer-footer">
                                <button
                                    type="button"
                                    className="btn-reset-v4"
                                    onClick={() => setShowCreateService(false)}
                                    disabled={createSaving}
                                >
                                    Cancel
                                </button>
                                <button type="submit" className="btn-apply-v4" disabled={createSaving}>
                                    {createSaving ? 'Creating…' : 'Create Service'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Unified Filter Drawer */}
            {showFilterModal && (
                <div className="gst-filters-drawer-overlay" onClick={() => setShowFilterModal(false)}>
                    <div className="gst-filters-drawer" onClick={e => e.stopPropagation()}>
                        <div className="drawer-header">
                            <h2 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)' }}>Filter Customer Services</h2>
                            <button className="btn-drawer-close" onClick={() => setShowFilterModal(false)}><XCircle size={20} /></button>
                        </div>
                        
                        <div className="drawer-content">
                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Core Identifiers</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Customer ID</label>
                                        <input type="number" name="customer_id" value={filterInputs.customer_id} onChange={handleFilterChange} placeholder="Enter ID..." />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Service</label>
                                        <FormCustomSelect
                                            name="service_code"
                                            value={filterInputs.service_code}
                                            onChange={handleFilterChange}
                                            options={serviceCodeOptions}
                                            placeholder="All Services"
                                            ariaLabel="Service code"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Service Status</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Record Status</label>
                                        <FormCustomSelect
                                            name="status"
                                            value={filterInputs.status}
                                            onChange={handleFilterChange}
                                            options={optionsFromPairs([
                                                { value: '', label: 'All Status' },
                                                { value: 'ACTIVE', label: 'Active' },
                                                { value: 'INACTIVE', label: 'Inactive' },
                                            ])}
                                            placeholder="All Status"
                                            ariaLabel="Record status"
                                        />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Fulfillment Status</label>
                                        <FormCustomSelect
                                            name="service_status"
                                            value={filterInputs.service_status}
                                            onChange={handleFilterChange}
                                            options={optionsFromPairs([
                                                { value: '', label: 'All Service Status' },
                                                { value: 'PENDING', label: 'Pending' },
                                                { value: 'PROVIDED', label: 'Provided' },
                                            ])}
                                            placeholder="All Service Status"
                                            ariaLabel="Fulfillment status"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Assignment</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>RM</label>
                                        <FormCustomSelect
                                            name="rm_id"
                                            value={filterInputs.rm_id}
                                            onChange={handleFilterChange}
                                            options={rmFilterOptions}
                                            placeholder="All RMs"
                                            ariaLabel="RM filter"
                                        />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>OP</label>
                                        <FormCustomSelect
                                            name="op_id"
                                            value={filterInputs.op_id}
                                            onChange={handleFilterChange}
                                            options={opFilterOptions}
                                            placeholder="All OPs"
                                            ariaLabel="OP filter"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Timeline</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Created From</label>
                                        <FilterDateInput name="from_date" value={filterInputs.from_date} onChange={handleFilterChange} ariaLabel="Created from" />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Created To</label>
                                        <FilterDateInput name="to_date" value={filterInputs.to_date} onChange={handleFilterChange} ariaLabel="Created to" />
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="drawer-footer">
                            <button className="btn-reset-v4" onClick={clearFilters}>Reset All</button>
                            <button className="btn-apply-v4" onClick={handleSearch}>
                                {loading ? 'Searching...' : 'Apply Filters'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <div className="gst-table-wrapper cs-services-table-wrapper">
                <div className="gst-table-container">
                <div className="filings-ledger-header cs-services-grid-template">
                    <div className="filings-ledger-header-cell">ID</div>
                    <div className="filings-ledger-header-cell">Cust ID</div>
                    <div className="filings-ledger-header-cell">Customer Name</div>
                    <div className="filings-ledger-header-cell">Business Name</div>
                    <div className="filings-ledger-header-cell">Phone</div>
                    <div className="filings-ledger-header-cell">Code</div>
                    <div className="filings-ledger-header-cell">RM</div>
                    <div className="filings-ledger-header-cell">OP</div>
                    <div className="filings-ledger-header-cell">Status</div>
                    <div className="filings-ledger-header-cell">Service Status</div>
                    <div className="filings-ledger-header-cell">Follow-up</div>
                    <div className="filings-ledger-header-cell">Created At</div>
                    <div className="filings-ledger-header-cell cs-actions-sticky">Actions</div>
                </div>
                {loading ? (
                    <CustomerServicesTableSkeleton />
                ) : error ? (
                    <div className="employee-table-error">Error: {error}</div>
                ) : data.length === 0 ? (
                    <div className="cs-empty-state-v4">
                        <div className="empty-icon-stack">
                            <Search size={40} className="icon-main" />
                            <FileText size={20} className="icon-sub" />
                        </div>
                        <h3>No Services Found</h3>
                        <p>We couldn't find any customer services matching your current filters.</p>
                        {Object.values(appliedFilters).some(v => v !== '') && (
                            <button className="btn-reset-v4" onClick={clearFilters} style={{ marginTop: '16px' }}>
                                Clear All Filters
                            </button>
                        )}
                    </div>
                ) : (
                    <div className="filings-ledger-body">
                        {data.map((item) => (
                            <div
                                key={item.id}
                                className={`filings-ledger-row cs-services-grid-template ${activeFollowupId === item.id ? 'active-drawer-row' : ''} ${selectedServiceId === item.id ? 'cs-row-active' : ''}`}
                            >
                                <div className="filings-ledger-cell">{item.id}</div>
                                <div className="filings-ledger-cell">{item.customer_id ?? '-'}</div>
                                <div className="filings-ledger-cell bold-cell">
                                    {item.customer_id == null
                                        ? 'Unattached'
                                        : (item.full_name === 'string' ? `Customer ${item.customer_id}` : (item.full_name || '-'))}
                                </div>
                                <div className="filings-ledger-cell ledger-cell-longtext" title={item.business_name}>{item.business_name || '-'}</div>
                                <div className="filings-ledger-cell">{item.mobile || '-'}</div>
                                <div className="filings-ledger-cell"><code className="code-badge">{item.service_code}</code></div>
                                <div className="filings-ledger-cell">{resolveRmLabel(item)}</div>
                                <div className="filings-ledger-cell">{resolveOpLabel(item)}</div>
                                <div className="filings-ledger-cell">
                                    <span className={`service-status-chip ${recordStatusLabel(item) === 'ACTIVE' ? 'status-active' : 'required'}`}>
                                        {recordStatusLabel(item)}
                                    </span>
                                </div>
                                <div className="filings-ledger-cell">
                                    <span className={`service-status-chip ${item.service_status === 'PROVIDED' ? 'status-provided' :
                                        item.service_status === 'PENDING' ? 'pending' :
                                            item.service_status === 'PARTIAL' ? 'partial' :
                                                item.service_status === 'REQUIRED' ? 'required' : 'pending'
                                        }`}>
                                        {item.service_status ? item.service_status.replace('_', ' ') : '-'}
                                    </span>
                                </div>
                                <div className="filings-ledger-cell">
                                    {item.service_status === 'PROVIDED' ? (
                                        <span className="cs-followup-na">—</span>
                                    ) : (
                                        <button
                                            className={`btn-followup-toggle ${activeFollowupId === item.id ? 'active' : ''}`}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setActiveFollowupId(item.id);
                                                setFollowupServiceData(item);
                                            }}
                                        >
                                            <Plus size={14} />
                                            <span>Create</span>
                                        </button>
                                    )}
                                </div>
                                <div className="filings-ledger-cell">{formatDateTime(item.created_at)}</div>
                                <div className="filings-ledger-cell cs-actions-sticky">
                                    <div className="table-actions-combined">
                                        <button
                                            type="button"
                                            className="btn-view-services-mini btn-view-icon-only"
                                            title="View service"
                                            aria-label="View service"
                                            onClick={(e) => openServiceView(item, e)}
                                        >
                                            <Eye size={16} />
                                        </button>
                                        <button
                                            type="button"
                                            className="btn-edit-action"
                                            title="Edit service"
                                            aria-label="Edit service"
                                            onClick={(e) => openServiceEdit(item, e)}
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
                currentPage={currentPage}
                onPageChange={setCurrentPage}
                hasMore={data.length >= rowsPerPage}
                loading={loading}
            />

            {/* --- FOLLOW-UP SIDE DRAWER --- */}
            <div className={`followup-drawer-overlay ${activeFollowupId ? 'show' : ''}`} onClick={() => {
                setActiveFollowupId(null);
                setFollowupServiceData(null);
            }}>
                <div className={`followup-drawer-panel ${activeFollowupId ? 'show' : ''}`} onClick={e => e.stopPropagation()}>
                    <div className="drawer-header">
                        <div className="drawer-title">
                            <Clock size={14} />
                            <div>
                                <h3>Follow-up Management</h3>
                                <div className="drawer-task-identity">
                                    <span className="task-id-pill">{followupServiceData?.id}</span>
                                    <span className="task-service-text">{followupServiceData?.service_name}</span>
                                </div>
                            </div>
                        </div>
                        <button className="btn-close-drawer" onClick={() => {
                            setActiveFollowupId(null);
                            setFollowupServiceData(null);
                        }}>&times;</button>
                    </div>
                    
                    <div className="drawer-body" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 100px)', overflow: 'visible' }}>
                        {activeFollowupId && (
                            <FollowupManager 
                                serviceId={activeFollowupId}
                                serviceData={followupServiceData}
                                rmUsername={usernameByEmpId[String(followupServiceData?.rm_id)] || '-'}
                                isAdmin={isAdmin}
                                setToastMessage={setToastMessage}
                                onServiceUpdated={(updated) => {
                                    setFollowupServiceData((prev) => ({ ...prev, ...updated }));
                                    fetchServices();
                                }}
                                onFollowupCreated={() => {
                                    setActiveFollowupId(null);
                                    setFollowupServiceData(null);
                                    fetchServices();
                                }}
                            />
                        )}
                    </div>
                </div>
            </div>

            {selectedServiceId && (
                <CustomerServiceDetailsModal
                    key={`cs-${selectedServiceId}-${detailsEditMode ? 'edit' : 'view'}`}
                    serviceId={selectedServiceId}
                    initialService={selectedService}
                    initialRmUsername={selectedService ? resolveRmLabel(selectedService) : '-'}
                    initialOpUsername={selectedService ? resolveOpLabel(selectedService) : '-'}
                    isAdmin={isAdmin}
                    setToastMessage={setToastMessage}
                    onUpdated={fetchServices}
                    initialEditMode={detailsEditMode}
                    onClose={closeServiceDetails}
                />
            )}

            {/* Inline payment — stays on the Customer Services tab instead of
                switching to the add-payment tab (keeps the flow within 2 tabs). */}
            {showAddPayment && (
                <AddPayment
                    initialServiceType="CUSTOMER_SERVICE"
                    onBack={() => {
                        setShowAddPayment(false);
                        fetchServices();
                    }}
                />
            )}
        </div>
    );
};

export default CustomerServices;
