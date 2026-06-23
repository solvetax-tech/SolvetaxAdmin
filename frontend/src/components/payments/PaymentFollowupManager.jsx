/**
 * Follow-up history and scheduling for payment collection follow-ups.
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
    listPaymentFollowups,
    schedulePaymentFollowup,
    updatePaymentFollowup,
    hasOpenPaymentFollowup,
} from '../../utils/followupsApi';
import '../customers/FollowupManager.css';
import ModernDateTimePicker from '../common/ModernDateTimePicker';
import { addNotification } from '../../utils/notificationUtils';

const PaymentFollowupManager = ({
    paymentId,
    paymentData,
    rmUsername,
    onFollowupCreated,
}) => {
    const [localPayment, setLocalPayment] = useState(paymentData);
    const [followups, setFollowups] = useState([]);
    const [loading, setLoading] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState(null);
    const [newFollowup, setNewFollowup] = useState({
        followup_at: '',
        remarks: '',
    });

    useEffect(() => {
        setLocalPayment(paymentData);
    }, [paymentData]);

    const fetchFollowups = useCallback(async () => {
        if (!paymentId) return;
        setLoading(true);
        try {
            const response = await listPaymentFollowups({
                payment_id: parseInt(paymentId, 10),
            });
            setFollowups(response.data.data || []);
        } catch (err) {
            console.error('Failed to fetch payment follow-ups:', err);
        } finally {
            setLoading(false);
        }
    }, [paymentId]);

    useEffect(() => {
        fetchFollowups();
    }, [fetchFollowups]);

    const hasOpenFollowup = useMemo(
        () => hasOpenPaymentFollowup(localPayment, followups),
        [localPayment, followups],
    );

    const handleCreateFollowup = async (e) => {
        if (e) e.preventDefault();

        if (!newFollowup.followup_at) {
            setError('Please select a follow-up date and time.');
            return;
        }

        setIsSaving(true);
        setError(null);
        try {
            const pid = parseInt(paymentId, 10);
            const payload = {
                followup_at: newFollowup.followup_at,
                remarks: newFollowup.remarks?.trim() || null,
            };

            const response = hasOpenFollowup
                ? await updatePaymentFollowup(pid, { ...payload, status: 'PENDING' })
                : await schedulePaymentFollowup({
                    payment_id: pid,
                    ...payload,
                });

            const createdFollowupId = response.data?.id ?? pid;

            setNewFollowup({ followup_at: '', remarks: '' });
            await fetchFollowups();
            window.dispatchEvent(new Event('st_followups_updated'));

            if (onFollowupCreated) onFollowupCreated();

            addNotification(
                'Payment Follow-up Created',
                `New payment follow-up scheduled for Payment ID ${pid}.`,
                'CREATE',
                {
                    label: 'View Lead',
                    path: `/dashboard?tab=dashboard&sub=followups&category=payments&complete_task_id=${createdFollowupId ?? pid}`,
                },
            );

            window.dispatchEvent(new Event('st_followups_updated'));
        } catch (err) {
            console.error('Schedule payment follow-up error:', err);
            const errorData = err.response?.data?.detail;
            let errorMessage = 'Failed to schedule payment follow-up';

            if (typeof errorData === 'string') {
                errorMessage = errorData;
            } else if (Array.isArray(errorData)) {
                errorMessage = errorData.map((item) => item.msg).join(', ');
            } else if (errorData?.msg) {
                errorMessage = errorData.msg;
            } else if (errorData?.error?.message) {
                errorMessage = errorData.error.message;
            } else {
                errorMessage = err.message || errorMessage;
            }

            setError(errorMessage);
        } finally {
            setIsSaving(false);
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

    const resolvedRmLabel = rmUsername && rmUsername !== '-' ? rmUsername : null;

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
                                <p>No follow-up history found for this payment.</p>
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
                        <Plus size={14} />
                        <span>Schedule Follow-up</span>
                    </div>

                    {error && (
                        <div className="inlay-error">
                            <AlertCircle size={14} />
                            <span>{error}</span>
                            <button type="button" onClick={() => setError(null)}>&times;</button>
                        </div>
                    )}

                    {resolvedRmLabel && (
                        <div className="inlay-rm-assigned">
                            <User size={14} />
                            <span>RM: <strong>{resolvedRmLabel}</strong></span>
                        </div>
                    )}

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
                </div>
            </div>
        </div>
    );
};

export default PaymentFollowupManager;
