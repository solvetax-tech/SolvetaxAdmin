import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { XCircle, Loader2 } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromPairs } from '../common/selectOptionUtils';
import {
    createTask, patchTask, getAvailableSlots,
    TASK_STATUSES, TASK_STATUS_LABEL, TASK_SLOT_MINUTES, toDateInput,
} from '../../utils/employeeTasksApi';
import './TaskModal.css';

const SLOT_MS = TASK_SLOT_MINUTES * 60000;
const fmtTime = (ms) => new Date(ms).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

const STATUS_OPTS = optionsFromPairs(TASK_STATUSES.map((s) => ({ value: s, label: TASK_STATUS_LABEL[s] })));

/**
 * Create or edit a task. The time is chosen from a Google-Calendar-style grid of
 * the day's free 15-min slots. A task blocks a contiguous START → END range:
 * click a slot to book it, then click a LATER slot to set the (exclusive) end —
 * e.g. start 00:00 + end 00:15 books one slot; start 00:00 + end 00:30 books two.
 *
 * Everything is keyed by epoch-ms (instant) so it compares cleanly regardless of
 * ISO string formatting between the grid and stored task slots.
 */
export default function TaskModal({ task, date, onClose, onSaved }) {
    const isEdit = Boolean(task);
    const initialDay = task ? toDateInput(new Date(task.scheduled_at)) : (date || toDateInput(new Date()));

    const [form, setForm] = useState({
        title: task?.title || '',
        description: task?.description || '',
        status: task?.status || 'PENDING',
        followup_at: task?.followup_at ? toLocalInput(task.followup_at) : '',
        followup_note: task?.followup_note || '',
    });
    const [day, setDay] = useState(initialDay);
    const [slots, setSlots] = useState([]);
    // Booked = the epoch-ms of every slot this task blocks. anchor = the pending
    // start after a first click, awaiting an end click (null once a range is set).
    const [booked, setBooked] = useState(() => new Set((task?.time_slots || []).map((s) => Date.parse(s))));
    const [anchor, setAnchor] = useState(null);
    const [loadingSlots, setLoadingSlots] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [fieldErrors, setFieldErrors] = useState({});

    const loadSlots = useCallback(async () => {
        setLoadingSlots(true);
        try {
            const res = await getAvailableSlots(day, isEdit ? task.id : undefined);
            setSlots(res.slots || []);
        } catch {
            setSlots([]);
        } finally {
            setLoadingSlots(false);
        }
    }, [day, isEdit, task]);

    useEffect(() => { loadSlots(); }, [loadSlots]);

    // Full ordered timeline (incl. taken, so a range can't jump a booked slot),
    // plus an epoch -> index lookup. Only free slots are rendered/clickable.
    const timeline = useMemo(
        () => slots.map((s) => ({ ...s, epoch: Date.parse(s.iso) })),
        [slots],
    );
    const idxByEpoch = useMemo(() => {
        const m = new Map();
        timeline.forEach((s, i) => m.set(s.epoch, i));
        return m;
    }, [timeline]);
    const freeSlots = timeline.filter((s) => s.available);

    const clearSlotError = () => setFieldErrors((p) => (p.slot ? { ...p, slot: undefined } : p));

    // Click a free slot: first click sets the start (books just that slot); a
    // second, later click sets the exclusive end, booking [start, end) up to the
    // first taken slot in between. Clicking the same/earlier slot restarts.
    const pickSlot = (s) => {
        clearSlotError();
        const e = s.epoch;
        if (anchor == null) { setAnchor(e); setBooked(new Set([e])); return; }
        const ai = idxByEpoch.get(anchor);
        const ci = idxByEpoch.get(e);
        if (ai == null || ci == null || ci < ai) { setAnchor(e); setBooked(new Set([e])); return; }
        if (ci === ai) { setAnchor(null); setBooked(new Set()); return; } // click start again = clear
        const next = new Set();
        for (let i = ai; i < ci; i += 1) {
            if (!timeline[i].available) break; // stop at a booked slot
            next.add(timeline[i].epoch);
        }
        setBooked(next);
        setAnchor(null); // range complete; next click starts fresh
    };

    const resetSlots = () => { setAnchor(null); setBooked(new Set()); };

    // start -> end readout: end = last booked slot's END (start + 15 min).
    const bookedMs = [...booked].sort((a, b) => a - b);
    const rangeStartMs = bookedMs.length ? bookedMs[0] : null;
    const rangeEndMs = bookedMs.length ? bookedMs[bookedMs.length - 1] + SLOT_MS : null;

    const change = (e) => {
        const { name, value } = e.target;
        setForm((prev) => ({ ...prev, [name]: value }));
        setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
    };

    const submit = async (e) => {
        e.preventDefault();
        if (saving) return;
        const errs = {};
        if (form.title.trim().length < 1) errs.title = 'Enter a title.';
        if (booked.size < 1) errs.slot = 'Pick a start slot (and an end slot for a longer block).';
        if (Object.keys(errs).length) { setFieldErrors(errs); return; }

        setSaving(true);
        setError(null);
        try {
            const body = {
                title: form.title.trim(),
                description: form.description.trim() || null,
                time_slots: bookedMs.map((ms) => new Date(ms).toISOString()),
            };
            if (form.followup_at) body.followup_at = form.followup_at;
            if (form.followup_note.trim()) body.followup_note = form.followup_note.trim();
            if (isEdit) body.status = form.status;

            if (isEdit) await patchTask(task.id, body);
            else await createTask(body);
            window.dispatchEvent(new CustomEvent('st_tasks_updated'));
            onSaved?.();
            onClose?.();
        } catch (err) {
            const status = err?.response?.status;
            const detail = err?.response?.data?.detail;
            if (status === 409) setError(typeof detail === 'string' ? detail : 'That time is no longer free.');
            else {
                const fields = detail?.error?.fields;
                if (status === 400 && fields) { setFieldErrors(fields); setError(detail?.error?.message || 'Check the values.'); }
                else setError((typeof detail === 'string' && detail) || err?.message || 'Could not save the task.');
            }
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="gst-filters-drawer-overlay" onClick={() => !saving && onClose?.()}>
            <div className="gst-filters-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header">
                    <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>{isEdit ? 'Edit Task' : 'New Task'}</h2>
                    <button className="btn-drawer-close" onClick={() => onClose?.()} disabled={saving}><XCircle size={20} /></button>
                </div>

                <form onSubmit={submit} style={{ display: 'contents' }}>
                    <div className="drawer-content">
                        {error && <div className="error-banner" style={{ marginBottom: '14px' }}><span>{error}</span></div>}

                        <div className="filter-section-v4">
                            <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                <label>Title <span style={{ color: 'var(--danger)' }}>*</span></label>
                                <input type="text" name="title" value={form.title} onChange={change} placeholder="e.g. Call client about GST" maxLength={200} />
                                {fieldErrors.title && <span className="field-error-msg">{fieldErrors.title}</span>}
                            </div>
                            <div className="filter-group-v4" style={{ marginBottom: '12px' }}>
                                <label>Description</label>
                                <textarea name="description" value={form.description} onChange={change} rows={2} placeholder="Optional details"
                                    style={{ width: '100%', boxSizing: 'border-box', background: 'var(--bg-input)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '10px 12px', color: 'var(--text-primary)', fontSize: '14px', outline: 'none', resize: 'vertical', fontFamily: 'inherit' }} />
                            </div>

                            <div className="filter-group-v4">
                                <label>Date</label>
                                <input type="date" name="day" value={day} onChange={(e) => { setDay(e.target.value); resetSlots(); }} />
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <div className="filter-group-v4">
                                <label>Time slots <span style={{ color: 'var(--danger)' }}>*</span> <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(click a start slot, then an end slot)</span></label>
                                {loadingSlots ? (
                                    <div className="task-slots-loading"><Loader2 size={16} className="task-spin" /> Loading slots…</div>
                                ) : freeSlots.length === 0 ? (
                                    <div className="task-slots-loading">No free slots left on this day.</div>
                                ) : (
                                    <div className="task-slot-grid">
                                        {freeSlots.map((s) => {
                                            const isBooked = booked.has(s.epoch);
                                            const isEndMark = !isBooked && s.epoch === rangeEndMs; // exclusive end boundary
                                            const isAnchor = anchor === s.epoch;
                                            return (
                                                <button
                                                    key={s.iso}
                                                    type="button"
                                                    className={`task-slot ${isBooked ? 'selected' : ''} ${isEndMark ? 'range-end' : ''}`}
                                                    title={anchor != null ? `End at ${s.time}` : `Start at ${s.time}`}
                                                    onClick={() => pickSlot(s)}
                                                >
                                                    {s.time}
                                                    {isAnchor && anchor != null && <span className="task-slot-tag">start</span>}
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                                {booked.size > 0 ? (
                                    <span style={{ marginTop: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>
                                        {fmtTime(rangeStartMs)} → {fmtTime(rangeEndMs)} · {booked.size} slot{booked.size > 1 ? 's' : ''} ({booked.size * 15} min)
                                        {anchor != null && ' — pick an end slot, or leave as is'}
                                        {' · '}<button type="button" className="task-slot-clear" onClick={resetSlots}>clear</button>
                                    </span>
                                ) : (
                                    <span style={{ marginTop: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>
                                        Click a slot to book it. Click a later slot to extend to that end time.
                                    </span>
                                )}
                                {fieldErrors.slot && <span className="field-error-msg">{fieldErrors.slot}</span>}
                            </div>
                        </div>

                        <div className="filter-divider-v4" style={{ height: '1px', background: 'rgba(var(--fg-rgb),0.05)', margin: '16px 0' }} />

                        <div className="filter-section-v4">
                            <div className="filter-row-v4" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '12px', marginBottom: '12px' }}>
                                {isEdit && (
                                    <div className="filter-group-v4">
                                        <label>Status</label>
                                        <FormCustomSelect name="status" value={form.status} onChange={change} options={STATUS_OPTS} ariaLabel="Status" />
                                    </div>
                                )}
                                <div className="filter-group-v4">
                                    <label>Follow-up at <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(optional)</span></label>
                                    <input type="datetime-local" name="followup_at" value={form.followup_at} onChange={change} />
                                </div>
                            </div>
                            {form.followup_at && (
                                <div className="filter-group-v4">
                                    <label>Follow-up note</label>
                                    <input type="text" name="followup_note" value={form.followup_note} onChange={change} placeholder="Optional note for the follow-up" />
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="drawer-footer">
                        <button type="button" className="btn-reset-v4" onClick={() => onClose?.()} disabled={saving}>Cancel</button>
                        <button type="submit" className="btn-apply-v4" disabled={saving || loadingSlots}>{saving ? 'Saving…' : (isEdit ? 'Save Changes' : 'Create Task')}</button>
                    </div>
                </form>
            </div>
        </div>
    );
}

/** ISO (with offset) → value for <input type="datetime-local"> in the browser's local (IST) zone. */
function toLocalInput(iso) {
    const d = new Date(iso);
    const pad = (x) => String(x).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
