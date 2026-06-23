/**
 * @file FollowupManager.jsx
 * @description Integrated follow-up history and creation component for Customer Services.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    Loader2,
    Clock,
    User,
    MessageSquare,
    Plus,
    Send,
    AlertCircle,
} from 'lucide-react';
import {
    listCustomerServiceFollowups,
    scheduleCustomerServiceFollowup,
    updateCustomerServiceFollowup,
    hasOpenCustomerServiceFollowup,
} from '../../utils/followupsApi';
import { patchCustomerService } from '../../utils/customerServiceApi';
import {
    fetchActiveRmEmployees,
    buildRmOpIdSelectOptions,
} from '../../utils/activeEmployees';
import './FollowupManager.css';
import ModernDateTimePicker from '../common/ModernDateTimePicker';
import { addNotification } from '../../utils/notificationUtils';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';

const FollowupManager = ({
    serviceId,
    serviceData,
    rmUsername,
    isAdmin,
    onFollowupCreated,
    onServiceUpdated,
    setToastMessage,
}) => {
    const [localService, setLocalService] = useState(serviceData);
    const [followups, setFollowups] = useState([]);
    const [loading, setLoading] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [isAssigningRm, setIsAssigningRm] = useState(false);
    const [activeRMs, setActiveRMs] = useState([]);
    const [selectedRmId, setSelectedRmId] = useState('');
    const [error, setError] = useState(null);
    const [newFollowup, setNewFollowup] = useState({
        followup_at: '',
        remarks: '',
    });

    const hasRmAssigned = Boolean(
        localService?.rm_id != null && localService?.rm_id !== '',
    );

    useEffect(() => {
        setLocalService(serviceData);
    }, [serviceData]);

    useEffect(() => {
        if (!isAdmin || hasRmAssigned) return;
        fetchActiveRmEmployees()
            .then(setActiveRMs)
            .catch(() => setActiveRMs([]));
    }, [isAdmin, hasRmAssigned]);

    const fetchFollowups = useCallback(async () => {
        if (!serviceId) return;
        setLoading(true);
        try {
            const response = await listCustomerServiceFollowups({
                customer_service_id: parseInt(serviceId, 10),
            });
            setFollowups(response.data.data || []);
        } catch (err) {
            console.error('Failed to fetch follow-ups:', err);
        } finally {
            setLoading(false);
        }
    }, [serviceId]);

    useEffect(() => {
        fetchFollowups();
    }, [fetchFollowups]);

    const handleCreateFollowup = async (e) => {
        if (e) e.preventDefault();

        if (!hasRmAssigned) {
            setError('Assign an RM to this service before scheduling a follow-up.');
            return;
        }

        if (!newFollowup.followup_at) {
            setError('Please select a follow-up date and time.');
            return;
        }

        setIsSaving(true);
        setError(null);
        try {
            const customerServiceId = parseInt(serviceId, 10);
            const payload = {
                followup_at: newFollowup.followup_at,
                remarks: newFollowup.remarks?.trim() || null,
            };

            const response = hasOpenFollowup
                ? await updateCustomerServiceFollowup(customerServiceId, {
                    ...payload,
                    status: 'PENDING',
                })
                : await scheduleCustomerServiceFollowup(customerServiceId, payload);
            const createdFollowupId = response.data?.id ?? customerServiceId;

            setNewFollowup({ followup_at: '', remarks: '' });
            fetchFollowups();

            if (onFollowupCreated) onFollowupCreated();

            addNotification(
                'Follow-up Created',
                `New follow-up scheduled for ${localService?.service_name || 'Service'} (Service ID: ${serviceId}).`,
                'CREATE',
                {
                    label: 'View Lead',
                    path: `/dashboard?tab=dashboard&sub=followups&category=services&complete_task_id=${createdFollowupId ?? customerServiceId}`,
                },
            );

            window.dispatchEvent(new Event('st_followups_updated'));
        } catch (err) {
            console.error('Schedule error:', err);
            const errorData = err.response?.data?.detail;
            let errorMessage = 'Failed to schedule follow-up';

            if (typeof errorData === 'string') {
                errorMessage = errorData;
            } else if (Array.isArray(errorData)) {
                errorMessage = errorData.map((item) => item.msg).join(', ');
            } else if (errorData?.msg) {
                errorMessage = errorData.msg;
            } else {
                errorMessage = err.message || errorMessage;
            }

            setError(errorMessage);

            if (setToastMessage) {
                setToastMessage(`Error: ${errorMessage}`);
            }
        } finally {
            setIsSaving(false);
        }
    };

    const handleAssignRm = async (e) => {
        if (e) e.preventDefault();
        if (!selectedRmId) {
            setError('Please select an RM to assign.');
            return;
        }

        setIsAssigningRm(true);
        setError(null);
        try {
            const updated = await patchCustomerService(parseInt(serviceId, 10), {
                rm_id: Number(selectedRmId),
            });
            const selectedRm = activeRMs.find((rm) => String(rm.emp_id) === String(selectedRmId));
            const nextService = {
                ...localService,
                ...updated,
                rm_id: updated?.rm_id ?? Number(selectedRmId),
                rm_username: updated?.rm_username || selectedRm?.username || localService?.rm_username,
            };
            setLocalService(nextService);
            setSelectedRmId('');
            if (onServiceUpdated) onServiceUpdated(nextService);
            if (setToastMessage) {
                setToastMessage({ type: 'success', text: 'RM assigned successfully.' });
            }
        } catch (err) {
            const errorMessage = err.response?.data?.detail || err.message || 'Failed to assign RM';
            setError(typeof errorMessage === 'string' ? errorMessage : 'Failed to assign RM');
            if (setToastMessage) {
                setToastMessage({
                    type: 'error',
                    text: typeof errorMessage === 'string' ? errorMessage : 'Failed to assign RM',
                });
            }
        } finally {
            setIsAssigningRm(false);
        }
    };

    const formatDateTime = (dtStr) => {
        if (!dtStr) return '-';
        try {
            return new Date(dtStr).toLocaleString('en-IN', {
                day: '2-digit',
                month: 'short',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return dtStr;
        }
    };

    const rmOptions = optionsFromPairs(
        buildRmOpIdSelectOptions(activeRMs).map((opt) => ({ value: opt.value, label: opt.label })),
    );

    const resolvedRmLabel = useMemo(() => {
        if (localService?.rm_username) return localService.rm_username;
        if (rmUsername && rmUsername !== '-') return rmUsername;
        const rm = activeRMs.find((row) => String(row.emp_id) === String(localService?.rm_id));
        return rm?.username || 'Assigned RM';
    }, [localService, rmUsername, activeRMs]);

    const hasOpenFollowup = useMemo(
        () => hasOpenCustomerServiceFollowup(localService, followups),
        [localService, followups],
    );

    return (
        <div className="followup-manager-inlay">
            <div className="inlay-sections">
                <div className="history-column">
                    <div className="section-header">
                        <Clock size={14} />
                        <span>Follow-up History</span>
                    </div>

                    <div className="history-scroll">
                        {loading && followups.length === 0 ? (
                            <div className="inlay-loading-centered">
                                <Loader2 size={32} className="spin" />
                                <span>Syncing Follow-up History...</span>
                            </div>
                        ) : followups.length === 0 ? (
                            <div className="inlay-empty">
                                <MessageSquare size={32} />
                                <p>No follow-up history found for this service.</p>
                                <span>All previous interactions will appear here.</span>
                            </div>
                        ) : (
                            <div className="history-timeline">
                                {followups.map((f) => (
                                    <div key={f.id} className="timeline-item">
                                        <div className="timeline-marker" />
                                        <div className="timeline-content">
                                            <div className="item-top">
                                                <span className={`status-tag ${(f.status || f.followup_status || 'pending').toLowerCase()}`}>
                                                    {f.status || f.followup_status || 'PENDING'}
                                                </span>
                                                <span className="item-date">
                                                    <Clock size={10} />
                                                    {formatDateTime(f.followup_at)}
                                                </span>
                                            </div>
                                            <div className="item-remarks-v2">
                                                {f.remarks && f.remarks.includes('\n[COMPLETED]: ') ? (
                                                    <div className="remarks-split-inlay">
                                                        <div className="remark-sub-section">
                                                            <span className="remark-sub-label">Original Instruction</span>
                                                            <p className="actual-remark">{f.remarks.split('\n[COMPLETED]: ')[0]}</p>
                                                        </div>
                                                        <div className="remark-sub-section outcome">
                                                            <span className="remark-sub-label">Completion Outcome</span>
                                                            <p className="actual-remark">{f.remarks.split('\n[COMPLETED]: ')[1]}</p>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className="remark-simple">
                                                        <MessageSquare size={12} className="icon-muted" />
                                                        <p>{f.remarks === 'string' ? 'No remarks' : (f.remarks || 'No remarks')}</p>
                                                    </div>
                                                )}
                                            </div>
                                            {f.assigned_to_name && f.assigned_to_name !== 'string' && (
                                                <div className="item-assignee">
                                                    <User size={10} />
                                                    <span>{f.assigned_to_name}</span>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>

                <div className="create-column">
                    <div className="section-header">
                        {hasRmAssigned ? <Plus size={14} /> : <User size={14} />}
                        <span>{hasRmAssigned ? 'Schedule Follow-up' : 'Assign RM'}</span>
                    </div>

                    {localService?.status?.toLowerCase() === 'completed' ? (
                        <div className="inlay-status-notice">
                            <AlertCircle size={16} />
                            <p>This service is <strong>Completed</strong>. No further follow-ups can be scheduled.</p>
                        </div>
                    ) : !hasRmAssigned ? (
                        <>
                            {error && (
                                <div className="inlay-error">
                                    <AlertCircle size={14} />
                                    <span>{error}</span>
                                    <button type="button" onClick={() => setError(null)}>&times;</button>
                                </div>
                            )}

                            <div className="inlay-rm-notice">
                                <AlertCircle size={16} />
                                <p>An RM must be assigned to this service before you can schedule a follow-up.</p>
                            </div>

                            {isAdmin ? (
                                <form className="inlay-form" onSubmit={handleAssignRm}>
                                    <div className="form-field full">
                                        <label>Relationship Manager (RM)</label>
                                        <div className="input-with-icon">
                                            <User size={16} />
                                            <FormCustomSelect
                                                name="rm_id"
                                                value={selectedRmId}
                                                onChange={(e) => setSelectedRmId(e.target.value)}
                                                options={rmOptions}
                                                placeholder="Select RM..."
                                                ariaLabel="Relationship Manager"
                                            />
                                        </div>
                                    </div>

                                    <button
                                        type="submit"
                                        className="btn-schedule-inlay"
                                        disabled={isAssigningRm || !selectedRmId}
                                    >
                                        {isAssigningRm ? (
                                            <Loader2 size={18} className="spin" />
                                        ) : (
                                            <User size={18} />
                                        )}
                                        <span>{isAssigningRm ? 'Assigning...' : 'Assign RM'}</span>
                                    </button>
                                </form>
                            ) : (
                                <p className="inlay-rm-hint">Contact an admin to assign an RM for this service.</p>
                            )}
                        </>
                    ) : (
                        <>
                            {error && (
                                <div className="inlay-error">
                                    <AlertCircle size={14} />
                                    <span>{error}</span>
                                    <button type="button" onClick={() => setError(null)}>&times;</button>
                                </div>
                            )}

                            <div className="inlay-rm-assigned">
                                <User size={14} />
                                <span>RM: <strong>{resolvedRmLabel}</strong></span>
                            </div>

                            <form className="inlay-form" onSubmit={handleCreateFollowup}>
                                <div className="form-field full">
                                    <label>Date & Time</label>
                                    <ModernDateTimePicker
                                        value={newFollowup.followup_at}
                                        onChange={(val) => setNewFollowup({ ...newFollowup, followup_at: val })}
                                        placeholder="When to follow up?"
                                    />
                                </div>

                                <div className="form-field full">
                                    <label>Remarks / Notes <span className="field-optional">(optional)</span></label>
                                    <textarea
                                        placeholder="Details about this follow-up..."
                                        value={newFollowup.remarks}
                                        onChange={(e) => setNewFollowup({ ...newFollowup, remarks: e.target.value })}
                                    />
                                </div>

                                <button
                                    type="submit"
                                    className="btn-schedule-inlay"
                                    disabled={isSaving || !newFollowup.followup_at}
                                >
                                    {isSaving ? (
                                        <Loader2 size={18} className="spin" />
                                    ) : (
                                        <Send size={18} />
                                    )}
                                    <span>{isSaving ? 'Scheduling...' : 'Schedule Follow-up'}</span>
                                </button>
                            </form>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default FollowupManager;
