import React, { useState } from 'react';
import { FileSpreadsheet, Upload, CheckCircle2, AlertCircle, Loader2, Info, Check } from 'lucide-react';
import api from '../../../utils/api';
import './BulkAssign.css';

/** Map POST /api/v1/crm/leads/import response to UI stats (new_leads, duplicates_found). */
function parseImportStats(data) {
  const stats = data?.stats || {};
  const newLeads =
    data?.new_leads ??
    stats.new_leads ??
    data?.inserted_count ??
    data?.imported_count ??
    0;
  const duplicatesFound =
    data?.duplicates_found ??
    stats.duplicates_found ??
    data?.duplicates_skipped ??
    stats.duplicates_skipped ??
    data?.skipped_count ??
    0;
  const failedCount = data?.failed_count ?? stats.failed ?? data?.failed ?? 0;
  const message =
    typeof data?.message === 'string' && data.message.trim()
      ? data.message
      : `Successfully imported ${newLeads} new lead(s). ${duplicatesFound} duplicate(s) found.`;

  return {
    newLeads: Number(newLeads) || 0,
    duplicatesFound: Number(duplicatesFound) || 0,
    failedCount: Number(failedCount) || 0,
    message,
    raw: data,
  };
}

const ImportLeads = ({ entityType = 'GST_REGISTRATION' }) => {
  const isIncomeTaxCrm = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null); // { type: 'success' | 'error', message: string, stats?: any }

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      if (selectedFile.name.endsWith('.csv') || selectedFile.name.endsWith('.xlsx') || selectedFile.name.endsWith('.xls')) {
        setFile(selectedFile);
        setStatus(null);
      } else {
        setStatus({ type: 'error', message: 'Please select a valid Excel or CSV file.' });
      }
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setStatus(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('entity_type', entityType);

    try {
      const response = await api.post('/api/v1/crm/leads/import', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      const parsed = parseImportStats(response.data);
      setStatus({
        type: 'success',
        message: parsed.message,
        stats: parsed,
      });
      setFile(null);
    } catch (err) {
      console.error("Import failed:", err);
      setStatus({ 
        type: 'error', 
        message: err.response?.data?.detail || 'Failed to import leads. Please check your file format.' 
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bulk-assign-container expanded">
       <div className="bulk-assign-header">
        <div className="header-title">
          <FileSpreadsheet size={20} className="icon" />
          <span>Import Leads - {entityType.replace(/_/g, ' ')}</span>
        </div>
      </div>

      <div className="bulk-assign-body" style={{ padding: '40px' }}>
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          {!status?.stats ? (
            <div 
              style={{ 
                border: '2px dashed rgba(var(--accent-rgb), 0.35)',
                borderRadius: 'var(--radius-lg)',
                padding: '60px 40px',
                textAlign: 'center',
                background: 'var(--bg-surface-2)',
                transition: 'all 0.3s ease'
              }}
              onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = 'var(--accent)'; }}
              onDragLeave={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = 'rgba(var(--accent-rgb), 0.2)'; }}
              onDrop={(e) => {
                e.preventDefault();
                const droppedFile = e.dataTransfer.files[0];
                if (droppedFile) handleFileChange({ target: { files: [droppedFile] } });
              }}
            >
              <div style={{ marginBottom: '24px' }}>
                <div style={{ 
                  width: '80px', 
                  height: '80px', 
                  borderRadius: '50%', 
                  background: 'rgba(var(--accent-rgb), 0.1)', 
                  display: 'flex', 
                  alignItems: 'center', 
                  justifyContent: 'center', 
                  margin: '0 auto' 
                }}>
                  <Upload size={32} color="var(--accent)" />
                </div>
              </div>

              {file ? (
                <div style={{ animation: 'fadeIn 0.3s ease' }}>
                  <h4 style={{ color: 'var(--text-primary)', marginBottom: '8px' }}>{file.name}</h4>
                  <p style={{ color: 'var(--text-primary)', fontSize: '13px' }}>
                    {(file.size / 1024 / 1024).toFixed(2)} MB • Ready to upload
                  </p>
                  <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '32px' }}>
                    <button 
                      className="btn-fetch" 
                      onClick={handleUpload} 
                      disabled={loading}
                      style={{ background: 'var(--accent)', color: 'var(--text-primary)' }}
                    >
                      {loading ? <Loader2 className="spin" size={18} /> : <Check size={18} />}
                      Confirm Upload
                    </button>
                    <button 
                      className="btn-drawer-secondary" 
                      onClick={() => setFile(null)}
                      disabled={loading}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <h3 style={{ color: 'var(--text-primary)', marginBottom: '12px' }}>Click or Drag File</h3>
                  <p style={{ color: 'var(--text-primary)', marginBottom: '32px' }}>
                    Support for .xlsx, .xls, and .csv files
                  </p>
                  <label 
                    className="btn-fetch" 
                    style={{ cursor: 'pointer', display: 'inline-flex' }}
                  >
                    <input type="file" style={{ display: 'none' }} onChange={handleFileChange} accept=".csv, .xlsx, .xls" />
                    Browse Files
                  </label>
                </>
              )}
            </div>
          ) : (
             <div style={{ animation: 'slideUp 0.4s ease' }}>
                <div style={{ textAlign: 'center', marginBottom: '40px' }}>
                  <div style={{ width: '64px', height: '64px', background: 'rgba(var(--accent-rgb), 0.1)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                    <CheckCircle2 size={32} color="var(--accent)" />
                  </div>
                  <h2 style={{ color: 'var(--text-primary)', marginBottom: '8px' }}>Import Complete!</h2>
                  <p style={{ color: 'var(--text-primary)' }}>{status.message}</p>
                </div>

                <div style={{ background: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', padding: '24px', border: '1px solid var(--border)', boxShadow: 'var(--shadow-sm)' }}>
                  <h4 style={{ color: 'var(--text-primary)', marginBottom: '20px', fontSize: '14px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Import Statistics</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    <div className="stat-item">
                      <div style={{ color: 'var(--text-primary)', fontSize: '12px', marginBottom: '4px' }}>New Leads</div>
                      <div style={{ color: 'var(--accent)', fontSize: '24px', fontWeight: '700' }}>{status.stats?.newLeads ?? 0}</div>
                    </div>
                    <div className="stat-item">
                      <div style={{ color: 'var(--text-primary)', fontSize: '12px', marginBottom: '4px' }}>Duplicates Found</div>
                      <div style={{ color: 'var(--warning)', fontSize: '24px', fontWeight: '700' }}>{status.stats?.duplicatesFound ?? 0}</div>
                    </div>
                  </div>
                  {status.stats?.failedCount > 0 && (
                    <div className="stat-item" style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
                      <div style={{ color: 'var(--text-primary)', fontSize: '12px', marginBottom: '4px' }}>Failed Rows</div>
                      <div style={{ color: 'var(--danger)', fontSize: '24px', fontWeight: '700' }}>{status.stats.failedCount}</div>
                    </div>
                  )}
                </div>

                <button 
                  className="btn-fetch" 
                  style={{ width: '100%', marginTop: '32px' }}
                  onClick={() => setStatus(null)}
                >
                  Import More Files
                </button>
             </div>
          )}

          {status && status.type === 'error' && (
            <div style={{ 
              marginTop: '24px',
              padding: '16px',
              background: 'rgba(var(--danger-rgb), 0.1)',
              border: '1px solid rgba(var(--danger-rgb), 0.2)',
              borderRadius: '12px',
              display: 'flex',
              gap: '12px',
              color: 'var(--danger)',
              fontSize: '14px',
              alignItems: 'center'
            }}>
              <AlertCircle size={18} />
              {status.message}
            </div>
          )}

          <div style={{ marginTop: '40px', padding: '24px', background: 'rgba(var(--info-rgb), 0.05)', border: '1px solid rgba(var(--info-rgb), 0.1)', borderRadius: '16px' }}>
            <div style={{ display: 'flex', gap: '12px' }}>
              <Info size={18} color="var(--info)" style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <h5 style={{ color: 'var(--text-primary)', marginBottom: '8px' }}>Instructions</h5>
                <ul style={{ color: 'var(--text-primary)', fontSize: '13px', paddingLeft: '16px', margin: 0, lineHeight: '1.6' }}>
                  <li>Ensure your file has a header row with field names.</li>
                  <li>
                    Mandatory columns: <strong>mobile</strong>, <strong>entity_type</strong>, <strong>lead_type</strong>, <strong>preferred_language</strong>.
                  </li>
                  {isIncomeTaxCrm ? (
                    <>
                      <li>
                        Optional Income Tax columns: <strong>full_name</strong>, <strong>email</strong>,{' '}
                        <strong>lead_source</strong>, <strong>tag</strong>, <strong>ay</strong> (assessment year, e.g. 2024-25), <strong>stage</strong>.
                      </li>
                      <li><strong>ay</strong> and <strong>lead_type</strong> accept typed values — use formats like <strong>2024-25</strong> for AY.</li>
                    </>
                  ) : (
                    <li>Optional columns: <strong>full_name</strong>, <strong>email</strong>, <strong>lead_source</strong>, <strong>tag</strong>, <strong>stage</strong>.</li>
                  )}
                  {isIncomeTaxCrm ? (
                    <li>
                      Only <strong>new</strong> leads are inserted. Duplicate{' '}
                      <strong>mobile + entity type + AY</strong> rows are skipped (existing leads are never updated).
                    </li>
                  ) : (
                    <li>
                      Only <strong>new</strong> leads are inserted. Duplicate{' '}
                      <strong>mobile + entity type</strong> rows are skipped (existing leads are never updated).
                    </li>
                  )}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ImportLeads;
