import React, { useCallback } from 'react';
import PaginatedTasks from './PaginatedTasks';
import { listAllTasks } from '../../utils/employeeTasksApi';

/** All of the caller's tasks across every day, newest scheduled first, optionally status-filtered. */
export default function AllTasks({ setToastMessage, statusFilter }) {
    const fetchPage = useCallback(
        (offset) => listAllTasks({ status: statusFilter, limit: 50, offset }),
        [statusFilter],
    );
    const filtered = statusFilter && statusFilter !== 'ALL';
    return (
        <PaginatedTasks
            fetchPage={fetchPage}
            setToastMessage={setToastMessage}
            emptyText={filtered ? 'No tasks match this filter.' : 'No tasks yet.'}
            countLabel={(total) => `${total} task${total === 1 ? '' : 's'}${filtered ? ' (filtered)' : ''}`}
        />
    );
}
