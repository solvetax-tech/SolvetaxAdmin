/**
 * @file Employee.jsx
 * @description Provides the UI for managing employees across the organization.
 * Features a paginated table view and an extensive filtering interface
 * allowing Admins/Managers to search by role, activity status, identifiers, etc.
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import '../Dashboard.css';
import './employee.css';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';

import { Search, Filter, RefreshCcw, ChevronLeft, ChevronRight, UserPlus, Settings, RotateCcw, Plus, X, Eye, Pencil, AlertCircle } from 'lucide-react';
import { getRoleBadgeClass, getRoleDisplayLabel, isCoAdmin } from '../../utils/roleBadgeUtils';
import api from '../../utils/api';
import Button from '../ui/Button';
import StatusPill from '../ui/StatusPill';
import LoadingOverlay from '../common/LoadingOverlay';
import Pagination from '../common/Pagination';

/** Role → pill tone: ADMIN = authority (amber), *MANAGER = info (blue), else neutral. */
const roleTone = (role) => {
    const r = String(role || '').toUpperCase();
    if (r === 'ADMIN') return 'warning';
    if (r.includes('MANAGER')) return 'info';
    return 'neutral';
};
import AddEmployeeModal from './AddEmployeeModal';
import EmployeeDetailsModal from './EmployeeDetailsModal';
import ActivationConfirmModal from './ActivationConfirmModal';
import Toast from '../common/Toast';
import './EmployeeDetailsModal.css';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

const Employee = ({ handleLogout, canSignup, isAdmin, profileData }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [isExporting, setIsExporting] = useState(false);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false);
    const [isActivationModalOpen, setIsActivationModalOpen] = useState(false);
    const [selectedEmpId, setSelectedEmpId] = useState(null);
    const [detailsEditMode, setDetailsEditMode] = useState(false);
    const [selectedEmployee, setSelectedEmployee] = useState(null);
    const [autoOpenEmpId, setAutoOpenEmpId] = useState(null);
    const [toast, setToast] = useState(null);
    const [error, setError] = useState(null);
    const [hasFetched, setHasFetched] = useState(false);
    const [showFilterModal, setShowFilterModal] = useState(false);
    const [roles, setRoles] = useState([]);
    const [managerMap, setManagerMap] = useState({});

    // Employee Filters
    const [filterInputs, setFilterInputs] = useState({
        empId: '',
        username: '',
        email: '',
        firstName: '',
        lastName: '',
        phoneNumber: '',
        role: [], // Changed to array
        isActive: '',
        createdAtFrom: '',
        createdAtTo: '',
    });

    const [appliedFilters, setAppliedFilters] = useState({
        empId: '',
        username: '',
        email: '',
        firstName: '',
        lastName: '',
        phoneNumber: '',
        role: [], // Changed to array
        isActive: '',
        createdAtFrom: '',
        createdAtTo: '',
    });

    const [empPage, setEmpPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [rowsPerPage] = useState(20);
    const abortControllerRef = useRef(null);

    useEffect(() => {
        const fetchRoles = async () => {
            try {
                const res = await api.get('/api/v1/employees/roles');
                setRoles(Array.isArray(res.data) ? res.data : []);
            } catch (err) {
                console.error("Failed to fetch roles", err);
            }
        };

        const fetchManagers = async () => {
            try {
                // Fetch potential managers (constrained by backend limit of 100)
                const res = await api.get('/api/v1/employees/filter?limit=100&is_active=true');
                const list = Array.isArray(res.data) ? res.data : (res.data?.data || []);
                const map = {};
                list.forEach(m => {
                    if (m.emp_id && m.username) {
                        map[String(m.emp_id)] = m.username;
                    }
                });
                setManagerMap(map);
            } catch (err) {
                console.error("Failed to fetch manager map", err);
            }
        };

        fetchRoles();
        fetchManagers();
    }, []);

    const fetchData = useCallback(async () => {
        if (abortControllerRef.current) abortControllerRef.current.abort();
        const controller = new AbortController();
        abortControllerRef.current = controller;

        setLoading(true);
        setError(null);
        setHasFetched(false);

        try {
            const params = new URLSearchParams();

            if (appliedFilters.empId) params.append('emp_id', appliedFilters.empId);
            if (appliedFilters.username) params.append('username', appliedFilters.username);
            if (appliedFilters.email) params.append('email', appliedFilters.email);
            if (appliedFilters.firstName || appliedFilters.lastName) {
                const fullName = [appliedFilters.firstName, appliedFilters.lastName].filter(Boolean).join(' ');
                params.append('full_name', fullName);
            }
            if (appliedFilters.phoneNumber) params.append('phone_number', appliedFilters.phoneNumber);
            if (Array.isArray(appliedFilters.role) && appliedFilters.role.length > 0) {
                appliedFilters.role.forEach(r => params.append('role', r));
            }

            if (appliedFilters.isActive === 'active') {
                params.append('is_active', 'true');
            } else if (appliedFilters.isActive === 'inactive') {
                params.append('is_active', 'false');
                params.append('include_inactive', 'true');
            } else {
                params.append('include_inactive', 'true');
            }

            if (appliedFilters.createdAtFrom) params.append('from_date', appliedFilters.createdAtFrom);
            if (appliedFilters.createdAtTo) params.append('to_date', appliedFilters.createdAtTo);

            params.append('limit', rowsPerPage);
            params.append('offset', (empPage - 1) * rowsPerPage);

            const response = await api.get(`/api/v1/employees/filter?${params.toString()}`, {
                signal: controller.signal
            });

            const result = response.data;
            setData(Array.isArray(result) ? result : (result.data || result.items || []));
            if (result.total_pages) setTotalPages(result.total_pages);
        } catch (err) {
            if (axios.isCancel(err) || err.name === 'CanceledError') return;
            if (localStorage.getItem('session_token')) {
                setError(`${err.message} (Check network/backend)`);
            }
        } finally {
            if (!controller.signal.aborted) {
                setLoading(false);
                setHasFetched(true);
            }
        }
    }, [appliedFilters, empPage, rowsPerPage, handleLogout]);

    useEffect(() => {
        fetchData();
        return () => {
            if (abortControllerRef.current) abortControllerRef.current.abort();
        };
    }, [empPage, rowsPerPage, fetchData]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const eid = params.get('emp_id');
        if (eid) {
            setFilterInputs(prev => ({ ...prev, empId: eid }));
            setAppliedFilters(prev => ({ ...prev, empId: eid }));
            setEmpPage(1);
            setAutoOpenEmpId(eid);
        }
    }, [location.search]);

    useEffect(() => {
        if (!autoOpenEmpId) return;
        if (!data || data.length === 0) return;
        const match = data.find(item => String(item.emp_id) === String(autoOpenEmpId));
        if (match) {
            setSelectedEmpId(match.emp_id);
            setDetailsEditMode(false);
            setIsDetailsModalOpen(true);
            setAutoOpenEmpId(null);
        }
    }, [autoOpenEmpId, data]);

    // Creating and editing employees is ADMIN-only. Other roles (RM, OP,
    // SALES_MANAGER, OP_MANAGER, …) get read-only access: they can view a
    // profile but see no "New Employee" button and no edit action.
    const canEditEmployee = isAdmin;

    const openEmployeeView = (item, e) => {
        e?.stopPropagation();
        setSelectedEmpId(item.emp_id);
        setDetailsEditMode(false);
        setIsDetailsModalOpen(true);
    };

    const openEmployeeEdit = (item, e) => {
        e?.stopPropagation();
        if (!item.is_active && isAdmin) {
            setSelectedEmployee(item);
            setIsActivationModalOpen(true);
            return;
        }
        setSelectedEmpId(item.emp_id);
        setDetailsEditMode(true);
        setIsDetailsModalOpen(true);
    };

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const handleSearch = () => {
        setHasFetched(false);
        setEmpPage(1);
        setAppliedFilters({ ...filterInputs });
    };

    const clearFilters = () => {
        setHasFetched(false);
        const emptyFilters = {
            empId: '', username: '', email: '', firstName: '', lastName: '',
            phoneNumber: '', role: [], isActive: '', createdAtFrom: '',
            createdAtTo: '',
        };
        setFilterInputs(emptyFilters);
        setAppliedFilters(emptyFilters);
        setEmpPage(1);
    };

    const handleRoleToggle = (roleCode) => {
        setFilterInputs(prev => {
            const currentRoles = prev.role || [];
            const newRoles = currentRoles.includes(roleCode)
                ? currentRoles.filter(r => r !== roleCode)
                : [...currentRoles, roleCode];
            return { ...prev, role: newRoles };
        });
    };

    const removeFilter = (key) => {
        const newValue = key === 'role' ? [] : '';
        setFilterInputs(prev => ({ ...prev, [key]: newValue }));
        setAppliedFilters(prev => ({ ...prev, [key]: newValue }));
        setEmpPage(1);
    };

    const renderFilterChips = () => {
        const labels = {
            empId: 'ID',
            username: 'Username',
            email: 'Email',
            firstName: 'First Name',
            lastName: 'Last Name',
            phoneNumber: 'Phone',
            role: 'Role',
            isActive: 'Status',
            createdAtFrom: 'From',
            createdAtTo: 'To'
        };

        return Object.entries(appliedFilters)
            .filter(([key, value]) => {
                if (key === 'role') return Array.isArray(value) && value.length > 0;
                return value !== '' && value !== null;
            })
            .map(([key, value]) => (
                <div key={key} className="filter-chip">
                    <span className="filter-chip-label">{labels[key] || key}:</span>
                    <span className="filter-chip-value">
                        {key === 'role' ? value.join(', ') : value}
                    </span>
                    <button className="btn-remove-chip" onClick={() => removeFilter(key)}>
                        <X size={12} />
                    </button>
                </div>
            ));
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


    // Calculate simple stats based on loaded data (approximation since it's only for the current view/page or needs a separate API call)
    // For now, we'll show meaningful placeholders or use the data length if total count isn't available
    const renderFilterFields = () => (
        <div className="premium-filter-grid">
            <div className="filter-field">
                <label>Employee ID</label>
                <input type="text" name="empId" value={filterInputs.empId} onChange={handleFilterChange} placeholder="Enter ID..." />
            </div>
            <div className="filter-field">
                <label>Username</label>
                <input type="text" name="username" value={filterInputs.username} onChange={handleFilterChange} placeholder="Enter Username..." />
            </div>
            <div className="filter-field">
                <label>First Name</label>
                <input type="text" name="firstName" value={filterInputs.firstName} onChange={handleFilterChange} placeholder="Enter First Name..." />
            </div>
            <div className="filter-field">
                <label>Last Name</label>
                <input type="text" name="lastName" value={filterInputs.lastName} onChange={handleFilterChange} placeholder="Enter Last Name..." />
            </div>
            <div className="filter-field">
                <label>Email</label>
                <input type="text" name="email" value={filterInputs.email} onChange={handleFilterChange} placeholder="Enter Email..." />
            </div>
            <div className="filter-field">
                <label>Phone Number</label>
                <input type="text" name="phoneNumber" value={filterInputs.phoneNumber} onChange={handleFilterChange} placeholder="Enter Phone..." />
            </div>
            <div className="filter-field multi-select-field">
                <label>Roles</label>
                <div className="multi-checkbox-group">
                    {roles.map(r => (
                        <label key={r.role_code} className="checkbox-item">
                            <input
                                type="checkbox"
                                checked={filterInputs.role.includes(r.role_code)}
                                onChange={() => handleRoleToggle(r.role_code)}
                            />
                            <span>{r.role_code}</span>
                        </label>
                    ))}
                </div>
            </div>
            {renderStatusFilter(filterInputs.isActive, handleFilterChange)}
            <div className="filter-field">
                <label>Created From</label>
                <FilterDateInput name="createdAtFrom" value={filterInputs.createdAtFrom || ''} onChange={handleFilterChange} ariaLabel="From date" />
            </div>
            <div className="filter-field">
                <label>Created To</label>
                <FilterDateInput name="createdAtTo" value={filterInputs.createdAtTo || ''} onChange={handleFilterChange} ariaLabel="To date" />
            </div>
        </div>
    );

    const hasActiveFilters = useMemo(() => (
        Boolean(
            appliedFilters.empId ||
            appliedFilters.username ||
            appliedFilters.email ||
            appliedFilters.firstName ||
            appliedFilters.lastName ||
            appliedFilters.phoneNumber ||
            (Array.isArray(appliedFilters.role) && appliedFilters.role.length > 0) ||
            appliedFilters.isActive ||
            appliedFilters.createdAtFrom ||
            appliedFilters.createdAtTo
        )
    ), [appliedFilters]);

    const TableSkeleton = () => (
        <div className="filings-ledger-body">
            {[...Array(12)].map((_, i) => (
                <div key={i} className="filings-ledger-row employee-grid-template">
                    <div className="filings-ledger-cell sticky-id-column"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell"><div className="filings-ledger-skeleton-bar" /></div>
                    <div className="filings-ledger-cell employee-actions-sticky"><div className="filings-ledger-skeleton-bar" style={{ width: '60px', margin: '0 auto' }} /></div>
                </div>
            ))}
        </div>
    );

    return (
        <div className="employee-tab-container">
            <div className="gst-action-bar-v2">
                <div className="active-filters-container">
                    {renderFilterChips()}
                </div>
                <div className="gst-action-buttons">
                    {hasActiveFilters && (
                        <Button variant="ghost" size="sm" icon={<RotateCcw size={14} />} onClick={clearFilters}>
                            Reset Filters
                        </Button>
                    )}
                    <Button variant="secondary" size="sm" icon={<Filter size={13} />} onClick={() => setShowFilterModal(true)}>
                        Filters
                    </Button>
                    {canEditEmployee && (
                        <Button variant="primary" size="sm" icon={<Plus size={13} />} onClick={() => setIsModalOpen(true)}>
                            New Employee
                        </Button>
                    )}
                </div>
            </div>

            {/* Filter Drawer */}
            <div className={`premium-drawer-overlay ${showFilterModal ? 'show' : ''}`} onClick={() => setShowFilterModal(false)}>
                <div className="premium-drawer-right" onClick={e => e.stopPropagation()}>
                    <div className="drawer-header-v4">
                        <h2><Filter size={20} /> Filter Employees</h2>
                        <button className="btn-drawer-close" onClick={() => setShowFilterModal(false)}><X size={18} /></button>
                    </div>

                    <div className="drawer-content-v4">
                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Core Identifiers</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>Employee ID</label>
                                    <input type="text" name="empId" value={filterInputs.empId} onChange={handleFilterChange} placeholder="ID..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Username</label>
                                    <input type="text" name="username" value={filterInputs.username} onChange={handleFilterChange} placeholder="Search..." />
                                </div>
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border-subtle)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Personal Details</h4>
                            <div className="drawer-filter-grid">
                                <div className="filter-group-v4">
                                    <label>First Name</label>
                                    <input type="text" name="firstName" value={filterInputs.firstName} onChange={handleFilterChange} placeholder="First name..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Last Name</label>
                                    <input type="text" name="lastName" value={filterInputs.lastName} onChange={handleFilterChange} placeholder="Last name..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Email</label>
                                    <input type="text" name="email" value={filterInputs.email} onChange={handleFilterChange} placeholder="Email..." />
                                </div>
                                <div className="filter-group-v4">
                                    <label>Phone Number</label>
                                    <input type="text" name="phoneNumber" value={filterInputs.phoneNumber} onChange={handleFilterChange} placeholder="Phone..." />
                                </div>
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border-subtle)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Configuration</h4>
                            <div className="drawer-filter-grid">
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
                                <div className="filter-group-v4">
                                    <label>From Date</label>
                                    <FilterDateInput name="createdAtFrom" value={filterInputs.createdAtFrom || ''} onChange={handleFilterChange} ariaLabel="From date" />
                                </div>
                                <div className="filter-group-v4">
                                    <label>To Date</label>
                                    <FilterDateInput name="createdAtTo" value={filterInputs.createdAtTo || ''} onChange={handleFilterChange} ariaLabel="To date" />
                                </div>

                                <div className="filter-group-v4 full-width">
                                    <label>Roles</label>
                                    <div className="multi-checkbox-drawer">
                                        {roles.map(r => (
                                            <label key={r.role_code} className="checkbox-item-v4">
                                                <input
                                                    type="checkbox"
                                                    checked={filterInputs.role.includes(r.role_code)}
                                                    onChange={() => handleRoleToggle(r.role_code)}
                                                />
                                                <span>{r.role_code}</span>
                                            </label>
                                        ))}
                                    </div>
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

            {isModalOpen && (
                <AddEmployeeModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    onSuccess={() => {
                        setIsModalOpen(false);
                        setToast({ message: 'Employee added successfully! ✨', type: 'success' });
                        fetchData();
                    }}
                />
            )}

            {isDetailsModalOpen && (
                <EmployeeDetailsModal
                    key={selectedEmpId ? `emp-${selectedEmpId}-${detailsEditMode}` : 'emp-closed'}
                    isOpen={isDetailsModalOpen}
                    onClose={() => {
                        setIsDetailsModalOpen(false);
                        setSelectedEmpId(null);
                        setDetailsEditMode(false);
                        fetchData();
                    }}
                    empId={selectedEmpId}
                    isAdmin={isAdmin}
                    initialEditMode={detailsEditMode}
                />
            )}

            {isActivationModalOpen && (
                <ActivationConfirmModal
                    isOpen={isActivationModalOpen}
                    onClose={() => {
                        setIsActivationModalOpen(false);
                        setSelectedEmployee(null);
                    }}
                    employee={selectedEmployee}
                    onActivate={() => {
                        setIsActivationModalOpen(false);
                        setSelectedEmpId(selectedEmployee.emp_id);
                        setDetailsEditMode(true);
                        setIsDetailsModalOpen(true);
                        setSelectedEmployee(null);
                        fetchData();
                    }}
                />
            )}

            {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

            <div className="employee-table-container">
                <div className="filings-ledger-header employee-grid-template">
                        <div className="filings-ledger-header-cell sticky-id-column">Emp ID</div>
                        <div className="filings-ledger-header-cell">Email Address</div>
                        <div className="filings-ledger-header-cell">First Name</div>
                        <div className="filings-ledger-header-cell">Last Name</div>
                        <div className="filings-ledger-header-cell">Phone</div>
                        <div className="filings-ledger-header-cell">Role</div>
                        <div className="filings-ledger-header-cell">Manager</div>
                        <div className="filings-ledger-header-cell">Active</div>
                        <div className="filings-ledger-header-cell">Created At</div>
                        <div className="filings-ledger-header-cell employee-actions-sticky">Actions</div>
                    </div>

                    {loading ? (
                        <TableSkeleton />
                    ) : error ? (
                        <div className="employee-table-error" style={{ padding: '40px', textAlign: 'center', color: 'var(--danger)' }}>
                            <AlertCircle size={32} style={{ marginBottom: '12px' }} />
                            <p>Error: {error}</p>
                        </div>
                    ) : (data.length === 0 && hasFetched) ? (
                        <div className="employee-table-msg" style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
                            <Search size={32} style={{ marginBottom: '12px', opacity: 0.5 }} />
                            <p>No employees found matching filters.</p>
                        </div>
                    ) : (
                        <div className="filings-ledger-body">
                            {data.map(item => (
                                <div
                                    key={item.emp_id}
                                    className="filings-ledger-row employee-grid-template"
                                >
                                    <div className="filings-ledger-cell sticky-id-column">
                                        <button type="button" className="row-id-link" title="View employee" onClick={(e) => openEmployeeView(item, e)}>{item.emp_id}</button>
                                    </div>
                                    <div className="filings-ledger-cell" style={{ color: 'var(--text-primary)' }}>{item.email}</div>
                                    <div className="filings-ledger-cell">{item.first_name || '-'}</div>
                                    <div className="filings-ledger-cell">{item.last_name || '-'}</div>
                                    <div className="filings-ledger-cell"><span className="ui-num">{item.phone_number || '-'}</span></div>
                                    <div className="filings-ledger-cell">
                                        <StatusPill value={getRoleDisplayLabel(item)} tone={isCoAdmin(item) ? 'co-admin' : roleTone(item.role)} dot={false} />
                                    </div>
                                    <div className="filings-ledger-cell" title={item.manager_username}>
                                        {item.manager_username || managerMap[String(item.manager_emp_id)] || (
                                            <span className="direct-report-tag">Direct Report</span>
                                        )}
                                    </div>
                                    <div className="filings-ledger-cell">
                                        <StatusPill tone={item.is_active ? 'success' : 'danger'}>
                                            {item.is_active ? 'Active' : 'Inactive'}
                                        </StatusPill>
                                    </div>
                                    <div className="filings-ledger-cell">
                                        <span className="ui-num" style={{ color: 'var(--text-primary)' }}>
                                            {item.created_at ? new Date(item.created_at).toLocaleDateString() : '-'}
                                        </span>
                                    </div>
                                    <div className="filings-ledger-cell gst-action-buttons employee-actions-sticky" style={{ justifyContent: 'center', gap: '6px' }}>
                                        <Button variant="ghost" icon={<Eye size={14} />} title="View profile" onClick={(e) => openEmployeeView(item, e)} />
                                        {canEditEmployee && (
                                            <Button
                                                variant="ghost"
                                                icon={<Pencil size={14} />}
                                                title={!item.is_active && isAdmin ? 'Activate employee' : 'Edit profile'}
                                                onClick={(e) => openEmployeeEdit(item, e)}
                                            />
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
            </div>

            <Pagination
                currentPage={empPage}
                onPageChange={setEmpPage}
                hasMore={data.length >= rowsPerPage}
                loading={loading}
            />
        </div>
    );
};

export default Employee;
