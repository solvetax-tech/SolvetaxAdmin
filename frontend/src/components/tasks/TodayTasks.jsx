import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Plus, ChevronLeft, ChevronRight, Pencil, Trash2, Clock, Bell } from 'lucide-react';
import TaskModal from './TaskModal';
import {
    listTasks, deleteTask, toDateInput, TASK_STATUS_LABEL, TASK_SLOT_MINUTES,
} from '../../utils/employeeTasksApi';
import './TodayTasks.css';

const timeOf = (iso) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
const fmt = (ms) => new Date(ms).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

// A task blocks one or more 15-min slots. Derive its start, its end (last
// slot + 15 min), and how many slots it holds.
const slotSpan = (t) => {
    const ms = (t.time_slots || []).map((s) => new Date(s).getTime()).sort((a, b) => a - b);
    const count = ms.length;
    const startMs = count ? ms[0] : new Date(t.scheduled_at).getTime();
    const endMs = (count ? ms[count - 1] : startMs) + TASK_SLOT_MINUTES * 60000;
    return { startMs, endMs, count };
};

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

export default function TodayTasks({ setToastMessage }) {
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
            const res = await listTasks(day, { signal: controller.signal });
            setData(res.data);
        } catch (err) {
            if (axios.isCancel(err) || err?.code === 'ERR_CANCELED') return;
            const detail = err?.response?.data?.detail;
            setError((typeof detail === 'string' && detail) || err?.message || 'Failed to load tasks.');
        } finally {
            setLoading(false);
        }
    }, [day]);

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
                    <p>No tasks scheduled for {prettyDay(day).toLowerCase()}.</p>
                    <button className="tt-new-btn" onClick={() => setModal('new')}><Plus size={16} /> Add one</button>
                </div>
            ) : (
                <div className="tt-list">
                    {data.map((t) => {
                        const sp = slotSpan(t);
                        return (
                        <div key={t.id} className={`tt-card st-${t.status?.toLowerCase()}`}>
                            <div className="tt-time">
                                <span className="tt-time-start">{fmt(sp.startMs)}</span>
                                <span className="tt-time-end">{fmt(sp.endMs)}</span>
                            </div>
                            <div className="tt-body">
                                <div className="tt-title-row">
                                    <span className="tt-title">{t.title}</span>
                                    <span className={`tt-status st-${t.status?.toLowerCase()}`}>{TASK_STATUS_LABEL[t.status] || t.status}</span>
                                </div>
                                {t.description && <div className="tt-desc">{t.description}</div>}
                                {(sp.count > 1 || t.followup_at) && (
                                    <div className="tt-meta">
                                        {sp.count > 1 && <span>{sp.count} slots · {sp.count * 15} min</span>}
                                        {t.followup_at && (
                                            <span className="tt-followup"><Bell size={12} /> Follow-up {timeOf(t.followup_at)}</span>
                                        )}
                                    </div>
                                )}
                            </div>
                            <div className="tt-actions">
                                <button className="tt-icon-btn" onClick={() => setModal(t)} title="Edit / reschedule"><Pencil size={14} /></button>
                                <button className="tt-icon-btn tt-danger" disabled={deletingId === t.id} onClick={() => remove(t)} title="Delete"><Trash2 size={14} /></button>
                            </div>
                        </div>
                        );
                    })}
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
