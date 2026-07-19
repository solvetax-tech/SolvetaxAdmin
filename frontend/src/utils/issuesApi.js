import api from './api';

export const ISSUES_BASE = '/api/v1/issue-reports';

export const ISSUE_PRIORITIES = ['LOW', 'MEDIUM', 'HIGH', 'URGENT'];
export const ISSUE_STATUSES = ['OPEN', 'IN_PROGRESS', 'RESOLVED'];

/** GET /api/v1/issue-reports/list — role-scoped by the backend. */
export async function listIssues(params = {}, config = {}) {
    const response = await api.get(`${ISSUES_BASE}/list`, { params, ...config });
    const body = response.data || {};
    return {
        data: Array.isArray(body.data) ? body.data : [],
        total: Number(body.total) || 0,
        count: Number(body.count) || 0,
        limit: Number(body.limit) || 0,
        offset: Number(body.offset) || 0,
    };
}

/** POST /api/v1/issue-reports/create */
export async function createIssue(body) {
    const response = await api.post(`${ISSUES_BASE}/create`, body);
    return response.data;
}

/** PATCH /api/v1/issue-reports/{id} — update status / priority / resolution note. */
export async function patchIssue(issueId, body) {
    const response = await api.patch(`${ISSUES_BASE}/${issueId}`, body);
    return response.data;
}

/** POST /api/v1/issue-reports/photo/upload — multipart; returns { blob_url }. */
export async function uploadIssuePhoto(file) {
    const form = new FormData();
    form.append('file', file);
    const response = await api.post(`${ISSUES_BASE}/photo/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data?.blob_url;
}

/** GET /api/v1/issue-reports/photo/view — mints a short-lived readable URL. */
export async function viewIssuePhoto(blobUrl) {
    const response = await api.get(`${ISSUES_BASE}/photo/view`, { params: { blob_url: blobUrl } });
    return response.data?.url;
}

export const PRIORITY_LABEL = {
    LOW: 'Low', MEDIUM: 'Medium', HIGH: 'High', URGENT: 'Urgent',
};
export const STATUS_LABEL = {
    OPEN: 'Open', IN_PROGRESS: 'In Progress', RESOLVED: 'Resolved',
};
