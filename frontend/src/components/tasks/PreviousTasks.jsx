import React, { useCallback } from 'react';
import PaginatedTasks from './PaginatedTasks';
import { listPreviousTasks, TASK_STATUS_LABEL } from '../../utils/employeeTasksApi';

/**
 * Past tasks (scheduled before today) that are still Pending or In Progress.
 * Read-only for creation — you can't schedule a task in the past — but you can
 * still edit / reschedule / mark them done. Filterable to one open status.
 */
export default function PreviousTasks({ setToastMessage, statusFilter }) {
    const fetchPage = useCallback(
        (offset) => listPreviousTasks({ status: statusFilter, limit: 50, offset }),
        [statusFilter],
    );
    const filtered = statusFilter && statusFilter !== 'ALL';
    const label = filtered ? TASK_STATUS_LABEL[statusFilter] : 'pending or in-progress';
    return (
        <PaginatedTasks
            fetchPage={fetchPage}
            setToastMessage={setToastMessage}
            allowCreate={false}
            emptyText={filtered ? `No previous ${label} tasks.` : "No previous pending or in-progress tasks — you're all caught up."}
            countLabel={(total) => `${total} ${filtered ? label : 'unfinished'} task${total === 1 ? '' : 's'} before today`}
        />
    );
}
