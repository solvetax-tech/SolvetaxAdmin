/**
 * @file gst_documents.jsx
 * @description Renders the GST Documents tracking table and detailed view.
 * Allows users to filter, inspect, and manage compliance files attached to GST records.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useLocation } from 'react-router-dom';
import '../Dashboard.css';
import '../employees/EmployeeDetailsModal.css';
import api from '../../utils/api';
import { canManageRmOpRecords } from '../../utils/rmOpAssignmentFields';
import LoadingOverlay from '../common/LoadingOverlay';
import UploadDocuments from './UploadDocuments';
import Pagination from '../common/Pagination';
import '../common/Filters.css';
import FilterDateInput from '../common/FilterDateInput';
import './gst_registration.css';
import './GSTRegistrationSignup.css';
import './gst_documents.css';
import './UploadDocuments.css';
import { Filter, X, RotateCcw, Plus, UploadCloud, Download, FileDown, AlertCircle, CheckCircle2, FileText, Link as LinkIcon, File as FileIcon, Upload, Trash2, Hash, Eye, Pencil, ExternalLink, Edit3 } from 'lucide-react';
import GSTDocumentsViewPanel from './GSTDocumentsViewPanel';
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

const BASE_URL = import.meta.env.VITE_API_URL;

const formatDateTime = (dtStr) => {
    if (!dtStr) return '-';
    try {
        return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
    } catch {
        return dtStr;
    }
};

export const GSTDocuments = ({ handleLogout, isAdmin, profileData, onRenderToolbar }) => {
    const canEdit = canManageRmOpRecords(profileData, isAdmin);
    const navigate = useNavigate();
    const location = useLocation();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [showFilterModal, setShowFilterModal] = useState(false);
    const [showUploadModal, setShowUploadModal] = useState(false);
    const [uploadMode, setUploadMode] = useState('upload');
    const rowsPerPage = 20;
    const [showDetailsModal, setShowDetailsModal] = useState(false);
    const [selectedDocument, setSelectedDocument] = useState(null);
    const [autoOpenDocId, setAutoOpenDocId] = useState(null);
    const [viewPanelOpen, setViewPanelOpen] = useState(false);
    const [viewDocId, setViewDocId] = useState(null);
    const [editModalMode, setEditModalMode] = useState(false);

    const [filterInputs, setFilterInputs] = useState({
        gstin: '', document_type: '', mobile: '',
        person_id: '', verified: '',
        is_active: '', include_inactive: true,
        from_date: '', to_date: ''
    });

    const [allDocTypes, setAllDocTypes] = useState([]);
    const [fetchingDocTypes, setFetchingDocTypes] = useState(false);

    const [appliedFilters, setAppliedFilters] = useState({
        gstin: '', document_type: '', mobile: '',
        person_id: '', verified: '',
        is_active: '', include_inactive: true,
        from_date: '', to_date: ''
    });

    const openDocumentView = (item, e) => {
        e?.stopPropagation();
        setViewDocId(item.document_id);
        setViewPanelOpen(true);
    };

    const openDocumentEdit = (item, e) => {
        e?.stopPropagation();
        setSelectedDocument(item);
        setEditModalMode(true);
        setShowDetailsModal(true);
    };

    const handleRowClick = (item) => {
        openDocumentView(item);
    };

    const closeDetailsModal = () => {
        setShowDetailsModal(false);
        setSelectedDocument(null);
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
        setFilterInputs({
            gstin: '', document_type: '', mobile: '',
            person_id: '', verified: '',
            is_active: '', include_inactive: true,
            from_date: '', to_date: ''
        });
        setAppliedFilters({
            gstin: '', document_type: '', mobile: '',
            person_id: '', verified: '',
            is_active: '', include_inactive: true,
            from_date: '', to_date: ''
        });
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
            gstin: 'GSTIN', document_type: 'Doc Type', mobile: 'Mobile',
            person_id: 'Person ID', verified: 'Verified',
            is_active: 'Status', from_date: 'From', to_date: 'To'
        };

        return Object.entries(appliedFilters)
            .filter(([key, value]) => {
                if (key === 'include_inactive') return false;
                return value !== '' && value !== null;
            })
            .map(([key, value]) => {
                let displayValue = value;
                if (key === 'document_type') {
                    const match = allDocTypes.find(d => (d.value || d.display_name) === value);
                    if (match) displayValue = match.display_name;
                }
                if (key === 'verified' || key === 'is_active') {
                    displayValue = value === 'true' ? 'Yes' : 'No';
                }

                return (
                    <div key={key} className="filter-chip">
                        <span className="filter-chip-label">{labels[key] || key}:</span>
                        <span className="filter-chip-value">{displayValue}</span>
                        <button className="btn-remove-chip" onClick={() => removeFilter(key)}>
                            <X size={12} />
                        </button>
                    </div>
                );
            });
    };

    const fetchGstData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            Object.entries(appliedFilters).forEach(([key, value]) => {
                if (value !== '' && value !== null && value !== undefined) {
                    const paramValue = typeof value === 'boolean' ? value.toString() : value;
                    params.append(key, paramValue);
                }
            });
            params.append('offset', (currentPage - 1) * rowsPerPage);
            params.append('limit', rowsPerPage);

            const response = await api.get(`/api/v1/gst-documents/dynamic_filter?${params.toString()}`);

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

    const GSTDocumentsTableSkeleton = () => (
        <div className="filings-ledger-body">
            {[...Array(12)].map((_, i) => (
                <div key={i} className="filings-ledger-row gst-docs-grid-template">
                    {[...Array(10)].map((_, j) => (
                        <div key={j} className="filings-ledger-cell">
                            <div className="filings-ledger-skeleton-bar" />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );

    const handleView = async (blobUrl) => {
        if (!blobUrl) return;
        try {
            const response = await api.get(`/api/v1/gst-blob/view?blob_url=${encodeURIComponent(blobUrl)}`);
            const secureUrl = response.data?.view_url;
            if (secureUrl) {
                window.open(secureUrl, '_blank');
            }
        } catch (err) {
            alert("Failed to generate secure view link.");
        }
    };

    const handleDownload = async (blobUrl, filename = 'document') => {
        if (!blobUrl) return;
        try {
            const response = await api.get(`/api/v1/gst-blob/download?blob_url=${encodeURIComponent(blobUrl)}`);
            if (response.data?.download_url) {
                const link = document.createElement('a');
                link.href = response.data.download_url;
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            }
        } catch (err) {
            alert("Failed to generate secure download link.");
        }
    };

    const fetchDocTypes = useCallback(async () => {
        setFetchingDocTypes(true);
        try {
            // Attempt primary config endpoint
            const res = await api.get('/api/v1/gst-registration/config/document_type');
            let docs = res.data || [];

            // Fallback if empty, using the master document-config
            if (docs.length === 0) {
                const configRes = await api.get('/api/v1/document-config/document-config');
                const configData = configRes.data?.data || configRes.data || [];

                // Map to consistent { value, display_name } format
                // Preferred sequence: value -> document_type -> display_name
                const mapped = configData.map(d => ({
                    display_name: d.display_name,
                    value: d.value || d.document_type || d.display_name
                })).filter(d => d.display_name);

                // De-duplicate by value to avoid redundant options
                const seen = new Set();
                docs = mapped.filter(el => {
                    const unique = !seen.has(el.value);
                    seen.add(el.value);
                    return unique;
                });
            }

            setAllDocTypes(docs);
        } catch (err) {
            console.error("Error fetching doc types:", err);
            setAllDocTypes([]);
        } finally {
            setFetchingDocTypes(false);
        }
    }, []);

    useEffect(() => {
        fetchGstData();
    }, [fetchGstData]);

    useEffect(() => {
        fetchDocTypes();
    }, [fetchDocTypes]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const gstin = params.get('gstin');
        const personId = params.get('person_id');
        if (gstin) {
            setFilterInputs(prev => ({ ...prev, gstin }));
            setAppliedFilters(prev => ({ ...prev, gstin }));
            setCurrentPage(1);
        }
        if (personId) {
            setFilterInputs(prev => ({ ...prev, person_id: personId }));
            setAppliedFilters(prev => ({ ...prev, person_id: personId }));
            setCurrentPage(1);
        }
    }, [location.search]);


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
                <label>Doc Type</label>
                <FormCustomSelect
                    name="document_type"
                    value={filterInputs.document_type}
                    onChange={handleFilterChange}
                    options={optionsFromPairs([
                        { value: '', label: 'All Types' },
                        ...allDocTypes.map((type) => ({
                            value: type.value || type.display_name,
                            label: type.display_name,
                        })),
                    ])}
                    placeholder="All Types"
                    ariaLabel="Document type"
                    disabled={fetchingDocTypes}
                />
            </div>
            <div className="filter-field">
                <label>Verified</label>
                <FormCustomSelect
                    name="verified"
                    value={filterInputs.verified}
                    onChange={handleFilterChange}
                    options={optionsFromPairs([
                        { value: '', label: 'All' },
                        { value: 'true', label: 'Yes' },
                        { value: 'false', label: 'No' },
                    ])}
                    placeholder="All"
                    ariaLabel="Verified"
                />
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
                <label>Created From</label>
                <FilterDateInput name="from_date" value={filterInputs.from_date} onChange={handleFilterChange} ariaLabel="From date" />
            </div>
            <div className="filter-field">
                <label>Created To</label>
                <FilterDateInput name="to_date" value={filterInputs.to_date} onChange={handleFilterChange} ariaLabel="To date" />
            </div>
            {renderStatusFilter(filterInputs.is_active, handleFilterChange)}
            <div className="filter-field" style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                <input type="checkbox" name="include_inactive" checked={filterInputs.include_inactive} onChange={(e) => setFilterInputs(p => ({ ...p, include_inactive: e.target.checked }))} style={{ width: 'auto' }} />
                <label style={{ cursor: 'pointer', textTransform: 'none' }}>Include Inactive</label>
            </div>
        </div>
    );

    const hasActiveDocsFilters = Object.entries(appliedFilters).some(([key, value]) => {
        if (key === 'include_inactive') return false;
        return value !== '' && value !== null;
    });

    const docsTopActions = (
        <>
            <button type="button" className="btn-filter-trigger" onClick={() => setShowFilterModal(true)}>
                <Filter size={13} /> Filters
            </button>
            {hasActiveDocsFilters && (
                <button type="button" className="btn-clear-v2" onClick={clearFilters}>
                    <RotateCcw size={14} /> Reset Filters
                </button>
            )}
            {canEdit && (
                <button
                    type="button"
                    className="btn-primary-action"
                    onClick={() => {
                        setUploadMode('upload');
                        setShowUploadModal(true);
                    }}
                >
                    <UploadCloud size={13} />
                    <span>Upload Document</span>
                </button>
            )}
        </>
    );

    useEffect(() => {
        if (!onRenderToolbar) return undefined;
        onRenderToolbar(docsTopActions);
        return () => onRenderToolbar(null);
    }, [onRenderToolbar, hasActiveDocsFilters, canEdit, showFilterModal]);

    return (
        <div className="gst-registration-container">
            {hasActiveDocsFilters && (
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
                            <h2>Filter GST Documents</h2>
                            <button className="btn-drawer-close" onClick={() => setShowFilterModal(false)}><X size={20} /></button>
                        </div>
                        
                        <div className="drawer-content">
                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Core Identifiers</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>GSTIN</label>
                                        <input name="gstin" value={filterInputs.gstin} onChange={handleFilterChange} placeholder="GSTIN..." />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Person ID</label>
                                        <input type="number" name="person_id" value={filterInputs.person_id} onChange={handleFilterChange} placeholder="ID..." />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border-subtle)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Document Metadata</h4>
                                <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                    <label>Document Type</label>
                                    <FormCustomSelect
                                        name="document_type"
                                        value={filterInputs.document_type}
                                        onChange={handleFilterChange}
                                        options={optionsFromPairs([
                                            { value: '', label: 'All Document Types' },
                                            ...allDocTypes.map((type) => ({
                                                value: type.value || type.display_name,
                                                label: type.display_name,
                                            })),
                                        ])}
                                        placeholder="All Document Types"
                                        ariaLabel="Document type"
                                        disabled={fetchingDocTypes}
                                    />
                                </div>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Verified Status</label>
                                        <FormCustomSelect
                                            name="verified"
                                            value={filterInputs.verified}
                                            onChange={handleFilterChange}
                                            options={optionsFromPairs([
                                                { value: '', label: 'Any Status' },
                                                { value: 'true', label: 'Verified Only' },
                                                { value: 'false', label: 'Pending Only' },
                                            ])}
                                            placeholder="Any Status"
                                            ariaLabel="Verified status"
                                        />
                                    </div>
                                    <div className="filter-group-v4">
                                        <label>Contact Mobile</label>
                                        <input name="mobile" value={filterInputs.mobile} onChange={handleFilterChange} placeholder="Mobile..." />
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border-subtle)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>System Context</h4>
                                <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '12px' }}>
                                    <div className="filter-group-v4">
                                        <label>Record State</label>
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
                                            ariaLabel="Record state"
                                        />
                                    </div>
                                    <div className="filter-group-v4" style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8px', height: '100%' }}>
                                        <input 
                                            type="checkbox" 
                                            name="include_inactive" 
                                            checked={filterInputs.include_inactive} 
                                            onChange={(e) => setFilterInputs(p => ({ ...p, include_inactive: e.target.checked }))} 
                                            style={{ width: 'auto' }} 
                                        />
                                        <label style={{ cursor: 'pointer', textTransform: 'none', opacity: 1, fontSize: '11px', color: 'var(--text-primary)', marginTop: '2px' }}>Show History</label>
                                    </div>
                                </div>
                            </div>

                            <div className="filter-divider-v4" style={{ height: '1px', background: 'var(--border-subtle)', margin: '16px 0' }} />

                            <div className="filter-section-v4">
                                <h4 className="section-title" style={{ fontSize: '10px', color: 'var(--accent)', marginBottom: '12px', textTransform: 'uppercase', fontWeight: '800' }}>Upload Timeline</h4>
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
                        <div className="filings-ledger-header gst-docs-grid-template">
                        <div className="filings-ledger-header-cell">Document ID</div>
                        <div className="filings-ledger-header-cell">Person ID</div>
                        <div className="filings-ledger-header-cell">GSTIN</div>
                        <div className="filings-ledger-header-cell">Document Type</div>
                        <div className="filings-ledger-header-cell">Verification Status</div>
                        <div className="filings-ledger-header-cell">Verified By</div>
                        <div className="filings-ledger-header-cell">Verification Date</div>
                        <div className="filings-ledger-header-cell">Record Status</div>
                        <div className="filings-ledger-header-cell" style={{ justifyContent: 'center' }}>File Action</div>
                        <div className="filings-ledger-header-cell gst-sticky-actions" style={{ justifyContent: 'center' }}>Actions</div>
                    </div>

                    {loading ? (
                        <GSTDocumentsTableSkeleton />
                    ) : error ? (
                        <div className="employee-table-error">Error: {error}</div>
                    ) : data.length === 0 ? (
                        <div className="gst-no-data-v4">
                        <div className="no-data-icon-box">
                            <FileText size={40} />
                        </div>
                        <h3>No Documents Found</h3>
                        <p>We couldn&apos;t find any GST documents matching your current filters.</p>
                        <button type="button" className="btn-reset-v4" onClick={clearFilters} style={{ marginTop: '16px' }}>
                            Clear All Filters
                        </button>
                    </div>
                    ) : (
                        <div className="filings-ledger-body">
                        {data.map((item, idx) => (
                            <div 
                                key={idx} 
                                className="filings-ledger-row gst-docs-grid-template gst-table-row gst-table-row--static"
                            >
                                <div className="filings-ledger-cell gst-docs-document-id-cell">{item.document_id ?? '-'}</div>
                                <div className="filings-ledger-cell">{item.person_id ?? '-'}</div>
                                <div className="filings-ledger-cell" style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{item.gstin}</div>
                                <div className="filings-ledger-cell" style={{ fontWeight: '600' }}>{item.document_type}</div>
                                <div className="filings-ledger-cell">
                                    <span className={`status-badge-v4 ${item.verified ? 'completed' : 'overdue'}`}>
                                        {item.verified ? 'VERIFIED' : 'PENDING'}
                                    </span>
                                </div>
                                <div className="filings-ledger-cell">{item.verified_by_name || '-'}</div>
                                <div className="filings-ledger-cell" style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{formatDateTime(item.verified_at)}</div>
                                <div className="filings-ledger-cell">
                                    <span className={`status-badge-v4 ${item.is_active ? 'completed' : 'overdue'}`}>
                                        {item.is_active ? 'ACTIVE' : 'INACTIVE'}
                                    </span>
                                </div>
                                <div className="filings-ledger-cell" style={{ justifyContent: 'center' }}>
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button
                                            className="btn-icon-minimal"
                                            onClick={(e) => { e.stopPropagation(); handleView(item.document_url); }}
                                            title="View Document"
                                        >
                                            <ExternalLink size={16} color="var(--info)" />
                                        </button>
                                        <button
                                            className="btn-icon-minimal"
                                            onClick={(e) => { e.stopPropagation(); handleDownload(item.document_url, `doc_${item.document_id}`); }}
                                            title="Download Securely"
                                        >
                                            <FileDown size={16} color="var(--accent)" />
                                        </button>
                                    </div>
                                </div>
                                <div className="filings-ledger-cell gst-action-buttons gst-sticky-actions" style={{ justifyContent: 'center' }}>
                                        <button
                                            type="button"
                                            className="btn-view-action"
                                            title="View Full Details"
                                            onClick={(e) => openDocumentView(item, e)}
                                        >
                                            <Eye size={14} />
                                        </button>
                                        <button
                                            type="button"
                                            className="btn-edit-action"
                                            title="Edit Document"
                                            onClick={(e) => openDocumentEdit(item, e)}
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

            <UploadDocuments
                isOpen={showUploadModal}
                mode={uploadMode}
                onClose={() => {
                    setShowUploadModal(false);
                    fetchGstData();
                }}
            />

            <GSTDocumentsDetailsModal
                key={selectedDocument ? `doc-edit-${selectedDocument.document_id}-${editModalMode}` : 'doc-edit-closed'}
                isOpen={showDetailsModal}
                data={selectedDocument}
                onClose={closeDetailsModal}
                onUpdated={fetchGstData}
                isAdmin={isAdmin}
                canEdit={canEdit}
                initialEditMode={editModalMode}
            />

            <GSTDocumentsViewPanel 
                isOpen={viewPanelOpen}
                onClose={() => {
                    setViewPanelOpen(false);
                    setViewDocId(null);
                }}
                documentId={viewDocId}
                documentData={data.find(d => d.document_id === viewDocId)}
                onUpdate={fetchGstData}
            />
        </div>
    );
};


const GSTDocumentsDetailsModal = ({ isOpen, data, onClose, onUpdated, isAdmin, canEdit: canEditProp, initialEditMode = false }) => {
    const canEdit = canEditProp ?? isAdmin;
    const [item, setItem] = useState(data);
    const [editMode, setEditMode] = useState(initialEditMode);
    const [formData, setFormData] = useState(data || {});
    const [message, setMessage] = useState({ type: '', text: '' });
    const [actionLoading, setActionLoading] = useState('');
    const [confirmAction, setConfirmAction] = useState('');

    // New states for enhanced editing
    const [fetchingDocs, setFetchingDocs] = useState(false);
    const [requiredDocs, setRequiredDocs] = useState([]);
    const [uploadMethod, setUploadMethod] = useState('link'); // Default to link for editing existing
    const [selectedFile, setSelectedFile] = useState(null);

    useEffect(() => {
        if (!isOpen) return;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen || !data) return;
        setItem(data);
        setFormData(data);
        setEditMode(initialEditMode);
        setMessage({ type: '', text: '' });
        setConfirmAction('');
        setUploadMethod('link');
        setSelectedFile(null);
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
            },
        });
    };

    const isEditing = editMode || initialEditMode;
    const showEditFooter = isEditing;
    const showViewFooter = !isEditing && canEdit;

    // Fetch required docs when person_id changes
    useEffect(() => {
        const fetchRequiredDocs = async () => {
            if (!editMode || !formData.person_id || isNaN(formData.person_id)) {
                setRequiredDocs([]);
                return;
            }

            setFetchingDocs(true);
            try {
                const personRes = await api.get(`/api/v1/gst-people/dynamic_filter?person_id=${formData.person_id}`);
                const personData = personRes.data?.data?.[0];

                if (personData && personData.gst_registration_id) {
                    const docsRes = await api.get(`/api/v1/document-config/gst-registration/${personData.gst_registration_id}/required-documents?person_id=${formData.person_id}`);
                    const fetchedDocs = docsRes.data?.documents || [];
                    
                    // Ensure the currently selected document type is always in the list
                    const currentType = item?.document_type;
                    if (currentType && !fetchedDocs.some(d => d.value === currentType)) {
                        fetchedDocs.unshift({ 
                            value: currentType, 
                            display_name: currentType, 
                            is_mandatory: false 
                        });
                    }
                    setRequiredDocs(fetchedDocs);
                } else {
                    setRequiredDocs([]);
                }
            } catch (err) {
                console.error("Failed to fetch required documents:", err);
                setRequiredDocs([]);
            } finally {
                setFetchingDocs(false);
            }
        };

        const timer = setTimeout(fetchRequiredDocs, 500);
        return () => clearTimeout(timer);
    }, [formData.person_id, editMode]);

    const handleChange = (e) => {
        const { name, value, type, checked, files } = e.target;

        if (type === 'file') {
            const file = files[0];
            if (file) {
                const allowedTypes = ['application/pdf', 'image/jpeg', 'image/png'];
                if (!allowedTypes.includes(file.type)) {
                    setMessage({ type: 'error', text: 'Unsupported file type. Allowed: PDF, JPG, PNG.' });
                    setSelectedFile(null);
                    return;
                }
                if (file.size > 10 * 1024 * 1024) {
                    setMessage({ type: 'error', text: 'File size exceeds 10MB limit.' });
                    setSelectedFile(null);
                    return;
                }
                setMessage({ type: '', text: '' });
                setSelectedFile(file);
            }
            return;
        }

        setFormData(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));

        if (name === 'person_id') {
            setFormData(prev => ({ ...prev, document_type: '' }));
            setRequiredDocs([]);
        }
    };

    const handleSave = async () => {
        setMessage({ type: '', text: '' });
        setActionLoading('save');
        try {
            const target = item || data;
            if (!target?.document_id) {
                setMessage({ type: 'error', text: 'Document ID is missing. Please reopen the details.' });
                setActionLoading('');
                return;
            }

            let finalUrl = formData.document_url;

            // Handle file upload if method is 'file'
            if (uploadMethod === 'file' && selectedFile) {
                const uploadFormData = new FormData();
                uploadFormData.append('file', selectedFile);

                const uploadRes = await api.post('/api/v1/gst-blob/upload', uploadFormData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                finalUrl = uploadRes.data.blob_url;
            }

            const payload = {
                document_type: formData.document_type,
                document_url: finalUrl,
                verified: formData.verified,
            };

            await api.post(`/api/v1/gst-documents/${target.document_id}/edit`, payload);

            setMessage({ type: 'success', text: 'Updated successfully!' });
            if (onUpdated) onUpdated();
            if (shouldCloseDrawerAfterSave(initialEditMode)) {
                onClose();
                return;
            }
            setEditMode(false);
            const updatedItem = { ...formData, document_url: finalUrl, person_id: parseInt(formData.person_id, 10) };
            setItem({ ...item, ...updatedItem });
            setFormData({ ...item, ...updatedItem });
        } catch (err) {
            console.error("Save error:", err);
            let errorMsg = err.message;
            if (err.response?.data?.detail) {
                const detail = err.response.data.detail;
                if (Array.isArray(detail)) {
                    errorMsg = detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ');
                } else {
                    errorMsg = detail;
                }
            }
            setMessage({ type: 'error', text: String(errorMsg) });
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
            if (!target?.document_id) {
                setMessage({ type: 'error', text: 'Document ID is missing. Please reopen the details.' });
                setActionLoading('');
                return;
            }
            await api.delete(`/api/v1/gst-documents/${target.document_id}/soft_delete`);
            setMessage({ type: 'success', text: 'Deleted successfully!' });
            setTimeout(() => {
                if (onUpdated) onUpdated();
                if (onClose) onClose();
            }, 1200);
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
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
            if (!target?.document_id) {
                setMessage({ type: 'error', text: 'Document ID is missing. Please reopen the details.' });
                setActionLoading('');
                return;
            }
            const res = await api.post(`/api/v1/gst-documents/${target.document_id}/activate`);
            const updatedData = res.data;
            setMessage({ type: 'success', text: 'Activated successfully!' });
            const finalData = { ...updatedData, is_active: true };
            setItem(finalData);
            setFormData(finalData);
            if (onUpdated) onUpdated();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setActionLoading('');
        }
    };

    const currentItem = item || data;
    if (!isOpen || !currentItem) return null;

    const drawerPanel = (
        <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={onClose}>
            <div className="gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
                <div className="drawer-header gst-reg-details-header">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4" style={{ background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--info)' }}>
                            <FileText size={20} />
                        </div>
                        <div className="modal-title-box">
                            <div className="modal-header-texts">
                                <h2 className="modal-title-v4">
                                    {currentItem?.document_type || 'GST Document'}
                                    {isEditing ? (
                                        <span className="modal-header-tag-v4 edit">EDIT</span>
                                    ) : (
                                        <span className="modal-header-tag-v4 view">VIEW</span>
                                    )}
                                </h2>
                                <p className="modal-subtitle-v4">Manage document details • ID: {currentItem?.document_id || '-'}</p>
                            </div>
                        </div>
                    </div>
                    <button type="button" className="btn-drawer-close" onClick={onClose} aria-label="Close"><X size={20} /></button>
                </div>

                <div className="drawer-content gst-reg-details-scroll gst-reg-details-form">
                        {message.text && (
                            <div className={`gst-message-banner ${message.type === 'success' ? 'success' : 'error'}`} style={{ marginBottom: '24px' }}>
                                {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                                <span className="gst-message-banner-text">{message.text}</span>
                            </div>
                        )}

                        {isEditing ? (
                            <div className="form-section-group">
                                <h3 className="section-title">1. Document Context</h3>
                                <div className="form-grid-3">
                                    <div className="form-group-v4">
                                        <label className="modal-label-caps">Person ID</label>
                                        <div className="modal-input-wrapper-v4">
                                            <Hash size={14} className="input-icon-v4" />
                                            <input
                                                type="number"
                                                name="person_id"
                                                value={formData.person_id || ''}
                                                readOnly
                                                disabled
                                                className="modal-input-v4 with-icon read-only-input"
                                                placeholder="ID"
                                            />
                                        </div>
                                    </div>

                                    <div className="form-group-v4">
                                        <label className="modal-label-caps">Document Type*</label>
                                        <div className="modal-input-wrapper-v4">
                                            <FileText size={14} className="input-icon-v4" />
                                            {requiredDocs.length > 0 || fetchingDocs ? (
                                                <FormCustomSelect
                                                    name="document_type"
                                                    value={formData.document_type || ''}
                                                    onChange={handleChange}
                                                    options={optionsFromPairs([
                                                        ...(fetchingDocs ? [] : [{ value: '', label: 'Select Type' }]),
                                                        ...(fetchingDocs && formData.document_type
                                                            ? [{ value: formData.document_type, label: formData.document_type }]
                                                            : []),
                                                        ...requiredDocs.map((doc) => ({
                                                            value: doc.value,
                                                            label: `${doc.display_name}${doc.is_mandatory ? ' *' : ''}`,
                                                        })),
                                                    ])}
                                                    placeholder={fetchingDocs ? 'Loading...' : 'Select Type'}
                                                    ariaLabel="Document type"
                                                    disabled={fetchingDocs}
                                                />
                                            ) : (
                                                <input
                                                    type="text"
                                                    name="document_type"
                                                    value={formData.document_type || ''}
                                                    onChange={handleChange}
                                                    required
                                                    className="modal-input-v4 with-icon"
                                                    placeholder="Enter type"
                                                />
                                            )}
                                            {fetchingDocs && (
                                                <div className="input-loader-right">
                                                    <RotateCcw size={12} className="refresh-spin" />
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-group">
                                    <h3 className="section-title">2. Update File</h3>
                                    
                                    <div className="upload-method-selector-v4">
                                        <button
                                            type="button"
                                            className={`method-chip-v4 ${uploadMethod === 'file' ? 'active' : ''}`}
                                            onClick={() => setUploadMethod('file')}
                                        >
                                            <FileIcon size={14} /> Replace File
                                        </button>
                                        <button
                                            type="button"
                                            className={`method-chip-v4 ${uploadMethod === 'link' ? 'active' : ''}`}
                                            onClick={() => setUploadMethod('link')}
                                        >
                                            <LinkIcon size={14} /> Update Link
                                        </button>
                                    </div>

                                    <div className="submission-zone-v4">
                                        {uploadMethod === 'file' ? (
                                            <div className="premium-drop-zone-v4">
                                                {!selectedFile ? (
                                                    <label className="drop-zone-label-v4">
                                                        <input
                                                            type="file"
                                                            onChange={handleChange}
                                                            accept=".pdf,.jpg,.jpeg,.png"
                                                            className="hidden-file-input"
                                                        />
                                                        <div className="drop-zone-content-v4">
                                                            <div className="drop-icon-box-v4">
                                                                <Upload size={24} />
                                                            </div>
                                                            <div className="drop-text-box-v4">
                                                                <p className="main-drop-text">Click to replace file</p>
                                                                <p className="sub-drop-text">PDF, JPG, PNG • Max 10MB</p>
                                                            </div>
                                                        </div>
                                                    </label>
                                                ) : (
                                                    <div className="file-preview-card-v4">
                                                        <div className="file-preview-icon-v4">
                                                            <FileIcon size={20} />
                                                        </div>
                                                        <div className="file-preview-info-v4">
                                                            <span className="file-preview-name">{selectedFile.name}</span>
                                                            <span className="file-preview-size">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</span>
                                                        </div>
                                                        <button
                                                            type="button"
                                                            className="btn-remove-preview-v4"
                                                            onClick={() => setSelectedFile(null)}
                                                        >
                                                            <Trash2 size={16} />
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <div className="premium-link-zone-v4">
                                                <div className="drop-icon-box-v4">
                                                    <LinkIcon size={24} />
                                                </div>
                                                <div className="drop-text-box-v4">
                                                    <p className="main-drop-text">Update Document Link</p>
                                                    <textarea
                                                        name="document_url"
                                                        value={formData.document_url || ''}
                                                        onChange={handleChange}
                                                        required
                                                        className="premium-link-textarea-v4"
                                                        placeholder="Paste the new document URL here..."
                                                        rows="2"
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    <div className="verification-toggle-v4">
                                        <label className="v4-checkbox-label">
                                            <input
                                                type="checkbox"
                                                name="verified"
                                                checked={!!formData.verified}
                                                onChange={handleChange}
                                                className="modal-checkbox-v4"
                                            />
                                            <span className="checkbox-text-v4">Document verified by regulatory authority</span>
                                        </label>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div className="form-section-group">
                                <div className="gst-details-premium-grid">
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">DOCUMENT ID</span>
                                        <span className="detail-value-v4 highlight-blue">{currentItem.document_id}</span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">GSTIN</span>
                                        <span className="detail-value-v4" style={{ fontFamily: 'monospace' }}>{currentItem.gstin || '-'}</span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">PERSON ID</span>
                                        <span className="detail-value-v4 highlight-green-v4">{currentItem.person_id || '-'}</span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">DOCUMENT TYPE</span>
                                        <span className="detail-value-v4">{currentItem.document_type || '-'}</span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">OWNERSHIP</span>
                                        <span className="detail-value-v4">{currentItem.ownership_category || '-'}</span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">MOBILE</span>
                                        <span className="detail-value-v4">{currentItem.mobile || '-'}</span>
                                    </div>
                                    <div className="detail-item-v4 full-width">
                                        <span className="detail-label-v4">DOCUMENT RESOURCE</span>
                                        <div className="detail-value-v4">
                                            <a 
                                                href={currentItem.document_url} 
                                                target="_blank" 
                                                rel="noopener noreferrer" 
                                                className="premium-view-link"
                                            >
                                                <Eye size={14} /> View Document Resource
                                            </a>
                                        </div>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">VERIFICATION STATUS</span>
                                        <span className={`status-badge-v4 ${currentItem.verified ? 'verified' : 'pending'}`}>
                                            {currentItem.verified ? 'Verified' : 'Pending'}
                                        </span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">VERIFIED BY</span>
                                        <span className="detail-value-v4">{currentItem.verified_by || '-'}</span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">RECORD STATUS</span>
                                        <span className={`status-badge-v4 ${currentItem.is_active ? 'active' : 'inactive'}`}>
                                            {currentItem.is_active ? 'Active' : 'Inactive'}
                                        </span>
                                    </div>
                                    <div className="detail-item-v4">
                                        <span className="detail-label-v4">CREATED AT</span>
                                        <span className="detail-value-v4">{formatDateTime(currentItem.created_at)}</span>
                                    </div>
                                </div>
                            </div>
                        )}
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
                                            <Edit3 size={16} /> Edit Details
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
                                            <CheckCircle2 size={16} /> Activate Record
                                        </button>
                                    ) : null
                                )
                            )
                        )}
                </AppDrawerFooter>

            {confirmAction && (
                <div className="gst-confirm-overlay" onClick={() => setConfirmAction('')}>
                    <div className="gst-confirm-content" onClick={e => e.stopPropagation()}>
                        <div className="gst-confirm-icon">
                            <AlertCircle size={32} color={confirmAction === 'delete' ? 'var(--danger)' : 'var(--accent)'} />
                        </div>
                        <h2>{confirmAction === 'delete' ? 'Confirm Delete' : 'Confirm Activation'}</h2>
                        <p>
                            {confirmAction === 'delete'
                                ? 'Are you sure you want to delete this GST document?'
                                : 'Are you sure you want to activate this GST document?'}
                        </p>
                        <div className="footer-actions-v4" style={{ marginTop: '32px', justifyContent: 'center' }}>
                            <button className="gst-btn-secondary" onClick={() => setConfirmAction('')} disabled={actionLoading !== ''}>
                                Cancel
                            </button>
                            <button 
                                className="glow-green" 
                                style={confirmAction === 'delete' ? { background: 'var(--danger)', boxShadow: '0 2px 8px rgba(var(--danger-rgb), 0.24)' } : {}}
                                onClick={confirmAction === 'delete' ? handleDelete : handleActivate} 
                                disabled={actionLoading !== ''}
                            >
                                {actionLoading !== '' ? <RotateCcw size={16} className="refresh-spin" /> : null}
                                {actionLoading !== '' ? 'Processing...' : 'Confirm Action'}
                            </button>
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


export const GSTDocumentDetails = ({ onLogout }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const data = location.state?.data;

    const label = 'GST Document';
    const [item, setItem] = useState(data);
    const [editMode, setEditMode] = useState(false);
    const [formData, setFormData] = useState(data);
    const [message, setMessage] = useState({ type: '', text: '' });
    const [isAdmin, setIsAdmin] = useState(false);
    const [showUploadModal, setShowUploadModal] = useState(false);
    const [uploadMode, setUploadMode] = useState('upload');

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

    // All hooks above — safe to early-return now (Rules of Hooks): guarding
    // before the useState/useEffect calls crashes React on a hook-count mismatch.
    if (!data) return <div className="gst-docs-no-data">No data provided. Please navigate from the dashboard.</div>;

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
    };

    const handleSave = async () => {
        setMessage({ type: '', text: '' });
        try {
            const payload = {
                document_type: formData.document_type,
                document_url: formData.document_url,
                verified: formData.verified,
            };
            await api.post(`/api/v1/gst-documents/${item.document_id}/edit`, payload);

            setMessage({ type: 'success', text: 'Updated successfully!' });
            setEditMode(false);
            setItem(prev => ({ ...prev, ...formData }));
        } catch (err) { setMessage({ type: 'error', text: err.message }); }
    };

    const handleDelete = async () => {
        if (!window.confirm(`Are you sure you want to delete this ${label}?`)) return;
        setMessage({ type: '', text: '' });
        try {
            await api.delete(`/api/v1/gst-documents/${item.document_id}/soft_delete`);

            setMessage({ type: 'success', text: 'Deleted successfully! Redirecting...' });
            setTimeout(() => {
                navigate('/dashboard?tab=gst&sub=documents');
            }, 1500);
        } catch (err) { setMessage({ type: 'error', text: err.message }); }
    };

    const handleActivate = async () => {
        if (!window.confirm(`Are you sure you want to activate this ${label}?`)) return;
        setMessage({ type: '', text: '' });
        try {
            const res = await api.post(`/api/v1/gst-documents/${item.document_id}/activate`);
            const updatedData = res.data;
            setMessage({ type: 'success', text: 'Activated successfully!' });
            const finalData = { ...updatedData, is_active: true };
            setItem(finalData);
            setFormData(finalData);
        } catch (err) { setMessage({ type: 'error', text: err.message }); }
    };

    return (
        <div className="employee-details-page">
            <div className="bg-orb orb-1"></div>
            <div className="bg-orb orb-2"></div>
            <div className="grid-overlay"></div>

            <div className="card-shell gst-docs-card-shell">
                <div className="accent-bar"></div>
                <div className="card-scroll">

                    <div className="centerText">
                        <span className="eyebrow">{editMode ? 'Edit Mode' : 'GST Document Record'}</span>
                        <h2>{label} Details</h2>
                    </div>

                    {message.text && (
                        <div className={`message-banner ${message.text.includes('success') ? 'success' : 'error'}`}>
                            {message.text}
                        </div>
                    )}

                    <div className="form">
                        {editMode ? (
                            <>
                                <div className="form-grid">
                                    <label>
                                        Doc Type
                                        <input name="document_type" value={formData.document_type || ''} onChange={handleChange} />
                                    </label>
                                    <label>
                                        Doc URL
                                        <input name="document_url" value={formData.document_url || ''} onChange={handleChange} />
                                    </label>
                                    <div className="gst-docs-checkbox-group-wrapper">
                                        <label className="filter-label gst-docs-checkbox-label">
                                            <input type="checkbox" name="verified" checked={formData.verified} onChange={handleChange} className="gst-docs-checkbox-input" /> Verified
                                        </label>
                                    </div>
                                </div>
                                <div className="form-buttons">
                                    <button onClick={handleSave} className="btn-success">Save Changes</button>
                                    <button onClick={() => { setEditMode(false); setFormData(item); setMessage({ type: '', text: '' }); }} className="btn-secondary">Cancel</button>
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="form-grid">
                                    <label>Doc ID<div className="form-value-box">{item.document_id}</div></label>
                                    <label>GSTIN<div className="form-value-box">{item.gstin}</div></label>
                                    <label>Person ID<div className="form-value-box">{item.person_id || '-'}</div></label>
                                    <label>Doc Type<div className="form-value-box">{item.document_type}</div></label>
                                    <label>Ownership<div className="form-value-box">{item.ownership_category || '-'}</div></label>
                                    <label>Mobile<div className="form-value-box">{item.mobile || '-'}</div></label>
                                    <label>Doc URL
                                        <div className="form-value-box gst-docs-form-value-box-ellipsis">
                                            <a href={item.document_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>View Document</a>
                                        </div>
                                    </label>
                                    <label>Verified<div className="form-value-box">{item.verified ? 'Yes' : 'No'}</div></label>
                                    <label>Verified By<div className="form-value-box">{item.verified_by || '-'}</div></label>
                                    <label>Verified At<div className="form-value-box">{formatDateTime(item.verified_at)}</div></label>
                                    <label>Active<div className="form-value-box">{item.is_active ? 'Yes' : 'No'}</div></label>
                                    <label>Created At<div className="form-value-box">{formatDateTime(item.created_at)}</div></label>
                                    <label>Updated At<div className="form-value-box">{formatDateTime(item.updated_at)}</div></label>
                                </div>

                                <div className="form-buttons gst-docs-form-buttons">
                                    {isAdmin && (
                                        item.is_active ? (
                                            <>
                                                <button onClick={() => setEditMode(true)}>Edit Details</button>
                                                <button onClick={handleDelete} className="btn-danger">Delete</button>
                                            </>
                                        ) : (
                                            <button onClick={handleActivate} className="btn-success">Activate</button>
                                        )
                                    )}
                                </div>
                            </>
                        )}


                    </div>
                </div>
            </div>

            <UploadDocuments
                isOpen={showUploadModal}
                mode={uploadMode}
                onClose={() => setShowUploadModal(false)}
            />
        </div>
    );
};
