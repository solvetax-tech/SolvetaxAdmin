/**
 * @file CustomerServiceDetailsModal.jsx
 * @description Renders a detailed view of a customer service record in a premium modal.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    Loader2,
    Briefcase,
    AlertCircle,
    CheckCircle2,
    Tag,
    User,
    Calendar,
    Hash,
    X,
    Activity,
} from 'lucide-react';
import {
    getCustomerServiceById,
    patchCustomerService,
    patchCustomerServiceStatus,
    softDeleteCustomerService,
    activateCustomerService,
    recordStatusLabel,
} from '../../utils/customerServiceApi';
import {
    fetchActiveRmEmployees,
    fetchActiveOpEmployees,
    buildRmOpIdSelectOptions,
} from '../../utils/activeEmployees';
import { handleDrawerCancelEdit, shouldCloseDrawerAfterSave } from '../../utils/drawerEditFlow';
import '../common/AppSideDrawer.css';
import {
    AppDrawerModalFooter,
    AppDrawerBtnDelete,
    AppDrawerBtnCancel,
    AppDrawerBtnSave,
} from '../common/AppDrawerEditFooter';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import './CustomerServiceDetailsModal.css';

const SERVICE_STATUS_OPTIONS = optionsFromPairs([
    { value: 'PENDING', label: 'Pending' },
    { value: 'PROVIDED', label: 'Provided' },
]);

const RECORD_STATUS_OPTIONS = optionsFromPairs([
    { value: 'true', label: 'Active' },
    { value: 'false', label: 'Inactive' },
]);

const buildFormFromService = (row) => ({
    rm_id: row?.rm_id != null && row?.rm_id !== '' ? String(row.rm_id) : '',
    op_id: row?.op_id != null && row?.op_id !== '' ? String(row.op_id) : '',
    service_status: row?.service_status || 'PENDING',
    is_active: row?.is_active === false ? 'false' : 'true',
});

const CustomerServiceDetailsModal = ({
    serviceId,
    onClose,
    initialService = null,
    initialRmUsername = '-',
    initialOpUsername = '-',
    isAdmin = false,
    initialEditMode = false,
    onUpdated,
    setToastMessage,
}) => {
    const [service, setService] = useState(initialService);
    const [loading, setLoading] = useState(!initialService);
    const [error, setError] = useState(null);
    const [editMode, setEditMode] = useState(initialEditMode);
    const [formData, setFormData] = useState(buildFormFromService(initialService));
    const [saveLoading, setSaveLoading] = useState(false);
    const [statusLoading, setStatusLoading] = useState(false);
    const [activeRMs, setActiveRMs] = useState([]);
    const [activeOps, setActiveOps] = useState([]);
    const [rmUsername, setRmUsername] = useState(initialRmUsername);
    const [opUsername, setOpUsername] = useState(initialOpUsername);

    const fetchServiceDetails = useCallback(async () => {
        if (!serviceId) return;
        if (!isAdmin) {
            if (initialService) {
                setService(initialService);
                setFormData(buildFormFromService(initialService));
            }
            setLoading(false);
            return;
        }

        if (!initialService) setLoading(true);
        setError(null);
        try {
            const serviceData = await getCustomerServiceById(serviceId);
            if (!serviceData) {
                throw new Error('Service record not found.');
            }
            setService(serviceData);
            setFormData(buildFormFromService(serviceData));
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : err?.message || 'Failed to load service details.');
        } finally {
            if (!initialService) setLoading(false);
        }
    }, [serviceId, initialService, isAdmin]);

    useEffect(() => {
        fetchServiceDetails();
    }, [fetchServiceDetails]);

    useEffect(() => {
        setService(initialService);
        setLoading(!initialService && isAdmin);
        setRmUsername(initialRmUsername);
        setOpUsername(initialOpUsername);
        setFormData(buildFormFromService(initialService));
        setEditMode(initialEditMode);
        setError(null);
    }, [initialService, initialRmUsername, initialOpUsername, serviceId, isAdmin, initialEditMode]);

    useEffect(() => {
        if (!service) return;
        setRmUsername(service.rm_name || initialRmUsername);
        setOpUsername(service.op_name || initialOpUsername);
    }, [service, initialRmUsername, initialOpUsername]);

    useEffect(() => {
        if (!isAdmin || !editMode) return;
        Promise.all([fetchActiveRmEmployees(), fetchActiveOpEmployees()])
            .then(([rms, ops]) => {
                setActiveRMs(rms);
                setActiveOps(ops);
            })
            .catch(() => {
                setActiveRMs([]);
                setActiveOps([]);
            });
    }, [isAdmin, editMode]);

    const rmOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'Unassigned' },
            ...buildRmOpIdSelectOptions(activeRMs, service?.rm_id != null ? {
                id: service.rm_id,
                label: rmUsername,
            } : null),
        ]),
        [activeRMs, service?.rm_id, rmUsername],
    );

    const opOptions = useMemo(
        () => optionsFromPairs([
            { value: '', label: 'Unassigned' },
            ...buildRmOpIdSelectOptions(activeOps, service?.op_id != null ? {
                id: service.op_id,
                label: opUsername,
            } : null),
        ]),
        [activeOps, service?.op_id, opUsername],
    );

    const handleFieldChange = (e) => {
        const { name, value } = e.target;
        setFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleCancelEdit = () => {
        handleDrawerCancelEdit({
            initialEditMode,
            onClose,
            setEditMode,
            resetEditState: () => {
                setFormData(buildFormFromService(service));
            },
        });
    };

    const handleSave = async () => {
        if (!serviceId) return;
        setSaveLoading(true);
        setError(null);
        try {
            if (isAdmin) {
                const body = {
                    service_status: formData.service_status,
                    is_active: formData.is_active === 'true',
                };
                if (formData.rm_id) body.rm_id = Number(formData.rm_id);
                else body.rm_id = null;
                if (formData.op_id) body.op_id = Number(formData.op_id);
                else body.op_id = null;

                const updated = await patchCustomerService(serviceId, body);
                setService(updated);
                setFormData(buildFormFromService(updated));
                setToastMessage?.({ type: 'success', text: 'Customer service updated.' });
            } else {
                const updated = await patchCustomerServiceStatus(serviceId, formData.service_status);
                setService((prev) => ({ ...prev, ...updated, service_status: formData.service_status }));
                setToastMessage?.({ type: 'success', text: 'Service status updated.' });
            }
            if (shouldCloseDrawerAfterSave(initialEditMode)) {
                onUpdated?.();
                onClose?.();
                return;
            }
            setEditMode(false);
            onUpdated?.();
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : err?.message || 'Failed to save changes.');
        } finally {
            setSaveLoading(false);
        }
    };

    const handleToggleActive = async () => {
        if (!serviceId || !isAdmin) return;
        const isActive = recordStatusLabel(service) === 'ACTIVE';
        setStatusLoading(true);
        setError(null);
        try {
            if (isActive) {
                await softDeleteCustomerService(serviceId);
                setToastMessage?.({ type: 'success', text: 'Customer service deactivated.' });
            } else {
                await activateCustomerService(serviceId);
                setToastMessage?.({ type: 'success', text: 'Customer service activated.' });
            }
            await fetchServiceDetails();
            onUpdated?.();
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : err?.message || 'Failed to update record status.');
        } finally {
            setStatusLoading(false);
        }
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try {
            return new Date(dtStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
        } catch {
            return dtStr;
        }
    };

    const displayStatus = recordStatusLabel(service);
    const isEditing = editMode || initialEditMode;

    const drawerShell = (bodyContent) => (
        <div className="gst-filters-drawer-overlay app-side-drawer-mode" onClick={onClose}>
            <div
                className={`gst-filters-drawer gst-reg-details-drawer gst-reg-side-drawer-shell app-drawer-panel customer-service-details-drawer${isEditing ? ' edit-mode' : ' view-mode'}`}
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
                aria-labelledby="cs-service-drawer-title"
            >
                <div className="drawer-header">
                    <div>
                        <h2 id="cs-service-drawer-title" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                            {isEditing ? 'Edit Customer Service' : 'Customer Service Details'}
                        </h2>
                        <p style={{ margin: '6px 0 0', fontSize: '13px', color: 'var(--text-primary)' }}>
                            {service?.id ?? '—'}
                            {service?.full_name ? ` · ${service.full_name}` : ''}
                        </p>
                    </div>
                    <button type="button" className="btn-drawer-close" onClick={onClose} aria-label="Close">
                        <X size={20} />
                    </button>
                </div>

                {error && (
                    <div className="modal-global-error-banner" style={{ margin: '0 24px 8px' }}>
                        <span>{error}</span>
                    </div>
                )}

                {bodyContent}

                {isEditing && (
                    <AppDrawerModalFooter
                        leading={isAdmin ? (
                            <AppDrawerBtnDelete
                                onClick={handleToggleActive}
                                disabled={statusLoading || saveLoading}
                                label={displayStatus === 'ACTIVE' ? 'Deactivate' : 'Activate'}
                            />
                        ) : null}
                    >
                        <AppDrawerBtnCancel onClick={handleCancelEdit} disabled={saveLoading} />
                        <AppDrawerBtnSave onClick={handleSave} loading={saveLoading} />
                    </AppDrawerModalFooter>
                )}
            </div>
        </div>
    );

    if (loading) {
        return drawerShell(
            <div className="drawer-content gst-reg-details-scroll">
                <div className="modal-inner-loading-overlay">
                    <Loader2 size={40} className="spin" />
                    <p>Loading service details...</p>
                </div>
            </div>,
        );
    }

    if (error && !service) {
        return drawerShell(
            <div className="drawer-content gst-reg-details-scroll cs-drawer-error-state">
                <AlertCircle size={48} color="#ef4444" />
                <h2>Error Loading Service</h2>
                <p>{error}</p>
            </div>,
        );
    }

    return drawerShell(
                <div className="drawer-content gst-reg-details-scroll">
                    <div className="premium-edit-grid-v4 cs-service-details-grid">
                        <div className="input-group-v4">
                            <label><Hash size={14} /> Service ID</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.id ?? ''} disabled />
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><User size={14} /> Customer ID</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.customer_id ?? ''} disabled />
                            </div>
                        </div>

                        <div className="input-group-v4 full">
                            <label><User size={14} /> Customer Name</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.full_name ?? ''} disabled style={{ color: 'var(--text-primary)', fontWeight: '600' }} />
                            </div>
                        </div>

                        
                        <div className="input-group-v4">
                            <label><User size={14} /> Business Name</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.business_name ?? '-'} disabled />
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><User size={14} /> Phone</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.mobile ?? '-'} disabled />
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><Briefcase size={14} /> Service Name</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.service_name ?? ''} disabled />
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><Tag size={14} /> Service Code</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={service?.service_code ?? ''} disabled className="code-badge-input" />
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><User size={14} /> RM</label>
                            <div className="input-wrapper-v4">
                                {isEditing && isAdmin ? (
                                    <FormCustomSelect
                                        name="rm_id"
                                        value={formData.rm_id}
                                        onChange={handleFieldChange}
                                        options={rmOptions}
                                        placeholder="Unassigned"
                                        ariaLabel="RM"
                                    />
                                ) : (
                                    <input type="text" value={rmUsername} disabled />
                                )}
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><User size={14} /> OP</label>
                            <div className="input-wrapper-v4">
                                {isEditing && isAdmin ? (
                                    <FormCustomSelect
                                        name="op_id"
                                        value={formData.op_id}
                                        onChange={handleFieldChange}
                                        options={opOptions}
                                        placeholder="Unassigned"
                                        ariaLabel="OP"
                                    />
                                ) : (
                                    <input type="text" value={opUsername} disabled />
                                )}
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><Activity size={14} /> Status</label>
                            <div className="input-wrapper-v4">
                                {isEditing && isAdmin ? (
                                    <FormCustomSelect
                                        name="is_active"
                                        value={formData.is_active}
                                        onChange={handleFieldChange}
                                        options={RECORD_STATUS_OPTIONS}
                                        placeholder="Status"
                                        ariaLabel="Record status"
                                    />
                                ) : (
                                    <input
                                        type="text"
                                        value={displayStatus}
                                        disabled
                                        className={`status-text-${displayStatus.toLowerCase()}`}
                                    />
                                )}
                            </div>
                        </div>

                        <div className="input-group-v4">
                            <label><CheckCircle2 size={14} /> Service Status</label>
                            <div className="input-wrapper-v4">
                                {isEditing ? (
                                    <FormCustomSelect
                                        name="service_status"
                                        value={formData.service_status}
                                        onChange={handleFieldChange}
                                        options={SERVICE_STATUS_OPTIONS}
                                        placeholder="Service status"
                                        ariaLabel="Service status"
                                    />
                                ) : (
                                    <input
                                        type="text"
                                        value={service?.service_status ?? '-'}
                                        disabled
                                        className={`status-text-${service?.service_status === 'PROVIDED' ? 'success' : 'pending'}`}
                                    />
                                )}
                            </div>
                        </div>

                        <div className="input-group-v4 full">
                            <label><Calendar size={14} /> Created At</label>
                            <div className="input-wrapper-v4">
                                <input type="text" value={formatDateTime(service?.created_at)} disabled />
                            </div>
                        </div>
                    </div>
                </div>
    );
};

export default CustomerServiceDetailsModal;
