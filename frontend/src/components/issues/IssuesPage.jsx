import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Plus, Bug, RefreshCw, Pencil, Image as ImageIcon, ExternalLink } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import RaiseIssueModal from './RaiseIssueModal';
import EditIssueModal from './EditIssueModal';
import {
    listIssues, viewIssuePhoto,
    ISSUE_PRIORITIES, ISSUE_STATUSES, PRIORITY_LABEL, STATUS_LABEL,
} from '../../utils/issuesApi';
import { formatDateTimeIST } from '../../utils/formatDateTimeIST';
import './IssuesPage.css';

const PAGE_SIZE = 20;

const STATUS_FILTER_OPTS = optionsFromPairs([
    { value: '', label: 'All Statuses' },
    ...ISSUE_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] })),
]);
const PRIORITY_FILTER_OPTS = optionsFromPairs([
    { value: '', label: 'All Priorities' },
    ...ISSUE_PRIORITIES.map((p) => ({ value: p, label: PRIORITY_LABEL[p] })),
]);

export default function IssuesPage({ setToastMessage }) {
    const [data, setData] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [page, setPage] = useState(1);
    const [statusFilter, setStatusFilter] = useState('');
    const [priorityFilter, setPriorityFilter] = useState('');
    const [showRaise, setShowRaise] = useState(false);
    const [editingIssue, setEditingIssue] = useState(null);

    const fetchData = useCallback(async () => {
        setLoading(true);
        setError(null);
        const controller = new AbortController();
        try {
            const params = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
            if (statusFilter) params.status = statusFilter;
            if (priorityFilter) params.priority = priorityFilter;
            const res = await listIssues(params, { signal: controller.signal });
            setData(res.data);
            setTotal(res.total);
        } catch (err) {
            if (axios.isCancel(err) || err?.code === 'ERR_CANCELED') return;
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || err?.message || 'Failed to load issues.');
        } finally {
            setLoading(false);
        }
        return () => controller.abort();
    }, [page, statusFilter, priorityFilter]);

    useEffect(() => { fetchData(); }, [fetchData]);

    const openPhoto = async (blobUrl) => {
        try {
            const url = await viewIssuePhoto(blobUrl);
            if (url) window.open(url, '_blank', 'noopener');
        } catch {
            setToastMessage?.('Could not open the photo.');
        }
    };

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    return (
        <div className="issues-page">
            <div className="issues-header">
                <div className="issues-title">
                    <Bug size={20} />
                    <h2>Issues</h2>
                    <span className="issues-count">{total}</span>
                </div>
                <div className="issues-actions">
                    <div style={{ minWidth: 160 }}>
                        <FormCustomSelect
                            name="status" value={statusFilter}
                            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                            options={STATUS_FILTER_OPTS} placeholder="All Statuses" ariaLabel="Status filter"
                        />
                    </div>
                    <div style={{ minWidth: 160 }}>
                        <FormCustomSelect
                            name="priority" value={priorityFilter}
                            onChange={(e) => { setPriorityFilter(e.target.value); setPage(1); }}
                            options={PRIORITY_FILTER_OPTS} placeholder="All Priorities" ariaLabel="Priority filter"
                        />
                    </div>
                    <button className="issues-btn-ghost" onClick={fetchData} title="Refresh"><RefreshCw size={15} /></button>
                    <button className="issues-btn-primary" onClick={() => setShowRaise(true)}>
                        <Plus size={16} /> Report Issue
                    </button>
                </div>
            </div>

            {error && <div className="error-banner" style={{ margin: '0 0 14px' }}><span>{error}</span></div>}

            <div className="issues-table-wrap">
                <table className="issues-table">
                    <thead>
                        <tr>
                            <th>Title</th>
                            <th>Description</th>
                            <th>Priority</th>
                            <th>Status</th>
                            <th>Resolution / Note</th>
                            <th>Reporter</th>
                            <th>Photos</th>
                            <th>Raised</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan={9} className="issues-empty">Loading…</td></tr>
                        ) : data.length === 0 ? (
                            <tr><td colSpan={9} className="issues-empty">No issues found.</td></tr>
                        ) : data.map((row) => (
                            <tr key={row.id}>
                                <td><div className="issue-title-cell">{row.title}</div></td>
                                <td>
                                    {row.description
                                        ? <div className="issue-desc-cell">{row.description}</div>
                                        : <span className="issue-muted">—</span>}
                                </td>
                                <td><span className={`issue-pill prio-${row.priority?.toLowerCase()}`}>{PRIORITY_LABEL[row.priority] || row.priority}</span></td>
                                <td><span className={`issue-pill st-${row.status?.toLowerCase()}`}>{STATUS_LABEL[row.status] || row.status}</span></td>
                                <td>
                                    {row.resolution_note
                                        ? <div className="issue-note-cell">{row.resolution_note}</div>
                                        : <span className="issue-muted">—</span>}
                                </td>
                                <td className="issue-muted">{row.reporter_name || row.reporter_username || `#${row.reporter_emp_id}`}</td>
                                <td>
                                    {Array.isArray(row.photo_urls) && row.photo_urls.length > 0 ? (
                                        <button className="issue-photos-btn" onClick={() => openPhoto(row.photo_urls[0])} title="View photo">
                                            <ImageIcon size={14} /> {row.photo_urls.length}
                                            <ExternalLink size={11} style={{ opacity: 0.6 }} />
                                        </button>
                                    ) : <span className="issue-muted">—</span>}
                                </td>
                                <td className="issue-muted">{formatDateTimeIST(row.created_at)}</td>
                                <td>
                                    <button className="issue-edit-btn" onClick={() => setEditingIssue(row)}>
                                        <Pencil size={13} /> Edit
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {totalPages > 1 && (
                <div className="issues-pager">
                    <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</button>
                    <span>Page {page} of {totalPages}</span>
                    <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</button>
                </div>
            )}

            {showRaise && (
                <RaiseIssueModal
                    onClose={() => setShowRaise(false)}
                    onCreated={() => { setPage(1); fetchData(); setToastMessage?.('Issue reported.'); }}
                />
            )}

            {editingIssue && (
                <EditIssueModal
                    issue={editingIssue}
                    onClose={() => setEditingIssue(null)}
                    onSaved={() => { fetchData(); setToastMessage?.('Issue updated.'); }}
                />
            )}
        </div>
    );
}
