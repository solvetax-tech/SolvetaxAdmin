import { useEffect, useRef, useCallback } from 'react';
import { addNotification } from '../utils/notificationUtils';
import { listCustomerServiceFollowups, listPaymentFollowups } from '../utils/followupsApi';

const FIFTEEN_MIN_MS = 15 * 60 * 1000;
/** Max setTimeout ahead (24h); longer follow-ups are picked up on the next poll. */
const SCHEDULE_WINDOW_MS = 24 * 60 * 60 * 1000;

const alertKey = (category, id) => `${category}:${id}`;

const buildFollowupPath = (taskId, category) =>
    `/dashboard?tab=dashboard&sub=followups&category=${category}&complete_task_id=${taskId}`;

/**
 * Monitor upcoming service + payment follow-ups:
 * - 15 minutes before followup_at → upcoming toast
 * - At followup_at exactly → due-now toast (via setTimeout)
 */
const useFollowupReminders = (profileData) => {
    const alerted15mRef = useRef(new Set());
    const alertedDueRef = useRef(new Set());
    const scheduledTimeoutsRef = useRef(new Map());
    const checkIntervalRef = useRef(null);

    useEffect(() => {
        try {
            const saved15m = sessionStorage.getItem('st_alerted_15m');
            const savedDue = sessionStorage.getItem('st_alerted_due');
            if (saved15m) alerted15mRef.current = new Set(JSON.parse(saved15m));
            if (savedDue) alertedDueRef.current = new Set(JSON.parse(savedDue));
        } catch (err) {
            console.error('Failed to load alerted follow-ups:', err);
        }
    }, []);

    const clearAllScheduledTimeouts = useCallback(() => {
        scheduledTimeoutsRef.current.forEach((timeoutId) => clearTimeout(timeoutId));
        scheduledTimeoutsRef.current.clear();
    }, []);

    const getEntityLabel = useCallback((item, category) => {
        if (category === 'payments') {
            const typeMap = {
                GST_FILING: 'GST Filing Payment',
                GST_FILING_RETURN_DETAILS: 'GST Return Payment',
                CUSTOMER_SERVICE: 'Service Payment',
            };
            return {
                entityType: typeMap[item.entity_type] || 'Payment',
                entityId: item.id,
            };
        }

        const typeMap = {
            CUSTOMER_SERVICE: 'Customer Service',
            GST_PEOPLE: 'GST People',
            GST_DOCUMENTS: 'GST Documents',
        };
        return {
            entityType: typeMap[item.entity_type] || item.entity_type || 'Task',
            entityId: item.entity_id || item.customer_service_id || item.id,
        };
    }, []);

    const getUpcomingDescription = useCallback((item, timeStr, category) => {
        const { entityType, entityId } = getEntityLabel(item, category);
        return `${entityType} with ID ${entityId} followup is scheduled at ${timeStr}`;
    }, [getEntityLabel]);

    const getDueNowDescription = useCallback((item, timeStr, category) => {
        const { entityType, entityId } = getEntityLabel(item, category);
        return `${entityType} with ID ${entityId} follow-up is due now at ${timeStr}`;
    }, [getEntityLabel]);

    const saveAlertedIds = useCallback(() => {
        try {
            sessionStorage.setItem('st_alerted_15m', JSON.stringify(Array.from(alerted15mRef.current)));
            sessionStorage.setItem('st_alerted_due', JSON.stringify(Array.from(alertedDueRef.current)));
        } catch (err) {
            console.error('Failed to save alerted follow-ups:', err);
        }
    }, []);

    const isAssignedToUser = useCallback((item, empId, isAdmin) => {
        if (isAdmin) return true;
        return (
            item.rm_id === empId ||
            item.op_id === empId ||
            item.assigned_to === empId
        );
    }, []);

    const processFollowups = useCallback((items, category, now, profile) => {
        const empId = profile.emp_id;
        const isAdmin = profile.role?.toUpperCase() === 'ADMIN';

        (items || []).forEach((item) => {
            if (!item?.followup_at || !item?.id) return;
            if (!isAssignedToUser(item, empId, isAdmin)) return;

            const key = alertKey(category, item.id);
            const followupTime = new Date(item.followup_at);
            const timeDiff = followupTime.getTime() - now.getTime();
            const timeStr = followupTime.toLocaleTimeString('en-IN', {
                hour: '2-digit',
                minute: '2-digit',
            });

            if (timeDiff <= 0) return;

            if (timeDiff <= FIFTEEN_MIN_MS && !alerted15mRef.current.has(key)) {
                const alertDesc = getUpcomingDescription(item, timeStr, category);
                addNotification('Upcoming Follow-up', alertDesc, 'SYSTEM', {
                    label: 'Complete Now',
                    path: buildFollowupPath(item.id, category),
                });
                window.dispatchEvent(new CustomEvent('st_show_toast', {
                    detail: {
                        message: alertDesc,
                        action: {
                            label: 'Complete Now',
                            taskId: item.id,
                            category,
                        },
                    },
                }));
                alerted15mRef.current.add(key);
                saveAlertedIds();
            }

            if (!alertedDueRef.current.has(key) && timeDiff <= SCHEDULE_WINDOW_MS) {
                const tId = setTimeout(() => {
                    if (alertedDueRef.current.has(key)) return;

                    const message = getDueNowDescription(item, timeStr, category);
                    addNotification('Follow-up Due Now', message, 'SYSTEM', {
                        label: 'Complete Now',
                        path: buildFollowupPath(item.id, category),
                    });
                    window.dispatchEvent(new CustomEvent('st_show_toast', {
                        detail: {
                            message: `DUE NOW: ${message}`,
                            action: {
                                label: 'Complete Now',
                                taskId: item.id,
                                category,
                            },
                            variant: 'urgent',
                        },
                    }));
                    alertedDueRef.current.add(key);
                    saveAlertedIds();
                }, timeDiff);
                scheduledTimeoutsRef.current.set(key, tId);
            }
        });
    }, [getUpcomingDescription, getDueNowDescription, isAssignedToUser, saveAlertedIds]);

    const checkUpcomingFollowups = useCallback(async () => {
        if (!profileData?.emp_id) return;

        try {
            const now = new Date();
            const startOfToday = new Date(now);
            startOfToday.setHours(0, 0, 0, 0);
            startOfToday.setHours(startOfToday.getHours() - 6);

            const endOfToday = new Date(now);
            endOfToday.setHours(23, 59, 59, 999);
            endOfToday.setHours(endOfToday.getHours() + 12);

            const listParams = {
                followup_from: startOfToday.toISOString(),
                followup_to: endOfToday.toISOString(),
                statuses: ['PENDING'],
                limit: 100,
            };

            clearAllScheduledTimeouts();

            const [serviceRes, paymentRes] = await Promise.all([
                listCustomerServiceFollowups(listParams),
                listPaymentFollowups(listParams),
            ]);

            processFollowups(serviceRes.data?.data || [], 'services', now, profileData);
            processFollowups(paymentRes.data?.data || [], 'payments', now, profileData);
        } catch (err) {
            console.error('Failed to fetch follow-up reminders:', err);
        }
    }, [profileData, clearAllScheduledTimeouts, processFollowups]);

    useEffect(() => {
        if (!profileData?.emp_id) return;

        checkUpcomingFollowups();
        checkIntervalRef.current = setInterval(checkUpcomingFollowups, 60000);
        window.addEventListener('st_followups_updated', checkUpcomingFollowups);

        return () => {
            if (checkIntervalRef.current) {
                clearInterval(checkIntervalRef.current);
            }
            clearAllScheduledTimeouts();
            window.removeEventListener('st_followups_updated', checkUpcomingFollowups);
        };
    }, [profileData, checkUpcomingFollowups, clearAllScheduledTimeouts]);
};

export default useFollowupReminders;
