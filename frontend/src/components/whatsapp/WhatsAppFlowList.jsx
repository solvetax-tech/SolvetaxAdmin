import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, X, Loader2, AlertCircle } from 'lucide-react';
import api from '../../utils/api';
import ThemeToggle from '../common/ThemeToggle';
import './WhatsApp.css';

const TRIGGER_LABELS = {
  inbound_keyword: 'Inbound Keyword',
  scheduled_date: 'Scheduled Date',
  crm_event: 'CRM Event',
};

function formatDate(str) {
  if (!str) return '-';
  try {
    return new Date(str).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return str;
  }
}

export default function WhatsAppFlowList() {
  const navigate = useNavigate();

  const [flows, setFlows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  /* ── New flow modal state ── */
  const [showModal, setShowModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTrigger, setNewTrigger] = useState('inbound_keyword');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const fetchFlows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/api/v1/whatsapp/flows');
      setFlows(Array.isArray(res.data) ? res.data : (res.data?.flows ?? []));
    } catch (err) {
      setError(err?.message ?? 'Failed to load flows');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchFlows(); }, [fetchFlows]);

  async function handleCreate(e) {
    e.preventDefault();
    if (!newName.trim()) { setCreateError('Name is required'); return; }
    setCreating(true);
    setCreateError('');
    try {
      const res = await api.post('/api/v1/whatsapp/flows', {
        name: newName.trim(),
        trigger_type: newTrigger,
      });
      const created = res.data;
      setShowModal(false);
      setNewName('');
      setNewTrigger('inbound_keyword');
      navigate(`/whatsapp-flows/${created.id}`);
    } catch (err) {
      setCreateError(err?.message ?? 'Failed to create flow');
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(flow, value) {
    // Optimistic update
    setFlows((prev) => prev.map((f) => f.id === flow.id ? { ...f, is_active: value } : f));
    try {
      await api.patch(`/api/v1/whatsapp/flows/${flow.id}`, { is_active: value });
    } catch {
      // Revert on failure
      setFlows((prev) => prev.map((f) => f.id === flow.id ? { ...f, is_active: flow.is_active } : f));
    }
  }

  function openModal() {
    setNewName('');
    setNewTrigger('inbound_keyword');
    setCreateError('');
    setShowModal(true);
  }

  return (
    <div className="wa-page">
      {/* Top bar */}
      <div className="wa-topbar">
        <button className="wa-topbar-back" onClick={() => navigate('/dashboard')}>
          <ArrowLeft size={14} /> Dashboard
        </button>
        <span className="wa-topbar-title">WhatsApp Workflows</span>
        <ThemeToggle />
      </div>

      <div className="wa-body">
        <div className="wa-flows-header">
          <h2 className="wa-flows-heading">Flows</h2>
          <button className="wa-btn primary" onClick={openModal}>
            <Plus size={14} /> New Flow
          </button>
        </div>

        <div className="wa-card" style={{ padding: 0 }}>
          {loading ? (
            <div className="wa-empty-state">
              <Loader2 size={20} className="spin" style={{ margin: '0 auto 8px', display: 'block' }} />
              Loading flows…
            </div>
          ) : error ? (
            <div className="wa-empty-state">
              <AlertCircle size={20} style={{ margin: '0 auto 8px', display: 'block', color: 'var(--danger)' }} />
              {error}
            </div>
          ) : flows.length === 0 ? (
            <div className="wa-empty-state">
              No flows yet. Create your first workflow.
            </div>
          ) : (
            <div className="wa-table-wrapper">
              <table className="wa-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trigger</th>
                    <th>Status</th>
                    <th>Active</th>
                    <th>Version</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {flows.map((flow) => (
                    <tr key={flow.id}>
                      <td>
                        <span
                          className="wa-table-link"
                          onClick={() => navigate(`/whatsapp-flows/${flow.id}`)}
                        >
                          {flow.name}
                        </span>
                      </td>
                      <td className="wa-table-muted">
                        {TRIGGER_LABELS[flow.trigger_type] ?? flow.trigger_type}
                      </td>
                      <td>
                        <span className={`wa-badge ${flow.status === 'published' ? 'published' : 'draft'}`}>
                          {flow.status === 'published' ? 'Published' : 'Draft'}
                        </span>
                      </td>
                      <td>
                        <label className="wa-toggle" title={flow.is_active ? 'Deactivate' : 'Activate'}>
                          <input
                            type="checkbox"
                            checked={!!flow.is_active}
                            onChange={(e) => handleToggleActive(flow, e.target.checked)}
                          />
                          <span className="wa-toggle-slider" />
                        </label>
                      </td>
                      <td className="wa-table-muted">
                        {flow.version ?? '-'}
                      </td>
                      <td className="wa-table-muted">
                        {formatDate(flow.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* New Flow Modal */}
      {showModal && (
        <div className="wa-modal-overlay" onClick={() => setShowModal(false)}>
          <div className="wa-modal" onClick={(e) => e.stopPropagation()}>
            <div className="wa-modal-title">
              New Flow
              <button className="wa-modal-close" onClick={() => setShowModal(false)}>
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleCreate}>
              <div className="wa-config-field">
                <p className="wa-form-label">Flow Name</p>
                <input
                  type="text"
                  className="wa-input"
                  placeholder="e.g. Welcome Message"
                  value={newName}
                  onChange={(e) => { setNewName(e.target.value); setCreateError(''); }}
                  autoFocus
                />
              </div>
              <div className="wa-config-field">
                <p className="wa-form-label">Trigger Type</p>
                <select
                  className="wa-select"
                  value={newTrigger}
                  onChange={(e) => setNewTrigger(e.target.value)}
                >
                  <option value="inbound_keyword">Inbound Keyword</option>
                  <option value="scheduled_date">Scheduled Date</option>
                  <option value="crm_event">CRM Event</option>
                </select>
              </div>

              {createError && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 'var(--text-xs)', color: 'var(--danger)', marginBottom: 8 }}>
                  <AlertCircle size={12} /> {createError}
                </div>
              )}

              <div className="wa-modal-footer">
                <button type="button" className="wa-btn secondary" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="wa-btn primary" disabled={creating}>
                  {creating ? <><Loader2 size={14} className="spin" /> Creating…</> : 'Create Flow'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
