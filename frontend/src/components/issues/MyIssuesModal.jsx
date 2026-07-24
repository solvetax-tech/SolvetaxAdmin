import React, { useState, useEffect, useCallback } from 'react';
import { X, Bug, RefreshCw, Image as ImageIcon, ExternalLink, Plus } from 'lucide-react';
import {
    listIssues, viewIssuePhoto,
    ISSUE_STATUSES, PRIORITY_LABEL, STATUS_LABEL,
} from '../../utils/issuesApi';
import { formatDateTimeIST } from '../../utils/formatDateTimeIST';
import './MyIssuesModal.css';

/**
 * Read-only "My Issues" panel: lets whoever reported issues track their own
 * submissions and see whether each is resolved (with the resolver's note).
 * Uses the role-agnostic `mine` filter so it shows only the caller's own rows.
 */
export default function MyIssuesModal({ onClose, onReport }) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [statusFilter, setStatusFilter] = useState('');

    const fetchData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = { mine: true, limit: 100 };
            if (statusFilter) params.status = statusFilter;
            const res = await listIssues(params);
            setData(res.data);
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || err?.message || 'Could not load your issues.');
        } finally {
            setLoading(false);
        }
    }, [statusFilter]);

    useEffect(() => { fetchData(); }, [fetchData]);

    const openPhoto = async (blobUrl) => {
        try {
            const url = await viewIssuePhoto(blobUrl);
            if (url) window.open(url, '_blank', 'noopener');
        } catch {
            /* ignore — the photo just won't open */
        }
    };

    return (
        <div className="my-issues-overlay" onClick={onClose}>
            <div className="my-issues-panel" onClick={(e) => e.stopPropagation()}>
                <div className="my-issues-head">
                    <div className="my-issues-title">
                        <Bug size={18} />
                        <h3>My Issues</h3>
                        {!loading && <span className="my-issues-count">{data.length}</span>}
                    </div>
                    <div className="my-issues-head-actions">
                        <button className="mi-icon-btn" onClick={fetchData} title="Refresh"><RefreshCw size={15} /></button>
                        <button className="mi-icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
                    </div>
                </div>

                <div className="my-issues-filters">
                    {['', ...ISSUE_STATUSES].map((s) => (
                        <button
                            key={s || 'all'}
                            type="button"
                            className={`mi-chip ${statusFilter === s ? 'active' : ''}`}
                            onClick={() => setStatusFilter(s)}
                        >
                            {s ? STATUS_LABEL[s] : 'All'}
                        </button>
                    ))}
                </div>

                <div className="my-issues-body">
                    {loading ? (
                        <div className="mi-state">Loading…</div>
                    ) : error ? (
                        <div className="mi-state mi-state--error">{error}</div>
                    ) : data.length === 0 ? (
                        <div className="mi-state">You haven’t reported any issues yet.</div>
                    ) : data.map((row) => (
                        <div key={row.id} className="mi-card">
                            <div className="mi-card-top">
                                <span className="mi-card-title">{row.title}</span>
                                <span className={`mi-status ${row.status?.toLowerCase()}`}>
                                    {STATUS_LABEL[row.status] || row.status}
                                </span>
                            </div>
                            {row.description && <div className="mi-card-desc">{row.description}</div>}
                            <div className="mi-card-meta">
                                <span className={`mi-prio ${row.priority?.toLowerCase()}`}>
                                    {PRIORITY_LABEL[row.priority] || row.priority}
                                </span>
                                <span className="mi-muted">Raised {formatDateTimeIST(row.created_at)}</span>
                                {Array.isArray(row.photo_urls) && row.photo_urls.length > 0 && (
                                    <button type="button" className="mi-photo" onClick={() => openPhoto(row.photo_urls[0])}>
                                        <ImageIcon size={13} /> {row.photo_urls.length}
                                        <ExternalLink size={10} style={{ opacity: 0.6 }} />
                                    </button>
                                )}
                            </div>
                            {row.resolution_note && (
                                <div className="mi-resolution">
                                    <b>Resolution:</b> {row.resolution_note}
                                </div>
                            )}
                        </div>
                    ))}
                </div>

                {onReport && (
                    <div className="my-issues-foot">
                        <button type="button" className="mi-report-btn" onClick={() => { onClose(); onReport(); }}>
                            <Plus size={15} /> Report a new issue
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
