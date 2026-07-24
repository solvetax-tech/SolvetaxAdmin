import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Wifi, WifiOff, AlertCircle, CheckCircle2, Loader2, Send, Shield, Clock, BarChart2 } from 'lucide-react';
import api from '../../utils/api';
import ThemeToggle from '../common/ThemeToggle';
import './WhatsApp.css';

/* ── Guardrail chain (static display) ─────────────────────────────────── */
const GUARDRAILS = [
  {
    label: 'Consent Check',
    desc: 'Customer must have whatsapp_consent = true in wa_instance_config.',
  },
  {
    label: 'Quiet Hours (09:00–21:00 IST)',
    desc: 'Messages outside this window are blocked. Config lives in wa_instance_config.',
  },
  {
    label: 'Daily Cap',
    desc: 'Per-customer daily message limit enforced. Threshold in wa_instance_config.',
  },
];

/* ── Map API status → badge variant ───────────────────────────────────── */
function connectionVariant(state) {
  if (!state) return 'unknown';
  const s = String(state).toLowerCase();
  if (s === 'open' || s === 'connected') return 'connected';
  if (s === 'close' || s === 'closed' || s === 'disconnected') return 'disconnected';
  return 'unknown';
}

/* ── Map send error status → display info ─────────────────────────────── */
function errorInfo(status, detail) {
  if (status === 403) return { cls: 'status-403', title: 'No Consent', icon: <Shield size={14} /> };
  // Guardrail 422s carry a string detail; a non-string detail is request validation.
  if (status === 422 && typeof detail !== 'string') return { cls: 'status-other', title: 'Invalid Request', icon: <AlertCircle size={14} /> };
  if (status === 422) return { cls: 'status-422', title: 'Quiet Hours', icon: <Clock size={14} /> };
  if (status === 429) return { cls: 'status-429', title: 'Rate Limited', icon: <BarChart2 size={14} /> };
  if (status === 502) return { cls: 'status-502', title: 'Gateway Unreachable', icon: <WifiOff size={14} /> };
  return { cls: 'status-other', title: `Error ${status || ''}`, icon: <AlertCircle size={14} /> };
}

export default function WhatsAppConfig() {
  const navigate = useNavigate();

  /* ── Instance status ── */
  const [instStatus, setInstStatus] = useState(null);   // null = loading
  const [instError, setInstError] = useState(null);     // {status, detail}

  /* ── Test send form ── */
  const [phone, setPhone] = useState('');
  const [message, setMessage] = useState('');
  const [phoneErr, setPhoneErr] = useState('');
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState(null);   // {ok, status, detail}

  useEffect(() => {
    let cancelled = false;
    api.get('/api/v1/whatsapp/instance/status')
      .then((res) => {
        if (!cancelled) setInstStatus(res.data);
      })
      .catch((err) => {
        if (cancelled) return;
        const status = err?.status ?? err?.response?.status;
        const detail = err?.response?.data?.detail ?? err?.message ?? 'Unknown error';
        setInstError({ status, detail });
        setInstStatus(false);
      });
    return () => { cancelled = true; };
  }, []);

  function validatePhone(v) {
    if (!/^\d{10}$/.test(v)) return 'Enter a 10-digit phone number';
    return '';
  }

  async function handleSend(e) {
    e.preventDefault();
    const err = validatePhone(phone);
    if (err) { setPhoneErr(err); return; }
    setPhoneErr('');
    setSending(true);
    setSendResult(null);
    try {
      await api.post('/api/v1/whatsapp/send', { phone, body: message });
      setSendResult({ ok: true });
    } catch (apiErr) {
      const status = apiErr?.status ?? apiErr?.response?.status;
      const raw = apiErr?.response?.data?.detail ?? apiErr?.message ?? 'Send failed';
      const detail = typeof raw === 'string' ? raw : JSON.stringify(raw);
      setSendResult({ ok: false, status, detail, rawDetail: raw });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="wa-page">
      {/* Top bar */}
      <div className="wa-topbar">
        <button className="wa-topbar-back" onClick={() => navigate('/dashboard')}>
          <ArrowLeft size={14} /> Dashboard
        </button>
        <span className="wa-topbar-title">WhatsApp Config</span>
        <ThemeToggle />
      </div>

      <div className="wa-body">

        {/* ── Instance Status card ── */}
        <div className="wa-card">
          <p className="wa-card-title"><Wifi size={16} /> Instance Status</p>
          <p className="wa-card-subtitle">Live connection state from Evolution API.</p>

          {instStatus === null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
              <Loader2 size={16} className="spin" /> Loading…
            </div>
          )}

          {instStatus === false && instError && (
            <div className="wa-unreachable-box">
              <WifiOff size={18} className="wa-unreachable-icon" />
              <div>
                <p className="wa-unreachable-title">Evolution API Unreachable</p>
                <p className="wa-unreachable-detail">
                  {String(instError.detail)}
                </p>
                <p className="wa-unreachable-detail" style={{ marginTop: 4, fontStyle: 'italic' }}>
                  This is expected in dev — the Evolution API container is not running locally.
                </p>
              </div>
            </div>
          )}

          {instStatus && typeof instStatus === 'object' && (
            <div className="wa-instance-row">
              <span className="wa-instance-name">
                {instStatus.instance_name ?? instStatus.instanceName ?? 'Instance'}
              </span>
              <span className={`wa-badge ${connectionVariant(instStatus.connection_state ?? instStatus.connectionState ?? instStatus.state)}`}>
                {connectionVariant(instStatus.connection_state ?? instStatus.connectionState ?? instStatus.state) === 'connected'
                  ? <><CheckCircle2 size={11} /> Connected</>
                  : <><WifiOff size={11} /> Disconnected</>}
              </span>
            </div>
          )}
        </div>

        {/* ── Guardrails card ── */}
        <div className="wa-card">
          <p className="wa-card-title"><Shield size={16} /> Message Guardrails</p>
          <p className="wa-card-subtitle">Every outbound message passes through these checks in order.</p>

          <div className="wa-chain">
            {GUARDRAILS.map((step, i) => (
              <div key={i} className="wa-chain-step">
                <div className="wa-chain-connector">
                  <div className="wa-chain-dot" />
                  {i < GUARDRAILS.length - 1 && <div className="wa-chain-line" />}
                </div>
                <div style={{ paddingBottom: i < GUARDRAILS.length - 1 ? 12 : 0 }}>
                  <p className="wa-chain-label">{step.label}</p>
                  <p className="wa-chain-desc">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Test Send card ── */}
        <div className="wa-card">
          <p className="wa-card-title"><Send size={16} /> Test Send</p>
          <p className="wa-card-subtitle">Send a test WhatsApp message through the guardrail chain.</p>

          <form onSubmit={handleSend}>
            <div className="wa-form-row">
              <div>
                <p className="wa-form-label">Phone Number</p>
                <input
                  type="text"
                  className={`wa-input${phoneErr ? ' error' : ''}`}
                  placeholder="10-digit mobile number"
                  value={phone}
                  maxLength={10}
                  onChange={(e) => { setPhone(e.target.value); setPhoneErr(''); setSendResult(null); }}
                />
                {phoneErr && (
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--danger)', marginTop: 4, display: 'block' }}>
                    {phoneErr}
                  </span>
                )}
              </div>
              <div>
                <p className="wa-form-label">Message</p>
                <textarea
                  className="wa-input"
                  placeholder="Your test message…"
                  value={message}
                  required
                  onChange={(e) => { setMessage(e.target.value); setSendResult(null); }}
                />
              </div>
            </div>

            <button type="submit" className="wa-btn primary" disabled={sending}>
              {sending ? <><Loader2 size={14} className="spin" /> Sending…</> : <><Send size={14} /> Send</>}
            </button>
          </form>

          {sendResult?.ok && (
            <div className="wa-success-banner">
              <CheckCircle2 size={14} /> Message sent successfully.
            </div>
          )}

          {sendResult && !sendResult.ok && (() => {
            const info = errorInfo(sendResult.status, sendResult.rawDetail ?? sendResult.detail);
            return (
              <div className={`wa-error-banner ${info.cls}`}>
                {info.icon}
                <div>
                  <p className="wa-error-title">{info.title}</p>
                  <p className="wa-error-detail">{String(sendResult.detail)}</p>
                </div>
              </div>
            );
          })()}
        </div>

      </div>
    </div>
  );
}
