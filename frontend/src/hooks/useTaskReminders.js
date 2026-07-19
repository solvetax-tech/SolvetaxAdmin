import { useEffect, useRef, useCallback } from 'react';
import { addNotification } from '../utils/notificationUtils';
import { listTasks, toDateInput } from '../utils/employeeTasksApi';

const TEN_MIN_MS = 10 * 60 * 1000;
/** Max setTimeout ahead (24h); anything further is caught on the next poll. */
const SCHEDULE_WINDOW_MS = 24 * 60 * 60 * 1000;
const TASK_PATH = '/dashboard?tab=dashboard&sub=today-tasks';

const timeStr = (d) => d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

/**
 * Personal task reminders, mirroring useFollowupReminders:
 *  - 10 minutes before scheduled_at → "starting soon" toast + notification
 *  - exactly at followup_at → "follow-up due now" toast (via setTimeout)
 * De-duped in sessionStorage so a reminder fires once per session.
 */
const useTaskReminders = (profileData) => {
    const alerted10mRef = useRef(new Set());
    const alertedFollowupRef = useRef(new Set());
    const timeoutsRef = useRef(new Map());
    const intervalRef = useRef(null);

    useEffect(() => {
        try {
            const a = sessionStorage.getItem('st_task_alerted_10m');
            const b = sessionStorage.getItem('st_task_alerted_fu');
            if (a) alerted10mRef.current = new Set(JSON.parse(a));
            if (b) alertedFollowupRef.current = new Set(JSON.parse(b));
        } catch { /* ignore */ }
    }, []);

    const persist = useCallback(() => {
        try {
            sessionStorage.setItem('st_task_alerted_10m', JSON.stringify([...alerted10mRef.current]));
            sessionStorage.setItem('st_task_alerted_fu', JSON.stringify([...alertedFollowupRef.current]));
        } catch { /* ignore */ }
    }, []);

    const clearTimeouts = useCallback(() => {
        timeoutsRef.current.forEach((id) => clearTimeout(id));
        timeoutsRef.current.clear();
    }, []);

    const process = useCallback((tasks, now) => {
        (tasks || []).forEach((t) => {
            if (!t?.id || t.status === 'DONE' || t.status === 'CANCELLED') return;

            // 10 minutes before the task.
            if (t.scheduled_at) {
                const start = new Date(t.scheduled_at);
                const diff = start.getTime() - now.getTime();
                const key = `t10:${t.id}`;
                if (diff > 0 && diff <= TEN_MIN_MS && !alerted10mRef.current.has(key)) {
                    const msg = `Task "${t.title}" starts at ${timeStr(start)}`;
                    addNotification('Task starting soon', msg, 'SYSTEM', { label: 'Open tasks', path: TASK_PATH });
                    window.dispatchEvent(new CustomEvent('st_show_toast', { detail: { message: msg } }));
                    alerted10mRef.current.add(key);
                    persist();
                }
            }

            // Exactly at follow-up time.
            if (t.followup_at) {
                const fu = new Date(t.followup_at);
                const diff = fu.getTime() - now.getTime();
                const key = `tfu:${t.id}`;
                if (diff > 0 && diff <= SCHEDULE_WINDOW_MS && !alertedFollowupRef.current.has(key)) {
                    const id = setTimeout(() => {
                        if (alertedFollowupRef.current.has(key)) return;
                        const msg = `Follow-up for "${t.title}" is due now`;
                        addNotification('Task follow-up due', msg, 'SYSTEM', { label: 'Open tasks', path: TASK_PATH });
                        window.dispatchEvent(new CustomEvent('st_show_toast', { detail: { message: `DUE NOW: ${msg}`, variant: 'urgent' } }));
                        alertedFollowupRef.current.add(key);
                        persist();
                    }, diff);
                    timeoutsRef.current.set(key, id);
                }
            }
        });
    }, [persist]);

    const check = useCallback(async () => {
        if (!profileData?.emp_id) return;
        try {
            clearTimeouts();
            const { data } = await listTasks(toDateInput(new Date()));
            process(data, new Date());
        } catch { /* transient; next poll retries */ }
    }, [profileData, clearTimeouts, process]);

    useEffect(() => {
        if (!profileData?.emp_id) return undefined;
        check();
        intervalRef.current = setInterval(check, 60000);
        window.addEventListener('st_tasks_updated', check);
        return () => {
            if (intervalRef.current) clearInterval(intervalRef.current);
            clearTimeouts();
            window.removeEventListener('st_tasks_updated', check);
        };
    }, [profileData, check, clearTimeouts]);
};

export default useTaskReminders;
