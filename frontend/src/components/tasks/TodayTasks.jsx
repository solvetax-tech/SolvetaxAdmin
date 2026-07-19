import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Plus, ChevronLeft, ChevronRight, Clock } from 'lucide-react';
import TaskModal from './TaskModal';
import TaskCard from './TaskCard';
import { listTasks, deleteTask, toDateInput } from '../../utils/employeeTasksApi';
import './TodayTasks.css';

const shiftDay = (dayStr, delta) => {
    const d = new Date(`${dayStr}T00:00:00`);
    d.setDate(d.getDate() + delta);
    return toDateInput(d);
};

const prettyDay = (dayStr) => {
    const d = new Date(`${dayStr}T00:00:00`);
    const today = toDateInput(new Date());
    if (dayStr === today) return 'Today';
    if (dayStr === shiftDay(today, 1)) return 'Tomorrow';
    if (dayStr === shiftDay(today, -1)) return 'Yesterday';
    return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
};

export default function TodayTasks({ setToastMessage, statusFilter }) {
    const [day, setDay] = useState(toDateInput(new Date()));
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [modal, setModal] = useState(null); // 'new' | task object | null
    const [deletingId, setDeletingId] = useState(null);

    const fetchData = useCallback(async () => {
        setLoading(true);
        setError(null);
        const controller = new AbortController();
        try {
            const res = await listTasks(day, statusFilter, { signal: controller.signal });
            setData(res.data);
        } catch (err) {
            if (axios.isCancel(err) || err?.code === 'ERR_CANCELED') return;
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || err?.message || 'Failed to load tasks.');
        } finally {
            setLoading(false);
        }
    }, [day, statusFilter]);

    useEffect(() => { fetchData(); }, [fetchData]);

    const remove = async (task) => {
        if (!window.confirm(`Delete "${task.title}"?`)) return;
        setDeletingId(task.id);
        try {
            await deleteTask(task.id);
            window.dispatchEvent(new CustomEvent('st_tasks_updated'));
            setToastMessage?.('Task deleted.');
            await fetchData();
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
                <div className="tt-daynav">
                    <button className="tt-nav-btn" onClick={() => setDay((d) => shiftDay(d, -1))} title="Previous day"><ChevronLeft size={16} /></button>
                    <div className="tt-day-label">
                        <span className="tt-day-main">{prettyDay(day)}</span>
                        <span className="tt-day-sub">{new Date(`${day}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                    </div>
                    <button className="tt-nav-btn" onClick={() => setDay((d) => shiftDay(d, 1))} title="Next day"><ChevronRight size={16} /></button>
                    {day !== toDateInput(new Date()) && (
                        <button className="tt-today-btn" onClick={() => setDay(toDateInput(new Date()))}>Today</button>
                    )}
                </div>
                <button className="tt-new-btn" onClick={() => setModal('new')}><Plus size={16} /> New Task</button>
            </div>

            {error && <div className="error-banner" style={{ margin: '0 0 14px' }}><span>{error}</span></div>}

            {loading ? (
                <div className="tt-empty">Loading…</div>
            ) : data.length === 0 ? (
                <div className="tt-empty">
                    <Clock size={28} style={{ opacity: 0.4 }} />
                    <p>No tasks {statusFilter && statusFilter !== 'ALL' ? 'match this filter' : `scheduled for ${prettyDay(day).toLowerCase()}`}.</p>
                    <button className="tt-new-btn" onClick={() => setModal('new')}><Plus size={16} /> Add one</button>
                </div>
            ) : (
                <div className="tt-list">
                    {data.map((t) => (
                        <TaskCard
                            key={t.id}
                            task={t}
                            onEdit={setModal}
                            onDelete={remove}
                            deleting={deletingId === t.id}
                        />
                    ))}
                </div>
            )}

            {modal && (
                <TaskModal
                    task={modal === 'new' ? null : modal}
                    date={day}
                    onClose={() => setModal(null)}
                    onSaved={() => { fetchData(); setToastMessage?.(modal === 'new' ? 'Task created.' : 'Task updated.'); }}
                />
            )}
        </div>
    );
}
