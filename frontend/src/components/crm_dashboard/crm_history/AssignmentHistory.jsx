import React, { useState, useEffect, useCallback } from 'react';
import { Activity, Loader2 } from 'lucide-react';
import { fetchBulkAssignLogs } from '../../../utils/crmBulkAutoAssignApi';
import Pagination from '../../common/Pagination';
import { formatEntityLabel, formatLogAssignedRoles } from './assignmentHistoryUtils';
import './AssignmentHistory.css';

const ROWS_PER_PAGE = 25;

const AssignmentHistory = ({ entityType = 'GST_REGISTRATION' }) => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalLogs, setTotalLogs] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scope, setScope] = useState('entity');
  const [runType, setRunType] = useState('all');

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        limit: ROWS_PER_PAGE,
        offset: (currentPage - 1) * ROWS_PER_PAGE,
      };
      if (scope === 'entity') {
        params.entityType = entityType;
      }
      if (runType !== 'all') {
        params.runType = runType;
      }
      const data = await fetchBulkAssignLogs(params);
      setLogs(data.items || []);
      setTotalLogs(data.total ?? 0);
    } catch (err) {
      console.error('AssignmentHistory: fetch failed:', err);
      setLogs([]);
      setTotalLogs(0);
    } finally {
      setLoading(false);
    }
  }, [currentPage, scope, runType, entityType]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    setCurrentPage(1);
  }, [scope, runType, entityType]);

  const totalPages = Math.max(1, Math.ceil(totalLogs / ROWS_PER_PAGE));

  return (
    <div className="assignment-history-panel">
      <div className="assignment-history-toolbar">
        <div className="assignment-history-filters">
          <span className="assignment-history-filter-label">Scope</span>
          <div className="history-scope-toggle">
            <button
              type="button"
              className={scope === 'all' ? 'active' : ''}
              onClick={() => setScope('all')}
            >
              All
            </button>
            <button
              type="button"
              className={scope === 'entity' ? 'active' : ''}
              onClick={() => setScope('entity')}
            >
              {formatEntityLabel(entityType)}
            </button>
          </div>
        </div>
        <div className="assignment-history-filters">
          <span className="assignment-history-filter-label">Type</span>
          <div className="history-scope-toggle">
            <button
              type="button"
              className={runType === 'all' ? 'active' : ''}
              onClick={() => setRunType('all')}
            >
              All
            </button>
            <button
              type="button"
              className={runType === 'MANUAL' ? 'active' : ''}
              onClick={() => setRunType('MANUAL')}
            >
              Manual
            </button>
            <button
              type="button"
              className={runType === 'AUTO' ? 'active' : ''}
              onClick={() => setRunType('AUTO')}
            >
              Auto
            </button>
          </div>
        </div>
        <button
          type="button"
          className="btn-icon-mini assignment-history-refresh"
          onClick={fetchLogs}
          disabled={loading}
          title="Refresh"
        >
          <Activity size={14} />
        </button>
      </div>

      <div className="gst-table-wrapper">
        <div className="gst-table-container assignment-history-table-wrap">
          <table className="gst-registrations-table bordered assignment-history-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Type</th>
                <th>Where</th>
                <th>Scheduler</th>
                <th>Matched</th>
                <th>Assigned as</th>
                <th>RM</th>
                <th>OP</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center">
                    <Loader2 className="spin" size={16} style={{ verticalAlign: 'middle', marginRight: 8 }} />
                    Loading assignment history…
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center">
                    No assignment runs logged yet (manual or auto).
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="gst-reg-table-row">
                    <td>{log.created_at ? new Date(log.created_at).toLocaleString() : '—'}</td>
                    <td>{log.run_type}</td>
                    <td>{formatEntityLabel(log.entity_type)}</td>
                    <td>{log.scheduler_name || (log.scheduler_id ? `#${log.scheduler_id}` : '—')}</td>
                    <td>{log.candidates_matched}</td>
                    <td>{formatLogAssignedRoles(log)}</td>
                    <td>{log.total_assigned_rm}</td>
                    <td>{log.total_assigned_op}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {(totalLogs > ROWS_PER_PAGE || currentPage > 1) && (
        <Pagination
          currentPage={currentPage}
          onPageChange={setCurrentPage}
          hasMore={currentPage < totalPages}
          loading={loading}
        />
      )}
    </div>
  );
};

export default AssignmentHistory;
