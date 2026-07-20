import React, { useState } from 'react';
import TodayTasks from './TodayTasks';
import AllTasks from './AllTasks';
import PreviousTasks from './PreviousTasks';
import { TASK_STATUSES, TASK_STATUS_LABEL } from '../../utils/employeeTasksApi';
import './TasksPage.css';

const OPEN_STATUSES = ['PENDING', 'IN_PROGRESS'];
const asOption = (s) => ({ value: s, label: TASK_STATUS_LABEL[s] });
// Today / All can filter by any status; Previous only by the open ones.
const STATUS_OPTIONS = [{ value: 'ALL', label: 'All' }, ...TASK_STATUSES.map(asOption)];
const PREVIOUS_STATUS_OPTIONS = [{ value: 'ALL', label: 'All' }, ...OPEN_STATUSES.map(asOption)];

const SUB_TABS = [
    { key: 'previous', label: 'Previous Tasks' },
    { key: 'today', label: 'Today Tasks' },
    { key: 'all', label: 'All' },
];

/**
 * Top-level Tasks page. Sub-tabs: Previous (past unfinished) / Today / All.
 * A status filter applies to every view; on Previous it offers only the open
 * statuses (Pending / In Progress).
 */
export default function TasksPage({ setToastMessage }) {
    const [view, setView] = useState('today'); // 'previous' | 'today' | 'all'
    const [status, setStatus] = useState('ALL');

    const changeView = (v) => {
        setView(v);
        // Previous can't show Done/Cancelled — fall back to All if one is selected.
        if (v === 'previous' && !['ALL', ...OPEN_STATUSES].includes(status)) setStatus('ALL');
    };

    const options = view === 'previous' ? PREVIOUS_STATUS_OPTIONS : STATUS_OPTIONS;

    return (
        <div className="tasks-page">
            <div className="tasks-page-bar">
                <div className="tasks-subtabs">
                    {SUB_TABS.map((t) => (
                        <button
                            key={t.key}
                            type="button"
                            className={`tasks-subtab ${view === t.key ? 'active' : ''}`}
                            onClick={() => changeView(t.key)}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                <div className="tasks-filter">
                    <span className="tasks-filter-label">Status</span>
                    <div className="tasks-status-pills">
                        {options.map((o) => (
                            <button
                                key={o.value}
                                type="button"
                                className={`tasks-pill ${status === o.value ? 'active' : ''}`}
                                onClick={() => setStatus(o.value)}
                            >
                                {o.label}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {view === 'previous' && <PreviousTasks setToastMessage={setToastMessage} statusFilter={status} />}
            {view === 'today' && <TodayTasks setToastMessage={setToastMessage} statusFilter={status} />}
            {view === 'all' && <AllTasks setToastMessage={setToastMessage} statusFilter={status} />}
        </div>
    );
}
