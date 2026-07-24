import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  Handle,
  Position,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  ArrowLeft, ChevronRight, Loader2, AlertCircle, CheckCircle2, X,
  Zap, Calendar, GitBranch, MessageSquare, ListChecks, Edit3, GitFork,
  Clock, StopCircle,
} from 'lucide-react';
import api from '../../utils/api';
import ThemeToggle from '../common/ThemeToggle';
import './WhatsApp.css';

/* ── Node type metadata ───────────────────────────────────────────────── */
const NODE_DEFS = {
  inboundKeyword: { label: 'Inbound Keyword', group: 'Triggers', icon: '📩', iconClass: 'trigger', defaultConfig: { keyword: '', match_mode: 'exact' } },
  scheduledDate:  { label: 'Scheduled Date',  group: 'Triggers', icon: '📅', iconClass: 'trigger', defaultConfig: { source: '', days_before: 1 } },
  crmEvent:       { label: 'CRM Event',        group: 'Triggers', icon: '⚡', iconClass: 'trigger', defaultConfig: { event_type: '', from_stage: '', to_stage: '' } },
  sendMessage:    { label: 'Send Message',     group: 'Actions',  icon: '💬', iconClass: 'action',  defaultConfig: { body: '' } },
  assignTask:     { label: 'Assign Task',      group: 'Actions',  icon: '✅', iconClass: 'action',  defaultConfig: { assignee: '', title: '', description: '' } },
  updateCrmField: { label: 'Update CRM Field', group: 'Actions',  icon: '✏️', iconClass: 'action',  defaultConfig: { field: '', value: '' } },
  condition:      { label: 'Condition',        group: 'Logic',    icon: '🔀', iconClass: 'logic',   defaultConfig: { variable: '', operator: 'equals', value: '' } },
  wait:           { label: 'Wait',             group: 'Logic',    icon: '⏳', iconClass: 'logic',   defaultConfig: { type: 'delay', delay_minutes: 60, timeout_hours: 24 } },
  endFlow:        { label: 'End Flow',         group: 'Control',  icon: '🔴', iconClass: 'control', defaultConfig: {} },
};

/* Group order for palette */
const PALETTE_GROUPS = ['Triggers', 'Actions', 'Logic', 'Control'];

/* ── Summary of a node's config for display on canvas ─────────────────── */
function nodeSummary(type, config) {
  if (!config) return '';
  switch (type) {
    case 'inboundKeyword': return config.keyword ? `"${config.keyword}"` : '';
    case 'scheduledDate':  return config.source ? `${config.days_before}d before ${config.source}` : '';
    case 'crmEvent':       return config.event_type || '';
    case 'sendMessage':    return config.body ? config.body.slice(0, 30) + (config.body.length > 30 ? '…' : '') : '';
    case 'assignTask':     return config.title || '';
    case 'updateCrmField': return config.field ? `${config.field} = ${config.value}` : '';
    case 'condition':      return config.variable ? `${config.variable} ${config.operator} ${config.value}` : '';
    case 'wait':
      if (config.type === 'reply') return 'Wait for reply';
      if (config.delay_minutes >= 1440) return `${Math.round(config.delay_minutes / 1440)}d`;
      if (config.delay_minutes >= 60) return `${Math.round(config.delay_minutes / 60)}h`;
      return `${config.delay_minutes}min`;
    default: return '';
  }
}

/* ── Custom ReactFlow node component ──────────────────────────────────── */
function WaNode({ data, selected }) {
  const def = NODE_DEFS[data.nodeType] ?? { label: data.nodeType, iconClass: 'control', icon: '?' };
  const summary = nodeSummary(data.nodeType, data.config);
  const isCondition = data.nodeType === 'condition';
  const isWaitReply = data.nodeType === 'wait' && data.config?.type === 'reply';
  const isTrigger = def.group === 'Triggers';
  const isEnd = data.nodeType === 'endFlow';

  return (
    <div className={`wa-node${selected ? ' selected' : ''}`}>
      {/* Target handle (top) — not on trigger nodes */}
      {!isTrigger && (
        <Handle type="target" position={Position.Top} style={{ background: 'var(--border-strong)' }} />
      )}

      <div className="wa-node-header">
        <span className={`wa-node-icon ${def.iconClass}`}>{def.icon}</span>
        <span className="wa-node-label">{data.label || def.label}</span>
      </div>
      {summary && <div className="wa-node-summary">{summary}</div>}

      {/* Source handles */}
      {!isEnd && !isCondition && !isWaitReply && (
        <Handle type="source" position={Position.Bottom} style={{ background: 'var(--border-strong)' }} />
      )}

      {/* Condition: true_output (left) + false_output (right) */}
      {isCondition && (
        <>
          <Handle
            type="source"
            position={Position.Bottom}
            id="true_output"
            style={{ left: '30%', background: 'var(--success)' }}
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="false_output"
            style={{ left: '70%', background: 'var(--danger)' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-muted)', marginTop: 10, paddingTop: 4 }}>
            <span style={{ color: 'var(--success)' }}>True</span>
            <span style={{ color: 'var(--danger)' }}>False</span>
          </div>
        </>
      )}

      {/* Wait (reply): on_reply (left) + on_timeout (right) */}
      {isWaitReply && (
        <>
          <Handle
            type="source"
            position={Position.Bottom}
            id="on_reply"
            style={{ left: '30%', background: 'var(--accent)' }}
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="on_timeout"
            style={{ left: '70%', background: 'var(--warning)' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-muted)', marginTop: 10, paddingTop: 4 }}>
            <span style={{ color: 'var(--accent)' }}>Reply</span>
            <span style={{ color: 'var(--warning)' }}>Timeout</span>
          </div>
        </>
      )}
    </div>
  );
}

const nodeTypes = { waNode: WaNode };

/* ── Read app theme for ReactFlow colorMode ───────────────────────────────── */
function useAppColorMode() {
  const read = () => {
    const t = document.documentElement.dataset.theme;
    return (t === 'light' || t === 'violet') ? 'light' : 'dark';
  };
  const [mode, setMode] = useState(read);
  useEffect(() => {
    const obs = new MutationObserver(() => setMode(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);
  return mode;
}

/* ── Delay presets ────────────────────────────────────────────────────── */
const DELAY_PRESETS = [
  { label: '5 minutes',  minutes: 5 },
  { label: '15 minutes', minutes: 15 },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour',     minutes: 60 },
  { label: '2 hours',    minutes: 120 },
  { label: '4 hours',    minutes: 240 },
  { label: '8 hours',    minutes: 480 },
  { label: '1 day',      minutes: 1440 },
  { label: '2 days',     minutes: 2880 },
  { label: '3 days',     minutes: 4320 },
];

/* ── Config drawer field renderer ─────────────────────────────────────── */
function ConfigFields({ nodeType, config, onChange }) {
  function field(key) { return config?.[key] ?? ''; }
  function set(key, value) { onChange({ ...config, [key]: value }); }

  switch (nodeType) {
    case 'inboundKeyword':
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Keyword</p>
            <input className="wa-input" value={field('keyword')} onChange={(e) => set('keyword', e.target.value)} placeholder="e.g. hello" />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Match Mode</p>
            <select className="wa-select" value={field('match_mode') || 'exact'} onChange={(e) => set('match_mode', e.target.value)}>
              <option value="exact">Exact</option>
              <option value="contains">Contains</option>
              <option value="starts_with">Starts With</option>
            </select>
          </div>
        </>
      );

    case 'scheduledDate':
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Date Source</p>
            <input className="wa-input" value={field('source')} onChange={(e) => set('source', e.target.value)} placeholder="e.g. due_date" />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Days Before</p>
            <input type="number" className="wa-input" min={0} value={field('days_before') ?? 1} onChange={(e) => set('days_before', Number(e.target.value))} />
          </div>
        </>
      );

    case 'crmEvent':
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Event Type</p>
            <input className="wa-input" value={field('event_type')} onChange={(e) => set('event_type', e.target.value)} placeholder="e.g. stage_change" />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">From Stage (optional)</p>
            <input className="wa-input" value={field('from_stage')} onChange={(e) => set('from_stage', e.target.value)} />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">To Stage (optional)</p>
            <input className="wa-input" value={field('to_stage')} onChange={(e) => set('to_stage', e.target.value)} />
          </div>
        </>
      );

    case 'sendMessage':
      return (
        <div className="wa-config-field">
          <p className="wa-config-label">Message Body</p>
          <textarea className="wa-input" rows={5} value={field('body')} onChange={(e) => set('body', e.target.value)} placeholder="Hello {{name}}, …" />
        </div>
      );

    case 'assignTask':
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Assignee</p>
            <input className="wa-input" value={field('assignee')} onChange={(e) => set('assignee', e.target.value)} placeholder="username or emp_id" />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Task Title</p>
            <input className="wa-input" value={field('title')} onChange={(e) => set('title', e.target.value)} />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Description</p>
            <textarea className="wa-input" rows={3} value={field('description')} onChange={(e) => set('description', e.target.value)} />
          </div>
        </>
      );

    case 'updateCrmField':
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Field</p>
            <input className="wa-input" value={field('field')} onChange={(e) => set('field', e.target.value)} placeholder="e.g. stage" />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Value</p>
            <input className="wa-input" value={field('value')} onChange={(e) => set('value', e.target.value)} />
          </div>
        </>
      );

    case 'condition':
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Variable</p>
            <input className="wa-input" value={field('variable')} onChange={(e) => set('variable', e.target.value)} placeholder="e.g. reply_text" />
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Operator</p>
            <select className="wa-select" value={field('operator') || 'equals'} onChange={(e) => set('operator', e.target.value)}>
              <option value="equals">Equals</option>
              <option value="not_equals">Not Equals</option>
              <option value="contains">Contains</option>
              <option value="starts_with">Starts With</option>
              <option value="gt">Greater Than</option>
              <option value="lt">Less Than</option>
            </select>
          </div>
          <div className="wa-config-field">
            <p className="wa-config-label">Value</p>
            <input className="wa-input" value={field('value')} onChange={(e) => set('value', e.target.value)} />
          </div>
        </>
      );

    case 'wait': {
      const waitType = field('type') || 'delay';
      return (
        <>
          <div className="wa-config-field">
            <p className="wa-config-label">Wait Type</p>
            <select className="wa-select" value={waitType} onChange={(e) => set('type', e.target.value)}>
              <option value="delay">Delay</option>
              <option value="reply">Wait for Reply</option>
            </select>
          </div>
          {waitType === 'delay' && (
            <div className="wa-config-field">
              <p className="wa-config-label">Delay</p>
              <select
                className="wa-select"
                value={field('delay_minutes') ?? 60}
                onChange={(e) => set('delay_minutes', Number(e.target.value))}
              >
                {DELAY_PRESETS.map((p) => (
                  <option key={p.minutes} value={p.minutes}>{p.label}</option>
                ))}
              </select>
            </div>
          )}
          {waitType === 'reply' && (
            <div className="wa-config-field">
              <p className="wa-config-label">Timeout (hours)</p>
              <input type="number" className="wa-input" min={1} value={field('timeout_hours') ?? 24} onChange={(e) => set('timeout_hours', Number(e.target.value))} />
            </div>
          )}
        </>
      );
    }

    case 'endFlow':
      return <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>No configuration needed.</p>;

    default:
      return <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Unknown node type.</p>;
  }
}

/* ── Inner editor component (must be inside ReactFlowProvider) ─────────── */
function FlowEditorInner({ flowId }) {
  const navigate = useNavigate();
  const { setCenter } = useReactFlow();
  const colorMode = useAppColorMode();

  const [flowMeta, setFlowMeta] = useState(null);   // { id, name, status, version }
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);

  /* ── Save state ── */
  const [saveStatus, setSaveStatus] = useState('idle'); // idle | saving | saved
  const debounceRef = useRef(null);

  /* ── Selected node for config drawer ── */
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) ?? null, [nodes, selectedNodeId]);

  /* ── Issues panel ── */
  const [issues, setIssues] = useState(null);   // null = hidden, [] = no issues, [...] = issues
  const [validating, setValidating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState(null);  // {ok, version} | {ok: false, issues}

  /* ── Drop zone ref ── */
  const canvasWrapperRef = useRef(null);

  /* ── Load flow ── */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    api.get(`/api/v1/whatsapp/flows/${flowId}`)
      .then((res) => {
        if (cancelled) return;
        const flow = res.data;
        setFlowMeta({ id: flow.id, name: flow.name, status: flow.status, version: flow.version });
        const draft = flow.draft_data;
        if (draft?.nodes) setNodes(draft.nodes);
        if (draft?.edges) setEdges(draft.edges);
      })
      .catch((err) => {
        if (!cancelled) setFetchError(err?.message ?? 'Failed to load flow');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [flowId, setNodes, setEdges]);

  /* ── Auto-save draft with 2s debounce ── */
  const { getViewport } = useReactFlow();

  const saveDraft = useCallback(() => {
    const viewport = getViewport();
    setSaveStatus('saving');
    api.put(`/api/v1/whatsapp/flows/${flowId}/draft`, {
      draft_data: { nodes, edges, viewport },
    })
      .then(() => setSaveStatus('saved'))
      .catch(() => setSaveStatus('idle'));
  }, [flowId, nodes, edges, getViewport]);

  // Debounce save on nodes/edges change (skip on first load)
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    if (loading) return;
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(saveDraft, 2000);
    return () => clearTimeout(debounceRef.current);
  }, [nodes, edges, saveDraft, loading]);

  /* ── Drag-and-drop from palette ── */
  function onDragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }

  function onDrop(e) {
    e.preventDefault();
    const nodeType = e.dataTransfer.getData('application/wa-node-type');
    if (!nodeType || !canvasWrapperRef.current) return;

    const bounds = canvasWrapperRef.current.getBoundingClientRect();
    const { x: vx, y: vy, zoom } = getViewport();
    const posX = (e.clientX - bounds.left - vx) / zoom;
    const posY = (e.clientY - bounds.top  - vy) / zoom;

    const def = NODE_DEFS[nodeType] ?? {};
    const id = `${nodeType}-${Date.now()}`;
    const newNode = {
      id,
      type: 'waNode',
      position: { x: posX - 80, y: posY - 30 },
      data: {
        nodeType,
        label: def.label ?? nodeType,
        config: { ...def.defaultConfig },
      },
    };
    setNodes((nds) => [...nds, newNode]);
  }

  /* ── Connect edges ── */
  const onConnect = useCallback((params) => {
    setEdges((eds) => addEdge({ ...params, animated: false }, eds));
  }, [setEdges]);

  /* ── Node click → open config drawer ── */
  function onNodeClick(_, node) {
    setSelectedNodeId(node.id);
  }

  /* ── Update node config from drawer ── */
  function updateNodeConfig(config) {
    setNodes((nds) =>
      nds.map((n) => n.id === selectedNodeId ? { ...n, data: { ...n.data, config } } : n)
    );
  }

  /* ── Validate ── */
  async function handleValidate() {
    setValidating(true);
    setIssues(null);
    setPublishResult(null);
    try {
      const res = await api.post(`/api/v1/whatsapp/flows/${flowId}/validate`);
      setIssues(res.data?.issues ?? []);
    } catch (err) {
      setIssues([{ node_id: null, check: 'api', message: err?.message ?? 'Validation request failed' }]);
    } finally {
      setValidating(false);
    }
  }

  /* ── Publish ── */
  async function handlePublish() {
    setPublishing(true);
    setPublishResult(null);
    setIssues(null);
    try {
      const res = await api.post(`/api/v1/whatsapp/flows/${flowId}/publish`);
      setPublishResult({ ok: true, version: res.data?.version });
      setFlowMeta((prev) => prev ? { ...prev, status: 'published', version: res.data?.version } : prev);
    } catch (err) {
      // FastAPI wraps HTTPException bodies in {detail: {...}} (QA bug 3, 2026-07-24)
      const errIssues = err?.response?.data?.detail?.issues ?? err?.response?.data?.issues;
      if (Array.isArray(errIssues)) {
        setIssues(errIssues);
        setPublishResult({ ok: false, issues: errIssues });
      } else {
        setPublishResult({ ok: false, issues: [{ node_id: null, check: 'api', message: err?.message ?? 'Publish failed' }] });
        setIssues([{ node_id: null, check: 'api', message: err?.message ?? 'Publish failed' }]);
      }
    } finally {
      setPublishing(false);
    }
  }

  /* ── Jump to node ── */
  function jumpToNode(nodeId) {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    setCenter(node.position.x + 80, node.position.y + 30, { zoom: 1.2, duration: 400 });
    setSelectedNodeId(nodeId);
  }

  if (loading) {
    return (
      <div className="wa-page" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <Loader2 size={28} className="spin" style={{ color: 'var(--accent)' }} />
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="wa-page" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <AlertCircle size={28} style={{ color: 'var(--danger)', marginBottom: 12 }} />
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>{fetchError}</p>
      </div>
    );
  }

  return (
    <div className="wa-page">
      {/* Top bar */}
      <div className="wa-topbar">
        <button className="wa-topbar-back" onClick={() => navigate('/whatsapp-flows')}>
          <ArrowLeft size={14} /> Flows
        </button>
        <span className="wa-topbar-title">
          {flowMeta?.name ?? 'Flow'}
          {flowMeta?.status && (
            <span className={`wa-badge ${flowMeta.status === 'published' ? 'published' : 'draft'}`} style={{ marginLeft: 10 }}>
              {flowMeta.status === 'published' ? 'Published' : 'Draft'}
            </span>
          )}
        </span>
        <ThemeToggle />
      </div>

      {/* Editor toolbar */}
      <div className="wa-editor-toolbar">
        <span className="wa-editor-title">
          {flowMeta?.name}
        </span>
        <span className={`wa-save-indicator${saveStatus === 'saving' ? ' saving' : saveStatus === 'saved' ? ' saved' : ''}`}>
          {saveStatus === 'saving' && <><Loader2 size={12} className="spin" /> Saving…</>}
          {saveStatus === 'saved' && <><CheckCircle2 size={12} /> Saved</>}
        </span>
        <button
          className="wa-btn secondary"
          style={{ height: 32, fontSize: 12 }}
          onClick={handleValidate}
          disabled={validating || publishing}
        >
          {validating ? <><Loader2 size={12} className="spin" /> Validating…</> : 'Validate'}
        </button>
        <button
          className="wa-btn primary"
          style={{ height: 32, fontSize: 12 }}
          onClick={handlePublish}
          disabled={publishing || validating}
        >
          {publishing ? <><Loader2 size={12} className="spin" /> Publishing…</> : 'Publish'}
        </button>
        {publishResult?.ok && (
          <span style={{ fontSize: 12, color: 'var(--success)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <CheckCircle2 size={12} /> Published (v{publishResult.version})
          </span>
        )}
      </div>

      {/* Main editor area */}
      <div className="wa-editor-shell" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* Palette */}
          <div className="wa-palette">
            {PALETTE_GROUPS.map((group) => {
              const items = Object.entries(NODE_DEFS).filter(([, def]) => def.group === group);
              return (
                <div key={group}>
                  <div className="wa-palette-group-label">{group}</div>
                  {items.map(([type, def]) => (
                    <div
                      key={type}
                      className="wa-palette-item"
                      draggable
                      onDragStart={(e) => e.dataTransfer.setData('application/wa-node-type', type)}
                    >
                      <span className={`wa-palette-icon wa-node-icon ${def.iconClass}`}>{def.icon}</span>
                      {def.label}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>

          {/* Canvas */}
          <div
            className="wa-canvas"
            ref={canvasWrapperRef}
            onDragOver={onDragOver}
            onDrop={onDrop}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onPaneClick={() => setSelectedNodeId(null)}
              nodeTypes={nodeTypes}
              fitView
              colorMode={colorMode}
            >
              <Background />
              <Controls />
              <MiniMap nodeColor={() => 'var(--accent-soft)'} />
            </ReactFlow>
          </div>

          {/* Config drawer */}
          {selectedNode && (
            <div className="wa-config-drawer">
              <div className="wa-config-drawer-header">
                <span className="wa-config-drawer-title">
                  {NODE_DEFS[selectedNode.data.nodeType]?.label ?? selectedNode.data.nodeType}
                </span>
                <button className="wa-modal-close" onClick={() => setSelectedNodeId(null)}>
                  <X size={14} />
                </button>
              </div>
              <div className="wa-config-body">
                <ConfigFields
                  nodeType={selectedNode.data.nodeType}
                  config={selectedNode.data.config}
                  onChange={updateNodeConfig}
                />
              </div>
            </div>
          )}
        </div>

        {/* Issues panel */}
        {issues !== null && (
          <div className="wa-issues-panel">
            <div className="wa-issues-header">
              {issues.length === 0
                ? <><CheckCircle2 size={12} style={{ color: 'var(--success)', marginRight: 4 }} /> No issues</>
                : <><AlertCircle size={12} style={{ color: 'var(--danger)', marginRight: 4 }} /> {issues.length} issue{issues.length !== 1 ? 's' : ''}</>}
              <button
                style={{ float: 'right', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '0 4px' }}
                onClick={() => setIssues(null)}
              >
                <X size={12} />
              </button>
            </div>
            {issues.map((issue, i) => (
              <div key={i} className="wa-issue-row">
                <AlertCircle size={12} style={{ color: 'var(--danger)', flexShrink: 0, marginTop: 1 }} />
                <span style={{ flex: 1 }}>
                  <strong>{issue.check}</strong>{issue.node_id ? ` (${issue.node_id})` : ''}: {issue.message}
                </span>
                {issue.node_id && (
                  <button className="wa-issue-jump" onClick={() => jumpToNode(issue.node_id)}>
                    Jump
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Wrapper providing ReactFlowProvider ───────────────────────────────── */
export default function WhatsAppFlowEditor() {
  const { id } = useParams();
  return (
    <ReactFlowProvider>
      <FlowEditorInner flowId={id} />
    </ReactFlowProvider>
  );
}
