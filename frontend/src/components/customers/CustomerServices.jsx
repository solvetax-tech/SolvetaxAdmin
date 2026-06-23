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
import FormCustomSelect from '../common/FormCustomSelect';
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
                        onClick={() =>
                            navigate('/dashboard?tab=add-payment&service_type=CUSTOMER_SERVICE&return_tab=customer-services')
                        }
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
                </div>
            </div>

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
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Core Identifiers</h4>
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
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Service Status</h4>
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
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Assignment</h4>
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
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Timeline</h4>
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
                                <div className="filings-ledger-cell">{item.customer_id}</div>
                                <div className="filings-ledger-cell bold-cell">
                                    {item.full_name === 'string' ? `Customer ${item.customer_id}` : (item.full_name || '-')}
                                </div>
                                <div className="filings-ledger-cell" title={item.business_name}>{item.business_name || '-'}</div>
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
        </div>
    );
};

export default CustomerServices;
