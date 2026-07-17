import React, { useState, useEffect } from 'react';
import { PhoneCall, Users, ShieldCheck, Loader2, ArrowRightCircle, Target, Activity } from 'lucide-react';
import api from '../../../utils/api';
import './CRMKnowledge.css';

const CRMKnowledge = ({ entityType = 'GST_REGISTRATION' }) => {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [stages, setStages] = useState([]);
    const [uiMappings, setUiMappings] = useState(null);

    const fetchCRMData = async () => {
        setLoading(true);
        setError(null);
        try {
            const apiBase = '/api/v1/crm/leads';
            const [stagesRes, mappingsRes] = await Promise.all([
                api.get(`${apiBase}/stages`, { params: { entity_type: entityType } }),
                api.get(`${apiBase}/ui-mappings`, { params: { entity_type: entityType } })
            ]);

            setStages(stagesRes.data?.stages || []);
            setUiMappings(mappingsRes.data || null);
        } catch (err) {
            console.error("Error fetching CRM knowledge data:", err);
            setError("Failed to fetch CRM knowledge data.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchCRMData();
    }, [entityType]);

    if (loading) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '300px', gap: '20px' }}>
                <Loader2 className="spinner" size={40} strokeWidth={1.5} style={{ color: 'var(--crm-blue)' }} />
                <p style={{ color: 'var(--text-muted)', fontSize: '15px', fontWeight: '500' }}>Loading CRM Data...</p>
            </div>
        );
    }

    if (error) return (
        <div style={{ padding: '40px', textAlign: 'center', background: 'rgba(var(--danger-rgb), 0.05)', borderRadius: '20px', border: '1px solid rgba(var(--danger-rgb), 0.1)' }}>
            <p style={{ color: 'var(--danger)', marginBottom: '20px' }}>{error}</p>
            <button onClick={fetchCRMData} className="btn-retry" style={{ background: 'var(--danger)', color: 'var(--text-primary)', border: 'none', padding: '10px 24px', borderRadius: '10px', fontWeight: '600', cursor: 'pointer' }}>Retry Sync</button>
        </div>
    );

    const getStagesForPitch = (pitchCode) => {
        if (!uiMappings?.stage_to_pitch || !stages) return [];
        
        const targetPitch = pitchCode.toUpperCase();
        const pitchMappings = uiMappings.stage_to_pitch
            .filter(m => m.pitch_type_code.toUpperCase() === targetPitch);

        return pitchMappings.map(m => {
            const masterStage = stages.find(s => 
                s.code.toUpperCase() === m.stage.toUpperCase() || 
                s.name.toUpperCase() === m.stage.toUpperCase()
            );
            return {
                id: masterStage?.id || '?',
                code: masterStage?.code || m.stage,
                name: masterStage?.name || m.stage
            };
        });
    };

    const getStatusesForPitch = (pitchCode) => {
        if (!uiMappings?.pitch_to_statuses) return [];
        const targetPitch = pitchCode.toUpperCase();
        return uiMappings.pitch_to_statuses[targetPitch] || [];
    };

    const firstPitchStagesData = getStagesForPitch('FIRST_PITCH_CALL');
    const finalPitchStagesData = getStagesForPitch('FINAL_PITCH_CALL');

    const firstPitchStatuses = getStatusesForPitch('FIRST_PITCH_CALL');
    const finalPitchStatuses = getStatusesForPitch('FINAL_PITCH_CALL');

    const callTypes = uiMappings ? [...new Set(uiMappings.stage_to_pitch.map(m => m.pitch_type_code))] : [];
    const allStatuses = uiMappings ? Object.values(uiMappings.pitch_to_statuses).flat().map(s => s.call_status_code) : [];
    const uniqueStatuses = [...new Set(allStatuses)];

    return (
        <div className="crm-knowledge-container">
            
            {/* 1. CRM Lead Stages Table */}
            <section className="crm-knowledge-section">
                <div className="crm-section-header">
                    <div className="crm-header-icon" style={{ borderColor: 'rgba(var(--warning-rgb), 0.3)', background: 'rgba(var(--warning-rgb), 0.1)', color: 'var(--crm-amber)' }}>
                        <Target size={22} />
                    </div>
                    <div>
                        <h2>CRM Lead Stages</h2>
                        <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>List of lead pipeline stages.</p>
                    </div>
                </div>
                <div className="table-wrapper">
                    <table className="knowledge-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Code</th>
                                <th>Name</th>
                            </tr>
                        </thead>
                        <tbody>
                            {stages.map((s) => (
                                <tr key={s.id}>
                                    <td><span className="crm-id-badge">{s.id}</span></td>
                                    <td><span className="crm-code-text">{s.code}</span></td>
                                    <td className="crm-name-text">{s.name}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </section>
            
            {/* 1.5. Pitch Call Allowed Statuses - Side by Side */}
            <div className="crm-double-section-wrapper">
                <section className="crm-knowledge-section" style={{ flex: 1 }}>
                    <div className="crm-section-header">
                        <div className="crm-header-icon" style={{ borderColor: 'rgba(var(--info-rgb), 0.3)', background: 'rgba(var(--info-rgb), 0.1)', color: 'var(--crm-blue)' }}>
                            <PhoneCall size={20} />
                        </div>
                        <div>
                            <h2>First Pitch Call Statuses</h2>
                            <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: 'var(--text-muted)' }}>Available outcomes for first pitch.</p>
                        </div>
                    </div>
                    
                    <div className="status-outcome-container">
                        {firstPitchStatuses.map((s, idx) => (
                            <span key={idx} className="status-outcome-pill">
                                {s.call_status_code}
                            </span>
                        ))}
                        {firstPitchStatuses.length === 0 && (
                            <p style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No statuses mapped.</p>
                        )}
                    </div>
                </section>

                <section className="crm-knowledge-section" style={{ flex: 1 }}>
                    <div className="crm-section-header">
                        <div className="crm-header-icon" style={{ borderColor: 'rgba(var(--accent-rgb), 0.3)', background: 'rgba(var(--accent-rgb), 0.1)', color: 'var(--accent)' }}>
                            <Activity size={20} />
                        </div>
                        <div>
                            <h2>Final Pitch Call Statuses</h2>
                            <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: 'var(--text-muted)' }}>Available outcomes for final pitch.</p>
                        </div>
                    </div>

                    <div className="status-outcome-container">
                        {finalPitchStatuses.map((s, idx) => (
                            <span key={idx} className="status-outcome-pill">
                                {s.call_status_code}
                            </span>
                        ))}
                        {finalPitchStatuses.length === 0 && (
                            <p style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No statuses mapped.</p>
                        )}
                    </div>
                </section>
            </div>

            {/* 2. CRM Communication Channels */}
            <section className="crm-knowledge-section">
                <div className="crm-section-header">
                    <div className="crm-header-icon">
                        <PhoneCall size={22} />
                    </div>
                    <div>
                        <h2>CRM Call Types & Statuses</h2>
                        <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>Configuration for calls and their outcome statuses.</p>
                    </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div className="config-list-item">
                        <div className="config-label">
                            <Activity size={14} style={{ marginRight: '8px' }} /> Call Types
                        </div>
                        <div className="config-values">
                            {callTypes.map((type, idx) => (
                                <div key={idx} className="mapping-action-chip">
                                    {type.replace(/_/g, ' ')}
                                </div>
                            ))}
                        </div>
                    </div>
                    <div className="config-list-item" style={{ borderLeft: '4px solid var(--accent)' }}>
                        <div className="config-label" style={{ color: 'var(--accent)' }}>
                            <ArrowRightCircle size={14} style={{ marginRight: '8px' }} /> Call Statuses
                        </div>
                        <div className="config-values">
                            {uniqueStatuses.map((status, idx) => (
                                <span key={idx} className="status-outcome-pill">
                                    {status.replace(/_/g, ' ')}
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
            </section>

            {/* 3. CRM Workflow Mappings Table */}
            <section className="crm-knowledge-section">
                <div className="crm-section-header">
                    <div className="crm-header-icon" style={{ borderColor: 'rgba(var(--success-rgb), 0.3)', background: 'rgba(var(--success-rgb), 0.1)', color: 'var(--crm-emerald)' }}>
                        <ShieldCheck size={22} />
                    </div>
                    <div>
                        <h2>CRM Stage Status Mappings</h2>
                        <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>Mappings between stages, call types, and statuses.</p>
                    </div>
                </div>
                <div className="table-wrapper" style={{ overflowX: 'auto' }}>
                    <table className="knowledge-table">
                        <thead>
                            <tr>
                                <th>Stage</th>
                                <th>Call Type</th>
                                <th>Call Statuses</th>
                            </tr>
                        </thead>
                        <tbody>
                            {uiMappings?.stage_to_pitch.map((map, idx) => {
                                const statuses = uiMappings.pitch_to_statuses[map.pitch_type_code] || [];
                                return (
                                    <tr key={idx}>
                                        <td className="mapping-stage-name">{map.stage}</td>
                                        <td>
                                            <div className="mapping-action-chip">
                                                {map.pitch_type_code}
                                            </div>
                                        </td>
                                        <td>
                                            <div className="status-outcome-container">
                                                {statuses.map((s, sIdx) => (
                                                    <span key={sIdx} className="status-outcome-pill">
                                                        {s.call_status_code}
                                                    </span>
                                                ))}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    );
};

export default CRMKnowledge;
