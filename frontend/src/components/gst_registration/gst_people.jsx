/**
 * @file gst_people.jsx
 * @description Renders the GST People table and detailed view component.
 * Enables searching, filtering, and editing of stakeholders bound to GST registrations.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useLocation } from 'react-router-dom';
import '../Dashboard.css';
import '../employees/EmployeeDetailsModal.css';
import api from '../../utils/api';
import { canManageRmOpRecords } from '../../utils/rmOpAssignmentFields';
import LoadingOverlay from '../common/LoadingOverlay';
import Pagination from '../common/Pagination';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import './gst_registration.css';
import './GSTRegistrationSignup.css';
import './gst_people.css';
import { Filter, X, RotateCcw, Plus, AlertCircle, CheckCircle2, Upload, Eye, Pencil, User, FileText } from 'lucide-react';
import UploadDocuments from './UploadDocuments';
import GSTPeopleViewPanel from './GSTPeopleViewPanel';
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

const GST_PERSON_DESIGNATIONS = [
    'Proprietor', 'Partner', 'Director', 'Managing Director', 'Karta',
    'Trustee', 'Authorised Signatory', 'Member', 'Others',
];
const designationFilterOptions = (placeholder) => optionsFromPairs([
    { value: '', label: placeholder },
    ...GST_PERSON_DESIGNATIONS.map((d) => ({ value: d, label: d })),
]);

const BASE_URL = import.meta.env.VITE_API_URL;

const extractGstPeopleError = (err) => {
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

const formatDateTime = (dtStr) => {
    if (!dtStr) return '-';
    try {
        return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
    } catch {
        return dtStr;
    }
};

export const GSTPeople = ({ handleLogout, isAdmin, profileData, onRenderToolbar }) => {
    const canEdit = canManageRmOpRecords(profileData, isAdmin);
    const navigate = useNavigate();
    const location = useLocation();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [showFilterModal, setShowFilterModal] = useState(false);
    const rowsPerPage = 20;
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showDetailsModal, setShowDetailsModal] = useState(false);
    const [selectedPerson, setSelectedPerson] = useState(null);
    const [autoOpenPersonId, setAutoOpenPersonId] = useState(null);
    const [showUploadModal, setShowUploadModal] = useState(false);
    const [selectedPersonForUpload, setSelectedPersonForUpload] = useState(null);
    const [viewPanelOpen, setViewPanelOpen] = useState(false);
    const [viewPersonId, setViewPersonId] = useState(null);
    const [showEditModal, setShowEditModal] = useState(false);
    const [editModalMode, setEditModalMode] = useState(false);

    const [filterInputs, setFilterInputs] = useState({
        gstin: '', full_name: '', mobile: '', email: '',
        person_id: '', customer_id: '', gst_registration_id: '',
        designation: '',
        is_active: '',
        from_date: '', to_date: ''
    });

    const [appliedFilters, setAppliedFilters] = useState({
        gstin: '', full_name: '', mobile: '', email: '',
        person_id: '', customer_id: '', gst_registration_id: '',
        designation: '',
        is_active: '',
        from_date: '', to_date: ''
    });

    const fetchGstData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            Object.entries(appliedFilters).forEach(([key, value]) => {
                if (value !== '' && value !== null && value !== undefined) {
                    // Convert booleans to strings explicitly to avoid backend confusion if necessary
                    const paramValue = typeof value === 'boolean' ? value.toString() : value;
                    params.append(key, paramValue);
                }
            });
            params.append('offset', (currentPage - 1) * rowsPerPage);
            params.append('limit', rowsPerPage);

            const response = await api.get(`/api/v1/gst-people/dynamic_filter?${params.toString()}`);

            const result = response.data;
            const items = Array.isArray(result) ? result : (result.data || []);
            setData(items);

            if (result.total_count) {
                setTotalPages(Math.ceil(result.total_count / rowsPerPage));
            } else {
                setTotalPages(items.length < rowsPerPage ? currentPage : currentPage + 1);
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [appliedFilters, currentPage]);

    const GSTPeopleTableSkeleton = () => (
        <div className="filings-ledger-body">
            {[...Array(12)].map((_, i) => (
                <div key={i} className="filings-ledger-row gst-people-grid-template">
                    {[...Array(12)].map((_, j) => (
                        <div key={j} className="filings-ledger-cell">
                            <div className="filings-ledger-skeleton-bar" />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );

    useEffect(() => {
        fetchGstData();
    }, [fetchGstData]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const personId = params.get('person_id');
        const gstRegId = params.get('gst_registration_id');
        const gstin = params.get('gstin');
        const designation = params.get('designation');
        if (personId) {
            setFilterInputs(prev => ({ ...prev, person_id: personId }));
            setAppliedFilters(prev => ({ ...prev, person_id: personId }));
            setCurrentPage(1);
            setAutoOpenPersonId(personId);
        }
        if (gstRegId) {
            setFilterInputs(prev => ({ ...prev, gst_registration_id: gstRegId }));
            setAppliedFilters(prev => ({ ...prev, gst_registration_id: gstRegId }));
            setCurrentPage(1);
        }
        if (gstin) {
            setFilterInputs(prev => ({ ...prev, gstin }));
            setAppliedFilters(prev => ({ ...prev, gstin }));
            setCurrentPage(1);
        }
        if (designation) {
            setFilterInputs(prev => ({ ...prev, designation }));
            setAppliedFilters(prev => ({ ...prev, designation }));
            setCurrentPage(1);
        }
    }, [location.search]);

    useEffect(() => {
        if (!autoOpenPersonId) return;
        if (!data || data.length === 0) return;
        const match = data.find(item => String(item.person_id) === String(autoOpenPersonId));
        if (match) {
            setSelectedPerson(match);
            setShowDetailsModal(true);
            setAutoOpenPersonId(null);
        }
    }, [autoOpenPersonId, data]);

    const openPersonView = (item, e) => {
        e?.stopPropagation();
        setViewPersonId(item.person_id);
        setViewPanelOpen(true);
    };

    const openPersonEdit = (item, e) => {
        e?.stopPropagation();
        setSelectedPerson(item);
        setEditModalMode(true);
        setShowDetailsModal(true);
    };

    const handleRowClick = (item) => {
        openPersonView(item);
    };

    const closeDetailsModal = () => {
        setShowDetailsModal(false);
        setSelectedPerson(null);
        setEditModalMode(false);
    };

    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFilterInputs(prev => ({ ...prev, [name]: value }));
    };

    const handleSearch = () => {
        setCurrentPage(1);
        setAppliedFilters({ ...filterInputs });
    };

    const clearFilters = () => {
        const empty = {
            gstin: '', full_name: '', mobile: '', email: '',
            person_id: '', customer_id: '', gst_registration_id: '',
            designation: '',
            is_active: '',
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

    const hasActivePeopleFilters = Object.entries(appliedFilters).some(([, value]) => value !== '' && value !== null);

    const renderFilterChips = () => {
        const labels = {
            gstin: 'GSTIN', full_name: 'Name', mobile: 'Mobile',
            email: 'Email', person_id: 'Person ID',
            customer_id: 'Customer ID', gst_registration_id: 'Reg ID',
            designation: 'Designation',
            is_active: 'Status',
            from_date: 'From', to_date: 'To'
        };

        return Object.entries(appliedFilters)
            .filter(([key, value]) => {
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
        <div className="premium-filter-grid">
            <div className="filter-field">
                <label>GSTIN</label>
                <input name="gstin" value={filterInputs.gstin} onChange={handleFilterChange} placeholder="Enter GSTIN..." />
            </div>
            <div className="filter-field">
                <label>Full Name</label>
                <input name="full_name" value={filterInputs.full_name} onChange={handleFilterChange} placeholder="Enter Name..." />
            </div>
            <div className="filter-field">
                <label>Customer ID</label>
                <input type="number" name="customer_id" value={filterInputs.customer_id} onChange={handleFilterChange} placeholder="Enter ID..." />
            </div>
            <div className="filter-field">
                <label>Reg ID</label>
                <input type="number" name="gst_registration_id" value={filterInputs.gst_registration_id} onChange={handleFilterChange} placeholder="Enter ID..." />
            </div>
            <div className="filter-field">
                <label>Person ID</label>
                <input type="number" name="person_id" value={filterInputs.person_id} onChange={handleFilterChange} placeholder="Enter ID..." />
            </div>
            <div className="filter-field">
                <label>Mobile</label>
                <input name="mobile" value={filterInputs.mobile} onChange={handleFilterChange} placeholder="Enter Mobile..." />
            </div>
            <div className="filter-field">
                <label>Email</label>
                <input name="email" value={filterInputs.email} onChange={handleFilterChange} placeholder="Enter Email..." />
            </div>
            <div className="filter-field">
                <label>Created From</label>
                <FilterDateInput name="from_date" value={filterInputs.from_date} onChange={handleFilterChange} ariaLabel="From date" />
            </div>
            <div className="filter-field">
                <label>Created To</label>
                <FilterDateInput name="to_date" value={filterInputs.to_date} onChange={handleFilterChange} ariaLabel="To date" />
            </div>
            <div className="filter-field">
                <label>Designation</label>
                <FormCustomSelect
                    name="designation"
                    value={filterInputs.designation}
                    onChange={handleFilterChange}
                    options={designationFilterOptions('All Designations')}
                    placeholder="All Designations"
                    ariaLabel="Designation"
                />
            </div>
            {renderStatusFilter(filterInputs.is_active, handleFilterChange)}
        </div>
    );

    const peopleTopActions = (
        <>
            <button type="button" className="btn-filter-trigger" onClick={() => setShowFilterModal(true)}>
                <Filter size={13} /> Filters
            </button>
            {hasActivePeopleFilters && (
                <button type="button" className="btn-clear-v2" onClick={clearFilters}>
                    <RotateCcw size={14} /> Reset Filters
                </button>
            )}
            {canEdit && (
                <button type="button" className="btn-primary-action" onClick={() => setShowCreateModal(true)}>
                    <Plus size={13} />
                    <span>Create Person</span>
                </button>
            )}
        </>
    );

    useEffect(() => {
        if (!onRenderToolbar) return undefined;
        onRenderToolbar(peopleTopActions);
        return () => onRenderToolbar(null);
    }, [onRenderToolbar, hasActivePeopleFilters, canEdit, showFilterModal]);

    return (
        <div className="gst-registration-container">
            {hasActivePeopleFilters && (
                <div className="gst-portal-filter-chips-row">
                    <div className="active-filters-container">
                        {renderFilterChips()}
                    </div>
                </div>
            )}

            {/* Unified Filter Drawer */}
            {showFilterModal && (
                <div className="gst-filters-drawer-overlay" onClick={() => setShowFilterModal(false)}>
                    <div className="gst-filters-drawer" onClick={e => e.stopPropagation()}>
                        <div className="drawer-header">
                            <h2>Filter GST People</h2>
                            <button className="btn-drawer-close" onClick={() => setShowFilterModal(false)}><X size={20} /></button>
                        </div>
                        
                        <div className="drawer-content">
                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Core Identifiers</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Person ID</label>
                                        <input type="number" name="person_id" value={filterInputs.person_id} onChange={handleFilterChange} placeholder="ID..." />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Customer ID</label>
                                        <input type="number" name="customer_id" value={filterInputs.customer_id} onChange={handleFilterChange} placeholder="ID..." />
                                    </div>
                                </div>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px', marginTop: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Reg ID</label>
                                        <input type="number" name="gst_registration_id" value={filterInputs.gst_registration_id} onChange={handleFilterChange} placeholder="ID..." />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>GSTIN</label>
                                        <input name="gstin" value={filterInputs.gstin} onChange={handleFilterChange} placeholder="GSTIN..." />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Stakeholder Profile</h4>
                                <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                    <label>Full Name</label>
                                    <input name="full_name" value={filterInputs.full_name} onChange={handleFilterChange} placeholder="Search by name..." />
                                </div>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Designation</label>
                                        <FormCustomSelect
                                            name="designation"
                                            value={filterInputs.designation}
                                            onChange={handleFilterChange}
                                            options={designationFilterOptions('All Designations')}
                                            placeholder="All Designations"
                                            ariaLabel="Designation"
                                        />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Active Status</label>
                                        <FormCustomSelect
                                            name="is_active"
                                            value={filterInputs.is_active}
                                            onChange={handleFilterChange}
                                            options={optionsFromPairs([
                                                { value: '', label: 'Any Status' },
                                                { value: 'true', label: 'Active Only' },
                                                { value: 'false', label: 'Inactive Only' },
                                            ])}
                                            placeholder="Any Status"
                                            ariaLabel="Active status"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Contact Information</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Mobile Number</label>
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
                                <h4 className="section-title" style={{ fontSize: '10px', color: '#2eb87a', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Audit Timeline</h4>
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

                        <div className="drawer-footer">
                            <button className="btn-reset-v4" onClick={clearFilters}>Reset All</button>
                            <button className="btn-apply-v4" onClick={() => { handleSearch(); setShowFilterModal(false); }}>
                                {loading ? 'Searching...' : 'Apply Filters'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <main className="gst-main-content-table">
                <div className="gst-table-wrapper gst-table-wrapper--portal">
                    <div className="gst-table-container gst-table-container--portal">
                        <div className="filings-ledger-header gst-people-grid-template">
                            <div className="filings-ledger-header-cell">Person ID</div>
                            <div className="filings-ledger-header-cell">Customer ID</div>
                            <div className="filings-ledger-header-cell">Registration ID</div>
                            <div className="filings-ledger-header-cell">GSTIN</div>
                            <div className="filings-ledger-header-cell">Full Name</div>
                            <div className="filings-ledger-header-cell">Designation</div>
                            <div className="filings-ledger-header-cell">Email Address</div>
                            <div className="filings-ledger-header-cell">Mobile Number</div>
                            <div className="filings-ledger-header-cell">Primary Member</div>
                            <div className="filings-ledger-header-cell">Record Status</div>
                            <div className="filings-ledger-header-cell">Ownership Category</div>
                            <div className="filings-ledger-header-cell gst-sticky-actions" style={{ justifyContent: 'center' }}>Actions</div>
                        </div>

                        {loading ? (
                            <GSTPeopleTableSkeleton />
                        ) : error ? (
                            <div className="employee-table-error">Error: {error}</div>
                        ) : data.length === 0 ? (
                            <div className="gst-no-data-v4">
                                <div className="no-data-icon-box">
                                    <FileText size={40} />
                                </div>
                                <h3>No People Found</h3>
                                <p>We couldn&apos;t find any GST people matching your current filters.</p>
                                <button type="button" className="btn-reset-v4" onClick={clearFilters} style={{ marginTop: '16px' }}>
                                    Clear All Filters
                                </button>
                            </div>
                        ) : (
                            <div className="filings-ledger-body">
                            {data.map((item, idx) => (
                                <div 
                                    key={idx} 
                                    className="filings-ledger-row gst-people-grid-template gst-table-row gst-table-row--static"
                                >
                                    <div className="filings-ledger-cell gst-people-person-id-cell">{item.person_id ?? '-'}</div>
                                    <div className="filings-ledger-cell">{item.customer_id ?? '-'}</div>
                                    <div className="filings-ledger-cell">{item.gst_registration_id ?? '-'}</div>
                                    <div className="filings-ledger-cell" style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{item.gstin}</div>
                                    <div className="filings-ledger-cell" style={{ fontWeight: '600' }}>{item.full_name}</div>
                                    <div className="filings-ledger-cell" title={item.designation || ''}>{item.designation || '-'}</div>
                                    <div className="filings-ledger-cell" title={item.email || ''}>{item.email || '-'}</div>
                                    <div className="filings-ledger-cell">{item.mobile || '-'}</div>
                                    <div className="filings-ledger-cell">{item.is_primary_customer ? 'Yes' : 'No'}</div>
                                    <div className="filings-ledger-cell">
                                        <span className={`status-badge-v4 ${item.is_active ? 'completed' : 'overdue'}`}>
                                            {item.is_active ? 'ACTIVE' : 'INACTIVE'}
                                        </span>
                                    </div>
                                    <div className="filings-ledger-cell">{item.ownership_category || '-'}</div>
                                    <div className="filings-ledger-cell gst-action-buttons gst-sticky-actions" style={{ justifyContent: 'center' }}>
                                            <button
                                                type="button"
                                                className="btn-view-action"
                                                title="View Details"
                                                onClick={(e) => openPersonView(item, e)}
                                            >
                                                <Eye size={14} />
                                            </button>
                                            <button
                                                type="button"
                                                className="btn-edit-action"
                                                title="Edit Record"
                                                onClick={(e) => openPersonEdit(item, e)}
                                            >
                                                <Pencil size={14} />
                                            </button>
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
                    hasMore={currentPage < totalPages}
                    loading={loading}
                />
            </main>

            <GSTPeopleCreateModal
                isOpen={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                onSuccess={() => {
                    setShowCreateModal(false);
                    fetchGstData();
                }}
            />

            <GSTPeopleDetailsModal
                key={selectedPerson ? `person-edit-${selectedPerson.person_id}-${editModalMode}` : 'person-edit-closed'}
                isOpen={showDetailsModal}
                data={selectedPerson}
                onClose={closeDetailsModal}
                onUpdated={fetchGstData}
                isAdmin={isAdmin}
                canEdit={canEdit}
                initialEditMode={editModalMode}
            />

            <UploadDocuments
                isOpen={showUploadModal}
                onClose={() => setShowUploadModal(false)}
                initialPersonId={selectedPersonForUpload}
            />

            <GSTPeopleViewPanel 
                isOpen={viewPanelOpen}
                onClose={() => {
                    setViewPanelOpen(false);
                    setViewPersonId(null);
                }}
                personId={viewPersonId}
                onUpdate={fetchGstData}
            />
        </div>
    );
};

const GSTPeopleCreateModal = ({ isOpen, onClose, onSuccess }) => {
    const initialFormData = {
        gst_registration_id: '',
        full_name: '',
        designation: '',
        pan: '',
        aadhaar: '',
        email: '',
        mobile: '',
        is_primary_customer: false,
    };
    const [formData, setFormData] = useState(initialFormData);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [fieldErrors, setFieldErrors] = useState({});
    const [success, setSuccess] = useState(false);
    const [designations, setDesignations] = useState([]);
    const [fetchingDesignations, setFetchingDesignations] = useState(false);

    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [showResults, setShowResults] = useState(false);
    const [selectedGstInfo, setSelectedGstInfo] = useState(null);
    const ignoreSearchRef = React.useRef(false);

    useEffect(() => {
        const timer = setTimeout(async () => {
            if (ignoreSearchRef.current) {
                ignoreSearchRef.current = false;
                return;
            }

            if (!searchQuery || searchQuery.length < 1) {
                setSearchResults([]);
                setShowResults(false);
                return;
            }

            setIsSearching(true);
            setShowResults(true);

            try {
                const params = new URLSearchParams();
                if (/^\d+$/.test(searchQuery)) {
                    params.append('gst_registration_id', searchQuery);
                } else {
                    params.append('gstin', searchQuery);
                }
                
                const response = await api.get(`/api/v1/gst-registrations/dynamic_filter?${params.toString()}&limit=5`);
                const result = response.data;
                const items = Array.isArray(result) ? result : (result.data || []);
                setSearchResults(items);
            } catch (err) {
                console.error("GST search failed:", err);
                setSearchResults([]);
            } finally {
                setIsSearching(false);
            }
        }, 500);

        return () => clearTimeout(timer);
    }, [searchQuery]);

    const handleSelectGst = (record) => {
        const gstId = record.id || record.gst_registration_id;
        if (!record || !gstId) {
            setShowResults(false);
            return;
        }
        ignoreSearchRef.current = true;
        
        // Auto-fill form fields from selected registration if they are currently empty
        setFormData(prev => ({ 
            ...prev, 
            gst_registration_id: gstId,
            full_name: prev.full_name || record.business_name || record.legal_name || record.trade_name || '',
            pan: prev.pan || record.pan || '',
            email: prev.email || record.email || '',
            mobile: prev.mobile || record.mobile || ''
        }));
        
        setSearchQuery(gstId.toString());
        setSelectedGstInfo(record);
        setShowResults(false);
        
        // Trigger manual validation for auto-filled fields
        validateField('gst_registration_id', gstId);
        if (record.pan) validateField('pan', record.pan);
        if (record.email) validateField('email', record.email);
        if (record.mobile) validateField('mobile', record.mobile);
    };

    const handleClearSearch = () => {
        setSearchQuery('');
        setSearchResults([]);
        setSelectedGstInfo(null);
        setFormData(prev => ({ ...prev, gst_registration_id: '' }));
        setShowResults(false);
    };

    const fetchDesignations = async (gstId) => {
        if (!gstId) return;
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
        if (isOpen && formData.gst_registration_id) {
            fetchDesignations(formData.gst_registration_id);
        } else if (!formData.gst_registration_id) {
            setDesignations([]);
        }
    }, [formData.gst_registration_id, isOpen]);

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
        setSearchQuery('');
        setSearchResults([]);
        setSelectedGstInfo(null);
    }, [isOpen]);

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

            const payload = Object.fromEntries(
                Object.entries(rawPayload).filter(([_, v]) => v !== '' && v !== null)
            );

            await api.post(`/api/v1/gst-people`, payload);
            setSuccess(true);
            setTimeout(() => {
                if (onSuccess) onSuccess();
                if (onClose) onClose();
            }, 1500);
        } catch (err) {
            setError(extractGstPeopleError(err));
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={onClose}>
            <div className="gst-modal-card-v4 app-drawer-panel gst-reg-side-drawer-shell" onClick={e => e.stopPropagation()}>
                {success ? (
                    <div className="gst-modal-success-state">
                        <div className="gst-success-icon-wrapper">
                            <CheckCircle2 size={48} className="gst-success-tick" />
                        </div>
                        <h2 className="modal-title-v4">GST Person Created</h2>
                        <p className="modal-subtitle-v4">The stakeholder has been successfully associated with the GST registration.</p>
                        <button className="gst-btn-primary" onClick={onClose} style={{ marginTop: '24px' }}>
                            Go to Dashboard
                        </button>
                    </div>
                ) : (
                    <>
                        <div className="modal-header-v4">
                            <div className="header-content-v4">
                                <div className="header-icon-box-v4" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#2eb87a' }}>
                                    <User size={20} />
                                </div>
                                <div className="modal-title-box">
                                    <div className="modal-header-texts">
                                        <h2 className="modal-title-v4">
                                            Create GST Person
                                            <span className="modal-header-tag-v4 create">NEW</span>
                                        </h2>
                                        <p className="modal-subtitle-v4">Attach a stakeholder to a GST registration profile</p>
                                    </div>
                                </div>
                            </div>
                            <button className="btn-drawer-close" onClick={onClose}><X size={20} /></button>
                        </div>

                        <form onSubmit={handleSubmit} className="modal-form-v4">
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
                                            <div className="searchable-select-wrapper">
                                                <input 
                                                    type="text" 
                                                    value={searchQuery} 
                                                    onChange={(e) => setSearchQuery(e.target.value)} 
                                                    placeholder="Search ID or GSTIN..." 
                                                    className={`modal-input-v4 ${fieldErrors.gst_registration_id ? 'error' : ''}`}
                                                    onFocus={() => searchQuery && setShowResults(true)}
                                                />
                                                {isSearching ? (
                                                    <div className="input-affix-right">
                                                        <RotateCcw size={14} className="gst-refresh-spin" />
                                                    </div>
                                                ) : searchQuery && (
                                                    <button 
                                                        type="button" 
                                                        className="input-affix-right clear-btn"
                                                        onClick={handleClearSearch}
                                                        style={{ pointerEvents: 'auto', cursor: 'pointer', background: 'none', border: 'none', color: 'var(--text-primary)', padding: '4px' }}
                                                    >
                                                        <X size={14} />
                                                    </button>
                                                )}
                                                
                                                {showResults && (
                                                    <>
                                                        <div className="gst-dropdown-backdrop" onClick={() => setShowResults(false)} />
                                                        <div className="searchable-dropdown">
                                                            {isSearching ? (
                                                                <div className="dropdown-item loading">Searching...</div>
                                                            ) : searchResults.length > 0 ? (
                                                                searchResults.map((res, idx) => {
                                                                    const gstId = res.id || res.gst_registration_id;
                                                                    return (
                                                                        <div key={gstId || idx} className="dropdown-item" onMouseDown={() => handleSelectGst(res)}>
                                                                            <div className="item-main">
                                                                                <span className="item-id">{gstId || 'N/A'}</span>
                                                                                <span className="item-name">{res.business_name || res.legal_name || res.trade_name || 'N/A'}</span>
                                                                            </div>
                                                                            <div className="item-sub">{res.gstin}</div>
                                                                        </div>
                                                                    );
                                                                })
                                                            ) : (
                                                                <div className="dropdown-item no-results">No matches found</div>
                                                            )}
                                                        </div>
                                                    </>
                                                )}
                                            </div>
                                            {fieldErrors.gst_registration_id && <span className="field-error-msg">{fieldErrors.gst_registration_id}</span>}
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Associated GSTIN</label>
                                            <div className="gst-form-value-box">{selectedGstInfo?.gstin || '-'}</div>
                                        </div>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Associated Business</label>
                                            <div className="gst-form-value-box" title={selectedGstInfo?.business_name || selectedGstInfo?.legal_name || selectedGstInfo?.trade_name || ''}>
                                                {selectedGstInfo?.business_name || selectedGstInfo?.legal_name || selectedGstInfo?.trade_name || '-'}
                                            </div>
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

                            <div className="modal-footer-v4">
                                <div className="footer-actions-v4">
                                    <button type="button" className="gst-btn-secondary" onClick={onClose}>
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

const GSTPeopleDetailsModal = ({ isOpen, data, onClose, onUpdated, isAdmin, canEdit: canEditProp, initialEditMode = false }) => {
    const canEdit = canEditProp ?? isAdmin;
    const [item, setItem] = useState(data);
    const [editMode, setEditMode] = useState(initialEditMode);
    const [formData, setFormData] = useState(data || {});
    const [message, setMessage] = useState({ type: '', text: '' });
    const [actionLoading, setActionLoading] = useState('');
    const [confirmAction, setConfirmAction] = useState('');
    const [fieldErrors, setFieldErrors] = useState({});
    const [designations, setDesignations] = useState([]);
    const [fetchingDesignations, setFetchingDesignations] = useState(false);

    const [searchQuery, setSearchQuery] = useState(data?.gst_registration_id?.toString() || '');
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [showResults, setShowResults] = useState(false);
    const [selectedGstInfo, setSelectedGstInfo] = useState(data || null);
    const ignoreSearchRef = React.useRef(false);

    useEffect(() => {
        if (!editMode) return;
        const timer = setTimeout(async () => {
            if (ignoreSearchRef.current) {
                ignoreSearchRef.current = false;
                return;
            }

            if (!searchQuery || searchQuery.length < 1) {
                setSearchResults([]);
                setShowResults(false);
                return;
            }

            setIsSearching(true);
            setShowResults(true);

            try {
                const params = new URLSearchParams();
                if (/^\d+$/.test(searchQuery)) {
                    params.append('gst_registration_id', searchQuery);
                } else {
                    params.append('gstin', searchQuery);
                }
                
                const response = await api.get(`/api/v1/gst-registrations/dynamic_filter?${params.toString()}&limit=5`);
                const result = response.data;
                const items = Array.isArray(result) ? result : (result.data || []);
                setSearchResults(items);
            } catch (err) {
                console.error("GST search failed:", err);
                setSearchResults([]);
            } finally {
                setIsSearching(false);
            }
        }, 500);

        return () => clearTimeout(timer);
    }, [searchQuery, editMode]);

    const handleSelectGst = (record) => {
        const gstId = record.id || record.gst_registration_id;
        if (!record || !gstId) {
            setShowResults(false);
            return;
        }
        ignoreSearchRef.current = true;

        // Auto-fill form fields from selected registration if they are currently empty
        setFormData(prev => ({ 
            ...prev, 
            gst_registration_id: gstId,
            full_name: prev.full_name || record.business_name || record.legal_name || record.trade_name || '',
            pan: prev.pan || record.pan || '',
            email: prev.email || record.email || '',
            mobile: prev.mobile || record.mobile || ''
        }));

        setSearchQuery(gstId.toString());
        setSelectedGstInfo(record);
        setShowResults(false);

        // Trigger manual validation for auto-filled fields
        validateField('gst_registration_id', gstId);
        if (record.pan) validateField('pan', record.pan);
        if (record.email) validateField('email', record.email);
        if (record.mobile) validateField('mobile', record.mobile);
    };

    const handleClearSearch = () => {
        setSearchQuery("");
        setSearchResults([]);
        setSelectedGstInfo(null);
        setFormData(prev => ({ ...prev, gst_registration_id: "" }));
        setShowResults(false);
    };


    const currentItem = item || data;

    const fetchDesignations = async (gstId) => {
        if (!gstId) return;
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
        if (isOpen && currentItem?.gst_registration_id) {
            fetchDesignations(currentItem.gst_registration_id);
        }
    }, [isOpen, currentItem?.gst_registration_id]);

    useEffect(() => {
        if (!isOpen) return;
        setItem(data);
        setFormData(data || {});
        setSearchQuery(data?.gst_registration_id?.toString() || '');
        setSelectedGstInfo(data || null);
        setEditMode(initialEditMode);
        setMessage({ type: '', text: '' });
        setConfirmAction('');
        setFieldErrors({});
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, data, initialEditMode]);

    useEffect(() => {
        if (isOpen && initialEditMode) setEditMode(true);
    }, [isOpen, initialEditMode]);

    const handleCancelEdit = () => {
        handleDrawerCancelEdit({
            initialEditMode,
            onClose,
            setEditMode,
            resetEditState: () => {
                setFormData(item || data || {});
                setMessage({ type: '', text: '' });
                setFieldErrors({});
            },
        });
    };

    const isEditing = editMode || initialEditMode;
    const showEditFooter = isEditing;
    const showViewFooter = !isEditing && canEdit;

    const validateField = (name, value) => {
        let errorMsg = '';
        const trimmedValue = typeof value === 'string' ? value.trim() : value;

        switch (name) {
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
            case 'mobile':
                if (trimmedValue) {
                    const phoneRegex = /^\d{10}$/;
                    if (!phoneRegex.test(trimmedValue)) errorMsg = 'Mobile must be 10 digits';
                }
                break;
            case 'email':
                if (trimmedValue) {
                    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                    if (!emailRegex.test(trimmedValue)) errorMsg = 'Invalid email format';
                }
                break;
            default:
                break;
        }

        setFieldErrors(prev => ({ ...prev, [name]: errorMsg }));
        return !errorMsg;
    };

    const validateForm = () => {
        const fieldsToValidate = ['full_name', 'designation', 'pan', 'aadhaar', 'mobile', 'email'];
        let isValid = true;
        fieldsToValidate.forEach(field => {
            if (!validateField(field, formData[field])) {
                isValid = false;
            }
        });
        return isValid;
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        const val = type === 'checkbox' ? checked : value;
        setFormData(prev => ({ ...prev, [name]: val }));
        if (type !== 'checkbox') {
            validateField(name, val);
        }
    };

    const handleSave = async () => {
        setMessage({ type: '', text: '' });
        if (!validateForm()) {
            setMessage({ type: 'error', text: 'Please correct the highlighted fields.' });
            return;
        }
        setActionLoading('save');
        try {
            const target = item || data;
            if (!target?.person_id) {
                setMessage({ type: 'error', text: 'Person ID is missing. Please reopen the details.' });
                setActionLoading('');
                return;
            }
            const payload = {
                full_name: formData.full_name,
                designation: formData.designation,
                pan: formData.pan,
                aadhaar: formData.aadhaar,
                mobile: formData.mobile,
                email: formData.email,
                is_primary_customer: formData.is_primary_customer,
                is_active: formData.is_active,
            };
            await api.post(`/api/v1/gst-people/${target.person_id}/edit`, payload);

            setMessage({ type: 'success', text: 'Updated successfully!' });
            if (onUpdated) onUpdated();
            if (shouldCloseDrawerAfterSave(initialEditMode)) {
                onClose();
                return;
            }
            setEditMode(false);
            const updatedItem = { ...item, ...formData };
            setItem(updatedItem);
            setFormData(updatedItem);
        } catch (err) {
            setMessage({ type: 'error', text: extractGstPeopleError(err) });
        } finally {
            setActionLoading('');
        }
    };

    const handleDelete = async () => {
        setMessage({ type: '', text: '' });
        setConfirmAction('');
        setActionLoading('delete');
        try {
            const target = item || data;
            if (!target?.person_id) {
                setMessage({ type: 'error', text: 'Person ID is missing. Please reopen the details.' });
                setActionLoading('');
                return;
            }
            await api.delete(`/api/v1/gst-people/${target.person_id}/soft_delete`);
            setMessage({ type: 'success', text: 'Deleted successfully!' });
            setTimeout(() => {
                if (onUpdated) onUpdated();
                if (onClose) onClose();
            }, 1200);
        } catch (err) {
            setMessage({ type: 'error', text: extractGstPeopleError(err) });
        } finally {
            setActionLoading('');
        }
    };

    const handleActivate = async () => {
        setMessage({ type: '', text: '' });
        setConfirmAction('');
        setActionLoading('activate');
        try {
            const target = item || data;
            if (!target?.person_id) {
                setMessage({ type: 'error', text: 'Person ID is missing. Please reopen the details.' });
                setActionLoading('');
                return;
            }
            const res = await api.post(`/api/v1/gst-people/${target.person_id}/activate`);
            const updatedData = res.data;
            setMessage({ type: 'success', text: 'Activated successfully!' });
            const finalData = { ...updatedData, is_active: true };
            setItem(finalData);
            setFormData(finalData);
            if (onUpdated) onUpdated();
        } catch (err) {
            setMessage({ type: 'error', text: extractGstPeopleError(err) });
        } finally {
            setActionLoading('');
        }
    };

    if (!isOpen) return null;

    const drawerPanel = (
        <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={onClose}>
            <div className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
                <div className="drawer-header gst-reg-details-header">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4" style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' }}>
                            <User size={20} />
                        </div>
                        <div className="modal-title-box">
                            <div className="modal-header-texts">
                                <h2 className="modal-title-v4">
                                    {currentItem?.full_name || 'GST Person'}
                                    {isEditing ? (
                                        <span className="modal-header-tag-v4 edit">EDIT</span>
                                    ) : (
                                        <span className="modal-header-tag-v4 view">VIEW</span>
                                    )}
                                </h2>
                                <p className="modal-subtitle-v4">Manage stakeholder profile • ID: {currentItem?.person_id || '-'}</p>
                            </div>
                        </div>
                    </div>
                    <button type="button" className="btn-drawer-close" onClick={onClose} aria-label="Close"><X size={20} /></button>
                </div>

                <div className="drawer-content gst-reg-details-scroll gst-reg-details-form">
                    {message.text && (
                        <div className={`gst-message-banner ${message.type === 'success' ? 'success' : 'error'}`}>
                            {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                            <span className="gst-message-banner-text">{message.text}</span>
                        </div>
                    )}

                        {/* SECTION 1: IDENTITY & CORE DETAILS */}
                        <div className="form-section-group">
                            <h3 className="section-title">1. Identity & Core Details</h3>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Full Name</label>
                                    {isEditing ? (
                                        <input 
                                            name="full_name" 
                                            value={formData.full_name || ''} 
                                            onChange={handleChange} 
                                            className={`modal-input-v4 ${fieldErrors.full_name ? 'error' : ''}`} 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.full_name || '-'}</div>
                                    )}
                                    {isEditing && fieldErrors.full_name && <span className="field-error-msg">{fieldErrors.full_name}</span>}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Designation</label>
                                    {isEditing ? (
                                        <FormCustomSelect
                                            name="designation"
                                            value={formData.designation || ''}
                                            onChange={handleChange}
                                            options={optionsFromConfig(
                                                designations,
                                                fetchingDesignations ? 'Loading...' : 'Select Designation'
                                            )}
                                            placeholder={fetchingDesignations ? 'Loading...' : 'Select Designation'}
                                            ariaLabel="Designation"
                                            disabled={fetchingDesignations}
                                            error={Boolean(fieldErrors.designation)}
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.designation || '-'}</div>
                                    )}
                                    {isEditing && fieldErrors.designation && <span className="field-error-msg">{fieldErrors.designation}</span>}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">PAN</label>
                                    {isEditing ? (
                                        <input 
                                            name="pan" 
                                            value={formData.pan || ''} 
                                            onChange={handleChange} 
                                            maxLength="10" 
                                            placeholder="ABCDE1234F"
                                            className={`modal-input-v4 ${fieldErrors.pan ? 'error' : ''}`} 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.pan || '-'}</div>
                                    )}
                                    {isEditing && fieldErrors.pan && <span className="field-error-msg">{fieldErrors.pan}</span>}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Aadhaar</label>
                                    {isEditing ? (
                                        <input 
                                            name="aadhaar" 
                                            value={formData.aadhaar || ''} 
                                            onChange={handleChange} 
                                            maxLength="12" 
                                            placeholder="12-digit number"
                                            className={`modal-input-v4 ${fieldErrors.aadhaar ? 'error' : ''}`} 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.aadhaar || '-'}</div>
                                    )}
                                    {isEditing && fieldErrors.aadhaar && <span className="field-error-msg">{fieldErrors.aadhaar}</span>}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">GST Registration ID</label>
                                    {isEditing ? (
                                        <div className="searchable-select-wrapper">
                                            <input 
                                                type="text" 
                                                value={searchQuery} 
                                                onChange={(e) => setSearchQuery(e.target.value)} 
                                                placeholder="Search ID or GSTIN..." 
                                                className="modal-input-v4"
                                                onFocus={() => searchQuery && setShowResults(true)}
                                            />
                                            {isSearching ? (
                                                <div className="input-affix-right">
                                                    <RotateCcw size={14} className="gst-refresh-spin" />
                                                </div>
                                            ) : searchQuery && (
                                                <button 
                                                    type="button" 
                                                    className="input-affix-right clear-btn"
                                                    onClick={handleClearSearch}
                                                    style={{ pointerEvents: 'auto', cursor: 'pointer', background: 'none', border: 'none', color: 'var(--text-primary)', padding: '4px' }}
                                                >
                                                    <X size={14} />
                                                </button>
                                            )}
                                            
                                            {showResults && (
                                                <>
                                                    <div className="gst-dropdown-backdrop" onClick={() => setShowResults(false)} />
                                                    <div className="searchable-dropdown">
                                                        {isSearching ? (
                                                            <div className="dropdown-item loading">Searching...</div>
                                                        ) : searchResults.length > 0 ? (
                                                            searchResults.map((res, idx) => {
                                                                const gstId = res.id || res.gst_registration_id;
                                                                return (
                                                                    <div key={gstId || idx} className="dropdown-item" onMouseDown={() => handleSelectGst(res)}>
                                                                        <div className="item-main">
                                                                            <span className="item-id">{gstId || 'N/A'}</span>
                                                                            <span className="item-name">{res.business_name || res.legal_name || res.trade_name || 'N/A'}</span>
                                                                        </div>
                                                                        <div className="item-sub">{res.gstin}</div>
                                                                    </div>
                                                                );
                                                            })
                                                        ) : (
                                                            <div className="dropdown-item no-results">No matches found</div>
                                                        )}
                                                    </div>
                                                </>
                                            )}
                                        </div>
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.gst_registration_id || '-'}</div>
                                    )}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Associated GSTIN</label>
                                    <div className="gst-form-value-box">{selectedGstInfo?.gstin || currentItem.gstin || '-'}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Associated Business</label>
                                    <div className="gst-form-value-box" title={selectedGstInfo?.business_name || selectedGstInfo?.legal_name || selectedGstInfo?.trade_name || currentItem.business_name || ''}>
                                        {selectedGstInfo?.business_name || selectedGstInfo?.legal_name || selectedGstInfo?.trade_name || currentItem.business_name || '-'}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* SECTION 2: CONTACT & STATUS */}
                        <div className="form-section-group" style={{ marginTop: '32px' }}>
                            <h3 className="section-title">2. Contact & Status</h3>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Mobile</label>
                                    {isEditing ? (
                                        <input 
                                            name="mobile" 
                                            value={formData.mobile || ''} 
                                            onChange={handleChange} 
                                            className={`modal-input-v4 ${fieldErrors.mobile ? 'error' : ''}`} 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.mobile || '-'}</div>
                                    )}
                                    {isEditing && fieldErrors.mobile && <span className="field-error-msg">{fieldErrors.mobile}</span>}
                                </div>
                                <div className="form-group-v4" style={{ gridColumn: 'span 2' }}>
                                    <label className="modal-label-caps">Email</label>
                                    {isEditing ? (
                                        <input 
                                            name="email" 
                                            value={formData.email || ''} 
                                            onChange={handleChange} 
                                            className={`modal-input-v4 ${fieldErrors.email ? 'error' : ''}`} 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{currentItem.email || '-'}</div>
                                    )}
                                    {isEditing && fieldErrors.email && <span className="field-error-msg">{fieldErrors.email}</span>}
                                </div>
                            </div>

                            <div className="gst-checkbox-row-v4" style={{ marginTop: '20px', display: 'flex', gap: '24px' }}>
                                <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-primary)' }}>
                                    <input 
                                        type="checkbox" 
                                        name="is_primary_customer" 
                                        checked={!!(isEditing ? formData.is_primary_customer : currentItem.is_primary_customer)} 
                                        onChange={isEditing ? handleChange : undefined} 
                                        disabled={!isEditing}
                                        className="modal-checkbox-v4" 
                                    />
                                    <span>Primary Customer</span>
                                </label>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--text-primary)' }}>
                                    <span style={{ color: 'var(--text-primary)', textTransform: 'uppercase', fontSize: '10px', fontWeight: '700' }}>Active Status:</span>
                                    <span style={{ color: currentItem.is_active ? '#2eb87a' : '#f44336', fontWeight: '600' }}>
                                        {currentItem.is_active ? 'ACTIVE' : 'INACTIVE'}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* SECTION 3: SYSTEM METADATA */}
                        <div className="form-section-group" style={{ marginTop: '32px' }}>
                            <h3 className="section-title">3. System Metadata</h3>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Customer ID</label>
                                    <div className="gst-form-value-box">{currentItem.customer_id || '-'}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Ownership</label>
                                    <div className="gst-form-value-box">{currentItem.ownership_category || '-'}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Created At</label>
                                    <div className="gst-form-value-box">{formatDateTime(currentItem.created_at)}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Updated At</label>
                                    <div className="gst-form-value-box">{formatDateTime(currentItem.updated_at)}</div>
                                </div>
                            </div>
                        </div>
                </div>

                <AppDrawerFooter>
                    {showEditFooter ? (
                        <>
                            {isAdmin && currentItem?.is_active !== false && (
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
                    ) : (
                        showViewFooter && (
                            currentItem.is_active ? (
                                <>
                                    <button type="button" className="glow-green" onClick={() => setEditMode(true)} disabled={actionLoading !== ''}>
                                        Edit Details
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
                                    <button type="button" className="glow-green" onClick={() => setConfirmAction('activate')} disabled={actionLoading !== ''}>
                                        Activate
                                    </button>
                                ) : null
                            )
                        )
                    )}
                </AppDrawerFooter>

                {confirmAction && (
                    <div className="gst-confirm-overlay">
                        <div className="gst-confirm-content">
                            <div className="gst-confirm-icon">
                                <AlertCircle size={32} color={confirmAction === 'delete' ? '#f44336' : '#2eb87a'} />
                            </div>
                            <h2>{confirmAction === 'delete' ? 'Confirm Delete' : 'Confirm Activation'}</h2>
                            <p>
                                {confirmAction === 'delete'
                                    ? 'Are you sure you want to delete this GST person?'
                                    : 'Are you sure you want to activate this GST person?'}
                            </p>
                            <div className="gst-confirm-actions">
                                <button className="gst-btn-secondary" onClick={() => setConfirmAction('')} disabled={actionLoading !== ''}>
                                    Cancel
                                </button>
                                {confirmAction === 'delete' ? (
                                    <button className="gst-btn-danger" onClick={handleDelete} disabled={actionLoading !== ''}>
                                        {actionLoading === 'delete' ? <RotateCcw size={16} className="gst-refresh-spin" /> : null}
                                        {actionLoading === 'delete' ? 'Deleting...' : 'Confirm'}
                                    </button>
                                ) : (
                                    <button className="gst-btn-success" onClick={handleActivate} disabled={actionLoading !== ''}>
                                        {actionLoading === 'activate' ? <RotateCcw size={16} className="gst-refresh-spin" /> : null}
                                        {actionLoading === 'activate' ? 'Activating...' : 'Confirm'}
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


export const GSTPersonDetails = ({ onLogout }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const data = location.state?.data;

    if (!data) return <div className="gst-people-no-data">No data provided. Please navigate from the dashboard.</div>;

    const label = 'GST Person';
    const [item, setItem] = useState(data);
    const [editMode, setEditMode] = useState(false);
    const [formData, setFormData] = useState(data);
    const [message, setMessage] = useState({ type: '', text: '' });
    const [subLoading, setSubLoading] = useState(false);
    const [isAdmin, setIsAdmin] = useState(false);
    const [designations, setDesignations] = useState([]);
    const [fetchingDesignations, setFetchingDesignations] = useState(false);

    const fetchDesignations = async (gstId) => {
        if (!gstId) return;
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
        if (editMode && item?.gst_registration_id) {
            fetchDesignations(item.gst_registration_id);
        }
    }, [editMode, item?.gst_registration_id]);

    useEffect(() => {
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
    }, [location.state?.isAdmin]);

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
    };

    const handleSave = async () => {
        setMessage({ type: '', text: '' });
        setSubLoading(true);
        try {
            // Sanitize payload to only include editable fields expected by the backend
            const payload = {
                full_name: formData.full_name,
                designation: formData.designation,
                pan: formData.pan,
                aadhaar: formData.aadhaar,
                mobile: formData.mobile,
                email: formData.email,
                is_primary_customer: formData.is_primary_customer,
                is_active: formData.is_active
            };
            await api.post(`/api/v1/gst-people/${item.person_id}/edit`, payload);

            setMessage({ type: 'success', text: 'Updated successfully!' });
            setEditMode(false);
            setItem(prev => ({ ...prev, ...formData }));
        } catch (err) { setMessage({ type: 'error', text: err.message }); }
        finally { setSubLoading(false); }
    };

    const handleDelete = async () => {
        if (!window.confirm(`Are you sure you want to delete this ${label}?`)) return;
        setMessage({ type: '', text: '' });
        setSubLoading(true);
        try {
            await api.delete(`/api/v1/gst-people/${item.person_id}/soft_delete`);

            setMessage({ type: 'success', text: 'Deleted successfully! Redirecting...' });
            setTimeout(() => {
                navigate('/dashboard?tab=gst&sub=people');
            }, 1500);
        } catch (err) { setMessage({ type: 'error', text: err.message }); }
        finally { setSubLoading(false); }
    };

    const handleActivate = async () => {
        if (!window.confirm(`Are you sure you want to activate this ${label}?`)) return;
        setMessage({ type: '', text: '' });
        setSubLoading(true);
        try {
            const res = await api.post(`/api/v1/gst-people/${item.person_id}/activate`);
            const updatedData = res.data;
            setMessage({ type: 'success', text: 'Activated successfully!' });
            const finalData = { ...updatedData, is_active: true };
            setItem(finalData);
            setFormData(finalData);
        } catch (err) { setMessage({ type: 'error', text: err.message }); }
        finally { setSubLoading(false); }
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try { return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }); } catch { return dtStr; }
    };

    return (
        <div className="employee-details-page">
            <div className="bg-orb orb-1" />
            <div className="bg-orb orb-2" />
            <div className="grid-overlay" />

            <div className="gst-modal-card-v4 wide-modal standalone-v4-card" style={{ margin: '40px auto', maxWidth: '1000px', position: 'relative', zIndex: 10 }}>
                <div className="modal-header-v4">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4" style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' }}>
                            <User size={20} />
                        </div>
                        <div className="modal-title-box">
                            <div className="modal-header-texts">
                                <h2 className="modal-title-v4">{item?.full_name || 'GST Person'}</h2>
                                <p className="modal-subtitle-v4">Manage stakeholder profile • ID: {item?.person_id || '-'}</p>
                            </div>
                        </div>
                    </div>
                    <button className="btn-drawer-close" onClick={() => navigate('/dashboard?tab=gst&sub=people')}><X size={20} /></button>
                </div>

                <div className="modal-form-v4">
                    {message.text && (
                        <div className={`gst-message-banner ${message.type === 'success' ? 'success' : 'error'}`} style={{ margin: '0 32px 24px' }}>
                            {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                            <span className="gst-message-banner-text">{message.text}</span>
                        </div>
                    )}

                    <div className="form-scroll-container">
                        {/* SECTION 1: IDENTITY & CORE DETAILS */}
                        <div className="form-section-group">
                            <h3 className="section-title">1. Identity & Core Details</h3>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Full Name</label>
                                    {isEditing ? (
                                        <input 
                                            name="full_name" 
                                            value={formData.full_name || ''} 
                                            onChange={handleChange} 
                                            className="modal-input-v4" 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{item.full_name || '-'}</div>
                                    )}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Designation</label>
                                    {editMode ? (
                                        <FormCustomSelect
                                            name="designation"
                                            value={formData.designation || ''}
                                            onChange={handleChange}
                                            options={optionsFromConfig(
                                                designations,
                                                fetchingDesignations ? 'Loading...' : 'Select Designation'
                                            )}
                                            placeholder={fetchingDesignations ? 'Loading...' : 'Select Designation'}
                                            ariaLabel="Designation"
                                            disabled={fetchingDesignations}
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{item.designation || '-'}</div>
                                    )}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">PAN</label>
                                    {isEditing ? (
                                        <input 
                                            name="pan" 
                                            value={formData.pan || ''} 
                                            onChange={handleChange} 
                                            maxLength="10" 
                                            placeholder="ABCDE1234F"
                                            className="modal-input-v4" 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{item.pan || '-'}</div>
                                    )}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Aadhaar</label>
                                    {isEditing ? (
                                        <input 
                                            name="aadhaar" 
                                            value={formData.aadhaar || ''} 
                                            onChange={handleChange} 
                                            maxLength="12" 
                                            placeholder="12-digit number"
                                            className="modal-input-v4" 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{item.aadhaar || '-'}</div>
                                    )}
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">GST Registration ID</label>
                                    <div className="gst-form-value-box">{item.gst_registration_id || '-'}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">GSTIN</label>
                                    <div className="gst-form-value-box">{item.gstin || '-'}</div>
                                </div>
                            </div>
                        </div>

                        {/* SECTION 2: CONTACT & STATUS */}
                        <div className="form-section-group" style={{ marginTop: '32px' }}>
                            <h3 className="section-title">2. Contact & Status</h3>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Mobile</label>
                                    {isEditing ? (
                                        <input 
                                            name="mobile" 
                                            value={formData.mobile || ''} 
                                            onChange={handleChange} 
                                            className="modal-input-v4" 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{item.mobile || '-'}</div>
                                    )}
                                </div>
                                <div className="form-group-v4" style={{ gridColumn: 'span 2' }}>
                                    <label className="modal-label-caps">Email</label>
                                    {isEditing ? (
                                        <input 
                                            name="email" 
                                            value={formData.email || ''} 
                                            onChange={handleChange} 
                                            className="modal-input-v4" 
                                        />
                                    ) : (
                                        <div className="gst-form-value-box">{item.email || '-'}</div>
                                    )}
                                </div>
                            </div>

                            <div className="gst-checkbox-row-v4" style={{ marginTop: '20px', display: 'flex', gap: '24px' }}>
                                <label className="custom-checkbox-v4-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-primary)' }}>
                                    <input 
                                        type="checkbox" 
                                        name="is_primary_customer" 
                                        checked={!!(editMode ? formData.is_primary_customer : item.is_primary_customer)} 
                                        onChange={editMode ? handleChange : undefined} 
                                        disabled={!editMode}
                                        className="modal-checkbox-v4" 
                                    />
                                    <span>Primary Customer</span>
                                </label>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--text-primary)' }}>
                                    <span style={{ color: 'var(--text-primary)', textTransform: 'uppercase', fontSize: '10px', fontWeight: '700' }}>Active Status:</span>
                                    <span style={{ color: item.is_active ? '#2eb87a' : '#f44336', fontWeight: '600' }}>
                                        {item.is_active ? 'ACTIVE' : 'INACTIVE'}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* SECTION 3: SYSTEM METADATA */}
                        <div className="form-section-group" style={{ marginTop: '32px' }}>
                            <h3 className="section-title">3. System Metadata</h3>
                            <div className="form-grid-3">
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Customer ID</label>
                                    <div className="gst-form-value-box">{item.customer_id || '-'}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Ownership Category</label>
                                    <div className="gst-form-value-box">{item.ownership_category || '-'}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Created At</label>
                                    <div className="gst-form-value-box">{formatDateTime(item.created_at)}</div>
                                </div>
                                <div className="form-group-v4">
                                    <label className="modal-label-caps">Updated At</label>
                                    <div className="gst-form-value-box">{formatDateTime(item.updated_at)}</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="modal-footer-v4" style={{ padding: '24px 32px' }}>
                    <div className="footer-actions-v4">
                        {editMode ? (
                            <>
                                <button onClick={() => { setEditMode(false); setFormData(item); setMessage({ type: '', text: '' }); }} className="gst-btn-secondary" disabled={subLoading}>
                                    Cancel
                                </button>
                                <button onClick={handleSave} className="gst-btn-primary" disabled={subLoading}>
                                    {subLoading && <RotateCcw size={16} className="gst-refresh-spin" />}
                                    {subLoading ? 'Saving...' : 'Save Changes'}
                                </button>
                            </>
                        ) : (
                            isAdmin && (
                                item.is_active ? (
                                    <>
                                        <button onClick={() => setEditMode(true)} className="gst-btn-primary" disabled={subLoading}>Edit Details</button>
                                        <button onClick={handleDelete} className="gst-btn-danger" disabled={subLoading}>
                                            {subLoading && <RotateCcw size={16} className="gst-refresh-spin" />}
                                            {subLoading ? 'Deleting...' : 'Delete'}
                                        </button>
                                    </>
                                ) : (
                                    <button onClick={handleActivate} className="gst-btn-primary" style={{ background: '#2eb87a' }} disabled={subLoading}>
                                        {subLoading && <RotateCcw size={16} className="gst-refresh-spin" />}
                                        {subLoading ? 'Activating...' : 'Activate'}
                                    </button>
                                )
                            )
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
