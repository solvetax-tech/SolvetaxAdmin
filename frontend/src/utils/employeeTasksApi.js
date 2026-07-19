import api from './api';

export const TASKS_BASE = '/api/v1/employee-tasks';

export const TASK_STATUSES = ['PENDING', 'IN_PROGRESS', 'DONE', 'CANCELLED'];
export const TASK_SLOT_MINUTES = 15;

export const TASK_STATUS_LABEL = {
    PENDING: 'Pending', IN_PROGRESS: 'In Progress', DONE: 'Done', CANCELLED: 'Cancelled',
};

/** GET /list?date=YYYY-MM-DD — the caller's tasks for that IST day. */
export async function listTasks(date, config = {}) {
    const params = {};
    if (date) params.date = date;
    const res = await api.get(`${TASKS_BASE}/list`, { params, ...config });
    const body = res.data || {};
    return { data: Array.isArray(body.data) ? body.data : [], count: body.count || 0, date: body.date };
}

/** GET /available-slots?date=&exclude_task_id= — 96 free/taken 15-min slots. */
export async function getAvailableSlots(date, excludeTaskId, config = {}) {
    const params = {};
    if (date) params.date = date;
    if (excludeTaskId) params.exclude_task_id = excludeTaskId;
    const res = await api.get(`${TASKS_BASE}/available-slots`, { params, ...config });
    return res.data || { slots: [] };
}

/** POST /create */
export async function createTask(body) {
    const res = await api.post(`${TASKS_BASE}/create`, body);
    return res.data;
}

/** PATCH /{id} — edit or reschedule. */
export async function patchTask(taskId, body) {
    const res = await api.patch(`${TASKS_BASE}/${taskId}`, body);
    return res.data;
}

/** DELETE /{id} — soft delete. */
export async function deleteTask(taskId) {
    const res = await api.delete(`${TASKS_BASE}/${taskId}`);
    return res.data;
}

/** Local YYYY-MM-DD for a Date (IST is the app's zone; the browser is in IST). */
export function toDateInput(d = new Date()) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}
