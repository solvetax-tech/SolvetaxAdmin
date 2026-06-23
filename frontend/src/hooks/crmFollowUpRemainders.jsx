import { useEffect, useRef, useCallback } from 'react';
import api from '../utils/api';
import { unwrapListPayload } from '../utils/apiResponse';
import { canViewCrmLead, isCrmFollowupLead, resolveLeadAlertStatus } from '../utils/crmLeadsAlerts';
import { normalizeFollowupStatusFields } from '../utils/followupsApi';
import { getCrmLeadsApiBase } from '../utils/crmLeadApi';

/**
 * Isolated CRM notification helper.
 * Writes to a separate key and dispatches a separate event to ensure 100% isolation from the main website.
 */
const addCrmNotification = (title, description, type = 'INFO', action = null, entityType = 'GST_REGISTRATION') => {
    try {
        const newNotif = {
            id: Date.now(),
            title,
            description,
            type,
            action,
            context: 'CRM',
            entityType,
            timestamp: new Date().toISOString(),
        };
        const existing = JSON.parse(localStorage.getItem('st_crm_notifications') || '[]');
        localStorage.setItem('st_crm_notifications', JSON.stringify([newNotif, ...existing]));
        // Dispatched a CRM-specific event
        window.dispatchEvent(new Event('st_crm_notifications_updated'));
        return newNotif;
    } catch (err) {
        console.error('Failed to add CRM notification:', err);
        return null;
    }
};

/**
 * CRM-specific hook to monitor upcoming lead follow-ups and trigger alerts 15 minutes before they are due.
 */
const useCrmFollowupReminders = (profileData, setToastMessage, entityType = 'GST_REGISTRATION') => {
    const alerted15mRef = useRef(new Set());
    const alertedDueRef = useRef(new Set());
    const scheduledTimeoutsRef = useRef(new Map());
    const checkIntervalRef = useRef(null);

    // Persist alerted IDs in session so they don't re-trigger on refresh
    useEffect(() => {
        try {
            const saved15m = sessionStorage.getItem('st_crm_alerted_15m');
            const savedDue = sessionStorage.getItem('st_crm_alerted_due');
            if (saved15m) alerted15mRef.current = new Set(JSON.parse(saved15m));
            if (savedDue) alertedDueRef.current = new Set(JSON.parse(savedDue));
        } catch (err) {
            console.error('Failed to load CRM alerted follow-ups:', err);
        }
    }, []);

    const saveAlertedIds = useCallback(() => {
        try {
            sessionStorage.setItem('st_crm_alerted_15m', JSON.stringify(Array.from(alerted15mRef.current)));
            sessionStorage.setItem('st_crm_alerted_due', JSON.stringify(Array.from(alertedDueRef.current)));
        } catch (err) {
            console.error('Failed to save CRM alerted follow-ups:', err);
        }
    }, []);

    const clearAllScheduledTimeouts = useCallback(() => {
        scheduledTimeoutsRef.current.forEach((timeoutId) => clearTimeout(timeoutId));
        scheduledTimeoutsRef.current.clear();
    }, []);

    const getCrmDescription = useCallback((item, timeDiff, timeStr) => {
        const entityId = item.id;
        const timing = timeDiff > 0 ? 'is scheduled' : 'was due';
        const mainText = `CRM Lead with ID ${entityId}`;
        const detailText = item.mobile ? ` (Mobile: ${item.mobile})` : '';
        return `${mainText}${detailText} followup ${timing} at ${timeStr}`;
    }, []);

    const checkCrmFollowups = useCallback(async () => {
        if (!profileData?.emp_id) return;

        try {
            const now = new Date();
            const startOfToday = new Date(now);
            startOfToday.setHours(0, 0, 0, 0);
            startOfToday.setHours(startOfToday.getHours() - 6);

            const endOfToday = new Date(now);
            endOfToday.setHours(23, 59, 59, 999);
            endOfToday.setHours(endOfToday.getHours() + 12); 

            const entityTypeNorm = (entityType || '').trim().toUpperCase();
            const params = {
                followup_at_from: startOfToday.toISOString(),
                followup_at_to: endOfToday.toISOString(),
                entity_type: entityTypeNorm,
                limit: 100,
                is_active: true,
            };

            const response = await api.get(`${getCrmLeadsApiBase(entityTypeNorm)}/filter`, { params });
            const { items: rawItems } = unwrapListPayload(response);
            const items = rawItems
                .filter((item) => canViewCrmLead(profileData, item))
                .filter((item) => isCrmFollowupLead(item))
                .map(item => ({
                ...item, 
                sourceType: 'CRM',
                entity_type: 'CRM_LEAD'
            }));
            
            const fifteenMinutesInMs = 15 * 60 * 1000;
            const twoMinutesAgoInMs = -2 * 60 * 1000; 

            clearAllScheduledTimeouts();

            items.forEach(item => {
                const alertStatus = resolveLeadAlertStatus(item);
                if (!alertStatus) return;

                const followupTime = new Date(item.followup_at);
                const timeDiff = followupTime.getTime() - now.getTime();
                const timeStr = followupTime.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

                // --- Precision Alert Engine ---
                const alertDesc = getCrmDescription(item, timeDiff, timeStr);
                const targetPath = `/crm-dashboard?tab=leads&target_lead_id=${item.id}&target_view=history&entity_type=${entityTypeNorm}`;

                const followupMetrics = normalizeFollowupStatusFields(item);

                // CASE 1: LEAD IS ALREADY DUE OR MISSED (Immediate)
                if (
                    timeDiff <= 0
                    && (followupMetrics.isMissedOpen || followupMetrics.isOverduePending || followupMetrics.inUrgentWindow)
                ) {
                    if (timeDiff >= twoMinutesAgoInMs && !alertedDueRef.current.has(item.id)) {
                        addCrmNotification('Follow-up Due Now', alertDesc, 'SYSTEM', { label: 'Complete Now', path: targetPath }, entityTypeNorm);
                        window.dispatchEvent(new CustomEvent('st_show_toast', {
                            detail: { 
                                message: alertDesc, 
                                action: { label: 'Complete Now', path: targetPath, taskId: item.id }, 
                                variant: 'urgent' 
                            }
                        }));
                        alertedDueRef.current.add(item.id);
                        saveAlertedIds();
                    }
                    return;
                }

                // CASE 2: LEAD IS DUE SOON (Within 30m window)
                if (timeDiff <= (30 * 60 * 1000)) {
                    
                    // A. Trigger/Schedule 15-Minute Warning
                    const timeTo15m = timeDiff - fifteenMinutesInMs;
                    
                    if (timeTo15m <= 0) {
                        // Already in the 15m window - Trigger Immediate UPCOMING if not alerted
                        if (!alerted15mRef.current.has(item.id)) {
                            addCrmNotification('Upcoming Follow-up (15m)', alertDesc, 'SYSTEM', { label: 'Complete Now', path: targetPath }, entityTypeNorm);
                            window.dispatchEvent(new CustomEvent('st_show_toast', {
                                detail: { message: `UPCOMING: ${alertDesc}`, action: { label: 'Complete Now', path: targetPath, taskId: item.id } }
                            }));
                            alerted15mRef.current.add(item.id);
                            saveAlertedIds();
                        }
                    } else {
                        // Schedule precise 15m warning
                        const t15 = setTimeout(() => {
                            addCrmNotification('Upcoming Follow-up (15m)', alertDesc, 'SYSTEM', { label: 'Complete Now', path: targetPath }, entityTypeNorm);
                            window.dispatchEvent(new CustomEvent('st_show_toast', {
                                detail: { message: `UPCOMING: ${alertDesc}`, action: { label: 'Complete Now', path: targetPath, taskId: item.id } }
                            }));
                            alerted15mRef.current.add(item.id);
                            saveAlertedIds();
                        }, timeTo15m);
                        scheduledTimeoutsRef.current.set(`${item.id}_15m`, t15);
                    }

                    // B. Schedule precise "Due Now" Alert
                    const tDue = setTimeout(() => {
                        const descriptiveMessage = getCrmDescription(item, 0, timeStr);
                        addCrmNotification('Follow-up Due Now', descriptiveMessage, 'SYSTEM', { 
                            label: 'Complete Now', 
                            path: targetPath 
                        }, entityTypeNorm);

                        window.dispatchEvent(new CustomEvent('st_show_toast', {
                            detail: { 
                                message: `DUE NOW: ${descriptiveMessage}`, 
                                action: { label: 'Complete Now', path: targetPath, taskId: item.id }, 
                                variant: 'urgent' 
                            }
                        }));
                        alertedDueRef.current.add(item.id);
                        saveAlertedIds();
                    }, timeDiff);
                    scheduledTimeoutsRef.current.set(`${item.id}_due`, tDue);
                }
            });
        } catch (err) {
            console.error('Failed to fetch CRM reminders:', err);
        }
    }, [profileData, entityType, saveAlertedIds, clearAllScheduledTimeouts, getCrmDescription]);

    useEffect(() => {
        if (!profileData?.emp_id) return undefined;
        checkCrmFollowups();
        checkIntervalRef.current = setInterval(checkCrmFollowups, 60000);
        window.addEventListener('st_followups_updated', checkCrmFollowups);

        return () => {
            if (checkIntervalRef.current) clearInterval(checkIntervalRef.current);
            clearAllScheduledTimeouts();
            window.removeEventListener('st_followups_updated', checkCrmFollowups);
        };
    }, [profileData, entityType, checkCrmFollowups, clearAllScheduledTimeouts]);
};

export default useCrmFollowupReminders;
