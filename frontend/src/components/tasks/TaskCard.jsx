import React from 'react';
import { Pencil, Trash2, Bell } from 'lucide-react';
import { TASK_STATUS_LABEL, TASK_SLOT_MINUTES } from '../../utils/employeeTasksApi';

const fmtTime = (ms) => new Date(ms).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
const fmtDay = (ms) => new Date(ms).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });

/** A task blocks one or more 15-min slots: derive start, end (last slot + 15m), count. */
const slotSpan = (t) => {
    const ms = (t.time_slots || []).map((s) => new Date(s).getTime()).sort((a, b) => a - b);
    const count = ms.length;
    const startMs = count ? ms[0] : new Date(t.scheduled_at).getTime();
    const endMs = (count ? ms[count - 1] : startMs) + TASK_SLOT_MINUTES * 60000;
    return { startMs, endMs, count };
};

/** One task row, shared by the Today and All views. `showDate` adds the day (All view). */
export default function TaskCard({ task, onEdit, onDelete, deleting, showDate }) {
    const sp = slotSpan(task);
    return (
        <div className={`tt-card st-${task.status?.toLowerCase()}`}>
            <div className="tt-time">
                {showDate && <span className="tt-time-date">{fmtDay(sp.startMs)}</span>}
                <span className="tt-time-start">{fmtTime(sp.startMs)}</span>
                <span className="tt-time-end">{fmtTime(sp.endMs)}</span>
            </div>
            <div className="tt-body">
                <div className="tt-title-row">
                    <span className="tt-title">{task.title}</span>
                    <span className={`tt-status st-${task.status?.toLowerCase()}`}>{TASK_STATUS_LABEL[task.status] || task.status}</span>
                </div>
                {task.description && <div className="tt-desc">{task.description}</div>}
                {(sp.count > 1 || task.followup_at) && (
                    <div className="tt-meta">
                        {sp.count > 1 && <span>{sp.count} slots · {sp.count * 15} min</span>}
                        {task.followup_at && (
                            <span className="tt-followup"><Bell size={12} /> Follow-up {fmtTime(new Date(task.followup_at).getTime())}</span>
                        )}
                    </div>
                )}
            </div>
            <div className="tt-actions">
                <button className="tt-icon-btn" onClick={() => onEdit(task)} title="Edit / reschedule"><Pencil size={14} /></button>
                <button className="tt-icon-btn tt-danger" disabled={deleting} onClick={() => onDelete(task)} title="Delete"><Trash2 size={14} /></button>
            </div>
        </div>
    );
}
