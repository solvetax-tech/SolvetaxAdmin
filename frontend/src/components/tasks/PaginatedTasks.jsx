import React, { useState, useEffect, useCallback } from 'react';
import { Plus, Clock } from 'lucide-react';
import TaskModal from './TaskModal';
import TaskCard from './TaskCard';
import { deleteTask } from '../../utils/employeeTasksApi';
import './TodayTasks.css';

/**
 * A generic paginated task list (used by the All and Previous views). The page
 * source is injected via `fetchPage(offset) -> { data, total }`; give it a stable
 * (memoized) identity so a change to it triggers a reload from the top.
 */
export default function PaginatedTasks({ fetchPage, setToastMessage, emptyText, countLabel, allowCreate = true }) {
    const [data, setData] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState(null);
    const [modal, setModal] = useState(null); // 'new' | task object | null
    const [deletingId, setDeletingId] = useState(null);

    const load = useCallback(async (offset = 0) => {
        const first = offset === 0;
        if (first) setLoading(true); else setLoadingMore(true);
        setError(null);
        try {
            const res = await fetchPage(offset);
            setTotal(res.total);
            setData((prev) => (first ? res.data : [...prev, ...res.data]));
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || err?.message || 'Failed to load tasks.');
        } finally {
            if (first) setLoading(false); else setLoadingMore(false);
        }
    }, [fetchPage]);

    useEffect(() => { load(0); }, [load]);

    // Refresh from the top whenever any task changes (create / edit / delete).
    useEffect(() => {
        const onUpd = () => load(0);
        window.addEventListener('st_tasks_updated', onUpd);
        return () => window.removeEventListener('st_tasks_updated', onUpd);
    }, [load]);

    const remove = async (task) => {
        if (!window.confirm(`Delete "${task.title}"?`)) return;
        setDeletingId(task.id);
        try {
            await deleteTask(task.id);
            window.dispatchEvent(new CustomEvent('st_tasks_updated'));
            setToastMessage?.('Task deleted.');
        } catch (err) {
            const detail = err?.response?.data?.detail;
            setToastMessage?.((typeof detail === 'string' && detail) || 'Could not delete the task.');
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <div className="today-tasks">
            <div className="tt-header">
                <div className="tt-count">{countLabel ? countLabel(total) : `${total} task${total === 1 ? '' : 's'}`}</div>
                {allowCreate && (
                    <button className="tt-new-btn" onClick={() => setModal('new')}><Plus size={16} /> New Task</button>
                )}
            </div>

            {error && <div className="error-banner" style={{ margin: '0 0 14px' }}><span>{error}</span></div>}

            {loading ? (
                <div className="tt-empty">Loading…</div>
            ) : data.length === 0 ? (
                <div className="tt-empty">
                    <Clock size={28} style={{ opacity: 0.4 }} />
                    <p>{emptyText}</p>
                    {allowCreate && (
                        <button className="tt-new-btn" onClick={() => setModal('new')}><Plus size={16} /> Add one</button>
                    )}
                </div>
            ) : (
                <>
                    <div className="tt-list">
                        {data.map((t) => (
                            <TaskCard key={t.id} task={t} onEdit={setModal} onDelete={remove} deleting={deletingId === t.id} showDate />
                        ))}
                    </div>
                    {data.length < total && (
                        <div className="tt-loadmore-row">
                            <button className="tt-loadmore" disabled={loadingMore} onClick={() => load(data.length)}>
                                {loadingMore ? 'Loading…' : `Load more (${total - data.length} left)`}
                            </button>
                        </div>
                    )}
                </>
            )}

            {modal && (
                <TaskModal
                    task={modal === 'new' ? null : modal}
                    onClose={() => setModal(null)}
                    onSaved={() => setToastMessage?.(modal === 'new' ? 'Task created.' : 'Task updated.')}
                />
            )}
        </div>
    );
}
