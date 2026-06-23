import { useEffect, useRef, useCallback } from 'react';
import { addNotification } from '../utils/notificationUtils';
import { buildGstFilingFocusPath, fetchGstFilingFollowupAlerts } from '../utils/dashboardApi';

const TEN_MIN_MS = 10 * 60 * 1000;
const PAST_DUE_CATCHUP_MS = 15 * 60 * 1000;
const SCHEDULE_WINDOW_MS = 48 * 60 * 60 * 1000;
const POLL_MS = 30000;
const buildGstFocusAction = (item) => {
    const path = buildGstFilingFocusPath({
        customerId: item.customer_id,
        returnDetailId: item.return_detail_id,
        formKey: item.form_key,
        period: item.period,
    });
    return {
        label: 'Open GST Filings',
        path,
        gstFocus: {
            customerId: item.customer_id,
            returnDetailId: item.return_detail_id,
            formKey: item.form_key,
            period: item.period,
        },
    };
};

const alertKey = (returnDetailId, formKey, followupAt) =>
    `gst_filings:${returnDetailId}:${formKey}:${followupAt}`;

const alertKeyPrefix = (returnDetailId, formKey) =>
    `gst_filings:${returnDetailId}:${formKey}:`;

const canViewFollowup = (item, empId, role) => {
    const normalizedRole = String(role || '').toUpperCase();
    if (normalizedRole === 'ADMIN' || normalizedRole === 'SPECIAL') return true;
    const eid = Number(empId);
    if (!Number.isFinite(eid)) return false;
    return Number(item.rm_id) === eid || Number(item.op_id) === eid;
};

/**
 * GST return-detail follow-up reminders (GST Filings dashboard only).
 * Poll + setTimeout: 10 minutes before and at followup_at.
 */
const useGstFilingFollowupReminders = (profileData) => {
    const alerted10mRef = useRef(new Set());
    const alertedDueRef = useRef(new Set());
    const scheduledTimeoutsRef = useRef(new Map());
    const checkIntervalRef = useRef(null);

    const saveAlertedIds = useCallback(() => {
        try {
            sessionStorage.setItem(
                'st_gst_filings_alerted_10m',
                JSON.stringify(Array.from(alerted10mRef.current)),
            );
            sessionStorage.setItem(
                'st_gst_filings_alerted_due',
                JSON.stringify(Array.from(alertedDueRef.current)),
            );
        } catch (err) {
            console.error('Failed to save GST filing alerted follow-ups:', err);
        }
    }, []);

    const clearAlertKeysForForm = useCallback((returnDetailId, formKey) => {
        if (!returnDetailId || !formKey) return;
        const prefix = alertKeyPrefix(returnDetailId, formKey);
        const filterSet = (setRef) => {
            setRef.current = new Set(
                [...setRef.current].filter((key) => !String(key).startsWith(prefix)),
            );
        };
        filterSet(alerted10mRef);
        filterSet(alertedDueRef);
        [...scheduledTimeoutsRef.current.keys()]
            .filter((k) => k.startsWith(prefix))
            .forEach((k) => {
                clearTimeout(scheduledTimeoutsRef.current.get(k));
                scheduledTimeoutsRef.current.delete(k);
            });
        saveAlertedIds();
    }, [saveAlertedIds]);

    useEffect(() => {
        try {
            const saved10m = sessionStorage.getItem('st_gst_filings_alerted_10m');
            const savedDue = sessionStorage.getItem('st_gst_filings_alerted_due');
            if (saved10m) alerted10mRef.current = new Set(JSON.parse(saved10m));
            if (savedDue) alertedDueRef.current = new Set(JSON.parse(savedDue));
        } catch (err) {
            console.error('Failed to load GST filing alerted follow-ups:', err);
        }
    }, []);

    const clearAllScheduledTimeouts = useCallback(() => {
        scheduledTimeoutsRef.current.forEach((timeoutId) => clearTimeout(timeoutId));
        scheduledTimeoutsRef.current.clear();
    }, []);

    const notifyUpcoming = useCallback((message, item) => {
        const action = buildGstFocusAction(item);
        addNotification('GST Filing Follow-up (10m)', message, 'SYSTEM', action, 'GST_FILINGS');
        window.dispatchEvent(new CustomEvent('st_show_toast', {
            detail: {
                message,
                action,
            },
        }));
    }, []);

    const notifyDueNow = useCallback((message, item) => {
        const action = buildGstFocusAction(item);
        addNotification('GST Filing Follow-up Due', message, 'SYSTEM', action, 'GST_FILINGS');
        window.dispatchEvent(new CustomEvent('st_show_toast', {
            detail: {
                message: `DUE NOW: ${message}`,
                action,
                variant: 'urgent',
            },
        }));
    }, []);

    const scheduleTimeout = useCallback((mapKey, delayMs, callback) => {
        if (delayMs <= 0 || delayMs > SCHEDULE_WINDOW_MS) return;
        const existing = scheduledTimeoutsRef.current.get(mapKey);
        if (existing) clearTimeout(existing);
        const tId = setTimeout(callback, delayMs);
        scheduledTimeoutsRef.current.set(mapKey, tId);
    }, []);

    const processGstFilingFollowups = useCallback((items, now, profile) => {
        const empId = profile.emp_id;
        const role = profile.role;

        clearAllScheduledTimeouts();

        (items || []).forEach((item) => {
            if (!item?.followup_at || !item?.return_detail_id || !item?.form_key) return;
            if (!canViewFollowup(item, empId, role)) return;

            const key = alertKey(item.return_detail_id, item.form_key, item.followup_at);
            const prefix = alertKeyPrefix(item.return_detail_id, item.form_key);
            const followupTime = new Date(item.followup_at);
            if (Number.isNaN(followupTime.getTime())) return;

            const timeDiff = followupTime.getTime() - now.getTime();
            const timeStr = followupTime.toLocaleTimeString('en-IN', {
                hour: '2-digit',
                minute: '2-digit',
            });
            const label = item.form_label || item.form_key;
            const who = item.display_name || item.gstin || `Customer ${item.customer_id}`;
            const upcomingDesc = `${label} follow-up for ${who} is scheduled at ${timeStr}`;
            const dueDesc = `${label} follow-up for ${who} is due now at ${timeStr}`;
            const pastDueDesc = `${label} follow-up for ${who} was due at ${timeStr}`;

            if (timeDiff > SCHEDULE_WINDOW_MS) return;

            // Poll-based: within 10 minutes before (works when tab is backgrounded)
            if (timeDiff > 0 && timeDiff <= TEN_MIN_MS && !alerted10mRef.current.has(key)) {
                notifyUpcoming(upcomingDesc, item);
                alerted10mRef.current.add(key);
                saveAlertedIds();
            }

            // Poll-based: due now or recently missed (catch-up on refresh/poll)
            if (timeDiff <= 0 && timeDiff >= -PAST_DUE_CATCHUP_MS && !alertedDueRef.current.has(key)) {
                notifyDueNow(timeDiff >= -2 * 60 * 1000 ? dueDesc : pastDueDesc, item);
                alertedDueRef.current.add(key);
                saveAlertedIds();
            }

            // setTimeout backup for exact timing when tab is active
            const timeTo10m = timeDiff - TEN_MIN_MS;
            if (timeDiff > TEN_MIN_MS && !alerted10mRef.current.has(key)) {
                scheduleTimeout(`${prefix}10m`, timeTo10m, () => {
                    if (alerted10mRef.current.has(key)) return;
                    notifyUpcoming(upcomingDesc, item);
                    alerted10mRef.current.add(key);
                    saveAlertedIds();
                });
            }

            if (timeDiff > 0 && !alertedDueRef.current.has(key)) {
                scheduleTimeout(`${prefix}due`, timeDiff, () => {
                    if (alertedDueRef.current.has(key)) return;
                    notifyDueNow(dueDesc, item);
                    alertedDueRef.current.add(key);
                    saveAlertedIds();
                });
            }
        });
    }, [
        clearAllScheduledTimeouts,
        notifyDueNow,
        notifyUpcoming,
        saveAlertedIds,
        scheduleTimeout,
    ]);

    const checkGstFilingFollowups = useCallback(async () => {
        if (!profileData?.emp_id) return;

        try {
            const now = new Date();
            const start = new Date(now.getTime() - 6 * 60 * 60 * 1000);
            const end = new Date(now.getTime() + SCHEDULE_WINDOW_MS);

            const gstRes = await fetchGstFilingFollowupAlerts({
                followup_from: start.toISOString(),
                followup_to: end.toISOString(),
                limit: 200,
            });

            processGstFilingFollowups(gstRes?.data || [], now, profileData);
        } catch (err) {
            console.error('Failed to fetch GST filing follow-up reminders:', err);
        }
    }, [profileData, processGstFilingFollowups]);

    useEffect(() => {
        if (!profileData?.emp_id) return;

        const handleFollowupUpdated = (event) => {
            const { returnDetailId, formKey } = event?.detail || {};
            clearAlertKeysForForm(returnDetailId, formKey);
            checkGstFilingFollowups();
        };

        checkGstFilingFollowups();
        checkIntervalRef.current = setInterval(checkGstFilingFollowups, POLL_MS);
        window.addEventListener('st_gst_followups_updated', handleFollowupUpdated);

        return () => {
            if (checkIntervalRef.current) clearInterval(checkIntervalRef.current);
            clearAllScheduledTimeouts();
            window.removeEventListener('st_gst_followups_updated', handleFollowupUpdated);
        };
    }, [
        profileData,
        checkGstFilingFollowups,
        clearAllScheduledTimeouts,
        clearAlertKeysForForm,
    ]);
};

export default useGstFilingFollowupReminders;
