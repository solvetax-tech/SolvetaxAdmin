import React, { useState, useEffect, useCallback } from 'react';
import { Activity, Server, Phone, History } from 'lucide-react';
import api from '../../../utils/api';
import { unwrapListPayload } from '../../../utils/apiResponse';
import Pagination from '../../common/Pagination';
import AssignmentHistory from './AssignmentHistory';
import './CRMHistory.css';

const CRMHistory = ({ entityType = 'GST_REGISTRATION' }) => {
  const [activeTab, setActiveTab] = useState('SYSTEM'); // 'SYSTEM' | 'CALL' | 'ASSIGNMENT'
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalActivities, setTotalActivities] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 50;

  const fetchActivities = useCallback(async () => {
    if (activeTab === 'ASSIGNMENT') return;
    setLoading(true);
    try {
      // If activeTab is 'CALL', fetch only CALL activities. If 'SYSTEM', fetch SYSTEM activities.
      // Depending on the API, if SYSTEM is not an explicit type but rather "all non-call", we might need to handle it.
      // We will pass the `activity_type` to the filter endpoint.
      const params = {
        limit: rowsPerPage,
        offset: (currentPage - 1) * rowsPerPage,
        activity_type: activeTab,
        entity_type: (entityType || '').trim().toUpperCase()
      };
      
      const apiBase = '/api/v1/crm/leads';
      const response = await api.get(`${apiBase}/activities/filter`, { params });
      const { items, total } = unwrapListPayload(response);
      setActivities(items);
      setTotalActivities(total || 0);
    } catch (err) {
      console.error("Failed to fetch activities:", err);
    } finally {
      setLoading(false);
    }
  }, [currentPage, activeTab, entityType]);

  useEffect(() => {
    fetchActivities();
  }, [fetchActivities]);

  const totalPages = Math.ceil(totalActivities / rowsPerPage);

  const formatLabel = (code) => {
    if (!code) return '';
    return code.replace(/_/g, ' ');
  };

  return (
    <div className="crm-history-container">
      <div className="history-header">
        <div>
          <h2 style={{ color: 'var(--text-primary)', fontSize: '24px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity color="#2eb87a" /> CRM Global History
          </h2>
          <p style={{ color: 'var(--text-primary)', marginTop: '4px', fontSize: '14px' }}>
            Track all lead activities and system updates across the module
          </p>
        </div>
        
        <div className="history-tabs">
          <button 
            className={`history-tab-btn ${activeTab === 'SYSTEM' ? 'active' : ''}`}
            onClick={() => { setActiveTab('SYSTEM'); setCurrentPage(1); }}
          >
            <Server size={16} /> System Activities
          </button>
          <button 
            className={`history-tab-btn ${activeTab === 'CALL' ? 'active' : ''}`}
            onClick={() => { setActiveTab('CALL'); setCurrentPage(1); }}
          >
            <Phone size={16} /> Call Activities
          </button>
          <button 
            className={`history-tab-btn ${activeTab === 'ASSIGNMENT' ? 'active' : ''}`}
            onClick={() => { setActiveTab('ASSIGNMENT'); setCurrentPage(1); }}
          >
            <History size={16} /> Assignment History
          </button>
        </div>
      </div>

      {activeTab === 'ASSIGNMENT' ? (
        <AssignmentHistory entityType={entityType} />
      ) : (
      <>
      <div className="gst-table-wrapper">
        <div className="gst-table-container">
          <table className="gst-registrations-table bordered">
            <thead>
              <tr>
                {(() => {
                  const fallbackHeaders = ['id', 'lead_id', 'activity_type', 'performed_at', 'performed_by', 'remarks'];
                  const keys = (activities && activities.length > 0)
                    ? Object.keys(activities[0])
                    : fallbackHeaders;
              
                  return keys.map((key) => {
                    const isStatusColumn = key.includes('status') || key.includes('code');
                    const cellClass = isStatusColumn ? 'status-column' : '';
                    return <th key={key} className={cellClass} style={{ textTransform: 'capitalize' }}>{formatLabel(key)}</th>;
                  });
                })()}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="20" className="text-center">Fetching activities from database...</td></tr>
              ) : activities.length === 0 ? (
                <tr><td colSpan="20" className="text-center">No activity records found for this category.</td></tr>
              ) : activities.map((act, idx) => {
                const keys = Object.keys(activities[0]);
                return (
                  <tr key={act.id || idx} className="gst-reg-table-row">
                    {keys.map(key => {
                      let val = act[key];
                      
                      if (val === null || val === undefined) {
                         val = '-';
                      } else if (key === 'performed_at') {
                         val = new Date(val).toLocaleString();
                      } else if (typeof val === 'boolean') {
                         val = val ? 'Yes' : 'No';
                      } else if (typeof val === 'object') {
                         val = JSON.stringify(val);
                      } else {
                         val = String(val);
                      }
            
                      const isStatusColumn = key === 'call_status_code' || key.includes('status');
                      return <td key={key} className={isStatusColumn ? 'status-column' : ''}>{val}</td>;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      
      {totalPages > 1 && (
        <Pagination 
          currentPage={currentPage}
          onPageChange={setCurrentPage}
          hasMore={currentPage < totalPages}
          loading={loading}
        />
      )}
      </>
      )}
    </div>
  );
};

export default CRMHistory;
